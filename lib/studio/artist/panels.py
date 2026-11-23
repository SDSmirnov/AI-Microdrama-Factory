"""Panel-by-panel rendering."""
import json
import logging
import os
from pathlib import Path
from typing import Optional

from PIL import Image

from lib.core.project import Project
from lib.core.prompts import NO_LABEL_TEXT, actor_line
from lib.core.utils import is_portrait, orientation
from lib.llm.base import BaseLLM
from lib.studio.artist.anchor_prompt import (
    _anchor_id, _anchor_visibility_block, _extract_camera_anchor_labels,
    _load_entrance_anchor_points,
)
from lib.studio.artist.render_utils import _load_scenes, _ref_label, _run_render_tasks, known_refs
from lib.studio.artist.view_catalog import _OUTDOOR_VIEWS, _ROOM_VIEWS, _VEHICLE_VIEWS
from lib.studio.blocking import blocking_mode

logger = logging.getLogger(__name__)


def panel_anchor_block_enabled() -> bool:
    """AI_PANEL_ANCHOR_BLOCK=0 drops the anchor block from panel render and QA prompts.

    The block never reached a model before 2026-11-13 (anchors were matched by display
    label, panels name them by id), so its effect on output is unmeasured: this switch
    is how to compare a panel with and without it.
    """
    return (os.getenv('AI_PANEL_ANCHOR_BLOCK', '1') or '1').strip().lower() not in ('0', 'false', 'no', 'off')


SKETCH_LABEL = '↑ IMAGE 1 — BLOCKING SKETCH: geometry only, see the BLOCKING block in the prompt.\n'


def _panel_blocking_context(scene: dict, panel: dict, project: 'Project', aspect_ratio: str,
                            with_sketch: bool = True) -> tuple[str, Image.Image | None]:
    """(spatial prompt context, sketch): car blocking replaces the anchor block; room blocking joins it."""
    # room_blocking imports artist view math: a module-level import here would cycle through artist/__init__
    from lib.studio.blocking_sketch import block_text, label, panel_blocking, panel_sketch, sketch_worthy
    from lib.studio.room_blocking import RoomBlocking

    mode = blocking_mode()
    blocking = panel_blocking(panel, scene, project.character_info.get, aspect_ratio) if mode != 'off' else None
    anchors = '' if blocking and not isinstance(blocking, RoomBlocking) else _panel_anchor_context(panel, project)
    if blocking is None:
        return anchors, None
    sketch = None
    path = (panel_sketch(blocking, project.ref_dir)
            if mode == 'sketch' and with_sketch and sketch_worthy(panel) else None)
    if path:
        with Image.open(path) as img:
            sketch = img.copy()
    logger.info(f"    🎭 Blocking: {label(blocking)}{' + sketch' if sketch else ''}")
    return '\n'.join(filter(None, [block_text(blocking, with_sketch=sketch is not None), anchors])), sketch


def _with_sketch(refs: list, sketch: Image.Image | None) -> list:
    """First, because the image model weights earlier references more."""
    return refs if sketch is None else [sketch, SKETCH_LABEL, *refs]


def _panel_camera_xy(panel: dict) -> tuple[float, float] | None:
    """The panel's camera in room coords, or None when absent or outside the room."""
    cam = (panel.get('camera_x'), panel.get('camera_y'))
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 for v in cam):
        return float(cam[0]), float(cam[1])
    return None


def _panel_anchor_context(panel: dict, project: 'Project') -> str:
    """Return a filtered anchor visibility block for the panel's active location ref.

    Includes objects named in panel.state.anchor_refs plus any anchor referenced by
    panel.camera_position (annotated as the camera placement anchor).
    Reprojects to the view used in location_references.
    Empty string when anchor data is unavailable or AI_PANEL_ANCHOR_BLOCK=0.
    """
    if not panel_anchor_block_enabled():
        return ''
    anchor_refs = set(panel.get('state', {}).get('anchor_refs', []))

    all_suffixes = [s for s, _ in _ROOM_VIEWS + _VEHICLE_VIEWS + _OUTDOOR_VIEWS]
    view_suffix = None
    loc_ref_name = None
    for ref_name in panel.get('location_references', []):
        for suffix in all_suffixes:
            if ref_name.endswith(f'-{suffix}'):
                view_suffix = suffix
                loc_ref_name = ref_name
                break
        if view_suffix:
            break

    if not view_suffix or not loc_ref_name:
        return ''

    # For View-From-Entrance (and View-Primary) anchor_points live on the ref itself;
    # for all other views they must be loaded from the canonical entrance sibling.
    anchor_points = (
        _load_entrance_anchor_points(loc_ref_name, view_suffix, project)
        or project.character_info.get(loc_ref_name, {}).get('anchor_points', {})
    )
    if not anchor_points:
        return ''

    camera_anchors = _extract_camera_anchor_labels(panel.get('camera_position', ''), anchor_points)
    include = anchor_refs | camera_anchors
    if not include:
        return ''

    filtered = dict(anchor_points)
    filtered['objects'] = [
        obj for obj in anchor_points.get('objects', [])
        if _anchor_id(obj) in include
    ]
    if not filtered['objects']:
        return ''

    return _anchor_visibility_block(filtered, view_suffix, frozenset(camera_anchors), _panel_camera_xy(panel))


def _build_panel_prompt(scene: dict, panel: dict, frame_type: str, prompts: dict, aspect_ratio: str = '9:16', anchor_context: str = '') -> str:
    """Build a focused single-panel image generation prompt."""
    style_prompt = prompts.get('style', '')
    single_panel_spec = f"Render a SINGLE {aspect_ratio} {orientation(aspect_ratio)} image. One panel only — no grid."
    imagery_prompt = prompts.get('imagery', '').replace('{grid_layout}', single_panel_spec)
    setting_context = prompts.get('setting', '')

    if frame_type == 'start':
        visual = panel.get('visual_start', '')
    elif frame_type == 'end':
        visual = panel.get('visual_end', '')
    else:  # static
        visual = panel.get('visual_start', panel.get('visual_end', ''))

    tags = []
    if panel.get('hook_type') and panel['hook_type'] != 'none':
        tags.append(panel['hook_type'].upper())
    if panel.get('emotional_beat'):
        tags.append(panel['emotional_beat'])
    tag_str = f" [{' | '.join(tags)}]" if tags else ""

    disposition_line = f"\nDisposition: {panel['visual_disposition']}" if panel.get('visual_disposition') else ""
    anchor_block = f"\n{anchor_context}" if anchor_context else ""

    actors_info = [
        actor_line(actor, actor.get('visual_ref') or actor.get('name', ''))
        for actor in panel.get('state', {}).get('actors', []) if actor.get('in_frame')
    ]
    actors_line = '\n'.join(actors_info)

    prompt = f"""{style_prompt}

{imagery_prompt}

{setting_context}

Location: {scene['location']}

CONSISTENCY RULE: Maintain IDENTICAL face, hair, clothing, and body proportions as shown in the reference images.
NO CAPTIONS. NO TEXT OVERLAYS. NO WATERMARKS. NO TEARS. NO SPITTING.
{NO_LABEL_TEXT}

Generate a SINGLE {orientation(aspect_ratio)} image ({aspect_ratio}) for:
Panel {panel['panel_index']} — {frame_type.upper()} frame{tag_str}

Actors: {actors_line}
Visual: {visual}{disposition_line}{anchor_block}
Camera / Lighting: {" | ".join(filter(None, [scene.get("camera_master", ""), scene.get("lighting_master", ""), panel.get("lights_and_camera", "")]))}

{"**IMPORTANT: THIS IS VERTICAL PORTRAIT IMAGE, IT SHOULD BE VIEWED NORMALLY, WITHOUT ROTATION**" if is_portrait(aspect_ratio) else ""}
"""
    return prompt


def _build_ref_contents(panel: dict, project: Project) -> tuple[list, list]:
    """Build reference image content parts for a panel.

    Image comes before its text annotation so the model sees the visual first.
    Returns (contents, opened_imgs) — caller must close opened_imgs after use.
    """
    # dict.fromkeys: dedupe in a stable order — the image model weights earlier references more.
    ref_chars = known_refs(panel.get('references', []) + panel.get('location_references', []),
                           project.character_images)
    if not ref_chars:
        return [], []

    contents = [
        "# Visual Reference Library\n"
        "IMPORTANT: Always prioritize the visual design from the provided images "
        "over your internal concepts."
    ]
    opened_imgs = []
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
        contents.append(img)
        contents.append(_ref_label(name, ref_type, info))
    return contents, opened_imgs


def _panel_image_size(config: dict) -> str:
    """Render resolution for a storyboard PANEL.

    Was hardcoded to '1K' while the project's own style block advertised
    "RESOLUTION: 2K / RENDER: Photorealistic 2K" — the style text and the
    actual render disagreed. A 1K 9:16 panel is 768x1360 (1.04 MP); the
    video model then receives a first frame SMALLER than its own 720p
    output and has to invent the detail.

    Measured cost curve (google/gemini-nano-banana-2.1, chat path):
        1K  (1.05 MP) $0.03490
        2K  (4.19 MP) $0.05172   1.48x the price for 4x the pixels
        4K (16.78 MP) $0.11487   3.29x the price for 16x the pixels

    So the default follows config['image_generation']['image_size'] (2K in
    the shipped presets, 1K in the CRAB test project) and can be overridden
    with AI_PANEL_IMAGE_SIZE.
    """
    env = (os.getenv('AI_PANEL_IMAGE_SIZE', '') or '').strip()
    if env:
        return env
    try:
        return ((config or {}).get('image_generation', {}) or {}).get(
            'image_size', '2K')
    except Exception:
        return '2K'


def _panel_output_path(project: Project, scene_id: int, panel_index: int, frame_type: str) -> Path:
    suffix = {'start': '_start', 'end': '_end', 'static': '_static'}[frame_type]
    return project.panels_dir / f"{scene_id:03d}_{panel_index:02d}{suffix}.png"


def _render_single_panel(
    scene: dict,
    panel: dict,
    scene_id: int,
    frame_type: str,
    aspect_ratio: str,
    project: Project,
    llm: BaseLLM,
    prompts: dict,
    config: dict,
):
    out_path = _panel_output_path(project, scene_id, panel['panel_index'], frame_type)
    if out_path.exists():
        logger.info(f"  ⏭  Skip {out_path.name} (exists)")
        return

    logger.info(f"  🎨 Rendering {out_path.name} ...")

    refs, opened_imgs = _build_ref_contents(panel, project)

    # Cross-scene continuity anchor for the first panel of each scene
    if panel['panel_index'] == 1 and scene_id > 1:
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

    anchor_context, sketch = _panel_blocking_context(scene, panel, project, aspect_ratio)
    refs = _with_sketch(refs, sketch)
    prompt_text = _build_panel_prompt(scene, panel, frame_type, prompts, aspect_ratio, anchor_context)

    try:
        img_bytes = llm.make_image(prompt_text, refs=refs, aspect_ratio=aspect_ratio,
                                    image_size=_panel_image_size(config))
        if img_bytes:
            out_path.write_bytes(img_bytes)
            logger.info(f"    ✅ Saved {out_path}")
        else:
            logger.error(f"    ❌ Empty response for {out_path.name}")
    except Exception as e:
        logger.error(f"    ❌ Failed {out_path.name}: {e}")
    finally:
        for img in opened_imgs:
            img.close()


def render_panels(
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    project: Project,
    scene_filter: Optional[int] = None,
    panel_filter: Optional[int] = None,
):
    """Render individual panel images from animation_metadata.json (single source of truth)."""
    logger.info("\n🎬 PANEL RENDER: Generating individual panel images...")

    scenes = _load_scenes(project)
    if not scenes:
        logger.warning("  ⚠️  No scenes found in animation_metadata.json or per-episode refined JSONs")
        return

    aspect_ratio = config['image_generation'].get('aspect_ratio', '9:16')

    if scene_filter is not None:
        scenes = [s for s in scenes if s.get('scene_id') == scene_filter]

    tasks = []
    for scene in scenes:
        sid = scene['scene_id']
        panels = scene.get('panels', [])
        if panel_filter is not None:
            panels = [p for p in panels if p.get('panel_index') == panel_filter]
        for panel in panels:
            tasks.append((scene, panel, sid, 'static', aspect_ratio))

    if not tasks:
        return

    logger.info(f"  📋 {len(tasks)} panel frame(s) to render.")
    _run_render_tasks(
        lambda t: _render_single_panel(*t, project=project, llm=llm, prompts=prompts, config=config),
        tasks, lambda t: f"scene {t[2]} panel {t[1].get('panel_index')}", project.image_workers,
    )


def render_extra_panel(
    scene: dict,
    panel: dict,
    out_path: Path,
    aspect_ratio: str,
    project: "Project",
    llm: "BaseLLM",
    prompts: dict,
    config: dict,
):
    """Render a single extra panel to an arbitrary output path.

    Reuses the same prompt/ref building logic as normal panel rendering,
    but writes to *out_path* instead of the canonical panels/ directory.
    """
    if out_path.exists():
        logger.info(f"  ⏭  Skip {out_path.name} (exists)")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"  🎨 Rendering extra panel → {out_path} ...")

    refs, opened_imgs = _build_ref_contents(panel, project)
    anchor_context, sketch = _panel_blocking_context(scene, panel, project, aspect_ratio)
    refs = _with_sketch(refs, sketch)
    prompt_text = _build_panel_prompt(scene, panel, 'static', prompts, anchor_context=anchor_context)

    try:
        img_bytes = llm.make_image(prompt_text, refs=refs, aspect_ratio=aspect_ratio,
                                    image_size=_panel_image_size(config))
        if img_bytes:
            out_path.write_bytes(img_bytes)
            logger.info(f"    ✅ Saved {out_path}")
        else:
            logger.error(f"    ❌ Empty image response for {out_path.name}")
    except Exception as e:
        logger.error(f"    ❌ Failed to render {out_path.name}: {e}")
    finally:
        for img in opened_imgs:
            img.close()
