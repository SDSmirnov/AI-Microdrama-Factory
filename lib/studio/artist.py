"""
Artist — character reference management and image rendering.

Consolidates safe_name, load_character_refs, generate_single_reference,
auto_cast_characters, render_character_refs, render_scene_grids, render_panels,
slice_combined, export_image_prompt from old numbered scripts.
"""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image

from lib.core.schemas import ANCHOR_SCHEMA, CHARACTER_SCHEMA, ENRICHMENT_SCHEMA, GRID_QA_SCHEMA, ROOM_DETAIL_SCHEMA, ROOM_VOCABULARY_SCHEMA, ROOM_DETAIL_SCHEMA
from lib.core.project import Project
from lib.core.utils import atomic_write, grid_dims, is_portrait, pad_to_ar, panel_boxes, safe_name
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

    Shows logline_subject_info (role) + video_visual_desc (canonical appearance)
    so the LLM can enforce appearance inheritance for character variants.
    Falls back gracefully for old JSONs missing these fields.
    """
    lines = []
    for name, info in project.character_info.items():
        role = info.get('logline_subject_info', '')
        appearance = info.get('video_visual_desc') or info.get('visual_desc', '')
        if role and appearance:
            context = f"{role} | appearance: {appearance}"
        else:
            context = role or appearance
        lines.append(f"  - {name}: {context}")
    return "\n".join(lines) if lines else "  (none yet)"


def _enrich_refs_pass(text: str, llm: BaseLLM, project: Project):
    """Pass 2: slow careful re-read for specific prop/set details not caught in pass 1.

    Appends textual findings (e.g. "coffee table has a small drawer",
    "iron safe is recessed into the left wall") to each ref's visual_desc.
    Only updates JSONs where non-empty additions are found.
    """
    if not project.character_info:
        return

    refs_block = "\n".join(
        f"  - {name}: {info.get('visual_desc', '')[:200]}"
        for name, info in project.character_info.items()
    )

    prompt = f"""You are a meticulous set designer re-reading a story text to extract specific visual details
that were missed in a first scan. Your ONLY task is to find concrete, visually actionable details
about the references listed below.

## EXISTING REFERENCES (name → current visual description excerpt):
{refs_block}

## INSTRUCTIONS
1. Re-read the text slowly, word by word.
2. For each reference, extract ONLY details explicitly stated in the text that are NOT already captured in the existing description.
   Focus on: specific props, materials, textures, colors, spatial arrangement, labels/inscriptions,
   relative positions ("clock is below the photo frame"), structural details ("drawer in the coffee table",
   "iron safe recessed into the wall"), wear/damage, lighting fixtures, brand names, etc.
3. Return ONLY references where you found new details (non-empty `visual_desc_additions`).
4. Do NOT invent details not in the text. Do NOT repeat what is already in the existing description.

Text:
<STORY>{text}</STORY>
"""

    enrichments = llm.make_json(prompt, ENRICHMENT_SCHEMA)
    if not enrichments:
        logger.info("  ℹ️  Enrichment pass: no new details found.")
        return

    updated = 0
    for item in enrichments:
        name = item.get('name', '')
        additions = item.get('visual_desc_additions', '').strip()
        if not additions or name not in project.character_info:
            if name and name not in project.character_info:
                logger.warning(f"  ⚠️  Enrichment: unknown ref '{name}' — skipping")
            continue

        sname = safe_name(name)
        json_path = project.ref_dir / f"{sname}.json"
        try:
            char = json.loads(json_path.read_text(encoding='utf-8'))
            char['visual_desc'] = f"{char['visual_desc'].rstrip('. ')}. {additions}"
            char['needs_regenerate'] = True
            json_path.write_text(json.dumps(char, indent=2), encoding='utf-8')
            project.character_info[name] = char
            logger.info(f"  ✏️  Enriched: {name} (+{len(additions)} chars)")
            updated += 1
        except Exception as e:
            logger.warning(f"  ⚠️  Failed to enrich {name}: {e}")

    logger.info(f"  ✅ Enrichment pass done: {updated}/{len(enrichments)} refs updated.")


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

APPEARANCE INHERITANCE — mandatory for character variants:
- If a new ref is the same person as an existing character (same individual, different outfit/state/context), you MUST copy their physical attributes verbatim from the existing ref's appearance field above: hair color, hair style, face, skin tone, eye color, body type, age. Only describe what actually changes (clothing, accessories, emotional state). Never invent new physical traits that contradict an existing ref.

For each NEW reference, provide:
  - name: short canonical label (letters, digits, hyphens only — no quotes or parentheses)
  - logline_subject_info: one sentence — who/what this is in the story (role, relationship, function)
  - visual_desc: detailed visual description for image generation
  - video_visual_desc: short visual summary for video/animation
  - type: Character | Location | Object | Room | Vehicle | Interface | Outdoor
  - style_reference: name of an existing or new reference to use as style base
  - variations: (PRIMARY character refs only) list of variation ref slugs — e.g. ["Alisa-Jeans", "Alisa-Gown"].
    Generate ONE variation per distinct costume/context (see casting instructions). Leave empty if character has only one look.
  - character_ref: (VARIATION refs only) parent character name — e.g. "Alisa" for "Alisa-Gown". Empty for primary refs.
  - context: (VARIATION refs only) when this variation applies — e.g. "Evening formal event, theater". Empty for primary refs.

CRITICAL — Rooms, Vehicles, and Outdoor locations MUST be split into separate per-view entries (see casting instructions above).
NEVER create a single monolithic entry with type=Room, type=Vehicle, or type=Outdoor.
A bare "Room-Name" entry with type=Room is WRONG — always use ALL SIX room views:
  "{{Room-Name}}-View-From-Entrance", "{{Room-Name}}-View-To-Entrance",
  "{{Room-Name}}-View-From-Left-Wall", "{{Room-Name}}-View-From-Right-Wall",
  "{{Room-Name}}-View-Center-To-Far", "{{Room-Name}}-View-Center-To-Entrance".
A bare "Vehicle-Name" entry with type=Vehicle is WRONG — always use "{{Vehicle-Name}}-Exterior", "{{Vehicle-Name}}-Interior-From-Entrance", "{{Vehicle-Name}}-Interior-To-Entrance".
A bare "Outdoor-Name" entry with type=Outdoor is WRONG — always use "{{Outdoor-Name}}-View-Primary" and "{{Outdoor-Name}}-View-Opposite".
visual_desc for each view entry must describe ONE camera angle only — no TOP/BOTTOM panels, no multi-panel layouts.

Text:

<STORY>{text}</STORY>
"""

    new_chars = llm.make_json(prompt, CHARACTER_SCHEMA)

    # Reject any monolithic Room/Vehicle entries without a view suffix — the LLM
    # was explicitly told to split these; a bare entry means it ignored the rule.
    _view_suffixes = {s for s, _ in _ROOM_VIEWS + _VEHICLE_VIEWS + _OUTDOOR_VIEWS}
    bad = [c for c in (new_chars or [])
           if c.get('type') in ('Room', 'Vehicle', 'Outdoor')
           and not any(c.get('name', '').endswith(f'-{s}') for s in _view_suffixes)]
    if bad:
        bad_names = [c['name'] for c in bad]
        logger.warning(
            "  ⚠️  LLM returned monolithic Room/Vehicle/Outdoor entries (not split into views): %s. "
            "Run 'make remake-room-refs' to split them, or delete and re-cast.",
            bad_names,
        )

    if new_chars:
        ctx = f"{casting_prompt_template} {setting_context}"
        max_workers = project.max_workers
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            list(executor.map(
                lambda char: generate_single_reference(char, ctx, config, project),
                new_chars
            ))
    else:
        logger.info("  ℹ️  Pass 1: no new references identified.")

    logger.info("\n🔍 CASTING PASS 2: Enriching refs with specific prop/set details...")
    try:
        _enrich_refs_pass(text, llm, project)
    except Exception as e:
        logger.warning(f"  ⚠️  Enrichment pass failed (non-fatal): {e}")


# ---------------------------------------------------------------------------
# Character reference image rendering
# ---------------------------------------------------------------------------

def _render_single_ref(char: dict, config: dict, project: Project, llm: BaseLLM, force: bool = False):
    name = char['name']
    sname = safe_name(name)
    png_path = project.ref_dir / f"{sname}.png"

    if png_path.exists() and not force:
        logger.info(f"  ⏭  Skip {name} (PNG exists)")
        return

    logger.info(f"  🎬 Rendering reference: {name}")

    refs = []
    opened_imgs = []

    ref_type = char.get('type', 'Character')
    style_ref = char.get('style_reference', '')
    if style_ref and style_ref != name:
        ref_png = project.ref_dir / f"{safe_name(style_ref)}.png"
        if ref_png.exists():
            img = Image.open(ref_png)
            opened_imgs.append(img)
            refs.append(img)
            refs.append(f"↑ Visual style reference for \"{style_ref}\" — match this aesthetic.\n")

    view_suffix = next(
        (s for s, _ in _ROOM_VIEWS if name.endswith(f'-{s}')),
        None,
    )
    anchor_points: dict = {}
    if ref_type.lower() == 'room' and view_suffix:
        # Prefer anchor_points.room_m as the authoritative dimension source
        anchor_points = char.get('anchor_points') or _load_entrance_anchor_points(name, view_suffix, project)
        room_m = anchor_points.get('room_m') if anchor_points else None
        if isinstance(room_m, (list, tuple)) and len(room_m) >= 2:
            dims_t: tuple[float, float] | None = (float(room_m[0]), float(room_m[1]))
        else:
            dims_raw = char.get('room_dims')
            dims_t = (
                (float(dims_raw[0]), float(dims_raw[1]))
                if isinstance(dims_raw, (list, tuple)) and len(dims_raw) == 2
                else _parse_room_dims(char.get('visual_desc', ''))
            )
        ref_aspect = _view_aspect_ratio(view_suffix, dims_t, config)
    else:
        ref_aspect = config.get('reference_characters', {}).get('ref_aspect_ratio', '3:4')

    anchor_block = _anchor_visibility_block(anchor_points, view_suffix) if anchor_points and view_suffix else ''

    if ref_type.lower() in ('room', 'vehicle'):
        if refs and view_suffix:
            consistency_rules = _VIEW_RENDER_CONSISTENCY.get(view_suffix, (
                "MATERIAL MATCH: ALL shared architectural elements must be identical to the style reference — "
                "wall surfaces, floor finish, ceiling, lighting fixtures, furniture."
            ))
        elif refs:
            consistency_rules = (
                "MATERIAL MATCH: ALL shared architectural elements must be identical to the style reference — "
                "wall surfaces, floor finish, ceiling, lighting fixtures, furniture."
            )
        else:
            consistency_rules = ""
        prompt_text = (
            f"CINEMATIC ENVIRONMENT REFERENCE: {name}. "
            f"{char['visual_desc']}. "
            f"{anchor_block}"
            f"Architectural photography, empty — no people, uniform studio lighting, 8k. "
            f"SINGLE IMAGE, single camera angle. "
            f"Show ONLY what is directly visible from this exact camera position within the described walls. "
            f"DO NOT show adjacent rooms, pools, corridors, or any space beyond the walls. "
            f"DO NOT add glass walls, mirrors, or openings not explicitly described. "
            f"DO NOT invent furniture, objects, or architectural features not listed above. "
            f"{consistency_rules}"
        )
    else:
        prompt_text = (
            f"CINEMATIC REFERENCE FOR {char['type']}: {name}. "
            f"{char['visual_desc']}. "
            f"Close-up, neutral expression, uniform lighting, 8k."
        )
        if ref_type.lower() == 'character':
            prompt_text += " Render character full-height."

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


def _topo_sort_refs(to_render: list) -> list:
    """Sort (char, json_path) pairs so style_reference dependencies render before dependents."""
    by_name = {c['name']: (c, jp) for c, jp in to_render}
    visited: set = set()
    result: list = []

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        pair = by_name.get(name)
        if pair is None:
            return
        dep = pair[0].get('style_reference', '')
        if dep and dep != name and dep in by_name:
            visit(dep)
        result.append(pair)

    for name in list(by_name):
        visit(name)
    return result


def render_character_refs(prompts: dict, config: dict, llm: BaseLLM, project: Project):
    """Render missing character reference portraits from ref_dir/*.json"""
    logger.info("\n🎭 RENDER REFS: Generating missing character reference portraits...")

    to_render = []
    for json_path in project.ref_dir.glob("*.json"):
        try:
            char = json.loads(json_path.read_text(encoding='utf-8'))
            name = char.get('name', '')
            if not name:
                continue
            png_missing = not (project.ref_dir / f"{safe_name(name)}.png").exists()
            if png_missing or char.get('needs_regenerate'):
                to_render.append((char, json_path))
        except Exception as e:
            logger.warning(f"  ⚠️  Could not read {json_path}: {e}")

    if not to_render:
        logger.info("  ✅ All character references already rendered.")
        return

    to_render = _topo_sort_refs(to_render)
    logger.info(f"  📋 {len(to_render)} references to render.")
    failed = []
    for c, json_path in to_render:
        before = len(project.character_images)
        _render_single_ref(c, config, project, llm, force=bool(c.get('needs_regenerate')))
        if len(project.character_images) == before:
            failed.append(c.get('name', '?'))
        elif c.get('needs_regenerate'):
            c.pop('needs_regenerate')
            atomic_write(json_path, json.dumps(c, indent=2))

    if failed:
        logger.warning(f"  ⚠️  {len(failed)}/{len(to_render)} ref(s) failed to render: {failed}. Run 'python cli.py refs' to retry.")


# ---------------------------------------------------------------------------
# Room / Vehicle ref splitting
# ---------------------------------------------------------------------------

_MULTIPANEL_MARKERS = ('top:', 'bottom:', 'top panel', 'bottom panel', '2-panel', 'two-panel',
                       'panel stacked', 'panels stacked', 'left panel', 'right panel')

_VIEW_DESC_SCHEMA = {
    'type': 'object',
    'properties': {'visual_desc': {'type': 'string'}},
    'required': ['visual_desc'],
}


def _extract_view_desc(original_desc: str, view_suffix: str, view_instruction: str,
                       llm: BaseLLM) -> str:
    """Use LLM to extract a clean single-panel visual description for one view.

    Called only when original_desc contains multi-panel layout markers.
    Returns the rewritten description, or original_desc on failure.
    """
    prompt = (
        f"The following room reference has a multi-panel visual_desc that describes "
        f"multiple camera angles (e.g. TOP/BOTTOM or left/right panels) in one block.\n\n"
        f"original visual_desc:\n{original_desc}\n\n"
        f"Extract and rewrite ONLY the part relevant to this single view:\n"
        f"View: {view_suffix}\nView instruction: {view_instruction}\n\n"
        f"Rules:\n"
        f"- Return a single coherent paragraph describing only this one camera angle.\n"
        f"- Remove all multi-panel layout language (TOP, BOTTOM, panels, etc.).\n"
        f"- Keep all specific details: furniture, materials, colours, lighting, props.\n"
        f"- Do NOT add new details not present in the original.\n"
        f"Return JSON: {{\"visual_desc\": \"...\"}}"
    )
    try:
        result = llm.make_json(prompt, schema=_VIEW_DESC_SCHEMA)
        desc = result.get('visual_desc', '').strip()
        if desc:
            return desc
    except Exception as e:
        logger.warning(f"  ⚠️  LLM view-desc extraction failed: {e}")
    return original_desc


# Y-axis views look along the room depth (entrance → far wall).
# X-axis views look across the room width (left wall → right wall).
_Y_AXIS_VIEWS = frozenset({
    'View-From-Entrance', 'View-To-Entrance',
    'View-Center-To-Far', 'View-Center-To-Entrance',
    'View-By-Far-Wall', 'View-By-Entrance',
})
_X_AXIS_VIEWS = frozenset({'View-From-Left-Wall', 'View-From-Right-Wall'})


def _parse_room_dims(visual_desc: str) -> tuple[float, float] | None:
    """Extract (width_m, depth_m) from visual_desc text.

    Prefers explicitly labelled phrases ('4m wide', '7m deep') because unlabelled
    'NxM' patterns give no hint about which axis is width vs depth.
    Returns None when dimensions cannot be reliably parsed.
    """
    desc = visual_desc.lower()
    mw = re.search(r'(\d+(?:\.\d+)?)\s*m(?:eters?)?\s+(?:wide|width|across)', desc)
    md = re.search(r'(\d+(?:\.\d+)?)\s*m(?:eters?)?\s+(?:deep|depth|long|length)', desc)
    if mw and md:
        return float(mw.group(1)), float(md.group(1))
    # Unlabelled NxM — treat first as width, second as depth only as last resort
    m = re.search(r'(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*m', desc)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def _view_aspect_ratio(view_suffix: str, dims: tuple[float, float] | None, config: dict) -> str:
    """Choose image aspect ratio for a room view from physical room dimensions.

    Y-axis views: visible horizontal span = room width.
    X-axis views: visible horizontal span = room depth.
    Falls back to config ref_aspect_ratio when dims unavailable.
    """
    fallback = config.get('reference_characters', {}).get('ref_aspect_ratio', '3:4')
    if dims is None:
        return fallback
    width, depth = dims
    if view_suffix in _Y_AXIS_VIEWS:
        return '3:4' if width < depth else '4:3'
    if view_suffix in _X_AXIS_VIEWS:
        return '16:9' if depth > width else '3:4'
    return fallback


# Camera position (cx, cy) and forward direction (fdx, fdy) per view, in normalised room coords.
_VIEW_CAMERA: dict[str, tuple[float, float, float, float]] = {
    'View-From-Entrance':      (0.5, 0.02,  0.0, +1.0),
    'View-To-Entrance':        (0.5, 0.98,  0.0, -1.0),
    'View-From-Left-Wall':     (0.02, 0.5, +1.0,  0.0),
    'View-From-Right-Wall':    (0.98, 0.5, -1.0,  0.0),
    'View-Center-To-Far':      (0.5, 0.5,   0.0, +1.0),
    'View-Center-To-Entrance': (0.5, 0.5,   0.0, -1.0),
    'View-By-Far-Wall':        (0.5, 0.85,  0.0, +1.0),
    'View-By-Entrance':        (0.5, 0.15,  0.0, -1.0),
}


def _project_image_x(obj_x: float, obj_y: float, view_suffix: str) -> float:
    """Return normalised image-x [0=image-left, 1=image-right] for an object at (obj_x, obj_y)."""
    if view_suffix in ('View-To-Entrance', 'View-Center-To-Entrance', 'View-By-Entrance'):
        return 1.0 - obj_x
    if view_suffix == 'View-From-Left-Wall':
        # entrance-side (low Y) → image-right; far-side (high Y) → image-left
        return 1.0 - obj_y
    if view_suffix == 'View-From-Right-Wall':
        # entrance-side (low Y) → image-left; far-side (high Y) → image-right
        return obj_y
    return obj_x  # View-From-Entrance, View-Center-To-Far, View-By-Far-Wall — no mirror


_VIEW_POSITION_LABEL: dict[str, str] = {
    'View-From-Entrance':      'standing at entrance doorway (y=0)',
    'View-To-Entrance':        'standing at far wall (y=1), facing entrance',
    'View-From-Left-Wall':     'at image-left wall (x=0), looking across room',
    'View-From-Right-Wall':    'at image-right wall (x=1), looking across room',
    'View-Center-To-Far':      'at room center, facing far wall',
    'View-Center-To-Entrance': 'at room center, facing entrance',
    'View-By-Far-Wall':        '1m from far wall (y≈0.85), facing far wall — close-up',
    'View-By-Entrance':        '1m from entrance (y≈0.15), facing entrance — close-up',
}
_VIEW_FACING_WALL: dict[str, str] = {
    'View-From-Entrance':      'far wall  (looking toward y=1)',
    'View-To-Entrance':        'entrance wall  (looking toward y=0)',
    'View-From-Left-Wall':     'image-right wall  (looking toward x=1)',
    'View-From-Right-Wall':    'image-left wall  (looking toward x=0)',
    'View-Center-To-Far':      'far wall  (looking toward y=1)',
    'View-Center-To-Entrance': 'entrance wall  (looking toward y=0)',
    'View-By-Far-Wall':        'far wall  (looking toward y=1)',
    'View-By-Entrance':        'entrance wall  (looking toward y=0)',
}
# Horizontal FOV in degrees; wide-angle for by-wall close shots.
_VIEW_HFOV: dict[str, int] = {
    'View-From-Entrance':      90,
    'View-To-Entrance':        90,
    'View-From-Left-Wall':     90,
    'View-From-Right-Wall':    90,
    'View-Center-To-Far':      75,
    'View-Center-To-Entrance': 75,
    'View-By-Far-Wall':        110,
    'View-By-Entrance':        110,
}


def _extract_camera_anchor_labels(camera_position: str, anchor_points: dict) -> set[str]:
    """Parse a camera_position string (e.g. 'near master-bed') and return anchor labels that match."""
    if not camera_position or not anchor_points:
        return set()
    cp = camera_position.lower()
    cp_hyphenated = cp.replace(' ', '-')
    labels = set()
    for obj in anchor_points.get('objects', []):
        label = obj.get('label', '')
        if label and (label in cp_hyphenated or label.replace('-', ' ') in cp):
            labels.add(label)
    return labels


def _anchor_visibility_block(anchor_points: dict, view_suffix: str, camera_anchor_labels: frozenset = frozenset()) -> str:
    """Produce camera setup header + per-object projected position data for a render prompt.

    Camera header describes position, facing wall, H-FOV, and perspective rules.
    For each visible anchor object outputs view-space coordinates:
      img_x   — normalised [0=image-left … 1=image-right] lateral position in this view
      depth   — normalised distance from camera along the viewing axis; also in metres when room_m present
      z       — object height (0=floor, 1=ceiling; unchanged across views)
      span    — projected footprint width in image-x (from width_x or depth_y depending on axis)

    Objects at or behind the camera plane (depth ≤ 0.02) are listed as NOT VISIBLE.
    Returns empty string when anchor_points is absent or has no objects.
    """
    objects = anchor_points.get('objects', []) if anchor_points else []
    if not objects or view_suffix not in _VIEW_CAMERA:
        return ''

    cx, cy, fdx, fdy = _VIEW_CAMERA[view_suffix]
    room_m: list = anchor_points.get('room_m') or []
    # Depth axis physical dimension: Y-axis views → room depth (room_m[1]); X-axis views → room width (room_m[0])
    depth_dim_m: float | None = (
        float(room_m[1]) if fdy != 0 and len(room_m) >= 2 else
        float(room_m[0]) if fdx != 0 and len(room_m) >= 1 else None
    )
    # Lateral axis: Y-axis views project room-X to image-X; X-axis views project room-Y to image-X.
    lateral_is_y = view_suffix in _X_AXIS_VIEWS

    def _x_label(v: float) -> str:
        if v < 0.25:
            return 'image-left'
        if v > 0.75:
            return 'image-right'
        if v < 0.42:
            return 'left-of-center'
        if v > 0.58:
            return 'right-of-center'
        return 'image-center'

    def _depth_label(d: float) -> str:
        if d < 0.15:
            return 'near-camera'
        if d < 0.40:
            return 'mid-ground'
        if d < 0.70:
            return 'background'
        return 'far-background'

    def _z_label(z: float) -> str:
        if z < 0.15:
            return 'floor-level'
        if z < 0.45:
            return 'table-height'
        if z < 0.75:
            return 'mid-height'
        return 'ceiling-level'

    # ── Camera header ──────────────────────────────────────────────────────────
    pos_label = _VIEW_POSITION_LABEL.get(view_suffix, '')
    facing = _VIEW_FACING_WALL.get(view_suffix, '')
    hfov = _VIEW_HFOV.get(view_suffix, 90)
    # Physical camera position in metres when room_m available
    room_w = float(room_m[0]) if len(room_m) >= 1 else None
    room_d = float(room_m[1]) if len(room_m) >= 2 else None
    pos_m = ''
    if room_w and room_d:
        pos_m = f'  ({cx * room_w:.1f}m from left wall, {cy * room_d:.1f}m from entrance)'
    perspective_note = (
        f"  Perspective: objects at depth 0.25 appear ~{int(1/0.25)}× larger than at depth 1.0; "
        "closer objects sit lower in frame, farther objects converge toward the horizon "
        "(eye-level ≈ z=0.45). Lateral spread widens near camera, compresses toward center at depth."
    )
    cam_lines = [
        'CAMERA SETUP:',
        f'  Position: room_x={cx:.2f}, room_y={cy:.2f}{pos_m}  — {pos_label}',
        f'  Facing:   {facing}',
        f'  H-FOV:    ~{hfov}°',
        perspective_note,
    ]

    # ── Per-object projection ──────────────────────────────────────────────────
    visible: list[str] = []
    hidden: list[str] = []

    for obj in objects:
        ox = float(obj.get('x', 0.5))
        oy = float(obj.get('y', 0.5))
        oz = float(obj.get('z', 0.3))
        wx = float(obj.get('width_x', 0.0))
        dy = float(obj.get('depth_y', 0.0))

        depth = (ox - cx) * fdx + (oy - cy) * fdy

        is_cam_anchor = obj.get('label') in camera_anchor_labels
        cam_remark = '  ← CAMERA POSITION: camera lens is placed here' if is_cam_anchor else ''

        # depth ≤ 0.02: at or behind the camera plane
        if depth <= 0.02:
            suffix = ' ← CAMERA POSITION: at/behind camera — MUST NOT appear in this view' if is_cam_anchor else ''
            hidden.append(f"  - {obj['label']}{suffix}")
            continue

        img_x = _project_image_x(ox, oy, view_suffix)
        footprint = dy if lateral_is_y else wx
        half = footprint / 2.0
        span_lo = max(0.0, img_x - half)
        span_hi = min(1.0, img_x + half)

        dist_str = f', ~{depth * depth_dim_m:.1f}m' if depth_dim_m else ''
        line = (
            f"  - {obj['label']}{cam_remark}\n"
            f"    img_x≈{img_x:.2f} ({_x_label(img_x)})"
            f"  depth≈{depth:.2f} ({_depth_label(depth)}{dist_str})"
            f"  z≈{oz:.2f} ({_z_label(oz)})"
        )
        if footprint > 0.02:
            line += f"  span img_x {span_lo:.2f}–{span_hi:.2f}"
        if is_cam_anchor:
            line += '  — do NOT render this object in mid or far background'
        visible.append(line)

    if not visible and not hidden:
        return ''

    lines: list[str] = cam_lines + ['']
    if visible:
        lines.append('OBJECTS VISIBLE FROM THIS CAMERA ANGLE (view-space coordinates):')
        lines.extend(visible)
    if hidden:
        lines.append('OBJECTS BEHIND THE CAMERA — MUST NOT APPEAR IN THIS IMAGE:')
        lines.extend(hidden)
    return '\n'.join(lines) + '\n'


def _load_entrance_anchor_points(name: str, view_suffix: str | None, project: Project) -> dict:
    """Load anchor_points from the View-From-Entrance sibling JSON, if available.

    Falls back to any anchor_points already embedded in the char dict.
    Returns empty dict when unavailable.
    """
    if view_suffix and view_suffix != 'View-From-Entrance':
        base = name[: -(len(view_suffix) + 1)]
        entrance_json = project.ref_dir / f"{safe_name(f'{base}-View-From-Entrance')}.json"
        if entrance_json.exists():
            try:
                data = json.loads(entrance_json.read_text(encoding='utf-8'))
                ap = data.get('anchor_points')
                if ap:
                    return ap
            except Exception:
                pass
    return {}


# Per-view spatial consistency note injected into the render prompt alongside the style reference.
# Tells the model HOW the reference is spatially related to this view — critical for
# lateral/rotated views where a generic "180-degree turn" rule is simply wrong.
_VIEW_RENDER_CONSISTENCY: dict[str, str] = {
    'View-To-Entrance': (
        "MATERIAL MATCH: ALL wall surfaces, floor, ceiling, fixtures, and furniture must be "
        "IDENTICAL to the style reference in material, color, and texture. "
        "SPATIAL RULE: this is a 180-degree turn — left and right are SWAPPED. "
        "Every object on the LEFT in the reference must appear on the RIGHT here, and vice versa."
    ),
    'View-Center-To-Entrance': (
        "MATERIAL MATCH: ALL materials must match the style reference exactly. "
        "SPATIAL RULE: 180-degree turn toward entrance — left/right SWAPPED vs reference. "
        "Entrance door is in the mid-background. No far wall visible."
    ),
    'View-By-Entrance': (
        "MATERIAL MATCH: entrance-wall materials and door frame must match the style reference exactly. "
        "SPATIAL RULE: left/right SWAPPED vs reference — same mirroring as View-To-Entrance."
    ),
    'View-From-Left-Wall': (
        "MATERIAL MATCH: ALL materials must match the style reference exactly. "
        "SPATIAL RULE: camera rotated 90° — now on the image-left wall looking across. "
        "The reference's image-right wall (x=1) is now the FAR WALL straight ahead. "
        "Entrance-side furniture (low Y in reference) appears image-right; "
        "far-side furniture (high Y in reference) appears image-left."
    ),
    'View-From-Right-Wall': (
        "MATERIAL MATCH: ALL materials must match the style reference exactly. "
        "SPATIAL RULE: camera rotated 90° — now on the image-right wall looking across. "
        "The reference's image-left wall (x=0) is now the FAR WALL straight ahead. "
        "Entrance-side furniture (low Y in reference) appears image-left; "
        "far-side furniture (high Y in reference) appears image-right."
    ),
    'View-Center-To-Far': (
        "MATERIAL MATCH: ALL materials must match the style reference exactly. "
        "SPATIAL RULE: SAME left/right orientation as reference — no mirroring. "
        "Camera at room center; far wall appears closer and dominates the frame."
    ),
    'View-By-Far-Wall': (
        "MATERIAL MATCH: far-wall materials, window frames, and surface details must match the style reference exactly. "
        "SPATIAL RULE: SAME left/right orientation as reference — no mirroring. "
        "Far wall fills ~80% of frame; mid-room furniture is behind the camera and NOT visible."
    ),
}


_VIEW_CAMERA_PHRASES = {
    'View-From-Entrance':      'viewed from the entrance, looking into the room',
    'View-To-Entrance':        'viewed from the far end, looking back toward the entrance',
    'View-From-Left-Wall':     'viewed from the image-left wall, looking across the room',
    'View-From-Right-Wall':    'viewed from the image-right wall, looking across the room',
    'View-Center-To-Far':      'viewed from room center, looking toward the far wall',
    'View-Center-To-Entrance': 'viewed from room center, looking toward the entrance',
    'View-By-Far-Wall':        'viewed from 1m of the far wall/window, looking at the far wall (silhouette position)',
    'View-By-Entrance':        'viewed from 1m of the entrance, looking at the entrance door (threshold position)',
    'Interior-From-Entrance':  'interior viewed from the entrance',
    'Interior-To-Entrance':    'interior viewed looking toward the entrance',
    'Exterior':                'exterior view',
    'View-Primary':            'primary direction view',
    'View-Opposite':           'opposite direction view',
}


def _view_logline(base_logline: str, view_suffix: str) -> str:
    """Build a view-specific logline_subject_info without inheriting camera-position language.

    Strips the part after the first view-position clause (', viewed', ' — ', '. ') from
    the base logline and appends the correct per-view camera phrase.
    """
    # Strip any existing view-position suffix from base
    for marker in (', viewed', ' — ', '. '):
        idx = base_logline.find(marker)
        if idx != -1:
            base_logline = base_logline[:idx]
    base_logline = base_logline.strip().rstrip('.')
    camera_phrase = _VIEW_CAMERA_PHRASES.get(view_suffix, view_suffix.replace('-', ' ').lower())
    return f"{base_logline} — {camera_phrase}"


_ROOM_VIEWS = [
    (
        'View-From-Entrance',
        'Wide shot standing at the entrance doorway, camera looking INTO the room toward the opposite wall. '
        'Use the compass wall layout from visual_desc: show the opposite wall, left wall, right wall, center floor. '
        'All furniture and decor visible from this angle must match the compass layout exactly. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-To-Entrance',
        'Wide shot standing at the far end of the room, camera looking BACK toward the entrance wall and door. '
        'CRITICAL SPATIAL RULE — 180-degree turn: left and right walls are SWAPPED relative to View-From-Entrance. '
        'What was on the LEFT when entering is now on the RIGHT. What was on the RIGHT when entering is now on the LEFT. '
        'Example: if the bar was on the IMAGE-LEFT wall in View-From-Entrance, it must appear on the IMAGE-RIGHT side of this image. '
        'Use the room layout from visual_desc to determine the correct left/right placement for each wall. '
        'Show the entrance wall with its door at the far end. '
        'All furniture and materials must be identical to the View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-From-Left-Wall',
        'Wide shot camera on the IMAGE-LEFT wall (x=0 as seen in View-From-Entrance), looking across the room toward the IMAGE-RIGHT wall. '
        'SPATIAL RE-MAPPING relative to View-From-Entrance: '
        'IMAGE-RIGHT wall (x=1) is now the FAR WALL straight ahead. '
        'Far/south wall (straight ahead in View-From-Entrance) is now image-LEFT. '
        'Entrance wall (behind camera in View-From-Entrance) is now image-RIGHT. '
        'Re-position all furniture using the room layout from visual_desc: '
        'entrance-side objects (low Y) appear image-right, far-wall objects (high Y) appear image-left. '
        'All materials and lighting identical to View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-From-Right-Wall',
        'Wide shot camera on the IMAGE-RIGHT wall (x=1 as seen in View-From-Entrance), looking across the room toward the IMAGE-LEFT wall. '
        'SPATIAL RE-MAPPING relative to View-From-Entrance: '
        'IMAGE-LEFT wall (x=0) is now the FAR WALL straight ahead. '
        'Entrance wall (behind camera in View-From-Entrance) is now image-LEFT. '
        'Far/south wall (straight ahead in View-From-Entrance) is now image-RIGHT. '
        'Re-position all furniture using the room layout from visual_desc: '
        'entrance-side objects (low Y) appear image-left, far-wall objects (high Y) appear image-right. '
        'All materials and lighting identical to View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-Center-To-Far',
        'Wide shot camera at the CENTER of the room, looking toward the FAR wall (high Y, straight ahead in View-From-Entrance). '
        'Left/right orientation SAME as View-From-Entrance: image-left wall (x=0) stays image-left, image-right wall (x=1) stays image-right. '
        'Camera is mid-room: far wall fills the mid-background; center-floor furniture dominates the foreground. '
        'Entrance wall is behind the camera and NOT visible. '
        'All materials and lighting identical to View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-Center-To-Entrance',
        'Wide shot camera at the CENTER of the room, looking toward the ENTRANCE wall (low Y, behind camera in View-From-Entrance). '
        'CRITICAL: left/right SWAPPED vs View-From-Entrance — image-left wall (x=0) is now image-RIGHT, image-right wall (x=1) is now image-LEFT. '
        'Camera is mid-room: entrance wall and door fill the mid-background; center-floor furniture dominates the foreground. '
        'Far wall is behind the camera and NOT visible. '
        'All materials and lighting identical to View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-By-Far-Wall',
        'Intimate close shot camera 1m from the FAR WALL / WINDOW side, looking toward the far wall (same axis direction as View-From-Entrance). '
        'Left/right orientation UNCHANGED vs View-From-Entrance — NO mirroring. '
        'The far wall fills ~80% of the frame: window panes, far-wall texture, any objects on the far wall dominate. '
        'CRITICAL: mid-room furniture is behind the camera — NOT visible. Only objects immediately beside the far wall appear. '
        'A small strip of floor is visible near the base of the far wall. '
        'Characters placed at this position will appear silhouetted against window light. '
        'All materials and lighting identical to View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-By-Entrance',
        'Intimate close shot camera 1m from the ENTRANCE WALL, looking toward the entrance door (same axis direction as View-To-Entrance). '
        'CRITICAL: left/right SWAPPED vs View-From-Entrance — same mirroring as View-To-Entrance. '
        'The entrance door and its frame fill ~80% of the frame. '
        'CRITICAL: mid-room furniture is behind the camera — NOT visible. Only entrance-wall objects appear. '
        'A small strip of floor is visible near the base of the entrance wall. '
        'All materials and lighting identical to View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
]

_VEHICLE_VIEWS = [
    (
        'Exterior',
        'Full exterior, three-quarter front angle, studio lighting, '
        'entire vehicle in frame, no people.',
    ),
    (
        'Interior-From-Entrance',
        'Interior cabin view looking IN from the driver/main door. '
        'Dashboard, steering wheel, front seats, controls, '
        'cabin materials. No people.',
    ),
    (
        'Interior-To-Entrance',
        'Interior cabin view looking TOWARD the entrance door from '
        'the back seat. Rear cabin, headrests, door panels, '
        'details not visible from entrance side. No people.',
    ),
]

_OUTDOOR_VIEWS = [
    (
        'View-Primary',
        'Wide establishing shot facing the primary direction as defined in the visual_desc compass layout. '
        'Show all foreground, midground, and background landmarks visible from this angle. '
        'Empty location, no people, landscape/architectural photography.',
    ),
    (
        'View-Opposite',
        'Wide establishing shot facing the OPPOSITE direction (180-degree turn from View-Primary). '
        'CRITICAL SPATIAL RULE — 180-degree turn: left and right sides are SWAPPED relative to View-Primary. '
        'What was on the LEFT in View-Primary is now on the RIGHT, and vice versa. '
        'Use the compass layout from visual_desc to determine the correct left/right placement of each landmark. '
        'All materials, lighting, and atmosphere must match View-Primary style reference. '
        'Empty location, no people, landscape/architectural photography.',
    ),
]


def _qa_and_refine_room_view(
    view_name: str,
    view_png_path: Path,
    truth_refs: list[tuple[str, Path]],
    view_data: dict,
    config: dict,
    project: Project,
    llm: BaseLLM,
    max_attempts: int = 3,
    threshold: int = 7,
) -> None:
    """QA a rendered room view and regenerate if consistency/geometry fails.

    truth_refs — list of (view_suffix, png_path) pairs used as ground truth.
    View-To-Entrance uses only [View-From-Entrance]; all other views use both.
    """
    from lib.studio.critic import analyze_room_view

    view_suffix = next(
        (s for s, _ in _ROOM_VIEWS if view_name.endswith(f'-{s}')),
        view_name.rsplit('-', 1)[-1],
    )
    # Load anchor_points for geometry-aware QA
    anchor_points = view_data.get('anchor_points') or _load_entrance_anchor_points(
        view_name, view_suffix, project
    )

    for attempt in range(1, max_attempts + 1):
        if not view_png_path.exists():
            logger.warning(f"  ⚠️  QA: PNG missing for {view_name}, skipping")
            return

        source_views: list[tuple[str, Image.Image]] = []
        for suffix, png_path in truth_refs:
            if png_path.exists():
                img = Image.open(png_path)
                source_views.append((suffix, img.copy()))
                img.close()

        if not source_views:
            logger.warning(f"  ⚠️  QA: no truth PNGs available for {view_name}, skipping")
            return

        with Image.open(view_png_path) as vi:
            view_img = vi.copy()

        result = analyze_room_view(
            llm=llm,
            view_img=view_img,
            source_views=source_views,
            view_suffix=view_suffix,
            visual_desc=view_data.get('visual_desc', ''),
            threshold=threshold,
            anchor_points=anchor_points or None,
        )
        for _, img in source_views:
            img.close()
        view_img.close()

        con = result['consistency_score']
        geo = result['geometry_score']
        need = result['needs_regeneration']
        logger.info(
            f"    QA {view_name} attempt {attempt}: consistency={con}/10 geometry={geo}/10 "
            + ("🔴 regenerate" if need else "🟢 OK")
        )
        for issue in result.get('issues', []):
            logger.info(f"      ⚠️  {issue}")

        if not need:
            return

        if attempt < max_attempts:
            regen_prompt = result.get('regeneration_prompt', '')
            if regen_prompt:
                patched = dict(view_data)
                patched['visual_desc'] = (
                    f"{view_data.get('visual_desc', '')}. CORRECTION REQUIRED: {regen_prompt}"
                )
                entrance_path = next(
                    (p for s, p in truth_refs if s == 'View-From-Entrance'), None
                )
                if entrance_path:
                    base = view_name[: -(len(view_suffix) + 1)]
                    patched['style_reference'] = f"{base}-View-From-Entrance"
                logger.info(f"    🔄 Regenerating {view_name} (attempt {attempt + 1})...")
                _render_single_ref(patched, config, project, llm, force=True)

    logger.warning(f"  ❌ {view_name} QA failed after {max_attempts} attempts")


def remake_room_refs(config: dict, llm: BaseLLM, project: Project):
    """Split monolithic Room/Vehicle refs into per-view refs and add any missing views.

    Handles two cases:
    1. Monolithic refs (no view suffix) — split into all views, render each.
    2. Already-split rooms missing new views (e.g. only have From/To-Entrance but
       not the 4+ new 8-point views) — derives them from the existing View-From-Entrance.

    All room views use View-From-Entrance as style_reference for material consistency.
    Original combined ref JSON/PNG are left untouched (not deleted).
    """
    load_character_refs(project)

    all_view_suffixes = {v[0] for v in _ROOM_VIEWS + _VEHICLE_VIEWS + _OUTDOOR_VIEWS}
    room_view_suffixes = {v[0] for v in _ROOM_VIEWS}

    # Case 1: monolithic refs — split into all views
    to_split = [
        (name, info)
        for name, info in project.character_info.items()
        if info.get('type') in ('Room', 'Vehicle', 'Outdoor')
        and not any(name.endswith(f'-{s}') for s in all_view_suffixes)
    ]

    # Case 2: rooms that have View-From-Entrance but are missing some of the 8 views.
    # Identify base names from existing View-From-Entrance refs.
    _entrance_suffix = 'View-From-Entrance'
    to_upgrade: list[tuple[str, dict]] = []
    for name, info in project.character_info.items():
        if info.get('type') == 'Room' and name.endswith(f'-{_entrance_suffix}'):
            base = name[: -(len(_entrance_suffix) + 1)]
            missing = [
                (suffix, instr) for suffix, instr in _ROOM_VIEWS
                if suffix != _entrance_suffix
                and not (project.ref_dir / f"{safe_name(f'{base}-{suffix}')}.json").exists()
            ]
            if missing:
                to_upgrade.append((base, info, missing))  # type: ignore[arg-type]

    if not to_split and not to_upgrade:
        logger.info("  ✅ All room views are up to date.")
        return

    logger.info(f"  📋 {len(to_split)} ref(s) to split, {len(to_upgrade)} room(s) to upgrade.")

    for name, info in to_split:
        rtype = info['type']
        views = _ROOM_VIEWS if rtype == 'Room' else _VEHICLE_VIEWS if rtype == 'Vehicle' else _OUTDOOR_VIEWS

        orig_desc = info['visual_desc']
        is_multipanel = any(m in orig_desc.lower() for m in _MULTIPANEL_MARKERS)
        if is_multipanel:
            logger.info(f"  🔍 Multi-panel visual_desc detected for {name} — will use LLM to extract per-view descriptions")

        # Parse room dimensions once for aspect ratio selection
        dims = _parse_room_dims(orig_desc) if rtype == 'Room' else None

        entrance_ref_name: Optional[str] = None   # first rendered view (View-From-Entrance)
        to_entrance_ref_name: Optional[str] = None  # View-To-Entrance; second truth for QA

        for view_suffix, view_instruction in views:
            view_name = f"{name}-{view_suffix}"
            view_json_path = project.ref_dir / f"{safe_name(view_name)}.json"

            if view_json_path.exists():
                logger.info(f"  ⏭  Skip JSON {view_name} (exists)")
                try:
                    existing = json.loads(view_json_path.read_text(encoding='utf-8'))
                    project.character_info[view_name] = existing
                except Exception:
                    pass
            else:
                if is_multipanel:
                    view_desc = _extract_view_desc(orig_desc, view_suffix, view_instruction, llm)
                else:
                    view_desc = f"{orig_desc}. {view_instruction}"
                # View-From-Entrance: pure T2I base — no style reference.
                # View-To-Entrance: T2I with From-Entrance as material anchor.
                # All others: pure T2I initially; QA pass will guide corrections.
                if view_suffix == 'View-From-Entrance':
                    style_ref = ''
                elif view_suffix == 'View-To-Entrance' and entrance_ref_name:
                    style_ref = entrance_ref_name
                else:
                    style_ref = ''
                new_ref: dict = {
                    'name': view_name,
                    'logline_subject_info': _view_logline(info.get('logline_subject_info', ''), view_suffix),
                    'visual_desc': view_desc,
                    'video_visual_desc': info.get('video_visual_desc', ''),
                    'type': rtype,
                    'style_reference': style_ref,
                }
                if dims and rtype == 'Room':
                    new_ref['room_dims'] = list(dims)
                view_json_path.write_text(json.dumps(new_ref, indent=2), encoding='utf-8')
                project.character_info[view_name] = new_ref
                logger.info(f"  ✅ Created JSON: {view_name}")

            view_png_path = project.ref_dir / f"{safe_name(view_name)}.png"

            # For Outdoor primary view: copy the original PNG directly (already a valid primary)
            if rtype == 'Outdoor' and entrance_ref_name is None and not view_png_path.exists():
                orig_png = project.ref_dir / f"{safe_name(name)}.png"
                if orig_png.exists():
                    view_png_path.write_bytes(orig_png.read_bytes())
                    project.character_images[view_name] = str(view_png_path)
                    logger.info(f"    📋  Copied original → {view_png_path}")

            if not view_png_path.exists():
                _render_single_ref(project.character_info[view_name], config, project, llm)
            elif view_name not in project.character_images:
                project.character_images[view_name] = str(view_png_path)

            if entrance_ref_name is None:
                entrance_ref_name = view_name
            if view_suffix == 'View-To-Entrance':
                to_entrance_ref_name = view_name

            # QA pass: all room views except View-From-Entrance
            if rtype == 'Room' and view_suffix != 'View-From-Entrance':
                truth: list[tuple[str, Path]] = []
                if entrance_ref_name:
                    ep = project.ref_dir / f"{safe_name(entrance_ref_name)}.png"
                    truth.append(('View-From-Entrance', ep))
                if view_suffix != 'View-To-Entrance' and to_entrance_ref_name:
                    tp = project.ref_dir / f"{safe_name(to_entrance_ref_name)}.png"
                    truth.append(('View-To-Entrance', tp))
                if truth:
                    _qa_and_refine_room_view(
                        view_name, view_png_path, truth,
                        project.character_info[view_name], config, project, llm,
                    )

        logger.info(f"  ✅ Split complete: {name} → {len(views)} views")
        # Clear any stale needs_regenerate from the monolithic ref — it's superseded by views.
        if info.get('needs_regenerate'):
            mono_json_path = project.ref_dir / f"{safe_name(name)}.json"
            info.pop('needs_regenerate')
            atomic_write(mono_json_path, json.dumps(info, indent=2))

    # Case 2: upgrade rooms that have View-From-Entrance but are missing new views.
    for base, entrance_info, missing_views in to_upgrade:
        entrance_ref_name = f"{base}-{_entrance_suffix}"
        to_entrance_ref_name = f"{base}-View-To-Entrance"
        logger.info(f"  🔄 Upgrading {base}: adding {len(missing_views)} missing view(s)")

        orig_desc = entrance_info['visual_desc']
        is_multipanel = any(m in orig_desc.lower() for m in _MULTIPANEL_MARKERS)
        dims = _parse_room_dims(orig_desc)

        for view_suffix, view_instruction in missing_views:
            view_name = f"{base}-{view_suffix}"
            view_json_path = project.ref_dir / f"{safe_name(view_name)}.json"

            if not view_json_path.exists():
                if is_multipanel:
                    view_desc = _extract_view_desc(orig_desc, view_suffix, view_instruction, llm)
                else:
                    view_desc = f"{orig_desc}. {view_instruction}"
                # View-To-Entrance uses From-Entrance as material anchor; others are pure T2I
                style_ref = entrance_ref_name if view_suffix == 'View-To-Entrance' else ''
                new_ref: dict = {
                    'name': view_name,
                    'logline_subject_info': _view_logline(entrance_info.get('logline_subject_info', ''), view_suffix),
                    'visual_desc': view_desc,
                    'video_visual_desc': entrance_info.get('video_visual_desc', ''),
                    'type': 'Room',
                    'style_reference': style_ref,
                }
                if dims:
                    new_ref['room_dims'] = list(dims)
                view_json_path.write_text(json.dumps(new_ref, indent=2), encoding='utf-8')
                project.character_info[view_name] = new_ref
                logger.info(f"  ✅ Created JSON: {view_name}")
            else:
                try:
                    project.character_info[view_name] = json.loads(
                        view_json_path.read_text(encoding='utf-8')
                    )
                except Exception:
                    pass

            view_png_path = project.ref_dir / f"{safe_name(view_name)}.png"
            if not view_png_path.exists():
                _render_single_ref(project.character_info[view_name], config, project, llm)
            elif view_name not in project.character_images:
                project.character_images[view_name] = str(view_png_path)

            # QA pass
            truth: list[tuple[str, Path]] = []
            ep = project.ref_dir / f"{safe_name(entrance_ref_name)}.png"
            truth.append(('View-From-Entrance', ep))
            if view_suffix != 'View-To-Entrance':
                tp = project.ref_dir / f"{safe_name(to_entrance_ref_name)}.png"
                truth.append(('View-To-Entrance', tp))
            _qa_and_refine_room_view(
                view_name, view_png_path, truth,
                project.character_info[view_name], config, project, llm,
            )

        logger.info(f"  ✅ Upgrade complete: {base}")

    logger.info("  ✅ remake-room-refs done.")


# ---------------------------------------------------------------------------
# Room anchor generation
# ---------------------------------------------------------------------------

def _generate_room_anchors(ref: dict, llm: BaseLLM, png_path=None, png_path_reverse=None) -> dict:
    """Call LLM to derive anchor_points from a View-From-Entrance room ref.

    Uses rendered PNGs (multimodal) when available; falls back to visual_desc text only.
    png_path         — View-From-Entrance image (primary; shows room interior).
    png_path_reverse — View-To-Entrance image (shows entrance wall/door, invisible in primary).
    Returns anchor dict on success, empty dict on failure.
    """
    name = ref.get('name', '?')
    desc = ref.get('visual_desc', '').strip()
    images = [p for p in (png_path, png_path_reverse) if p and Path(p).exists()]
    has_image = bool(images)
    if not desc and not has_image:
        logger.warning(f"  ⚠️  {name}: no visual_desc or PNG — skipping anchor generation")
        return {}

    if has_image:
        n = len(images)
        if n == 2:
            image_note = (
                "\nTwo images are attached:\n"
                "  Image 1 — View-From-Entrance (camera at entrance looking INTO the room).\n"
                "  Image 2 — View-To-Entrance (camera at far end looking TOWARD the entrance wall).\n"
                "Use both as the primary source of truth. Image 2 reveals the entrance wall, door frame, "
                "and objects near the entry that are behind the camera in Image 1. "
                "The text description is supplementary — resolve conflicts in favour of the images.\n"
            )
        else:
            image_note = (
                "\nAn image of the room (View-From-Entrance) is attached. Use it as the primary source "
                "of truth for spatial layout, furniture placement, and proportions. The text description "
                "is supplementary — resolve conflicts in favour of the image.\n"
            )
    else:
        image_note = ""

    prompt = (
        f"You are a spatial layout analyst. Convert the room reference below into a precise "
        f"coordinate anchor system for use by a cinematography AI.\n\n"
        f"Room reference: {name}\n"
        f"Camera view: View-From-Entrance (camera stands at the entrance looking INTO the room)."
        f"{image_note}\n"
        f"VISUAL DESCRIPTION:\n{desc}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. COORDINATE SYSTEM — all positions are normalized fractions in [0, 1]:\n"
        f"   X = fraction of room width. X=0 is the LEFT wall as it appears in the View-From-Entrance image.\n"
        f"   X=1 is the RIGHT wall as it appears in the View-From-Entrance image.\n"
        f"   X=0.5 is the center. Use the image as your ground truth for left vs right — ignore compass directions.\n"
        f"   Y = fraction of room depth. Y=0 is the entrance wall. Y=1 is the far wall (opposite the entrance).\n"
        f"   Z = fraction of room height. Z=0 is the floor. Z=1 is the ceiling.\n"
        f"   DO NOT use compass directions (North/South/East/West) anywhere in the output.\n"
        f"   Use only: 'image-left wall', 'image-right wall', 'entrance wall', 'far wall',\n"
        f"   'image-left side', 'image-right side', 'entrance-side', 'far-side'.\n"
        f"2. Estimate room_m = [width_m, depth_m] in meters (used for physical calculations only, not coordinates).\n"
        f"3. Map every significant furniture item, fixture, wall feature as a named object anchor. "
        f"   Use kebab-case ids (e.g. 'bar-counter', 'marble-table-1'). x/y/z = CENTER of the object. "
        f"   width_x = footprint width as fraction of room width (e.g. table spanning x=0.3–0.7 → width_x=0.4). "
        f"   depth_y = footprint depth as fraction of room depth. Use 0 for point features (lamps, photos, handles). "
        f"   facing_degrees_y = horizontal yaw 0–360: 0=toward entrance, 90=toward image-right, 180=toward far wall, 270=toward image-left. "
        f"   For objects with a natural facing direction (chairs, sofas, screens, desks). Use -1 for omnidirectional objects. "
        f"   In 'notes': describe position using X/Y values and image-left/image-right/entrance-side/far-side terms. "
        f"   Example: 'Against image-left wall (x≈0.05), mid-depth (y≈0.5). Faces image-right (toward center). width_x≈0.1, depth_y≈0.3, facing_degrees_y=90.'.\n"
        f"4. Define named zones (functional areas: seating clusters, bar, entrance area, etc.). "
        f"   Include x and y as the zone center in [0,1]. "
        f"   For each zone write TWO depth-stack hint strings:\n"
        f"   a) visual_disposition_hint — View-From-Entrance (camera at entrance, Y=0, looking toward far wall, Y=1). "
        f"      Y increases away from camera, so higher Y = deeper in frame. "
        f"      State the full depth chain. Use image-left/image-right for screen positions: "
        f"      x < 0.35 → image-left side (frame-left); x > 0.65 → image-right side (frame-right); else center. "
        f"      Include 'DEPTH: [nearest] → [mid] → [far background]'. "
        f"      Example: 'host at far side of desk (image-right, x≈0.7); desk surface in foreground lower-third "
        f"      between camera and host; host visible from mid-chest up above desk edge; far wall behind. "
        f"      DEPTH: entrance wall → desk foreground → host mid-ground → far wall background'.\n"
        f"   b) visual_disposition_hint_to_entrance — View-To-Entrance (camera at far wall, Y=1, looking toward entrance, Y=0). "
        f"      Depth is REVERSED: far-wall objects are now foreground, entrance is background. "
        f"      CRITICAL — image-left and image-right ARE SWAPPED: x_mirrored = 1 - x. "
        f"      x=0.1 (image-left entering) → x_mirrored=0.9 → frame-right in this view. "
        f"      x=0.9 (image-right entering) → x_mirrored=0.1 → frame-left in this view. "
        f"      NEVER copy screen directions from hint (a) — always recompute from mirrored X. "
        f"      Include 'DEPTH: [far-wall foreground] → [mid] → [entrance background]'. "
        f"      Example: sofa at x=0.05 (image-left entering, frame-left) → x_mirrored=0.95 → frame-RIGHT here. "
        f"      Write: 'Sofa in mid-ground frame-right; far-wall furniture in foreground; entrance door "
        f"      centered in background. DEPTH: far wall foreground → sofa mid-ground → entrance background'.\n"
        f"5. axes string: 'X=[0,1] image-left-to-right wall. Y=[0,1] entrance-to-far-wall. Z=[0,1] floor-to-ceiling. "
        f"   View-To-Entrance: x_mirrored = 1 - x (left↔right swap), Y depth reversed.'.\n\n"
        f"Return compact JSON only."
    )
    try:
        if has_image:
            imgs = [Image.open(p) for p in images]
            try:
                result = llm.analyze_image(imgs if len(imgs) > 1 else imgs[0], prompt, schema=ANCHOR_SCHEMA)
            finally:
                for img in imgs:
                    img.close()
        else:
            result = llm.make_json(prompt, schema=ANCHOR_SCHEMA)
        if result and result.get('zones'):
            return result
        logger.warning(f"  ⚠️  {name}: LLM returned empty anchor data")
        return {}
    except NotImplementedError:
        logger.warning(f"  ⚠️  {name}: backend does not support analyze_image — falling back to text-only")
        try:
            result = llm.make_json(prompt, schema=ANCHOR_SCHEMA)
            if result and result.get('zones'):
                return result
            return {}
        except Exception as e2:
            logger.warning(f"  ⚠️  {name}: text-only fallback also failed: {e2}")
            return {}
    except Exception as e:
        logger.warning(f"  ⚠️  {name}: anchor generation failed: {e}")
        return {}


def _generate_outdoor_anchors(ref: dict, llm: BaseLLM, png_path=None, png_path_reverse=None) -> dict:
    """Call LLM to derive anchor_points from a View-Primary outdoor ref.

    Uses rendered PNGs (multimodal) when available; falls back to visual_desc text only.
    png_path         — View-Primary image (primary; camera facing primary direction).
    png_path_reverse — View-Opposite image (shows landmarks behind the camera in View-Primary).
    Returns anchor dict on success, empty dict on failure.
    """
    name = ref.get('name', '?')
    desc = ref.get('visual_desc', '').strip()
    images = [p for p in (png_path, png_path_reverse) if p and Path(p).exists()]
    has_image = bool(images)
    if not desc and not has_image:
        logger.warning(f"  ⚠️  {name}: no visual_desc or PNG — skipping anchor generation")
        return {}

    if has_image:
        if len(images) == 2:
            image_note = (
                "\nTwo images are attached:\n"
                "  Image 1 — View-Primary (camera facing the primary direction).\n"
                "  Image 2 — View-Opposite (camera turned 180°, shows landmarks behind camera in Image 1).\n"
                "Use both as the primary source of truth. Image 2 reveals landmarks invisible in Image 1. "
                "The text description is supplementary — resolve conflicts in favour of the images.\n"
            )
        else:
            image_note = (
                "\nAn image of the location (View-Primary) is attached. Use it as the primary source of truth "
                "for spatial layout, landmark positions, and proportions. The text description is "
                "supplementary — resolve conflicts in favour of the image.\n"
            )
    else:
        image_note = ""

    prompt = (
        f"You are a spatial layout analyst. Convert the outdoor location reference below into a precise "
        f"coordinate anchor system for use by a cinematography AI.\n\n"
        f"Location reference: {name}\n"
        f"Camera view: View-Primary (camera faces the primary direction as defined in the compass layout)."
        f"{image_note}\n"
        f"VISUAL DESCRIPTION:\n{desc}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. Define a 2D coordinate origin at the center of the View-Primary frame at ground level. "
        f"   X positive = right in View-Primary (East if primary direction is North). "
        f"   Y positive = away from camera (into the scene). Z positive = up.\n"
        f"2. Estimate room_m = [width_x, depth_y] in meters — the visible span of the location.\n"
        f"3. Map every significant landmark (benches, lampposts, gates, trees, walls, paths, corners) "
        f"   as a named object anchor. Use kebab-case ids (e.g. 'east-lamppost', 'iron-gate'). "
        f"   Include 'notes' for landmarks with a clear left/right orientation.\n"
        f"4. Define named zones (functional areas: entrance zone, path center, far background, etc.). "
        f"   For each zone write TWO hint strings:\n"
        f"   a) visual_disposition_hint — View-Primary (canonical axis, camera facing primary direction). "
        f"      Self-contained phrase referencing visible landmarks. "
        f"      Example: 'standing at the LEFT edge of the iron gate, facing camera, stone wall behind'.\n"
        f"   b) visual_disposition_hint_to_entrance — View-Opposite (camera turned 180°, facing the opposite direction). "
        f"      Depth stack is REVERSED: far-end objects are now foreground, origin-end is background. "
        f"      CRITICAL — LEFT/RIGHT ARE SWAPPED: items with negative X (frame-left in View-Primary) are now frame-RIGHT. "
        f"      NEVER copy screen directions from visual_disposition_hint — always derive from negated X. "
        f"      State screen directions explicitly: 'frame-left', 'frame-right', 'left-of-center', 'right-of-center'. "
        f"      Example: if iron gate is at x=-3 (frame-left in View-Primary), it is frame-RIGHT in View-Opposite.\n"
        f"5. Add an axes string that a downstream LLM can paste into a scene prompt.\n"
        f"6. NOTE for downstream use: in View-Opposite perspective all X coordinates are negated "
        f"   (180° turn — left and right swap). State this in the axes string.\n\n"
        f"Return compact JSON only."
    )
    try:
        if has_image:
            imgs = [Image.open(p) for p in images]
            try:
                result = llm.analyze_image(imgs if len(imgs) > 1 else imgs[0], prompt, schema=ANCHOR_SCHEMA)
            finally:
                for img in imgs:
                    img.close()
        else:
            result = llm.make_json(prompt, schema=ANCHOR_SCHEMA)
        if result and result.get('zones'):
            return result
        logger.warning(f"  ⚠️  {name}: LLM returned empty anchor data")
        return {}
    except NotImplementedError:
        logger.warning(f"  ⚠️  {name}: backend does not support analyze_image — falling back to text-only")
        try:
            result = llm.make_json(prompt, schema=ANCHOR_SCHEMA)
            if result and result.get('zones'):
                return result
            return {}
        except Exception as e2:
            logger.warning(f"  ⚠️  {name}: text-only fallback also failed: {e2}")
            return {}
    except Exception as e:
        logger.warning(f"  ⚠️  {name}: anchor generation failed: {e}")
        return {}


def run_room_anchors(project: Project, llm: BaseLLM):
    """Generate anchor_points for all primary-view room and outdoor refs that lack them.

    Covers:
      - type=Room  with suffix -View-From-Entrance
      - type=Outdoor with suffix -View-Primary

    Writes anchor_points field back into each ref's JSON file.
    Idempotent: skips refs that already have anchor_points.
    """
    load_character_refs(project)

    targets = [
        (name, info)
        for name, info in project.character_info.items()
        if (
            (info.get('type') == 'Room' and name.endswith('-View-From-Entrance'))
            or (info.get('type') == 'Outdoor' and name.endswith('-View-Primary'))
        )
        and not info.get('anchor_points')
    ]

    if not targets:
        logger.info("  ✅ All primary-view room/outdoor refs already have anchor_points.")
        return

    logger.info(f"  📐 Generating anchor_points for {len(targets)} ref(s).")

    for name, info in targets:
        logger.info(f"  🔍 {name} ...")
        png_path = project.character_images.get(name)
        if info.get('type') == 'Outdoor':
            reverse_name = name.replace('-View-Primary', '-View-Opposite')
            png_reverse = project.character_images.get(reverse_name)
            anchors = _generate_outdoor_anchors(info, llm, png_path=png_path, png_path_reverse=png_reverse)
        else:
            reverse_name = name.replace('-View-From-Entrance', '-View-To-Entrance')
            png_reverse = project.character_images.get(reverse_name)
            anchors = _generate_room_anchors(info, llm, png_path=png_path, png_path_reverse=png_reverse)
        if not anchors:
            continue

        sname = safe_name(name)
        json_path = project.ref_dir / f"{sname}.json"
        try:
            current = json.loads(json_path.read_text(encoding='utf-8'))
            current['anchor_points'] = anchors
            json_path.write_text(json.dumps(current, indent=2), encoding='utf-8')
            project.character_info[name]['anchor_points'] = anchors
            n_zones = len(anchors.get('zones', []))
            n_obj = len(anchors.get('objects', []))
            logger.info(f"  ✅ {name}: {n_zones} zones, {n_obj} objects")
        except Exception as e:
            logger.warning(f"  ⚠️  Failed to save anchors for {name}: {e}")

    logger.info("  ✅ room-anchors done.")


def _build_vocabulary_prompt(base: str, text: str, views: dict) -> str:
    entrance_desc = views.get('View-From-Entrance', {}).get('visual_desc', '').strip()
    all_descs = "\n\n".join(
        f"View-From-Entrance:\n{entrance_desc}" if entrance_desc else "",
    ).strip() or entrance_desc
    return (
        "You are a set decorator and spatial design specialist.\n\n"
        "Your task: derive the definitive named-position vocabulary for this location. "
        "This vocabulary will be used to write consistent descriptions for EVERY camera view "
        "of the room, so it must be view-neutral — no image-left/right references, "
        "only room-relative terms (entrance side, far side, left wall, right wall).\n\n"
        "## NOVEL EXCERPT (who uses this space, what roles/jobs they have, "
        "what actions happen here, which props are mentioned):\n"
        f"<STORY>{text}</STORY>\n\n"
        f"## LOCATION: {base}\n\n"
        "## CURRENT BASE DESCRIPTION (View-From-Entrance):\n"
        f"{entrance_desc}\n\n"
        "## PROCESS:\n\n"
        "### STEP 1 — ENVIRONMENT TYPE REASONING\n"
        "Identify the space type (office, cafe, kitchen, garage, hospital ward, prison cell, "
        "living room, etc.). List what items are TYPICALLY present in such a space: "
        "furniture, equipment, surfaces, fixtures, materials, lighting. "
        "What would a visitor notice first? What is on every desk/counter/shelf/wall "
        "in this kind of place?\n\n"
        "### STEP 2 — STORY-REQUIRED SPECIFICS\n"
        "Re-read the novel excerpt. For each character who uses this space:\n"
        "- What is their ROLE/JOB? Role determines what is on their station:\n"
        "  a bank clerk gets a phone unit and a paper tray; a manager gets a leather chair, "
        "  a nameplate, a document inbox; a sous chef gets a mise en place rack and sharpening "
        "  steel; a mechanic apprentice gets basic hand tools, the senior gets the diagnostic "
        "  scanner and lift remote.\n"
        "- Which actions happen at their spot? What props must be physically present?\n"
        "- Which props are explicitly named in the text? Place them exactly.\n"
        "- Any recurring visits to the same spot? Give it a stable anchor label.\n\n"
        "### STEP 3 — BUILD NAMED POSITIONS\n"
        "For every named character position and every shared landmark, produce one entry:\n"
        "- id: kebab-case, character-prefixed for personal spots (amanda-desk, lena-workstation, "
        "  igors-office-chair) or object-prefixed for shared items (service-counter, repair-lift).\n"
        "- description: furniture type + exact room location (entrance-side / far-side / "
        "  left-wall / right-wall + distance estimate) + orientation + full item list on/near it.\n"
        "  Example: 'amanda-desk: 3rd glossy white plastic desk from the entrance on the "
        "  left-wall row. Ergonomic swivel chair behind it facing the right wall. "
        "  DELL 24\" monitor at center, Logitech keyboard in front, paper tray upper-right "
        "  corner, Panasonic desk phone lower-left, name holder at front edge.'\n"
        "- No vague phrases — 'standard equipment', 'various tools', 'usual items' are forbidden."
    )


def _build_view_prompt(base: str, suffix: str, view_desc: str, vocabulary: list[dict]) -> str:
    vocab_block = "\n".join(
        f"  [{item['id']}] {item['description']}" for item in vocabulary
    )
    return (
        "You are a set decorator writing a production-ready room description for a single "
        "camera view of a cinematic location.\n\n"
        f"## LOCATION: {base}\n"
        f"## VIEW: {suffix}\n\n"
        "## SHARED NAMED-POSITION VOCABULARY (use these labels and descriptions verbatim):\n"
        f"{vocab_block}\n\n"
        "## CURRENT VIEW DESCRIPTION:\n"
        f"{view_desc}\n\n"
        "## YOUR TASK\n"
        "Rewrite the current view description using the shared vocabulary above. Rules:\n"
        "1. Every named position from the vocabulary must appear with its label in backticks, "
        "placed correctly for THIS camera angle.\n"
        "2. image-left / image-right / depth order must match this specific view's perspective.\n"
        "3. Add any equipment or props from the vocabulary that the current description omits.\n"
        "4. Preserve room dimensions, ceiling height, lighting, flooring, and architectural "
        "features from the current description.\n"
        "5. End with: 'Empty room, no people, architectural photography.'\n"
        "6. Do NOT invent items not in the vocabulary or the current description."
    )


def detail_room_refs(text: str, llm: BaseLLM, project: Project, force: bool = False):
    """Enrich Room ref visual_desc with named furniture, equipment, and per-character anchor labels.

    Two-phase per room:
      Phase 1 — one LLM call derives a view-neutral named-position vocabulary (roles, equipment,
                 anchor labels). Short focused output, not view-specific.
      Phase 2 — one LLM call per view (parallel) writes the enriched visual_desc for that angle,
                 injecting the Phase 1 vocabulary verbatim.

    Runs AFTER casting, BEFORE refs. Sets needs_regenerate=True on views with existing PNGs.
    Idempotent: skips rooms where any view already carries details_applied=True unless force=True.
    """
    load_character_refs(project)

    all_suffixes = [s for s, _ in _ROOM_VIEWS]

    rooms: dict[str, dict[str, dict]] = {}
    for name, info in project.character_info.items():
        if info.get('type') != 'Room':
            continue
        for suffix in all_suffixes:
            if name.endswith(f'-{suffix}'):
                base = name[:-(len(suffix) + 1)]
                rooms.setdefault(base, {})[suffix] = info
                break

    if not rooms:
        logger.info("  ℹ️  No Room refs found.")
        return

    targets = [
        (base, views)
        for base, views in rooms.items()
        if force or not any(v.get('details_applied') for v in views.values())
    ]

    if not targets:
        logger.info("  ✅ All room refs already have details applied (use --force to redo).")
        return

    logger.info(f"  🏢 Detailing {len(targets)} room(s)...")

    for base, views in targets:
        logger.info(f"  📋 {base}: Phase 1 — building named-position vocabulary...")

        vocab_result = llm.make_json(_build_vocabulary_prompt(base, text, views), ROOM_VOCABULARY_SCHEMA)
        if not vocab_result or not vocab_result.get('named_positions'):
            logger.warning(f"  ⚠️  {base}: vocabulary pass returned nothing — skipping")
            continue

        vocabulary = vocab_result['named_positions']
        logger.info(f"  📐 {base}: {len(vocabulary)} named positions established")

        present_views = [(suffix, views[suffix]) for suffix in all_suffixes if suffix in views]

        logger.info(f"  📋 {base}: Phase 2 — enriching {len(present_views)} views in parallel...")

        def _enrich_view(args: tuple) -> tuple[str, str]:
            suffix, info = args
            full_name = f"{base}-{suffix}"
            view_desc = info.get('visual_desc', '').strip()
            result = llm.make_json(_build_view_prompt(base, suffix, view_desc, vocabulary), ROOM_DETAIL_SCHEMA)
            enriched = (result or {}).get('enriched_visual_desc', '').strip()
            return full_name, enriched

        with ThreadPoolExecutor(max_workers=project.max_workers) as executor:
            view_results = list(executor.map(_enrich_view, present_views))

        updated = 0
        for name, enriched in view_results:
            if not enriched:
                logger.warning(f"  ⚠️  {name}: empty result — skipping")
                continue
            if name not in project.character_info:
                logger.warning(f"  ⚠️  Unknown ref '{name}' — skipping")
                continue

            sname = safe_name(name)
            json_path = project.ref_dir / f"{sname}.json"
            try:
                char = json.loads(json_path.read_text(encoding='utf-8'))
                char['visual_desc'] = enriched
                char['details_applied'] = True
                if (project.ref_dir / f"{sname}.png").exists():
                    char['needs_regenerate'] = True
                json_path.write_text(json.dumps(char, indent=2), encoding='utf-8')
                project.character_info[name] = char
                logger.info(f"  ✏️  {name}: visual_desc enriched ({len(enriched)} chars)")
                updated += 1
            except Exception as e:
                logger.warning(f"  ⚠️  Failed to save {name}: {e}")

        logger.info(f"  ✅ {base}: {updated} views updated")

    logger.info("  ✅ detail-rooms done.")


# ---------------------------------------------------------------------------
# Scene grid rendering
# ---------------------------------------------------------------------------

def _grid_layout_spec(n: int, panel_ar: str, resolution: str) -> str:
    """Return the exact grid layout instruction string for N panels."""
    cols, rows, grid_ar = grid_dims(n)
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
    )
    return header


def _build_grid_prompt(scene: dict, prompts: dict, config: dict) -> str:
    """Build the text prompt for a scene grid image."""
    panel_ar = config['format'].get('panel_aspect_ratio', '9:16')
    resolution = config['image_generation'].get('image_size', '2K')

    n_panels = len(scene.get('panels', []))
    cols, rows, grid_ar = grid_dims(n_panels)
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
            f"{actor['name']}: {actor['pose']} {actor['position']}, looking at {actor['gaze_target']}, body turned to {actor['chest_direction']}, head turned to {actor['head_direction']}."
            for actor in p.get('state', {}).get('actors', []) if actor['in_frame']
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
    for name in loadable[:8]:
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
            slice_combined(path_combined, scene_id, config, project, len(scene.get('panels', [])) or 9)
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
            except Exception:
                pass
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
    _, _, grid_ar = grid_dims(n_panels)
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

def _panel_anchor_context(panel: dict, project: 'Project') -> str:
    """Return a filtered anchor visibility block for the panel's active location ref.

    Includes objects named in panel.state.anchor_refs plus any anchor referenced by
    panel.camera_position (annotated as the camera placement anchor).
    Reprojects to the view used in location_references.
    Empty string when anchor data is unavailable.
    """
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
        if obj.get('label') in include
    ]
    if not filtered['objects']:
        return ''

    return _anchor_visibility_block(filtered, view_suffix, frozenset(camera_anchors))


def _build_panel_prompt(scene: dict, panel: dict, frame_type: str, prompts: dict, aspect_ratio: str = '9:16', anchor_context: str = '') -> str:
    """Build a focused single-panel image generation prompt."""
    style_prompt = prompts.get('style', '')
    single_panel_spec = f"Render a SINGLE {aspect_ratio} portrait image. One panel only — no grid."
    imagery_prompt = prompts.get('imagery', '').replace('{grid_layout}', single_panel_spec)
    setting_context = prompts.get('setting', '')

    if frame_type == 'start':
        visual = panel.get('visual_start', '')
    elif frame_type == 'end':
        visual = panel.get('visual_end', '')
    else:  # static
        visual = panel.get('visual_start', panel.get('visual_end', ''))

    is_reversed = panel.get('is_reversed', False)

    tags = []
    if panel.get('hook_type') and panel['hook_type'] != 'none':
        tags.append(panel['hook_type'].upper())
    if panel.get('emotional_beat'):
        tags.append(panel['emotional_beat'])
    tag_str = f" [{' | '.join(tags)}]" if tags else ""

    disposition_line = f"\nDisposition: {panel['visual_disposition']}" if panel.get('visual_disposition') else ""
    anchor_block = f"\n{anchor_context}" if anchor_context else ""

    actors_info = [
        f"{actor.get('visual_ref') or actor['name']}: {actor['pose']} {actor['position']}, looking at {actor['gaze_target']}, body turned to {actor['chest_direction']}, head turned to {actor.get('head_direction')}."
        for actor in panel.get('state', {}).get('actors', []) if actor['in_frame']
    ]
    actors_line = '\n'.join(actors_info)

    prompt = f"""{style_prompt}

{imagery_prompt}

{setting_context}

Location: {scene['location']}

CONSISTENCY RULE: Maintain IDENTICAL face, hair, clothing, and body proportions as shown in the reference images.
NO CAPTIONS. NO TEXT OVERLAYS. NO WATERMARKS. NO TEARS. NO SPITTING.

Generate a SINGLE portrait image ({aspect_ratio}) for:
Panel {panel['panel_index']} — {frame_type.upper()} frame{tag_str}

Actors: {actors_line}
Visual: {visual}{disposition_line}{anchor_block}
Camera / Lighting: {" | ".join(filter(None, [scene.get("camera_master", ""), scene.get("lighting_master", ""), panel.get("lights_and_camera", "")]))}

{"**IMPORTANT: THIS IS VERTICAL PORTRAIT IMAGE, IT SHOULD BE VIEWED NORMALLY, WITHOUT ROTATION**" if is_portrait(aspect_ratio) else ""}
"""
    return prompt


def _ref_label(name: str, ref_type: str, info: str) -> str:
    """Return a type-aware annotation label that follows its reference image."""
    if ref_type in ('Location', 'Room'):
        return f"↑ SCENE ENVIRONMENT: \"{name}\" — match this background/location.\n{info}\n"
    if ref_type in ('Object', 'Vehicle', 'Interface'):
        return f"↑ PROP: \"{name}\" — match this object's appearance exactly.\n{info}\n"
    return f"↑ CHARACTER: \"{name}\" — match face, hair, clothing exactly.\n{info}\n"


def _build_ref_contents(panel: dict, project: Project) -> tuple[list, list]:
    """Build reference image content parts for a panel.

    Image comes before its text annotation so the model sees the visual first.
    Returns (contents, opened_imgs) — caller must close opened_imgs after use.
    """
    chars = list(set(panel.get('references', []) + panel.get('location_references', [])))
    ref_chars = [name for name in chars if name in project.character_images]
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
        except Exception:
            pass
        img = Image.open(png_path)
        opened_imgs.append(img)
        contents.append(img)
        contents.append(_ref_label(name, ref_type, info))
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

    anchor_context = _panel_anchor_context(panel, project)
    prompt_text = _build_panel_prompt(scene, panel, frame_type, prompts, aspect_ratio, anchor_context)

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
    anchor_context = _panel_anchor_context(panel, project)
    prompt_text = _build_panel_prompt(scene, panel, 'static', prompts, anchor_context=anchor_context)

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
    project: "Project",
    llm: "BaseLLM",
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


# ---------------------------------------------------------------------------
# Grid slicing
# ---------------------------------------------------------------------------

def slice_combined(path_combined: Path, sid: int, config: dict, project: Project, panel_count: int = 9):
    """Slice combined grid image into individual panel files, padding each to panel_aspect_ratio."""
    panels_dir = project.panels_dir
    panels_dir.mkdir(exist_ok=True)
    panel_ar = config['format'].get('panel_aspect_ratio', '9:16')

    with Image.open(path_combined) as img:
        w, h = img.size
        cols, rows, _ = grid_dims(panel_count)
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


# ---------------------------------------------------------------------------
# Image prompt export (for manual testing)
# ---------------------------------------------------------------------------

def _build_image_prompt(scene: dict, prompts: dict, config: dict) -> str:
    """Build the image generation prompt text for a scene."""
    panel_ar = config['format'].get('panel_aspect_ratio', '9:16')
    resolution = config['image_generation'].get('image_size', '2K')

    n = len(scene.get('panels', []))
    cols, rows, grid_ar = grid_dims(n)
    portrait = is_portrait(panel_ar)
    prompt = _build_prompt_header(scene, prompts, grid_layout=_grid_layout_spec(n, panel_ar, resolution))
    prompt += (
        f"**CRITICAL FORMAT:** Single image containing {n} panels (each {panel_ar}) arranged in a {cols}×{rows} grid.\n"
        + ("Each cell is a VERTICAL frame designed for mobile viewing.\n" if portrait else
           "Each cell is a HORIZONTAL frame designed for widescreen viewing.\n")
        + "SAFE ZONE per panel: compose key subjects (faces, hands, focal action) within the middle 65% of panel height.\n"
          "Top 15% and bottom 20% of each panel must remain visually uncluttered (background only — sky, wall, floor).\n"
        + ("Faces and close-ups are the primary dramatic instrument — this is vertical microdrama, not widescreen cinema.\n" if portrait else
           "Wide compositions and environmental context are the primary dramatic instrument.\n")
        + "Shallow depth of field. Subjects sharp, backgrounds contextual only.\n"
    )
    prompt += f"\nIMPORTANT: Generate SINGLE {resolution} {grid_ar} image with {n} panels in {cols}×{rows} grid layout.\n"

    for p in scene['panels']:
        prompt += f"\nPanel {p['panel_index']}:"
        if p.get('hook_type') and p['hook_type'] != 'none':
            prompt += f" [{p['hook_type'].upper()}]"
        if p.get('emotional_beat'):
            prompt += f" [{p['emotional_beat']}]"
        prompt += "\n"
        prompt += f"  Visual: {p.get('visual_start', p.get('visual_end', ''))}\n"
        if p.get('visual_disposition'):
            prompt += f"  Disposition: {p['visual_disposition']}\n"
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
