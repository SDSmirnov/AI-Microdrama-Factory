"""Spatial anchor points for room and outdoor refs."""
import json
import logging
from pathlib import Path

from PIL import Image

from lib.core.project import Project
from lib.core.schemas import ANCHOR_SCHEMA
from lib.core.utils import safe_name
from lib.llm.base import BaseLLM
from lib.studio.artist.catalog import load_character_refs

logger = logging.getLogger(__name__)


def _generate_room_anchors(ref: dict, llm: BaseLLM, png_path=None, png_path_reverse=None, extra: str = '') -> dict:
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
        f"2. Estimate room_m = [width_m, depth_m] in meters (used for physical calculations only, not coordinates). "
        f"   Also estimate room_height_m: floor-to-ceiling height in meters.\n"
        f"3. Map every significant furniture item, fixture, wall feature as a named object anchor. "
        f"   Use kebab-case ids (e.g. 'bar-counter', 'marble-table-1'). x/y/z = CENTER of the object. "
        f"   height_m = physical height of the object in meters (not a fraction); omit when unknown. "
        f"   width_x = footprint width as fraction of room width (e.g. table spanning x=0.3–0.7 → width_x=0.4). "
        f"   depth_y = footprint depth as fraction of room depth. Use 0 for point features (lamps, photos, handles). "
        f"   facing_degrees_y = horizontal yaw 0–360: 0=toward entrance, 90=toward image-right, 180=toward far wall, 270=toward image-left. "
        f"   For objects with a natural facing direction (chairs, sofas, screens, desks). Use -1 for omnidirectional objects. "
        f"   In 'notes': describe position using X/Y values and image-left/image-right/entrance-side/far-side terms. "
        f"   Example: 'Against image-left wall (x≈0.05), mid-depth (y≈0.5). Faces image-right (toward center). width_x≈0.1, depth_y≈0.3, facing_degrees_y=90.'.\n"
        f"   DOORS, hatches and gates: set hinge_side (x0/x1/y0/y1 = the end of the door along its wall where the hinges are, "
        f"or where a sliding leaf moves to), opens (the mechanism: inward/outward/double-inward/double-outward/bifold/"
        f"sliding/pocket/roll-up/up-and-over/revolving, none for an open doorway) and leaf_state (closed/ajar/open/folded) "
        f"from the description and image, and repeat mechanism, hinge, handle and state in 'notes'. "
        f"Example: entrance-wall hatch hinged on the image-left side → hinge_side='x0', lever on the image-right side.\n"
        f"4. Define named zones (functional areas: seating clusters, bar, entrance area, etc.). "
        f"   Include x and y as the zone center in [0,1]. "
        f"   A person in a hint is named by role or name only, never by looks or clothes: the character refs own them. "
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
        f"   View-To-Entrance: x_mirrored = 1 - x (left↔right swap), Y depth reversed.'.\n"
        f"{extra}\n"
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
        f"Camera view: View-Primary (camera faces the primary direction as defined in the layout)."
        f"{image_note}\n"
        f"VISUAL DESCRIPTION:\n{desc}\n\n"
        f"INSTRUCTIONS:\n"
        f"1. COORDINATE SYSTEM — every outdoor view is shot from ONE camera STATION, turning in place: "
        f"View-Primary faces +Y (ahead), View-Ortho-Primary +X (right), View-Opposite -Y (behind), "
        f"View-Ortho-Opposite -X (left). Positions are normalized fractions in [0, 1] of a box around the station:\n"
        f"   X=0 is the LEFT boundary as seen in View-Primary, X=1 the RIGHT boundary.\n"
        f"   Y=0 is the boundary BEHIND the View-Primary camera, Y=1 the far boundary it faces.\n"
        f"   Z=0 is the ground, Z=1 the top of the tallest landmark.\n"
        f"   The box spans the whole cross-section the story uses — for a street: facade, sidewalk, roadway, "
        f"far sidewalk, far facade — with the station inside it.\n"
        f"   DO NOT use compass directions (North/South/East/West) anywhere in the output.\n"
        f"2. Estimate room_m = [width_x, depth_y] in meters and station = [x, y], the camera spot "
        f"(default [0.5, 0.5]; in a street, the roadway lane beside the main facade). When the description "
        f"gives the station's distance to a landmark (a STATION line), station × room_m must reproduce it. "
        f"Building facades are objects with 'facade' in the id, spanning their full frontage.\n"
        f"   ALL FOUR HEADINGS: the other views are drawn from 3D sketches of these anchors, so map what each "
        f"heading faces — the RIGHT and LEFT sections (side wings, hedges, walls, balustrades) and the BEHIND "
        f"section (driveway, lawn, gates) — at their real distance from the station, not only what View-Primary shows.\n"
        f"3. Map every significant landmark (benches, lampposts, gates, trees, walls, paths, corners) "
        f"   as a named object anchor. Use kebab-case ids (e.g. 'right-lamppost', 'iron-gate'). "
        f"   Include 'notes' for landmarks with a clear left/right orientation.\n"
        f"4. Define named zones (functional areas: entrance zone, path center, far background, etc.). "
        f"   A person in a hint is named by role or name only, never by looks or clothes: the character refs own them. "
        f"   For each zone write TWO hint strings:\n"
        f"   a) visual_disposition_hint — View-Primary (canonical axis, camera facing primary direction). "
        f"      Self-contained phrase referencing visible landmarks. "
        f"      Example: 'standing at the LEFT edge of the iron gate, facing camera, stone wall behind'.\n"
        f"   b) visual_disposition_hint_to_entrance — View-Opposite (camera turned 180°, facing the opposite direction). "
        f"      Depth stack is REVERSED: far-end objects are now foreground, origin-end is background. "
        f"      CRITICAL — LEFT/RIGHT ARE SWAPPED: x_mirrored = 1 - x; items with x < 0.35 (frame-left in View-Primary) are now frame-RIGHT. "
        f"      NEVER copy screen directions from visual_disposition_hint — always derive from mirrored X. "
        f"      State screen directions explicitly: 'frame-left', 'frame-right', 'left-of-center', 'right-of-center'. "
        f"      Example: if iron gate is at x=0.1 (frame-left in View-Primary), it is frame-RIGHT in View-Opposite.\n"
        f"5. Add an axes string that a downstream LLM can paste into a scene prompt.\n"
        f"6. NOTE for downstream use: in View-Opposite perspective x_mirrored = 1 - x "
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


def _current_image(project: Project, name: str):
    """The view's PNG unless its JSON is marked stale: an image of the old truth would skew the anchors."""
    try:
        stale = json.loads((project.ref_dir / f"{safe_name(name)}.json").read_text(encoding='utf-8')).get('needs_regenerate')
    except (OSError, ValueError):
        stale = False
    return None if stale else project.character_images.get(name)


def run_room_anchors(project: Project, llm: BaseLLM, room_filter: set[str] | None = None):
    """Generate anchor_points for all primary-view room and outdoor refs that lack them.

    Covers:
      - type=Room  with suffix -View-From-Entrance
      - type=Outdoor with suffix -View-Primary

    room_filter limits the run to the given room base names (case-insensitive),
    so an unverified VTE cannot unlock anchors for a room that is not ready.

    Writes anchor_points field back into each ref's JSON file.
    Idempotent: skips refs that already have anchor_points.
    """
    load_character_refs(project)

    wanted = {name.lower() for name in room_filter} if room_filter else None

    def _allowed(name: str, suffix: str) -> bool:
        if not wanted:
            return True
        base = name[: -(len(suffix) + 1)]
        return base.lower() in wanted or name.lower() in wanted

    targets = [
        (name, info)
        for name, info in project.character_info.items()
        if (
            (info.get('type') == 'Room' and name.endswith('-View-From-Entrance'))
            or (info.get('type') == 'Outdoor' and name.endswith('-View-Primary'))
        )
        and not info.get('anchor_points')
        and _allowed(
            name,
            'View-From-Entrance' if info.get('type') == 'Room' else 'View-Primary',
        )
    ]

    if not targets:
        logger.info("  ✅ All primary-view room/outdoor refs already have anchor_points.")
        return

    logger.info(f"  📐 Generating anchor_points for {len(targets)} ref(s).")

    for name, info in targets:
        logger.info(f"  🔍 {name} ...")
        png_path = project.character_images.get(name)
        if info.get('type') == 'Outdoor':
            png_reverse = _current_image(project, name.replace('-View-Primary', '-View-Opposite'))
            anchors = _generate_outdoor_anchors(info, llm, png_path=png_path, png_path_reverse=png_reverse)
        else:
            png_reverse = _current_image(project, name.replace('-View-From-Entrance', '-View-To-Entrance'))
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
