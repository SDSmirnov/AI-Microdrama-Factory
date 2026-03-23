
## SCREENPLAY_INSTRUCTIONS — YOUR PANEL-BY-PANEL BLUEPRINT

The episode JSON you receive contains a `screenplay_instructions` field with a per-panel blueprint (P1…P9).
For each panel, use its blueprint fields as **direct inputs**:
- `ACTION` → drives spatial composition and motion in `visual_start` and `motion_prompt`
- `EMOTION` → drives the primary face physics in `visual_start` and `visual_end`
- `STAKE` → must appear as a visible element in `visual_start`; use for bokeh/rack focus where noted
- `DIALOGUE SEED` → starting point for `dialogue`/`voiceover`; expand to full ≤8-word line
- `hook_type` in the bracket → set panel's `hook_type` field
- `SCALE` in the bracket → set the shot scale in `lights_and_camera`
- `LOCATION` in the bracket → set the scene location

If `screenplay_instructions` lacks a blueprint entry for a panel, infer from the `raw_narrative` and `rewritten_condensed_narrative`.

## INDEPENDENCE PROTOCOL — NON-NEGOTIABLE
Each panel is rendered by a separate image-generation model that receives ONLY that panel's text — no history, no context, no memory.
- FORBIDDEN: "same as before", "same POV", "same framing", "same appearance", "as in panel N", "continues from", "identical to", "as established".
- REQUIRED in EVERY panel's visual_start and visual_end: location details, shot type, camera angle, and lighting. Character reference images are injected separately — do NOT repeat canonical appearance (hair color, build, eye color, usual outfit). Instead, describe ONLY scene-specific deviations: costume changes ("silk robe instead of usual dress"), carried items for this scene ("holding a gun", "bag on left shoulder"), injuries or transient state ("soaked, mascara running"). Signature visual tells (scar, tattoo, prop) must be mentioned when visible at CU/ECU range.
- Treat each panel description as the ONLY instruction the image model will ever receive for that shot.
- POV CAMERA LAW: A shot described as "from [Character X]'s perspective" or "[Character X]'s POV" means the camera occupies Character X's eye position. Character X CANNOT appear anywhere in that frame. If Character X must be visible: drop the POV framing and use over-the-shoulder, reaction shot, or standard two-shot instead.

## VERTICAL CINEMATIC PHOTOGRAPHY — 9 PANELS PER SCENE

**PORTRAIT FRAME (9:16). Every decision is made for a phone screen held vertically.**

FRAMING HIERARCHY:
- ECU (Extreme Close-Up): eyes, hands, objects — for peak emotional moments
- CU (Close-Up): face from chin to forehead — default for dialogue and reaction
- MS (Medium Shot): chest up — confrontation, spatial relationship between characters
- WIDE: only when the environment is the dramatic agent (threat, scale, isolation)

ANGLE VARIETY RULE: No two consecutive panels may share the same shot scale AND the same camera angle. If P3 = CU / eye-level, then P4 must change at least one dimension: scale (ECU / MS / WIDE) OR angle (low / high / over-shoulder / oblique). Monotone shot sequences collapse rhythm.

SAFE ZONE RULE: Compose all key subjects within the middle 65% of frame height.
Top 15% and bottom 20% must be visually clear (sky, wall, floor — no faces, no action).
Set text_safe_composition: true when this is achieved.

VISUAL DRAMATIC INTENSITY — WHAT GOES IN EVERY NARRATIVE FRAME:

**visual_start must answer four questions in one image:**
1. WHO has power right now, and WHO doesn't? — Show it through spatial position (standing over / cornered), posture (open vs. closed), or a prop (who holds the phone, the contract, the weapon).
2. WHAT specific emotion is visible on the primary face? — Not "he looks angry." Write the physics: "jaw set, lips compressed, eyes tracking her hands rather than her face." The AI renders what you describe.
3. WHAT detail signals something is at stake? — A door left open, a phone face-down, hands too close together, a glass at the edge of a table. One object carries the threat without naming it.
4. IS the character's signature visual tell present? — For any CU or ECU, the character's defining prop, mark, or gesture must be explicitly described as visible, OR motion_prompt must explain why it is off-frame.

**visual_end must show a state transition with dramatic weight — not a completed action:**
- A decision made visible: the hand that finally reaches, eyes that finally meet, fingers releasing a grip.
- A boundary crossed: physical proximity breached, an object picked up or put down that shifts the dynamic.
- A contradiction revealed: the suppressed smile, the flash of real fear behind performed confidence.
- NEVER write visual_end as "the action is done." visual_end is a NEW STATE — it demands resolution in the next panel.

**motion_intent — declare BEFORE writing motion_prompt (required field):**
One sentence: what does the character want to achieve in this physical moment?
- RIGHT: "Pavel grabs her arm to stop her from leaving." / "Sofya leans back to re-establish dominance."
- WRONG: "Pavel moves toward Sofya." (describes action, not goal)
Without a declared intent, motion_prompt defaults to time-filling gestures. If you cannot state WHY the character moves, the panel has no narrative content — rewrite the panel.

**visual_start TIMING LAW:**
visual_start = the SPLIT SECOND before motion_prompt [0s] begins. Not the previous panel's outcome. Not mid-motion.
WRONG: visual_start = "He is angrily brushing foam from his jacket" — already mid-action.
RIGHT: visual_start = "He stands still, both hands hovering over his lapels, the first brush not yet begun."
EXCEPTION: scene-opening panel when action is already underway — visual_start describes the ongoing action.

**motion_prompt DEFAULT — characters move. Every panel must have visible full-body physical action:**
People walk across rooms, gesture emphatically, turn away, step closer, grab objects, push past someone, sit down hard, stand up fast. A 6-second clip is a movie clip — something must visibly happen in physical space.
WRONG: "character stands facing camera, jaw tightens, eyes shift left"
RIGHT: "At 0s Alisa strides from the door toward the table, 3 quick steps. At 3s she stops 80cm away, leans forward, plants both hands flat on the table. At 5s she locks eyes with him without breaking contact."

**MOTION BUDGET — 6 seconds is a large amount of real time. Use it:**
Plan motion_prompt as a complete physical arc that realistically takes ~6s to execute:
- 6s budget: enter a room (1s) + approach someone (1.5s) + grab their wrist (0.5s) + force them to look at you (1s) + deliver line (2s)
- NOT: "slowly, deliberately raises the phone toward his ear over 6 seconds"
If the core action takes 1s, add what happens before and after — the approach, the reaction, the consequence.

**TEMPORAL COMPRESSION LAW — when a physical action sequence takes ≤4 seconds in real life, it MUST be ONE panel:**
Never map fast sequential events 1:1 to panels. A trip-and-fall is 0.5s. A punch-and-collapse is under 2s.
WRONG: panel 2 = "running", panel 3 = "shouts over shoulder", panel 4 = "door hits face" — three panels for four seconds.
RIGHT: one panel, motion_prompt: "At 0s Pavel is mid-sprint. At 2.5s he twists back, shouts. At 4s the door swings into frame. At 4.5s contact. From 4.5s to 6s camera holds on impact."
Camera movement is the compression tool: one panel can travel from MS tracking shot → snap zoom into ECU.

**motion_prompt HESITATION — use ONLY for a single genuine decision moment (≤1 panel per scene, not in first two panels):**
Reserve for the exact instant a character faces a choice that changes everything.
Maximum 3 seconds of visible deliberation before action resolves.
HARD ENFORCEMENT: If a single gesture spans more than 3 seconds without a physical state change — HARD FAILURE.

**TABLEAU FAILURE — add to HARD ENFORCEMENT list:**
Any segment where the only visible motion is eye movement or micro-expression for ≥2 consecutive seconds = TABLEAU FAILURE.
WRONG: "From 1s to 3.5s, her eyes slowly scan his posture." RIGHT: fill with approach, turn, reach, or large-limb action.

**COMBAT/CONTACT SEQUENCES — physical impact always collapses into one clip:**
Wind-up + strike + reaction = one panel. Push + stumble, grab + spin, throw + crash = one panel.

**POST-WRITE MOTION AUDIT (run on every panel before finalizing):**
1. FREEZE CHECK: any segment ≥2s with no physical body state change → HARD FAILURE.
2. VOICE CHECK: does the panel have `dialogue` OR `voiceover`? If both empty → HARD FAILURE.
3. INTENT CHECK: does every beat in motion_prompt serve the declared `motion_intent`?
4. TIMING LAW CHECK: does `visual_start` describe the state JUST BEFORE motion_prompt [0s]?
5. COMBAT CHECK: two consecutive panels both describing the same physical impact → merge them.

## 9-PANEL NARRATIVE FLOW

Distribute the scene across 9 panels in strict chronological order of the source text.
No positions are mandated by structure — the story dictates what each panel shows.

**OPENING PANELS (P1–P2):**
Drop into the scene with the primary action already underway or just beginning.
Avoid static setup shots. P1 shows something happening, not someone waiting.
P1 duration: 3–5s. Action must be visible from frame 0.
If the scene opens mid-action (source text begins in media res), describe the ongoing action.

**MID-SCENE PANELS (P3–P7):**
Follow the action, dialogue, and emotional shifts in source order.
Vary shot scales. Place ECU at the scene's emotional peak — wherever the source puts it.
Dialogue exchanges follow the source verbatim: every spoken line in the source gets a panel.
Do not reorder or condense exchanges.

**CLOSING PANELS (P8–P9):**
End where the source ends. If the source ends quietly — end quietly.
If the source ends on an unresolved moment — end on that unresolved moment.
Do NOT invent escalation to create a more dramatic ending.
P9 reflects the natural conclusion or transition point of this scene.

HOOK TYPES — record in hook_type field:
- `scene_open`: panel that begins the scene (P1)
- `dialogue_exchange`: panels carrying back-and-forth dialogue
- `action`: physical action panels
- `revelation`: a character learns or realizes something
- `emotional_beat`: face carries the scene's emotional weight, minimal dialogue
- `scene_close`: panel that closes the scene (P9)
- `narrative`: general story beat (default)

MANDATORY: at least one ECU panel per scene for the emotional peak.
MANDATORY: at least one tilt reveal or match cut per scene (see techniques below).

SOURCE FIDELITY LAW:
You may ONLY dramatize actions, words, and events present or directly implied in the source text.
Do NOT invent actions, revelations, or escalations beyond the source — especially not at scene endings.
An invented dramatic beat that contradicts the next already-written passage breaks downstream continuity.
When the source is ambiguous, choose the most conservative dramatization.

SOURCE TEXT PHYSICS REPAIR:
Before encoding any action sequence, reconstruct the physical trajectory:
1. TRAJECTORY INTEGRITY — trace each object and body through space step by step.
2. REAL DURATION — assign each physical action its actual clock time. A fall is 0.5s. A pratfall is under 1s.
3. OBJECT PHYSICS — common objects behave predictably. A4 paper doesn't swirl; it flutters and falls in 2–3s.

MOTION PROMPTS for vertical format:
- Prefer vertical camera movements: tilt up/down, vertical dolly, snap zoom into eyes
- Match motion intensity to emotional_beat
- Duration ~6s per panel; motion should resolve visually but not necessarily narratively

MOTION_PROMPT PHYSICAL REALISM — the video model renders every word literally:
1. Physical movements only. No emotional language in motion_prompt.
   WRONG: "he recoils in horror"  RIGHT: "at 1.5s his eyes open wide, jaw drops ~2cm, upper body leans back 10°"
2. No spectacle verbs: erupts/sprays/explodes → describe the minimal physical event.
3. No speed metaphors: "blurring speed" → use explicit timestamps and distances.
4. Anatomically correct scale: a tear is a 2–3mm bead, not "rivers".
5. ITEM ORIGIN — every retrieved object must come from a physically real place:
   "right hand moves to shoulder holster, draws pistol" — NEVER "pulls out a gun".

TILT REVEAL — vertical-format signature technique:
Use tilt in motion_prompt to reveal information progressively top-to-bottom or bottom-to-top.
Mandatory for at least one panel per scene. State tilt direction, speed, and what is concealed at start.

MICRO-EXPRESSION CLUSTER — rapid emotional escalation technique:
Plan 2–3 consecutive ECU panels in the emotional peak zone, 1–2s each with transition_to_next=jump_cut.
Each shows the same face in a different emotion: calm → surprise → fear.
In motion_prompt, describe only the face: micro-muscle shifts, eye movement, lip compression. No camera movement.

BOKEH / SELECTIVE FOCUS — attention direction technique:
In peak panels, compose with shallow DOF to isolate a single foreground object.
Specify in lights_and_camera: "shallow DOF, [object] sharp in foreground, subject as bokeh at [distance]."

SHADOW & SILHOUETTE — indirect reveal technique:
Show the threat, emotion, or subject through its shadow or silhouette — never directly.
Silhouette: subject backlit against window light, open doorway, or fire.
Shadow-object contrast: show a small innocent object sharply lit while a looming shadow falls across it.

REFLECTION REVEAL — hidden truth technique:
Show a character's real internal state in a reflective surface while their face performs the opposite.
"camera frames the dark phone screen — eyes reflected in glass show cold calculation while voice sounds warm."

RACK FOCUS — prop-to-face revelation:
Camera static. Start with foreground object sharp, subject's face as bokeh. At emotional peak, pull focus to face.

MATCH CUT — visual shape continuity:
Plan visual_end of one panel to share a geometric shape or motion vector with visual_start of the next.
Concrete pairs: circular (glass rim → clock face → eye iris), vertical line (door frame → standing figure → knife blade),
upward sweep (hand rising → bird launching → smoke), falling diagonal (body slumping → rain on glass).
MANDATORY: plan at least one match_cut transition per scene.

VOICE BUDGET (hard technical limit): 24 characters per second × panel duration = max characters for dialogue + voiceover COMBINED.
6s panel = 144 chars total. 4s panel = 96 chars total. Exceeding causes TTS truncation.

MANDATORY VOICE COVERAGE — HARD RULE:
Every panel MUST have either `dialogue` OR `voiceover` populated. HARD FAILURE if both are empty.

DIALOGUE: ≤8 words, delivered in CU on speaker's face. Populate both `dialogue` and sync `voiceover` for inner counterpoint.
VOICEOVER: inner monologue only — no voice/gender prefix. {target_language} language. HARD LIMIT: 4–5 words for emotional_beat panels.
`voiceover_settings` — required alongside every non-empty voiceover. Set: gender, actor, age, tone.

DIALOGUE EXCHANGE CONTINUITY — HARD RULE:
Any line of dialogue that is a direct question, demand, or statement addressed to a specific person MUST receive its verbal response within the same panel OR the immediately following panel.

HOW TO HANDLE MULTI-TURN EXCHANGES:
1. SHORT EXCHANGE (≤2 turns, total ≤80 chars): pack both sides into one panel's `dialogue` field.
   Format: `"Speaker1 (voice): Line1\nSpeaker2 (voice): Line2"`
2. LONGER EXCHANGE (3–4 turns): allocate consecutive panels, one turn per panel.
3. REVELATION EXCHANGE: include both the trigger question and the answer in one panel.

CAPTION CONTRACT (caption field — required for EVERY panel):
`caption` is a persistent bottom-third text overlay. It is a HOOK, not a summary.
Rules: ≤40 characters. NEVER narrates the visible action. Delivers emotional punch or subtext.
RIGHT: "Thirty-one nights. One cracked screen." / "She laughed. With someone else."

sound_design=silence CLARIFICATION: means ambient/music/SFX channels are zeroed. Voiceover TTS plays independently.
NEVER write "complete silence" when a voiceover is present.

SOUND DESIGN (sound_design) — required for EVERY panel:
Capture the sonic atmosphere of this exact panel moment, separate from dialogue/voiceover.
Plan sonic contrast: sustained silence broken by a sharp sound is more powerful than continuous noise.

TRANSITION TO NEXT PANEL (transition_to_next):
- match_cut: visual_end shares a geometric shape or motion vector with next panel's visual_start.
- jump_cut: intentional jarring cut — reduce duration to 2–3s. Use in action bursts and rapid exchange.
- smash_cut: maximum contrast — silence cuts to noise, stillness to chaos.
- j_cut: next panel's audio begins 1–2s before the visual cut.
- hard_cut: standard clean cut (default).

PANEL TYPE (panel_type):
- narrative: the only valid value. Every panel shows characters in action — faces, hands, relationships.

**IMPORTANT: EACH SCENE MUST HAVE EXACTLY 9 PANELS.**

SCENE-LEVEL CAMERA AND LIGHTING MASTER:
For every scene, generate:
- camera_master: one sentence capturing the dominant lens (mm), angle, and primary lighting condition shared by all panels.
- lighting_master: one sentence capturing key light direction/color/quality, fill ratio, and any visible practicals.

LOCATION REFERENCE NAMING — populate location_references per panel using EXACT split view names:
- Room refs are split into two views. Choose based on WHERE THE CAMERA IS POSITIONED:
  - `{Room-Name}-View-From-Entrance` — camera at/near the entrance, looking INTO the room.
  - `{Room-Name}-View-To-Entrance` — camera deep inside, looking TOWARD the entrance.
  Key rule: the background element "behind [subject]" is on the wall OPPOSITE the camera.
    "window behind her" → camera at entrance side → View-From-Entrance.
    "entrance behind him" → camera at far/desk side → View-To-Entrance.
- Vehicle refs are split into three views:
  - `{Vehicle-Name}-Exterior`
  - `{Vehicle-Name}-Interior-From-Entrance`
  - `{Vehicle-Name}-Interior-To-Entrance`
- Outdoor refs are split into two views. Choose based on camera direction relative to the PRIMARY DIRECTION defined in the location's compass layout:
  - `{Outdoor-Name}-View-Primary` — camera faces the PRIMARY DIRECTION (toward the canonical background landmark).
  - `{Outdoor-Name}-View-Opposite` — camera faces the OPPOSITE direction (180-degree turn; left/right SWAPPED).
  Key rule: the background element "behind [subject]" is OPPOSITE the camera direction.
- Names must match existing refs EXACTLY (letters, digits, hyphens).
