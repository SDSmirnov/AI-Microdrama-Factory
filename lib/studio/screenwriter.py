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


from lib.core.schemas import SCREENPLAY_SCHEMA, SCENE_SCHEMA, REVERSAL_SCHEMA
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
        char_refs_block = "CHARACTER/LOCATION REFERENCES (use these exact descriptions for visual consistency):\n" + "\n".join(lines)
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
Important: all dialogues, voiceovers and texts MUST be in Russian as in original text for the consistency.

{prompts.get('screenplay_scene', '')}
    """
    return prompt


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
        f'7. TRANSITION EPISODES (episode_type: "transition"): When a significant time gap (>{gap_threshold}) exists between chapters, insert one Transition episode BEFORE the POV-A episode of the next chapter. Transitions bridge the gap using {transition_style} technique — parallel images from each character\'s space during the time gap (e.g. both characters\' environments at dawn, rain on two different windows). Rules: no dialogue, no voiceover, all panels are atmosphere_insert, panel durations 2–3s. pov_character: "". Episode must still have {panels_per_scene} panels.'
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
    arc_duration_map = {2: '~54s', 3: '~81s'}
    arc_duration = arc_duration_map.get(episodes_count, f'~{episodes_count * 27}s')
    episodes_rules = (
        episodes_rules
        .replace('__EPISODES_COUNT__', str(episodes_count))
        .replace('__ARC_PANELS__', str(arc_panels))
        .replace('__ARC_DURATION__', arc_duration)
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
            "CHARACTER/LOCATION REFERENCES — use these EXACT descriptions in visual_continuity_rules "
            "and screenplay_instructions to prevent hallucination:\n" + "\n".join(lines)
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
    if episode_type == 'confrontation':
        return prompts.get('episode_type_confrontation', '')
    if episode_type == 'transition':
        panel_duration = str(config['format'].get('panel_duration_s', 6))
        tmpl = prompts.get('episode_type_transition', '')
        return tmpl.replace('{{PANEL_DURATION}}', panel_duration)
    if episode_type in ('arc_open', 'arc_mid', 'arc_close'):
        return prompts.get(f'episode_type_{episode_type}', '')
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

### RULE 1 — SELF-CONTAINED PANELS
Each panel will be rendered INDEPENDENTLY — no pipeline shares context between panels.
Therefore every panel MUST contain all required visual information inline:
- Repeat the character's full visual appearance in visual_start and visual_end (hair, clothing, build,
  distinguishing features) — NEVER write "same appearance as before" or "continues from panel N".
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
Example: "MEDIUM SHOT. Ivan (30s, dark stubble, grey hoodie) stands LEFT of frame, facing RIGHT toward
camera at 45°, arms crossed, jaw tight. Behind him: rain-streaked window, blurred city lights bokeh."

### RULE 3 — is_reversed FLAG FOR ANIMATION
Panels will be animated as {config['format'].get('panel_duration_s', 6)}-second clips by the AI video model, which does NOT support image references.
The only way to show a character or object ENTERING the frame is reverse playback:
render the character LEAVING, then play the clip reversed.

Set is_reversed=true for any panel where:
- A character enters the scene, walks in, or appears from off-screen.
- An object comes into view (door opens revealing someone, fog clears to show a figure, etc.).
- Someone approaches the camera from a distance.
- visual_end shows a presence that is ABSENT in visual_start.
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

The following panels in this scene require REVERSE REVEAL animation:
the action was originally written in chronological order, but the AI Image-To-Video must generate reversed clip.
  - visual_start = what the camera sees at t=0  (the obscured / empty / hidden state)
  - visual_end   = what the camera sees at the end (the fully revealed state)

Your job: write motion_prompt_reversed describing how the scene transitions
FROM visual_end TO visual_start. This will be initially rendered as a forward-playing clip,
then REVERSED during post-processing so the viewer sees visual_start → visual_end.
It must be viewed closer to natural when replayed backwards,
e.g. if person walks in room from the open door, then "motion_prompt_reversed" should be like
"Jack goes backwards to the open door and then closes the door, all time facing camera".

Rules:
- The motion must be physically plausible as a forward-playing clip.
- Duration: {config['format'].get('panel_duration_s', 6)} seconds total.
- Use timestamps (e.g. "At 2 seconds…") for clarity.
- Be very detailed (100+ words). The AI video model needs precision.
- Do NOT invent new elements — only describe the transition between the two provided states.
- Preserve all lighting and camera details from lights_and_camera.
- Output ONLY a JSON array with the same panel_index values. Each object must have
  exactly two keys: "panel_index" (integer) and "motion_prompt_reversed" (string).

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
        reversed_map = {item['panel_index']: item['motion_prompt_reversed'] for item in items}
        for p in scene.get('panels', []):
            if p.get('is_reversed', False) and p['panel_index'] in reversed_map:
                p['motion_prompt_original'] = p['motion_prompt']
                p['motion_prompt'] = reversed_map[p['panel_index']]
                original_start = p['visual_start']
                original_end   = p['visual_end']
                p['visual_start'] = original_end
                p['visual_end']   = original_start
                logger.info(f"      ✅ Panel {p['panel_index']}: motion_prompt_reversed generated")
            elif p.get('is_reversed', False):
                logger.info(f"      ⚠️  Panel {p['panel_index']}: no motion_prompt_reversed returned by LLM")
    else:
        logger.error(f"      ❌ Reversal LLM call returned empty for scene {scene.get('scene_id', '?')}")

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
        panel.setdefault('voiceover', '')
        panel.setdefault('emotional_beat', '')
        panel.setdefault('hook_type', 'none')
        panel.setdefault('text_safe_composition', True)
        panel.setdefault('panel_type', 'narrative')
        panel.setdefault('transition_to_next', 'hard_cut')
        panel.setdefault('sound_design', 'silence')
        panel.setdefault('location_references', [])

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
) -> list:
    """
    Process a filtered list of episodes sequentially:
      analyze → refine → reversal → write checkpoint per episode.
    Returns all_scenes (list of refined scene dicts, mutated in place by process_single_scene).
    """
    all_episodes: list = []
    continuity_map = _build_continuity_map(episodes_list)
    for ep in episodes:
        ep_id = ep['episode_id']
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
) -> dict:
    """
    Full pipeline: episodes → scenes → reversal → save JSONs.
    Returns {'scenes': [...]}.
    """
    output_dir = output_dir or DEFAULT_OUTPUT_DIR

    episodes = analyze_episodes_master(text, prompts, config, llm, character_info=character_info)
    if not episodes:
        raise RuntimeError(
            "analyze_episodes_master returned None or empty — check LLM response and API key"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "animation_episodes.json").write_text(
        json.dumps(episodes, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    logger.debug(episodes)

    all_scenes: list = []
    batch_analyze: list = []
    all_episodes: list = []

    episodes_list = episodes.get('episodes', [])
    validate_episode_structure(episodes_list)
    continuity_map = _build_continuity_map(episodes_list)

    for i, episode in enumerate(episodes_list):
        episode_counter = episode.get('episode_id', i + 1)
        prev_rules = continuity_map.get(episode_counter, '')
        batch_analyze.append((episode_counter, json.dumps(episode, ensure_ascii=False, indent=2), prompts, config, llm, all_episodes, character_info, prev_rules))

    failed_episodes = []
    _ep_lock = Lock()

    def _safe_analyze(args):
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

    # Assign global scene IDs and group by episode for sequential per-episode refinement.
    # Scenes within an episode are processed sequentially so the terminal visual_end of
    # scene N can be passed as spatial anchor into scene N+1's refinement pass.
    # Different episodes are still refined in parallel.
    scene_counter = 0
    ep_scene_groups: dict = {}  # {episode_counter: [(scene_id, scene), ...]}

    for episode_counter, data in all_episodes:
        logger.info(f"Processing episode: {episode_counter} scene start: {scene_counter}")
        (output_dir / f"animation_episode_scenes_{episode_counter:03d}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )
        ep_scene_groups[episode_counter] = []
        for scene in data.get('scenes', []):
            scene_counter += 1
            ep_scene_groups[episode_counter].append((scene_counter, scene))

    failed_scenes = []
    _sc_lock = Lock()

    def _process_episode_scenes(ep_counter: int):
        prev_terminal: str = None
        ep_refined: list = []
        for sc_id, scene in ep_scene_groups[ep_counter]:
            try:
                refined = process_single_scene(
                    ep_counter, sc_id, scene, prompts, config, llm,
                    all_scenes, output_dir, character_info, prev_terminal,
                )
                ep_refined.append(refined)
                # Thread the terminal frame into the next scene's refinement
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
        # Write checkpoint with ALL scenes for this episode (not per-scene overwrite)
        if ep_refined:
            try:
                _write_episode_checkpoint(ep_counter, ep_refined, output_dir)
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
