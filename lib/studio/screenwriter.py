"""
Screenwriter — screenplay and scene keyframe generation.

Prompts are loaded from lib/prompting/<style>/ via load_prompts().
"""
import copy
import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock


from lib.core import puppet as _puppet
from lib.core.prompts import TARGET_LANGUAGE
from lib.core.schemas import SCREENPLAY_SCHEMA, SCENE_SCHEMA, REVERSAL_SCHEMA, SPATIAL_DISPOSITION_SCHEMA
from lib.core.state import ProjectState
from lib.core.utils import DEFAULT_OUTPUT_DIR, is_portrait
from lib.llm.base import BaseLLM, retry_on_errors

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 3-POV continuity map — enforces temporal parallelism
# ---------------------------------------------------------------------------
def _build_continuity_map(episodes_list: list) -> dict:
    """
    Return {episode_id: prev_continuity_rules} enforcing 3-POV temporal parallelism.

    Within each chapter (same chapter_id):
    - pov_a and pov_b both receive the chapter entry state (previous chapter's
      confrontation exit) — NOT each other's output, because they are parallel timelines.
    - confrontation receives merged pov_a + pov_b exit states (both characters'
      visual state at the meeting threshold).
    - transition (chapter_id: 0): linear chain from previous episode.

    Falls back to linear chaining when chapter_id is absent (pre-schema episodes).
    """
    if not episodes_list or 'chapter_id' not in episodes_list[0]:
        result = {}
        for i, ep in enumerate(episodes_list):
            prev = episodes_list[i - 1].get('visual_continuity_rules', '') if i > 0 else ''
            result[ep['episode_id']] = prev
        return result

    # First pass: collect chapter entry states and pov exits.
    chapter_state: dict = {}  # {chapter_id: {entry_state, pov_a_exit, pov_b_exit}}
    last_confrontation_exit = ''

    for ep in episodes_list:
        cid = ep.get('chapter_id', 0)
        etype = ep.get('episode_type', '')
        if cid == 0 or etype == 'transition':
            continue
        if cid not in chapter_state:
            chapter_state[cid] = {
                'entry_state': last_confrontation_exit,
                'pov_a_exit': '',
                'pov_b_exit': '',
            }
        cs = chapter_state[cid]
        if etype == 'pov_a':
            cs['pov_a_exit'] = ep.get('visual_continuity_rules', '')
        elif etype == 'pov_b':
            cs['pov_b_exit'] = ep.get('visual_continuity_rules', '')
        elif etype == 'confrontation':
            last_confrontation_exit = ep.get('visual_continuity_rules', '')

    # Second pass: assign prev_rules per episode.
    continuity_map: dict = {}
    last_prev = ''
    for ep in episodes_list:
        cid = ep.get('chapter_id', 0)
        etype = ep.get('episode_type', '')
        eid = ep['episode_id']
        cs = chapter_state.get(cid, {})

        if etype == 'pov_a':
            continuity_map[eid] = cs.get('entry_state', '')
        elif etype == 'pov_b':
            continuity_map[eid] = cs.get('entry_state', '')  # same entry, not pov_a output
        elif etype == 'confrontation':
            pov_a_exit = cs.get('pov_a_exit', '')
            pov_b_exit = cs.get('pov_b_exit', '')
            if pov_a_exit and pov_b_exit:
                continuity_map[eid] = (
                    f"POV-A state at meeting threshold:\n{pov_a_exit}"
                    f"\n\nPOV-B state at meeting threshold:\n{pov_b_exit}"
                )
            else:
                continuity_map[eid] = pov_a_exit or pov_b_exit or cs.get('entry_state', '')
        else:
            # transition or unknown: linear
            continuity_map[eid] = last_prev

        last_prev = ep.get('visual_continuity_rules', '')

    return continuity_map


_ARC_TYPES = {'arc_open', 'arc_mid', 'arc_close'}
_POV_TYPES = {'pov_a', 'pov_b', 'confrontation'}


def validate_episode_structure(episodes_list: list) -> None:
    """Warn on 3-POV structural violations (wrong triplet order or missing types).
    Skips validation for long-arc styles (arc_open/arc_mid/arc_close episode types).
    """
    if not any('chapter_id' in ep for ep in episodes_list):
        return
    all_types = {ep.get('episode_type', '') for ep in episodes_list}
    if all_types & _ARC_TYPES:
        return  # long-arc style — linear structure, no triplet constraint
    if not (all_types & _POV_TYPES):
        return  # single-POV style (microdrama DramaBox) — no triplet constraint
    chapters: dict = {}
    for ep in episodes_list:
        cid = ep.get('chapter_id', 0)
        if cid == 0 or ep.get('episode_type') == 'transition':
            continue
        chapters.setdefault(cid, []).append(ep.get('episode_type', ''))
    expected = ['pov_a', 'pov_b', 'confrontation']
    for cid in sorted(chapters):
        if chapters[cid] != expected:
            logger.warning(
                "⚠️  Chapter %d 3-POV violation: expected %s, got %s",
                cid, expected, chapters[cid],
            )


# ---------------------------------------------------------------------------
# base_scene_prompt — verbatim from 01_cinematic_preroll.py:468-525
# ---------------------------------------------------------------------------
def base_scene_prompt(prompts: dict, config: dict, character_info: dict = None) -> str:
    scenery_template = prompts.get('scenery', '')
    setting_context = prompts.get('setting', '')
    panels_per_scene = config['format']['panels_per_scene']
    is_animation = config['animation']['enabled']

    char_refs_block = ""
    if character_info:
        lines = []
        for name, info in character_info.items():
            desc = info.get('video_visual_desc') or info.get('visual_desc', '')
            if desc:
                lines.append(f"- {name}: {desc}")
            else:
                lines.append(f"- {name}")
        char_refs_block = "CHARACTER/LOCATION REFERENCE BASELINE — for identification only. In visual_start/visual_end write ONLY deviations from these (costume change, injury, scene prop, flashback). Do NOT repeat canonical features already here:\n" + "\n".join(lines)
    else:
        char_refs_block = "Available Characters/Locations/Objects for panel references: []"

    prompt = f"""
{scenery_template}

{setting_context}

CONTEXT:
{char_refs_block}
Panels per scene: {panels_per_scene}
Animation mode: {is_animation}

{"Include visual_start and visual_end for START/END keyframes." if is_animation else "Include single key visual moment per panel."}
{f"Include dialogue (≤{config['dialogue'].get('max_words_per_line', 8)} words per line) and voiceover for each panel." if config['dialogue']['enabled'] else ""}
{"Include caption for narrative text." if config['captions']['enabled'] else ""}
Important: all dialogues, voiceovers and texts MUST be in {TARGET_LANGUAGE} for the consistency.

{prompts.get('screenplay_scene', '')}
    """
    return prompt


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
            "arc_open  (Ep1, P1–9):  cold_open[A+B] → first_demand[A] → first_counter[B] →\n"
            "                         escalation[A] → emotional_capture[B] → rising_action[A] →\n"
            "                         pivot → near_collapse[B] → arc_bridge[A+B]\n"
            "arc_close (Ep2, P1–9):  arc_pickup[A+B] → pressure_exchange[A] → decisive_blow[B] →\n"
            "                         impact[A] → pivot → twist → cost[A+B] →\n"
            "                         consequence[A+B] → cliffhanger[A+B: ambiguous]\n"
            "```\n"
        )
    elif episodes_count == 4:
        arc_map = (
            "### DUEL ARC — 4-EPISODE STRUCTURE\n\n"
            "```\n"
            "arc_open  (Ep1, P1–9):  cold_open[A+B] → first_demand[A] → first_counter[B] →\n"
            "                         escalation[A] → emotional_capture[B] → rising_action[A] →\n"
            "                         pivot → near_collapse[B] → arc_bridge[A+B]\n"
            "arc_mid   (Ep2, P1–9):  arc_pickup[A+B] → pressure_exchange → complication →\n"
            "                         rising_pressure[B] → pivot → new_weapon[A] →\n"
            "                         counter_offensive[B] → pre_collapse[A] → arc_bridge[A+B]\n"
            "arc_mid   (Ep3, P1–9):  arc_pickup[A+B] → deepening_complication → revelation[B] →\n"
            "                         escalating_cost[A] → pivot → point_of_no_return[A] →\n"
            "                         final_gambit[B] → convergence[A+B] → arc_bridge[A+B]\n"
            "arc_close (Ep4, P1–9):  arc_pickup[A+B] → collapse_point → reversal →\n"
            "                         aftermath → pivot → twist → cost[A+B] →\n"
            "                         consequence[A+B] → cliffhanger[A+B: ambiguous]\n"
            "```\n"
        )
    elif episodes_count == 5:
        arc_map = (
            "### DUEL ARC — 5-EPISODE STRUCTURE\n\n"
            "```\n"
            "arc_open  (Ep1, P1–9):  cold_open[A+B] → first_demand[A] → first_counter[B] →\n"
            "                         escalation[A] → emotional_capture[B] → rising_action[A] →\n"
            "                         pivot → near_collapse[B] → arc_bridge[A+B]\n"
            "arc_mid   (Ep2, P1–9):  arc_pickup[A+B] → pressure_exchange → complication →\n"
            "                         rising_pressure[B] → pivot → new_weapon[A] →\n"
            "                         counter_offensive[B] → pre_collapse[A] → arc_bridge[A+B]\n"
            "arc_mid   (Ep3, P1–9):  arc_pickup[A+B] → deepening_complication → revelation[B] →\n"
            "                         escalating_cost[A] → pivot → point_of_no_return[A] →\n"
            "                         final_gambit[B] → convergence[A+B] → arc_bridge[A+B]\n"
            "arc_mid   (Ep4, P1–9):  arc_pickup[A+B] → last_chance[A] → ultimatum[B] →\n"
            "                         desperation_move[A] → pivot → cost_revealed[A+B] →\n"
            "                         forced_choice[B] → threshold_crossed[A] → arc_bridge[A+B]\n"
            "arc_close (Ep5, P1–9):  arc_pickup[A+B] → collapse_point → reversal →\n"
            "                         aftermath → pivot → twist → cost[A+B] →\n"
            "                         consequence[A+B] → cliffhanger[A+B: ambiguous]\n"
            "```\n"
        )
    else:
        arc_map = (
            "### DUEL ARC — 3-EPISODE STRUCTURE\n\n"
            "```\n"
            "arc_open  (Ep1, P1–9):  cold_open[A+B] → first_demand[A] → first_counter[B] →\n"
            "                         escalation[A] → emotional_capture[B] → rising_action[A] →\n"
            "                         pivot → near_collapse[B] → arc_bridge[A+B]\n"
            "arc_mid   (Ep2, P1–9):  arc_pickup[A+B] → pressure_exchange → complication →\n"
            "                         rising_pressure[B] → pivot → new_weapon[A] →\n"
            "                         counter_offensive[B] → pre_collapse[A] → arc_bridge[A+B]\n"
            "arc_close (Ep3, P1–9):  arc_pickup[A+B] → collapse_point → reversal →\n"
            "                         aftermath → pivot → twist → cost[A+B] →\n"
            "                         consequence[A+B] → cliffhanger[A+B: ambiguous]\n"
            "```\n"
        )

    duel_block = (prompts.get('episode_type_duel', '')
                  .replace('__CHAR_A__', char_a)
                  .replace('__CHAR_B__', char_b))
    return f"## DUEL MODE — {char_a.upper()} vs {char_b.upper()}\n\n{arc_map}\n{duel_block}"


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
    panels_per_scene = config['format'].get('panels_per_scene', 9)
    multi_pov_cfg = config.get('multi_pov', {})
    multi_pov_enabled = multi_pov_cfg.get('enabled', False)

    transitions_instruction = (
        f'7. TRANSITION EPISODES (episode_type: "transition"): When a significant time gap (>{gap_threshold}) exists between chapters, insert one Transition episode BEFORE the POV-A episode of the next chapter. Transitions bridge the gap using {transition_style} technique — parallel environmental shots from each character\'s space during the time gap (e.g. both characters\' environments at dawn, rain on two different windows). Rules: no dialogue, no voiceover, no character close-ups, panel_type "narrative", panel durations 2–3s. pov_character: "". Episode must still have {panels_per_scene} panels.'
        if transitions_enabled else
        '7. Do not generate transition episodes.'
    )

    if multi_pov_enabled:
        temporal_mode = multi_pov_cfg.get('temporal_mode', 'parallel')
        if temporal_mode == 'complementary':
            temporal_rule = (
                '6b. COMPLEMENTARY PERSPECTIVES (MANDATORY): POV-A and POV-B of the same chapter are NOT required to cover the same clock window — '
                'they may be parallel timelines OR emotionally sequential, depending on narrative needs. '
                'POV-B may show backstory, the other side of a conversation, or parallel moments that reframe POV-A\'s emotional logic. '
                'Both episodes MUST end at the same emotional surrender threshold: the instant before the two characters\' next charged meeting. '
                'The test: a viewer who watches both POVs must feel they understand the full emotional geometry of the chapter — '
                'her desire and restraint, his obsession and control — before the connection episode resolves the tension.'
            )
        else:
            temporal_rule = (
                '6b. TEMPORAL PARALLELISM (MANDATORY): POV-A and POV-B of the same chapter cover the SAME clock window — they are parallel timelines, not sequential. '
                'Both open at the same diegetic moment and both end at the exact same narrative threshold: the instant before the two characters meet. '
                'Confrontation picks up from that threshold. Never advance POV-B past where POV-A ends, and never let POV-A events bleed into POV-B time. '
                'The viewer sees the same chapter twice — once through each character\'s eyes — and the two lines converge at the confrontation.'
            )
        multi_pov_instruction = (
            '6. MULTI-POV DECOMPOSITION: Decompose each chapter into exactly 3 sub-episodes in this fixed order:\n'
            '   a. POV-A (episode_type: "pov_a"): First protagonist\'s perspective exclusively. Their actions, thoughts, observations. Other character absent or peripheral. Set pov_character to their name.\n'
            '   b. POV-B (episode_type: "pov_b"): Second protagonist\'s perspective exclusively. Their reaction to the same events, internal world. Set pov_character to their name.\n'
            '   c. Confrontation (episode_type: "confrontation"): Both characters present, direct interaction, peak emotional charge of the chapter. pov_character: "".\n'
            '   Cover the full story from beginning to end. Each sub-episode covers 30–50 seconds of real-time action.\n'
            '   Tag each episode with chapter_id = source chapter number (integer, 1-based). All three sub-episodes of the same chapter share the same chapter_id. Transition episodes use chapter_id: 0.\n'
            f'{temporal_rule}'
        )
        schema = SCREENPLAY_SCHEMA
    else:
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
    arc_panels = episodes_count * 9
    arc_duration_map = {2: '~54s', 3: '~81s', 4: '~108s', 5: '~135s'}
    arc_duration = arc_duration_map.get(episodes_count, f'~{episodes_count * 27}s')
    duel_cfg = config.get('duel', {})
    duel_instruction = _build_duel_instruction(duel_cfg, prompts, episodes_count) if duel_cfg.get('enabled') else ''
    episodes_rules = (
        episodes_rules
        .replace('__EPISODES_COUNT__', str(episodes_count))
        .replace('__ARC_PANELS__', str(arc_panels))
        .replace('__ARC_DURATION__', arc_duration)
        .replace('__DUEL_INSTRUCTION__', duel_instruction)
    )

    if character_info:
        lines = []
        for name, info in character_info.items():
            desc = info.get('video_visual_desc') or info.get('visual_desc', '')
            if desc:
                lines.append(f"- {name}: {desc}")
            else:
                lines.append(f"- {name}")
        char_refs_block = (
            "CHARACTER/LOCATION REFERENCES — for screenplay planning and visual_continuity_rules only "
            "(use exact descriptions to prevent hallucination). Panel visual_start/visual_end must describe "
            "only scene-specific deviations, not repeat these baselines:\n" + "\n".join(lines)
        )
    else:
        char_refs_block = ""

    prompt = (
        f"{episodes_rules}\n\n{setting_context}\n\n"
        + (f"{char_refs_block}\n\n" if char_refs_block else "")
        + f"Respond in specified JSON format.\n\nTEXT TO ADAPT:\n<STORY>{text}</STORY>"
    )
    return llm.make_json(prompt, schema)


# ---------------------------------------------------------------------------
# Episode-type-specific prompt block
# ---------------------------------------------------------------------------
def _episode_type_block(episode_type: str, pov_character: str, prompts: dict, config: dict) -> str:
    """Return episode-type-specific cinematic constraints loaded from prompts."""
    if episode_type in ('pov_a', 'pov_b'):
        label = 'A' if episode_type == 'pov_a' else 'B'
        char = pov_character or f'POV-{label} character'
        tmpl = prompts.get('episode_type_pov', '')
        return tmpl.replace('{{LABEL}}', label).replace('{{CHAR}}', char)
    if episode_type == 'pov':
        return prompts.get('episode_type_pov', '')
    if episode_type == 'confrontation':
        return prompts.get('episode_type_confrontation', '')
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
):
    logger.info(f"\n🎥 MASTER CINEMATOGRAPHER: Preparing Keyframes for episode {episode_counter}...")
    base_prompt = base_scene_prompt(prompts, config, character_info)

    # Extract episode metadata
    try:
        episode_data = json.loads(text)
        current_continuity = episode_data.get('visual_continuity_rules', '')
        episode_type = episode_data.get('episode_type', '')
        pov_character = episode_data.get('pov_character', '')
    except (json.JSONDecodeError, AttributeError):
        current_continuity = ''
        episode_type = ''
        pov_character = ''

    continuity_block = ""
    if prev_continuity_rules:
        continuity_block += f"\n## VISUAL CONTINUITY FROM PREVIOUS EPISODE — MANDATORY\nThese rules MUST be enforced in every panel of this episode:\n{prev_continuity_rules}\n"
    if current_continuity:
        continuity_block += f"\n## THIS EPISODE'S VISUAL STATE (carry forward to future scenes)\n{current_continuity}\n"

    episode_type_block = _episode_type_block(episode_type, pov_character, prompts, config)

    prompt = f"""
    {base_prompt}
    {continuity_block}
    {episode_type_block}
    TEXT TO ADAPT:
    {text}
"""
    @retry_on_errors(max_retries=3, backoff_factor=2)
    def _call():
        return llm.make_json(prompt, SCENE_SCHEMA)

    result = _call()
    if not result or 'scenes' not in result:
        logger.error(f"❌ Empty scene result for episode {episode_counter}")
    all_episodes.append((episode_counter, result or {}))
    logger.info(f"CINEMATOGRAPHER: Ready Keyframes for episode {episode_counter}")


# ---------------------------------------------------------------------------
# Refinement pass
# ---------------------------------------------------------------------------
def refine_scenes_for_episode(scene: dict, prompts: dict, config: dict, llm: BaseLLM, character_info: dict = None, prev_scene_terminal: str = None) -> dict:
    """
    Refinement pass before reversal:
    1. Makes every panel self-contained — all character/location details inline.
    2. Ensures visual_start explicitly describes spatial disposition.
    3. Flags is_reversed=true when a character/object appears in visual_end/motion_prompt
       without being present in visual_start (animation backend has no image-reference support).
    4. Enforces cross-panel spatial continuity and cross-scene entry state.
    5. Verifies emotional arc integrity (rules loaded from prompts).
    6. Enforces camera_master/lighting_master compliance across all panels.
    """
    scene_id = scene.get('scene_id', '?')
    logger.info(f"    ✏️  Refinement pass: scene {scene_id}")

    base_prompt = base_scene_prompt(prompts, config, character_info)
    aspect_ratio = config['image_generation'].get('aspect_ratio', '9:16')
    scene_text = json.dumps(scene, ensure_ascii=False, indent=2)

    # Build spatial chain: existing panel endpoints for cross-panel anchor
    panels_sorted = sorted(scene.get('panels', []), key=lambda p: p.get('panel_index', 0))
    panels_spatial_chain = "\n".join(
        f"  Panel {p.get('panel_index', '?')} visual_end: {p.get('visual_end', '')[:250]}"
        for p in panels_sorted
    )

    # Cross-scene entry block
    prev_terminal_block = ""
    if prev_scene_terminal:
        prev_terminal_block = f"""
### RULE 4 — CROSS-SCENE SPATIAL CONTINUITY
The PREVIOUS scene ended on this exact visual state:
<PREV_SCENE_TERMINAL>
{prev_scene_terminal}
</PREV_SCENE_TERMINAL>
Panel 1's visual_start MUST be spatially compatible: same environment, same lighting condition,
same character positions — unless this scene opens in a different location or after a time-skip,
in which case state that explicitly in panel 1's visual_start (e.g. "CUT TO: new location, 10 minutes later").
"""

    prompt = f"""
{base_prompt}

{"**IMPORTANT: ADJUST CAMERA AND DYNAMICS TO SCENE NEEDS FOR IMMERSIVE VERTICAL VIEW**" if is_portrait(aspect_ratio) else "**IMPORTANT: ADJUST CAMERA AND DYNAMICS TO SCENE NEEDS FOR IMMERSIVE WIDESCREEN VIEW**"}

**Your task: refine the single scene below. Return it with the SAME schema, improving every panel
according to the rules below. Do NOT change scene_id, panel_index, or structural fields.**

## REFINEMENT RULES

### RULE 1 — SELF-CONTAINED PANELS (deviations only, not full descriptions)
Each panel is rendered INDEPENDENTLY alongside its character/location reference images.
The T2I model already receives reference PNGs and their full descriptions — do NOT repeat baseline
appearance (canonical outfit, hair color, build, eye color) that is already in the references.

Instead, for each panel write ONLY what DIFFERS from the reference for this specific panel:
- Costume/wardrobe changes (e.g. "wearing silk robe instead of usual dress")
- Scene-specific props not in the reference (e.g. "holding a gun", "bandage on left arm")
- Flashback or alternate-timeline appearance (e.g. "younger, 18yo, school uniform — flashback")
- Injury, dirt, wetness, or other transient physical state

NEVER repeat canonical features (hair color, body type, usual clothing) — they are in the refs.
NEVER write "same appearance as before" or "continues from panel N" — each panel is standalone.

Always specify per panel (these are NOT in references):
- Repeat the location details (architecture, lighting, props, atmosphere) in every panel.
- Repeat the exact shot type and camera angle (ECU / CU / MS / WIDE + lens + angle) in every panel
  and in lights_and_camera — never say "same framing".

### RULE 2 — SPATIAL DISPOSITION IN visual_start
visual_start must explicitly state the spatial arrangement at t=0:
- Who is present, where they stand/sit relative to camera and to each other.
- Body orientation (facing camera / three-quarter / profile / turned away).
- Distance from camera (foreground / mid-ground / background).
- Dominant expression, posture, gesture at t=0.
- Background elements visible from this camera angle.
- Any scene-specific appearance deviation from their reference (costume change, injury, etc.)
Example: "MEDIUM SHOT. Ivan stands LEFT of frame, facing RIGHT toward camera at 45°, arms crossed,
jaw tight, wearing silk robe [deviation: usually in grey hoodie]. Behind him: rain-streaked window,
blurred city lights bokeh."

### RULE 3 — is_reversed FLAG FOR ANIMATION
Panels will be animated as {config['format'].get('panel_duration_s', 6)}-second clips by the AI video model, which does NOT support image references.
The only way to show a character or object ENTERING the frame is reverse playback:
render the character LEAVING, then play the clip reversed.

Set is_reversed=true for any panel where:
- A character enters the scene, walks in, or appears from off-screen.
- An object comes into view (door opens revealing someone, fog clears to show a figure, etc.).
- Someone approaches the camera from a distance.
- visual_end shows a presence that is ABSENT in visual_start.
- A character's FACE is hidden at visual_start (back to camera, hood up, silhouette, turned away)
  and is REVEALED during the motion (turns around, removes hood, steps into light facing camera).
  Shoot the character turning AWAY (face → back), reverse so viewer sees the face reveal.
{prev_terminal_block}
### RULE 5 — CROSS-PANEL SPATIAL CONTINUITY
Characters do not teleport between panels. Each panel's visual_start at t=0 must be spatially
compatible with the PREVIOUS panel's visual_end unless a hard_cut or location change is established.
If a character was LEFT of frame at the end of panel N, they cannot be RIGHT of frame at the start
of panel N+1 without a stated camera repositioning or character movement.

Current panel endpoint chain (use as spatial anchor when refining):
<PANEL_SPATIAL_CHAIN>
{panels_spatial_chain}
</PANEL_SPATIAL_CHAIN>

{prompts.get('refinement_arc_rule', '')}

### RULE 7 — CAMERA AND LIGHTING MASTER COMPLIANCE
Every panel's lights_and_camera must stay within the scene's camera_master and lighting_master DNA.
Deviations for dramatic effect are allowed but must be flagged explicitly (e.g. "deviation from master:
snap to 24mm wide for panic effect, then return to established 85mm CU").

SCENE TO REFINE:
{scene_text}
"""

    @retry_on_errors(max_retries=3, backoff_factor=2)
    def _call_api():
        return llm.make_json(prompt, SCENE_SCHEMA)

    result = _call_api()
    if not result or 'scenes' not in result or not result['scenes']:
        logger.error(f"      ❌ Refinement returned empty for scene {scene_id}, keeping original")
        return scene

    refined_scene = result['scenes'][0]
    # Preserve top-level fields the LLM might not echo back
    for key in ('scene_id', 'episode_id'):
        if key in scene:
            refined_scene[key] = scene[key]

    logger.info(f"      ✅ Refinement done for scene {scene_id}")
    return refined_scene


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
    prompt = f"""
You are a Master Cinematographer writing motion prompts for AI video generation.

The following panels require REVERSE REVEAL animation. The clip is shot forward by the AI,
then reversed in post — so you describe forward physics that read naturally when played backward.

  - visual_start = what the viewer sees at t=0 (obscured/empty/hidden state)
  - visual_end   = what the viewer sees at the end (revealed/present state)

You must generate TWO things per panel:

1. motion_prompt_reversed — describes the FORWARD clip the AI will render:
   starts at visual_end state, ends at visual_start state.
   When this clip is reversed, the viewer sees visual_start → visual_end.

2. visual_start_explicit — a fully explicit rewrite of visual_end (which becomes the new
   visual_start after the swap). Required because the original visual_end may contain vague
   references like "same framing" or lack camera/shot details.
   Must include: shot type (ECU/CU/MS/MLS/LS), camera angle, character position in frame,
   key props, lighting state. No implicit references.

BODY MECHANICS RULES (critical for natural reversal):
- Name the exact limb used: "reaches with RIGHT hand", "steps with LEFT foot"
- State face direction at every beat: "facing camera", "in profile left", "turning 45° to door"
- Sequence every movement beat: weight shift, reach, grip, step, pivot — one sentence each
- For entries/exits: show full travel — partial frame edge → full frame presence, or reverse
- Forward physics that reverse naturally:
    character walking AWAY from camera  →  entry toward camera when reversed
    door swinging SHUT, character outside  →  door opening, entry when reversed
    character sitting DOWN  →  character rising when reversed

Example:
  Original visual_start: "Closed office door, empty hallway."
  Original visual_end:   "Secretary inside room, door open, colleagues laughing in background."
  → motion_prompt_reversed (forward: inside → outside):
    "At 0s: MS shot from room corner — Secretary stands center-frame just inside doorway,
    coat settling, colleagues visible over her right shoulder mid-laugh. Camera holds static.
    At 1s she turns her head left toward the door, shifts weight to left foot.
    At 2s she reaches forward with her RIGHT hand, grips the door handle.
    At 3s she steps backward with her right foot through the threshold, body crossing doorframe.
    At 4s she steps back again with left foot, now fully in hallway, facing INTO the room,
    left hand still holding the door edge. At 5.5s she pulls the door closed with a firm pull,
    door swinging toward camera. At 6.5s door clicks shut, hallway empty — closed door fills frame."
  → visual_start_explicit:
    "MS shot from room corner — Secretary stands center-frame just inside doorway, coat mid-settle,
    right hand at side, colleagues blurred in background over her right shoulder, warm office
    lighting, door fully open to the left of frame."

RULES:
- motion_prompt_reversed: 100+ words, timestamps, all verbs physically plausible forward
- Do NOT invent new visual elements beyond the two provided states
- Preserve all lighting and camera details from lights_and_camera
- Duration: {config['format'].get('panel_duration_s', 6)} seconds total

{setting_context}

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
_TO_ENTRANCE_SUFFIXES = ('-View-To-Entrance', '-Interior-To-Entrance', '-View-Opposite')
_VIEW_SWAP: dict[str, str] = {
    'View-From-Entrance': 'View-To-Entrance',
    'View-To-Entrance': 'View-From-Entrance',
    'Interior-From-Entrance': 'Interior-To-Entrance',
    'Interior-To-Entrance': 'Interior-From-Entrance',
    'View-Primary': 'View-Opposite',
    'View-Opposite': 'View-Primary',
}


def _panel_view_type(panel: dict) -> str:
    """Return 'To-Entrance' if this panel's location_references indicate a reversed-axis view."""
    for ref in panel.get('location_references', []):
        if any(ref.endswith(s) for s in _TO_ENTRANCE_SUFFIXES):
            return 'To-Entrance'
    return 'From-Entrance'


def _swap_view_ref(ref: str) -> str:
    """Swap the view-axis suffix of a location ref name. Returns original if no suffix matches."""
    for old, new in _VIEW_SWAP.items():
        if ref.endswith(f'-{old}'):
            return ref[: -len(old)] + new
    return ref


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
            'visual_start': p.get('visual_start', ''),
            'visual_end': p.get('visual_end', ''),
            'lights_and_camera': p.get('lights_and_camera', ''),
            'motion_prompt': p.get('motion_prompt', ''),
            'references': p.get('references', []),
            'location_references': p.get('location_references', []),
            'dialogue': p.get('dialogue', ''),
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
""" if prev_terminal_disposition else ""}
CRITICAL — USE ONLY PHYSICAL LANDMARKS. NEVER use "screen-left" or "screen-right".
Screen direction depends on the camera angle in lights_and_camera and changes between panels —
using screen directions in visual_disposition causes characters to appear to teleport when
the camera moves. visual_disposition must be camera-agnostic.

Use ONLY: compass walls (East wall / West wall / North wall / South wall),
named anchor objects (West chair / East chair / bar counter / marble table / entrance door),
physical relations (back to the brick wall / facing the gilded mirror / standing beside the bar counter).

Each panel has a "view_type" field for your spatial reasoning only.
  Rooms/Vehicles: "From-Entrance" (canonical axis) or "To-Entrance" (reversed — left/right swapped).
  Outdoor locations: "From-Entrance" maps to View-Primary (canonical axis); "To-Entrance" maps to View-Opposite (reversed — left/right swapped).
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
  Identify the single character whose face fills the frame. Determine which direction their
  face points, using anchor_points zones and narrative context.
  In a bilateral confrontation (interview, argument across a table): each character faces
  the other. Character at the entrance zone faces AWAY from entrance (toward desk). Character
  at the desk/far zone faces TOWARD the entrance.
  Express as "toward entrance" or "away from entrance".

STEP B — Camera direction for a face shot:
  • A face shot shows the character looking AT the camera (front-on or near-front).
    Camera is therefore on the side the character faces TOWARD.
    Character faces TOWARD entrance → camera is at/near entrance side → From-Entrance.
    Character faces AWAY from entrance (toward desk) → camera is on desk/far side → To-Entrance.
  • OVER-THE-SHOULDER / POV: camera is BEHIND the named subject, looking at the target.
    Apply the above rule to the TARGET character (whose face is actually visible), not the subject.

STEP C — Decide swap:
  Compare inferred view_type to current view_type. Set swap_view=true if they differ.

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
   destination anchor (visual_end), e.g. "Alisa moves FROM the marble table TOWARD the East wall bar counter".
3. Enforce cross-panel consistency: a character in the West chair in panel 1 stays in the West chair
   in all subsequent panels unless motion_prompt explicitly moves them.
   Read ALL panels before writing any — assign anchors globally first.
4. For tables: always name the physical chair (e.g. "West chair" / "East chair") per
   anchor_points.objects[].notes. Never use screen directions.
5. For single-character or no-character panels: name the nearest anchor object and depth
   (close to camera / mid-room / far end of room).
6. Keep each visual_disposition under 120 words.

DEPTH STACK RULE — required whenever furniture or props exist in the scene:
Use anchor_points Y-coordinates and view_type to compute depth order for each panel:
  - View-From-Entrance: higher Y = deeper in room = farther from camera.
  - View-To-Entrance: lower Y = closer to entrance = farther from camera (depth is reversed).
For every object with Y between the camera and the character, express it as occlusion:
  "[object] [surface/edge] occupies [lower/upper] [fraction] of frame;
   [character] visible from [body part] upward above [object edge]"
Append a DEPTH line to visual_disposition:
  "DEPTH: [nearest to camera] → [mid-ground] → [background]"
If anchor_points zones include visual_disposition_hint_to_entrance and the panel uses
a To-Entrance view, use that hint as the starting point for visual_disposition and extend
with character-specific anchor assignments. Never omit the depth chain when furniture is
between the camera and the subject.

SCENE PANELS:
{json.dumps(panels_context, ensure_ascii=False, indent=2)}

Return a JSON array: [{{"panel_index": N, "visual_disposition": "...", "swap_view": false, "swap_view_reason": "..."}}, ...]
Set swap_view=true only for panels where the view must be flipped (see VIEW VALIDATION above).
swap_view_reason is required for every panel."""

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
            swapped += 1
            reason = swap_reasons.get(idx, '')
            logger.info(f"      🔄 Panel {idx}: view swapped {old_refs} → {new_refs}"
                        + (f" [{reason}]" if reason else ""))

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
            for v in _puppet.SceneState(frames).validate_transitions():
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
    character_info: dict = None,
    prev_scene_terminal: str = None,
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

    scene = refine_scenes_for_episode(scene, prompts, config, llm, character_info, prev_scene_terminal)
    scene = apply_reversal_pass(scene, prompts, config, llm)
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
      analyze → refine → reversal → write checkpoint per episode.
    Returns all_scenes (list of refined scene dicts, mutated in place by process_single_scene).

    With resume=True and a ProjectState, episodes whose refined checkpoint is already
    marked done are loaded from disk instead of re-running the LLM pipeline.
    """
    all_episodes: list = []
    continuity_map = _build_continuity_map(episodes_list)
    for ep in episodes:
        ep_id = ep['episode_id']
        # Phase 1 skip: raw analysis already done — load raw checkpoint
        if resume and state and state.episode_raw_done(ep_id):
            raw_path = output_dir / f"animation_episode_scenes_{ep_id:03d}.json"
            if raw_path.exists():
                try:
                    all_episodes.append((ep_id, json.loads(raw_path.read_text(encoding='utf-8'))))
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
        )

    ep_scenes_map: dict = {}
    scene_counter = 0
    for ep_counter, data in sorted(all_episodes, key=lambda x: x[0]):
        ep_scenes_map[ep_counter] = []
        for scene in data.get('scenes', []):
            scene_counter += 1
            ep_scenes_map[ep_counter].append((scene_counter, scene))

    all_scenes: list = []
    for ep_counter, scene_list in sorted(ep_scenes_map.items()):
        # Phase 2 skip: refined checkpoint already done — load from disk
        if resume and state and state.episode_refined_done(ep_counter):
            refined_path = output_dir / f"animation_episode_scenes_{ep_counter:03d}_refined.json"
            if refined_path.exists():
                try:
                    data = json.loads(refined_path.read_text(encoding='utf-8'))
                    all_scenes.extend(data.get('scenes', []))
                    logger.info(f"⏭  Episode {ep_counter}: refined checkpoint loaded (skipping refinement)")
                    continue
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"⚠️  Episode {ep_counter}: refined checkpoint unreadable ({exc}), re-refining")

        prev_terminal = None
        ep_refined: list = []
        for sc_id, scene in scene_list:
            refined = process_single_scene(
                ep_counter, sc_id, scene, prompts, config, llm, all_scenes,
                output_dir=output_dir, character_info=character_info,
                prev_scene_terminal=prev_terminal,
            )
            ep_refined.append(refined)
            if refined:
                last_panel = max(
                    refined.get('panels', []),
                    key=lambda p: p.get('panel_index', 0),
                    default=None,
                )
                if last_panel:
                    prev_terminal = last_panel.get('visual_end', '')
        if ep_refined:
            try:
                _write_episode_checkpoint(ep_counter, ep_refined, output_dir)
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
    max_workers: int = 10,
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
      - Phase 3 (refine/ep): skipped if state.episode_refined_done(N) → load *_refined.json
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
    validate_episode_structure(episodes_list)
    continuity_map = _build_continuity_map(episodes_list)

    # ── Phase 2: parallel raw scene analysis (per episode) ────────────────────
    batch_analyze: list = []
    for i, episode in enumerate(episodes_list):
        episode_counter = episode.get('episode_id', i + 1)
        prev_rules = continuity_map.get(episode_counter, '')
        batch_analyze.append((episode_counter, json.dumps(episode, ensure_ascii=False, indent=2), prompts, config, llm, all_episodes, character_info, prev_rules))

    failed_episodes = []
    _ep_lock = Lock()

    def _safe_analyze(args):
        ep_id = args[0]
        if resume and state and state.episode_raw_done(ep_id):
            raw_path = output_dir / f"animation_episode_scenes_{ep_id:03d}.json"
            if raw_path.exists():
                try:
                    data = json.loads(raw_path.read_text(encoding='utf-8'))
                    with _ep_lock:
                        all_episodes.append((ep_id, data))
                    logger.info(f"⏭  Episode {ep_id}: raw checkpoint loaded (skipping LLM analysis)")
                    return
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"⚠️  Episode {ep_id}: raw checkpoint unreadable ({exc}), re-analyzing")
        try:
            analyze_scenes_for_episode(*args)
        except Exception as e:
            logger.error(f"❌ Episode {args[0]} scene analysis failed: {e}")
            with _ep_lock:
                failed_episodes.append(args[0])

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_safe_analyze, batch_analyze))

    if failed_episodes:
        total = len(batch_analyze)
        logger.warning(f"⚠️  {len(failed_episodes)}/{total} episode(s) failed analysis: {failed_episodes}")
        if len(failed_episodes) >= total:
            raise RuntimeError(f"All {total} episodes failed scene analysis — aborting pipeline")

    all_episodes = sorted(all_episodes, key=lambda e: e[0])

    # Assign global scene IDs and write raw checkpoints.
    # Mark each episode raw-done only after its file is committed to disk.
    scene_counter = 0
    ep_scene_groups: dict = {}  # {episode_counter: [(scene_id, scene), ...]}

    for episode_counter, data in all_episodes:
        logger.info(f"Processing episode: {episode_counter} scene start: {scene_counter}")
        raw_path = output_dir / f"animation_episode_scenes_{episode_counter:03d}.json"
        raw_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        if state and not state.episode_raw_done(episode_counter):
            state.mark_episode_raw_done(episode_counter)
        ep_scene_groups[episode_counter] = []
        for scene in data.get('scenes', []):
            scene_counter += 1
            ep_scene_groups[episode_counter].append((scene_counter, scene))

    # ── Phase 3: parallel per-episode refinement + reversal ───────────────────
    failed_scenes = []
    _sc_lock = Lock()

    def _process_episode_scenes(ep_counter: int):
        # Skip if refined checkpoint already committed
        if resume and state and state.episode_refined_done(ep_counter):
            refined_path = output_dir / f"animation_episode_scenes_{ep_counter:03d}_refined.json"
            if refined_path.exists():
                try:
                    data = json.loads(refined_path.read_text(encoding='utf-8'))
                    with _sc_lock:
                        all_scenes.extend(data.get('scenes', []))
                    logger.info(f"⏭  Episode {ep_counter}: refined checkpoint loaded (skipping refinement)")
                    return
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(f"⚠️  Episode {ep_counter}: refined checkpoint unreadable ({exc}), re-refining")

        prev_terminal: str = None
        ep_refined: list = []
        for sc_id, scene in ep_scene_groups[ep_counter]:
            try:
                refined = process_single_scene(
                    ep_counter, sc_id, scene, prompts, config, llm,
                    all_scenes, output_dir, character_info, prev_terminal,
                )
                ep_refined.append(refined)
                if refined:
                    last_panel = max(
                        refined.get('panels', []),
                        key=lambda p: p.get('panel_index', 0),
                        default=None,
                    )
                    if last_panel:
                        prev_terminal = last_panel.get('visual_end', '')
            except Exception as e:
                logger.error(f"❌ Scene {sc_id} processing failed: {e}")
                with _sc_lock:
                    failed_scenes.append(sc_id)
        if ep_refined:
            try:
                _write_episode_checkpoint(ep_counter, ep_refined, output_dir)
                if state:
                    state.mark_episode_refined_done(ep_counter)
            except Exception as e:
                logger.warning(f"⚠️  Could not write checkpoint for episode {ep_counter}: {e}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_episode_scenes, ep_c): ep_c for ep_c in ep_scene_groups}
        for future in as_completed(futures):
            ep_c = futures[future]
            if exc := future.exception():
                logger.error(f"❌ Episode {ep_c} scene processing error: {exc}")

    if failed_scenes:
        total = scene_counter
        logger.warning(f"⚠️  {len(failed_scenes)}/{total} scene(s) failed processing: {failed_scenes}")

    all_scenes = sorted(all_scenes, key=lambda s: s['scene_id'])
    return {'scenes': all_scenes}
