
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

VISUAL DRAMATIC INTENSITY — WHAT GOES IN EVERY NARRATIVE FRAME:
(Applies to panel_type=narrative only. For atmosphere_insert: skip questions 1–2; fill question 3 with the single environmental element that carries all the drama — scale, texture, or color temperature is the conflict; and fill question 4 with how that element changes state.)

**visual_start must answer three questions in one image:**
1. WHO has power right now, and WHO doesn't? — Show it through spatial position (standing over / cornered), posture (open vs. closed), or a prop (who holds the phone, the contract, the weapon).
2. WHAT specific emotion is visible on the primary face? — Not "he looks angry." Write the physics: "jaw set, lips compressed, eyes tracking her hands rather than her face." The AI renders what you describe.
3. WHAT detail signals something is at stake? — A door left open, a phone face-down, hands too close together, a glass at the edge of a table. One object carries the threat without naming it.

**visual_end must show a state transition with dramatic weight — not a completed action:**
- A decision made visible: the hand that finally reaches, eyes that finally meet, fingers releasing a grip that was held for panels.
- A boundary crossed: physical proximity breached, an object picked up or put down that shifts the power dynamic.
- A contradiction revealed: the suppressed smile when they should be devastated, the flash of real fear behind a performed confidence.
- NEVER write visual_end as "the action is done." visual_end is a NEW UNSTABLE STATE — it demands resolution in the next panel.

**ARC BRIDGE EXCEPTION — ep1.p9 only:**
visual_end must show physical suspension: the action is mid-motion and frozen. The hand is raised, the finger is 1cm from the target, the mouth is open and the word is not spoken. The drama has not crossed its threshold. The cut happens before the action completes.
motion_prompt MUST end before the action resolves: describe the approach to the action, the last frame before completion, and then stop. The video clip ends there.

**ARC PICKUP — ep2.p1 only:**
visual_start picks up from the arc_bridge visual_end: same location, same character, same physical position, 1–2 seconds later in narrative time. The motion_prompt begins from where the bridge ended. The voiceover carries the character's inner decision — what they are about to do and why.

**motion_prompt DRAMATIC PHYSICS — hesitation and micro-decision carry more drama than the action itself:**
The moment before the action: the 0.5s of held breath, the hand that moves toward and slows, the eyes that almost look away but don't. Write these as timestamped physical events.
WRONG: "He picks up the phone and calls."
RIGHT: "At 0s phone sits on table, hand rests 10cm to the right. At 1.5s fingers move left, stop 3cm from phone. At 3.0s index finger contacts screen but does not press. At 5.0s hand withdraws into a fist on the table — phone uncalled."

## 9-PANEL STRUCTURE BY EPISODE TYPE

### ARC PART 1 (arc_part1) — Setup, Panels 1–9

Panel structure is mandatory:
- Panel 1: cold_open — most arresting image, zero context, maximum visual tension. hook_type: cold_open. [≈0–6s]
- Panel 2: verbal_hook — character speaks the arc's central conflict in ≤8 words: ultimatum, threat, confession, or challenge. CU on speaker's face. NOT exposition — the conflict naming the stakes. hook_type: verbal_hook. [≈7s mark]
- Panel 3: context — orient the viewer. Who is this, where are they, what world is this. Delivered through action, not exposition. One MS or WIDE shot for spatial grounding.
- Panel 4: first_escalation — first obstacle, complication, or pressure arrives.
- Panel 5: emotional_capture — point of no return: an action taken, a line crossed, a secret revealed. The viewer is locked in. hook_type: emotional_capture. [≈30s mark]
- Panel 6: rising_action — stakes raised further. A new obstacle or revelation that makes escape impossible.
- Panel 7: atmosphere_insert — mandatory abstract panel. panel_type: atmosphere_insert. No character close-ups. Amplifies the emotional tone without explaining it. Duration 3–4s.
- Panel 8: mid_revelation — new information changes the context of everything shown so far. Not the twist (which comes in part 2) — this is the information that makes the twist possible.
- Panel 9: arc_bridge — hook_type: arc_bridge. Physical suspension: action frozen mid-motion, decision at the threshold but not crossed. sound_design: silence. motion_prompt ends before the action resolves. NEVER a resolution. NEVER a full cliffhanger — the drama has not peaked yet.

### ARC PART 2 (arc_part2) — Payoff, Panels 1–9

Panel structure is mandatory:
- Panel 1: arc_pickup — hook_type: arc_pickup. Same location, same moment as arc_bridge, 1–2 seconds later. Continuation, not a new cold_open. Voiceover carries the inner decision. [≈0–6s of ep2]
- Panel 2: escalation_return — pressure from part 1 returns with increased force. The stakes of the mid_revelation are now active.
- Panel 3: confrontation_build — the confrontation that part 1 was building toward is now inevitable. Characters approach the collision point.
- Panel 4: confrontation_peak — maximum conflict. ECU on face. This is the scene's fulcrum — the moment everything depends on.
- Panel 5: atmosphere_insert — mandatory abstract panel. panel_type: atmosphere_insert. Duration 3–4s. Transition in via smash_cut; transition out via smash_cut or match_cut.
- Panel 6: twist — one fact changes everything. What the viewer thought was happening was wrong. The information arrives visually — a prop, a reflection, a door opening.
- Panel 7: reversal — power dynamic inverts. Whoever was in control is now not. Delivered through a physical action or discovery, not dialogue.
- Panel 8: consequence — the visible cost of the reversal. An irreversible action taken. A state that cannot be undone. Not a resolution — the aftermath is still open.
- Panel 9: cliffhanger — hook_type: cliffhanger. Freeze on maximum unresolved tension. One visible element with two possible interpretations. End mid-breath. Never resolve. Never summarize. [The Button]

### TRANSITION episode (transition)
Atmosphere-only. ALL 9 panels are atmosphere_insert. No dialogue, no character conflict, no close-ups.
Serves as visual bridge between two 18-panel arc units. See episode_type_transition.md for full spec.

## MOTION PROMPTS

MOTION_PROMPT PHYSICAL REALISM — the video model renders every word literally, with zero narrative context:
1. Physical movements only, no emotional language. Emotions go in voiceover/emotional_beat. Use joint angles, degrees, distances.
   WRONG: "he recoils in horror"  RIGHT: "at 1.5s his eyes open wide, jaw drops ~2 cm, upper body leans back 10°"
2. No spectacle verbs for human actions: erupts/sprays/fountains/explodes/bursts → describe the minimal physical event.
3. No speed metaphors: "blurring speed", "in an instant" → use explicit timestamps and distances.
4. Anatomically correct scale: a tear is a 2–3 mm bead on the cheek, not "rivers" or "streams".
5. Before writing any phrase: ask — could the AI render this as a grotesque artifact? If yes, rewrite as plain physical movement.

MOTION PROMPTS for vertical format:
- Prefer vertical camera movements: tilt up/down, vertical dolly, snap zoom into eyes
- Match motion intensity to emotional_beat (dread = slow creep, shock = snap cut energy, rage = handheld shake)
- For shock/revelation panels: specify fast zoom-in on face in lights_and_camera and motion_prompt — "camera snap-zooms into subject's eyes over 0.5s"
- For static-camera + dynamic-subject contrast: note "camera locked on tripod, subject moves through frame"
- Duration ~6s per panel; motion should resolve visually but not narratively

## CINEMATOGRAPHY TECHNIQUES

TILT REVEAL — vertical-format signature:
Use tilt in motion_prompt to reveal information progressively top-to-bottom or bottom-to-top.
Mandatory for at least one confrontation or twist panel per arc unit.
Example: "camera starts on hands gripping a phone, slow tilt upward over 4s, arrives at subject's face."

MICRO-EXPRESSION CLUSTER — rapid escalation:
Plan 2–3 consecutive ECU panels (panels 3–5 escalation zone of arc_part1) at duration 1–2s each with transition_to_next=jump_cut.
Each shows the same face in a different emotion: calm → surprise → fear.
In motion_prompt, describe only the face: micro-muscle shifts, eye movement, lip compression. No camera movement.

BOKEH / SELECTIVE FOCUS — attention direction:
In escalation and twist panels, compose with shallow DOF to isolate a single foreground object.
Specify in lights_and_camera: "shallow DOF, [object] sharp in foreground, subject/background as bokeh."

SHADOW & SILHOUETTE — indirect reveal (use in escalation/confrontation):
Show the threat, emotion, or subject through its shadow or silhouette — never directly.

REFLECTION REVEAL — hidden truth (use in twist panels):
Show a character's real internal state in a reflective surface while their face performs the opposite.

RACK FOCUS — prop-to-face revelation (use in escalation/confrontation):
Camera static. Start with foreground object in sharp focus, subject's face as background bokeh. At peak, pull focus to the face.

MATCH CUT — visual shape continuity (use in escalation transitions):
Plan visual_end of one panel to share a geometric shape or motion vector with visual_start of the next.
MANDATORY: plan at least one match_cut per arc unit in the escalation zone (ep1.p3–p6).
Also use a match_cut at the arc_bridge → arc_pickup transition to make the join feel seamless.

## SOUND

DIALOGUE: ≤8 words, delivered in CU on speaker's face. Populate both `dialogue` and sync `voiceover` for inner counterpoint.
VOICEOVER: inner monologue revealing what the image cannot show. Russian language.

SOUND DESIGN (sound_design) — required for EVERY panel:
- Plan sonic contrast deliberately: sustained silence broken by a sharp sound is more powerful than continuous noise.
- MANDATORY: at least one panel per arc_part1 scene must have sound_design="silence" as setup for the next panel's sonic event.
- arc_bridge panel (ep1.p9) MUST have sound_design="silence" — the cut to episode 2 is a sonic reset.
- arc_pickup panel (ep2.p1) begins into silence, then rebuilds.
- For j_cut transitions: describe the next scene's audio that bleeds in.

TRANSITION TO NEXT PANEL (transition_to_next):
- match_cut: share geometric shape or motion vector with visual_start of next. Name the match explicitly in motion_prompt.
- jump_cut: jarring cut, reduce duration to 2–3s. Use in escalation bursts and micro-expression clusters.
- smash_cut: maximum contrast — silence cuts to noise, stillness cuts to chaos.
- j_cut: next panel's audio begins 1–2s before the visual cut.
- hard_cut: standard clean cut (default).
- For arc_bridge → arc_pickup (the episode boundary): plan this as match_cut in visual_end of arc_bridge and visual_start of arc_pickup.

PANEL TYPE (panel_type):
- narrative: standard story panel.
- atmosphere_insert: MANDATORY — exactly one per arc_part1 (at ep1.p7) and one per arc_part2 (at ep2.p5). Duration 3–4s. No dialogue, no character close-ups. Two subtypes:
  * ENVIRONMENTAL: 1–2 macro-scale elements only (crashing wave, storm wall, lone tree in wind). Grand scale, 2–3 color palette. visual_start: "minimalism: [element], [light condition], hyper-realistic. No people, no faces."
  * TEXTURE/DETAIL: extreme macro of a single physical surface — cracked concrete, condensation on cold glass, a scar, a burning letter. Shallow DOF, single element, fills the frame.
  Transition in via smash_cut or match_cut; transition out via smash_cut or match_cut.

**IMPORTANT: EACH SCENE MUST HAVE EXACTLY 9 PANELS following the structure above.**

SCENE-LEVEL CAMERA AND LIGHTING MASTER:
For every scene, generate:
- camera_master: one sentence capturing the dominant lens (mm), angle, and primary lighting condition shared by all panels in this scene.
- lighting_master: one sentence capturing key light direction/color/quality, fill ratio, and any visible practicals.
