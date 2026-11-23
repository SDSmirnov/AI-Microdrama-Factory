"""Spatial passes: visual_disposition from room anchors, view swaps, and rewrites of contradicting visuals."""
import json
import logging

from lib.core import puppet as _puppet
from lib.core.schemas import (
    SPATIAL_DISPOSITION_SCHEMA,
    SPATIAL_REWRITE_SCHEMA,
)
from lib.llm.base import BaseLLM

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Spatial disposition pass
# ---------------------------------------------------------------------------
_TO_ENTRANCE_SUFFIXES = ('-View-To-Entrance', '-View-Center-To-Entrance', '-View-By-Entrance', '-Interior-To-Entrance', '-View-Opposite')
_VIEW_SWAP: dict[str, str] = {
    'View-From-Entrance': 'View-To-Entrance',
    'View-To-Entrance': 'View-From-Entrance',
    'View-From-Left-Wall': 'View-From-Right-Wall',
    'View-From-Right-Wall': 'View-From-Left-Wall',
    'View-Center-To-Far': 'View-Center-To-Entrance',
    'View-Center-To-Entrance': 'View-Center-To-Far',
    'View-By-Far-Wall': 'View-By-Entrance',
    'View-By-Entrance': 'View-By-Far-Wall',
    'Interior-From-Entrance': 'Interior-To-Entrance',
    'Interior-To-Entrance': 'Interior-From-Entrance',
    'View-Primary': 'View-Opposite',
    'View-Opposite': 'View-Primary',
    'View-Ortho-Primary': 'View-Ortho-Opposite',
    'View-Ortho-Opposite': 'View-Ortho-Primary',
}


_LATERAL_SUFFIXES = ('-View-From-Left-Wall', '-View-From-Right-Wall', '-View-Ortho-Primary', '-View-Ortho-Opposite')


def _panel_view_type(panel: dict) -> str:
    """Return view axis type for spatial reasoning in the disposition prompt.

    'From-Entrance' — canonical Y-axis (entrance at y=0, far wall at y=1); left/right as in source ref.
    'To-Entrance'   — reversed Y-axis (camera at far wall looking toward entrance); left/right swapped.
    'Lateral'       — X-axis camera (camera on left or right wall); depth runs along X, not Y.
    """
    for ref in panel.get('location_references', []):
        if any(ref.endswith(s) for s in _LATERAL_SUFFIXES):
            return 'Lateral'
        if any(ref.endswith(s) for s in _TO_ENTRANCE_SUFFIXES):
            return 'To-Entrance'
    return 'From-Entrance'


def _swap_view_ref(ref: str) -> str:
    """Swap the view-axis suffix of a location ref name. Returns original if no suffix matches."""
    for old, new in _VIEW_SWAP.items():
        if ref.endswith(f'-{old}'):
            return ref[: -len(old)] + new
    return ref


# Ordered longest-first so partial strings don't get replaced before their superstrings.
_FRAME_LR_PAIRS = [
    ('frame-center-left', 'frame-center-right'),
    ('frame-left',        'frame-right'),
]


def _mirror_screen_directions(text: str) -> str:
    """Atomically swap frame-left ↔ frame-right (and center variants) in a text string.

    Uses placeholder tokens to avoid the A→B / B→A double-replacement problem.
    Only swaps explicit camera-frame terms; does not touch anatomical directions
    ("his left hand", "her right shoulder") or anchor-relative directions.
    """
    if not text:
        return text
    for a, b in _FRAME_LR_PAIRS:
        tok = f'__{a.upper().replace("-", "_")}__'
        text = text.replace(a, tok)
        text = text.replace(b, a)
        text = text.replace(tok, b)
    return text


_DISPOSITION_RULES = """CRITICAL — USE ONLY PHYSICAL LANDMARKS. NEVER use "screen-left", "screen-right", "frame-left", "frame-right".
Screen direction depends on camera angle and changes between panels —
visual_disposition must be camera-agnostic.
NEVER use compass directions (North/South/East/West) — coordinates are image-relative [0,1] fractions.

Use ONLY: named anchor objects (sofa / armchair / bar counter / entrance door / panoramic window),
image-relative wall names (image-left wall / image-right wall / entrance wall / far wall),
physical relations (back to the image-left wall / facing the entrance / standing beside the sofa).

Each panel has a "view_type" field for your spatial reasoning only.
  "From-Entrance" — canonical Y-axis: entrance at y=0, far wall at y=1. Higher Y = deeper in room.
                    Covers View-From-Entrance, View-Center-To-Far, View-By-Far-Wall.
                    Outdoor: View-Primary. Left/right match the source reference.
  "To-Entrance"   — reversed Y-axis: camera at far/entrance wall looking toward entrance. Left/right SWAPPED.
                    Covers View-To-Entrance, View-Center-To-Entrance, View-By-Entrance.
                    Outdoor: View-Opposite.
  "Lateral"       — 90°-rotated axis: camera on the image-left or image-right wall.
                    Depth runs along X (not Y): larger |object_x − camera_x| = farther from camera.
                    Left/right in frame corresponds to the Y axis (entrance-to-far-wall).
                    Use camera_x to determine which wall (x≈0 = image-left wall, x≈1 = image-right wall).
Do NOT write "MIRROR VIEW:" or any screen-direction annotation in the output.

VIEW VALIDATION (fields: swap_view + swap_view_reason):
Camera axis semantics:
  - "From-Entrance": camera at/near entrance, looking INTO room.
  - "To-Entrance": camera deep inside room, looking TOWARD entrance.

━━ FIRST: classify the shot ━━

Before anything else, classify this panel into exactly one category:
  A. FACE SHOT — visual_start contains "CLOSE-UP", "ECU", "EXTREME CLOSE-UP", or a tight
     portrait framing on a SINGLE character's face, OR the panel's dialogue line is spoken
     BY that character. The primary intent is showing one character's face expression.
  B. TWO-SHOT — visual_start begins with "MEDIUM SHOT" or "WIDE" AND two character names
     from references[] are both described in the same frame ("Opposite", "across the desk",
     "between them"). Wide establishing or two-character coverage.
  C. ACTION / WIDE SINGLE — fall, crash, movement, or single-character medium/wide shot
     where no close face is the primary subject.
  D. INSERT — extreme close-up of an object only (hands, folder, object); no character face.

━━ PRIMARY METHOD — use ONLY for category A (FACE SHOTS) ━━

STEP A — Subject's facing direction:
  PRIMARY SOURCE: read `state_actors[].chest_direction` for the primary subject first.
  This is the authoritative Pass 1A output — do not override it with prose inference.
  chest_direction → room-relative meaning:
    "toward_entrance" / contains "entrance" / contains "door"  → faces TOWARD entrance
    "toward_far_wall" / contains "window" / "away from entrance" → faces AWAY from entrance
    "lateral" / "toward_left_wall" / "toward_right_wall"        → PROFILE → swap_view=false, stop
  FALLBACK (only when chest_direction is absent or clearly lateral): use narrative context.
  In a bilateral confrontation: character at entrance zone faces AWAY from entrance; character
  at far/desk zone faces TOWARD entrance.
  WARNING — never infer facing from background descriptions:
    "far wall behind subject" → far wall is OPPOSITE the camera; tells you nothing about facing.
    "entrance behind subject" → entrance is OPPOSITE the camera; tells you nothing about facing.
  Express result as "toward entrance" or "away from entrance".

STEP B — Camera direction for a face shot:
  PRIMARY: if camera_y is available, use it directly:
    camera_y ≤ 0.3 → camera is at entrance side → From-Entrance.
    camera_y ≥ 0.7 → camera is at far side → To-Entrance.
    camera_y 0.3–0.7 → center-room; fall back to SECONDARY rule below.
  SECONDARY (when camera_y unavailable or center-room):
    A face shot shows the character looking AT the camera (front-on or near-front).
    Camera is therefore on the side the character faces TOWARD.
    Character faces TOWARD entrance → camera at entrance → From-Entrance.
    Character faces AWAY from entrance → camera on far side → To-Entrance.
  • OVER-THE-SHOULDER / POV: camera is BEHIND the named subject, looking at the target.
    Apply the above rule to the TARGET character (whose face is actually visible), not the subject.

STEP C — Decide swap:
  Compare inferred view_type to current view_type.
  ECU/CU (tight single-character shots): swap_view=true ONLY on GEOMETRIC IMPOSSIBILITY —
    the character's face definitively points away from the current camera axis, making the
    face shot physically impossible. Ambiguous, weakly-inferred, or background-derived
    facing evidence → swap_view=false. When in doubt, preserve the existing view.
  MS/WS face shots: swap_view=true when evidence is clear and consistent.

━━ FALLBACK — use for categories B, C, D ━━

  • TWO-SHOT (B): NEVER swap. Use whichever view best matches the established scene axis.
  • "[furniture/desk] in foreground" between camera and subject → camera is on far/desk side
    → To-Entrance (camera past the furniture looking toward entrance).
  • "[element] behind [subject]" → that element is on the wall OPPOSITE the camera.
    Map to anchor_points wall → camera is on the opposing wall.
  • Action shots with no clear spatial signals → set swap_view=false (leave unchanged).
  • INSERT (D): no swap.

NEVER swap: profiles, silhouettes, rear shots, overhead shots.
Set false when classification is ambiguous or signals are absent.

For EACH panel output swap_view_reason: one sentence — shot category, primary signal used,
and decision. Examples:
  "Category A face shot, Svetlana faces toward entrance → camera at entrance → From-Entrance; current To-Entrance wrong → swap=true"
  "Category A face shot, Pavel faces away from entrance → camera on desk side → To-Entrance; current From-Entrance wrong → swap=true"
  "Category B two-shot → no swap"
  "Category C action, desk in foreground → camera on far/desk side → To-Entrance; current From-Entrance wrong → swap=true"
  "Category D insert, no swap"

RULES:
0. CAMERA-SIDE EXCLUSION — apply before all other rules:
   Inspect lights_and_camera and visual_start for POV or OTS signals:
     - "POV", "point-of-view", "[Name]'s POV", "POV from [Name]"
     - "over-the-shoulder of [Name]", "OTS [Name]", "camera behind [Name]"
     - "subjective camera", "first-person view"
   Any character identified as the camera source is BEHIND the lens and NOT visible in frame.
   In visual_disposition write: "[Name] — behind camera, not in frame" for that character.
   Do NOT place them in foreground, background, or any spatial zone.
   They may only appear as a partial anonymous element (e.g. "shoulder edge in extreme foreground corner")
   if visual_start explicitly describes a partial OTS sliver — and only then.
1. Identify which characters are VISIBLE in frame from visual_start, visual_end, references, dialogue.
   Exclude any character identified as the camera source per Rule 0.
2. Assign each visible character to the most appropriate zone using only physical landmark language.
   For moving panels (non-empty motion_prompt): state BOTH the origin anchor (visual_start) and
   destination anchor (visual_end), e.g. "Alisa moves FROM the marble table TOWARD the bar counter".
3. Enforce cross-panel consistency: a character assigned to an anchor in panel 1 stays at that anchor
   in all subsequent panels unless motion_prompt explicitly moves them.
   Read ALL panels before writing any — assign anchors globally first.
4. For tables: name the physical chair using the id/label from anchor_points.objects[].notes
   (notes use image-left/image-right terms, not compass). Never use screen directions.
5. For single-character or no-character panels: name the nearest anchor object and depth
   (close to camera / mid-room / far end of room).
6. Keep each visual_disposition under 120 words.

DEPTH STACK RULE — required whenever furniture or props exist in the scene:
Use camera_y from the panel to determine depth order. Depth = distance from camera along the
camera's primary axis:
  - camera_y ≤ 0.3 (entrance side) or camera_y ≥ 0.7 (far side): primary axis is Y.
      Depth of object = |object_y − camera_y|. Larger = farther from camera.
  - camera_x ≤ 0.15 or camera_x ≥ 0.85 (side-wall axis): primary axis is X.
      Depth of object = |object_x − camera_x|. Larger = farther from camera.
  - Fallback when camera_x/y is null: use view_type:
      From-Entrance / To-Entrance → Y axis. Lateral → X axis.
For every object whose depth is BETWEEN the camera's depth and the character's depth, express
it as occlusion:
  "[object] [surface/edge] occupies [lower/upper] [fraction] of frame;
   [character] visible from [body part] upward above [object edge]"
Append a DEPTH line to visual_disposition:
  "DEPTH: [nearest to camera] → [mid-ground] → [background]"
Never omit the depth chain when furniture is between the camera and the subject.

CHAIR FACING — when assigning a character to a chair anchor:
Each chair in anchor_points.objects[] carries facing_degrees_y (0=toward entrance, 90=image-right,
180=toward far wall, 270=image-left; -1=omnidirectional).
Include the facing in visual_disposition: "seated in [chair-id] (facing [wall description])".
Example: chair with facing_degrees_y=90 → "seated in chair-left-near, facing image-right wall".
This is the authoritative facing source — do NOT override it with chest_direction inferences.

LATERAL AXES — append BOTH lines after DEPTH. NEVER use "frame-left" or "frame-right" here.
Coordinates are normalized [0,1]: X=0 = image-left wall, X=1 = image-right wall,
Y=0 = entrance wall, Y=1 = far wall.

Determine lateral axis from camera coordinates:
  camera_y ≤ 0.3 or camera_y ≥ 0.7 → Entrance/Far-wall axis → lateral axis is X.
  camera_x ≤ 0.15 or camera_x ≥ 0.85 → Side-wall axis → lateral axis is Y.
  camera_x/y null → fall back to view_type: From-Entrance/Opposite → X; To-Entrance → X (mirrored).

For each in-frame actor: look up their nearest anchor in anchor_points.objects[] or anchor_points.zones[].
Read that anchor's x and y.

X-axis classification (center band = [0.35, 0.65]):
  x < 0.35  → image-left side
  x > 0.65  → image-right side
  else       → center-X

Y-axis classification (center band = [0.35, 0.65]):
  y < 0.35  → entrance-end
  y > 0.65  → far-end
  else       → center-Y

Append:
  "LATERAL-X: [CharA] [image-left/center-X/image-right side] (x≈N) | [CharB] ..."
  "LATERAL-Y: [CharA] [entrance-end/center-Y/far-end] (y≈N) | [CharB] ..."

When all actors share the same classification: "all actors [class] (x≈N)" or "(y≈N)"."""


def _disposition_panels_context(panels: list[dict]) -> list[dict]:
    return [
        {
            'panel_index': p.get('panel_index'),
            'view_type': _panel_view_type(p),
            'camera_position': p.get('camera_position', ''),
            'camera_x': p.get('camera_x'),
            'camera_y': p.get('camera_y'),
            'camera_z': p.get('camera_z'),
            'visual_start': p.get('visual_start', ''),
            'lights_and_camera': p.get('lights_and_camera', ''),
            'motion_prompt': p.get('motion_prompt', ''),
            'references': p.get('references', []),
            'location_references': p.get('location_references', []),
            'dialogue': p.get('dialogue', ''),
            'state_actors': [
                {
                    'name': a.get('name'),
                    'position': a.get('position'),
                    'in_frame': a.get('in_frame'),
                    'chest_direction': a.get('chest_direction', ''),
                }
                for a in p.get('state', {}).get('actors', [])
            ],
        }
        for p in panels
    ]


def _disposition_prompt(scene: dict, anchor_points: dict, prev_terminal_disposition: str,
                        panels_context: list[dict]) -> str:
    return f"""You are a spatial continuity supervisor for an AI-generated drama series.

Your task: write a visual_disposition field for EACH panel in the scene.

visual_disposition is a compact natural-language string that pins every character present
in the panel to a specific zone or anchor object in the room.
It is injected verbatim into the image generation prompt alongside visual_start.
It must be SELF-CONTAINED — no "same as before", no panel references.

ROOM LOCATION: {scene.get('location', '')}

ANCHOR POINTS (coordinate system + named zones with copy-paste hints):
{json.dumps(anchor_points, ensure_ascii=False, indent=2)}
{f"""
CROSS-SCENE ANCHOR CONTINUITY:
The previous scene ended with this spatial disposition for its last panel:
<PREV_SCENE_TERMINAL_DISPOSITION>
{prev_terminal_disposition}
</PREV_SCENE_TERMINAL_DISPOSITION>
If this scene opens in the same physical location, character anchor assignments MUST be
identical to the above — same chair, same wall, same zone. Do not reassign characters
to different anchors unless motion_prompt explicitly moves them in this scene.
""" if prev_terminal_disposition else ""}{f"""
SCREENPLAY SCENE ENTRY POSITIONS:
The screenwriter declared the following character starting positions for this scene:
<INITIAL_DISPOSITION>
{scene.get('initial_disposition', '')}
</INITIAL_DISPOSITION>
Resolve natural-language positions to the nearest anchor zone from ANCHOR POINTS above.
Use as spatial ground truth for P1's visual_disposition.
When CROSS-SCENE ANCHOR CONTINUITY is also present and this scene continues in the same
location, prefer the terminal anchor positions from the previous scene — they are more
precise. Use INITIAL_DISPOSITION only when prev_terminal_disposition is absent or when
this scene opens in a different location.
""" if scene.get('initial_disposition') else ""}
{_DISPOSITION_RULES}

SCENE PANELS:
{json.dumps(panels_context, ensure_ascii=False, indent=2)}

Return a JSON array: [{{"panel_index": N, "visual_disposition": "...", "swap_view": false, "swap_view_reason": "..."}}, ...]
Set swap_view=true only for panels where the view must be flipped (see VIEW VALIDATION above).
swap_view_reason is required for every panel. """


def _apply_view_swap(p: dict, available_refs: frozenset[str], reason: str) -> bool:
    """Flip the panel's location refs to the opposite view and mirror frame-left/right in its text."""
    idx = p.get('panel_index')
    old_refs = p.get('location_references', [])
    new_refs = [_swap_view_ref(r) for r in old_refs]
    if new_refs == old_refs:
        return False
    if available_refs:
        # Only flag refs that actually changed (have a known view suffix) and are absent.
        missing = [r for r, o in zip(new_refs, old_refs) if r != o and r not in available_refs]
        if missing:
            logger.warning(
                f"      ⚠️  Panel {idx}: swap_view=true but target ref(s) not found "
                f"— skipping swap. Missing: {missing}"
            )
            return False
    p['location_references'] = new_refs
    mirrored_fields = []
    for field in ('visual_start', 'visual_end', 'motion_prompt', 'visual_start_explicit'):
        if p.get(field):
            original = p[field]
            p[field] = _mirror_screen_directions(original)
            if p[field] != original:
                mirrored_fields.append(field)
    mirror_note = f", mirrored: {mirrored_fields}" if mirrored_fields else ""
    logger.info(f"      🔄 Panel {idx}: view swapped {old_refs} → {new_refs}"
                + (f" [{reason}]" if reason else "") + mirror_note)
    return True


def _puppet_rewrite(panels: list[dict], anchor_points: dict, disp_map: dict, scene_id) -> None:
    """Validate 180-rule/transitions and replace LLM dispositions with deterministic ones (never raises)."""
    if not (anchor_points and anchor_points.get('zones')):
        return
    try:
        frames = _puppet.build_scene_frames(panels, anchor_points)

        # Validate 180-degree rule — log warnings, never block
        for v in _puppet.validate_180_rule(frames):
            logger.warning(
                f"      ⚠️  180-rule: panel {v['panel_a']}→{v['panel_b']}: {v['reason']}"
            )

        # Validate movement transitions — log warnings, never block
        for v in _puppet.SceneState(frames, room_m=anchor_points.get('room_m', [8.0, 8.0])).validate_transitions():
            logger.warning(
                f"      ⚠️  Transition jump: panel {v['panel_a']}→{v['panel_b']} "
                f"'{v['character']}' moved {v['distance_m']}m "
                f"(budget {v['budget_m']}m)"
            )

        # Replace LLM-generated visual_disposition with deterministic output
        panel_by_idx = {p.get('panel_index'): p for p in panels}
        det_rewrites = 0
        for frame in frames:
            if frame.panel_index not in disp_map:
                continue  # LLM produced no disposition for this panel — skip
            if not frame.characters:
                continue  # no zone assignments parsed — keep LLM text
            det = _puppet.compile_visual_disposition(frame, anchor_points)
            if det:
                panel_by_idx[frame.panel_index]['visual_disposition'] = det
                det_rewrites += 1
        if det_rewrites:
            logger.info(
                f"      🎭 Puppet: {det_rewrites}/{len(panels)} panels rewritten deterministically"
            )
    except Exception:
        logger.exception(
            f"      ⚠️  Puppet post-processing failed for scene {scene_id} — LLM disposition kept"
        )


def apply_spatial_disposition_pass(
    scene: dict,
    anchor_points: dict,
    llm: BaseLLM,
    prev_terminal_disposition: str = '',
    available_refs: frozenset[str] = frozenset(),
) -> dict:
    """Write visual_disposition for each panel, grounded in room anchor_points.

    Reads panels from scene, calls LLM once per scene with anchor coordinate context,
    writes visual_disposition back into each panel dict in-place.
    prev_terminal_disposition: visual_disposition of the last panel of the previous scene
    in the same location — used to enforce cross-scene anchor consistency.
    available_refs: set of known ref names used to validate swap_view targets before applying.
    Skips panels where LLM returns no result; never raises.
    """
    scene_id = scene.get('scene_id', '?')
    panels = scene.get('panels', [])
    if not panels:
        return scene

    prompt = _disposition_prompt(scene, anchor_points, prev_terminal_disposition,
                                 _disposition_panels_context(panels))

    result = llm.make_json(prompt, SPATIAL_DISPOSITION_SCHEMA)
    if not result:
        logger.error(f"      ❌ Spatial disposition LLM call returned empty for scene {scene_id}")
        return scene

    items = result if isinstance(result, list) else result.get('items', [])
    disp_map = {
        item['panel_index']: item['visual_disposition']
        for item in items
        if item.get('visual_disposition')
    }
    swap_set = {item['panel_index'] for item in items if item.get('swap_view')}
    swap_reasons = {item['panel_index']: item.get('swap_view_reason', '') for item in items}

    updated = 0
    swapped = 0
    for p in panels:
        idx = p.get('panel_index')
        if idx in disp_map:
            p['visual_disposition'] = disp_map[idx]
            updated += 1
        if idx in swap_set and _apply_view_swap(p, available_refs, swap_reasons.get(idx, '')):
            swapped += 1

    logger.info(
        f"      ✅ Spatial disposition: {updated}/{len(panels)} panels for scene {scene_id}"
        + (f", {swapped} view(s) corrected" if swapped else "")
    )
    _puppet_rewrite(panels, anchor_points, disp_map, scene_id)
    return scene


def apply_spatial_rewrite_pass(
    scene: dict,
    anchor_points: dict,
    llm: BaseLLM,
) -> dict:
    """Correct spatial contradictions in visual_start / motion_prompt using visual_disposition.

    Runs AFTER apply_spatial_disposition_pass (visual_disposition must already be set).
    Sends one LLM call per scene group with anchor data + the anchor-grounded disposition
    as ground truth. Only panels with a factual spatial contradiction are returned and patched.
    Never raises; logs and skips on LLM failure.
    """
    scene_id = scene.get('scene_id', '?')
    panels = [p for p in scene.get('panels', []) if p.get('visual_disposition')]
    if not panels:
        logger.info(f"      ⏭  Scene {scene_id}: no panels with visual_disposition — skipping rewrite pass")
        return scene

    panels_context = [
        {
            'panel_index': p.get('panel_index'),
            'visual_disposition': p.get('visual_disposition', ''),
            'visual_start': p.get('visual_start', ''),
            'motion_prompt': p.get('motion_prompt', ''),
            'camera_position': p.get('camera_position', ''),
            'camera_x': p.get('camera_x', ''),
            'camera_y': p.get('camera_y', ''),
            'camera_z': p.get('camera_z', ''),
            'actors': p.get('state', {}).get('actors', []),
        }
        for p in panels
    ]

    prompt = f"""You are a spatial consistency corrector for an AI-generated drama series.

TASK: compare each panel's visual_start (and motion_prompt) against its anchor-grounded
visual_disposition, which is the authoritative spatial ground truth. Fix ONLY definite
factual spatial contradictions — wrong frame-left/right, wrong depth label, impossible
subject position given the anchor data. Do NOT rewrite vague or merely underspecified text.

CORRECTION RULES:
1. Contradiction = a term in visual_start or motion_prompt that directly conflicts with
   what visual_disposition establishes (e.g. visual_disposition says "Alisa — image-LEFT side"
   but visual_start says "Alisa enters from frame-right").
2. Change ONLY the contradicted spatial term(s). Preserve all other prose verbatim.
3. If no contradiction exists → return empty strings for both fields.
4. Preserve shot scale, lighting description, camera angle prose, dialogue context.
5. Do NOT "improve" text that is correct or merely vague — only fix direct conflicts.
6. motion_prompt_rewrite: only set when motion_prompt references a frame direction or depth
   that contradicts visual_disposition. Never set if motion_prompt is absent or empty.

ROOM ANCHOR GEOMETRY:
{json.dumps(anchor_points, ensure_ascii=False, indent=2)}

SCENE PANELS (visual_disposition = ground truth):
{json.dumps(panels_context, ensure_ascii=False, indent=2)}

Return a JSON array — one entry per panel:
[{{"panel_index": N, "visual_start_rewrite": "...", "motion_prompt_rewrite": ""}}, ...]
Include ALL panels. Use empty string when no correction is needed.
"""

    result = llm.make_json(prompt, SPATIAL_REWRITE_SCHEMA)
    if not result:
        logger.error(f"      ❌ Spatial rewrite LLM call returned empty for scene {scene_id}")
        return scene

    items = result if isinstance(result, list) else result.get('items', [])
    panel_by_idx = {p.get('panel_index'): p for p in scene.get('panels', [])}
    rewritten = 0
    for item in items:
        idx = item.get('panel_index')
        panel = panel_by_idx.get(idx)
        if panel is None:
            continue
        vs_rewrite = (item.get('visual_start_rewrite') or '').strip()
        mp_rewrite = (item.get('motion_prompt_rewrite') or '').strip()
        if vs_rewrite:
            logger.info(f"      ✏️  Panel {idx}: visual_start rewritten by spatial rewrite pass")
            logger.debug(f"        before: {panel.get('visual_start', '')[:120]}")
            logger.debug(f"        after:  {vs_rewrite[:120]}")
            panel['visual_start'] = vs_rewrite
            rewritten += 1
        if mp_rewrite:
            logger.info(f"      ✏️  Panel {idx}: motion_prompt rewritten by spatial rewrite pass")
            logger.debug(f"        before: {panel.get('motion_prompt', '')[:120]}")
            logger.debug(f"        after:  {mp_rewrite[:120]}")
            panel['motion_prompt'] = mp_rewrite
            rewritten += 1

    logger.info(
        f"      ✅ Spatial rewrite: scene {scene_id} — {rewritten} field(s) corrected "
        f"across {len(panels)} panel(s)"
    )
    return scene
