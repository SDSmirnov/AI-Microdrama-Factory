"""
lib/audio/dubbing.py — Smart AI dubbing pipeline.

Steps:
  1. Transcribe original video with Whisper (cached)
  2. Translate + emotion-annotate segments with BaseLLM.make_json
  3. Generate TTS per segment with BaseLLM.make_speech (cached)
  4. Assemble with overlap-resolution into a final audio track
"""

import hashlib
import json
import os
import time
from pathlib import Path

from pydub import AudioSegment

from lib.llm.base import BaseLLM
from lib.llm.gemini import GeminiLLM
from lib.audio.tts import VOICE_MAP, generate_speech

try:
    from moviepy.editor import VideoFileClip
except ImportError:
    VideoFileClip = None

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

TARGET_WPM = 130          # Russian speech rate
SPEED_TOLERANCE = 1.35    # max speedup factor
MIN_GAP_MS = 50           # min gap between dub segments


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_llm(api_key: str | None = None) -> BaseLLM:
    key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("IMG_AI_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY not set")
    return GeminiLLM(api_key=key, text_model="gemini-2.5-pro")


def _file_hash(filepath: str) -> str:
    stat = os.stat(filepath)
    return hashlib.md5(f"{stat.st_size}_{stat.st_mtime}".encode()).hexdigest()


def _max_words(duration_sec: float) -> int:
    return int((duration_sec * TARGET_WPM) / 60)


# ---------------------------------------------------------------------------
# Step 1: Transcription (Whisper, cached)
# ---------------------------------------------------------------------------

def transcribe_video(
    video_path: str,
    cache_path: str = "transcription_cache.json",
    temp_wav: str = "temp_source.wav",
) -> tuple[list[dict], float]:
    """Return (segments, total_duration_sec). Caches result in cache_path."""
    if VideoFileClip is None:
        raise RuntimeError("moviepy not installed; run: pip install moviepy")

    video_hash = _file_hash(video_path)

    if os.path.exists(cache_path):
        try:
            cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
            if cache.get("video_hash") == video_hash:
                print(f"  Using cached transcription ({len(cache['segments'])} segments)")
                return cache["segments"], cache["total_duration"]
        except (json.JSONDecodeError, KeyError):
            pass

    print("  Extracting audio from video...")
    clip = VideoFileClip(video_path)
    total_duration = clip.duration
    if not os.path.exists(temp_wav):
        clip.audio.write_audiofile(temp_wav, logger=None)
    clip.close()

    print("  Running Whisper transcription...")
    if WhisperModel is None:
        raise RuntimeError("faster-whisper not installed; run: pip install faster-whisper")
    model = WhisperModel("medium", device="cpu", compute_type="int8")
    segments_raw, _ = model.transcribe(
        temp_wav,
        beam_size=5,
        language="en",
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )
    segments = [
        {"start": s.start, "end": s.end, "original_text": s.text.strip()}
        for s in segments_raw
    ]

    cache = {
        "video_hash": video_hash,
        "video_path": video_path,
        "total_duration": total_duration,
        "segments": segments,
        "timestamp": time.time(),
    }
    Path(cache_path).write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  Transcription cached → {cache_path}")
    return segments, total_duration


# ---------------------------------------------------------------------------
# Step 2: Translation + emotion tagging
# ---------------------------------------------------------------------------

def analyze_and_translate(
    segments: list[dict],
    context: str = "",
    llm: BaseLLM | None = None,
    api_key: str | None = None,
) -> list[dict]:
    """Translate segments to Russian, add tone/voice_type/speaker_id."""
    if llm is None:
        llm = _default_llm(api_key)

    input_data = [
        {
            "id": i,
            "text": s["original_text"],
            "duration": round(s["end"] - s["start"], 2),
            "max_words": _max_words(s["end"] - s["start"]),
        }
        for i, s in enumerate(segments)
    ]

    prompt = f"""You are a professional Russian dubbing director.

For EACH sentence:
1. Translate to natural Russian.
2. Keep translation within max_words (Russian rate: {TARGET_WPM} wpm).
3. Detect Emotion/Tone.
4. Choose Voice Type from: male_hero, male_deep, male_calm, female_hero, female_soft, female_strict, narrator.
5. Assign speaker_id for consistency (e.g. "hero", "narrator").

Output RAW JSON list with fields: id, ru_text, word_count, tone, voice_type, speaker_id.
DO NOT use Markdown.

<CONTEXT>{context}</CONTEXT>

DATA: {json.dumps(input_data, ensure_ascii=False)}"""

    try:
        result = llm.make_json(prompt)
        trans_map = {item["id"]: item for item in result}
    except Exception:
        print("Warning: failed to parse translation response")
        return segments

    enriched = []
    for i, seg in enumerate(segments):
        item = trans_map.get(i, {})
        seg = seg.copy()
        ru = item.get("ru_text", seg["original_text"])
        seg.update(
            ru_text=ru,
            word_count=len(ru.split()),
            tone=item.get("tone", "neutral"),
            voice_type=item.get("voice_type", "narrator"),
            speaker_id=item.get("speaker_id"),
        )
        enriched.append(seg)
    return enriched


# ---------------------------------------------------------------------------
# Step 3: TTS generation
# ---------------------------------------------------------------------------

def generate_audio_segment(
    text: str,
    voice_key: str,
    tone: str,
    output_path: Path,
    llm: BaseLLM | None = None,
    api_key: str | None = None,
) -> bool:
    """Generate one dubbed audio segment. Uses file-cache if output_path exists."""
    if output_path.exists():
        return True
    if llm is None:
        llm = _default_llm(api_key)
    return generate_speech(text, voice_key, tone, output_path, llm=llm)


# ---------------------------------------------------------------------------
# Step 4: Overlap resolution + assembly
# ---------------------------------------------------------------------------

def _resolve_overlaps(segments: list[dict]) -> list[dict]:
    """Trim segment ends to prevent dub overlap; prioritize next segment's start."""
    if not segments:
        return []

    resolved = [segments[0].copy()]
    for i in range(1, len(segments)):
        cur = segments[i].copy()
        prev = resolved[-1]
        prev_end = prev.get("adjusted_end", prev["end"])
        cur_start = cur["start"]

        gap_threshold = cur_start - (MIN_GAP_MS / 1000.0)
        if prev_end > gap_threshold:
            new_prev_end = cur_start - (MIN_GAP_MS / 1000.0)
            prev_start = prev.get("adjusted_start", prev["start"])
            if new_prev_end - prev_start > 0.5:
                prev["adjusted_end"] = round(new_prev_end, 3)
                cur["adjusted_start"] = cur_start
            else:
                cur["adjusted_start"] = round(prev_end + (MIN_GAP_MS / 1000.0), 3)
        else:
            cur["adjusted_start"] = cur_start

        cur["adjusted_end"] = cur["end"]
        resolved.append(cur)
    return resolved


def assemble_audio(
    segments: list[dict],
    total_duration: float,
    segments_dir: Path,
    llm: BaseLLM | None = None,
    api_key: str | None = None,
) -> AudioSegment:
    """Generate TTS for each segment and overlay onto a silent track."""
    if llm is None:
        llm = _default_llm(api_key)

    segments = _resolve_overlaps(segments)
    track = AudioSegment.silent(duration=int(total_duration * 1000))
    segments_dir.mkdir(exist_ok=True)

    for i, seg in enumerate(segments):
        text = seg.get("ru_text", "")
        if not text or len(text) < 2:
            continue

        out_file = segments_dir / f"seg_{i}_{seg['voice_type']}.wav"
        print(f"  [{i}] [{seg['voice_type']}] [{seg['tone']}] {text[:50]}...")
        ok = generate_audio_segment(text, seg["voice_type"], seg["tone"], out_file, llm=llm)
        if not ok:
            continue

        audio = AudioSegment.from_wav(str(out_file))
        seg_start = seg.get("adjusted_start", seg["start"])
        seg_end = seg.get("adjusted_end", seg["end"])
        slot_ms = (seg_end - seg_start) * 1000
        actual_ms = len(audio)

        if actual_ms > slot_ms:
            factor = min(actual_ms / slot_ms, SPEED_TOLERANCE)
            if factor > 1.05:
                audio = audio.speedup(playback_speed=factor)

        track = track.overlay(audio, position=int(seg_start * 1000))

    return track


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_dubbing(
    video_path: str,
    output_path: str,
    context_path: str = "",
    plan_cache: str = "dubbing_plan.json",
    transcription_cache: str = "transcription_cache.json",
    temp_wav: str = "temp_source.wav",
    segments_dir: str = "temp_segments",
    llm: BaseLLM | None = None,
    api_key: str | None = None,
) -> None:
    """End-to-end dubbing: transcribe → translate → TTS → assemble → export."""
    if llm is None:
        llm = _default_llm(api_key)

    context = Path(context_path).read_text(encoding="utf-8") if context_path else ""

    print("Step 1: Transcribing...")
    segments, duration = transcribe_video(video_path, transcription_cache, temp_wav)

    plan_file = Path(plan_cache)
    if plan_file.exists():
        print(f"Step 2: Loading existing plan from {plan_cache}")
        rich_segments = json.loads(plan_file.read_text(encoding="utf-8"))
    else:
        print("Step 2: Translating + analyzing emotions...")
        rich_segments = analyze_and_translate(segments, context, llm=llm)
        plan_file.write_text(json.dumps(rich_segments, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Plan saved → {plan_cache}")

    print("Step 3-4: Generating TTS + assembling...")
    final_audio = assemble_audio(rich_segments, duration, Path(segments_dir), llm=llm)

    final_audio.export(output_path, format="mp3")
    print(f"\nDone: {output_path}")
    print(f"  Transcription cache: {transcription_cache}")
    print(f"  Dubbing plan:        {plan_cache}")
