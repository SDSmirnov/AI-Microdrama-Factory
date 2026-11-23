"""Reference portrait rendering."""
import json
import logging
from pathlib import Path

from PIL import Image

from lib.core.project import Project
from lib.core.prompts import NO_LABEL_TEXT
from lib.core.utils import atomic_write, safe_name
from lib.llm.base import BaseLLM
from lib.studio.artist.anchor_prompt import _anchor_visibility_block, _load_entrance_anchor_points
from lib.studio.artist.view_catalog import (
    _OUTDOOR_VIEWS, _ROOM_VIEWS, _VIEW_RENDER_CONSISTENCY, _X_AXIS_VIEWS, _Y_AXIS_VIEWS,
)
from lib.studio.artist.view_geometry import OUTDOOR_ASPECT, _parse_room_dims, _view_aspect_ratio
from lib.studio.room_geometry import behind_camera_rule, resolve_room_height_m, WALL_INSET_M

logger = logging.getLogger(__name__)


def _render_single_ref(char: dict, config: dict, project: Project, llm: BaseLLM,
                       force: bool = False, output_path: Path | None = None):
    name = char['name']
    sname = safe_name(name)
    png_path = project.ref_dir / f"{sname}.png"
    target_path = Path(output_path) if output_path else png_path

    # A staged render (output_path) must not be skipped because the live PNG
    # already exists — that is the whole point of staging a candidate.
    if output_path is None and png_path.exists() and not force:
        logger.info(f"  ⏭  Skip {name} (PNG exists)")
        return png_path

    logger.info(f"  🎬 Rendering reference: {name}")

    view_suffix = next(
        (s for s, _ in _ROOM_VIEWS + _OUTDOOR_VIEWS if name.endswith(f'-{s}')),
        None,
    )

    refs = []
    opened_imgs = []
    truth_labels: list[str] = []

    ref_type = char.get('type', 'Character')
    style_ref = char.get('style_reference', '')
    is_room = ref_type.lower() == 'room' and bool(view_suffix)
    is_outdoor_view = ref_type.lower() == 'outdoor' and bool(view_suffix)

    if is_room:
        # Room views have an explicit truth hierarchy:
        #   VFE  → no refs (base truth)
        #   VTE  → VFE only (second truth)
        #   rest → sketch + VFE + VTE
        base = name[: -(len(view_suffix) + 1)]
        vfe_png = project.ref_dir / f"{safe_name(base + '-View-From-Entrance')}.png"
        vte_png = project.ref_dir / f"{safe_name(base + '-View-To-Entrance')}.png"
        sketch_png = project.ref_dir / f"{safe_name(name)}.sketch.png"

        def _attach(path: Path, label: str) -> None:
            img = Image.open(path)
            opened_imgs.append(img)
            refs.append(img)
            refs.append(label)

        if view_suffix == 'View-To-Entrance':
            if vfe_png.exists():
                _attach(
                    vfe_png,
                    "IMAGE 1 — BASE TRUTH (View-From-Entrance): the same room seen "
                    "from the entrance. Keep every material, fixture, object identity "
                    "and object count identical. Only the camera has turned 180°.\n",
                )
                truth_labels.append('View-From-Entrance')
        elif view_suffix == 'View-From-Entrance':
            if char.get('floor_plan') and sketch_png.exists():
                _attach(sketch_png, "IMAGE 1 — FLOOR-PLAN SKETCH of this exact camera: match camera angle, lens, "
                                    "perspective, occlusion and every object's position, footprint and height; "
                                    "ignore its lines and flat colours.\n")
        else:
            index = 1
            if sketch_png.exists():
                _attach(
                    sketch_png,
                    "IMAGE 1 — LAYOUT SKETCH: match camera angle, perspective, "
                    "occlusion and object placement; ignore its lines and gray fills.\n",
                )
                index = 2
            if vfe_png.exists():
                _attach(
                    vfe_png,
                    f"IMAGE {index} — BASE TRUTH (View-From-Entrance): authoritative "
                    "for wall, floor, ceiling, fixture and furniture materials, colors, "
                    "lighting and object count.\n",
                )
                truth_labels.append('View-From-Entrance')
                index += 1
            if vte_png.exists():
                _attach(
                    vte_png,
                    f"IMAGE {index} — SECOND TRUTH (View-To-Entrance): authoritative "
                    "for the entrance wall, door, and details that are behind the camera "
                    "in the base-truth view. Match it exactly where it shows the same "
                    "elements.\n",
                )
                truth_labels.append('View-To-Entrance')

        # Legacy fallback: old room JSONs may only carry style_reference.
        if not refs and style_ref and style_ref != name:
            ref_png = project.ref_dir / f"{safe_name(style_ref)}.png"
            if ref_png.exists():
                img = Image.open(ref_png)
                opened_imgs.append(img)
                refs.append(img)
                refs.append(
                    f"↑ Visual style reference for \"{style_ref}\" — match this aesthetic.\n"
                )
    elif style_ref and style_ref != name:
        sketch_png = project.ref_dir / f"{safe_name(name)}.sketch.png"
        if ref_type.lower() == 'outdoor' and sketch_png.exists():  # derived outdoor views: geometry from the sketch
            img = Image.open(sketch_png)
            opened_imgs.append(img)
            refs += [img, "IMAGE 1 — LAYOUT SKETCH: match camera angle, perspective, occlusion and object placement; "
                          "ignore its lines and gray fills.\n"]
        ref_png = project.ref_dir / f"{safe_name(style_ref)}.png"
        if ref_png.exists():
            img = Image.open(ref_png)
            opened_imgs.append(img)
            refs.append(img)
            refs.append(
                f"↑ SAME PERSON: \"{style_ref}\" — keep face, hair, age and build IDENTICAL; "
                f"change only the outfit and accessories described below.\n"
                if style_ref == char.get('character_ref') else
                f"↑ Visual style reference for \"{style_ref}\" — match this aesthetic.\n"
            )

    anchor_points: dict = {}
    framing_note = ''
    room_height = None
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
        room_height, _ = resolve_room_height_m(
            anchor_points, char.get('visual_desc', '')
        )
        ref_aspect = _view_aspect_ratio(view_suffix, dims_t, config, room_height)
        horizontal = None
        if dims_t:
            if view_suffix in _Y_AXIS_VIEWS:
                horizontal = dims_t[0]
            elif view_suffix in _X_AXIS_VIEWS:
                horizontal = dims_t[1]
        if horizontal:
            framing_note = (
                f"FRAMING: this view faces a {horizontal:.1f} m wide, "
                f"{room_height:.1f} m high wall — compose for the {ref_aspect} "
                "frame, not the film's vertical format. "
            )
    elif is_outdoor_view:
        anchor_points = char.get('anchor_points') or _load_entrance_anchor_points(name, view_suffix, project)
        ref_aspect = OUTDOOR_ASPECT
    else:
        ref_aspect = config.get('reference_characters', {}).get('ref_aspect_ratio', '3:4')

    anchor_block = (
        _anchor_visibility_block(
            anchor_points, view_suffix,
            camera_inset_m=WALL_INSET_M if ref_type.lower() == 'room' else 0.0,
            room_height_m=room_height,
        )
        if anchor_points and view_suffix else ''
    )

    if is_room or is_outdoor_view:
        from lib.studio.room_qa import compose_render_desc
        render_desc = compose_render_desc(char)
    else:
        render_desc = char.get('visual_desc', '')

    if ref_type.lower() in ('room', 'vehicle'):
        if is_room and view_suffix == 'View-From-Entrance' and refs:
            consistency_rules = ("GEOMETRY CONTRACT: the attached sketch is the room's floor plan seen from this "
                                 "camera. Walls, openings and furniture stand exactly where it draws them; materials, "
                                 "colours and lighting come from the description. ")
        elif is_room and view_suffix != 'View-From-Entrance':
            spatial = _VIEW_RENDER_CONSISTENCY.get(view_suffix, '')
            if view_suffix == 'View-To-Entrance':
                truth_contract = (
                    "TRUTH CONTRACT: the attached View-From-Entrance image is the base truth. "
                    "This is a 180-degree turn: left and right are SWAPPED. Preserve the identity, "
                    "material and count of every object. The entrance wall and door are the "
                    "background. Do not add or remove furniture. "
                )
            else:
                truth_contract = (
                    "TRUTH CONTRACT: the attached View-From-Entrance and View-To-Entrance images "
                    "are the two truths. View-From-Entrance defines materials, colors, lighting "
                    "and object identity; View-To-Entrance defines the entrance wall and anything "
                    "hidden behind the base-truth camera. The layout sketch is geometry-only "
                    "advice. Preserve every object's identity and count; do not invent furniture. "
                )
            consistency_rules = truth_contract + spatial
        elif refs and view_suffix:
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
            f"{render_desc}. "
            f"{anchor_block}"
            f"{framing_note}"
            f"Architectural photography, empty — no people, uniform studio lighting, 8k. "
            f"SINGLE IMAGE, single camera angle. "
            f"Show ONLY what is directly visible from this exact camera position within the described walls. "
            f"DO NOT show adjacent rooms, pools, corridors, or any space beyond the walls. "
            f"DO NOT add glass walls, mirrors, or openings not explicitly described. "
            f"DO NOT invent furniture, objects, or architectural features not listed above. "
            f"{behind_camera_rule(view_suffix)} {NO_LABEL_TEXT} "
            f"{consistency_rules}"
        )
    elif is_outdoor_view:
        prompt_text = (
            f"CINEMATIC LOCATION REFERENCE: {name}. "
            f"{render_desc}. "
            f"{anchor_block}"
            "Location-scout photograph from eye height, empty — no people, no moving traffic. "
            "SINGLE IMAGE, single camera angle. "
            "DO NOT invent buildings, landmarks or street furniture not described above. "
            f"{behind_camera_rule(view_suffix)} {NO_LABEL_TEXT} "
            f"{_VIEW_RENDER_CONSISTENCY.get(view_suffix, '') if refs else ''}"
        )
    else:
        prompt_text = (
            f"CINEMATIC REFERENCE FOR {char['type']}: {name}. "
            f"{render_desc}. "
            # The "no text / no sheet" clause is measured (CRAB probes, 2026-11-11): without it
            # minimax-h3-image returns a character SHEET with lettering and an inset face crop,
            # which is then fed to panels and clips as if it were a portrait.
            + ("Full-height figure, head to toe in frame, neutral expression, uniform lighting, 8k. "
               "ONE single full-body photographic portrait on a plain dark studio backdrop. "
               "No text anywhere, no labels, no character sheet, no panels, no inset crops."
               if ref_type.lower() == 'character' else
               "Close-up, neutral expression, uniform lighting, 8k.")
        )

    try:
        img_bytes = llm.make_image(prompt_text, refs=refs, aspect_ratio=ref_aspect, image_size="1K")
        if img_bytes:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(img_bytes)
            if output_path is None:
                project.character_images[name] = str(png_path)
            logger.info(f"    ✅ Saved {target_path}")
            return target_path
        logger.error(f"    ❌ Empty response for {name}")
        return None
    except Exception as e:
        logger.error(f"    ❌ Failed to render {name}: {e}")
        return None
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


def render_character_refs(prompts: dict, config: dict, llm: BaseLLM, project: Project,
                          entrance_views_only: bool = False, no_rooms: bool = False,
                          types: set[str] | None = None):
    """Render missing character reference portraits from ref_dir/*.json.

    entrance_views_only limits room refs to the two entrance-axis views; it is
    used before anchors exist so derived views are not rendered twice.
    no_rooms leaves Room and Outdoor views to room-views: its truth chain renders them from sketches
    and QA-gates them; a render here would skip both.
    """
    logger.info("\n🎭 RENDER REFS: Generating missing character reference portraits...")

    to_render = []
    for json_path in project.ref_dir.glob("*.json"):
        try:
            char = json.loads(json_path.read_text(encoding='utf-8'))
            name = char.get('name', '')
            if not name:
                continue
            if no_rooms and char.get('type') in ('Room', 'Outdoor'):
                continue
            if types and char.get('type') not in types:
                continue
            if entrance_views_only and char.get('type') == 'Room':
                suffix = next(
                    (s for s, _ in _ROOM_VIEWS if name.endswith(f'-{s}')), None
                )
                if suffix and suffix not in ('View-From-Entrance', 'View-To-Entrance'):
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
