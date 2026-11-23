"""Episode breakdown and per-episode prompt blocks; scopes refs to a scene's location."""
import copy
import json
import logging
import re

from lib.core.schemas import (
    SCREENPLAY_SCHEMA,
)
from lib.core.utils import PANEL_COUNT_OPTIONS
from lib.llm.base import BaseLLM
from lib.studio import ledger

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


_LOCATION_TYPES = frozenset({'room', 'vehicle', 'outdoor', 'location'})
_VIEW_SUFFIX_RE = re.compile(r'-(?:View-.+|Interior-.+|Exterior)$')
# Words too generic to tell one location ref from another.
_LOCATION_STOPWORDS = frozenset({'room', 'interior', 'exterior', 'the', 'and'})


def _scope_refs_to_scene(character_info: dict, scene_text: str) -> dict:
    """Drop location refs unrelated to this scene; characters and props pass through.

    Every scene used to receive the anchors and descriptions of every location in the
    project. A location ref is kept when every distinctive word of its name occurs in
    scene_text — all of them, because a partial match on a common word ("office") would
    scope the scene to the wrong room and hide the right one. scene_text must be the
    scene's location AND its instructions: a scene often cuts to a second location that
    only the instructions name (2 of 5 scenes in the CRAB test project).
    Returns character_info unchanged when nothing matches (non-Latin text, paraphrased
    names) — an unscoped prompt is costlier but never wrong.
    """
    words = set(re.findall(r'[a-z0-9]{3,}', (scene_text or '').lower()))

    def _matches(name: str) -> bool:
        tokens = set(re.findall(r'[a-z0-9]{3,}', _VIEW_SUFFIX_RE.sub('', name).lower()))
        tokens = (tokens - _LOCATION_STOPWORDS) or tokens
        return bool(tokens) and tokens <= words

    is_location = {
        name: (info.get('type') or '').lower() in _LOCATION_TYPES
        for name, info in (character_info or {}).items()
    }
    kept = {name for name, loc in is_location.items() if loc and _matches(name)}
    if not kept:
        return character_info
    dropped = sorted(name for name, loc in is_location.items() if loc and name not in kept)
    if dropped:
        logger.info(f"      🗺  Scene location refs: {sorted(kept)} ({len(dropped)} other location ref(s) left out)")
    return {name: info for name, info in character_info.items() if not is_location[name] or name in kept}


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
    panel_count_field = schema['properties']['episodes']['items']['properties']['scenes']['items']['properties']['panel_count']
    panel_count_field['description'] = panel_count_field['description'].replace(
        ', '.join(map(str, PANEL_COUNT_OPTIONS)), ', '.join(map(str, panel_count_options)))
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
            if info.get('type', '') == 'Room' and 'View-From-Entrance' not in name:
                continue

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
    screenplay = _clamp_panel_counts(llm.make_json(prompt, schema), panel_count_options)
    issues = ledger.screenplay_issues(screenplay or {})
    if not issues:
        return screenplay
    for issue in issues:
        logger.warning(f"  ⚠️  Continuity: {issue}")
    retry = llm.make_json(f"{prompt}\n\n{ledger.issues_block(issues)}", schema)
    retry = retry and _clamp_panel_counts(retry, panel_count_options)
    left = ledger.screenplay_issues(retry or {})
    if retry and len(left) < len(issues):
        logger.info(f"  🔁 Screenplay retry: {len(issues)} → {len(left)} continuity issue(s)")
        return retry
    return screenplay


def _clamp_panel_counts(screenplay: dict, panel_count_options: list[int]) -> dict:
    """The grid renderer has layouts only for the style's panel counts."""
    for episode in screenplay.get('episodes', []):
        for scene in episode.get('scenes', []):
            count = scene.get('panel_count')
            if count is not None and count not in panel_count_options:
                scene['panel_count'] = min(panel_count_options, key=lambda option: (abs(option - count), -option))
                logger.warning(f"  ⚠️  Episode {episode.get('episode_id')} scene {scene.get('scene_local_id')}: "
                               f"panel_count {count} not in {panel_count_options} → {scene['panel_count']}")
    return screenplay


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
    block = prompts.get(f'episode_type_{episode_type}', '')
    if not block and episode_type not in ('', 'standard'):
        logger.warning(f"  ⚠️  No episode_type_{episode_type}.md in the active style — episode gets no type-specific rules")
    return block


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
        'panel': last_panel,
        'scene': scenes[-1],
    }
