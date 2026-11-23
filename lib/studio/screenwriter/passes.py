"""Scene passes: 1 architecture, 1A state, 1B placement, 2 visual, 3 motion and audio, and their merge."""
import json
import logging

from lib.core.prompts import TARGET_LANGUAGE
from lib.core.schemas import (
    PASS1_SCHEMA,
    PASS1A_SCHEMA,
    PASS1B_SCHEMA,
    PASS2_SCHEMA,
    PASS3_SCHEMA,
)
from lib.llm.base import BaseLLM
from lib.studio.blocking_sketch import block_text, panel_blocking
from lib.studio.screenwriter.episodes import _episode_narrative_block

logger = logging.getLogger(__name__)


def _pass1_architecture(
    scene_spec: dict,
    episode_context: dict,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    continuity_block: str,
    episode_type_block: str,
    prev_episode_exit: dict = None,
) -> dict | None:
    """Pass 1: scene_trajectories + panel skeletons (hook_type, duration, scale, motion_intent, dialogue_seed)."""
    setting = prompts.get('setting', '')
    rules = prompts.get('pass1_architecture', '')
    scene_id = scene_spec.get('scene_local_id', 1)
    panel_count = scene_spec.get('panel_count', 9)

    visual_end = (prev_episode_exit or {}).get('visual_end', '')
    prev_exit_block = (
        f"\nPREVIOUS SCENE EXIT STATE (last frame the viewer saw — first panel MUST visually follow from this):\n{visual_end}\n"
        if visual_end else ""
    )

    prompt = f"""{setting}

{rules}

{continuity_block}
{episode_type_block}
{prev_exit_block}
TARGET SCENE: {scene_id} — {scene_spec.get('location', '')}
PANEL COUNT: Generate EXACTLY {panel_count} panel stubs.

SCENE INSTRUCTIONS:
{scene_spec.get('scene_instructions', '')}

EPISODE CONTEXT:
{json.dumps(episode_context, ensure_ascii=False, indent=2)}
"""
    result = llm.make_json(prompt, PASS1_SCHEMA)
    if not result or not result.get('scenes'):
        logger.error(f"  ❌ Pass 1 failed for scene {scene_id}")
        return None
    return result['scenes'][0]


def _pass1a_state(
    scene_spec: dict,
    p1_scene: dict,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    character_info: dict,
    location_anchors: dict,
    episode_context: dict = None,
    prev_episode_exit: dict = None,
    correction: str = '',
) -> dict | None:
    """Pass 1A: panel state chain (actor positions, props, complete_disposition) + motion_action."""
    rules = prompts.get('pass1a_state', '')
    scene_id = scene_spec.get('scene_local_id', 1)
    panel_count = scene_spec.get('panel_count', 9)

    # Build minimal char block — behavioral signatures + variation menus (no visual details needed here)
    char_lines = []
    for name, info in (character_info or {}).items():
        # Skip variation refs in the top-level listing — they appear as sub-items under their parent
        if info.get('character_ref'):
            continue
        bsig = info.get('behavioral_signature', '')
        pvoc = info.get('physical_vocabulary', '')
        if bsig or pvoc:
            char_lines.append(f"- {name}: {bsig} | {pvoc}")
        else:
            char_lines.append(f"- {name}")
        # Inject appearance variation menu if this character has variations
        variations = info.get('variations', [])
        if variations:
            var_items = []
            for var_name in variations:
                var_info = (character_info or {}).get(var_name, {})
                ctx = var_info.get('context', '')
                var_items.append(f"  * {var_name}: {ctx}" if ctx else f"  * {var_name}")
            char_lines.append(
                "  APPEARANCE VARIATIONS — select visual_ref for each panel based on scene context:\n"
                + "\n".join(var_items)
                + "\n  (use base character name as visual_ref if none of the above apply)"
            )
    char_block = "CAST IN SCENE:\n" + "\n".join(char_lines) if char_lines else ""

    anchors_block = ""
    if location_anchors:
        anchors_block = (
            "ROOM ANCHOR POINTS — authoritative spatial reference for this scene.\n"
            "Use ONLY these named landmarks for actor positions. FORBIDDEN: compass directions, invented doorway names.\n"
            + json.dumps(location_anchors, ensure_ascii=False, indent=2)
        )

    trajectories_json = json.dumps(p1_scene.get('scene_trajectories', []), ensure_ascii=False, indent=2)
    skeletons_json = json.dumps(p1_scene.get('panels', []), ensure_ascii=False, indent=2)
    initial_disposition = scene_spec.get('initial_disposition', '')

    narrative_block = _episode_narrative_block(episode_context)

    prev_state = (prev_episode_exit or {}).get('state')
    prev_state_block = (
        "PREVIOUS SCENE EXIT STATE — actors/props/disposition at the last frame of the previous scene.\n"
        "Panel 1 state chain MUST begin from this baseline (carry positions, poses, props forward unless the scene explicitly changes them):\n"
        + json.dumps(prev_state, ensure_ascii=False, indent=2)
        if prev_state else ""
    )

    declared = {k: scene_spec[k] for k in ('transition_in', 'entry_state', 'exit_state') if scene_spec.get(k)}
    declared_block = (
        "SCREENPLAY STATE CONTRACT — panel 1 matches entry_state, the last panel reaches exit_state "
        "(seats, places, wardrobe); every change in between is performed by a motion_action:\n"
        + json.dumps(declared, ensure_ascii=False, indent=2) if declared else ""
    )

    prompt = f"""{rules}

{char_block}

{anchors_block}

{narrative_block}

{prev_state_block}

{declared_block}

SCENE: {scene_spec.get('location', '')}
PANEL COUNT: {panel_count} panels — produce EXACTLY {panel_count} panel state entries.

INITIAL DISPOSITION (scene open — map every positional term to a named ROOM ANCHOR POINT above; anchor-relative relations only, no coordinates):
{initial_disposition if initial_disposition else "(not specified — infer from scene instructions)"}

SCENE TRAJECTORIES (from Pass 1):
{trajectories_json}

PANEL SKELETONS (motion_intent per panel, from Pass 1):
{skeletons_json}

SCENE INSTRUCTIONS:
{scene_spec.get('scene_instructions', '')}

{correction}
"""
    result = llm.make_json(prompt, PASS1A_SCHEMA)
    if not result or not result.get('panels'):
        logger.warning(f"  ⚠️  Pass 1A returned empty for scene {scene_id} — continuing without state")
        return None
    return result


# Counterpart views of each canonical (anchor-keyed) view; optional ones count only when their ref exists.
_COUNTERPART_VIEWS = {
    '-View-From-Entrance': ('-View-To-Entrance',),
    '-View-From-Left-Wall': ('-View-From-Right-Wall',),
    '-View-Center-To-Far': ('-View-Center-To-Entrance',),
    '-View-By-Far-Wall': ('-View-By-Entrance',),
    '-View-Primary': ('-View-Opposite', '-View-Ortho-Primary', '-View-Ortho-Opposite'),
    '-Interior-From-Entrance': ('-Interior-To-Entrance',),
}
_OPTIONAL_VIEWS = ('-View-Ortho-Primary', '-View-Ortho-Opposite')


def _counterpart_slugs(location_keys, available) -> list[str]:
    """Other valid view refs of the anchored locations, for the prompt's location_references rule."""
    slugs = []
    for key in location_keys:
        for suffix, others in _COUNTERPART_VIEWS.items():
            if key.endswith(suffix):
                base = key[: -len(suffix)]
                slugs += [base + o for o in others if o not in _OPTIONAL_VIEWS or base + o in available]
    return slugs


def _pass1b_disposition(
    scene_spec: dict,
    p1_scene: dict,
    p1a_result: dict | None,
    prompts: dict,
    llm: BaseLLM,
    location_anchors: dict,
    correction: str = '',
    available_refs=frozenset(),
) -> dict | None:
    """Pass 1B: camera placement + spatial disposition per panel.

    Requires location_anchors (room anchor_points) and the pass1b_disposition prompt.
    Returns None silently when either is absent — Pass 2 falls back to self-computed camera.
    """
    rules = prompts.get('pass1b_disposition', '')
    if not rules or not location_anchors:
        return None

    scene_id = scene_spec.get('scene_local_id', 1)
    panel_count = scene_spec.get('panel_count', 9)

    reversed_slugs = _counterpart_slugs(location_anchors, available_refs)
    also_valid = (
        "\nAlso valid as location_references (opposite-direction counterparts): "
        + ", ".join(f'"{s}"' for s in reversed_slugs)
        if reversed_slugs else ""
    )

    anchors_block = (
        "ROOM ANCHOR POINTS (use only named anchors listed below):\n"
        + json.dumps(location_anchors, ensure_ascii=False, indent=2)
        + also_valid
    )

    skeletons_json = json.dumps(p1_scene.get('panels', []), ensure_ascii=False, indent=2)
    state_json = (
        json.dumps(p1a_result.get('panels', []), ensure_ascii=False, indent=2)
        if p1a_result else "(not available)"
    )
    # drama_requirements per panel — declared in Pass 1; used here as area-of-interest signal for camera axis.
    # Keyed by panel_index so Pass 1B can look up the primary_target for each panel.
    drama_per_panel = {
        p.get('panel_index'): p.get('drama_requirements', {})
        for p in p1_scene.get('panels', [])
        if p.get('drama_requirements')
    }
    drama_block = (
        "DRAMA REQUIREMENTS from Pass 1 (keyed by panel_index).\n"
        "focus_priority.primary_target = the actor/anchor the camera looks AT — use as area of interest for STEP 2 axis derivation:\n"
        + json.dumps(drama_per_panel, ensure_ascii=False, indent=2)
    ) if drama_per_panel else ""

    prompt = f"""{rules}

{anchors_block}

{drama_block}

SCENE: {scene_spec.get('location', '')}
PANEL COUNT: {panel_count} panels — produce EXACTLY {panel_count} entries.

INITIAL DISPOSITION:
{scene_spec.get('initial_disposition', '(not specified)')}

PANEL SKELETONS from Pass 1 (scale, hook_type, motion_intent, drama_requirements):
{skeletons_json}

PANEL STATES from Pass 1A (actor positions, chest_direction, complete_disposition):
{state_json}

{correction}
"""

    result = llm.make_json(prompt, PASS1B_SCHEMA)
    if not result or not result.get('panels'):
        logger.warning(f"  ⚠️  Pass 1B returned empty for scene {scene_id} — proceeding without disposition")
        return None
    return result


def _resolve_effective_char_info(character_info: dict, p1a_result: dict | None) -> dict:
    """
    After Pass 1A, substitute variation refs for base character refs in character_info.

    Scans visual_ref values from all panel states. Where a visual_ref is a variation
    (has character_ref set), replaces the base character entry with the variation entry
    (inheriting behavioral_signature/physical_vocabulary from the parent if not set on
    the variation). Non-character refs (locations, objects) pass through unchanged.

    Returns a new dict suitable for Pass 2 char_block construction.
    """
    if not p1a_result or not character_info:
        return character_info or {}

    # Collect all visual_refs used across the scene's panels
    used_visual_refs: set[str] = set()
    for panel in p1a_result.get('panels', []):
        for actor in panel.get('state', {}).get('actors', []):
            vref = actor.get('visual_ref') or actor.get('name', '')
            if vref:
                used_visual_refs.add(vref)

    # Determine which base characters are replaced by an active variation
    replaced_bases: set[str] = set()
    for vref in used_visual_refs:
        info = character_info.get(vref, {})
        parent = info.get('character_ref', '')
        if parent and parent in character_info:
            replaced_bases.add(parent)

    effective: dict = {}
    for name, info in character_info.items():
        is_variation = bool(info.get('character_ref'))
        if is_variation:
            # Include only variations that are actually used in this scene
            if name in used_visual_refs:
                entry = dict(info)
                parent = info.get('character_ref', '')
                base = character_info.get(parent, {})
                # Inherit behavioral/physical from parent when not set on the variation
                if not entry.get('behavioral_signature'):
                    entry['behavioral_signature'] = base.get('behavioral_signature', '')
                if not entry.get('physical_vocabulary'):
                    entry['physical_vocabulary'] = base.get('physical_vocabulary', '')
                effective[name] = entry
        elif name in replaced_bases:
            # Base character replaced by one or more active variations — skip its visual entry
            # BUT keep it as a face-anchor: do NOT add to char_block (variations carry style_reference → parent PNG)
            pass
        else:
            # Non-varied character, location, object, room, vehicle — include as-is
            effective[name] = info

    return effective or character_info


def _pass2_blocking_block(scene_spec: dict, p1_scene: dict, p1a_result: dict | None, p1b_result: dict | None,
                         character_info: dict, config: dict) -> str:
    """Per-panel blocking (car seats or resolved room positions), so Pass 2 writes the frame sides the render will use."""
    aspect = (config.get('image_generation') or {}).get('aspect_ratio', '9:16')
    by_index = [{p.get('panel_index'): p for p in (r or {}).get('panels', [])} for r in (p1a_result, p1b_result)]
    blocks = []
    for skeleton in p1_scene.get('panels', []):
        idx = skeleton.get('panel_index')
        b = panel_blocking({**skeleton, **by_index[0].get(idx, {}), **by_index[1].get(idx, {})}, scene_spec,
                           character_info.get, aspect)
        if b:
            body = block_text(b).splitlines()[1:]
            shot = f' vehicle_shot={b.shot}' if hasattr(b, 'shot') else ''
            blocks.append(f'P{idx}:{shot}\n' + '\n'.join(line for line in body if not line.startswith('Physical rules')))
    if not blocks:
        return ''
    return ('BLOCKING — computed from seats / resolved positions; AUTHORITATIVE. Copy each vehicle_shot and write '
            'frame-left/right, distance, facing and background in visual_start/visual_end exactly as listed.\n\n'
            + '\n\n'.join(blocks))


_VIEW_TO_AXIS = {
    'View-From-Entrance':      'Entrance  (x drives lateral: x<0.35→frame-left, x>0.65→frame-right; depth: low-Y=FG)',
    'View-Center-To-Far':      'Entrance  (x drives lateral: x<0.35→frame-left, x>0.65→frame-right; depth: low-Y=FG)',
    'View-By-Far-Wall':        'Entrance  (x drives lateral: x<0.35→frame-left, x>0.65→frame-right; depth: low-Y=FG)',
    'View-Primary':            'Entrance  (x drives lateral: x<0.35→frame-left, x>0.65→frame-right; depth: low-Y=FG)',
    'Interior-From-Entrance':  'Entrance  (x drives lateral: x<0.35→frame-left, x>0.65→frame-right; depth: low-Y=FG)',
    'View-To-Entrance':        'Far-wall  (1-x drives lateral: x>0.65→frame-left, x<0.35→frame-right; depth: high-Y=FG)',
    'View-Center-To-Entrance': 'Far-wall  (1-x drives lateral: x>0.65→frame-left, x<0.35→frame-right; depth: high-Y=FG)',
    'View-By-Entrance':        'Far-wall  (1-x drives lateral: x>0.65→frame-left, x<0.35→frame-right; depth: high-Y=FG)',
    'View-Opposite':           'Far-wall  (1-x drives lateral: x>0.65→frame-left, x<0.35→frame-right; depth: high-Y=FG)',
    'Interior-To-Entrance':    'Far-wall  (1-x drives lateral: x>0.65→frame-left, x<0.35→frame-right; depth: high-Y=FG)',
    'View-From-Left-Wall':     'Left-wall (1-y drives lateral: y>0.65→frame-left, y<0.35→frame-right; depth: low-X=FG)',
    'View-From-Right-Wall':    'Right-wall (y drives lateral: y<0.35→frame-left, y>0.65→frame-right; depth: high-X=FG)',
    'View-Ortho-Primary':      'Cross-axis (1-y drives lateral: y>0.65→frame-left, y<0.35→frame-right; depth: X just past the station=FG, X below it is behind camera)',
    'View-Ortho-Opposite':     'Cross-axis (y drives lateral: y<0.35→frame-left, y>0.65→frame-right; depth: X just short of the station=FG, X above it is behind camera)',
}
# Explicit camera facing direction per view — used for PROFILE derivation.
# PROFILE depends on whether actor chest_direction matches or opposes the camera's look direction.
_VIEW_TO_DIRECTION = {
    'View-From-Entrance':      'toward far wall (away from entrance)',
    'View-Center-To-Far':      'toward far wall (away from entrance)',
    'View-By-Far-Wall':        'toward far wall (away from entrance)',
    'View-Primary':            'toward primary landmark (away from camera)',
    'Interior-From-Entrance':  'toward interior / far end (away from entrance)',
    'View-To-Entrance':        'toward entrance (away from far wall)',
    'View-Center-To-Entrance': 'toward entrance (away from far wall)',
    'View-By-Entrance':        'toward entrance (away from far wall)',
    'View-Opposite':           'toward opposite landmark (away from primary)',
    'Interior-To-Entrance':    'toward entrance / exit (away from interior)',
    'View-From-Left-Wall':     'toward right wall (away from left wall)',
    'View-From-Right-Wall':    'toward left wall (away from right wall)',
    'View-Ortho-Primary':      'from the station toward the x=1 side (90° right of primary)',
    'View-Ortho-Opposite':     'from the station toward the x=0 side (90° left of primary)',
}


def _view_lookup(refs: list[str], table: dict[str, str], default: str) -> str:
    return next((value for ref in refs for suffix, value in table.items() if ref.endswith(suffix)), default)


def _axis_for_panel(refs: list[str]) -> str:
    return _view_lookup(refs, _VIEW_TO_AXIS, 'Entrance (default)')


def _direction_for_panel(refs: list[str]) -> str:
    return _view_lookup(refs, _VIEW_TO_DIRECTION, 'toward far wall (default)')


def _pass2_visual(
    scene_spec: dict,
    p1_scene: dict,
    p1a_result: dict | None,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    character_info: dict,
    location_anchors: dict,
    episode_context: dict = None,
    p1b_result: dict | None = None,
    correction: str = '',
) -> dict | None:
    """Pass 2: visual_start, visual_end, lights_and_camera, references per panel."""
    setting = prompts.get('setting', '')
    imagery = prompts.get('imagery', '')
    rules = prompts.get('pass2_visual', '')
    scene_id = scene_spec.get('scene_local_id', 1)
    panel_count = scene_spec.get('panel_count', 9)

    # Character refs — visual deviations only (canonical appearance is in reference images)
    char_lines = []
    for name, info in (character_info or {}).items():
        desc = info.get('visual_desc') or info.get('video_visual_desc', '')
        if desc:
            char_lines.append(f"- {name}: {desc}")
        else:
            char_lines.append(f"- {name}")
    char_block = (
        "CHARACTER/LOCATION REFERENCE BASELINE — write ONLY deviations from these in visual_start/visual_end:\n"
        + "\n".join(char_lines)
    ) if char_lines else ""

    anchors_block = ""
    if location_anchors:
        _reversed_slugs = _counterpart_slugs(location_anchors, character_info)
        _also_valid = (
            "\nAlso valid as location_references (opposite-direction counterparts): "
            + ", ".join(f'"{s}"' for s in _reversed_slugs)
            if _reversed_slugs else ""
        )
        anchors_block = (
            "ROOM ANCHOR POINTS — authoritative spatial reference.\n"
            "camera_position MUST name a physical landmark from the objects/zones listed below "
            "(e.g. 'near entrance-door', 'at panoramic-windows end'). "
            "FORBIDDEN in camera_position: compass directions, invented room names.\n"
            "location_references MUST be the exact ref slug matching the camera's position and facing direction.\n"
            "8-POINT ROOM VIEW SELECTION (priority order — first rule that matches wins):\n"
            "  camera_y ≤ 0.20 → View-From-Entrance (near entrance, looking in)\n"
            "  camera_y ≥ 0.80 → View-To-Entrance (at far wall, looking toward entrance)\n"
            "  camera_x ≤ 0.20 → View-From-Left-Wall (image-left wall, looking toward image-right)\n"
            "  camera_x ≥ 0.80 → View-From-Right-Wall (image-right wall, looking toward image-left)\n"
            "  center-room (0.20–0.80 on both axes):\n"
            "    far wall (y=1) is background → View-Center-To-Far\n"
            "    entrance wall (y=0) is background → View-Center-To-Entrance\n"
            "  SPECIAL — use only when shot specifically requires wall-proximity framing:\n"
            "    View-By-Far-Wall: camera 1m from far wall, far wall fills frame — silhouette/window shots\n"
            "    View-By-Entrance: camera 1m from entrance, door fills frame — threshold/doorway shots\n"
            "Use the canonical slug (top-level key below). Opposite-direction counterparts listed above."
            + _also_valid + "\n"
            "AVAILABILITY: side-wall, center, and by-wall views may not exist for every room — "
            "if the slug does not appear in the anchor data, fall back to View-From-Entrance or View-To-Entrance.\n"
            "HARD FAILURE: a slug in location_references that does not appear in ROOM ANCHOR POINTS or its listed counterparts.\n"
            + json.dumps(location_anchors, ensure_ascii=False, indent=2)
        )

    skeletons_json = json.dumps(p1_scene.get('panels', []), ensure_ascii=False, indent=2)
    trajectories_json = json.dumps(p1_scene.get('scene_trajectories', []), ensure_ascii=False, indent=2)
    state_json = json.dumps(p1a_result.get('panels', []), ensure_ascii=False, indent=2) if p1a_result else "(not available)"
    initial_disposition = scene_spec.get('initial_disposition', '')
    narrative_block = _episode_narrative_block(episode_context)

    bg_activity = scene_spec.get('background_activity') or {}
    bg_block = (
        "BACKGROUND ACTIVITY — MANDATORY BGD: line in EVERY MS/MWS/WS/XWS panel "
        "(both visual_start and visual_end); skip at CU/ECU/Macro; state may progress across panels:\n"
        f"  crowd_type: {bg_activity.get('crowd_type', '')}\n"
        f"  density: {bg_activity.get('density', '')}\n"
        f"  movement: {bg_activity.get('movement', '')}\n"
        f"  focal_plane: {bg_activity.get('focal_plane', '')}\n"
    ) if bg_activity and bg_activity.get('density') != 'none' else ""

    # When Pass 1B produced camera placement, inject it as authoritative ground truth.
    # Pass 2 must copy these values verbatim and use visual_disposition as the projection baseline.
    # CRITICAL: projection axis is derived from location_references (already decided by 1B),
    # NOT re-derived from camera_x/y — the two can conflict on lateral-wall shots where
    # camera_y is high but the axis is lateral, not far-wall.

    p1b_block = ""
    if p1b_result and p1b_result.get('panels'):
        p1b_data = [
            {
                'panel_index': p.get('panel_index'),
                'camera_position': p.get('camera_position'),
                'camera_x': p.get('camera_x'),
                'camera_y': p.get('camera_y'),
                'camera_z': p.get('camera_z'),
                'location_references': p.get('location_references', []),
                'projection_axis': _axis_for_panel(p.get('location_references', [])),
                'camera_direction': _direction_for_panel(p.get('location_references', [])),
                'visual_disposition': p.get('visual_disposition', ''),
            }
            for p in p1b_result['panels']
        ]
        p1b_block = (
            "CAMERA PLACEMENT from Pass 1B — AUTHORITATIVE.\n"
            "Copy camera_position, camera_x, camera_y, camera_z, location_references verbatim into your output.\n"
            "DO NOT recompute camera position or view selection — those decisions are final.\n"
            "PROJECTION AXIS — use the `projection_axis` field below to determine frame-left/frame-right for each panel.\n"
            "HARD RULE: derive frame positions from projection_axis, NOT from camera_x/y priority rules.\n"
            "camera_x/y encode where the camera sits in the room; projection_axis encodes which spatial\n"
            "dimension drives the left/right split in the frame. These can differ on lateral-wall shots.\n"
            "CAMERA DIRECTION — use `camera_direction` field (per panel below) for STEP 1B PROFILE derivation.\n"
            "Use visual_disposition as the anchor-grounded starting point for visual_start projection.\n"
            + json.dumps(p1b_data, ensure_ascii=False, indent=2)
        )

    prompt = f"""{setting}

{imagery}

{char_block}

{anchors_block}

{narrative_block}

{bg_block}

{p1b_block}

{_pass2_blocking_block(scene_spec, p1_scene, p1a_result, p1b_result, character_info, config)}

{rules}

SCENE: {scene_spec.get('location', '')}
PANEL COUNT: {panel_count} panels — produce EXACTLY {panel_count} visual entries.

INITIAL DISPOSITION (all actors present at scene start — P1 non-ECU visual_start MUST include ALL of them):
{initial_disposition}

SCENE TRAJECTORIES:
{trajectories_json}

PANEL SKELETONS from Pass 1 (scale, motion_intent, drama_requirements per panel):
{skeletons_json}

PANEL STATES from Pass 1A (use as projection source for visual_start):
{state_json}

{correction}
"""
    result = llm.make_json(prompt, PASS2_SCHEMA)
    if not result or not result.get('panels'):
        logger.error(f"  ❌ Pass 2 failed for scene {scene_id}")
        return None
    return result


def _pass3_motion_audio(
    scene_spec: dict,
    p1_scene: dict,
    p1a_result: dict | None,
    p2_result: dict,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    episode_context: dict = None,
    correction: str = '',
) -> dict | None:
    """Pass 3: motion_prompt, dialogue, voiceover, sound_design, duration per panel."""
    rules = prompts.get('pass3_motion_audio', '')
    motion_dyn = prompts.get('motion_dynamics', '')
    scene_id = scene_spec.get('scene_local_id', 1)
    panel_count = scene_spec.get('panel_count', 9)

    skeletons_json = json.dumps(p1_scene.get('panels', []), ensure_ascii=False, indent=2)
    state_json = json.dumps(p1a_result.get('panels', []), ensure_ascii=False, indent=2) if p1a_result else "(not available)"
    visuals_json = json.dumps(p2_result.get('panels', []), ensure_ascii=False, indent=2)

    # For Pass 3, condensed narrative is the dialogue coverage contract — surface it prominently
    cn = (episode_context or {}).get('rewritten_condensed_narrative', '')
    cn_block = (
        f"DIALOGUE COVERAGE CONTRACT — every spoken line here MUST appear verbatim in `dialogue`/`voiceover` fields.\n"
        f"Do NOT invent lines not present here. Do NOT drop lines present here.\n{cn}"
        if cn else ""
    )

    bg_activity = scene_spec.get('background_activity') or {}
    bg_block = (
        "BACKGROUND ACTIVITY — append AMBIENT: note in EVERY panel that has a BGD: line (MS/MWS/WS/XWS); "
        "skip at CU/ECU/Macro; evolve crowd state to match Pass 2 BGD description for that panel:\n"
        f"  crowd_type: {bg_activity.get('crowd_type', '')}\n"
        f"  density: {bg_activity.get('density', '')}\n"
        f"  movement: {bg_activity.get('movement', '')}\n"
        f"  focal_plane: {bg_activity.get('focal_plane', '')}\n"
    ) if bg_activity and bg_activity.get('density') != 'none' else ""

    prompt = f"""{rules}

{motion_dyn}

{cn_block}

{bg_block}

SCENE: {scene_spec.get('location', '')}
PANEL COUNT: {panel_count} panels — produce EXACTLY {panel_count} motion/audio entries.
All dialogue, voiceover, and caption text MUST be in {TARGET_LANGUAGE}.

PANEL SKELETONS from Pass 1 (motion_intent + dialogue_seed):
{skeletons_json}

PANEL STATES from Pass 1A (motion_action per actor):
{state_json}

PANEL VISUALS from Pass 2 (visual_start + visual_end — your motion must connect these two states):
{visuals_json}

{correction}
"""
    result = llm.make_json(prompt, PASS3_SCHEMA)
    if not result or not result.get('panels'):
        logger.error(f"  ❌ Pass 3 failed for scene {scene_id}")
        return None
    return result


def _merge_scene_passes(
    scene_spec: dict,
    p1_scene: dict,
    p1a_result: dict | None,
    p2_result: dict,
    p3_result: dict,
    p1b_result: dict | None = None,
) -> dict:
    """Merge all pass outputs into a single scene dict matching SCENE_SCHEMA."""
    # Index each pass by panel_index
    p1_panels = {p['panel_index']: p for p in p1_scene.get('panels', [])}
    p1a_panels = {p['panel_index']: p for p in (p1a_result or {}).get('panels', [])}
    p1b_panels = {p['panel_index']: p for p in (p1b_result or {}).get('panels', [])}
    p2_panels = {p['panel_index']: p for p in p2_result.get('panels', [])}
    p3_panels = {p['panel_index']: p for p in p3_result.get('panels', [])}

    all_indices = sorted(
        set(p1_panels) | set(p2_panels) | set(p3_panels)
    )
    merged_panels = []
    for idx in all_indices:
        panel = {}
        # Apply in order: p1 (skeleton) → p1a (state) → p2 (visual) → p3 (motion/audio)
        # Later passes win on overlap (e.g. p3 may refine hook_type from p1)
        panel.update(p1_panels.get(idx, {}))
        panel.update(p1a_panels.get(idx, {}))
        panel.update(p2_panels.get(idx, {}))
        panel.update(p3_panels.get(idx, {}))
        # Pass 1B is authoritative for camera placement and spatial disposition —
        # override whatever Pass 2 computed for these fields.
        if idx in p1b_panels:
            p1b = p1b_panels[idx]
            for key in ('camera_position', 'camera_x', 'camera_y', 'camera_z',
                        'location_references', 'visual_disposition'):
                if p1b.get(key) is not None:
                    panel[key] = p1b[key]
        # Ensure required SCENE_SCHEMA defaults
        panel.setdefault('motion_prompt_reversed', '')
        panel.setdefault('caption', '')
        panel.setdefault('references', [])
        panel.setdefault('location_references', [])
        panel.setdefault('panel_type', 'narrative')
        panel.setdefault('voiceover_settings', {})
        panel.setdefault('voiceover_timing', '')
        panel.setdefault('visual_disposition', '')
        panel.setdefault('anchor_refs', [])
        merged_panels.append(panel)

    merged: dict = {
        'scene_id': scene_spec.get('scene_local_id', 1),
        'location': scene_spec.get('location', ''),
        'pre_action_description': scene_spec.get('scene_instructions', '')[:200],
        'camera_master': p2_result.get('camera_master', ''),
        'lighting_master': p2_result.get('lighting_master', ''),
        'scene_trajectories': p1_scene.get('scene_trajectories', []),
        'panels': merged_panels,
    }
    bg = scene_spec.get('background_activity')
    if bg and bg.get('density') != 'none':
        merged['background_activity'] = bg
    return merged
