"""
Screenwriter — screenplay and scene keyframe generation.

All prompts and SYSTEM_PROMPT are preserved verbatim from 01_cinematic_preroll.py.
"""
import json
import logging
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock


from lib.core.schemas import SCREENPLAY_SCHEMA, SCENE_SCHEMA, REVERSAL_SCHEMA
from lib.core.utils import DEFAULT_OUTPUT_DIR
from lib.llm.base import BaseLLM, retry_on_errors

logger = logging.getLogger(__name__)

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
- INDEPENDENCE LAW: Every panel and every episode is processed by a separate AI model with ZERO memory of any prior output. Each description must be fully self-contained. NEVER use lazy references: no "same as before", "same POV", "same framing", "same appearance", "continues from previous", "as established", "identical to panel N". Omitting implied details is a hard failure — the downstream model will hallucinate or guess wrong. Restate character appearance, location, camera angle, and lighting in EVERY panel description, verbatim if needed.
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
{"Include dialogue (≤8 words per line) and voiceover (inner monologue, Russian) for each panel." if config['dialogue']['enabled'] else ""}
{"Include caption for narrative text." if config['captions']['enabled'] else ""}
Important: all dialogues, voiceovers and texts MUST be in Russian as in original text for the consistency.

## INDEPENDENCE PROTOCOL — NON-NEGOTIABLE
Each panel is rendered by a separate image-generation model that receives ONLY that panel's text — no history, no context, no memory.
- FORBIDDEN: "same as before", "same POV", "same framing", "same appearance", "as in panel N", "continues from", "identical to", "as established".
- REQUIRED: Restate character appearance (hair, clothing, build, expression), location details, shot type, camera angle, and lighting in EVERY panel's visual_start and visual_end — even if they repeat word-for-word from the previous panel.
- Treat each panel description as the ONLY instruction the image model will ever receive for that shot.

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
- For shock/revelation panels (confrontation, twist): specify a fast zoom-in on the face in lights_and_camera and motion_prompt — "camera snap-zooms into subject's eyes over 0.5s" (Scorsese zoom technique)
- For static-camera + dynamic-subject contrast (emphasises isolation or action): note "camera locked on tripod, subject moves through frame" in lights_and_camera
- Duration ~6s per panel; motion should resolve visually but not narratively

MOTION_PROMPT PHYSICAL REALISM — the video model renders every word literally, with zero narrative context:
1. Physical movements only, no emotional language. Emotions go in voiceover/emotional_beat. Use joint angles, degrees, distances.
   WRONG: "he recoils in horror, utterly poleaxed"  RIGHT: "at 1.5s his eyes open wide, jaw drops ~2 cm, upper body leans back 10°"
2. No spectacle verbs for human actions: erupts/sprays/fountains/explodes/bursts → describe the minimal physical event.
   WRONG: "a fine spray of liquid erupts from his mouth catching the light"  RIGHT: "at 2s a small amount of liquid escapes his lips as he exhales"
3. No speed metaphors: "blurring speed", "in an instant", "lightning-fast" → use explicit timestamps and distances.
   WRONG: "her hand enters with blurring speed"  RIGHT: "at 0.5s her hand enters from the right; finger contacts screen at 0.8s"
4. Anatomically correct scale: a tear is a 2–3 mm bead on the cheek, not "rivers" or "streams". Dramatic language (ping-pong tears, vomit fountains) is caused by dramatic words in motion_prompt — remove them.
5. Before writing any phrase: ask — could the AI render this as a grotesque artifact or broken anatomy? If yes, rewrite it as a plain physical movement.

TILT REVEAL — vertical-format signature technique:
Use tilt in motion_prompt to reveal information progressively top-to-bottom or bottom-to-top.
This exploits the 9:16 frame: start on feet/hands, tilt up to reveal face; or start on face, tilt down to reveal weapon/object.
Mandatory for at least one confrontation or twist panel per scene. State tilt direction, speed (slow/fast), and what is concealed at the start.
Example: "camera starts on hands gripping a phone, slow tilt upward over 4s, arrives at subject's face — expression reveals they have read something devastating."

MICRO-EXPRESSION CLUSTER — rapid emotional escalation technique:
Plan 2–3 consecutive ECU panels (panels 3–5 escalation zone) at duration 1–2s each with transition_to_next=jump_cut between them.
Each shows the same face in a different emotion: calm → surprise → fear, or doubt → recognition → dread.
In motion_prompt, describe only the face: micro-muscle shifts, eye movement, lip compression. No camera movement — locked ECU on eyes.
The rapid succession of emotions in jump_cut rhythm creates maximum tension with minimal action.

BOKEH / SELECTIVE FOCUS — attention direction technique:
In escalation and twist panels, compose with shallow DOF to isolate a single foreground object (a ring, a phone screen, a scar, a hand).
Specify in lights_and_camera: "shallow DOF, [object] sharp in foreground, subject/background as bokeh at [distance]."
This directs the viewer's attention to a prop that carries subtext — without dialogue, the framing tells them what matters.

SHADOW & SILHOUETTE — indirect reveal technique (use in escalation/confrontation):
Show the threat, emotion, or subject through its shadow or silhouette — never directly. The hidden is more powerful than the visible.
- Shadow play: camera aimed at a lit wall or floor surface. The character appears only as a moving shadow. motion_prompt: "shadow of a hand advances slowly across sunlit wall from left, fingers splayed, reaching toward a door handle — the hand itself is never in frame."
- Silhouette: subject backlit against window light, open doorway, or fire. Pure dark shape, no features — emotion only through body posture and outline. visual_start: "silhouette of [subject] against [bright window / fire / streetlight], no facial features visible, form and posture carry all meaning."
- Shadow-object contrast: show a small, innocent object (child's toy, wedding ring, glass of wine) sharply lit while a looming shadow falls across it. The shadow implies the unseen threat.
These techniques create menace without showing it, allowing the viewer's imagination to complete the horror.

REFLECTION REVEAL — hidden truth technique (use in twist panels):
Show a character's real internal state in a reflective surface while their face performs the opposite for another character.
- Phone screen reflection: "camera frames the dark phone screen — Ruslan's eyes reflected in the glass show cold calculation while off-screen his voice sounds warm and reassuring."
- Window / mirror: character faces away, their true expression visible only in the reflection behind them.
- Liquid surface: close-up of wine, water, or rain puddle — a distorted face reflected, showing what they really feel.
motion_prompt example: "camera locks on the dark surface of a phone screen. At 2s, the reflection of Alisa's eyes appears — pupils contracted, jaw clenched — while her voice off-screen says 'I'm fine'. The reflection tells the truth."

RACK FOCUS — prop-to-face revelation (use in escalation/confrontation):
Camera static. Start with foreground object in sharp focus, subject's face as background bokeh. At the emotional peak, pull focus to the face.
The object carries the subtext; the face carries the reaction. Together they form the meaning.
motion_prompt: "camera static. At 0s, a wedding ring sits sharp in extreme foreground, the blurred face of [subject] barely visible behind it. At 3s, rack focus pulls from the ring to [subject]'s face — revealing an expression of [emotion] as the ring becomes bokeh."
Use in confrontation panels when a prop is the unspoken subject of the scene (a ring, a phone, money, a key, a weapon).

MATCH CUT — visual shape continuity (use in escalation transitions):
Plan the visual_end of one panel to share a geometric shape or motion vector with the visual_start of the next.
Concrete shape pairs to plan deliberately:
- Circular: a glass rim → a clock face → an eye iris → a tunnel end
- Vertical line: a door frame → a standing figure → a knife blade → a pillar
- Upward sweep: a hand rising → a bird launching → smoke curling → a head tilting back
- Falling diagonal: a body slumping → rain streaking glass → a torn letter falling
In motion_prompt, name the match explicitly: "visual_end: [subject]'s arm sweeps upward in an arc — MATCH CUT via upward diagonal to next panel."
MANDATORY: plan at least one match_cut transition per episode in the escalation zone (panels 3–5).

DIALOGUE: ≤8 words, delivered in CU on speaker's face. Populate both `dialogue` and sync `voiceover` for inner counterpoint.
VOICEOVER: inner monologue revealing what the image cannot show. Russian language.

SOUND DESIGN (sound_design) — required for EVERY panel:
- Capture the sonic atmosphere of this exact panel moment, separate from dialogue/voiceover.
- Plan sonic contrast deliberately: sustained silence broken by a sharp sound is more powerful than continuous noise.
- MANDATORY: at least one panel per scene must have sound_design="silence" as deliberate setup for the next panel's sonic event. Pair with transition_to_next=smash_cut on the following panel.
- For j_cut transitions: describe the next scene's audio that bleeds in ("J-cut: rain ambient from next scene starts at 5s mark").
- Examples: "silence", "low-frequency hum builds", "amplified footstep at 2s, then silence", "heartbeat rises to bass drop on cut", "glass crack at 4s, then pin-drop silence", "distant thunder, growing".

TRANSITION TO NEXT PANEL (transition_to_next):
- match_cut: plan visual_end of this panel to share a geometric shape or motion vector with visual_start of the next. In motion_prompt, explicitly name the match: "visual_end matches next panel via [circular shape / upward sweep / falling diagonal / vertical line]."
- jump_cut: intentional jarring cut — reduce duration to 2–3s. Use in escalation bursts and micro-expression clusters for beat-synced pace.
- smash_cut: maximum contrast — silence cuts to noise, stillness cuts to chaos, or vice versa. Capture contrast in sound_design.
- j_cut: next panel's audio begins audibly 1–2s before the visual cut. Describe the audio in sound_design.
- hard_cut: standard clean cut (default).

PANEL TYPE (panel_type):
- narrative: standard story panel.
- atmosphere_insert: MANDATORY — exactly one per episode, at panel 7 or 8 (emotional peak / pre-cliffhanger). A single minimalist WOW shot with no dialogue, no character close-ups. Two subtypes:
  * ENVIRONMENTAL: 1–2 macro-scale elements only (crashing wave, wall of flame, fog swallowing a city, storm wall, lone tree in wind). Grand scale, 2–3 color palette. visual_start: "minimalism: [element], [light condition], hyper-realistic. No people, no faces." No character refs needed.
  * TEXTURE/DETAIL: extreme macro of a single physical surface — cracked concrete, condensation on cold glass, a scar, a burning letter, fabric under tension. Reveals what the story is made of. Shallow DOF, single element, fills the frame.
  Duration 3–4s. Transition in via smash_cut or match_cut; transition out via smash_cut or match_cut.
  The voiceover or sound from the surrounding panels spills over this image — the abstract visual amplifies the emotion without explaining it.

**IMPORTANT: EACH SCENE MUST HAVE EXACTLY 9 PANELS following the structure above.**

SCENE-LEVEL CAMERA AND LIGHTING MASTER:
For every scene, generate:
- camera_master: one sentence capturing the dominant lens (mm), angle, and primary lighting condition shared by all panels in this scene.
- lighting_master: one sentence capturing key light direction/color/quality, fill ratio, and any visible practicals. All panels must stay within this lighting DNA — deviations must be noted in that panel's lights_and_camera.
    """
    return prompt


# ---------------------------------------------------------------------------
# Episode-level screenplay — verbatim from 01_cinematic_preroll.py:529-592
# ---------------------------------------------------------------------------
def analyze_episodes_master(text: str, prompts: dict, config: dict, llm: BaseLLM) -> dict:
    logger.info("\n🎥 MASTER SCREENWRITER: Preparing screenplay...")
    setting_context = prompts.get('setting', '')
    episodes_count = config.get('episodes_count', 3)
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

**Cold Open = Visual Question Mark:** The cold_open is NOT just an arresting image — it is an unanswered question.
Show CONSEQUENCE before CAUSE: the reaction before the stimulus, the wound before the weapon, the running before the threat.
The viewer must be asking "what happened?" or "what is about to happen?" — that unresolved tension is the hook.
Never open on exposition, establishing shot, or character introduction. Open on a fragment that demands completion.

**Micro-Act Structure (per episode, 9 panels):**
- Panels 1–2: HOOK + CONTEXT. Drop into chaos, then orient.
- Panels 3–5: ESCALATION. Pressure compounds. Each panel adds a new obstacle or revelation.
- Panels 6–7: CONFRONTATION / PEAK. Maximum interpersonal or physical conflict. Face in extreme close-up.
- Panel 8: TWIST / REVERSAL. One piece of information changes everything.
- Panel 9: CLIFFHANGER. Freeze on maximum tension. Cut. Never resolve.

**Shot Scale Rhythm:** Prevent monotony by alternating scale across panels.
After 2–3 consecutive ECU/CU panels, insert one MS or WIDE to re-establish spatial context before the next escalation.
Note the intended shot scale (ECU / CU / MS / WIDE) for each panel position in screenplay_instructions.

**Dialogue Contract:** Max 8 words per line. People interrupt. People go silent. Silence is dialogue.
**Voiceover Contract:** Inner monologue or sparse narrator. Synced to visual. Reveals subtext (fear, memory, desire) — never describes what we see.

**Sonic Arc — plan the episode's sound journey in screenplay_instructions:**
Map explicitly where silence lives, where the sonic hit lands, and where the crescendo peaks. Example structure:
"Panels 1–3: low ambient hum, tension. Panel 4: sudden silence. Panel 5: sharp crack on cut. Panels 6–7: music crescendo. Panel 8: drop to silence. Panel 9: single heartbeat, then cut."
Silence is more powerful than noise. One sonic hit after sustained silence is worth ten continuous sound events.

**Visual Motif — seed and pay off across episodes:**
In episode 1, establish at least one recurring visual element: a specific object, gesture, framing, or color.
Record it in visual_continuity_rules as "MOTIF: [description]" and call it back at the climax episode — same framing, transformed meaning.
Example: a character grips a glass in episode 1 (nervous energy) → the same grip in episode 3 (controlled rage).

**Cliffhanger = Rewatch Hook, not Summary:**
The final panel must not resolve or summarise — it must leave one visible element unexplained with two possible interpretations.
The viewer rewinds because the image contains information they missed, not because they were told it was tense.
Example: a face in extreme close-up showing an emotion that contradicts what just happened. The contradiction is the hook.

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
4. Add continuity rules for episodes, e.g. if in episode 3 hero puts on spacesuit, it should be noted in next episodes (4, 5, etc) until he takes it off.
5. Episodes will be split for animation independently, so should have enough context.
6. Cover the full story from beginning to end. Use exactly {episodes_count} episodes of 30–50 seconds, so that the final cut version will fit 2 minute Shorts format.
7. Episode 1 panel 1 MUST be a cold_open — consequence before cause, visual question mark, no exposition.
8. Mark hook_type for the cold_open panel, emotional peak panel, and cliffhanger panel in screenplay_instructions.
9. Every episode MUST end on a cliffhanger or revelation — never on resolution.
10. In screenplay_instructions, include the episode sonic arc: name exactly where silence lives, where the sonic hit lands, and what the crescendo moment is.
11. In visual_continuity_rules, tag any visual motif established in this episode with "MOTIF:" prefix so downstream episodes can call it back deliberately.
12. Note intended shot scale (ECU / CU / MS / WIDE) for each panel position in screenplay_instructions to enforce scale rhythm.

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
    prev_continuity_rules: str = None,
):
    logger.info(f"\n🎥 MASTER CINEMATOGRAPHER: Preparing Keyframes for episode {episode_counter}...")
    base_prompt = base_scene_prompt(prompts, config, character_info)

    # Extract current episode's own continuity rules (for downstream episodes) and surface prev ones
    try:
        episode_data = json.loads(text)
        current_continuity = episode_data.get('visual_continuity_rules', '')
    except (json.JSONDecodeError, AttributeError):
        current_continuity = ''

    continuity_block = ""
    if prev_continuity_rules:
        continuity_block += f"\n## VISUAL CONTINUITY FROM PREVIOUS EPISODE — MANDATORY\nThese rules MUST be enforced in every panel of this episode:\n{prev_continuity_rules}\n"
    if current_continuity:
        continuity_block += f"\n## THIS EPISODE'S VISUAL STATE (carry forward to future scenes)\n{current_continuity}\n"

    prompt = f"""
    {base_prompt}
    {continuity_block}
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
       without being present in visual_start (Grok Imagine has no image-reference support).
    4. Enforces cross-panel spatial continuity and cross-scene entry state.
    5. Verifies 9-panel emotional arc integrity.
    6. Enforces camera_master/lighting_master compliance across all panels.
    """
    scene_id = scene.get('scene_id', '?')
    logger.info(f"    ✏️  Refinement pass: scene {scene_id}")

    base_prompt = base_scene_prompt(prompts, config, character_info)
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

**IMPORTANT: ADJUST CAMERA AND DYNAMICS TO SCENE NEEDS FOR IMMERSIVE VERTICAL VIEW**

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

### RULE 3 — is_reversed FLAG FOR GROK IMAGINE
Panels will be animated as 6-second clips by Grok Imagine, which does NOT support image references.
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

### RULE 6 — EMOTIONAL ARC INTEGRITY
Verify and enforce the 9-panel arc structure. Do NOT allow resolution before panel 9:
  Panel 1: cold_open | Panel 2: context | Panels 3–5: escalation
  Panel 6: confrontation | Panel 7: peak | Panel 8: twist | Panel 9: cliffhanger
Each panel's emotional_beat and hook_type must align with its position in the arc.

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
    for ep in episodes:
        ep_id = ep['episode_id']
        idx = next((i for i, e in enumerate(episodes_list) if e['episode_id'] == ep_id), -1)
        prev_rules = episodes_list[idx - 1].get('visual_continuity_rules', '') if idx > 0 else ''
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

    episodes = analyze_episodes_master(text, prompts, config, llm)
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

    # Pass each episode the previous episode's visual_continuity_rules
    episodes_list = episodes.get('episodes', [])
    for i, episode in enumerate(episodes_list):
        episode_counter = episode.get('episode_id', i + 1)
        prev_rules = episodes_list[i - 1].get('visual_continuity_rules', '') if i > 0 else ''
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
