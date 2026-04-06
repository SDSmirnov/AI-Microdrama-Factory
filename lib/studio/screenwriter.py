"""
Screenwriter — screenplay and scene keyframe generation.

Prompts are loaded from lib/prompting/<style>/ via load_prompts().
"""
import copy
import json
import logging
import os
import tempfile
from pathlib import Path


from lib.core import puppet as _puppet
from lib.core.prompts import TARGET_LANGUAGE
from lib.core.schemas import (
    SCREENPLAY_SCHEMA, SCENE_SCHEMA, REVERSAL_SCHEMA, SPATIAL_DISPOSITION_SCHEMA,
    SPATIAL_REWRITE_SCHEMA,
    PASS1_SCHEMA, PASS1A_SCHEMA, PASS1B_SCHEMA, PASS2_SCHEMA, PASS3_SCHEMA,
)
from lib.core.state import ProjectState
from lib.core.utils import DEFAULT_OUTPUT_DIR, PANEL_COUNT_OPTIONS
from lib.llm.base import BaseLLM, retry_on_errors

logger = logging.getLogger(__name__)

_ARC_TYPES = {'arc_open', 'arc_mid', 'arc_close'}


# ---------------------------------------------------------------------------
# Duel mode instruction builder
# ---------------------------------------------------------------------------
def _build_duel_instruction(duel_cfg: dict, prompts: dict, episodes_count: int) -> str:
    """Build the __DUEL_INSTRUCTION__ block injected into screenplay_episodes prompt."""
    char_a = duel_cfg.get('character_a', 'Character A')
    char_b = duel_cfg.get('character_b', 'Character B')

    if episodes_count == 2:
        arc_map = (
            "### DUEL ARC — 2-EPISODE STRUCTURE\n\n"
            "```\n"
            "arc_open  (Ep1, P1–PN): cold_open[A+B] → first_demand[A] → first_counter[B] →\n"
            "                         escalation[A] → emotional_capture[B] → rising_action[A] →\n"
            "                         pivot → near_collapse[B] → arc_bridge[A+B]\n"
            "arc_close (Ep2, P1–PN): arc_pickup[A+B] → pressure_exchange[A] → decisive_blow[B] →\n"
            "                         impact[A] → pivot → twist → cost[A+B] →\n"
            "                         consequence[A+B] → cliffhanger[A+B: ambiguous]\n"
            "```\n"
        )
    elif episodes_count == 4:
        arc_map = (
            "### DUEL ARC — 4-EPISODE STRUCTURE\n\n"
            "```\n"
            "arc_open  (Ep1, P1–PN): cold_open[A+B] → first_demand[A] → first_counter[B] →\n"
            "                         escalation[A] → emotional_capture[B] → rising_action[A] →\n"
            "                         pivot → near_collapse[B] → arc_bridge[A+B]\n"
            "arc_mid   (Ep2, P1–PN): arc_pickup[A+B] → pressure_exchange → complication →\n"
            "                         rising_pressure[B] → pivot → new_weapon[A] →\n"
            "                         counter_offensive[B] → pre_collapse[A] → arc_bridge[A+B]\n"
            "arc_mid   (Ep3, P1–PN): arc_pickup[A+B] → deepening_complication → revelation[B] →\n"
            "                         escalating_cost[A] → pivot → point_of_no_return[A] →\n"
            "                         final_gambit[B] → convergence[A+B] → arc_bridge[A+B]\n"
            "arc_close (Ep4, P1–PN): arc_pickup[A+B] → collapse_point → reversal →\n"
            "                         aftermath → pivot → twist → cost[A+B] →\n"
            "                         consequence[A+B] → cliffhanger[A+B: ambiguous]\n"
            "```\n"
        )
    elif episodes_count == 5:
        arc_map = (
            "### DUEL ARC — 5-EPISODE STRUCTURE\n\n"
            "```\n"
            "arc_open  (Ep1, P1–PN): cold_open[A+B] → first_demand[A] → first_counter[B] →\n"
            "                         escalation[A] → emotional_capture[B] → rising_action[A] →\n"
            "                         pivot → near_collapse[B] → arc_bridge[A+B]\n"
            "arc_mid   (Ep2, P1–PN): arc_pickup[A+B] → pressure_exchange → complication →\n"
            "                         rising_pressure[B] → pivot → new_weapon[A] →\n"
            "                         counter_offensive[B] → pre_collapse[A] → arc_bridge[A+B]\n"
            "arc_mid   (Ep3, P1–PN): arc_pickup[A+B] → deepening_complication → revelation[B] →\n"
            "                         escalating_cost[A] → pivot → point_of_no_return[A] →\n"
            "                         final_gambit[B] → convergence[A+B] → arc_bridge[A+B]\n"
            "arc_mid   (Ep4, P1–PN): arc_pickup[A+B] → last_chance[A] → ultimatum[B] →\n"
            "                         desperation_move[A] → pivot → cost_revealed[A+B] →\n"
            "                         forced_choice[B] → threshold_crossed[A] → arc_bridge[A+B]\n"
            "arc_close (Ep5, P1–PN): arc_pickup[A+B] → collapse_point → reversal →\n"
            "                         aftermath → pivot → twist → cost[A+B] →\n"
            "                         consequence[A+B] → cliffhanger[A+B: ambiguous]\n"
            "```\n"
        )
    else:
        arc_map = (
            "### DUEL ARC — 3-EPISODE STRUCTURE\n\n"
            "```\n"
            "arc_open  (Ep1, P1–PN): cold_open[A+B] → first_demand[A] → first_counter[B] →\n"
            "                         escalation[A] → emotional_capture[B] → rising_action[A] →\n"
            "                         pivot → near_collapse[B] → arc_bridge[A+B]\n"
            "arc_mid   (Ep2, P1–PN): arc_pickup[A+B] → pressure_exchange → complication →\n"
            "                         rising_pressure[B] → pivot → new_weapon[A] →\n"
            "                         counter_offensive[B] → pre_collapse[A] → arc_bridge[A+B]\n"
            "arc_close (Ep3, P1–PN): arc_pickup[A+B] → collapse_point → reversal →\n"
            "                         aftermath → pivot → twist → cost[A+B] →\n"
            "                         consequence[A+B] → cliffhanger[A+B: ambiguous]\n"
            "```\n"
        )

    duel_block = (prompts.get('episode_type_duel', '')
                  .replace('__CHAR_A__', char_a)
                  .replace('__CHAR_B__', char_b))
    return f"## DUEL MODE — {char_a.upper()} vs {char_b.upper()}\n\n{arc_map}\n{duel_block}"


# ---------------------------------------------------------------------------
# Ref helpers (used by both screenplay and 4-pass scene generation)
# ---------------------------------------------------------------------------

def _get_location_anchors(character_info: dict) -> dict:
    """Extract anchor_points from all room/vehicle/outdoor refs that have them.

    Returns {ref_name: anchor_points_dict}. Prefers canonical views
    (View-From-Entrance, View-Primary, Exterior, Interior-From-Entrance) to avoid
    duplicate anchor sets; falls back to any typed ref with anchor_points.
    """
    canonical_suffixes = ('-View-From-Entrance', '-View-Primary', '-Exterior', '-Interior-From-Entrance')
    result: dict = {}
    fallback: dict = {}
    for name, info in (character_info or {}).items():
        if info.get('type') in ('Room', 'Vehicle', 'Outdoor') and info.get('anchor_points'):
            if any(name.endswith(s) for s in canonical_suffixes):
                result[name] = info['anchor_points']
            else:
                fallback[name] = info['anchor_points']
    return result or fallback


# ---------------------------------------------------------------------------
# Episode-level screenplay — verbatim from 01_cinematic_preroll.py:529-592
# ---------------------------------------------------------------------------
def analyze_episodes_master(text: str, prompts: dict, config: dict, llm: BaseLLM, character_info: dict = None) -> dict:
    logger.info("\n🎥 MASTER SCREENWRITER: Preparing screenplay...")
    setting_context = prompts.get('setting', '')
    transitions_cfg = config.get('transitions', {})
    transitions_enabled = transitions_cfg.get('enabled', True)
    gap_threshold = transitions_cfg.get('gap_threshold', '4h')
    transition_style = transitions_cfg.get('style', 'visual_rhyme')
    panel_count_options = config['format'].get('panel_count_options', PANEL_COUNT_OPTIONS)

    transitions_instruction = (
        f'7. TRANSITION EPISODES (episode_type: "transition"): When a significant time gap (>{gap_threshold}) exists between chapters, insert one Transition episode BEFORE the next episode. Transitions bridge the gap using {transition_style} technique — parallel environmental shots from each character\'s space during the time gap (e.g. both characters\' environments at dawn, rain on two different windows). Rules: no dialogue, no voiceover, no character close-ups, panel_type "narrative", panel durations 2–3s. pov_character: "". Transition episodes use 4–6 panels (brief atmospheric bridge).'
        if transitions_enabled else
        '7. Do not generate transition episodes.'
    )

    multi_pov_instruction = (
        '6. EPISODE STRUCTURE: Each narrative chapter produces one episode covering its full events in chronological order. '
        'Set episode_type: "standard" and pov_character: "" for all episodes.'
    )
    schema = copy.deepcopy(SCREENPLAY_SCHEMA)
    ep_required = schema['properties']['episodes']['items']['required']
    for field in ('chapter_id', 'episode_type', 'pov_character'):
        if field in ep_required:
            ep_required.remove(field)

    episodes_rules = prompts.get('screenplay_episodes', '')
    episodes_rules = episodes_rules.replace('__MULTI_POV_INSTRUCTION__', multi_pov_instruction)
    episodes_rules = episodes_rules.replace('__TRANSITIONS_INSTRUCTION__', transitions_instruction)
    episodes_count = config.get('episodes_count', 2)
    min_panels = episodes_count * min(panel_count_options)
    max_panels = episodes_count * max(panel_count_options)
    arc_duration = f'~{min_panels * 3}s–{max_panels * 3}s'
    duel_cfg = config.get('duel', {})
    duel_instruction = _build_duel_instruction(duel_cfg, prompts, episodes_count) if duel_cfg.get('enabled') else ''
    episodes_rules = (
        episodes_rules
        .replace('__EPISODES_COUNT__', str(episodes_count))
        .replace('__PANEL_COUNT_OPTIONS__', str(panel_count_options))
        .replace('__ARC_DURATION__', arc_duration)
        .replace('__DUEL_INSTRUCTION__', duel_instruction)
    )
    char_refs_block = ""
    anchors_block = ""
    if character_info:
        lines = []
        for name, info in character_info.items():
            desc = info.get('visual_desc') or info.get('video_visual_desc', '')
            if desc:
                lines.append(f"- {name}: {desc}")
            else:
                lines.append(f"- {name}")
        char_refs_block = (
            "CHARACTER/LOCATION REFERENCES — for screenplay planning and visual_continuity_rules only "
            "(use exact descriptions to prevent hallucination). Panel visual_start/visual_end must describe "
            "only scene-specific deviations, not repeat these baselines:\n" + "\n".join(lines)
        )
        location_anchors = _get_location_anchors(character_info)
        if location_anchors:
            anchors_block = (
                "LOCATION ANCHOR POINTS — authoritative room geometry.\n"
                "Use ONLY these named landmarks when writing scene_instructions and initial_disposition.\n"
                "FORBIDDEN: compass directions not derived from these axes, invented doorway/wall names.\n"
                + json.dumps(location_anchors, ensure_ascii=False, indent=2)
            )

    prompt = (
        f"{episodes_rules}\n\n{setting_context}\n\n"
        + (f"{char_refs_block}\n\n" if char_refs_block else "")
        + (f"{anchors_block}\n\n" if anchors_block else "")
        + f"Respond in specified JSON format.\n\nTEXT TO ADAPT:\n<STORY>{text}</STORY>"
    )
    return llm.make_json(prompt, schema)


# ---------------------------------------------------------------------------
# Episode-type-specific prompt block
# ---------------------------------------------------------------------------
def _episode_type_block(episode_type: str, pov_character: str, prompts: dict, config: dict) -> str:
    """Return episode-type-specific cinematic constraints loaded from prompts."""
    if episode_type == 'pov':
        return prompts.get('episode_type_pov', '')
    if episode_type == 'transition':
        panel_duration = str(config['format'].get('panel_duration_s', 6))
        tmpl = prompts.get('episode_type_transition', '')
        return tmpl.replace('{{PANEL_DURATION}}', panel_duration)
    if episode_type in ('arc_open', 'arc_mid', 'arc_close'):
        block = prompts.get(f'episode_type_{episode_type}', '')
        duel_cfg = config.get('duel', {})
        if duel_cfg.get('enabled'):
            duel_block = (prompts.get('episode_type_duel', '')
                          .replace('__CHAR_A__', duel_cfg.get('character_a', 'Character A'))
                          .replace('__CHAR_B__', duel_cfg.get('character_b', 'Character B')))
            block = f'{block}\n\n{duel_block}'
        return block
    return ''


# ---------------------------------------------------------------------------
# 4-Pass scene generation
# ---------------------------------------------------------------------------

def _episode_narrative_block(episode_context: dict | None) -> str:
    """Build a concise narrative context block from episode_context for injection into passes 1A–3."""
    if not episode_context:
        return ""
    parts = []
    cn = episode_context.get('rewritten_condensed_narrative', '')
    if cn:
        parts.append(f"CONDENSED NARRATIVE (verbatim dialogue + action coverage contract):\n{cn}")
    meta = []
    pov = episode_context.get('pov_character', '')
    daytime = episode_context.get('daytime', '')
    if pov:
        meta.append(f"POV_CHARACTER: {pov}")
    if daytime:
        meta.append(f"DAYTIME: {daytime}")
    if meta:
        parts.insert(0, " | ".join(meta))
    return "\n\n".join(parts)


def _extract_episode_exit(scenes_data: dict) -> dict | None:
    """
    Extract exit context from the last panel of the last scene of an episode data dict.
    Returns {'visual_end': str, 'state': dict | None} or None if no panels found.
    visual_end → injected into Pass 1 (visual continuity anchor).
    state      → injected into Pass 1A (structural state bootstrap: actor positions, poses, props).
    """
    scenes = scenes_data.get('scenes', [])
    if not scenes:
        return None
    last_panel = max(
        scenes[-1].get('panels', []),
        key=lambda p: p.get('panel_index', 0),
        default=None,
    )
    if not last_panel:
        return None
    return {
        'visual_end': last_panel.get('visual_end', ''),
        'state': last_panel.get('state') or None,
    }


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
        f"\nPREVIOUS EPISODE EXIT STATE (last frame the viewer saw — first panel MUST visually follow from this):\n{visual_end}\n"
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
    @retry_on_errors(max_retries=3, backoff_factor=2)
    def _call():
        return llm.make_json(prompt, PASS1_SCHEMA)

    result = _call()
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
        "PREVIOUS EPISODE EXIT STATE — actors/props/disposition at the last frame of the prior episode.\n"
        "Panel 1 state chain MUST begin from this baseline (carry positions, poses, props forward unless the scene explicitly changes them):\n"
        + json.dumps(prev_state, ensure_ascii=False, indent=2)
        if prev_state else ""
    )

    prompt = f"""{rules}

{char_block}

{anchors_block}

{narrative_block}

{prev_state_block}

SCENE: {scene_spec.get('location', '')}
PANEL COUNT: {panel_count} panels — produce EXACTLY {panel_count} panel state entries.

INITIAL DISPOSITION (scene open — map any legacy positional terms to ROOM ANCHOR POINTS above; use only image-relative [0,1] coordinates):
{initial_disposition if initial_disposition else "(not specified — infer from scene instructions)"}

SCENE TRAJECTORIES (from Pass 1):
{trajectories_json}

PANEL SKELETONS (motion_intent per panel, from Pass 1):
{skeletons_json}

SCENE INSTRUCTIONS:
{scene_spec.get('scene_instructions', '')}
"""
    @retry_on_errors(max_retries=3, backoff_factor=2)
    def _call():
        return llm.make_json(prompt, PASS1A_SCHEMA)

    result = _call()
    if not result or not result.get('panels'):
        logger.warning(f"  ⚠️  Pass 1A returned empty for scene {scene_id} — continuing without state")
        return None
    return result


def _pass1b_disposition(
    scene_spec: dict,
    p1_scene: dict,
    p1a_result: dict | None,
    prompts: dict,
    llm: BaseLLM,
    location_anchors: dict,
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

    # Build reversed-slug list so the prompt knows which counterpart slugs are valid
    _reversed_slug_map = {
        '-View-From-Entrance': '-View-To-Entrance',
        '-View-From-Left-Wall': '-View-From-Right-Wall',
        '-View-Center-To-Far': '-View-Center-To-Entrance',
        '-View-By-Far-Wall': '-View-By-Entrance',
        '-View-Primary': '-View-Opposite',
        '-Exterior': None,
        '-Interior-From-Entrance': '-Interior-To-Entrance',
    }
    reversed_slugs: list[str] = []
    for key in location_anchors:
        for suffix, rev in _reversed_slug_map.items():
            if rev and key.endswith(suffix):
                reversed_slugs.append(key[: -len(suffix)] + rev)
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
"""

    @retry_on_errors(max_retries=3, backoff_factor=2)
    def _call():
        return llm.make_json(prompt, PASS1B_SCHEMA)

    result = _call()
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
        # Derive reversed-axis ref slug names so they appear alongside the anchor data
        # Maps canonical (anchor-keyed) view suffixes → their opposite-direction counterparts.
        # Only canonical views appear as anchor keys; their counterparts are derived on demand.
        _reversed_slug_map = {
            '-View-From-Entrance': '-View-To-Entrance',
            '-View-From-Left-Wall': '-View-From-Right-Wall',
            '-View-Center-To-Far': '-View-Center-To-Entrance',
            '-View-By-Far-Wall': '-View-By-Entrance',
            '-View-Primary': '-View-Opposite',
            '-Exterior': None,
            '-Interior-From-Entrance': '-Interior-To-Entrance',
        }
        _reversed_slugs: list[str] = []
        for _key in location_anchors:
            for _suffix, _rev in _reversed_slug_map.items():
                if _rev and _key.endswith(_suffix):
                    _reversed_slugs.append(_key[: -len(_suffix)] + _rev)
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
        "BACKGROUND ACTIVITY — scene-level background life "
        "(inject as BGD: line at MS/MWS/WS/XWS scale; skip at CU/ECU/Macro):\n"
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
        'View-From-Left-Wall':     'Left-wall (y drives lateral: y<0.35→frame-left, y>0.65→frame-right; depth: low-X=FG)',
        'View-From-Right-Wall':    'Right-wall (1-y drives lateral: y>0.65→frame-left, y<0.35→frame-right; depth: high-X=FG)',
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
    }

    def _axis_for_panel(refs: list[str]) -> str:
        for ref in refs:
            for suffix, axis in _VIEW_TO_AXIS.items():
                if ref.endswith(suffix):
                    return axis
        return 'Entrance (default)'

    def _direction_for_panel(refs: list[str]) -> str:
        for ref in refs:
            for suffix, direction in _VIEW_TO_DIRECTION.items():
                if ref.endswith(suffix):
                    return direction
        return 'toward far wall (default)'

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
"""
    @retry_on_errors(max_retries=3, backoff_factor=2)
    def _call():
        return llm.make_json(prompt, PASS2_SCHEMA)

    result = _call()
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
        "BACKGROUND ACTIVITY — append AMBIENT: note per AMBIENT BACKGROUND MOTION rules:\n"
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
"""
    @retry_on_errors(max_retries=3, backoff_factor=2)
    def _call():
        return llm.make_json(prompt, PASS3_SCHEMA)

    result = _call()
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


def generate_scene_4pass(
    scene_spec: dict,
    episode_context: dict,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    character_info: dict,
    continuity_block: str,
    episode_type_block: str,
    prev_episode_exit: dict = None,
) -> dict | None:
    """
    Orchestrate 4-pass scene generation.
    Falls back to None on failure (caller should use legacy single-call path).
    prev_episode_exit: {'visual_end': str, 'state': dict|None} from last panel of previous episode.
      visual_end → Pass 1 (visual continuity anchor for first scene).
      state      → Pass 1A (structural state bootstrap: actor positions, poses, props).
    Both are injected only for scene_local_id == 1.
    """
    scene_id = scene_spec.get('scene_local_id', 1)
    logger.info(f"    🎬 4-pass generation: scene {scene_id}")

    location_anchors = _get_location_anchors(character_info)
    if location_anchors:
        logger.debug(f"      📐 Anchors loaded: {list(location_anchors.keys())}")
    else:
        logger.warning(f"      ⚠️  No room anchor_points found — spatial positions may be inaccurate. Run room-anchors first.")

    # Cross-episode exit only relevant for the first scene of an episode
    exit_for_scene1 = prev_episode_exit if scene_id == 1 else None
    p1 = _pass1_architecture(
        scene_spec, episode_context, prompts, config, llm,
        continuity_block, episode_type_block,
        prev_episode_exit=exit_for_scene1,
    )
    if not p1:
        return None
    logger.info(f"      ✅ Pass 1 done ({len(p1.get('panels', []))} panel stubs)")

    p1a = _pass1a_state(scene_spec, p1, prompts, config, llm, character_info, location_anchors,
                        episode_context=episode_context, prev_episode_exit=exit_for_scene1)
    if p1a:
        logger.info(f"      ✅ Pass 1A done ({len(p1a.get('panels', []))} states)")
    else:
        logger.warning(f"      ⚠️  Pass 1A skipped — proceeding without state")

    p1b = _pass1b_disposition(scene_spec, p1, p1a, prompts, llm, location_anchors)
    if p1b:
        logger.info(f"      ✅ Pass 1B done ({len(p1b.get('panels', []))} camera/disposition entries)")
    else:
        logger.debug(f"      ⏭  Pass 1B skipped (no anchors or prompt) — Pass 2 will self-compute camera")

    # Substitute active variation refs for base character refs in Pass 2 char block
    effective_char_info = _resolve_effective_char_info(character_info, p1a)

    p2 = _pass2_visual(scene_spec, p1, p1a, prompts, config, llm, effective_char_info, location_anchors,
                       episode_context=episode_context, p1b_result=p1b)
    if not p2:
        return None
    logger.info(f"      ✅ Pass 2 done ({len(p2.get('panels', []))} visuals)")

    p3 = _pass3_motion_audio(scene_spec, p1, p1a, p2, prompts, config, llm,
                              episode_context=episode_context)
    if not p3:
        return None
    logger.info(f"      ✅ Pass 3 done ({len(p3.get('panels', []))} motion/audio entries)")

    merged = _merge_scene_passes(scene_spec, p1, p1a, p2, p3, p1b_result=p1b)
    logger.info(f"      ✅ Merged: {len(merged.get('panels', []))} panels")
    return merged


# ---------------------------------------------------------------------------
# Scene keyframe generation
# ---------------------------------------------------------------------------
def analyze_scenes_for_episode(
    episode_counter: int,
    text: str,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    all_episodes: list,
    character_info: dict = None,
    prev_continuity_rules: str = None,
    prev_active_questions: dict = None,
    prev_episode_exit: dict = None,
):
    logger.info(f"\n🎥 MASTER CINEMATOGRAPHER: Preparing Keyframes for episode {episode_counter}...")

    # Extract episode metadata
    try:
        episode_data = json.loads(text)
        current_continuity = episode_data.get('visual_continuity_rules', '')
        episode_type = episode_data.get('episode_type', '')
        pov_character = episode_data.get('pov_character', '')
    except (json.JSONDecodeError, AttributeError):
        episode_data = {}
        current_continuity = ''
        episode_type = ''
        pov_character = ''

    continuity_block = ""
    if prev_continuity_rules:
        continuity_block += (
            f"\n## VISUAL CONTINUITY FROM PREVIOUS EPISODE — MANDATORY\n"
            f"These rules MUST be enforced in every panel of this episode:\n{prev_continuity_rules}\n"
        )
    if current_continuity:
        continuity_block += (
            f"\n## THIS EPISODE'S VISUAL STATE (carry forward to future scenes)\n{current_continuity}\n"
        )
    active_questions = episode_data.get('active_questions', {})
    if active_questions:
        q_lines = []
        for key, label in [('macro', 'MACRO'), ('episode', 'EPISODE'), ('scene', 'SCENE')]:
            val = active_questions.get(key, '')
            if val:
                q_lines.append(f"  {label}: {val}")
        planted = active_questions.get('planted_this_episode', '')
        if planted:
            q_lines.append(f"  PLANTED (pay off within 3 episodes): {planted}")
        if q_lines:
            continuity_block += (
                f"\n## ACTIVE DRAMATIC QUESTIONS — keep these alive in panels\n"
                f"Do NOT resolve the MACRO question. SCENE question should be visible through action/reaction:\n"
                + "\n".join(q_lines) + "\n"
            )
    if prev_active_questions:
        prev_planted = prev_active_questions.get('planted_this_episode', '')
        if prev_planted:
            continuity_block += (
                f"\n## PREVIOUSLY PLANTED QUESTIONS — must remain visibly alive or pay off this episode\n"
                f"  {prev_planted}\n"
            )

    episode_type_block = _episode_type_block(episode_type, pov_character, prompts, config)

    # Resolve scenes_spec: new format has scenes[], old format has screenplay_instructions
    scenes_spec = episode_data.get('scenes', [])
    if not scenes_spec:
        # Compat shim: old-format episode without scenes[] — synthesize a single scene
        panel_count_options = config['format'].get('panel_count_options', PANEL_COUNT_OPTIONS)
        default_count = 9 if 9 in panel_count_options else panel_count_options[-1]
        scenes_spec = [{
            'scene_local_id': 1,
            'location': episode_data.get('location', ''),
            'panel_count': default_count,
            'scene_instructions': episode_data.get('screenplay_instructions', ''),
        }]
        logger.debug(f"  Episode {episode_counter}: no scenes[] found — using compat single-scene ({default_count} panels)")

    # Strip keys that go into scene-level context to avoid confusion
    episode_context = {
        k: v for k, v in episode_data.items()
        if k not in ('scenes', 'screenplay_instructions')
    }

    all_raw_scenes = []
    for scene_spec in scenes_spec:
        scene_id = scene_spec.get('scene_local_id', 1)
        # Pass cross-episode exit only to the first scene; within-episode scenes don't need it
        exit_ctx = prev_episode_exit if scene_id == 1 else None
        scene = generate_scene_4pass(
            scene_spec=scene_spec,
            episode_context=episode_context,
            prompts=prompts,
            config=config,
            llm=llm,
            character_info=character_info,
            continuity_block=continuity_block,
            episode_type_block=episode_type_block,
            prev_episode_exit=exit_ctx,
        )
        if scene:
            scene['episode_id'] = episode_counter
            all_raw_scenes.append(scene)
        else:
            logger.error(f"❌ 4-pass failed for episode {episode_counter}, scene {scene_id} — skipping")

    all_episodes.append((episode_counter, {'scenes': all_raw_scenes}))
    logger.info(f"CINEMATOGRAPHER: Ready Keyframes for episode {episode_counter}")


# ---------------------------------------------------------------------------
# Reversal pass
# ---------------------------------------------------------------------------
def apply_reversal_pass(scene: dict, prompts: dict, config: dict, llm: BaseLLM) -> dict:
    reversed_panels = [p for p in scene.get('panels', []) if p.get('is_reversed', False)]
    if not reversed_panels:
        return scene

    logger.info(f"    🔄 Reversal pass: {len(reversed_panels)} panel(s) flagged in scene {scene.get('scene_id', '?')}")

    setting_context = prompts.get('setting', '')
    panels_context = json.dumps(reversed_panels, ensure_ascii=False, indent=2)
    scene_trajectories = scene.get('scene_trajectories', [])
    trajectories_context = (
        f"\nSCENE TRAJECTORIES (emotional arcs — use to ensure visual_start_explicit matches "
        f"the declared emotional state at the reversal panel):\n"
        f"{json.dumps(scene_trajectories, ensure_ascii=False, indent=2)}\n"
    ) if scene_trajectories else ""
    duration = config['format'].get('panel_duration_s', 6)
    hold_s   = 0.4  # hold at both ends of forward clip for clean retrograde head/tail
    prompt = f"""
You are a Master Cinematographer choreographing RETROGRADE MOTION clips for AI video generation.

RETROGRADE MOTION: the AI renders a forward clip; the clip is inverted frame-by-frame in post
so the viewer perceives time running backwards. Every physical choice you make must be designed
to produce a specific perceptual result when played in retrograde.

  - visual_start = what the viewer sees at t=0 after retrograde inversion (the hidden / before-state)
  - visual_end   = what the viewer sees at the end after retrograde inversion (the revealed / after-state)

You must generate TWO things per panel:

1. motion_prompt_reversed — describes the FORWARD clip the AI will render.
   The forward clip runs from visual_end state → visual_start state.
   In retrograde playback the viewer perceives visual_start → visual_end.

2. visual_start_explicit — a fully explicit rewrite of visual_end (which becomes the first
   frame visible to the viewer after retrograde inversion). Required because the original
   visual_end may be vague or lack technical camera details.
   Must include: shot type (ECU/CU/MS/MLS/LS), camera angle, character position in frame,
   key props, lighting state. Zero implicit references.

━━━ RETROGRADE MOTION DESIGN PRINCIPLES ━━━

Hold frames (mandatory):
  Begin the forward clip with a {hold_s}s STATIC HOLD at visual_end state — frozen, no motion.
  End  the forward clip with a {hold_s}s STATIC HOLD at visual_start state — frozen, no motion.
  These become clean head/tail in retrograde and prevent jarring cuts.

Choose retrograde-effective action types:
  ENTRY  (retrograde reveals): forward clip = character walks AWAY from camera to distance / exits
         through door → retrograde shows smooth approach / entry. Best for character arrivals.
  RISE   (retrograde reveals): forward clip = character sits DOWN into chair → retrograde = rising.
  DRAW   (retrograde reveals): forward clip = weapon/object returned to holster/pocket → retrograde = draw.
  ASSEMBLE (retrograde reveals): forward clip = object breaks apart / liquid spills →
         retrograde = assembly / pour. Exploits retrograde physics (particles, liquids).
  CONCEAL (retrograde reveals): forward clip = cloth draped over object, lights dimmed →
         retrograde = cloth lifts, lights come up.
  CLOSE  (retrograde reveals): forward clip = door/curtain swings SHUT → retrograde = it opens.

Retrograde physics — design for them explicitly:
  Fabric:   settling drape / fabric dropping onto surface → retrograde: fabric lifts and billows.
  Liquid:   pour into container → retrograde: liquid rises out. Use slow, controlled pours.
  Smoke/breath: exhale cloud expanding → retrograde: cloud contracts back to lips.
  Gravity:  object placed on table with slight bounce → retrograde: object lifts off.
  Hair:     hair falls forward over face → retrograde: hair sweeps back dramatically.

Body mechanics (mandatory precision):
  - Name the exact limb at every beat: "reaches with RIGHT hand", "steps with LEFT foot"
  - State face direction every beat: "facing camera", "3/4 profile left", "back to camera"
  - Sequence every movement beat explicitly: weight shift → reach → grip → step → pivot
  - Full travel for entries/exits: from full-frame presence to partial frame edge (or vice versa)
  - Velocity gradient: start at low speed, hold steady — abrupt starts/stops destroy retrograde illusion

Forbidden patterns (break retrograde illusion):
  ✗ Blinking or eye movements (asymmetric in retrograde)
  ✗ Talking / mouth movement (speech retrograde reads as alien)
  ✗ Multiple simultaneous moving elements (chaos — pick one primary motion)
  ✗ Rapid cuts or camera moves (must be continuous, locked or single slow push/pull)
  ✗ Ambient crowd motion in background (people retrograde looks absurd)

━━━ EXAMPLE ━━━

  visual_start: "Closed office door, empty hallway."
  visual_end:   "Secretary inside room, door open, colleagues laughing in background."

  → motion_prompt_reversed (forward: inside → outside, retrograde-designed):
    "RETROGRADE ENTRY. MS locked camera from room corner, warm overhead light.
    0s–0.4s: HOLD — Secretary stands center-frame just inside doorway, coat fully settled,
    right hand at side, colleagues blurred mid-laugh over her right shoulder. Static freeze.
    0.4s: She turns head LEFT toward door, shifts weight onto LEFT foot — slow, deliberate.
    1.2s: Reaches forward with RIGHT hand, index finger extended, grips door handle.
    2s: Steps backward across threshold with RIGHT foot — torso crosses doorframe centerline.
    2.8s: LEFT foot follows; she is now fully in hallway, face turned INTO the room,
    left hand trailing on door edge.
    3.8s: She pulls door steadily CLOSED — door swings toward camera in smooth arc.
    5.2s: Door clicks shut; hallway empty, closed door fills frame.
    5.2s–5.6s: HOLD — closed door, empty hallway, no motion. Static freeze."

  → visual_start_explicit:
    "MS locked shot from room corner — Secretary center-frame just inside doorway, coat
    fully settled, right hand at side, colleagues soft-focus over her right shoulder,
    warm office overhead lighting, door fully open to left of frame."

━━━ RULES ━━━
- motion_prompt_reversed: 120+ words, explicit timestamps, all verbs forward-plausible
- Label clip type at the top: "RETROGRADE ENTRY", "RETROGRADE RISE", "RETROGRADE DRAW", etc.
- Do NOT invent visual elements beyond the two provided states
- Preserve all lighting and camera details from lights_and_camera
- Duration: {duration}s total (including {hold_s}s holds at each end)

{setting_context}
{trajectories_context}
PANELS TO PROCESS:
{panels_context}
"""

    @retry_on_errors(max_retries=3, backoff_factor=2)
    def _call_api():
        return llm.make_json(prompt, REVERSAL_SCHEMA)

    result = _call_api()

    if result:
        # result may be a list (schema is array) or dict with list
        items = result if isinstance(result, list) else result.get('items', [])
        reversed_map = {item['panel_index']: item for item in items}
        for p in scene.get('panels', []):
            if p.get('is_reversed', False) and p['panel_index'] in reversed_map:
                item = reversed_map[p['panel_index']]
                p['motion_prompt_original'] = p['motion_prompt']
                p['motion_prompt'] = item['motion_prompt_reversed']
                original_start = p['visual_start']
                original_end   = p['visual_end']
                p['visual_start'] = item.get('visual_start_explicit') or original_end
                p['visual_end']   = original_start
                logger.info(f"      ✅ Panel {p['panel_index']}: motion_prompt_reversed generated")
            elif p.get('is_reversed', False):
                logger.info(f"      ⚠️  Panel {p['panel_index']}: no motion_prompt_reversed returned by LLM")
    else:
        logger.error(f"      ❌ Reversal LLM call returned empty for scene {scene.get('scene_id', '?')}")

    return scene


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
}


_LATERAL_SUFFIXES = ('-View-From-Left-Wall', '-View-From-Right-Wall')


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

    panels_context = [
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

    prompt = f"""You are a spatial continuity supervisor for an AI-generated vertical drama series.

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
CRITICAL — USE ONLY PHYSICAL LANDMARKS. NEVER use "screen-left", "screen-right", "frame-left", "frame-right".
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

When all actors share the same classification: "all actors [class] (x≈N)" or "(y≈N)".

SCENE PANELS:
{json.dumps(panels_context, ensure_ascii=False, indent=2)}

Return a JSON array: [{{"panel_index": N, "visual_disposition": "...", "swap_view": false, "swap_view_reason": "..."}}, ...]
Set swap_view=true only for panels where the view must be flipped (see VIEW VALIDATION above).
swap_view_reason is required for every panel. """

    @retry_on_errors(max_retries=3, backoff_factor=2)
    def _call_api():
        return llm.make_json(prompt, SPATIAL_DISPOSITION_SCHEMA)

    result = _call_api()
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
        if idx in swap_set:
            old_refs = p.get('location_references', [])
            new_refs = [_swap_view_ref(r) for r in old_refs]
            if new_refs == old_refs:
                continue
            if available_refs:
                # Only flag refs that actually changed (have a known view suffix) and are absent.
                missing = [r for r, o in zip(new_refs, old_refs) if r != o and r not in available_refs]
                if missing:
                    logger.warning(
                        f"      ⚠️  Panel {idx}: swap_view=true but target ref(s) not found "
                        f"— skipping swap. Missing: {missing}"
                    )
                    continue
            p['location_references'] = new_refs
            # Mirror screen-direction terms in all camera-relative text fields.
            # These were written assuming the old view axis; with the axis flipped,
            # frame-left becomes frame-right and vice versa.
            mirrored_fields = []
            for field in ('visual_start', 'visual_end', 'motion_prompt', 'visual_start_explicit'):
                if p.get(field):
                    original = p[field]
                    p[field] = _mirror_screen_directions(original)
                    if p[field] != original:
                        mirrored_fields.append(field)
            swapped += 1
            reason = swap_reasons.get(idx, '')
            mirror_note = f", mirrored: {mirrored_fields}" if mirrored_fields else ""
            logger.info(f"      🔄 Panel {idx}: view swapped {old_refs} → {new_refs}"
                        + (f" [{reason}]" if reason else "") + mirror_note)

    logger.info(
        f"      ✅ Spatial disposition: {updated}/{len(panels)} panels for scene {scene_id}"
        + (f", {swapped} view(s) corrected" if swapped else "")
    )

    # --- Puppet post-processing (Option A: deterministic rewrite) ---
    # Guard: skip if anchor_points has no zones (legacy or incomplete anchor data).
    if anchor_points and anchor_points.get('zones'):
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

    prompt = f"""You are a spatial consistency corrector for an AI-generated vertical drama series.

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

    @retry_on_errors(max_retries=3, backoff_factor=2)
    def _call_api():
        return llm.make_json(prompt, SPATIAL_REWRITE_SCHEMA)

    result = _call_api()
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


# ---------------------------------------------------------------------------
# Checkpoint writer
# ---------------------------------------------------------------------------
def _write_episode_checkpoint(episode_counter: int, scenes: list, output_dir: Path):
    """Atomically write all refined scenes for an episode to its checkpoint file."""
    out_path = output_dir / f"animation_episode_scenes_{episode_counter:03d}_refined.json"
    content = json.dumps({'scenes': scenes}, ensure_ascii=False, indent=2)
    tmp_fd, tmp_name = tempfile.mkstemp(dir=output_dir, suffix='.json.tmp')
    try:
        with os.fdopen(tmp_fd, 'w', encoding='utf-8') as f:
            f.write(content)
        os.replace(tmp_name, out_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Single scene processing
# ---------------------------------------------------------------------------
def process_single_scene(
    episode_counter: int,
    scene_id: int,
    scene: dict,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    all_scenes: list,
    output_dir: Path = None,
) -> dict:
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    scene['scene_id'] = scene_id
    scene['episode_id'] = episode_counter
    for idx, panel in enumerate(scene.get('panels', []), 1):
        panel['panel_index'] = idx
        panel.setdefault('is_reversed', False)
        panel.setdefault('motion_prompt_reversed', '')
        panel.setdefault('motion_intent', '')
        panel.setdefault('voiceover', '')
        panel.setdefault('voiceover_settings', {})
        panel.setdefault('emotional_beat', '')
        panel.setdefault('hook_type', 'none')
        panel.setdefault('text_safe_composition', True)
        panel.setdefault('panel_type', 'narrative')
        panel.setdefault('transition_to_next', 'hard_cut')
        panel.setdefault('sound_design', 'silence')
        panel.setdefault('location_references', [])
        panel.setdefault('visual_disposition', '')

    if config.get('animation', {}).get('reversal_pass', True):
        scene = apply_reversal_pass(scene, prompts, config, llm)
    else:
        # Reversal pass disabled: clear is_reversed so downstream animation/render
        # treats all panels as forward clips.
        for panel in scene.get('panels', []):
            panel['is_reversed'] = False
            panel['motion_prompt_reversed'] = ''
        logger.info(f"      ⏭  Scene {scene['scene_id']}: reversal pass disabled — all panels treated as forward")

    all_scenes.append(scene)
    return scene


# ---------------------------------------------------------------------------
# Sequential scenes pipeline (used by cli.py `scenes` subcommand)
# ---------------------------------------------------------------------------
def run_scenes_pipeline(
    episodes: list,
    episodes_list: list,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    output_dir: Path,
    character_info: dict = None,
    state: ProjectState | None = None,
    resume: bool = False,
) -> list:
    """
    Process a filtered list of episodes sequentially:
      analyze → reversal → write checkpoint per episode.
    Returns all_scenes (list of scene dicts, mutated in place by process_single_scene).

    With resume=True and a ProjectState, episodes whose reversal checkpoint is already
    marked done are loaded from disk instead of re-running.
    """
    all_episodes: list = []
    continuity_map = {ep['episode_id']: episodes_list[i - 1].get('visual_continuity_rules', '') if i > 0 else '' for i, ep in enumerate(episodes_list)}
    active_questions_map = {ep['episode_id']: episodes_list[i - 1].get('active_questions', {}) if i > 0 else {} for i, ep in enumerate(episodes_list)}

    prev_episode_exit: dict | None = None  # exit context (visual_end + state) from previous episode
    for ep in episodes:
        ep_id = ep['episode_id']
        # Phase 1 skip: raw analysis already done — load raw checkpoint
        if resume and state and state.episode_raw_done(ep_id):
            raw_path = output_dir / f"animation_episode_scenes_{ep_id:03d}.json"
            if raw_path.exists():
                try:
                    loaded = json.loads(raw_path.read_text(encoding='utf-8'))
                    all_episodes.append((ep_id, loaded))
                    prev_episode_exit = _extract_episode_exit(loaded)
                    logger.info(f"⏭  Episode {ep_id}: raw checkpoint loaded (skipping LLM analysis)")
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"⚠️  Episode {ep_id}: raw checkpoint unreadable ({exc}), re-analyzing")
        prev_rules = continuity_map.get(ep_id, '')
        analyze_scenes_for_episode(
            ep_id, json.dumps(ep, ensure_ascii=False, indent=2),
            prompts, config, llm, all_episodes,
            character_info=character_info,
            prev_continuity_rules=prev_rules,
            prev_active_questions=active_questions_map.get(ep_id, {}),
            prev_episode_exit=prev_episode_exit,
        )
        # Update exit context from the episode we just analyzed
        if all_episodes and all_episodes[-1][0] == ep_id:
            prev_episode_exit = _extract_episode_exit(all_episodes[-1][1])

    ep_scenes_map: dict = {}
    scene_counter = 0
    for ep_counter, data in sorted(all_episodes, key=lambda x: x[0]):
        ep_scenes_map[ep_counter] = []
        for scene in data.get('scenes', []):
            scene_counter += 1
            ep_scenes_map[ep_counter].append((scene_counter, scene))

    all_scenes: list = []
    for ep_counter, scene_list in sorted(ep_scenes_map.items()):
        # Phase 2 skip: checkpoint already done — load from disk
        if resume and state and state.episode_refined_done(ep_counter):
            refined_path = output_dir / f"animation_episode_scenes_{ep_counter:03d}_refined.json"
            if refined_path.exists():
                try:
                    data = json.loads(refined_path.read_text(encoding='utf-8'))
                    all_scenes.extend(data.get('scenes', []))
                    logger.info(f"⏭  Episode {ep_counter}: reversal checkpoint loaded (skipping)")
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"⚠️  Episode {ep_counter}: checkpoint unreadable ({exc}), re-running")

        ep_processed: list = []
        for sc_id, scene in scene_list:
            ep_processed.append(process_single_scene(
                ep_counter, sc_id, scene, prompts, config, llm, all_scenes,
                output_dir=output_dir,
            ))
        if ep_processed:
            try:
                _write_episode_checkpoint(ep_counter, ep_processed, output_dir)
                if state:
                    state.mark_episode_refined_done(ep_counter)
            except Exception as e:
                logger.warning(f"⚠️  Could not write checkpoint for episode {ep_counter}: {e}")

    return all_scenes


# ---------------------------------------------------------------------------
# Scene merge / upsert
# ---------------------------------------------------------------------------
def merge_scenes(
    old_metadata: dict,
    new_scenes: list,
    new_ep_ids: set,
    panels_dir: Path,
) -> list:
    """
    Upsert new_scenes into old_metadata['scenes'], preserving scene_ids where possible
    so that panels/<NNN>_*.png filenames remain valid.

    - If the number of scenes for the replaced episodes is unchanged, old scene_ids are reused.
    - If the count changed, new sequential IDs are assigned and orphaned panel files are logged.
    Returns the merged, sorted list of scenes.
    """
    old_scenes = old_metadata.get('scenes', [])
    kept = [s for s in old_scenes if s.get('episode_id') not in new_ep_ids]
    old_ep_scene_ids = sorted(
        s['scene_id'] for s in old_scenes if s.get('episode_id') in new_ep_ids
    )
    merged = sorted(kept, key=lambda s: s.get('scene_id', 0))

    if len(new_scenes) == len(old_ep_scene_ids):
        for scene, sid in zip(new_scenes, old_ep_scene_ids):
            scene['scene_id'] = sid
        merged = sorted(merged + new_scenes, key=lambda s: s.get('scene_id', 0))
    else:
        if old_ep_scene_ids:
            logger.warning(
                f"Scene count changed for episode(s) {sorted(new_ep_ids)}: "
                f"{len(old_ep_scene_ids)} old → {len(new_scenes)} new. "
                f"Panels for old scene_ids {old_ep_scene_ids} may be orphaned."
            )
            orphaned = sorted(
                p for sid in old_ep_scene_ids
                for p in panels_dir.glob(f"{sid:03d}_*.png")
            )
            if orphaned:
                logger.warning(
                    f"  Orphaned panel files ({len(orphaned)}): "
                    + ", ".join(p.name for p in orphaned)
                )
        next_id = (max(s['scene_id'] for s in merged) + 1) if merged else 1
        for scene in new_scenes:
            scene['scene_id'] = next_id
            next_id += 1
            merged.append(scene)

    return merged


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------
def analyze_scenes_master(
    text: str,
    prompts: dict,
    config: dict,
    llm: BaseLLM,
    character_info: dict = None,
    output_dir: Path = None,
    state: ProjectState | None = None,
    resume: bool = False,
) -> dict:
    """
    Full pipeline: episodes → scenes → reversal → save JSONs.
    Returns {'scenes': [...]}.

    With resume=True and a ProjectState, each completed phase is skipped and
    loaded from its checkpoint file:
      - Phase 1 (episodes):  skipped if state.episodes_done()  → load animation_episodes.json
      - Phase 2 (raw/ep):    skipped if state.episode_raw_done(N) → load animation_episode_scenes_NNN.json
      - Phase 3 (reversal/ep): skipped if state.episode_refined_done(N) → load *_refined.json
    """
    output_dir = output_dir or DEFAULT_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Phase 1: episode breakdown ────────────────────────────────────────────
    episodes_path = output_dir / "animation_episodes.json"
    if resume and state and state.episodes_done() and episodes_path.exists():
        try:
            episodes = json.loads(episodes_path.read_text(encoding='utf-8'))
            logger.info("⏭  Phase 1: episode breakdown loaded from checkpoint (skipping LLM)")
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"⚠️  Episode checkpoint unreadable ({exc}), re-generating")
            episodes = None
    else:
        episodes = None

    if episodes is None:
        episodes = analyze_episodes_master(text, prompts, config, llm, character_info=character_info)
        if not episodes:
            raise RuntimeError(
                "analyze_episodes_master returned None or empty — check LLM response and API key"
            )
        episodes_path.write_text(json.dumps(episodes, ensure_ascii=False, indent=2), encoding='utf-8')
        if state:
            state.mark_episodes_done(len(episodes.get('episodes', [])))
    logger.debug(episodes)

    all_scenes: list = []
    all_episodes: list = []

    episodes_list = episodes.get('episodes', [])
    continuity_map = {ep['episode_id']: episodes_list[i - 1].get('visual_continuity_rules', '') if i > 0 else '' for i, ep in enumerate(episodes_list)}
    active_questions_map = {ep['episode_id']: episodes_list[i - 1].get('active_questions', {}) if i > 0 else {} for i, ep in enumerate(episodes_list)}

    # ── Phase 2: raw scene analysis (sequential — prev_episode_exit threaded) ────
    failed_episodes = []
    prev_episode_exit: dict | None = None

    for i, episode in enumerate(episodes_list):
        episode_counter = episode.get('episode_id', i + 1)
        if resume and state and state.episode_raw_done(episode_counter):
            raw_path = output_dir / f"animation_episode_scenes_{episode_counter:03d}.json"
            if raw_path.exists():
                try:
                    data = json.loads(raw_path.read_text(encoding='utf-8'))
                    all_episodes.append((episode_counter, data))
                    prev_episode_exit = _extract_episode_exit(data)
                    logger.info(f"⏭  Episode {episode_counter}: raw checkpoint loaded (skipping LLM analysis)")
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"⚠️  Episode {episode_counter}: raw checkpoint unreadable ({exc}), re-analyzing")
        try:
            analyze_scenes_for_episode(
                episode_counter, json.dumps(episode, ensure_ascii=False, indent=2),
                prompts, config, llm, all_episodes,
                character_info=character_info,
                prev_continuity_rules=continuity_map.get(episode_counter, ''),
                prev_active_questions=active_questions_map.get(episode_counter, {}),
                prev_episode_exit=prev_episode_exit,
            )
            if all_episodes and all_episodes[-1][0] == episode_counter:
                prev_episode_exit = _extract_episode_exit(all_episodes[-1][1])
                # Checkpoint immediately — don't wait for the batch write after the loop
                raw_path = output_dir / f"animation_episode_scenes_{episode_counter:03d}.json"
                raw_path.write_text(json.dumps(all_episodes[-1][1], ensure_ascii=False, indent=2), encoding='utf-8')
                if state and not state.episode_raw_done(episode_counter):
                    state.mark_episode_raw_done(episode_counter)
                logger.info(f"  💾 Episode {episode_counter}: raw checkpoint written")
        except Exception as e:
            logger.error(f"❌ Episode {episode_counter} scene analysis failed: {e}")
            failed_episodes.append(episode_counter)

    if failed_episodes:
        total = len(episodes_list)
        logger.warning(f"⚠️  {len(failed_episodes)}/{total} episode(s) failed analysis: {failed_episodes}")
        if len(failed_episodes) >= total:
            raise RuntimeError(f"All {total} episodes failed scene analysis — aborting pipeline")

    all_episodes = sorted(all_episodes, key=lambda e: e[0])

    # Assign global scene IDs. Raw checkpoints were already written per-episode above.
    scene_counter = 0
    ep_scene_groups: dict = {}  # {episode_counter: [(scene_id, scene), ...]}

    for episode_counter, data in all_episodes:
        logger.info(f"Processing episode: {episode_counter} scene start: {scene_counter}")
        ep_scene_groups[episode_counter] = []
        for scene in data.get('scenes', []):
            scene_counter += 1
            ep_scene_groups[episode_counter].append((scene_counter, scene))

    # ── Phase 3: reversal pass (sequential — cross-episode order preserved) ──────
    failed_scenes = []
    for ep_counter in sorted(ep_scene_groups):
        # Skip if checkpoint already committed
        if resume and state and state.episode_refined_done(ep_counter):
            refined_path = output_dir / f"animation_episode_scenes_{ep_counter:03d}_refined.json"
            if refined_path.exists():
                try:
                    data = json.loads(refined_path.read_text(encoding='utf-8'))
                    all_scenes.extend(data.get('scenes', []))
                    logger.info(f"⏭  Episode {ep_counter}: reversal checkpoint loaded (skipping)")
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"⚠️  Episode {ep_counter}: checkpoint unreadable ({exc}), re-running")

        ep_processed: list = []
        for sc_id, scene in ep_scene_groups[ep_counter]:
            try:
                ep_processed.append(process_single_scene(
                    ep_counter, sc_id, scene, prompts, config, llm,
                    all_scenes, output_dir,
                ))
            except Exception as e:
                logger.error(f"❌ Scene {sc_id} processing failed: {e}")
                failed_scenes.append(sc_id)
        if ep_processed:
            try:
                _write_episode_checkpoint(ep_counter, ep_processed, output_dir)
                if state:
                    state.mark_episode_refined_done(ep_counter)
            except Exception as e:
                logger.warning(f"⚠️  Could not write checkpoint for episode {ep_counter}: {e}")

    all_scenes = sorted(all_scenes, key=lambda s: s['scene_id'])
    return {'scenes': all_scenes}
