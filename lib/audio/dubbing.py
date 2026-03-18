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
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

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
MAX_INTRA_GAP_SEC = 1.5   # word gap threshold to force-split a Whisper segment


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


def _split_on_gaps(segments: list[dict], max_gap_sec: float = MAX_INTRA_GAP_SEC) -> list[dict]:
    """Split Whisper segments where the inter-word gap exceeds max_gap_sec.

    A pause that long inside a single segment almost certainly means Whisper
    stitched together two distinct utterances (different speakers or takes).
    Word text tokens from faster-whisper carry a leading space, so joining
    them with "" and stripping produces the correct phrase.
    """
    result = []
    for seg in segments:
        words = seg.get("words", [])
        if len(words) <= 1:
            result.append(seg)
            continue

        # collect indices where a new chunk starts
        cut_at = [0]
        for i in range(len(words) - 1):
            if words[i + 1]["start"] - words[i]["end"] >= max_gap_sec:
                cut_at.append(i + 1)
        cut_at.append(len(words))

        if len(cut_at) == 2:          # no cuts found
            result.append(seg)
            continue

        for j in range(len(cut_at) - 1):
            chunk = words[cut_at[j]: cut_at[j + 1]]
            result.append({
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
                "original_text": "".join(w["word"] for w in chunk).strip(),
                "words": chunk,
            })

    return result


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
                logger.info("Using cached transcription (%d segments)", len(cache["segments"]))
                return cache["segments"], cache["total_duration"]
        except (json.JSONDecodeError, KeyError):
            pass

    logger.info("Extracting audio from video...")
    clip = VideoFileClip(video_path)
    total_duration = clip.duration
    if not os.path.exists(temp_wav):
        clip.audio.write_audiofile(temp_wav, logger=None)
    clip.close()

    logger.info("Running Whisper transcription...")
    if WhisperModel is None:
        raise RuntimeError("faster-whisper not installed; run: pip install faster-whisper")
    model = WhisperModel("medium", device="cpu", compute_type="int8")
    segments_raw, _ = model.transcribe(
        temp_wav,
        beam_size=10,
        language="ru",
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=100),
    )
    segments = [
        {
            "start": s.start,
            "end": s.end,
            "original_text": s.text.strip(),
            "words": [
                {"word": w.word, "start": w.start, "end": w.end}
                for w in (s.words or [])
            ],
        }
        for s in segments_raw
    ]
    segments = _split_on_gaps(segments)
    logger.info("After gap-split: %d segments", len(segments))

    cache = {
        "video_hash": video_hash,
        "video_path": video_path,
        "total_duration": total_duration,
        "segments": segments,
        "timestamp": time.time(),
    }
    Path(cache_path).write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Transcription cached → %s", cache_path)
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
    """Translate segments to Russian, add tone/voice_type/speaker_id.

    If a Whisper segment contains speech from multiple speakers (detected via
    screenplay context), the LLM splits it into sub-segments using word-level
    timestamps. Output list may be longer than input.
    """
    if llm is None:
        llm = _default_llm(api_key)

    # Send word list as indexed tokens so LLM returns word index ranges,
    # not timestamps (LLM cannot reliably copy float values).
    input_data = [
        {
            "id": i,
            "text": s["original_text"],
            "duration": round(s["end"] - s["start"], 2),
            "max_words": _max_words(s["end"] - s["start"]),
            "words": [
                {"idx": j, "word": w["word"]}
                for j, w in enumerate(s.get("words", []))
            ],
        }
        for i, s in enumerate(segments)
    ]

    prompt = f"""You are a professional Russian dubbing director.

For EACH segment, check the screenplay context and determine how many speakers are present.
If a segment contains speech from multiple speakers, split it at word boundaries.

Rules:
1. Translate each part to natural Russian.
2. Keep translation within max_words per part (Russian rate: {TARGET_WPM} wpm).
3. Detect Emotion/Tone per part.
4. Choose Voice Type from: male_hero, male_deep, male_calm, female_hero, female_soft, female_strict, narrator.
5. Assign speaker_id for consistency (e.g. "igor", "ruslan_vo").
6. For each split specify word_start_idx and word_end_idx (inclusive) from the "words" list.
   Timestamps will be derived from these indices in code — do NOT include start/end floats.

Output RAW JSON list — one entry per segment:
{{
  "id": <original segment id>,
  "splits": [
    {{
      "word_start_idx": <int>,
      "word_end_idx": <int, inclusive>,
      "ru_text": "<Russian translation>",
      "tone": "<tone>",
      "voice_type": "<voice type>",
      "speaker_id": "<speaker id>"
    }}
  ]
}}

Single-speaker segments have exactly one split covering all words. DO NOT use Markdown.

<CONTEXT>{context}</CONTEXT>

DATA: {json.dumps(input_data, ensure_ascii=False)}"""

    try:
        result = llm.make_json(prompt)
        splits_map = {item["id"]: item["splits"] for item in result}
    except Exception:
        logger.warning("Failed to parse translation response", exc_info=True)
        return segments

    enriched = []
    for i, seg in enumerate(segments):
        words = seg.get("words", [])
        splits = splits_map.get(i) or []
        if not splits:
            enriched.append({
                **seg,
                "ru_text": seg["original_text"],
                "word_count": len(seg["original_text"].split()),
                "tone": "neutral",
                "voice_type": "narrator",
                "speaker_id": None,
            })
            continue

        for split in splits:
            w0 = split.get("word_start_idx", 0)
            w1 = split.get("word_end_idx", len(words) - 1)
            if words:
                w0 = max(0, min(w0, len(words) - 1))
                w1 = max(w0, min(w1, len(words) - 1))
                start = words[w0]["start"]
                end = words[w1]["end"]
                original_text = "".join(words[j]["word"] for j in range(w0, w1 + 1)).strip()
            else:
                start, end = seg["start"], seg["end"]
                original_text = seg["original_text"]

            if end <= start:
                logger.warning("Skipping split with invalid range [%s, %s] in segment %d", start, end, i)
                continue
            ru = split.get("ru_text") or original_text
            enriched.append({
                "start": start,
                "end": end,
                "original_text": original_text,
                "ru_text": ru,
                "word_count": len(ru.split()),
                "tone": split.get("tone", "neutral"),
                "voice_type": split.get("voice_type", "narrator"),
                "speaker_id": split.get("speaker_id"),
            })

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
        logger.info("[%d] [%s] [%s] %s...", i, seg["voice_type"], seg["tone"], text[:50])
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

    logger.info("Step 1: Transcribing...")
    segments, duration = transcribe_video(video_path, transcription_cache, temp_wav)

    plan_file = Path(plan_cache)
    if plan_file.exists():
        logger.info("Step 2: Loading existing plan from %s", plan_cache)
        rich_segments = json.loads(plan_file.read_text(encoding="utf-8"))
    else:
        logger.info("Step 2: Translating + analyzing emotions...")
        rich_segments = analyze_and_translate(segments, context, llm=llm)
        plan_file.write_text(json.dumps(rich_segments, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Plan saved → %s", plan_cache)

    logger.info("Step 3-4: Generating TTS + assembling...")
    final_audio = assemble_audio(rich_segments, duration, Path(segments_dir), llm=llm)

    final_audio.export(output_path, format="mp3")
    logger.info("Done: %s (transcription cache: %s, dubbing plan: %s)", output_path, transcription_cache, plan_cache)
