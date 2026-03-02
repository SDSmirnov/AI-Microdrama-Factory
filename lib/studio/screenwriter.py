"""
Screenwriter — screenplay and scene keyframe generation.

All prompts and SYSTEM_PROMPT are preserved verbatim from 01_cinematic_preroll.py.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from lib.core.schemas import SCREENPLAY_SCHEMA, SCENE_SCHEMA, REVERSAL_SCHEMA
from lib.llm.base import BaseLLM, retry_on_errors

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "cinematic_render"

# ---------------------------------------------------------------------------
# SYSTEM PROMPT — verbatim from 01_cinematic_preroll.py:284-332
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """
# CONTEXT: We produce VERTICAL MICRODRAMA for TikTok/Reels/Shorts (9:16 portrait).
# Each scene = 9 panels × ~6s raw = 54s footage → ~30–45s after edit. Violence and hard dramatic content allowed (fictional source).
# GOAL: Generate production-ready assets for AI Image-To-Video pipeline. Every panel must carry dramatic weight — no filler.

## CONSTRAINTS
- You prepare assets for AI-based tools, be very specific in details
- You follow best practices in visual storytelling and cinematography
- PORTRAIT FRAME LAW: All compositions are 9:16. Faces and close-ups are the primary dramatic instrument. Wide shots exist only when the environment IS the threat or the scale IS the emotion.
- SAFE ZONE: Key action must stay in the middle 65% of frame height. Top 15% and bottom 20% reserved for subtitles/UI.
- VOICEOVER IS THE SPINE: Every panel has either dialogue or voiceover. Inner monologue reveals what the image cannot show. Never narrates the obvious.
- DIALOGUE IS PERFORMANCE: ≤8 words per line. Staccato. Emotionally specific. Delivered in close-up on the speaker's face.
- HOOK ARCHITECTURE: Panel 1 of every episode = cold_open (most arresting image, zero context). Emotional peak before midpoint. Final panel = cliffhanger or revelation.

## RESPONSE PROTOCOLS

### THE "NITPICKER" VERIFICATION PROTOCOL

Before delivering the result, you must run the text through an internal filter using the following checkpoints (and output this block at the end):

1. WHAT THE FUCK? (Logic/Data) — Check the physics of the world, magical assumptions, absence of character action validation.
* *Solution:* Fix plot holes, add justification for technologies/motives.

2. WHY THE FUCK? (Purpose) — Why does this scene exist? Is its complexity justified? Does it serve the plot or is it "filler"?
* *Solution:* Simplify or deepen the conflict.

3. ON WHAT GROUNDS? (Contract/Boundaries) — Are the limits of the heroes' powers respected, the setting rules followed, and genre laws obeyed?
* *Solution:* Impose constraints, add consequences for breaking rules.

4. FUCK THAT (Realism/Errors) — Is everything too easy? Are there any deus ex machinas? Where's the handling of "errors" (heroes' failures)?
* *Solution:* Add timeouts, failures, plan breakdowns.

The "It's Crap, Redo It" Protocol
Instructions: You must adhere to the following iterative quality control process for every response:

1. Ruthless Audit: Analyze your initial draft. Explicitly identify why it is "crap" (e.g., generic, hallucinated, shallow, or lazy). List every flaw.

2. Iterate: Rewrite the response to address the flaws. Audit it again. Why is it still "crap"?

3. Refine: Produce a superior version. Scrutinize it one last time for any remaining weakness.

4. Finalize: Eliminate all issues and present only the definitive, high-quality final answer.

Command: Use the "It's Crap, Redo It" Protocol to generate a perfect, comprehensive response to the following request.

## CRITICAL:
- Always apply described "The Nitpicker" and "It's Crap, Redo It" protocols for every response

"""


# ---------------------------------------------------------------------------
# base_scene_prompt — verbatim from 01_cinematic_preroll.py:468-525
# ---------------------------------------------------------------------------
def base_scene_prompt(prompts: dict, config: dict, character_info: dict = None) -> str:
    scenery_template = prompts.get('scenery', '')
    setting_context = prompts.get('setting', '')
    panels_per_scene = config['format']['panels_per_scene']
    is_animation = config['animation']['enabled']

    known_refs = list((character_info or {}).keys())

    prompt = f"""
{scenery_template}

{setting_context}

CONTEXT:
Available Characters/Locations/Objects for panel references: {known_refs}
Panels per scene: {panels_per_scene}
Animation mode: {is_animation}

{"Include visual_start and visual_end for START/END keyframes." if is_animation else "Include single key visual moment per panel."}
{"Include dialogue (≤8 words per line) and voiceover (inner monologue, Russian) for each panel." if config['dialogue']['enabled'] else ""}
{"Include caption for narrative text." if config['captions']['enabled'] else ""}
Important: all dialogues, voiceovers and texts MUST be in Russian as in original text for the consistency.

## VERTICAL MICRODRAMA CINEMATOGRAPHY — 9 PANELS PER SCENE

**PORTRAIT FRAME (9:16). Every decision is made for a phone screen held vertically.**

FRAMING HIERARCHY:
- ECU (Extreme Close-Up): eyes, hands, objects — for peak emotional moments
- CU (Close-Up): face from chin to forehead — default for dialogue and reaction
- MS (Medium Shot): chest up — confrontation, spatial relationship between characters
- WIDE: only when the environment is the dramatic agent (threat, scale, isolation)

SAFE ZONE RULE: Compose all key subjects within the middle 65% of frame height.
Top 15% and bottom 20% must be visually clear (sky, wall, floor — no faces, no action).
Set text_safe_composition: true when this is achieved.

9-PANEL MICRO-ACT STRUCTURE (mandatory rhythm):
- Panel 1: cold_open — most arresting image, zero context, maximum tension or beauty
- Panel 2: context — orient viewer: who, where, what's at stake (compressed, no exposition dumps)
- Panel 3: escalation — first pressure or obstacle
- Panel 4: escalation — complication, stakes raised
- Panel 5: escalation — point of no return
- Panel 6: confrontation — peak conflict, ECU on face
- Panel 7: peak — maximum emotional intensity, the scene's fulcrum
- Panel 8: twist — one fact changes everything
- Panel 9: cliffhanger — freeze on maximum unresolved tension

MOTION PROMPTS for vertical format:
- Prefer vertical camera movements: tilt up/down, vertical dolly, snap zoom into eyes
- Match motion intensity to emotional_beat (dread = slow creep, shock = snap cut energy, rage = handheld shake)
- Duration ~6s per panel; motion should resolve visually but not narratively

DIALOGUE: ≤8 words, delivered in CU on speaker's face. Populate both `dialogue` and sync `voiceover` for inner counterpoint.
VOICEOVER: inner monologue revealing what the image cannot show. Russian language.

**IMPORTANT: EACH SCENE MUST HAVE EXACTLY 9 PANELS following the structure above.**
    """
    return prompt


# ---------------------------------------------------------------------------
# Episode-level screenplay — verbatim from 01_cinematic_preroll.py:529-592
# ---------------------------------------------------------------------------
def analyze_episodes_master(text: str, prompts: dict, config: dict, llm: BaseLLM) -> dict:
    logger.info("\n🎥 MASTER SCREENWRITER: Preparing screenplay...")
    setting_context = prompts.get('setting', '')
    prompt = f"""
# Role: MASTER SCREENWRITER — VERTICAL MICRODRAMA (PROD-SPEC)

You are a master screenwriter specializing in VERTICAL MICRODRAMA — the native dramatic form of TikTok, Reels, and Shorts.
You think in portrait frames. You write for a viewer holding a phone in one hand, thumb ready to scroll.
You have 3 seconds to hook them. You have 45 seconds to wreck them emotionally. You have one frame to make them stay.
You don't write synopses. You write action, sound, and light.
We film great viral vertical microdramas.

## VERTICAL MICRODRAMA DRAMATURGY

**The 3-Second Law:** Episode opens in medias res — the most visually arresting moment, zero explanation.
The viewer asks "what is happening?" THAT question keeps them watching.

**Micro-Act Structure (per episode, 9 panels):**
- Panels 1–2: HOOK + CONTEXT. Drop into chaos, then orient.
- Panels 3–5: ESCALATION. Pressure compounds. Each panel adds a new obstacle or revelation.
- Panels 6–7: CONFRONTATION / PEAK. Maximum interpersonal or physical conflict. Face in extreme close-up.
- Panel 8: TWIST / REVERSAL. One piece of information changes everything.
- Panel 9: CLIFFHANGER. Freeze on maximum tension. Cut. Never resolve.

**Dialogue Contract:** Max 8 words per line. People interrupt. People go silent. Silence is dialogue.
**Voiceover Contract:** Inner monologue or sparse narrator. Synced to visual. Reveals subtext (fear, memory, desire) — never describes what we see.
**Sound Design:** Include sonic cues in screenplay_instructions ("heartbeat rises", "pin-drop silence", "bass drop on cut"). These drive motion prompt pacing downstream.
**Continuity of Tension:** Each episode ends mid-breath. The cliffhanger is not a summary — it is a question mark with a face.

## GOLDEN RULES OF TEXT

* **Show, Don't Tell:** Instead of "he got angry," write: "Gelsen grips the glass so hard his knuckles turn white. A crack creeps across the glass."
* **1:1 Density:** 1 page of screenplay = 1 minute of screen time. No condensed summaries.
* **Bullet Dialogue:** ≤8 words. Staccato. Subtext-laden. Cut before resolution.
* **Technical Block:** Each scene begins with a slug line: `INT/EXT. LOCATION — TIME OF DAY`
* **Portrait Slug:** Add framing note after slug: `[VERTICAL — ECU / CU / MS / WIDE]`

## RESPONSE STRUCTURE

1. **Title and Logline.**
2. **Character List** (with brief psychological profiles and visual details).
3. **Screenplay** (broken down by scenes with dialogue and stage directions).
4. **"NITPICKER" Protocol Report** (Quote → Complaint → Solution).

LAUNCH INSTRUCTION: deliver text that makes the cinematographer itch to grab a camera.

1. Quote raw narrative text verbatim for the context, do not shorten.
2. Screenplay instructions will be used to generate cinematic prerolls for AI-driven animation. Be very direct and verbose.
3. Each episode should cover from 30 to 50 seconds of real-time action.
5. Add continuity rules for episodes, e.g. if in episode 3 hero puts on spacesuit, it should be noted in next episodes (4, 5, etc) until he takes it off.
6. Episodes will be split for animation independently, so should have enough context.
7. Cover the full story from beginning to end. Use exactly 3 episodes of 30–50 seconds, so that the final cut version will fit 2 minute Shorts format.
8. Episode 1 panel 1 MUST be a cold_open — in medias res, maximum visual impact, no exposition.
9. Mark hook_type for the cold_open panel, emotional peak panel, and cliffhanger panel in screenplay_instructions.
10. Every episode MUST end on a cliffhanger or revelation — never on resolution.

{setting_context}

Respond in specified JSON format.

TEXT TO ADAPT:
<STORY>{text}</STORY>
"""
    return llm.make_json(prompt, SCREENPLAY_SCHEMA)


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
):
    logger.info(f"\n🎥 MASTER CINEMATOGRAPHER: Preparing Keyframes for episode {episode_counter}...")
    base_prompt = base_scene_prompt(prompts, config, character_info)
    prompt = f"""
    {base_prompt}

    TEXT TO ADAPT:
    {text}
"""
    result = llm.make_json(prompt, SCENE_SCHEMA)
    if not result or 'scenes' not in result:
        logger.error(f"❌ Empty scene result for episode {episode_counter}")
    all_episodes.append((episode_counter, result or {}))
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

    prompt = f"""
You are a Master Cinematographer writing motion prompts for AI video generation.

The following panels in this scene require REVERSE REVEAL animation:
the action was originally written in chronological order, but the AI Image-To-Video must generate reversed clip.
  - visual_start = what the camera sees at t=0  (the obscured / empty / hidden state)
  - visual_end   = what the camera sees at the end (the fully revealed state)

Your job: write motion_prompt_reversed describing how the scene transitions
FROM visual_end TO visual_start. This will be initially rendered as a forward-playing clip,
then REVERSED during post-processing so the viewer sees visual_start → visual_end.

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

    refine_limiter_rpm = 25

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
):
    scene['scene_id'] = scene_id
    for idx, panel in enumerate(scene.get('panels', []), 1):
        panel['panel_index'] = idx
        panel.setdefault('is_reversed', False)
        panel.setdefault('motion_prompt_reversed', '')
        panel.setdefault('voiceover', '')
        panel.setdefault('emotional_beat', '')
        panel.setdefault('hook_type', 'none')
        panel.setdefault('text_safe_composition', True)
        panel.setdefault('location_references', [])

    scene = apply_reversal_pass(scene, prompts, config, llm)
    all_scenes.append(scene)

    out_path = OUTPUT_DIR / f"animation_episode_scenes_{episode_counter:03d}_refined.json"
    out_path.write_text(
        json.dumps({'scenes': [scene]}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


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
) -> dict:
    """
    Full pipeline: episodes → scenes → reversal → save JSONs.
    Returns {'scenes': [...]}.
    """
    episodes = analyze_episodes_master(text, prompts, config, llm)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "animation_episodes.json").write_text(
        json.dumps(episodes, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    logger.info(episodes)

    all_scenes: list = []
    scene_counter = 0
    batch_refinement: list = []
    batch_analyze: list = []
    all_episodes: list = []

    for episode in episodes.get('episodes', []):
        episode_counter = episode.get('episode_id', len(batch_analyze) + 1)
        batch_analyze.append((episode_counter, json.dumps(episode, ensure_ascii=False, indent=2), prompts, config, llm, all_episodes, character_info))

    def _safe_analyze(args):
        try:
            analyze_scenes_for_episode(*args)
        except Exception as e:
            logger.error(f"❌ Episode {args[0]} scene analysis failed: {e}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_safe_analyze, batch_analyze))

    all_episodes = sorted(all_episodes, key=lambda e: e[0])

    for episode_counter, data in all_episodes:
        logger.info(f"Processing episode: {episode_counter} scene start: {scene_counter}")
        (OUTPUT_DIR / f"animation_episode_scenes_{episode_counter:03d}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

        for scene in data.get('scenes', []):
            scene_counter += 1
            batch_refinement.append((episode_counter, scene_counter, scene, prompts, config, llm, all_scenes))

    def _safe_process(args):
        try:
            process_single_scene(*args)
        except Exception as e:
            logger.error(f"❌ Scene {args[1]} processing failed: {e}")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        list(executor.map(_safe_process, batch_refinement))

    all_scenes = sorted(all_scenes, key=lambda s: s['scene_id'])
    return {'scenes': all_scenes}
