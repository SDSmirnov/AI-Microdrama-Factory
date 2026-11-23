"""Re-render a panel at a wider aspect ratio."""
import logging
from pathlib import Path

from PIL import Image

from lib.core.project import Project
from lib.core.prompts import NO_LABEL_TEXT
from lib.llm.base import BaseLLM
from lib.studio.artist.panels import _build_ref_contents, _panel_anchor_context

logger = logging.getLogger(__name__)


def _derive_fullframe_disposition(panel: dict) -> str:
    """Build a camera-agnostic visual_disposition for the expanded frame.

    Uses panel['state'] as ground truth — includes all actors regardless of
    original in_frame status, since the wider crop reveals previously cropped subjects.
    Falls back to existing visual_disposition if state is absent.
    """
    state = panel.get('state', {})
    if not state:
        return panel.get('visual_disposition', '')

    parts: list[str] = []

    base = state.get('complete_disposition', '').strip()
    if base:
        parts.append(base)

    # Add explicit lines for actors that were off-frame — they are now visible
    off_frame = [a for a in state.get('actors', []) if not a.get('in_frame', True)]
    if off_frame:
        actor_lines = []
        for a in off_frame:
            line = f"{a['name']}: {a.get('position', 'position unknown')}, {a.get('pose', '')}"
            if a.get('gaze_target'):
                line += f", gaze on {a['gaze_target']}"
            if a.get('motion_action'):
                line += f" — {a['motion_action']}"
            actor_lines.append(line.strip(', '))
        parts.append("Now visible in expanded frame: " + "; ".join(actor_lines) + ".")

    if state.get('environment'):
        parts.append(state['environment'])

    return " ".join(parts)


def _derive_fullframe_visual(panel: dict) -> str:
    """Build a full-scene visual description from panel state for full-frame rendering.

    The original visual_start describes a tight crop (CU/MCU) which conflicts with
    an expanded-frame render. This derives a WS/MS description from state that covers
    all actors, props, and environment — regardless of original in_frame status.
    """
    state = panel.get('state', {})
    if not state:
        return panel.get('visual_start', panel.get('visual_end', ''))

    # complete_disposition already appears in the Disposition line — don't repeat it here.
    # Just enumerate actors, props, and environment for the visual body.
    parts: list[str] = []

    for actor in state.get('actors', []):
        line = (
            f"{actor['name']}: {actor.get('position', '')}, {actor.get('pose', '')}"
        )
        if actor.get('motion_action'):
            line += f"; {actor['motion_action']}"
        parts.append(line.rstrip(', '))

    for prop in state.get('props', []):
        prop_line = f"{prop['name']}: {prop.get('position', '')}"
        if prop.get('prop_change'):
            prop_line += f"; {prop['prop_change']}"
        parts.append(prop_line)

    # environment is already in the Disposition line via _derive_fullframe_disposition
    return " ".join(parts)


def _build_fullframe_prompt(
    scene: dict,
    panel: dict,
    aspect_ratio: str,
    prompts: dict,
    anchor_context: str = '',
) -> str:
    """Build an image generation prompt for a full-frame (expanded AR) render.

    Unlike _build_panel_prompt this:
    - uses visual derived from state (all actors, WS/MS framing)
    - includes disposition with off-frame actors
    - uses correct orientation label for non-portrait ARs
    - does not carry the original CU visual that would fight the expansion
    """
    style_prompt = prompts.get('style', '')
    single_panel_spec = f"Render a SINGLE {aspect_ratio} image. One panel only — no grid."
    imagery_prompt = prompts.get('imagery', '').replace('{grid_layout}', single_panel_spec)
    setting_context = prompts.get('setting', '')

    visual = _derive_fullframe_visual(panel)
    disposition = panel.get('visual_disposition', '')
    disposition_line = f"\nDisposition: {disposition}" if disposition else ""
    anchor_block = f"\n{anchor_context}" if anchor_context else ""

    tags = []
    if panel.get('hook_type') and panel['hook_type'] != 'none':
        tags.append(panel['hook_type'].upper())
    if panel.get('emotional_beat'):
        tags.append(panel['emotional_beat'])
    tag_str = f" [{' | '.join(tags)}]" if tags else ""

    cam = " | ".join(filter(None, [
        scene.get('camera_master', ''),
        scene.get('lighting_master', ''),
        panel.get('lights_and_camera', ''),
    ]))

    return f"""{style_prompt}

{imagery_prompt}

{setting_context}

Location: {scene['location']}
Scene setup: {scene.get('pre_action_description', '')}
CONSISTENCY RULE: Maintain IDENTICAL face, hair, clothing, and body proportions as shown in the reference images.
NO CAPTIONS. NO TEXT OVERLAYS. NO WATERMARKS. NO TEARS. NO SPITTING.
{NO_LABEL_TEXT}

Generate a SINGLE {aspect_ratio} image for:
Panel {panel['panel_index']} — FULL-FRAME EXPANSION{tag_str}

Visual (full scene, all actors):{disposition_line}
{visual}{anchor_block}
Camera / Lighting: {cam}
IMPORTANT: Shot scale must be wide enough to show ALL actors listed above — widen to MS or WS as needed.

FULL-FRAME RECOMPOSE: Render a {aspect_ratio} expansion of the SOURCE PANEL above. \
Do NOT crop — expand outward to reveal the full environment. \
All actors must be visible at their stated positions. \
Match character references exactly: same face, clothing, lighting.

⚠️ RENDER EXACTLY AS DESCRIBED. DO NOT DEVIATE. DO NOT IMPROVE.
Do not add, remove, or reinterpret any element. Do not substitute poses, costumes, props, \
lighting, or character positions with alternatives you consider "better". \
The description is the final authority — execute it literally.
FREEZE THE MOMENT: Show the central character in the pose JUST BEFORE the action begins — \
not mid-action, not post-action. The action has not happened yet. \
DO NOT CHANGE THE INITIAL POSE OF THE CENTRAL CHARACTER.
"""


def render_full_frame_panel(
    scene: dict,
    panel: dict,
    source_png: Path,
    out_path: Path,
    aspect_ratio: str,
    project: Project,
    llm: BaseLLM,
    prompts: dict,
):
    """Re-render an existing panel at a different aspect ratio for animation.

    The rendered source PNG is injected as the primary reference so the model
    expands the frame outward instead of reinventing the shot.
    Outputs to *out_path* (caller decides the directory).
    """
    if out_path.exists():
        logger.info(f"  ⏭  Skip {out_path.name} (exists)")
        return

    if not source_png.exists():
        logger.error(f"  ❌ Source panel not found: {source_png}")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"  🎨 Rendering full-frame {out_path.name} ({aspect_ratio}) ...")

    # Union refs from every panel in the scene — the wider frame may expose
    # characters or locations that were outside the original 9:16 crop.
    scene_char_refs: set[str] = set()
    scene_loc_refs: set[str] = set()
    for p in scene.get('panels', []):
        scene_char_refs.update(p.get('references', []))
        scene_loc_refs.update(p.get('location_references', []))
    wide_panel = dict(
        panel,
        references=list(scene_char_refs),
        location_references=list(scene_loc_refs),
        visual_disposition=_derive_fullframe_disposition(panel),
    )

    char_refs, opened_imgs = _build_ref_contents(wide_panel, project)

    source_img = Image.open(source_png)
    opened_imgs.insert(0, source_img)

    source_label = (
        f"↑ SOURCE PANEL — original render. RE-COMPOSE in {aspect_ratio}: "
        f"expand the frame to reveal more environment while keeping subject/action "
        f"centered. Preserve identical characters, poses, expressions, lighting.\n"
    )

    # Place source panel first (after the ref-library header), char refs follow
    header = (
        "# Visual Reference Library\n"
        "IMPORTANT: Always prioritize the visual design from the provided images "
        "over your internal concepts."
    )
    if char_refs:
        # char_refs[0] is the header — replace with ours that includes source frame
        refs = [header, source_img, source_label] + char_refs[1:]
    else:
        refs = [header, source_img, source_label]

    anchor_context = _panel_anchor_context(wide_panel, project)
    prompt_text = _build_fullframe_prompt(scene, wide_panel, aspect_ratio, prompts, anchor_context)

    try:
        img_bytes = llm.make_image(prompt_text, refs=refs, aspect_ratio=aspect_ratio, image_size='2K')
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
