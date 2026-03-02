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
- SOUND/DIALOGUE (SFX):{dialogue}

### YOUR GOALS:
1. Synchronize 'start_time' with the core action (impact, flash, or movement).
2. Ensure the lighting changes described are captured.
3. Cut the video BEFORE the AI begins to 'hallucinate' (limbs melting, background warping).
4. If the video is a static image or misses the main object, set 'is_usable' to false.

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
    subprocess.run(cmd, capture_output=True)


def run_autocut(
    llm: BaseLLM,
    json_path: str,
    clips_dir: str,
    out_dir: str,
    min_fidelity: int = 3,
) -> None:
    """
    Iterate scenes/panels from json_path, find matching clips in clips_dir,
    AI-analyze each, then write trimmed clips + JSON reports to out_dir.
    """
    clips = Path(clips_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    data = json.loads(Path(json_path).read_text(encoding="utf-8"))

    for scene in data.get("scenes", []):
        s_id = scene["scene_id"]
        for panel in scene.get("panels", []):
            p_idx = panel["panel_index"]
            pattern = f"clip_{s_id}_{p_idx:03d}.mp4"
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

            stem = f"clip_{s_id}_{p_idx:03d}_cut"
            out_video = out / f"{stem}.mp4"
            out_json = out / f"{stem}.json"

            if analysis["is_usable"] and analysis["fidelity_score"] > min_fidelity:
                ffmpeg_cut(src, out_video, analysis["start_time"], analysis["end_time"])
                out_json.write_text(
                    json.dumps(analysis, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                logger.info(f"  Cut: {out_video.name}  score={analysis['fidelity_score']}")
            else:
                logger.warning(f"  Rejected: {pattern}  score={analysis['fidelity_score']}  {analysis['edit_notes']}")
