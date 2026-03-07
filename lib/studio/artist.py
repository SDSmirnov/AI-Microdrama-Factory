"""
Artist — character reference management and image rendering.

Consolidates safe_name, load_character_refs, generate_single_reference,
auto_cast_characters, render_character_refs, render_scene_grids, render_panels,
slice_combined, export_image_prompt from old numbered scripts.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image

from lib.core.schemas import CHARACTER_SCHEMA, GRID_QA_SCHEMA
from lib.core.project import Project
from lib.core.utils import grid_dims, panel_boxes, safe_name
from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers — single definitions replacing 4-script duplication
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Character reference loading
# ---------------------------------------------------------------------------

def load_character_refs(project: Project):
    """Populate project.character_images and project.character_info from ref_dir."""
    ref_dir = project.ref_dir
    for json_path in ref_dir.glob("*.json"):
        try:
            char = json.loads(json_path.read_text(encoding='utf-8'))
            name = char.get('name', '')
            if not name:
                continue
            project.character_info[name] = char
            png_path = json_path.with_suffix('.png')
            if png_path.exists():
                project.character_images[name] = str(png_path)
        except Exception as e:
            logger.warning(f"  ⚠️  Could not load {json_path}: {e}")

    have_png = len(project.character_images)
    total = len(project.character_info)
    logger.info(f"  📚 Character refs: {have_png} with PNG, {total - have_png} missing PNG")


# ---------------------------------------------------------------------------
# Casting
# ---------------------------------------------------------------------------

def generate_single_reference(char: dict, setting_context: str, config: dict, project: Project):
    """Save character reference JSON. Image rendering is done separately by render_character_refs."""
    name = char['name']
    fname = safe_name(name)
    json_path = project.ref_dir / f"{fname}.json"
    json_path.write_text(json.dumps(char, indent=2), encoding='utf-8')
    project.character_info[name] = char
    logger.info(f"  ✅ Saved reference JSON: {name}")


def _existing_refs_context(project: Project) -> str:
    """
    Build a human-readable block describing existing refs for the casting prompt.

    Uses logline_subject_info when available; falls back to a truncated
    video_visual_desc or visual_desc for backward compatibility with old JSONs.
    """
    lines = []
    for name, info in project.character_info.items():
        context = (
            info.get('logline_subject_info')
            or info.get('video_visual_desc', '')[:120]
            or info.get('visual_desc', '')[:120]
        )
        lines.append(f"  - {name}: {context}")
    return "\n".join(lines) if lines else "  (none yet)"


def auto_cast_characters(
    text: str,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    project: Project,
):
    """Identify characters/locations/objects and save reference JSONs."""
    load_character_refs(project)

    if not config.get('reference_characters', {}).get('enabled', True):
        logger.info("ℹ️  Casting disabled in config")
        return

    logger.info("\n🎭 CASTING: Identifying characters/locations/objects...")

    existing_context = _existing_refs_context(project)
    casting_prompt_template = prompts.get('casting', '')
    setting_context = prompts.get('setting', '')

    prompt = f"""
{casting_prompt_template}

{setting_context}

Analyze the text for KEY reference characters/locations/objects/rooms/vehicles/interfaces that will be visible on screen.

## EXISTING REFERENCES (do NOT recreate these):
{existing_context}

DEDUPLICATION RULES — read carefully:
- Match by IDENTITY, not by name. If a character/place in the text is the same entity as an existing reference (same role, same location, same object) — SKIP IT, even if the name differs slightly.
- Only add a NEW entry if it is genuinely a different entity not yet covered above.
- If unsure, prefer reusing an existing reference over creating a new one.

For each NEW reference, provide:
  - name: short canonical label (letters, digits, hyphens only — no quotes or parentheses)
  - logline_subject_info: one sentence — who/what this is in the story (role, relationship, function)
  - visual_desc: detailed visual description for image generation
  - video_visual_desc: short visual summary for video/animation
  - type: Character | Location | Object | Room | Vehicle | Interface
  - style_reference: name of an existing or new reference to use as style base

Text:

<STORY>{text}</STORY>
"""

    new_chars = llm.make_json(prompt, CHARACTER_SCHEMA)
    if not new_chars:
        return

    ctx = f"{casting_prompt_template} {setting_context}"
    max_workers = project.max_workers
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(
            lambda char: generate_single_reference(char, ctx, config, project),
            new_chars
        ))


# ---------------------------------------------------------------------------
# Character reference image rendering
# ---------------------------------------------------------------------------

def _render_single_ref(char: dict, config: dict, project: Project, llm: BaseLLM):
    name = char['name']
    sname = safe_name(name)
    png_path = project.ref_dir / f"{sname}.png"

    if png_path.exists():
        logger.info(f"  ⏭  Skip {name} (PNG exists)")
        return

    logger.info(f"  🎬 Rendering reference: {name}")

    refs = []
    opened_imgs = []
    style_ref = char.get('style_reference', '')
    if style_ref and style_ref != name:
        ref_png = project.ref_dir / f"{safe_name(style_ref)}.png"
        if ref_png.exists():
            refs.append(f"## Visual Style reference for {style_ref}")
            img = Image.open(ref_png)
            opened_imgs.append(img)
            refs.append(img)

    ref_aspect = config.get('reference_characters', {}).get('ref_aspect_ratio', '3:4')
    prompt_text = (
        f"CINEMATIC REFERENCE FOR {char['type']}: {name}. "
        f"{char['visual_desc']}. "
        "Close-up, neutral expression, uniform lighting, 8k."
    )

    try:
        img_bytes = llm.make_image(prompt_text, refs=refs, aspect_ratio=ref_aspect, image_size="1K")
        if img_bytes:
            png_path.write_bytes(img_bytes)
            project.character_images[name] = str(png_path)
            logger.info(f"    ✅ Saved {png_path}")
        else:
            logger.error(f"    ❌ Empty response for {name}")
    except Exception as e:
        logger.error(f"    ❌ Failed to render {name}: {e}")
    finally:
        for img in opened_imgs:
            img.close()


def render_character_refs(prompts: dict, config: dict, llm: BaseLLM, project: Project):
    """Render missing character reference portraits from ref_dir/*.json"""
    logger.info("\n🎭 RENDER REFS: Generating missing character reference portraits...")

    to_render = []
    for json_path in project.ref_dir.glob("*.json"):
        try:
            char = json.loads(json_path.read_text(encoding='utf-8'))
            name = char.get('name', '')
            if name and not (project.ref_dir / f"{safe_name(name)}.png").exists():
                to_render.append(char)
        except Exception as e:
            logger.warning(f"  ⚠️  Could not read {json_path}: {e}")

    if not to_render:
        logger.info("  ✅ All character references already rendered.")
        return

    logger.info(f"  📋 {len(to_render)} references to render.")
    failed = []
    for c in to_render:
        before = len(project.character_images)
        _render_single_ref(c, config, project, llm)
        if len(project.character_images) == before:
            failed.append(c.get('name', '?'))

    if failed:
        logger.warning(f"  ⚠️  {len(failed)}/{len(to_render)} ref(s) failed to render: {failed}. Run 'python cli.py refs' to retry.")


# ---------------------------------------------------------------------------
# Scene grid rendering
# ---------------------------------------------------------------------------

def _build_prompt_header(scene: dict, prompts: dict) -> str:
    """Build the shared prompt header for scene image generation."""
    return (
        f"{prompts.get('style', '')}\n\n"
        f"{prompts.get('imagery', '')}\n\n"
        f"{prompts.get('setting', '')}\n\n"
        f"Location: {scene['location']}\n"
        f"Setup: {scene.get('pre_action_description', '')}\n"
        "CONSISTENCY RULE: All instances of the same character across all panels must have IDENTICAL face, hair, clothing, body proportions.\n"
        "NO CAPTIONS!\n"
    )


def _build_grid_prompt(scene: dict, prompts: dict, config: dict) -> str:
    """Build the text prompt for a scene grid image."""
    aspect_ratio = config['image_generation']['aspect_ratio']
    resolution = config['image_generation']['image_size']

    prompt = _build_prompt_header(scene, prompts)
    prompt += f"\nIMPORTANT: Generate SINGLE {resolution} {aspect_ratio} image with panels in grid layout.\n"

    for p in scene['panels']:
        prompt += f"\nPanel {p['panel_index']}:\n"
        prompt += f"  Visual: {p.get('visual_start', p.get('visual_end', ''))}\n"
        if 'lights_and_camera' in p:
            prompt += f"  Camera: {p['lights_and_camera']}\n"

    logger.debug(prompt)
    return prompt


_MAX_GRID_RETRIES = 3
# Slightly increase temperature on each retry to vary output.
# Range 0.35–0.45 is intentionally narrow: enough to diversify without breaking prompt-following.
_GRID_BASE_TEMP = 0.35
_GRID_TEMP_STEP = 0.05


def _quick_grid_check(img_bytes: bytes, scene: dict, project: Project, llm: BaseLLM) -> tuple[bool, str]:
    """Quick vision check on a rendered grid. Returns (passed, reason).

    Catches only catastrophic failures (wrong identity, missing people).
    On any error, returns (True, ...) to avoid blocking the pipeline.
    """
    all_refs = list({
        ref
        for panel in scene.get('panels', [])
        for ref in panel.get('references', []) + panel.get('location_references', [])
    })
    loadable = [name for name in all_refs if name in project.character_images]
    if not loadable:
        return True, ""

    contents = ["# VISUAL REFERENCES (characters, locations, objects)\n"]
    opened = []
    for name in loadable[:4]:
        try:
            img = Image.open(project.character_images[name])
            opened.append(img)
            contents.append(f"## Reference: {name}\n")
            contents.append(img)
        except Exception:
            pass

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
            slice_combined(path_combined, scene_id, config, project)
        return

    chars = []
    for panel in scene.get('panels', []):
        chars.extend(panel.get('references', []))
        chars.extend(panel.get('location_references', []))
    chars = list(set(chars))
    logger.info(f"  📎 Scene {scene_id} refs: {chars}")

    refs = []
    opened_imgs = []
    ref_chars = [name for name in chars if name in project.character_images]
    if ref_chars:
        refs.append(
            "# Visual Reference Library\n"
            "## IMPORTANT:\n"
            "Always prioritize the visual design of characters/objects "
            "from the provided images over your internal concepts."
        )
        for name in ref_chars:
            png_path = project.character_images[name]
            info = ""
            try:
                meta = json.loads(Path(png_path).with_suffix('.json').read_text(encoding='utf-8'))
                info = meta.get('video_visual_desc', '')
            except Exception:
                pass
            refs.append(f"## Visual Reference for: \"{name}\"\nUse it for appearances\n{info}\n")
            img = Image.open(png_path)
            opened_imgs.append(img)
            refs.append(img)

    prompt_text = _build_grid_prompt(scene, prompts, config)
    aspect_ratio = config['image_generation']['aspect_ratio']
    resolution = config['image_generation']['image_size']

    logger.info(f"  🎨 Rendering scene {scene_id} ({config['format']['type']})...")
    img_bytes = None
    try:
        for attempt in range(_MAX_GRID_RETRIES):
            temp = _GRID_BASE_TEMP + attempt * _GRID_TEMP_STEP
            try:
                candidate = llm.make_image(
                    prompt_text, refs=refs,
                    aspect_ratio=aspect_ratio, image_size=resolution,
                    temperature=temp,
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
        slice_combined(path_combined, scene_id, config, project)


def _load_scenes(project: Project) -> list:
    """
    Load scenes from animation_metadata.json (single source of truth).
    Falls back to per-episode *_refined.json files if metadata doesn't exist yet.
    """
    meta_path = project.output_dir / "animation_metadata.json"
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding='utf-8'))
            scenes = data.get('scenes', [])
            logger.info(f"  📋 Loaded {len(scenes)} scene(s) from animation_metadata.json")
            return scenes
        except Exception as e:
            logger.warning(f"  ⚠️  Could not read animation_metadata.json: {e}")

    # Fallback: collect from per-episode refined files
    logger.warning("  ⚠️  animation_metadata.json not found, falling back to per-episode refined JSONs")
    scenes = []
    for json_path in sorted(project.output_dir.glob("animation_episode_scenes_*_refined.json")):
        try:
            data = json.loads(json_path.read_text(encoding='utf-8'))
            scenes.extend(data.get('scenes', []))
        except Exception as e:
            logger.warning(f"  ⚠️  Could not read {json_path}: {e}")
    return scenes


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
    with ThreadPoolExecutor(max_workers=project.image_workers) as executor:
        executor.map(
            lambda s: _render_single_grid(s, s['scene_id'], prompts, config, project, llm),
            scenes
        )


# ---------------------------------------------------------------------------
# Panel-by-panel rendering
# ---------------------------------------------------------------------------

def _build_panel_prompt(scene: dict, panel: dict, frame_type: str, prompts: dict) -> str:
    """Build a focused single-panel image generation prompt."""
    style_prompt = prompts.get('style', '')
    imagery_prompt = prompts.get('imagery', '')
    setting_context = prompts.get('setting', '')

    if frame_type == 'start':
        visual = panel.get('visual_start', '')
    elif frame_type == 'end':
        visual = panel.get('visual_end', '')
    else:  # static
        visual = panel.get('visual_start', panel.get('visual_end', ''))

    is_reversed = panel.get('is_reversed', False)
    active_motion = (
        panel.get('motion_prompt_reversed', '')
        if is_reversed and panel.get('motion_prompt_reversed')
        else panel.get('motion_prompt', '')
    )

    tags = []
    if panel.get('hook_type') and panel['hook_type'] != 'none':
        tags.append(panel['hook_type'].upper())
    if panel.get('emotional_beat'):
        tags.append(panel['emotional_beat'])
    tag_str = f" [{' | '.join(tags)}]" if tags else ""

    prompt = f"""{style_prompt}

{imagery_prompt}

{setting_context}

Location: {scene['location']}
Scene setup: {scene.get('pre_action_description', '')}
CONSISTENCY RULE: Maintain IDENTICAL face, hair, clothing, and body proportions as shown in the reference images.
NO CAPTIONS. NO TEXT OVERLAYS. NO WATERMARKS.

Generate a SINGLE portrait image (9:16) for:
Panel {panel['panel_index']} — {frame_type.upper()} frame{tag_str}

Visual: {visual}
Camera / Lighting: {panel.get('lights_and_camera', '')}

**IMPORTANT: THIS IS VERTICAL PORTRAIT IMAGE, IT SHOULD BE VIEWED NORMALLY, WITHOUT ROTATION**
"""
    if active_motion:
        prompt += f"Motion context: {active_motion}\n"
    return prompt


def _build_ref_contents(panel: dict, project: Project) -> tuple[list, list]:
    """Build reference image content parts for a panel.

    Returns (contents, opened_imgs) — caller must close opened_imgs after use.
    """
    chars = list(set(panel.get('references', []) + panel.get('location_references', [])))
    ref_chars = [name for name in chars if name in project.character_images]
    if not ref_chars:
        return [], []

    contents = [
        "# Visual Reference Library\n"
        "## IMPORTANT:\n"
        "Always prioritize the visual design of characters/objects "
        "from the provided images over your internal concepts."
    ]
    opened_imgs = []
    for name in ref_chars:
        png_path = project.character_images[name]
        info = ""
        try:
            meta = json.loads(Path(png_path).with_suffix('.json').read_text(encoding='utf-8'))
            info = meta.get('video_visual_desc', '')
        except Exception:
            pass
        contents.append(f"## Visual Reference for: \"{name}\"\n{info}\n")
        img = Image.open(png_path)
        opened_imgs.append(img)
        contents.append(img)
    return contents, opened_imgs


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
):
    out_path = _panel_output_path(project, scene_id, panel['panel_index'], frame_type)
    if out_path.exists():
        logger.info(f"  ⏭  Skip {out_path.name} (exists)")
        return

    logger.info(f"  🎨 Rendering {out_path.name} ...")

    refs, opened_imgs = _build_ref_contents(panel, project)
    prompt_text = _build_panel_prompt(scene, panel, frame_type, prompts)

    try:
        img_bytes = llm.make_image(prompt_text, refs=refs, aspect_ratio=aspect_ratio, image_size='1K')
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
    with ThreadPoolExecutor(max_workers=project.image_workers) as executor:
        executor.map(
            lambda t: _render_single_panel(*t, project=project, llm=llm, prompts=prompts),
            tasks
        )


def render_extra_panel(
    scene: dict,
    panel: dict,
    out_path: Path,
    aspect_ratio: str,
    project: "Project",
    llm: "BaseLLM",
    prompts: dict,
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
    prompt_text = _build_panel_prompt(scene, panel, 'static', prompts)

    try:
        img_bytes = llm.make_image(prompt_text, refs=refs, aspect_ratio=aspect_ratio, image_size='1K')
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


# ---------------------------------------------------------------------------
# Grid slicing
# ---------------------------------------------------------------------------

def slice_combined(path_combined: Path, sid: int, config: dict, project: Project):
    """Slice combined grid image into individual panel files."""
    panels_dir = project.panels_dir
    panels_dir.mkdir(exist_ok=True)

    with Image.open(path_combined) as img:
        w, h = img.size
        panels_per_scene = config['format']['panels_per_scene']
        cols, rows = grid_dims(panels_per_scene)
        crops = [(idx, img.crop(box).copy()) for idx, box in enumerate(panel_boxes(w, h, cols, rows, panels_per_scene), 1)]

    for idx, crop in crops:
        out = panels_dir / f"{sid:03d}_{idx:02d}_static.png"
        try:
            crop.save(out)
        except Exception as e:
            logger.error(f"    ❌ Failed to save panel {idx} for scene {sid}: {e}")


# ---------------------------------------------------------------------------
# Image prompt export (for manual testing)
# ---------------------------------------------------------------------------

def _build_image_prompt(scene: dict, prompts: dict, config: dict) -> str:
    """Build the image generation prompt text for a scene."""
    aspect_ratio = config['image_generation']['aspect_ratio']
    resolution = config['image_generation']['image_size']

    prompt = _build_prompt_header(scene, prompts)
    prompt += (
        "**CRITICAL FORMAT:** Single image containing 9 portrait panels (9:16 each) arranged in a 3×3 grid.\n"
        "Each cell is a VERTICAL frame designed for mobile viewing.\n"
        "SAFE ZONE per panel: compose key subjects (faces, hands, focal action) within the middle 65% of panel height.\n"
        "Top 15% and bottom 20% of each panel must remain visually uncluttered (background only — sky, wall, floor).\n"
        "Faces and close-ups are the primary dramatic instrument — this is vertical microdrama, not widescreen cinema.\n"
        "Shallow depth of field. Subjects sharp, backgrounds contextual only.\n"
    )
    prompt += f"\nIMPORTANT: Generate SINGLE {resolution} {aspect_ratio} image with 9 panels in 3x3 grid layout.\n"

    for p in scene['panels']:
        prompt += f"\nPanel {p['panel_index']}:"
        if p.get('hook_type') and p['hook_type'] != 'none':
            prompt += f" [{p['hook_type'].upper()}]"
        if p.get('emotional_beat'):
            prompt += f" [{p['emotional_beat']}]"
        prompt += "\n"
        prompt += f"  Visual: {p.get('visual_start', p.get('visual_end', ''))}\n"
        if 'lights_and_camera' in p:
            prompt += f"  Camera: {p['lights_and_camera']}\n"
        if config['dialogue']['enabled'] and p.get('dialogue'):
            prompt += f"  Dialogue: {p['dialogue']}\n"
        if config['dialogue'].get('voiceover') and p.get('voiceover'):
            prompt += f"  Voiceover: {p['voiceover']}\n"
        if config['captions']['enabled'] and p.get('caption'):
            prompt += f"  Caption: {p['caption']}\n"

    return prompt


def export_image_prompt(scene: dict, scene_id: int, prompts: dict, config: dict, project: Project):
    """Write cinematic_render/image_prompts/scene_00x.md for manual image generation testing."""
    project.image_prompts_dir.mkdir(parents=True, exist_ok=True)

    chars = list({ref for panel in scene.get('panels', []) for ref in panel.get('references', [])})

    md = f"# Scene {scene_id:03d} — {scene.get('location', '')}\n\n"
    if scene.get('pre_action_description'):
        md += f"**Setup:** {scene['pre_action_description']}\n\n"

    ref_chars = [name for name in chars if name in project.character_info]
    if ref_chars:
        md += "## Character Reference Descriptions\n\n"
        md += "_Use these to maintain visual consistency when prompting the model:_\n\n"
        for name in ref_chars:
            info = project.character_info[name]
            desc = info.get('video_visual_desc') or info.get('visual_desc', '')
            md += f"### {name}\n{desc}\n\n"
        md += "---\n\n"

    md += "## Image Generation Prompt\n\n"
    md += "```\n"
    md += _build_image_prompt(scene, prompts, config)
    md += "\n```\n"

    out_path = project.image_prompts_dir / f"scene_{scene_id:03d}.md"
    out_path.write_text(md, encoding='utf-8')
    logger.info(f"  📝 Saved image prompt: {out_path}")
