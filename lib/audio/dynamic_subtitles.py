"""lib/audio/dynamic_subtitles.py — Dynamic karaoke-style subtitle overlay.

Steps:
  1. Parse SRT → phrase timings + text
  2. (Optional) Whisper-align audio → word-level timestamps within each phrase window
  3. Build ASS subtitle file with \\kf karaoke tags (yellow fill, current word)
  4. Burn ASS into video via ffmpeg
  5. Write word-level SRT as side output
"""

import json
import logging
import re
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

_SRT_TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


# ---------------------------------------------------------------------------
# Step 1: SRT parsing
# ---------------------------------------------------------------------------

def _srt_to_sec(t: str) -> float:
    m = _SRT_TIME_RE.match(t.strip())
    if not m:
        raise ValueError(f"Cannot parse SRT time: {t!r}")
    h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
    ms = int(m.group(4).ljust(3, "0")[:3])
    return h * 3600 + mn * 60 + s + ms / 1000


def parse_srt(path: str) -> list[dict]:
    """Parse SRT file → list of {start, end, text} (times in seconds)."""
    raw = Path(path).read_text(encoding="utf-8-sig")
    entries = []
    for block in re.split(r"\n\s*\n", raw.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        m = re.match(r"(.+?)\s*-->\s*(.+)", lines[1])
        if not m:
            continue
        start = _srt_to_sec(m.group(1))
        end = _srt_to_sec(m.group(2))
        text = re.sub(r"<[^>]+>", "", " ".join(lines[2:])).strip()
        if text:
            entries.append({"start": start, "end": end, "text": text})
    return entries


# ---------------------------------------------------------------------------
# Step 2: Whisper word-level alignment
# ---------------------------------------------------------------------------

def _extract_audio_wav(video_path: str, wav_path: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000", wav_path],
        check=True, capture_output=True,
    )


def _whisper_word_timestamps(
    video_path: str,
    cache_path: str,
    language: str | None = None,
) -> list[dict]:
    """Run Whisper with word_timestamps=True. Returns flat list of {word, start, end}.

    Caches by video file size+mtime. Language mismatch between audio and SRT is fine:
    only the timing rhythm is used, not the Whisper text.
    """
    if WhisperModel is None:
        raise RuntimeError("faster-whisper not installed; run: pip install faster-whisper")

    import hashlib
    import os
    import time

    stat = os.stat(video_path)
    vid_hash = hashlib.md5(f"{stat.st_size}_{stat.st_mtime}".encode()).hexdigest()

    cache = Path(cache_path)
    if cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            if data.get("video_hash") == vid_hash:
                logger.info("Using cached word timestamps (%d words)", len(data["words"]))
                return data["words"]
        except (json.JSONDecodeError, KeyError):
            pass

    wav_path = str(cache.with_suffix(".tmp.wav"))
    logger.info("Extracting audio for Whisper alignment...")
    _extract_audio_wav(video_path, wav_path)

    logger.info("Running Whisper word alignment...")
    model = WhisperModel("medium", device="cpu", compute_type="int8")
    segments_raw, _ = model.transcribe(
        wav_path,
        beam_size=10,
        language=language,
        word_timestamps=True,
        vad_filter=True,
    )
    words = [
        {"word": w.word.strip(), "start": w.start, "end": w.end}
        for seg in segments_raw
        for w in (seg.words or [])
        if w.word.strip()
    ]

    try:
        Path(wav_path).unlink(missing_ok=True)
    except Exception:
        pass

    cache.write_text(
        json.dumps({"video_hash": vid_hash, "words": words, "timestamp": time.time()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Cached word timestamps → %s (%d words)", cache_path, len(words))
    return words


# ---------------------------------------------------------------------------
# Step 3: Assign per-word timings within each phrase
# ---------------------------------------------------------------------------

def _assign_word_timings(phrases: list[dict], all_words: list[dict]) -> list[dict]:
    """Distribute SRT phrase words across the phrase time window.

    Uses Whisper word beat-times as proportional rhythm weights when ≥2 are found
    in the phrase window. Falls back to even split otherwise.
    Works regardless of language mismatch between SRT text and audio.
    """
    result = []
    for phrase in phrases:
        t0, t1 = phrase["start"], phrase["end"]
        text_words = phrase["text"].split()
        n = len(text_words)
        span = max(t1 - t0, 0.001)

        # Allow small tolerance at phrase boundaries
        w_words = [w for w in all_words if w["start"] >= t0 - 0.1 and w["end"] <= t1 + 0.1]

        if len(w_words) >= 2:
            beats = [(w["start"] + w["end"]) / 2 for w in w_words]
            b_min, b_max = beats[0], beats[-1]
            b_span = max(b_max - b_min, 0.001)
            assigned = []
            for i, word in enumerate(text_words):
                # Interpolate word index → beat time → ratio in phrase
                beat_idx = i * (len(beats) - 1) / max(n - 1, 1)
                lo = int(beat_idx)
                hi = min(lo + 1, len(beats) - 1)
                frac = beat_idx - lo
                beat_t = beats[lo] * (1 - frac) + beats[hi] * frac
                ratio = (beat_t - b_min) / b_span
                w_start = t0 + ratio * span
                w_end = min(t0 + (ratio + 1 / n) * span, t1)
                assigned.append({"word": word, "start": w_start, "end": w_end})
        else:
            dur = span / max(n, 1)
            assigned = [
                {"word": w, "start": t0 + i * dur, "end": t0 + (i + 1) * dur}
                for i, w in enumerate(text_words)
            ]

        result.append({**phrase, "words": assigned})
    return result


# ---------------------------------------------------------------------------
# Step 4: Build ASS file
# ---------------------------------------------------------------------------

def _sec_to_ass(t: float) -> str:
    """Convert seconds → ASS timestamp H:MM:SS.cs"""
    cs = round(t * 100)
    h = cs // 360000; cs %= 360000
    m = cs // 6000;   cs %= 6000
    s = cs // 100;    cs %= 100
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def build_ass(
    phrases: list[dict],
    video_width: int = 1080,
    video_height: int = 1920,
    font_size: int = 68,
    margin_v: int = 340,
) -> str:
    """Build ASS subtitle content with \\kf karaoke fill tags.

    ASS color format: &HAABBGGRR
    SecondaryColour (upcoming words) = white  &H00FFFFFF
    PrimaryColour   (active word fill) = yellow &H0000FFFF
    """
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        f"PlayResX: {video_width}\n"
        f"PlayResY: {video_height}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Arial,{font_size},&H0000FFFF,&H00FFFFFF,&H00000000,&H80000000,"
        f"-1,0,0,0,100,100,1,0,1,3,2,2,40,40,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    )
    lines = [header]
    for phrase in phrases:
        parts = [
            f"{{\\kf{max(1, round((w['end'] - w['start']) * 100))}}}{w['word']}"
            for w in phrase.get("words", [])
        ]
        text = " ".join(parts) if parts else phrase["text"]
        lines.append(
            f"Dialogue: 0,{_sec_to_ass(phrase['start'])},{_sec_to_ass(phrase['end'])},"
            f"Default,,0,0,0,,{text}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 5: Word-level SRT output
# ---------------------------------------------------------------------------

def _sec_to_srt(t: float) -> str:
    """Convert seconds → SRT timestamp HH:MM:SS,mmm"""
    ms = round(t * 1000)
    h = ms // 3600000; ms %= 3600000
    m = ms // 60000;   ms %= 60000
    s = ms // 1000;    ms %= 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_word_srt(phrases: list[dict]) -> str:
    """Build SRT with one entry per word (for external player use)."""
    lines = []
    idx = 1
    for phrase in phrases:
        for w in phrase.get("words", []):
            lines.append(str(idx))
            lines.append(f"{_sec_to_srt(w['start'])} --> {_sec_to_srt(w['end'])}")
            lines.append(w["word"])
            lines.append("")
            idx += 1
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 6: Burn subtitles into video
# ---------------------------------------------------------------------------

def _probe_dimensions(video_path: str) -> tuple[int, int]:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", video_path],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        w, h = out.split(",")
        return int(w), int(h)
    except Exception:
        logger.warning("Could not probe video dimensions, defaulting to 1080x1920")
        return 1080, 1920


def burn_subtitles(video_path: str, ass_path: str, output_path: str) -> None:
    abs_ass = str(Path(ass_path).resolve())
    cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", f"ass={abs_ass}", "-c:a", "copy", output_path]
    logger.info("ffmpeg: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _probe_duration(video_path: str) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", video_path],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        return float(out)
    except Exception:
        logger.warning("Could not probe video duration, defaulting to 60s")
        return 60.0


def render_subtitle_overlay(
    ass_path: str,
    width: int,
    height: int,
    duration: float,
    output_path: str,
    fps: int = 30,
) -> None:
    """Render karaoke subtitles onto a transparent background — no source video baked in.

    Output codec is chosen by extension:
      .mov  → ProRes 4444 (yuva444p10le) — best Shotcut/Resolve compatibility
      .webm → VP9 (yuva420p)             — open format, slightly lossy alpha
    Import the resulting file into Shotcut as a track above your video clip.
    """
    abs_ass = str(Path(ass_path).resolve())
    out = Path(output_path)
    ext = out.suffix.lower()

    if ext == ".mp4":
        output_path = str(out.with_suffix(".mov"))
        logger.warning("MP4 does not support alpha — writing to %s instead", output_path)
        ext = ".mov"

    # Explicit RGBA zeroing before ass filter ensures non-subtitle pixels stay transparent.
    # Without format=rgba+geq, lavfi color source may output RGB (no alpha channel),
    # causing ass filter to composite onto opaque black.
    if ext == ".webm":
        pix_fmt = "yuva420p"
        vf = f"format=rgba,geq=r=0:g=0:b=0:a=0,ass={abs_ass},format={pix_fmt}"
        codec_args = ["-c:v", "libvpx-vp9", "-pix_fmt", pix_fmt, "-b:v", "0", "-crf", "18", "-an"]
    else:  # .mov — use qtrle (QuickTime RLE): lossless, argb, universally supported with alpha
        pix_fmt = "argb"
        vf = f"format=rgba,geq=r=0:g=0:b=0:a=0,ass={abs_ass},format={pix_fmt}"
        codec_args = ["-c:v", "qtrle", "-pix_fmt", pix_fmt, "-an"]

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=black@0.0:size={width}x{height}:rate={fps}",
        "-t", str(duration),
        "-vf", vf,
        *codec_args,
        output_path,
    ]
    logger.info("Rendering transparent subtitle overlay: %s", " ".join(cmd))
    subprocess.run(cmd, check=True)


# ---------------------------------------------------------------------------
# Transcribe video → SRT (for manual editing before dynamic-subtitles)
# ---------------------------------------------------------------------------

def run_transcribe_srt(
    video_path: str,
    output_path: str,
    transcription_cache: str = "transcription_cache.json",
    language: str | None = None,
) -> None:
    """Transcribe video with Whisper and write phrase-level SRT for manual editing."""
    from lib.audio.dubbing import transcribe_video

    logger.info("Transcribing %s...", video_path)
    segments, duration = transcribe_video(video_path, transcription_cache)
    logger.info("  %d segments, %.1fs total", len(segments), duration)

    lines = []
    for i, seg in enumerate(segments, 1):
        lines.append(str(i))
        lines.append(f"{_sec_to_srt(seg['start'])} --> {_sec_to_srt(seg['end'])}")
        lines.append(seg["original_text"])
        lines.append("")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    logger.info("SRT → %s (%d entries)", output_path, len(segments))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_dynamic_subtitles(
    video_path: str,
    srt_path: str,
    output_path: str,
    whisper_cache: str = "dynamic_subtitles_words.json",
    ass_output: str | None = None,
    word_srt_output: str | None = None,
    use_whisper: bool = True,
    whisper_language: str | None = None,
    font_size: int = 68,
    margin_v: int = 120,
    overlay_only: bool = False,
    overlay_fps: int = 30,
) -> None:
    """End-to-end: video + SRT → video with karaoke subtitle overlay (or transparent overlay).

    overlay_only=True: output is a transparent ProRes 4444 / VP9 file (no source video baked in).
    Import it as a track above your video in Shotcut/Resolve.
    """
    logger.info("Step 1: Parsing SRT %s...", srt_path)
    phrases = parse_srt(srt_path)
    logger.info("  %d phrases", len(phrases))

    all_words: list[dict] = []
    if use_whisper:
        logger.info("Step 2: Whisper word-level alignment...")
        try:
            all_words = _whisper_word_timestamps(video_path, whisper_cache, language=whisper_language)
            logger.info("  %d words", len(all_words))
        except Exception as exc:
            logger.warning("Whisper alignment failed (%s) — falling back to even split", exc)

    logger.info("Step 3: Assigning word timings...")
    phrases = _assign_word_timings(phrases, all_words)

    logger.info("Step 4: Building ASS file...")
    width, height = _probe_dimensions(video_path)
    ass_content = build_ass(phrases, width, height, font_size=font_size, margin_v=margin_v)
    ass_path = ass_output or str(Path(output_path).with_suffix(".ass"))
    Path(ass_path).write_text(ass_content, encoding="utf-8")
    logger.info("  ASS → %s", ass_path)

    word_srt_path = word_srt_output or str(Path(output_path).with_suffix(".words.srt"))
    Path(word_srt_path).write_text(build_word_srt(phrases), encoding="utf-8")
    logger.info("  Word SRT → %s", word_srt_path)

    if overlay_only:
        logger.info("Step 5: Rendering transparent subtitle overlay...")
        duration = _probe_duration(video_path)
        render_subtitle_overlay(ass_path, width, height, duration, output_path, fps=overlay_fps)
    else:
        logger.info("Step 5: Burning subtitles...")
        burn_subtitles(video_path, ass_path, output_path)
    logger.info("Done → %s", output_path)
