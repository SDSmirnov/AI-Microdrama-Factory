"""
Critic — Grid Quality Gate.

Port of 05_grid_quality_gate.py using a vision-capable BaseLLM backend.
"""
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from lib.core.schemas import PANEL_QA_SCHEMA, ROOM_VIEW_QA_SCHEMA
from lib.core.utils import DEFAULT_OUTPUT_DIR, grid_dims, panel_boxes
from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)

MAX_REFS_PER_PANEL = 6

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
    'View-By-Entrance': (
        "Camera 1m from the entrance wall, looking toward the entrance door. "
        "Left/right are SWAPPED vs View-From-Entrance — same mirroring as View-To-Entrance. "
        "The entrance door must fill ~80% of the frame. "
        "No mid-room furniture should be visible — it is behind the camera. "
        "Far wall must NOT be visible."
    ),
}

# Wall names keyed by which boundary the camera→subject ray exits through
_WALL_LABELS = {
    'x0': 'image-left wall',
    'x1': 'image-right wall',
    'y0': 'entrance wall',
    'y1': 'far wall',
}


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

    # Resolve anchor_points from the panel's canonical (View-From-Entrance / View-Primary) location ref.
    # All non-canonical view suffixes are stripped to reach the View-From-Entrance entry that holds anchor_points.
    _TO_CANONICAL = {
        '-View-To-Entrance':        '-View-From-Entrance',
        '-View-From-Left-Wall':     '-View-From-Entrance',
        '-View-From-Right-Wall':    '-View-From-Entrance',
        '-View-Center-To-Far':      '-View-From-Entrance',
        '-View-Center-To-Entrance': '-View-From-Entrance',
        '-View-By-Far-Wall':        '-View-From-Entrance',
        '-View-By-Entrance':        '-View-From-Entrance',
        '-View-Opposite':           '-View-Primary',
        '-Interior-To-Entrance':    '-Interior-From-Entrance',
    }
    anchor_points = None
    for ref_name in panel_meta.get('location_references', []):
        canonical = ref_name
        for suffix, replacement in _TO_CANONICAL.items():
            if ref_name.endswith(suffix):
                canonical = ref_name[:-len(suffix)] + replacement
                break
        entry = ref_catalog.get(canonical) or ref_catalog.get(ref_name)
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
        wall_label = _WALL_LABELS[wall_key]

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
                facing_note = f' (chair facing_degrees_y={facing:.0f}° suggests back toward {_WALL_LABELS[back_wall]}; ray projection takes precedence)'
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

    from lib.studio.artist import _anchor_visibility_block, _extract_camera_anchor_labels

    # Suffix → canonical view that carries anchor_points
    _TO_CANONICAL_SUFFIX = {
        'View-To-Entrance':        'View-From-Entrance',
        'View-From-Left-Wall':     'View-From-Entrance',
        'View-From-Right-Wall':    'View-From-Entrance',
        'View-Center-To-Far':      'View-From-Entrance',
        'View-Center-To-Entrance': 'View-From-Entrance',
        'View-By-Far-Wall':        'View-From-Entrance',
        'View-By-Entrance':        'View-From-Entrance',
        'View-Opposite':           'View-Primary',
        'Interior-To-Entrance':    'Interior-From-Entrance',
    }
    _CANONICAL_SUFFIXES = {'View-From-Entrance', 'View-Primary', 'Interior-From-Entrance', 'Exterior'}
    _ALL_SUFFIXES = set(_TO_CANONICAL_SUFFIX) | _CANONICAL_SUFFIXES

    view_suffix = None
    anchor_points = None
    for ref_name in panel_meta.get('location_references', []):
        matched = next((s for s in _ALL_SUFFIXES if ref_name.endswith(f'-{s}')), None)
        if not matched:
            continue
        view_suffix = matched
        canonical_suffix = _TO_CANONICAL_SUFFIX.get(matched, matched)
        if canonical_suffix != matched:
            base = ref_name[: -(len(matched) + 1)]
            canonical_name = f'{base}-{canonical_suffix}'
        else:
            canonical_name = ref_name
        entry = ref_catalog.get(canonical_name) or ref_catalog.get(ref_name)
        if entry:
            anchor_points = entry.get('json', {}).get('anchor_points')
        break

    if not anchor_points or not view_suffix:
        return ''

    camera_anchors = _extract_camera_anchor_labels(panel_meta.get('camera_position', ''), anchor_points)
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

    block = _anchor_visibility_block(filtered, view_suffix, frozenset(camera_anchors))
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
        except Exception:
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
    return None


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
    anchor_visibility = _compute_anchor_visibility(panel_meta, ref_catalog)

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
  For character/fidelity issues: "Eckels' face does not match reference — wrong jaw shape, hair should be silver not brown."
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
{spatial_ground_truth}{anchor_visibility}
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

def analyze_room_view(
    llm: BaseLLM,
    view_img: Image.Image,
    source_views: list[tuple[str, Image.Image]],
    view_suffix: str,
    visual_desc: str,
    threshold: int = 7,
    anchor_points: dict | None = None,
) -> dict:
    """Score a room view against one or more truth source views using a vision LLM.

    source_views — list of (suffix, image) pairs used as ground truth.
    Returns a ROOM_VIEW_QA_SCHEMA dict.
    """
    from lib.studio.artist import _anchor_visibility_block
    spatial_rule = _VIEW_SPATIAL_RULES.get(view_suffix, '')
    anchor_block = _anchor_visibility_block(anchor_points, view_suffix) if anchor_points else ''
    n_sources = len(source_views)
    single = n_sources == 1
    sources_list = '\n'.join(
        f'  - Image {i + 1}: "{s}"' for i, (s, _) in enumerate(source_views)
    )
    truth_label = f'Image 1 ("{source_views[0][0]}")' if single else f'Images 1–{n_sources}'
    prompt = f"""You are a QA supervisor for an AI film production pipeline.
Your task: evaluate a ROOM VIEW image for material consistency and spatial correctness.

## TRUTH VIEW(S) — authoritative ground truth for this room
{sources_list}

## VIEW UNDER EVALUATION
Image {n_sources + 1} is "{view_suffix}" — a different camera angle inside the same room.

## REQUIRED GEOMETRY FOR "{view_suffix}"
{spatial_rule}

## ROOM DESCRIPTION
{visual_desc}
{anchor_block}
## SCORING

**consistency_score** (0–10): Does the evaluated image show the SAME room as {truth_label}?
Check every element that can be verified across views:
- Wall surfaces: material, color, texture, finish (tile vs plaster vs brick, etc.)
- Floor: material, pattern, color
- Ceiling: height, material, fixtures
- Lighting: fixture type, position, color temperature
- Windows and doors: frame style, glazing, proportions
- Furniture and objects: same pieces present, correct materials, correct COUNT
- Furniture POSITIONS must be re-mapped per the spatial rules above (e.g., a sofa on
  image-left in View-From-Entrance must appear on image-right in View-To-Entrance).
Score 10 = perfect match. Score 0 = clearly a different room or furniture missing/wrong.

**geometry_score** (0–10): Is the camera angle geometrically correct for "{view_suffix}"?
Check: background wall identity, left/right orientation, foreshortening/depth.
Use REQUIRED GEOMETRY above. Score 0 if the wrong wall is in the background or the
spatial orientation is impossible for this camera position.

**needs_regeneration**: True if consistency_score < {threshold} OR geometry_score < {threshold}.

**issues**: One item per distinct problem. Be specific — name the element and the discrepancy.
  Material example: "Floor shows light oak parquet but truth view shows dark concrete."
  Position example: "Sofa appears image-left but should be image-right per 180° turn rule."
  Geometry example: "Entrance door visible in background — camera should face the far wall."
  Missing example: "Bookcase present in truth view is absent from evaluated image."

**regeneration_prompt**: Precise fix instructions to append to visual_desc for re-generation.
  State BOTH material corrections AND spatial/position corrections as separate sentences.
  Name exact objects and their required position (image-left / image-right / background / foreground).
  Example: "Far wall must be white plaster not brick. Sofa must appear on image-right not image-left."
  Empty string when needs_regeneration=false.
"""
    image_content: list = []
    for i, (suffix, img) in enumerate(source_views):
        image_content.append(f"# SOURCE VIEW {i + 1}: {suffix}\n")
        image_content.append(img)
    image_content.append(f"\n# VIEW TO EVALUATE: {view_suffix}\n")
    image_content.append(view_img)

    try:
        result = llm.analyze_image(image=image_content, prompt=prompt, schema=ROOM_VIEW_QA_SCHEMA)
    except Exception as e:
        logger.error(f"  ❌ analyze_room_view error ({view_suffix}): {e}")
        result = {
            "consistency_score": 0,
            "geometry_score": 0,
            "needs_regeneration": True,
            "issues": [f"API_ERROR: {str(e)[:200]}"],
            "regeneration_prompt": "API call failed, manual review required.",
        }
    return result


def run_room_view_qa(
    llm: BaseLLM,
    project,  # Project
    max_attempts: int = 3,
    threshold: int = 7,
    view_filter: Optional[List[str]] = None,
) -> dict:
    """Discover all derived room view PNGs, QA-score them, and regenerate failing ones.

    Mirrors the panel-by-panel-with-qa loop in artist.py.
    Returns a summary dict: { view_name: { "attempts": [...], "passed": bool } }
    """
    # Import here to avoid circular dependency (artist imports from critic indirectly)
    from lib.studio.artist import _load_entrance_anchor_points, _render_single_ref, load_character_refs
    from lib.core.utils import safe_name

    load_character_refs(project)
    config: dict = {}  # _render_single_ref only needs config for aspect ratio; use defaults

    ref_dir: Path = project.ref_dir
    summary: dict = {}

    for view_suffix in _DERIVED_VIEW_SUFFIXES:
        if view_filter and view_suffix not in view_filter:
            continue

        truth_suffixes = _VIEW_TRUTH_SOURCES[view_suffix]

        view_jsons = sorted(ref_dir.glob(f"*-{safe_name(view_suffix)}.json"))
        for view_json in view_jsons:
            view_png = view_json.with_suffix('.png')
            if not view_png.exists():
                logger.info(f"  ⏭  No PNG for {view_json.stem}, skipping")
                continue

            view_data = json.loads(view_json.read_text(encoding='utf-8'))
            view_ref_name = view_data.get('name', view_json.stem)
            base_name = (
                view_ref_name[: -(len(view_suffix) + 1)]
                if view_ref_name.endswith(f'-{view_suffix}')
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

            # Load anchor_points for geometry-aware QA prompt
            ap = view_data.get('anchor_points') or (
                _load_entrance_anchor_points(view_ref_name, view_suffix, project)
                if hasattr(project, 'ref_dir') else {}
            )

            for attempt in range(1, max_attempts + 1):
                source_views: list[tuple[str, Image.Image]] = []
                for ts, tp in truth_pngs:
                    img = Image.open(tp)
                    source_views.append((ts, img.copy()))
                    img.close()

                with Image.open(view_png) as vi:
                    view_img = vi.copy()

                result = analyze_room_view(
                    llm=llm,
                    view_img=view_img,
                    source_views=source_views,
                    view_suffix=view_suffix,
                    visual_desc=view_data.get('visual_desc', ''),
                    threshold=threshold,
                    anchor_points=ap or None,
                )
                for _, img in source_views:
                    img.close()
                view_img.close()

                result['attempt'] = attempt
                summary[key]['attempts'].append(result)

                con = result['consistency_score']
                geo = result['geometry_score']
                need = result['needs_regeneration']
                logger.info(
                    f"    attempt {attempt}: consistency={con}/10  geometry={geo}/10  "
                    + ("🔴 regenerate" if need else "🟢 OK")
                )
                for issue in result.get('issues', []):
                    logger.info(f"      ⚠️  {issue}")

                if not need:
                    summary[key]['passed'] = True
                    break

                if attempt < max_attempts:
                    regen_prompt = result.get('regeneration_prompt', '')
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


