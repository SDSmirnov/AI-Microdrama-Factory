"""
lib/audio/ducking.py — Auto-duck original video audio during dubbed speech.

Detects speech segments in a dubbed MP3, then lowers the original MP4
audio wherever the dub plays.
"""

import sys
from pathlib import Path

from pydub import AudioSegment
from pydub.effects import normalize


def detect_speech_segments(
    audio: AudioSegment,
    threshold_db: float = -40,
    min_silence_ms: int = 300,
) -> list[tuple[int, int]]:
    """Return list of (start_ms, end_ms) speech segments from audio."""
    chunks = [audio[i:i + 10] for i in range(0, len(audio), 10)]
    volume_levels = [chunk.dBFS for chunk in chunks]

    raw_segments: list[tuple[int, int]] = []
    in_speech = False
    speech_start = 0

    for i, level in enumerate(volume_levels):
        time_ms = i * 10
        if level > threshold_db and not in_speech:
            in_speech = True
            speech_start = time_ms
        elif level <= threshold_db and in_speech:
            raw_segments.append((speech_start, time_ms))
            in_speech = False

    if in_speech:
        raw_segments.append((speech_start, len(audio)))

    if not raw_segments:
        return []

    merged: list[tuple[int, int]] = []
    curr_start, curr_end = raw_segments[0]
    for next_start, next_end in raw_segments[1:]:
        if next_start - curr_end < min_silence_ms:
            curr_end = next_end
        else:
            merged.append((curr_start, curr_end))
            curr_start, curr_end = next_start, next_end
    merged.append((curr_start, curr_end))

    return merged


def apply_ducking(
    original: AudioSegment,
    speech_segments: list[tuple[int, int]],
    duck_db: float = -15,
    fade_ms: int = 50,
    padding_ms: int = 100,
) -> AudioSegment:
    """Apply volume ducking to `original` at each (start_ms, end_ms) region."""
    result = original
    for start_ms, end_ms in speech_segments:
        duck_start = max(0, start_ms - padding_ms)
        duck_end = min(len(result), end_ms + padding_ms)

        before = result[:duck_start]
        segment = result[duck_start:duck_end] + duck_db
        after = result[duck_end:]

        if fade_ms > 0:
            fade_len = min(fade_ms, len(segment) // 2)
            segment = segment.fade_in(fade_len).fade_out(fade_len)

        result = before + segment + after
    return result


def run_ducking(
    video_path: str,
    dubbed_path: str,
    output_path: str,
    duck_db: float = -15,
    threshold_db: float = -40,
    min_silence_ms: int = 300,
    fade_ms: int = 50,
    padding_ms: int = 100,
    do_normalize: bool = False,
) -> None:
    """
    Full ducking pipeline:
      1. Extract original audio from MP4
      2. Load dubbed MP3
      3. Detect speech in dub
      4. Duck original audio
      5. Export result
    """
    print(f"Extracting audio from video: {video_path}")
    try:
        original = AudioSegment.from_file(video_path, format="mp4")
    except Exception as e:
        print(f"Error reading video: {e}")
        sys.exit(1)

    print(f"Loading dubbed audio: {dubbed_path}")
    try:
        dubbed = AudioSegment.from_mp3(dubbed_path)
    except Exception as e:
        print(f"Error reading dubbed audio: {e}")
        sys.exit(1)

    diff_ms = abs(len(original) - len(dubbed))
    if diff_ms > 1000:
        print(f"Warning: {diff_ms / 1000:.2f}s duration mismatch — files may be out of sync")

    speech = detect_speech_segments(dubbed, threshold_db=threshold_db, min_silence_ms=min_silence_ms)
    if not speech:
        print("No speech detected. Try a lower --threshold value.")
        sys.exit(1)

    print(f"Found {len(speech)} speech segments")
    ducked = apply_ducking(original, speech, duck_db=duck_db, fade_ms=fade_ms, padding_ms=padding_ms)

    if do_normalize:
        ducked = normalize(ducked)

    ducked.export(output_path, format="mp3", bitrate="192k")
    print(f"Done: {output_path}  ({len(ducked) / 1000:.2f}s)")
