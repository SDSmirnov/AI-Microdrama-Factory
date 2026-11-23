"""
Critic — Grid Quality Gate.

Port of 05_grid_quality_gate.py using a vision-capable BaseLLM backend.
"""
import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from lib.core.schemas import PANEL_QA_SCHEMA, ROOM_VIEW_QA_SCHEMA
from lib.studio.archivist import match_ref
from lib.studio.qa_gate import CRITICAL_TAGGING, apply_critical_artifact_gate
from lib.core.utils import DEFAULT_OUTPUT_DIR, canonical_ref_name, grid_dims, panel_boxes, view_suffix
from lib.llm.base import BaseLLM
from lib.studio.room_geometry import WALL_INSET_M, WALL_NAMES, behind_camera_rule, resolve_room_height_m
from lib.studio.blocking import blocking_mode
from lib.studio.blocking_sketch import block_text, panel_blocking
from lib.studio.room_blocking import RoomBlocking

logger = logging.getLogger(__name__)

MAX_REFS_PER_PANEL = 6

# How many PREVIOUS panels the continuity check is given. Only the most
# recent ones matter for a spatial flip: the earlier ones are already
# superseded by the newest. Keeps the QA prompt from growing with scene
# length.
#
# MEASURED 2026-11-12 (scene 1 panel 6, gemini-3.8-flash): keeping all 5
# previous panels costs 15 121 prompt tokens, keeping the last 2 costs
# 13 452 - an 11 % cut on every judge call.
#
# NOTE: the sibling lever - downscaping the reference images - was MEASURED
# and does NOT work. 896x1200 refs and 384x512 refs cost the SAME 13 452
# prompt tokens, because Gemini already resizes an image into a single
# 768x768 tile before billing it. Do not re-add a downscale.
PREV_PANELS_FOR_QA = 2

# Maps each QA-eligible view suffix → list of truth source view suffixes.
# View-To-Entrance is checked against From-Entrance only (it's the second primary view).
# All other derived views are checked against both primary views for full consistency.
_VIEW_TRUTH_SOURCES: dict[str, list[str]] = {
    'View-To-Entrance':        ['View-From-Entrance'],
    'View-From-Left-Wall':     ['View-From-Entrance', 'View-To-Entrance'],
    'View-From-Right-Wall':    ['View-From-Entrance', 'View-To-Entrance'],
    'View-Center-To-Far':      ['View-From-Entrance', 'View-To-Entrance'],
    'View-Center-To-Entrance': ['View-From-Entrance', 'View-To-Entrance'],
    'View-By-Far-Wall':        ['View-From-Entrance', 'View-To-Entrance'],
    'View-By-Entrance':        ['View-From-Entrance', 'View-To-Entrance'],
}

_DERIVED_VIEW_SUFFIXES = tuple(_VIEW_TRUTH_SOURCES)

# Outdoor views turn in place at one station; View-Primary is the only truth image.
OUTDOOR_TRUTH = 'View-Primary'
_OUTDOOR_TRUTH_SOURCES: dict[str, list[str]] = {
    s: [OUTDOOR_TRUTH] for s in ('View-Opposite', 'View-Ortho-Primary', 'View-Ortho-Opposite')
}

# Spatial re-mapping rules per view — injected into the QA prompt so the LLM
# knows what "correct geometry" looks like for each camera position.
_VIEW_SPATIAL_RULES: dict[str, str] = {
    'View-To-Entrance': (
        "Camera at the far end of the room, looking BACK toward the entrance wall and door. "
        "CRITICAL 180-degree turn from View-From-Entrance: left/right are SWAPPED. "
        "Every object that was on the IMAGE-LEFT in View-From-Entrance must appear on the IMAGE-RIGHT here. "
        "Every object on the IMAGE-RIGHT in View-From-Entrance must appear on the IMAGE-LEFT here. "
        "Entrance wall with its door must be visible as the background. "
        "The far wall is directly behind the camera and must NOT be visible. "
        "Furniture count and type must match View-From-Entrance exactly — no pieces added or removed."
    ),
    'View-From-Left-Wall': (
        "Camera on the image-left wall (x=0), looking toward the image-right wall (x=1). "
        "The image-right wall must be the background far wall. "
        "Entrance-side objects (low Y) appear on image-right; far-side objects (high Y) appear on image-left. "
        "The entrance wall and the image-left wall are BOTH behind/beside the camera — neither should be visible as a far background."
    ),
    'View-From-Right-Wall': (
        "Camera on the image-right wall (x=1), looking toward the image-left wall (x=0). "
        "The image-left wall must be the background far wall. "
        "Entrance-side objects (low Y) appear on image-left; far-side objects (high Y) appear on image-right. "
        "The entrance wall and the image-right wall are BOTH behind/beside the camera — neither should be visible as a far background."
    ),
    'View-Center-To-Far': (
        "Camera at center of room, looking toward the far wall (high Y). "
        "Left/right orientation same as View-From-Entrance (image-left wall stays image-left). "
        "Far wall fills the mid-background — it should look closer than in View-From-Entrance. "
        "Entrance wall/door must NOT be visible — it is directly behind the camera."
    ),
    'View-Center-To-Entrance': (
        "Camera at center of room, looking toward the entrance wall (low Y). "
        "Left/right are SWAPPED vs View-From-Entrance (image-left wall is now image-right). "
        "Entrance door fills the mid-background — it should look closer than in View-To-Entrance. "
        "Far wall must NOT be visible — it is directly behind the camera."
    ),
    'View-By-Far-Wall': (
        "Camera 1m from the far wall / window side, looking toward the far wall. "
        "Left/right orientation SAME as View-From-Entrance (no mirroring). "
        "The far wall must fill ~80% of the frame — window panes and far-wall details are the dominant subject. "
        "No mid-room furniture should be visible — it is behind the camera. "
        "Entrance wall/door must NOT be visible."
    ),
    'View-Opposite': (
        "Same camera spot as View-Primary, turned 180°: left/right are SWAPPED. What lined View-Primary's "
        "image-left now lines the image-right and vice versa; what was behind the View-Primary camera is ahead."
    ),
    'View-Ortho-Primary': (
        "Same camera spot as View-Primary, turned 90° RIGHT: what lined View-Primary's image-right side "
        "(e.g. the near facade) is straight ahead, seen head-on; View-Primary's distance runs off to the image-LEFT."
    ),
    'View-Ortho-Opposite': (
        "Same camera spot as View-Primary, turned 90° LEFT: what lined View-Primary's image-left side "
        "(e.g. the far side of the street) is straight ahead, seen head-on; View-Primary's distance runs off "
        "to the image-RIGHT."
    ),
    'View-By-Entrance': (
        "Camera 1m from the entrance wall, looking toward the entrance door. "
        "Left/right are SWAPPED vs View-From-Entrance — same mirroring as View-To-Entrance. "
        "The entrance door must fill ~80% of the frame. "
        "No mid-room furniture should be visible — it is behind the camera. "
        "Far wall must NOT be visible."
    ),
}

# Room-view QA correction bands. Integer scores are compared against these
# thresholds, so the pass mark must be 9: at 8 the view is still fixable with
# targeted edits, and 5–7 needs an instructed re-render. A pass mark of 7
# would make the targeted-edit band unreachable.
ROOM_QA_PASS_THRESHOLD = 9
ROOM_QA_FULL_REGEN_BELOW = 5
ROOM_QA_INSTRUCTION_UNTIL = 7
# A re-render trades one known local defect for new unknown ones; edit instead.
ROOM_QA_MAX_LOCAL_EDITS = 3

ROOM_QA_ACTIONS = (
    'accept',
    'targeted_edit',
    'regenerate_with_instructions',
    'regenerate',
    'blocked',
)


def decide_room_view_action(
    score: float,
    *,
    pass_threshold: int = ROOM_QA_PASS_THRESHOLD,
    full_regen_below: int = ROOM_QA_FULL_REGEN_BELOW,
    instruction_until: int = ROOM_QA_INSTRUCTION_UNTIL,
) -> str:
    """Map the worst room-view score onto a deterministic correction action.

    < 5      → regenerate (clear accumulated corrections and start over)
    5–7      → regenerate_with_instructions (append corrections)
    8        → targeted_edit (edit the delivered image)
    >= 9     → accept

    The bands are expressed on the *minimum* of the style, architecture and
    geometry scores: one badly wrong dimension is enough to fail the view.
    """
    if score >= pass_threshold:
        return 'accept'
    if score > instruction_until:
        return 'targeted_edit'
    if score >= full_regen_below:
        return 'regenerate_with_instructions'
    return 'regenerate'


def _coerce_score(value: Any, default: int = 0) -> int:
    try:
        return max(0, min(10, int(round(float(value)))))
    except (TypeError, ValueError):
        return default


def _issue_to_text(issue: Any) -> str:
    if isinstance(issue, str):
        return issue
    if not isinstance(issue, dict):
        return str(issue)
    category = str(issue.get('category') or '').strip()
    observed = str(issue.get('observed') or '').strip()
    expected = str(issue.get('expected') or '').strip()
    obj = str(issue.get('object') or '').strip()
    if observed or expected:
        subject = f"{obj}: " if obj else ''
        text = f"{subject}{observed or '?'}"
        if expected:
            text += f" (expected: {expected})"
    else:
        text = str(issue.get('details') or issue.get('target') or '').strip() or 'unspecified issue'
    return f"[{category}] {text}" if category else text


def _is_local_fix(issue_details: list[dict], edit_instructions: list[dict]) -> bool:
    """True when the judge's edit ops cover a small, object-level defect set."""
    if not 0 < len(edit_instructions) <= ROOM_QA_MAX_LOCAL_EDITS:
        return False
    return not any(
        issue.get('severity') == 'high' and issue.get('category') in ('style', 'geometry')
        for issue in issue_details
    )


def normalize_room_view_qa(
    result: dict,
    *,
    pass_threshold: int = ROOM_QA_PASS_THRESHOLD,
    api_error: bool = False,
) -> dict:
    """Normalise a QA response to the current contract, keeping old keys usable.

    The judge is asked for style/architecture/geometry scores and an action, but
    older backends and test doubles may return only ``consistency_score`` and
    ``geometry_score``. Both shapes land here, so callers see one structure.
    """
    raw = dict(result or {})
    style = _coerce_score(raw.get('style_score', raw.get('consistency_score', 0)))
    architecture = _coerce_score(
        raw.get('architecture_score', raw.get('consistency_score', style))
    )
    geometry = _coerce_score(raw.get('geometry_score', style))
    overall = min(style, architecture, geometry)

    if api_error or raw.get('api_error'):
        action = 'blocked'
        status = 'blocked'
    else:
        action = decide_room_view_action(overall, pass_threshold=pass_threshold)
        status = 'passed' if action == 'accept' else 'failed'

    raw_issues = raw.get('issues') or []
    if not isinstance(raw_issues, list):
        raw_issues = [raw_issues]
    issues = [_issue_to_text(issue) for issue in raw_issues]
    issue_details = [issue for issue in raw_issues if isinstance(issue, dict)]

    edit_instructions = raw.get('edit_instructions') or []
    if not isinstance(edit_instructions, list):
        edit_instructions = []
    edit_instructions = [i for i in edit_instructions if isinstance(i, dict)]
    if action == 'regenerate_with_instructions' and _is_local_fix(issue_details, edit_instructions):
        action = 'targeted_edit'
    if (action not in ('accept', 'blocked') and overall >= ROOM_QA_INSTRUCTION_UNTIL
            and issue_details and all(i.get('severity') == 'low' for i in issue_details)):
        action, status = 'accept', 'passed'

    normalized = {
        'style_score': style,
        'architecture_score': architecture,
        'geometry_score': geometry,
        'overall_score': overall,
        'action': action,
        'status': status,
        # Compatibility aliases used by the legacy QA/refine loop.
        'consistency_score': min(style, architecture),
        'needs_regeneration': action not in ('accept', 'blocked'),
        'issues': issues,
        'issue_details': issue_details,
        'regeneration_prompt': str(raw.get('regeneration_prompt') or '').strip(),
        'edit_instructions': edit_instructions,
        'edit_prompt': str(raw.get('edit_prompt') or '').strip(),
        'api_error': bool(api_error or raw.get('api_error')),
    }
    if raw.get('error'):
        normalized['error'] = str(raw['error'])
    return normalized



def _compute_background_ground_truth(panel_meta: Dict, ref_catalog: Dict[str, Dict]) -> str:
    """Return a SPATIAL GROUND TRUTH block for injection into the critic prompt.

    Uses camera_x/y from panel_meta and subject anchor coords from anchor_points
    to compute the expected background wall via camera→subject→wall ray projection.
    Returns empty string when data is insufficient.
    """
    cx = panel_meta.get('camera_x')
    cy = panel_meta.get('camera_y')
    if cx is None or cy is None:
        return ''

    anchor_points = None
    for ref_name in panel_meta.get('location_references', []):
        entry = ref_catalog.get(canonical_ref_name(ref_name)) or ref_catalog.get(ref_name)
        if entry:
            ap = entry.get('json', {}).get('anchor_points')
            if ap:
                anchor_points = ap
                break

    if not anchor_points:
        return ''

    objects_by_id = {o['id']: o for o in anchor_points.get('objects', [])}

    # Find the primary in-frame subject and resolve their anchor
    lines = []
    for actor in panel_meta.get('state', {}).get('actors', []):
        if not actor.get('in_frame'):
            continue
        # Parse actor's position string for [bracket-ids] first (actor-specific),
        # then fall back to state-level anchor_refs (shared, less precise)
        anchor_ids = re.findall(r'\[([^\]]+)\]', actor.get('position', ''))
        if not anchor_ids:
            anchor_ids = list(panel_meta.get('state', {}).get('anchor_refs', []))

        # Prefer anchors with facing_degrees_y >= 0 (chairs/seats — more precise for background)
        # over omnidirectional objects (tables, -1 or missing). Try facing anchors first.
        sub_obj = None
        candidates_plain = []
        for aid in anchor_ids:
            obj = objects_by_id.get(aid)
            if obj and obj.get('x') is not None and obj.get('y') is not None:
                if obj.get('facing_degrees_y', -1) >= 0:
                    sub_obj = obj
                    break
                candidates_plain.append(obj)
        if sub_obj is None and candidates_plain:
            sub_obj = candidates_plain[0]

        if sub_obj is None:
            continue

        sx, sy = sub_obj['x'], sub_obj['y']
        dx, dy = sx - cx, sy - cy
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            continue  # camera on top of subject — degenerate

        # Find smallest positive t for each wall
        candidates = {}
        if dx < -1e-6:
            candidates['x0'] = sx / (-dx)
        elif dx > 1e-6:
            candidates['x1'] = (1 - sx) / dx
        if dy < -1e-6:
            candidates['y0'] = sy / (-dy)
        elif dy > 1e-6:
            candidates['y1'] = (1 - sy) / dy

        if not candidates:
            continue
        wall_key = min(candidates, key=candidates.get)
        wall_label = WALL_NAMES[wall_key]

        # Cross-check with facing_degrees_y on the subject's anchor (chair etc.)
        facing = sub_obj.get('facing_degrees_y', -1)
        facing_note = ''
        if facing >= 0:
            # back wall = OPPOSITE of facing direction
            # facing 0=toward entrance(y0)  → back=far wall(y1)
            # facing 90=toward image-right(x1) → back=image-left(x0)
            # facing 180=toward far wall(y1)  → back=entrance(y0)
            # facing 270=toward image-left(x0) → back=image-right(x1)
            back_map = [(315, 45, 'y1'), (45, 135, 'x0'), (135, 225, 'y0'), (225, 315, 'x1')]
            back_wall = None
            for lo, hi, w in back_map:
                if lo <= hi:
                    if lo <= facing < hi:
                        back_wall = w
                        break
                else:  # wraps 315→360→45
                    if facing >= lo or facing < hi:
                        back_wall = w
                        break
            if back_wall and back_wall != wall_key:
                facing_note = f' (chair facing_degrees_y={facing:.0f}° suggests back toward {WALL_NAMES[back_wall]}; ray projection takes precedence)'
            elif back_wall:
                facing_note = f' (confirmed by chair facing_degrees_y={facing:.0f}°)'

        lines.append(
            f"  {actor['name']}: camera ({cx:.2f},{cy:.2f}) → anchor \"{sub_obj['id']}\" ({sx:.2f},{sy:.2f})"
            f" → ray direction ({dx:.2f},{dy:.2f}) → exits through {wall_label}{facing_note}."
        )

    if not lines:
        return ''

    return (
        "\n## SPATIAL GROUND TRUTH — AUTHORITATIVE, DO NOT CONTRADICT\n\n"
        "The background visible behind each subject was determined geometrically by projecting "
        "a ray from the camera position through the subject's anchor and finding which room wall "
        "it exits through. This is the CORRECT background for the camera angle used.\n\n"
        "**DO NOT flag the following backgrounds as spatial errors:**\n"
        + '\n'.join(lines)
        + "\n\nIf the rendered image shows content consistent with the expected wall above, "
        "it is CORRECT. Flag as a spatial error ONLY if the image shows a wall that is "
        "geometrically impossible given the camera position — e.g., the opposite wall appears "
        "behind the subject when the ray clearly exits through a different wall.\n"
    )


def _compute_anchor_visibility(panel_meta: Dict, ref_catalog: Dict[str, Dict]) -> str:
    """Return a filtered anchor visibility block for the panel's active location ref.

    Includes objects named in panel.state.anchor_refs plus any anchor referenced by
    panel.camera_position (annotated as the camera placement anchor).
    Mirrors _panel_anchor_context from artist.py but operates on ref_catalog.
    Returns empty string when anchor data is unavailable.
    """
    anchor_refs = set(panel_meta.get('state', {}).get('anchor_refs', []))

    from lib.studio.artist import (_anchor_id, _anchor_visibility_block, _extract_camera_anchor_labels,
                                   _panel_camera_xy, panel_anchor_block_enabled)
    if not panel_anchor_block_enabled():
        return ''

    view = None
    anchor_points = None
    for ref_name in panel_meta.get('location_references', []):
        view = view_suffix(ref_name)
        if not view:
            continue
        entry = ref_catalog.get(canonical_ref_name(ref_name)) or ref_catalog.get(ref_name)
        if entry:
            anchor_points = entry.get('json', {}).get('anchor_points')
        break

    if not anchor_points or not view:
        return ''

    camera_anchors = _extract_camera_anchor_labels(panel_meta.get('camera_position', ''), anchor_points)
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

    block = _anchor_visibility_block(filtered, view, frozenset(camera_anchors), _panel_camera_xy(panel_meta))
    if not block:
        return ''
    return '\n## ANCHOR POSITIONS IN THIS VIEW (view-space coordinates)\n' + block


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_ref_catalog(ref_dir: Path) -> Dict[str, Dict]:
    """Build catalog: { "Name": { "json": {...}, "img_path": Path, ... } }"""
    catalog: Dict[str, Dict] = {}
    if not ref_dir.exists():
        logger.warning(f"⚠️  Ref dir not found: {ref_dir}")
        return catalog

    for json_file in ref_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"⚠️  Unreadable ref {json_file.name}: {e}")
            continue

        name = data.get("name", json_file.stem)
        img_path = json_file.with_suffix(".png")

        entry: Dict[str, Any] = {
            "json": data,
            "img_path": img_path if img_path.exists() else None,
            "visual_desc": data.get("visual_desc", ""),
            "video_visual_desc": data.get("video_visual_desc", ""),
            "type": data.get("type", "unknown"),
        }
        catalog[name] = entry
        norm = name.lower().replace(" ", "_").replace("-", "_")
        if norm != name:
            catalog[norm] = entry

    logger.info(f"📂 Loaded {len(set(id(v) for v in catalog.values()))} refs from {ref_dir}")
    return catalog


def find_ref(name: str, catalog: Dict[str, Dict]) -> Optional[Dict]:
    if name in catalog:
        return catalog[name]
    norm = name.lower().replace(" ", "_").replace("-", "_").replace("'", "").replace('"', "")
    if norm in catalog:
        return catalog[norm]
    title = name.replace("-", " ").replace("_", " ").title().replace(" ", "_")
    if title in catalog:
        return catalog[title]
    return catalog.get(match_ref(name, catalog))


# ---------------------------------------------------------------------------
# Grid slicing
# ---------------------------------------------------------------------------

def slice_grid(grid_path: Path, panels_count: int) -> List[Image.Image]:
    with Image.open(grid_path) as img:
        w, h = img.size
        cols, rows, _ = grid_dims(panels_count)
        return [img.crop(box).copy() for box in panel_boxes(w, h, cols, rows, panels_count)]


# ---------------------------------------------------------------------------
# Panel analysis
# ---------------------------------------------------------------------------

def _blocking_qa_block(panel_meta: Dict, scene_meta: Dict, ref_catalog: Dict[str, Dict],
                       size: tuple[int, int]) -> tuple[str, bool]:
    """(people → frame truth, replaces the anchor block) projected with the judged image's own aspect."""
    if blocking_mode() == 'off':
        return '', False
    blocking = panel_blocking(panel_meta, scene_meta,
                              lambda n: (find_ref(n, ref_catalog) or {}).get('json'), f'{size[0]}:{size[1]}')
    if blocking is None:
        return '', False
    car = not isinstance(blocking, RoomBlocking)
    return (
        "\n## BLOCKING GROUND TRUTH\n"
        f"{block_text(blocking)}\n"
        "Check every visible person against this list. A mirrored frame side (a person on frame-left who must be "
        f"on frame-right), a person drawn who must be out of frame, {'a wrong seat or an extra seat row' if car else 'a person at the wrong furniture or a wrong posture'}, "
        "or a camera position the location cannot hold is a CRITICAL artifact: prefix each with "
        "'BLOCKING:', cap composition_match at 4 and set needs_refinement.\n"
    ), car


def analyze_panel(
    llm: BaseLLM,
    panel_img: Image.Image,
    panel_meta: Dict,
    scene_meta: Dict,
    ref_catalog: Dict[str, Dict],
    scene_id: int,
    panel_id: int,
    threshold: int,
    prev_scene_terminal: str = None,
    prompts: dict = None,
) -> Dict:
    char_ref_names = panel_meta.get("references", [])
    loc_ref_names = panel_meta.get("location_references", [])
    ref_names = list(dict.fromkeys(char_ref_names + loc_ref_names))  # preserve order, dedupe
    ref_images_content: List[Any] = []
    ref_descriptions: List[str] = []
    loaded_refs: List[str] = []

    opened_ref_imgs: List[Image.Image] = []
    for rname in ref_names[:MAX_REFS_PER_PANEL]:
        ref = find_ref(rname, ref_catalog)
        if ref and ref.get("img_path"):
            try:
                rimg = Image.open(ref["img_path"])
                opened_ref_imgs.append(rimg)
                desc = ref.get("video_visual_desc") or ref.get("visual_desc", "")
                ref_type = ref.get("type", "?")
                # Image before annotation — model sees visual before reading label
                ref_images_content.append(rimg)
                ref_images_content.append(f'↑ Reference "{rname}" ({ref_type}):\n{desc}')
                ref_descriptions.append(f"- {rname}: {desc[:200]}")
                loaded_refs.append(rname)
            except Exception as e:
                logger.warning(f"  ⚠️  Could not load ref {rname}: {e}")

    visual_start = panel_meta.get("visual_start", "")
    visual_end = panel_meta.get("visual_end", "")
    visual_desc = visual_start or visual_end
    actors_info = [
        f"{a.get('name','?')}: {a.get('pose','')} {a.get('position','')}, looking at {a.get('gaze_target','?')}, body turned to {a.get('chest_direction','?')}, head turned to {a.get('head_direction','?')}."
        for a in panel_meta.get('state', {}).get('actors', []) if a.get('in_frame')
    ]
    actors_line = ' '.join(actors_info)

    # Derive camera_direction from location_references for PROFILE consistency check.
    _VIEW_TO_CAMERA_DIR: dict[str, str] = {
        'View-From-Entrance':      'toward far wall (camera at entrance, y≈0 → looking toward y=1)',
        'View-Center-To-Far':      'toward far wall (camera at center → looking toward y=1)',
        'View-By-Far-Wall':        'toward far wall (camera near far wall → looking toward y=1)',
        'View-Primary':            'toward primary landmark (away from camera)',
        'Interior-From-Entrance':  'toward interior/far end (away from entrance)',
        'View-To-Entrance':        'toward entrance (camera at far wall, y≈1 → looking toward y=0)',
        'View-Center-To-Entrance': 'toward entrance (camera at center → looking toward y=0)',
        'View-By-Entrance':        'toward entrance (camera near entrance → looking toward y=0)',
        'View-Opposite':           'toward opposite landmark (away from primary)',
        'Interior-To-Entrance':    'toward entrance/exit (away from interior)',
        'View-From-Left-Wall':     'toward right wall (camera at x=0 → looking toward x=1)',
        'View-From-Right-Wall':    'toward left wall (camera at x=1 → looking toward x=0)',
        'View-Ortho-Primary':      'toward the x=1 side (camera at the station, 90° right of primary)',
        'View-Ortho-Opposite':     'toward the x=0 side (camera at the station, 90° left of primary)',
    }
    camera_direction = ''
    for loc_ref in panel_meta.get('location_references', []):
        for suffix, direction in _VIEW_TO_CAMERA_DIR.items():
            if loc_ref.endswith(suffix):
                camera_direction = direction
                break
        if camera_direction:
            break
    prev_panels = [
        {
            'panel_index': p['panel_index'],
            'visual_desc': p['visual_end'],
            'lights_and_camera': p.get('lights_and_camera', ''),
            'references': p.get('references', []) + p.get('location_references', []),
            **({'visual_disposition': p['visual_disposition']} if p.get('visual_disposition') else {}),
        }
        for p in scene_meta.get('panels', [])
        if p['panel_index'] < panel_meta['panel_index']
    ]
    if len(prev_panels) > PREV_PANELS_FOR_QA:
        prev_panels = prev_panels[-PREV_PANELS_FOR_QA:]

    inter_scene_block = ""
    if panel_id == 1 and prev_scene_terminal:
        inter_scene_block = f"""
## PREVIOUS SCENE TERMINAL FRAME (cross-scene continuity check)
The previous scene ended on this visual state:
{prev_scene_terminal}
Check panel 1: does it maintain spatial continuity (location, lighting, character positions)?
If a location change or time-skip occurs, it must be stated explicitly in visual_start.
Flag in artifacts if there is an unexplained discontinuity.
"""

    dramatic_intensity_panel_type = "  Evaluate: is there a visible power struggle, physical threat, raw emotion on a face, or a visual secret in the frame?"

    spatial_ground_truth = _compute_background_ground_truth(panel_meta, ref_catalog)
    people, replaces_anchors = _blocking_qa_block(panel_meta, scene_meta, ref_catalog, panel_img.size)
    anchor_visibility = people + ('' if replaces_anchors else _compute_anchor_visibility(panel_meta, ref_catalog))

    qa_criteria = (prompts or {}).get('qa', '')
    if qa_criteria:
        scoring_section = (
            qa_criteria
            .replace('__THRESHOLD__', str(threshold))
            .replace('__DRAMATIC_INTENSITY_PANEL_TYPE__', dramatic_intensity_panel_type)
        )
    else:
        scoring_section = f"""You are a QA supervisor for an AI film production pipeline.

## SCORING CRITERIA
- **fidelity** (0-10): Overall match to the description above.
- **character_consistency** (0-10): Do characters match the reference images?
  Check: face shape, hair color/style, age, build, clothing, helmet design.
  If the same character appears different from their reference, score LOW.
  Score 0 if no character references were expected for this panel.
- **composition_match** (0-10): Does the shot type, angle, framing match?
- **dramatic_intensity** (0-10): Is this panel dramatically engaging?
  Ask: could this frame stop a scrolling thumb in 0.3 seconds?
  10 = maximum visible tension, conflict, or emotional shock — impossible to look away.
  0 = static, generic, no visible conflict, inert pose, nothing at stake.
  A technically perfect but empty panel (no conflict, no hook, no subtext) scores 0 and is DEFECTIVE.
{dramatic_intensity_panel_type}
  **Animation seed exception**: If "Motion intent" below is non-empty, this panel is a START KEYFRAME for I2V animation. The I2V model will animate the face and body from this initial pose — the target expression (smirk, sneer, glare, etc.) will emerge during animation. Do NOT penalize a neutral or transitional initial expression (e.g., "generic smile" vs. "smirk"). Score `dramatic_intensity` on pose, body language, spatial tension, and staging — not on whether the final target expression is already visible.
- **artifacts**: List ALL visual problems (extra limbs, wrong face, melted features,
  text overlays, wrong number of people, missing objects, etc.)
- **needs_refinement**: True if fidelity < {threshold} OR character_consistency < {threshold}
  OR dramatic_intensity < {threshold} OR critical artifacts exist.
- **refinement_prompt**: If needs_refinement, describe EXACTLY what to fix.
  For character/fidelity issues: "Character's face does not match reference — wrong jaw shape, hair should be silver not brown."
  For dramatic_intensity failures: specify the concrete visual element to add or change — power indicator, emotional expression, or stake object.
  Example: "Panel is static and inert. Add visible power imbalance: reframe so character A stands over seated character B. Add character A's hand resting on B's shoulder from above. Insert a prop in foreground (unsigned contract, phone with lit screen) to signal what is at stake. B's face should show jaw clenched, eyes averted downward — not neutral."
  Never write "panel lacks drama" — write what specific visual element would create it.

## IMPORTANT
- Compare character faces CAREFULLY against reference images.
- Even small differences (hair color, eye color, facial structure) matter.
- A panel with beautiful composition but WRONG character face scores LOW on character_consistency.
- Panels without character references (landscapes, objects) can score 0 on character_consistency
  without needing refinement for that reason.
- Check narrative continuity
"""

    prompt = f"""{scoring_section}
{CRITICAL_TAGGING}{spatial_ground_truth}{anchor_visibility}
## TASK
Analyze this PANEL IMAGE against its script description and character references.
Score the visual fidelity and decide if the panel needs regeneration.

## SCENE CONTEXT
Scene ID: {scene_meta.get('scene_id')}
Location: {scene_meta.get('location', 'N/A')}
Setup: {scene_meta.get('pre_action_description', '')}
Camera master: {scene_meta.get('camera_master', 'N/A')}
Lighting master: {scene_meta.get('lighting_master', 'N/A')}
{inter_scene_block}
## PREVIOUS PANELS - FOR CONTEXT AND CONSISTENCY CHECKS
<PREV_PANELS>{json.dumps(prev_panels, ensure_ascii=False, indent=2)}</PREV_PANELS>

## ANALYZED PANEL {panel_id} DESCRIPTION
Panel type: {panel_meta.get('panel_type', 'narrative')}{f"  |  Hook: {panel_meta['hook_type']}" if panel_meta.get('hook_type') and panel_meta['hook_type'] != 'none' else ''}{f"  |  Emotional beat: {panel_meta['emotional_beat']}" if panel_meta.get('emotional_beat') else ''}
{f"Actors: {actors_line}" + chr(10) if actors_line else ""}Visual (start frame rendered): {visual_desc}
{f"Visual (end state after motion): {visual_end}" + chr(10) if visual_end and visual_end != visual_desc else ""}{f"Disposition: {panel_meta['visual_disposition']}" + chr(10) if panel_meta.get('visual_disposition') else ""}Camera/Lighting: {panel_meta.get('lights_and_camera', '')}
{f"Camera direction: {camera_direction}" + chr(10) if camera_direction else ""}Motion intent: {panel_meta.get('motion_prompt', '')[:300]}
Expected characters/objects: {', '.join(ref_names) if ref_names else 'None specified'}

"""

    image_contents: List[Any] = []
    if ref_images_content:
        image_contents.append("# CHARACTER/OBJECT REFERENCE IMAGES\n")
        image_contents.extend(ref_images_content)
    image_contents.append(f"\n# PANEL {panel_id} TO ANALYZE\n")
    image_contents.append(panel_img)

    try:
        result = llm.analyze_image(
            image=image_contents,
            prompt=prompt,
            schema=PANEL_QA_SCHEMA,
        )
    except Exception as e:
        logger.error(f"  ❌ Gemini error scene {scene_id} panel {panel_id}: {e}")
        result = {
            "fidelity": 0,
            "character_consistency": 0,
            "composition_match": 0,
            "dramatic_intensity": 0,
            "artifacts": [f"API_ERROR: {str(e)[:200]}"],
            "needs_refinement": True,
            "api_error": True,
            "refinement_prompt": "API call failed, manual review required.",
            "reasoning": f"Error: {e}",
            "suggest_mirror": False,
            "mirror_reason": "",
            "shot_impossible": False,
            "shot_impossible_reason": "",
        }
    finally:
        for img in opened_ref_imgs:
            img.close()

    # A weaker judge can return a JSON array (or a string) instead of the
    # object the schema asks for. Unwrapping it here keeps one malformed
    # response from crashing the whole panel loop.
    if isinstance(result, list):
        result = result[0] if result and isinstance(result[0], dict) else {}
    elif not isinstance(result, dict):
        result = {}
    if not result:
        logger.error(f"  ❌ QA judge returned a non-object result "
                     f"(scene {scene_id} panel {panel_id})")
        result = {
            "fidelity": 0,
            "character_consistency": 0,
            "composition_match": 0,
            "dramatic_intensity": 0,
            "artifacts": ["API_ERROR: judge returned a non-object result"],
            "needs_refinement": True,
            "api_error": True,
            "refinement_prompt": "API call failed, manual review required.",
            "reasoning": "Judge returned a non-object result.",
            "suggest_mirror": False,
            "mirror_reason": "",
            "shot_impossible": False,
            "shot_impossible_reason": "",
        }

    # Hard-artifact gate: a perspective/scale/duplicate-character defect
    # leaves the numeric scores HIGH (the face is fine, the lighting is
    # fine), so the panel used to PASS with broken geometry. Promote the
    # critical classes to a hard needs_refinement trigger.
    result = apply_critical_artifact_gate(result)

    result["scene_id"] = scene_id
    result["panel_id"] = panel_id
    result["references_expected"] = ref_names
    result["references_loaded"] = loaded_refs
    return result


# ---------------------------------------------------------------------------
# Scene processing
# ---------------------------------------------------------------------------

def _load_panel_images_individual(
    output_dir: Path,
    scene_id: int,
    panels: list,
) -> Dict[int, "Image.Image"]:
    """Load individual panel PNGs from panels/ dir. Returns {panel_index: Image}."""
    panels_dir = output_dir / "panels"
    result: Dict[int, "Image.Image"] = {}
    for panel in panels:
        pid = panel["panel_index"]
        for suffix in ("_static", "_start"):
            p = panels_dir / f"{scene_id:03d}_{pid:02d}{suffix}.png"
            if p.exists():
                try:
                    result[pid] = Image.open(p)
                except Exception as e:
                    logger.warning(f"  ⚠️  Could not open {p}: {e}")
                break
    return result


def process_scene(
    llm: BaseLLM,
    scene: Dict,
    ref_catalog: Dict[str, Dict],
    grid_format: str,
    panels_per_scene: int,  # kept for call-site compat; derived from scene when possible
    threshold: int,
    panel_filter: Optional[List[int]] = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    prev_scene_last_panel: str = None,
    prompts: dict = None,
) -> List[Dict]:
    scene_id = scene["scene_id"]
    grid_path = output_dir / f"scene_{scene_id:03d}_grid_combined.png"
    panels = sorted(scene.get("panels", []), key=lambda p: p["panel_index"])
    # Prefer actual panel count from scene data over config-level default
    actual_panel_count = len(panels) if panels else panels_per_scene

    if grid_path.exists():
        panel_images_list = slice_grid(grid_path, actual_panel_count)
        # index 0-based list → dict by panel_index for uniform access below
        panel_images: Dict[int, "Image.Image"] = {
            i + 1: img for i, img in enumerate(panel_images_list)
        }
    else:
        logger.warning(f"⏭️  Grid not found: {grid_path} — trying individual panel files")
        panel_images = _load_panel_images_individual(output_dir, scene_id, panels)
        if not panel_images:
            logger.warning(f"⏭️  No panel images found for scene {scene_id}, skipping")
            return []
    results = []

    for panel_meta in panels:
        pid = panel_meta["panel_index"]
        if panel_filter and pid not in panel_filter:
            continue
        if pid not in panel_images:
            logger.warning(f"  ⚠️  Panel {pid} image not available (have {sorted(panel_images)})")
            continue

        logger.info(f"  🔍 Scene {scene_id}, Panel {pid} (refs: {panel_meta.get('references', [])})")

        result = analyze_panel(
            llm=llm,
            panel_img=panel_images[pid],
            panel_meta=panel_meta,
            scene_meta=scene,
            ref_catalog=ref_catalog,
            scene_id=scene_id,
            panel_id=pid,
            threshold=threshold,
            prev_scene_terminal=prev_scene_last_panel if pid == 1 else None,
            prompts=prompts,
        )
        results.append(result)

        fid = result["fidelity"]
        cc = result["character_consistency"]
        di = result.get("dramatic_intensity", "?")
        impossible_tag = "  🚫 IMPOSSIBLE" if result.get("shot_impossible") else ""
        need = "🔴 NEEDS FIX" if result["needs_refinement"] else "🟢 OK"
        mirror_tag = "  🪞 MIRROR" if result.get("suggest_mirror") else ""
        logger.info(f"    → fidelity={fid}/10  char_consistency={cc}/10  drama={di}/10  {need}{mirror_tag}{impossible_tag}")
        if result.get("shot_impossible"):
            logger.info(f"       🚫 IMPOSSIBLE SHOT: {result.get('shot_impossible_reason', '')}")
        if result.get("suggest_mirror"):
            logger.info(f"       🪞 {result.get('mirror_reason', '')}")
        if result["artifacts"]:
            for art in result["artifacts"][:3]:
                logger.info(f"       ⚠️  {art}")

    return results


# ---------------------------------------------------------------------------
# Room view QA
# ---------------------------------------------------------------------------

def _room_qa_output_spec(threshold: int) -> str:
    """Shared output contract for every room-view QA prompt (fields, bands, edits)."""
    return f"""**overall_score**: the minimum of style_score, architecture_score and geometry_score.

**action**: choose the correction band that matches overall_score:
- "regenerate" when overall_score < 5 — start over from the description/truth views
- "regenerate_with_instructions" when 5–7 — re-render with explicit corrections
- "targeted_edit" when overall_score is 8, or 5–7 when every issue is a local
  object fix (at most {ROOM_QA_MAX_LOCAL_EDITS} edit operations) — fix the delivered image with edits
- "accept" when overall_score >= {threshold}

**issues**: One object per distinct problem. Be specific. Room references fix layout and
  look, not set dressing: do NOT report objects smaller than ~30 cm (cups, cutlery, pens,
  mice, keyboards, papers, clipboards, stencil text) or fixture counts that do not change
  the look of the room. A reference id printed as lettering (e.g. "GUO-CRATE SEAT" on a crate)
  is a "medium" style issue to remove; never require such lettering.
  category: "style", "architecture" or "geometry"
  severity: "high" — opening, wall, large furniture or equipment missing, added or on the
  wrong side; a door hinged, handled or swinging on the wrong side; wrong material, camera
  or room. "medium" — a large object misplaced or
  misoriented. "low" — anything else, including the order or count of items on a counter,
  shelf or rail. A view whose issues are all "low" is accepted.
  object: the element name (e.g. "floor", "server-rack-row", "entrance door")
  expected: what the truth views/sketch require
  observed: what the evaluated image actually shows
  Examples:
    {{"category":"style","severity":"high","object":"floor","expected":"dark concrete","observed":"light oak parquet"}}
    {{"category":"architecture","severity":"high","object":"sofa","expected":"image-right","observed":"image-left"}}
    {{"category":"geometry","severity":"high","object":"background wall","expected":"far wall","observed":"entrance door"}}

**regeneration_prompt**: Precise fix instructions for a full re-render.
  State BOTH material corrections AND spatial/position corrections as separate sentences.
  Name exact objects and their required position (image-left / image-right / background / foreground).
  Example: "Far wall must be white plaster not brick. Sofa must appear on image-right not image-left."
  Empty string for accept/targeted_edit.

**edit_instructions**: Targeted image edits. Fill them whenever overall_score >= 5 and
  the defects are object-level (an extra, missing, misplaced, rotated or wrongly coloured
  object), even if you chose "regenerate_with_instructions". Leave empty for global
  defects: wrong materials across surfaces, wrong camera position, wrong room.
  One object per operation:
  - op: "remove" | "add" | "move" | "rotate" | "replace" | "recolor" | "resize"
  - target: the object to change
  - from: current state or position (empty string when not applicable)
  - to: required state or position (empty string when not applicable)
  - details: extra visual detail for the editor (empty string when not applicable)
  Examples:
    {{"op":"remove","target":"extra chair","from":"image-left foreground","to":"","details":""}}
    {{"op":"move","target":"wooden crate","from":"image-left wall","to":"image-right wall, 1 m from entrance","details":"keep size and material"}}
    {{"op":"rotate","target":"console desk","from":"facing entrance","to":"facing far wall","details":""}}
  Empty array for accept and "regenerate".

**edit_prompt**: One self-contained instruction for the image editor, built from
  edit_instructions. It must say to keep everything else pixel-identical: same camera,
  same framing, same materials and lighting. Empty string when edit_instructions is empty.
"""


def _call_room_qa(llm: BaseLLM, image_content: list, prompt: str, label: str) -> tuple[dict, bool]:
    """Run the room QA judge; an API failure is reported, never scored."""
    try:
        return llm.analyze_image(image=image_content, prompt=prompt, schema=ROOM_VIEW_QA_SCHEMA), False
    except Exception as e:
        logger.error(f"  ❌ room QA error ({label}): {e}")
        return {
            'api_error': True,
            'error': str(e)[:200],
            'issues': [{'category': 'geometry', 'severity': 'high', 'object': 'qa',
                        'expected': 'a QA response', 'observed': f'API_ERROR: {str(e)[:200]}'}],
        }, True


_ROOM_STYLE_CHECKS = """- Wall surfaces: material, color, texture, finish (tile vs plaster vs brick, etc.)
- Floor: material, pattern, color
- Ceiling: height, material, fixtures
- Lighting: fixture type, position, color temperature
- Windows and doors: frame style, glazing, proportions"""
_OUTDOOR_STYLE_CHECKS = """- Facades: material, color, storeys, signage style, awnings, window rhythm
- Ground: roadway, lane markings, curbs, sidewalk paving, grass/sand/soil
- Sky, weather, time of day, sun direction and shadow length
- Street furniture and vegetation: lamps, signs, benches, trees — type and style
- Era: vehicles, signage and fixtures belong to the same period"""


def analyze_room_view(
    llm: BaseLLM,
    view_img: Image.Image,
    source_views: list[tuple[str, Image.Image]],
    view_suffix: str,
    visual_desc: str,
    threshold: int = ROOM_QA_PASS_THRESHOLD,
    anchor_points: dict | None = None,
    expected_aspect: str | None = None,
    sketch_img: Image.Image | None = None,
    enforce_aspect: bool = True,
) -> dict:
    """Score a room view against one or more truth source views using a vision LLM.

    source_views — list of (suffix, image) pairs used as ground truth.
    expected_aspect — optional physical framing ratio (e.g. "16:9"). When set,
    a deterministic pre-check adds an issue and fails the geometry score if the
    delivered image does not match it.
    sketch_img — optional bare 3D sketch for this exact view. It is passed as
    geometry-only truth (camera, occlusion, placement), so the judge does not
    penalise objects the sketch camera intentionally hides.
    enforce_aspect — when False, a framing mismatch is reported in ``issues``
    but does not lower the score (used for the base-truth view, which must not
    be force-regenerated).
    Returns a normalized QA dict: style/architecture/geometry/overall scores,
    action band, compatibility aliases (consistency_score, needs_regeneration),
    structured edit instructions, and an ``api_error`` flag when the judge
    failed. On API error the action is ``blocked`` and needs_regeneration is
    False so callers keep the existing PNG.
    """
    from lib.studio.artist import _anchor_visibility_block
    outdoor = view_suffix in _OUTDOOR_TRUTH_SOURCES
    place = 'outdoor location' if outdoor else 'room'
    spatial_rule = f"{_VIEW_SPATIAL_RULES.get(view_suffix, '')} {behind_camera_rule(view_suffix)}".strip()
    anchor_block = (
        _anchor_visibility_block(
            anchor_points, view_suffix, camera_inset_m=0.0 if outdoor else WALL_INSET_M,
            room_height_m=resolve_room_height_m(anchor_points, visual_desc)[0],
        )
        if anchor_points else ''
    )
    n_sources = len(source_views)
    sketch_index = n_sources + 1 if sketch_img is not None else None
    eval_index = n_sources + (2 if sketch_img is not None else 1)

    expected_ratio = None
    aspect_issue = None
    if expected_aspect:
        try:
            exp_w, exp_h = (int(part) for part in expected_aspect.split(':'))
            expected_ratio = exp_w / exp_h
        except (ValueError, ZeroDivisionError):
            expected_ratio = None
    if expected_ratio:
        actual_ratio = view_img.width / view_img.height
        if abs(math.log(actual_ratio / expected_ratio)) > math.log(1.12):
            aspect_issue = (
                f"Image aspect ratio is {view_img.width}x{view_img.height} "
                f"({actual_ratio:.2f}:1); this view should be {expected_aspect} "
                f"({expected_ratio:.2f}:1)."
            )
    framing_block = ''
    if expected_ratio:
        framing_block = (
            f"\n## EXPECTED FRAMING\n"
            f"This {place} view must use aspect ratio {expected_aspect} "
            f"({expected_ratio:.2f}:1). The supplied image is "
            f"{view_img.width}x{view_img.height} "
            f"({view_img.width / view_img.height:.2f}:1).\n"
        )
    single = n_sources == 1
    sources_list = '\n'.join(
        f'  - Image {i + 1}: "{s}"' for i, (s, _) in enumerate(source_views)
    )
    truth_label = f'Image 1 ("{source_views[0][0]}")' if single else f'Images 1–{n_sources}'
    sketch_section = ''
    if sketch_img is not None and outdoor:
        sketch_section = (
            f"\n## GEOMETRY SKETCH — authoritative for THIS view, not materials\n"
            f"Image {sketch_index} is a bare 3D sketch of the view under evaluation, from the same "
            "camera station as View-Primary. Use it for camera heading, perspective, and the "
            "left/right/ahead placement of facades, curbs, landmarks and street furniture. Buildings "
            "are plain full-height slabs and the sky is blank; ignore its lines, fills and missing "
            "detail as style.\n"
        )
    elif sketch_img is not None:
        sketch_section = (
            f"\n## GEOMETRY SKETCH — authoritative for THIS view, not materials\n"
            f"Image {sketch_index} is a bare 3D sketch of the view under evaluation. "
            "Use it for camera angle, perspective, foreshortening, occlusion, and "
            "the left/right/background placement of objects. It carries no "
            "materials, colors or lighting; ignore its lines and fills as style. "
            f"Wall views are cut {WALL_INSET_M:.1f} m inside the camera wall and the "
            "sketch camera may stand behind that cut, outside the room (fourth wall "
            "removed). An object the sketch hides — before the cut, or because the "
            "camera sits inside it — must NOT be reported as missing from the "
            "evaluated image.\n"
        )
    prompt = f"""You are a QA supervisor for an AI film production pipeline.
Your task: evaluate a {place.upper()} VIEW image for material consistency and spatial correctness.

## TRUTH VIEW(S) — authoritative ground truth for this {place}
{sources_list}
{sketch_section}
## VIEW UNDER EVALUATION
Image {eval_index} is "{view_suffix}" — a different camera angle {'from the same spot in the same location' if outdoor else 'inside the same room'}.

## REQUIRED GEOMETRY FOR "{view_suffix}"
{spatial_rule}

## {place.upper()} DESCRIPTION
{visual_desc}
{anchor_block}{framing_block}
## SCORING

Score three independent dimensions. The pipeline takes the MINIMUM of the three,
so a single badly wrong dimension fails the view.

**style_score** (0–10): Do materials, colors, textures, finishes, lighting fixtures
and color temperature match {truth_label}?
{_OUTDOOR_STYLE_CHECKS if outdoor else _ROOM_STYLE_CHECKS}
10 = identical style. 0 = clearly a different {place} style.

**architecture_score** (0–10): Is it the SAME {place}, the SAME architecture and the SAME set of objects?
- Same walls, structural features, doors, windows
- Same furniture and equipment: identity, material, COUNT
- Positions must be re-mapped per the spatial rules above (e.g., a sofa on
  image-left in View-From-Entrance must appear on image-right in View-To-Entrance)
10 = identical architecture. 0 = wrong {place}, missing/extra major structures or furniture.

**geometry_score** (0–10): Is the camera angle geometrically correct for "{view_suffix}"?
Check: {'what lies ahead (facade, street, landmark)' if outdoor else 'background wall identity'}, left/right orientation, foreshortening/depth.
Use REQUIRED GEOMETRY above. Score 0 if the wrong {'side' if outdoor else 'wall'} is in the background or the
spatial orientation is impossible for this camera position.

When the geometry sketch and a truth view disagree about whether an object is
visible in THIS view, follow the sketch: it encodes this camera's occlusion.
Truth views remain authoritative for materials, colors and object identity.

The truth views outrank the {place.upper()} DESCRIPTION. Where the text and a truth view
disagree about something the truth view shows (which end of a counter an item sits
at, the order of goods on a shelf or rail, a count), require what the truth view shows,
re-mapped for this camera, and do not report the text. Use the description only for
what no truth view shows.

{_room_qa_output_spec(threshold)}"""
    image_content: list = []
    for i, (suffix, img) in enumerate(source_views):
        image_content.append(f"# SOURCE VIEW {i + 1}: {suffix}\n")
        image_content.append(img)
    if sketch_img is not None:
        image_content.append(f"\n# GEOMETRY SKETCH: {view_suffix}\n")
        image_content.append(sketch_img)
    image_content.append(f"\n# VIEW TO EVALUATE: {view_suffix}\n")
    image_content.append(view_img)

    result, api_error = _call_room_qa(llm, image_content, prompt, view_suffix)

    result = normalize_room_view_qa(result, pass_threshold=threshold, api_error=api_error)

    if aspect_issue:
        issues = [aspect_issue] + [i for i in result.get('issues', []) if i != aspect_issue]
        result['issues'] = issues
        result.setdefault('issue_details', []).append({
            'category': 'geometry',
            'severity': 'high',
            'object': 'framing',
            'expected': f'{expected_aspect} ({expected_ratio:.2f}:1)',
            'observed': f'{view_img.width}x{view_img.height} '
                        f'({view_img.width / view_img.height:.2f}:1)',
        })
        if enforce_aspect and not result['api_error']:
            # A wrong frame is a deterministic geometry failure: it cannot be
            # edited away and the score must drop below the pass mark.
            result['geometry_score'] = min(
                result['geometry_score'], max(0, threshold - 1)
            )
            result['overall_score'] = min(
                result['style_score'], result['architecture_score'], result['geometry_score']
            )
            result['action'] = decide_room_view_action(
                result['overall_score'], pass_threshold=threshold
            )
            result['consistency_score'] = min(
                result['style_score'], result['architecture_score']
            )
            result['needs_regeneration'] = result['action'] not in ('accept', 'blocked')
            result['status'] = 'passed' if result['action'] == 'accept' else 'failed'
        fix = (
            f"Re-render at {expected_aspect}; the delivered image is "
            f"{view_img.width}x{view_img.height}."
        )
        prior = (result.get('regeneration_prompt') or '').strip()
        result['regeneration_prompt'] = f"{prior} {fix}".strip()
        result['aspect_issue'] = aspect_issue
    return result


def analyze_room_description(
    llm: BaseLLM,
    view_img: Image.Image,
    visual_desc: str,
    named_positions: list[dict] | None = None,
    threshold: int = ROOM_QA_PASS_THRESHOLD,
    sketch_img: Image.Image | None = None,
) -> dict:
    """QA View-From-Entrance against its description (and its floor-plan sketch): whatever it invents propagates."""
    positions = '\n'.join(
        f"  [{p.get('id', '?')}] {p.get('description', '')}" for p in named_positions or []
    )
    positions_block = (
        f"\n## NAMED POSITIONS (each visible in the stated place unless behind the camera)"
        f"\n{positions}\n"
        if positions else ''
    )
    sketch_step = (
        "5. A FLOOR-PLAN SKETCH of the same camera comes first: it is the geometry truth. Every wall,\n"
        "   opening and object must stand where the sketch draws it, at its size; ignore the sketch's\n"
        "   flat colours, lines and simplified shapes. An object on another wall, at another depth or\n"
        "   with a clearly different footprint is a geometry issue; a camera or lens that differs from\n"
        "   the sketch caps geometry_score at 6.\n"
        if sketch_img else ''
    )
    prompt = f"""You are a QA supervisor for an AI film production pipeline.

The image is the BASE-TRUTH reference "View-From-Entrance" of an empty room: the camera
stands at the entrance looking INTO the room. Every other camera view of this room is
generated from it, so any element the description does not ask for will be copied into
every view. Judge the image strictly against the description.

## DESCRIPTION
{visual_desc}
{positions_block}
## METHOD
1. List every architectural opening in the image: doors, hatches, windows, arches,
   passages, vents large enough to read as openings. Compare their COUNT, wall and
   position with the description. An opening the description does not mention is a
   high-severity architecture issue, even if it looks plausible. For every door also
   compare hinge edge, handle side and swing with the description.
2. List every piece of furniture and equipment. Each must be described or be a named
   position; anything else is an unrequested object. Each described or named element
   that is missing, duplicated, or on the wrong wall/side is an issue.
3. Check materials, colors, lighting and fixtures against the description.
4. Check the camera: at the entrance, looking into the room.
   {behind_camera_rule('View-From-Entrance')}
   The room is empty: no people, no text, no captions, no panels.
{sketch_step}
## SCORING

**style_score** (0–10): materials, colors, textures, finishes and lighting match the
  description.

**architecture_score** (0–10): the inventory matches — same openings, same objects,
  same counts, nothing missing, nothing added. One unrequested door or window caps
  this score at 6.

**geometry_score** (0–10): camera position/direction is View-From-Entrance and every
  object sits on the described wall/side and at the described depth.

{_room_qa_output_spec(threshold)}"""
    image_content = (["# FLOOR-PLAN SKETCH (geometry truth for this camera)\n", sketch_img] if sketch_img else []) + [
        "# VIEW TO EVALUATE: View-From-Entrance\n", view_img]
    result, api_error = _call_room_qa(llm, image_content, prompt, 'View-From-Entrance')
    return normalize_room_view_qa(result, pass_threshold=threshold, api_error=api_error)


def analyze_outdoor_description(
    llm: BaseLLM,
    view_img: Image.Image,
    visual_desc: str,
    threshold: int = ROOM_QA_PASS_THRESHOLD,
) -> dict:
    """QA View-Primary against its description: the other three station views are built from it."""
    prompt = f"""You are a QA supervisor for an AI film production pipeline.

The image is the BASE-TRUTH reference "View-Primary" of an empty outdoor location. The camera
stands at the location's STATION and faces AHEAD (the primary direction). The other views turn in
place at the same spot: RIGHT, BEHIND, LEFT. Anything the image invents is copied into them.

## DESCRIPTION
{visual_desc}

## METHOD
1. Find the AHEAD section of the description (or the primary direction): what must fill the
   view straight ahead and in the distance.
2. The RIGHT section must line the image-right edge, the LEFT section the image-left edge —
   e.g. a street's main facade the description puts on the RIGHT runs along the image-right side,
   receding. A side swapped left/right is a high-severity geometry issue.
3. The BEHIND section is behind the camera: never show or require it.
4. List buildings, openings, landmarks and street furniture in the image; each must be described.
   An unrequested landmark or a missing named one is an architecture issue.
5. Check materials, era, weather, time of day and light against the description.
   The location is empty: no people, no text, no captions, no panels.

## SCORING

**style_score** (0–10): materials, era, weather and light match the description.

**architecture_score** (0–10): the inventory matches — same buildings, landmarks and street
  furniture, nothing missing, nothing added.

**geometry_score** (0–10): the camera stands at eye height at the station facing AHEAD, and
  every element sits on its described side and at its described distance.

{_room_qa_output_spec(threshold)}"""
    image_content = [f"# VIEW TO EVALUATE: {OUTDOOR_TRUTH}\n", view_img]
    result, api_error = _call_room_qa(llm, image_content, prompt, OUTDOOR_TRUTH)
    return normalize_room_view_qa(result, pass_threshold=threshold, api_error=api_error)


def run_room_view_qa(
    llm: BaseLLM,
    project,  # Project
    max_attempts: int = 3,
    threshold: int = ROOM_QA_PASS_THRESHOLD,
    view_filter: Optional[List[str]] = None,
) -> dict:
    """Discover all derived room view PNGs, QA-score them, and regenerate failing ones.

    Mirrors the panel-by-panel-with-qa loop in artist.py.
    Returns a summary dict: { view_name: { "attempts": [...], "passed": bool } }
    """
    # Import here to avoid circular dependency (artist imports from critic indirectly)
    from lib.studio.artist import (
        _load_entrance_anchor_points,
        _parse_room_dims,
        _render_single_ref,
        _view_aspect_ratio,
        load_character_refs,
    )
    from lib.studio.room_geometry import resolve_room_height_m
    from lib.core.utils import safe_name

    load_character_refs(project)
    config: dict = {}  # _render_single_ref only needs config for aspect ratio; use defaults

    ref_dir: Path = project.ref_dir
    summary: dict = {}

    for suffix in _DERIVED_VIEW_SUFFIXES:
        if view_filter and suffix not in view_filter:
            continue

        truth_suffixes = _VIEW_TRUTH_SOURCES[suffix]

        view_jsons = sorted(ref_dir.glob(f"*-{safe_name(suffix)}.json"))
        for view_json in view_jsons:
            view_png = view_json.with_suffix('.png')
            if not view_png.exists():
                logger.info(f"  ⏭  No PNG for {view_json.stem}, skipping")
                continue

            view_data = json.loads(view_json.read_text(encoding='utf-8'))
            view_ref_name = view_data.get('name', view_json.stem)
            base_name = (
                view_ref_name[: -(len(suffix) + 1)]
                if view_ref_name.endswith(f'-{suffix}')
                else None
            )

            # Resolve all truth source PNGs
            truth_pngs: list[tuple[str, Path]] = []
            for ts in truth_suffixes:
                source_ref = f"{base_name}-{ts}" if base_name else f"{view_json.stem}-{ts}"
                source_png = ref_dir / f"{safe_name(source_ref)}.png"
                if source_png.exists():
                    truth_pngs.append((ts, source_png))
                else:
                    logger.warning(f"  ⚠️  Truth PNG not found: {source_png} — skipping {ts}")

            if not truth_pngs:
                logger.warning(f"  ⚠️  No truth PNGs for {view_ref_name}, skipping")
                continue

            logger.info(f"  🔍 QA: {view_ref_name}  (truth: {[s for s,_ in truth_pngs]})")
            key = view_ref_name
            summary[key] = {'attempts': [], 'passed': False}
            sketch_png = ref_dir / f"{safe_name(view_ref_name)}.sketch.png"

            # Load anchor_points for geometry-aware QA prompt
            ap = view_data.get('anchor_points') or (
                _load_entrance_anchor_points(view_ref_name, suffix, project)
                if hasattr(project, 'ref_dir') else {}
            )

            # Physical framing target, derived from the same room dimensions
            # and ceiling height used by the render prompt and the sketch.
            dims = None
            room_m = ap.get('room_m') if isinstance(ap, dict) else None
            if isinstance(room_m, (list, tuple)) and len(room_m) >= 2:
                dims = (float(room_m[0]), float(room_m[1]))
            else:
                dims = _parse_room_dims(view_data.get('visual_desc', ''))
            expected_aspect = None
            if dims:
                room_h, _ = resolve_room_height_m(
                    ap if isinstance(ap, dict) else {},
                    view_data.get('visual_desc', ''),
                )
                expected_aspect = _view_aspect_ratio(
                    suffix, dims, config, room_h
                )

            for attempt in range(1, max_attempts + 1):
                source_views: list[tuple[str, Image.Image]] = []
                for ts, tp in truth_pngs:
                    img = Image.open(tp)
                    source_views.append((ts, img.copy()))
                    img.close()

                with Image.open(view_png) as vi:
                    view_img = vi.copy()

                sketch_img = Image.open(sketch_png).copy() if sketch_png.exists() else None

                result = analyze_room_view(
                    llm=llm,
                    view_img=view_img,
                    source_views=source_views,
                    view_suffix=suffix,
                    visual_desc=view_data.get('visual_desc', ''),
                    threshold=threshold,
                    anchor_points=ap or None,
                    expected_aspect=expected_aspect,
                    sketch_img=sketch_img,
                )
                for _, img in source_views:
                    img.close()
                view_img.close()
                if sketch_img is not None:
                    sketch_img.close()

                result['attempt'] = attempt
                summary[key]['attempts'].append(result)

                con = result['consistency_score']
                geo = result['geometry_score']
                overall = result['overall_score']
                need = result['needs_regeneration']
                logger.info(
                    f"    attempt {attempt}: overall={overall}/10  style={result['style_score']}/10  "
                    f"architecture={result['architecture_score']}/10  geometry={geo}/10  "
                    f"consistency={con}/10  action={result['action']}  "
                    + ("🔴 regenerate" if need else "🟢 OK")
                )
                for issue in result.get('issues', []):
                    logger.info(f"      ⚠️  {issue}")

                if not need:
                    summary[key]['passed'] = True
                    break

                if attempt < max_attempts:
                    regen_prompt = (
                        result.get('regeneration_prompt')
                        or result.get('edit_prompt')
                        or '; '.join(result.get('issues', []))
                    )
                    if regen_prompt:
                        patched = dict(view_data)
                        patched['visual_desc'] = (
                            f"{view_data.get('visual_desc', '')}. "
                            f"CORRECTION REQUIRED: {regen_prompt}"
                        )
                        # Use View-From-Entrance as style reference for material anchoring
                        entrance_png = next(
                            (p for s, p in truth_pngs if s == 'View-From-Entrance'), None
                        )
                        if entrance_png and base_name:
                            patched['style_reference'] = f"{base_name}-View-From-Entrance"
                        logger.info(f"    🔄 Regenerating (attempt {attempt + 1})...")
                        _render_single_ref(patched, config, project, llm, force=True)
                        if view_json.exists():
                            view_data = json.loads(view_json.read_text(encoding='utf-8'))

            if not summary[key]['passed']:
                logger.warning(f"  ❌ {view_ref_name} failed after {max_attempts} attempts")

    passed = sum(1 for v in summary.values() if v['passed'])
    total = len(summary)
    logger.info(f"\n📄 Room view QA complete: {passed}/{total} passed")
    return summary


