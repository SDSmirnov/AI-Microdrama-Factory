"""Scene grid rendering and slicing."""
import json
import logging
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image

from lib.core.project import Project
from lib.core.prompts import NO_LABEL_TEXT, actor_line
from lib.core.schemas import GRID_QA_SCHEMA
from lib.core.utils import grid_dims, pad_to_ar, panel_boxes
from lib.llm.base import BaseLLM
from lib.studio.artist.render_utils import _load_scenes, _ref_label, _run_render_tasks, known_refs

logger = logging.getLogger(__name__)


def _grid_layout_spec(n: int, panel_ar: str, resolution: str) -> str:
    """Return the exact grid layout instruction string for N panels."""
    cols, rows, grid_ar = grid_dims(n, panel_ar)
    return (
        f"Render a SINGLE {resolution} {grid_ar} image with exactly {n} equal-sized panels "
        f"in {cols} columns \u00d7 {rows} rows. Each panel is {panel_ar} AR. "
        f"Panels left-to-right, top-to-bottom: Panel\u00a01\u00a0=\u00a0top-left, Panel\u00a0{n}\u00a0=\u00a0bottom-right."
    )


def _build_prompt_header(scene: dict, prompts: dict, grid_layout: str = '') -> str:
    """Build the shared prompt header for scene image generation."""
    imagery = prompts.get('imagery', '').replace('{grid_layout}', grid_layout)
    header = (
        f"{prompts.get('style', '')}\n\n"
        f"{imagery}\n\n"
        f"{prompts.get('setting', '')}\n\n"
        f"Location: {scene['location']}\n"
        f"Setup: {scene.get('pre_action_description', '')}\n"
    )
    if scene.get('camera_master'):
        header += f"Scene camera master: {scene['camera_master']}\n"
    if scene.get('lighting_master'):
        header += f"Scene lighting master: {scene['lighting_master']}\n"
    header += (
        "CONSISTENCY RULE: All instances of the same character across all panels must have IDENTICAL face, hair, clothing, body proportions.\n"
        "NO CAPTIONS!\n"
        f"{NO_LABEL_TEXT}\n"
    )
    return header


def _build_grid_prompt(scene: dict, prompts: dict, config: dict) -> str:
    """Build the text prompt for a scene grid image."""
    panel_ar = config['format'].get('panel_aspect_ratio', '9:16')
    resolution = config['image_generation'].get('image_size', '2K')

    n_panels = len(scene.get('panels', []))
    cols, rows, grid_ar = grid_dims(n_panels, panel_ar)
    gl_spec = _grid_layout_spec(n_panels, panel_ar, resolution)
    prompt = _build_prompt_header(scene, prompts, grid_layout=gl_spec)
    prompt += (
        f"\nIMPORTANT: {gl_spec}."
        f"Panels are arranged left-to-right, top-to-bottom: Panel 1 is top-left, Panel {n_panels} is bottom-right. "
        f"The entire grid is a single continuous micro-story within one location.\n"
    )

    for p in scene['panels']:
        prompt += f"\nPanel {p['panel_index']}:\n"

        actors_info = [
            actor_line(actor, actor.get('name', ''))
            for actor in p.get('state', {}).get('actors', []) if actor.get('in_frame')
        ]
        actors_line = ' '.join(actors_info)
        prompt += f"  Actors: {actors_line}\n"

        prompt += f"  Visual: {p.get('visual_start', p.get('visual_end', ''))}\n"
        if p.get('visual_disposition'):
            prompt += f"  Disposition: {p['visual_disposition']}\n"
        if 'lights_and_camera' in p:
            prompt += f"  Camera: {p['lights_and_camera']}\n"

    logger.debug(prompt)
    return prompt


_MAX_GRID_RETRIES = 3


def _quick_grid_check(img_bytes: bytes, scene: dict, project: Project, llm: BaseLLM) -> tuple[bool, str]:
    """Quick vision check on a rendered grid. Returns (passed, reason).

    Catches only catastrophic failures (wrong identity, missing people).
    On any error, returns (True, ...) to avoid blocking the pipeline.
    """
    loadable = known_refs([ref for panel in scene.get('panels', [])
                           for ref in panel.get('references', []) + panel.get('location_references', [])],
                          project.character_images)
    if not loadable:
        return True, ""

    contents = ["# VISUAL REFERENCES (characters, locations, objects)\n"]
    opened = []
    for name in loadable[:8]:
        try:
            img = Image.open(project.character_images[name])
            opened.append(img)
            contents.append(f"## Reference: {name}\n")
            contents.append(img)
        except Exception as e:
            logger.warning(f"⚠️  Ref image {name} not loaded: {e}")

    try:
        grid_img = Image.open(BytesIO(img_bytes))
        opened.append(grid_img)
        contents.append("\n# RENDERED GRID\n")
        contents.append(grid_img)

        expected_panels = len(scene.get('panels', []))
        prompt = (
            f"Quick sanity check on this storyboard grid against the references above "
            f"(characters, locations, objects). Expected panel count: {expected_panels}.\n"
            "passed=false ONLY if the grid is fundamentally unusable:\n"
            "- blank or corrupted image\n"
            f"- wrong number of panels (not {expected_panels})\n"
            "- completely wrong scene with no resemblance to any reference\n"
            "- so many simultaneous catastrophic failures that downstream QA refinement cannot recover it\n"
            "Character drift, minor identity mismatch, wrong props, lighting issues — "
            "these are handled by QA refinement and are NOT grounds for failure.\n"
            "When in doubt, passed=true."
        )
        result = llm.analyze_image(image=contents, prompt=prompt, schema=GRID_QA_SCHEMA)
        return result.get('passed', True), result.get('reason', '')
    except Exception as e:
        logger.warning(f"  ⚠️  Grid QA check error — accepting grid: {e}")
        return True, ""
    finally:
        for img in opened:
            img.close()


def _render_single_grid(scene: dict, scene_id: int, prompts: dict, config: dict,
                         project: Project, llm: BaseLLM):
    path_combined = project.output_dir / f"scene_{scene_id:03d}_grid_combined.png"

    if path_combined.exists():
        logger.info(f"  ⏭  Skip scene {scene_id} (grid exists)")
        if config['slicing']['enabled']:
            slice_combined(path_combined, scene_id, config, project, len(scene.get('panels', [])) or 9)
        return

    chars = []
    for panel in scene.get('panels', []):
        chars.extend(panel.get('references', []))
        chars.extend(panel.get('location_references', []))
    chars = list(dict.fromkeys(chars))
    logger.info(f"  📎 Scene {scene_id} refs: {chars}")

    refs = []
    opened_imgs = []
    ref_chars = known_refs(chars, project.character_images)
    if ref_chars:
        refs.append(
            "# Visual Reference Library\n"
            "IMPORTANT: Always prioritize the visual design from the provided images "
            "over your internal concepts."
        )
        for name in ref_chars:
            png_path = project.character_images[name]
            info = ""
            ref_type = "Character"
            try:
                meta = json.loads(Path(png_path).with_suffix('.json').read_text(encoding='utf-8'))
                info = meta.get('visual_desc') or meta.get('video_visual_desc', '')
                ref_type = meta.get('type', 'Character')
            except FileNotFoundError:
                pass
            except Exception as e:
                logger.warning(f"⚠️  Unreadable metadata for {png_path}: {e}")
            img = Image.open(png_path)
            opened_imgs.append(img)
            refs.append(img)
            refs.append(_ref_label(name, ref_type, info))

    # Cross-scene continuity anchor: last rendered panel of previous scene
    if scene_id > 1:
        prev_panels = sorted(project.panels_dir.glob(f"{scene_id - 1:03d}_*_static.png"))
        if prev_panels:
            try:
                anchor_img = Image.open(prev_panels[-1])
                opened_imgs.append(anchor_img)
                refs.append(anchor_img)
                refs.append(
                    "↑ PREVIOUS SCENE TERMINAL FRAME — match character appearance "
                    "continuity (clothing, hair, build) from this frame.\n"
                )
            except Exception as e:
                logger.warning(f"  ⚠️  Could not load cross-scene anchor: {e}")

    prompt_text = _build_grid_prompt(scene, prompts, config)
    n_panels = len(scene.get('panels', []))
    _, _, grid_ar = grid_dims(n_panels, config['format'].get('panel_aspect_ratio', '9:16'))
    resolution = config['image_generation'].get('image_size', '2K')

    logger.info(f"  🎨 Rendering scene {scene_id} ({config['format']['type']})...")
    img_bytes = None
    try:
        for attempt in range(_MAX_GRID_RETRIES):
            try:
                candidate = llm.make_image(
                    prompt_text, refs=refs,
                    aspect_ratio=grid_ar, image_size=resolution,
                )
            except Exception as e:
                logger.error(f"    ❌ Render error scene {scene_id} attempt {attempt + 1}: {e}")
                continue
            if not candidate:
                logger.error(f"    ❌ Empty response scene {scene_id} attempt {attempt + 1}")
                continue
            passed, reason = _quick_grid_check(candidate, scene, project, llm)
            img_bytes = candidate
            if passed:
                logger.info(f"    ✅ Scene {scene_id} passed grid QA (attempt {attempt + 1})")
                break
            logger.warning(
                f"  🔄 Scene {scene_id} grid QA failed attempt {attempt + 1}/{_MAX_GRID_RETRIES}: {reason}"
            )
        if img_bytes:
            path_combined.write_bytes(img_bytes)
            logger.info(f"    ✅ Saved {path_combined}")
        else:
            logger.error(f"    ❌ All attempts failed for scene {scene_id}")
            return
    finally:
        for img in opened_imgs:
            img.close()

    if config['slicing']['enabled']:
        slice_combined(path_combined, scene_id, config, project, len(scene.get('panels', [])) or 9)


def render_scene_grids(
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    project: Project,
    scene_filter: Optional[int] = None,
):
    """Render scene grid images from animation_metadata.json (single source of truth)."""
    logger.info("\n🎬 RENDER GRIDS: Generating scene grid images...")

    scenes = _load_scenes(project)
    if not scenes:
        logger.warning("  ⚠️  No scenes found in animation_metadata.json or per-episode refined JSONs")
        return

    if scene_filter is not None:
        scenes = [s for s in scenes if s.get('scene_id') == scene_filter]
        if not scenes:
            logger.error(f"  ❌ Scene {scene_filter} not found in refined JSONs")
            return

    logger.info(f"  📋 {len(scenes)} scene(s) to process.")
    _run_render_tasks(
        lambda s: _render_single_grid(s, s['scene_id'], prompts, config, project, llm),
        scenes, lambda s: f"scene {s.get('scene_id')}", project.image_workers,
    )


def slice_combined(path_combined: Path, sid: int, config: dict, project: Project, panel_count: int = 9):
    """Slice combined grid image into individual panel files, padding each to panel_aspect_ratio."""
    panels_dir = project.panels_dir
    panels_dir.mkdir(exist_ok=True)
    panel_ar = config['format'].get('panel_aspect_ratio', '9:16')

    with Image.open(path_combined) as img:
        w, h = img.size
        cols, rows, _ = grid_dims(panel_count, panel_ar)
        crops = [(idx, img.crop(box).copy()) for idx, box in enumerate(panel_boxes(w, h, cols, rows, panel_count), 1)]

    for idx, crop in crops:
        out = panels_dir / f"{sid:03d}_{idx:02d}_static.png"
        try:
            padded = pad_to_ar(crop, panel_ar)
            padded.save(out)
        except Exception as e:
            logger.error(f"    ❌ Failed to save panel {idx} for scene {sid}: {e}")
        finally:
            crop.close()
