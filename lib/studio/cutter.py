"""
lib/studio/cutter.py — AI-powered video clip trimmer.

Uses a vision-capable BaseLLM backend to analyze each generated animation
clip against its panel metadata, determine trim points, then cut with ffmpeg.
"""

import json
import logging
import subprocess
from pathlib import Path

from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "start_time":    {"type": "number",  "description": "Start trim point in seconds"},
        "end_time":      {"type": "number",  "description": "End trim point in seconds"},
        "is_usable":     {"type": "boolean", "description": "Whether the clip is high quality and matches script"},
        "edit_notes":    {"type": "string",  "description": "Detailed explanation of the cut and sync points"},
        "fidelity_score":{"type": "integer", "description": "How well the video matches metadata (1-10)"},
    },
    "required": ["start_time", "end_time", "is_usable", "edit_notes", "fidelity_score"],
}

_PROMPT_TEMPLATE = """\
You are a lead editor for a sci-fi movie. Analyze this AI video clip against the technical script.

### SCRIPT METADATA:
- VISUAL START:        {visual_start}
- VISUAL END:          {visual_end}
- MOTION:              {motion_prompt}
- LIGHTING/CAMERA:     {lights_and_camera}
- SOUND/DIALOGUE:      {dialogue}
- SOUND DESIGN:        {sound_design}
- TRANSITION TO NEXT:  {transition_to_next}

### YOUR GOALS:
1. Synchronize 'start_time' with the core action (impact, flash, or movement).
2. Ensure the lighting changes described are captured.
3. Cut the video BEFORE the AI begins to 'hallucinate' (limbs melting, background warping).
4. If the video is a static image or misses the main object, set 'is_usable' to false.
5. For transition_to_next=match_cut: set end_time so the final frame best matches the
   shape or motion described in the next panel's visual_start. Note the match point in edit_notes.
6. For transition_to_next=jump_cut: trim aggressively — keep only the peak action moment.
   Prefer a shorter, punchier cut even if it loses context.
7. For transition_to_next=smash_cut: end on the sharpest contrast frame (silence→noise or
   stillness→chaos). Note the contrast in edit_notes.
8. For transition_to_next=j_cut: set end_time to include the final 1–2s where the next
   scene's audio should begin bleeding in. Note the j_cut point in edit_notes.
9. Respect sound_design cues when choosing start_time/end_time — align cuts to sonic events.

Provide technical edit notes in 'edit_notes'.
"""


def analyze_clip(llm: BaseLLM, video_path: Path, panel: dict) -> dict | None:
    """Analyze clip against panel metadata and return trim decision."""
    prompt = _PROMPT_TEMPLATE.format(
        visual_start=panel.get("visual_start", ""),
        visual_end=panel.get("visual_end", ""),
        motion_prompt=panel.get("motion_prompt", ""),
        lights_and_camera=panel.get("lights_and_camera", ""),
        dialogue=panel.get("dialogue", ""),
        sound_design=panel.get("sound_design", ""),
        transition_to_next=panel.get("transition_to_next", "hard_cut"),
    )

    try:
        result = llm.analyze_video(video=video_path, prompt=prompt, schema=ANALYSIS_SCHEMA)
    except NotImplementedError:
        raise
    except Exception as e:
        logger.error(f"❌ Video analysis failed for {video_path.name}: {e}")
        return None

    if not result:
        return None

    if isinstance(result, dict) and "text" in result:
        try:
            return json.loads(result["text"])
        except Exception:
            logger.error(f"❌ Could not parse video analysis text for {video_path.name}")
            return None
    return result


def ffmpeg_cut(input_path: Path, output_path: Path, start: float, end: float) -> None:
    """Trim video with ffmpeg (re-encode, high quality)."""
    duration = max(0.1, end - start)
    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", str(input_path),
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True, timeout=300)
    except FileNotFoundError as e:
        raise RuntimeError("ffmpeg not found on PATH") from e
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode(errors="replace")[:300]
        raise RuntimeError(
            f"ffmpeg failed ({e.returncode}) for {input_path.name}: {stderr}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"ffmpeg timed out for {input_path.name}") from e


def run_autocut(
    llm: BaseLLM,
    json_path: str,
    clips_dir: str,
    out_dir: str,
    min_fidelity: int = 3,
    edge_trim: float = 0.0,
) -> None:
    """
    Iterate scenes/panels from json_path, find matching clips in clips_dir,
    AI-analyze each, then write trimmed clips + JSON reports to out_dir.

    edge_trim (Item 10a): when > 0, the cut window shrinks by this many
    seconds on both head and tail after the gates pass (clip edges drift).
    Negative values are rejected at parse time (--edge-trim).
    """
    clips = Path(clips_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    failures: list[str] = []
    required = ("is_usable", "fidelity_score", "start_time", "end_time")

    for scene in data.get("scenes", []):
        s_id = scene["scene_id"]
        for panel in scene.get("panels", []):
            p_idx = panel["panel_index"]
            pattern = f"clip_{s_id:02d}_{p_idx:03d}.mp4"
            src = clips / pattern
            if not src.exists():
                logger.warning(f"Not found: {pattern} — skipping")
                continue

            logger.info(f"Analyzing {pattern}...")
            try:
                analysis = analyze_clip(llm, src, panel)
            except NotImplementedError as e:
                raise RuntimeError(f"Selected backend does not support video analysis: {e}") from e
            if not analysis:
                continue

            missing = [key for key in required if key not in analysis]
            if missing:
                logger.error(f"  ❌ {pattern}: analysis missing {', '.join(missing)}")
                failures.append(pattern)
                continue

            stem = f"clip_{s_id}_{p_idx:03d}_cut"
            out_video = out / f"{stem}.mp4"
            out_json = out / f"{stem}.json"

            if analysis["is_usable"] and analysis["fidelity_score"] >= min_fidelity:
                start = analysis["start_time"]
                end = analysis["end_time"]
                if edge_trim > 0:
                    if edge_trim * 2 >= end - start:
                        logger.warning(
                            f"  Skipped: {pattern}  edge_trim {edge_trim}s x2 "
                            f">= usable window {end - start:.1f}s")
                        continue
                    start += edge_trim
                    end -= edge_trim
                try:
                    ffmpeg_cut(src, out_video, start, end)
                except RuntimeError as e:
                    logger.error(f"  ❌ {pattern}: {e}")
                    failures.append(pattern)
                    continue
                out_json.write_text(
                    json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                logger.info(f"  Cut: {out_video.name}  score={analysis['fidelity_score']}")
            else:
                logger.warning(f"  Rejected: {pattern}  score={analysis['fidelity_score']}  {analysis.get('edit_notes', '')}")

    if failures:
        raise RuntimeError(
            f"{len(failures)} clip(s) failed to cut: {', '.join(failures[:5])}"
            + ("" if len(failures) <= 5 else f" (+{len(failures) - 5} more)"))
