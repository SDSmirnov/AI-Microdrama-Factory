
## SCREENPLAY_INSTRUCTIONS — YOUR PANEL-BY-PANEL BLUEPRINT

The episode JSON you receive contains a `screenplay_instructions` field with a per-panel blueprint (P1…P9).
For each panel, use its blueprint fields as **direct inputs**:
- `POWER` → drives spatial composition in `visual_start` (who is standing/sitting/cornered, who holds the prop)
- `EMOTION` → drives the primary face physics in `visual_start` and `visual_end`
- `STAKE OBJECT` → must appear as a visible element in `visual_start`; use for bokeh/rack focus where noted
- `STATE` → defines the dramatic delta between `visual_start` and `visual_end`
- `DIALOGUE SEED` → starting point for `dialogue`/`voiceover`; expand to full ≤8-word line
- `hook_type` in the bracket → set panel's `hook_type` field to the value after the `/` (e.g. `cold_open/hidden_identity`)
- `SCALE` in the bracket → set the shot scale in `lights_and_camera`
- `LOCATION` in the bracket → set the scene location; for INTERCUT episodes, alternate locations per the INTERCUT rule

If `screenplay_instructions` lacks a blueprint entry for a panel (e.g. transition episodes), infer from narrative context.

## INDEPENDENCE PROTOCOL — NON-NEGOTIABLE
Each panel is rendered by a separate image-generation model that receives ONLY that panel's text — no history, no context, no memory.
- FORBIDDEN: "same as before", "same POV", "same framing", "same appearance", "as in panel N", "continues from", "identical to", "as established".
- REQUIRED in EVERY panel's visual_start and visual_end: location details, shot type, camera angle, and lighting. Character reference images are injected separately — do NOT repeat canonical appearance (hair color, build, eye color, usual outfit). Instead, describe ONLY scene-specific deviations: costume changes ("silk robe instead of usual dress"), carried items for this scene ("holding a gun", "bag on left shoulder"), injuries or transient state ("soaked, mascara running"), flashback appearance ("18yo, school uniform — flashback"). Signature visual tells (scar, tattoo, prop) must be mentioned when visible at CU/ECU range.
- Treat each panel description as the ONLY instruction the image model will ever receive for that shot.
- POV CAMERA LAW: A shot described as "from [Character X]'s perspective" or "[Character X]'s POV" means the camera occupies Character X's eye position. Character X CANNOT appear anywhere in that frame — not in background, not in periphery, not at all. A character cannot see themselves. If Character X must be visible: drop the POV framing and use over-the-shoulder, reaction shot, or standard two-shot instead.
- CHARACTER ISOLATION LAW: Every visual_start and visual_end must explicitly name every character present in the frame. End each description with one of:
  - "NO OTHER CHARACTERS ARE VISIBLE IN THIS SHOT." — for single or paired shots
  - "ONLY [Name1] AND [Name2] ARE IN THIS SHOT. NO ONE ELSE." — for two-shots
  Never leave the character count implicit. The image model fills empty space with people from the scene context — block this with an explicit headcount every time.
- REFERENCES ARRAY CONTRACT: The `references` array must contain ONLY characters and props that are physically visible in this panel's visual_start or visual_end.
  FORBIDDEN: listing a character in references because they appear in a later panel of the same scene, or because they are mentioned in dialogue (off-screen voice = not visible).
  Off-screen speakers: include in `dialogue` field only. Their ref image must NOT be injected.
  Rule: if a character is not visible → not in references.

## VERTICAL MICRODRAMA CINEMATOGRAPHY — 9 PANELS PER SCENE

**PORTRAIT FRAME (9:16). Every decision is made for a phone screen held vertically.**

FRAMING HIERARCHY:
- ECU (Extreme Close-Up): eyes, hands, objects — for peak emotional moments
- CU (Close-Up): face from chin to forehead — default for dialogue and reaction
- MS (Medium Shot): chest up — confrontation, spatial relationship between characters
- WIDE: only when the environment is the dramatic agent (threat, scale, isolation)

CAMERA-FACING ORIENTATION LAW: Every visual_start must state explicitly how characters are oriented relative to the camera. Choose one and write it in the description:
- "faces visible to camera" — frontal or near-frontal; default for MS/CU/ECU
- "three-quarter profile to camera" — partial face visible (OTS with emotion)
- "back to camera" — only when backs are the INTENTIONAL dramatic choice
Never omit orientation. "Two figures on a bench" without camera orientation → model defaults to backs or profiles. If faces are needed: state it.

OVER-THE-SHOULDER WITH EMOTION: When an OTS shot must convey the foreground character's emotional state (shock, awe, fear), "pure back-of-head" loses the beat. Use instead: "three-quarter rear profile — foreground character's face is partially visible at the frame edge, showing [emotion]." If the foreground character's reaction is THE dramatic payload of the panel (not the background subject), switch from OTS to a reaction close-up and describe the background character in dialogue or voiceover.

ANGLE VARIETY RULE: No two consecutive panels may share the same shot scale AND the same camera angle. If P3 = CU / eye-level, then P4 must change at least one dimension: scale (ECU / MS / WIDE) OR angle (low / high / over-shoulder / oblique). Monotone shot sequences collapse rhythm. Force a change at every cut.

SAFE ZONE RULE: Compose all key subjects within the middle 65% of frame height.
Top 15% and bottom 20% must be visually clear (sky, wall, floor — no faces, no action).
Set text_safe_composition: true when this is achieved.

VISUAL DRAMATIC INTENSITY — WHAT GOES IN EVERY NARRATIVE FRAME:

**visual_start must answer four questions in one image:**
1. WHO has power right now, and WHO doesn't? — Show it through spatial position (standing over / cornered), posture (open vs. closed), or a prop (who holds the phone, the contract, the weapon).
2. WHAT specific emotion is visible on the primary face? — Not "he looks angry." Write the physics: "jaw set, lips compressed, eyes tracking her hands rather than her face." The AI renders what you describe.
3. WHAT detail signals something is at stake? — A door left open, a phone face-down, hands too close together, a glass at the edge of a table. One object carries the threat without naming it. If the screenplay_instructions blueprint names a STAKE OBJECT for this panel, it is MANDATORY in visual_start with these exact words: "FEATURED PROP: [name] — [where in frame, focus state]." Example: "FEATURED PROP: business card — held extended between Viktor's fingers, sharp focus, center frame." Without this line, the image model will not render the prop.
4. IS the character's signature visual tell present? — For any CU or ECU, the character's defining prop, mark, or gesture (as documented in their reference) must be explicitly described as visible, OR motion_prompt must explain why it is off-frame. Signature tells are the "fairy tale anchor" — without them, characters become generic faces. Never omit them at close range.

**visual_end must show a state transition with dramatic weight — not a completed action:**
- A decision made visible: the hand that finally reaches, eyes that finally meet, fingers releasing a grip that was held for panels.
- A boundary crossed: physical proximity breached, an object picked up or put down that shifts the power dynamic.
- A contradiction revealed: the suppressed smile when they should be devastated, the flash of real fear behind a performed confidence.
- NEVER write visual_end as "the action is done." visual_end is a NEW UNSTABLE STATE — it demands resolution in the next panel.

**motion_intent — declare BEFORE writing motion_prompt (required field):**
One sentence: what does the character want to achieve in this physical moment?
- RIGHT: "Pavel grabs her arm to stop her from leaving." / "Sofya leans back to re-establish dominance." / "Alisa crosses the room to reclaim the document before he reads it."
- WRONG: "Pavel moves toward Sofya." (describes action, not goal)
Without a declared intent, motion_prompt defaults to time-filling gestures ("holds the pose", "gaze remains fixed", "stands motionless"). If you cannot state WHY the character moves, the panel has no dramatic content — rewrite the panel.

**visual_start TIMING LAW:**
visual_start = the SPLIT SECOND before motion_prompt [0s] begins. Not the previous panel's outcome state. Not mid-motion.
The exact physical configuration at t=(-0.1s): hands at their resting position before the grab, body weight loaded before the lunge, fingers uncurled before the fist forms.
WRONG: visual_start = "He is angrily brushing foam from his jacket" — already mid-action.
WRONG: visual_start = "Her fingers are relaxed in defeat" — residual state of the previous clip; this clip's action hasn't started yet.
RIGHT: visual_start = "He stands still, both hands hovering over his lapels, the first brush not yet begun."
EXCEPTIONS: cold_open P1 — [0s] starts already in motion, visual_start describes the ongoing action. No other exceptions.

**motion_prompt DEFAULT — characters move. Every panel must have visible full-body physical action:**
People walk across rooms, gesture emphatically, turn away, step closer, grab objects, push past someone, sit down hard, stand up fast. A 6-second clip is a movie clip — something must visibly happen in physical space. Micro-expressions alone are dead screen.
WRONG: "character stands facing camera, jaw tightens, eyes shift left"
RIGHT: "At 0s Alisa strides from the door toward the table, 3 quick steps. At 3s she stops 80cm away, leans forward, plants both hands flat on the table surface. At 5s she locks eyes with him without breaking contact."
Default motion: at least one full-body or large-limb movement. Facial detail augments movement — never replaces it.

**MOTION BUDGET — 6 seconds is a large amount of real time. Use it:**
A real human takes 0.2s to press a button, 0.5s to pick up a phone, 1s to stand up from a chair, 2s to cross a small room, 4–6s to run 30 meters. The AI defaults to writing one micro-gesture and stretching it to fill the clip — this produces near-static footage. Plan the motion_prompt as a complete physical arc that REALISTICALLY takes ~6s to execute:
- 6s budget: enter a room (1s) + approach someone (1.5s) + grab their wrist (0.5s) + force them to look at you (1s) + deliver line (2s)
- NOT: "slowly, deliberately raises the phone toward his ear over 6 seconds"
- NOT: "holds finger over the send button, hesitating, for the duration of the clip"
Fill the time. If the core action takes 1s, add what happens before and after — the approach, the reaction, the consequence. A panel where nothing new happens between second 1 and second 5 is a failed panel. Each timestamped beat in motion_prompt must describe a DIFFERENT physical state than the previous beat.

**TEMPORAL COMPRESSION LAW — when a physical action sequence takes ≤4 seconds in real life, it MUST be ONE panel:**
Never map fast sequential events 1:1 to panels. If a character runs across a short space AND shouts AND collides — that is one continuous physical arc ≤4 seconds. Encode it as a single panel with a complex multi-beat motion_prompt. Three panels × 6s = 18 seconds of screen time for a 3-second real event — this is a broken clock.
Diagnostic: before splitting a fast action into multiple panels, ask — how long does this physically take in real life? If the answer is ≤4s, collapse into one panel. The 6-second budget easily contains: sprint (2s) + shout mid-run (1s) + collision (0.5s) + impact held (2.5s).
WRONG: panel 2 = "running", panel 3 = "shouts over shoulder while running", panel 4 = "door hits face" — three panels for four seconds of reality.
RIGHT: one panel, motion_prompt: "At 0s Pavel is mid-sprint down the corridor, arms pumping. At 2.5s he twists his upper body back over his right shoulder, mouth opening wide — shout beginning. At 4s the toilet door swings violently into frame from the left. At 4.5s the door makes full contact with his face. From 4.5s to 6s camera holds on the door filling the frame, 'СК' sign in sharp focus."
Rule of thumb: any transition_to_next=hard_cut between two panels where BOTH motion_prompts describe parts of the SAME continuous physical action is a red flag — merge them.
Camera movement is the compression tool: `lights_and_camera` describes the opening camera position; `motion_prompt` must describe how the camera moves through the action. A single panel can travel from MS tracking shot → snap zoom into ECU on impact moment → slow-motion hold. This is one clip, not three panels. Use it:
- Tracking MS that crash-zooms to ECU face at the moment of collision
- Dolly-in from wide to CU timed to the emotional peak
- Camera whip-pan that reorients from one subject to another mid-action
- Pull-back reveal that widens from ECU to MS as the full situation becomes clear
WRONG: lights_and_camera = "MS tracking" → separate panel lights_and_camera = "CU static" → separate panel lights_and_camera = "ECU on door sign"
RIGHT (one panel): lights_and_camera = "Starts MS tracking alongside Pavel; motion_prompt drives crash-zoom to ECU on impact." motion_prompt: "At 0s camera tracks Pavel at MS, moving parallel. At 4s camera begins rapid push-in. At 4.5s full ECU on his face fills frame — wide eyes, door edge entering from left. At 4.8s impact; camera holds ECU on the 'СК' sign."
SLOW-MOTION CONSTRAINT: do NOT write speed transitions within a single clip (normal speed → slow-mo or vice versa). Video models render the entire clip at one speed. If slow-motion is needed for a key impact moment, set the entire clip's motion to slow-motion in motion_prompt and lights_and_camera — never as a mid-clip transition.

**motion_prompt HESITATION — use ONLY for a single life-altering decision moment (≤1 panel per episode, never P1–P3):**
Reserve for the exact instant a character faces a choice that changes everything: a trigger they may or may not pull, a call they may or may not make, a door they may or may not open. Maximum 3 seconds of visible deliberation before action resolves.
WRONG: applying hesitation to confrontation, argument, revelation, or any panel where narrative momentum must continue.
RIGHT: "At 0s hand hovers 5cm above the phone. At 2s finger descends and presses call. At 3s phone is already at ear — decision made."
If you are tempted to write hesitation for any other reason: don't. Move the character instead.
HARD ENFORCEMENT: If a single gesture or held position spans more than 3 seconds without a physical state change — HARD FAILURE. Add what happens before (approach) and after (contact, response) to fill the clip.

**TABLEAU FAILURE — add to HARD ENFORCEMENT list:**
Any segment where the only visible motion is eye movement, micro-expression shift, or breathing for ≥2 consecutive seconds with no full-body or large-limb change = TABLEAU FAILURE.
WRONG: "From 1s to 3.5s, her eyes slowly scan his posture." (2.5s of eye motion only)
WRONG: "At 0s the scene is held in tense silence, no one moves." — dead screen regardless of emotional intent.
RIGHT: fill the segment with approach, turn, reach, grab, step back, or any large-limb action.

**COMBAT/CONTACT SEQUENCES — physical impact always collapses into one clip:**
If a character winds up, strikes, and the target reacts — that is one continuous physical arc of ≤4 seconds. It MUST be one panel.
WRONG: P5 = "character winds up", P6 = "fist connects", P7 = "opponent falls" — three panels for four seconds of reality.
RIGHT (one panel): "At 0s arm is already in mid-swing. At 0.3s fist contacts jaw. At 1s knees buckle. At 2.5s full collapse. Camera holds on fallen figure 2.5s–6s."
Same rule: push → stumble, grab → spin, shove → door impact, throw → crash. Impact + immediate consequence = one clip.

**POST-WRITE MOTION AUDIT (run on every panel before finalizing):**
1. FREEZE CHECK: scan each timestamped segment. If any segment ≥2s has no change in physical body state → HARD FAILURE. Add motion.
2. VOICE CHECK: does the panel have `dialogue` OR `voiceover`? If both empty → HARD FAILURE.
3. INTENT CHECK: does every beat in motion_prompt serve the declared `motion_intent`? Dead beats ("holds the point", "remains still", "gaze is fixed") → replace with purposeful action.
4. TIMING LAW CHECK: does `visual_start` describe the state JUST BEFORE motion_prompt [0s]? If it describes mid-action or the residual state of the previous panel → rewrite.
5. COMBAT CHECK: if two consecutive panels both describe parts of the same physical impact sequence → merge into one.

9-PANEL MICRO-ACT STRUCTURE (mandatory rhythm for all single-POV episodes):
(TRANSITION episodes override this entirely — see episode_type block. All 9 panels are environmental with no dialogue, no character conflict structure.)
- Panel 1: cold_open — EXPLANATION HOOK. The viewer drops into interaction already in progress. They see something happening and need to understand it: "what IS this?", "who IS this person?", "why ARE they doing that?" — forward pull toward understanding, not toward a withheld reveal. Duration: 3s hard cap (2–3s target). This is the maximum drop-off zone; every extra second costs viewers.
  TECHNICAL CONSTRAINT: after autocut, only 2–4s of the 6s clip will be visible. The action MUST be in progress at frame 0. motion_prompt[0s] MUST describe an ongoing physical event — NOT a character position, NOT a setup pose. If motion_prompt[0s] says "character stands / sits / holds", it is dead screen.
  Choose one of five hook archetypes that fits the source scene:
  * STATUS REVERSAL: protagonist caught in humiliation or subjugation — the viewer asks "why is this happening to them?"
  * IMPOSSIBLE SITUATION: no visible exit — the viewer asks "how did they end up here?"
  * HIDDEN IDENTITY: someone in frame is acting in an unexpected way — the viewer asks "who IS this person really?"
  * TICKING CLOCK: a deadline or countdown is already running — the viewer asks "what happens when it hits zero?"
  * SHOCKING REVELATION: someone is reacting to something we haven't seen — the viewer asks "what did they just find out?"
  Record the chosen hook archetype in hook_type as: cold_open/status_reversal, cold_open/impossible_situation, cold_open/hidden_identity, cold_open/ticking_clock, or cold_open/revelation.
  REQUIRED in visual_start: characters actively doing something — arguing mid-sentence, physically interacting with an object or each other, reacting to an event already in motion. A hand already extended with money. A body already stumbling back from a push. Words already coming out of a mouth. An argument already at elevated volume.
  REQUIRED in motion_prompt: "At 0s: [ongoing action already in progress]" — the action is 50%+ complete when the clip starts.
  FORBIDDEN for cold_open: character sitting/looking/waiting/traveling without active conflict; establishing location shots; beauty-without-stakes (reflections in windows, city lights on a passive face); character posed for the camera; anticipation poses (hand hovering, finger poised, body "about to" act); any shot where the answer to "what is happening RIGHT NOW?" is "nothing yet." [≈0–3s, hard cap 4s]
- Panel 2: verbal_hook — a character delivers the episode's central conflict in ≤8 words: an ultimatum, threat, confession, or challenge. Delivery in CU on speaker's face. NOT exposition — the dialogue names the stakes mid-confrontation.
  Duration: 4s hard cap. Still in the maximum drop-off zone. motion_prompt[0s] must show the character already speaking or reacting — not walking into frame, not "preparing to speak." The words are already coming out.
  FORBIDDEN for P2: character entering frame, character turning toward camera, setup before the line. The speaker is already in CU, already mid-delivery. [≈4–7s]
- Panel 3: escalation — first pressure or obstacle. Compose as a fully self-contained power-dynamic image: power, primary emotion, and stake object readable without context from P1–P2. Duration: 4–5s.
- Panel 4: emotional_capture — point of no return: an action, revelation, or commitment that makes watching the episode to the end feel necessary. Must escalate from panel 3 in emotional temperature, not just plot. Duration: 6s.
- Panel 5: crystallization — stakes become visceral and irreversible; no exit. STRONGEST THUMBNAIL CANDIDATE: compose for legibility as a static image, CU or ECU face with a recognizable ambiguous emotion, no key subject in text-overlay zone. Duration: 6–7s.
- Panel 6: confrontation — peak conflict, ECU on face
- Panel 7: pivot — ECU reaction shot at maximum pressure, before the twist. Duration 3–4s. NO dialogue — voiceover MANDATORY: 4–5 words of inner monologue, nothing more. This is the protagonist's silent internal response to the confrontation. HARD FAILURE if voiceover is empty OR exceeds 5 words.
- Panel 8: twist — one fact changes everything
- Panel 9 (intermediate episodes only): tension_peak — maximum escalation, no resolution. Protagonist at peak pressure — threat is closest, choice is seconds away. voiceover MANDATORY (4–5 words inner monologue): the held thought before the next episode's response. Viewer is propelled immediately into the next episode of the SAME published series.
- Panel 9 (final episode of series only): cliffhanger — RESPONSE PRESSURE FREEZE. Protagonist has just received a devastating action, revelation, or demand. The cliffhanger freezes them at the moment BEFORE their response — response forming but not yet delivered. NEVER freeze on a revelation itself (satisfies the viewer) — freeze on the protagonist's face as they absorb it. The viewer must unlock the next series to see: "What do they say/do right now?" DRAMABOX SERIES THUMBNAIL: the final FRAME of visual_end is the series unlock card. Require: (1) protagonist face in CU/ECU — ambiguous emotion, readable as either fear OR determination; (2) a stake object visible in frame; (3) no key subject in bottom 20% text zone. WRONG: "We see Alisa is lying — the truth is now known." RIGHT: "Ruslan's face is perfectly still; something he has just heard demands a response — the next series reveals what it is." If your P9 resolves anything, move the resolution to the next series P2 and end P9 on the moment just before the response.
  Choose one of four cliffhanger types (rotate — never repeat same type twice in a row across series):
  * RESPONSE_FREEZE: protagonist receives a line/action and must respond — cut before the response. Most powerful DramaBox hook.
  * REVELATION: new information reframes everything — protagonist's face at the moment of understanding, before reaction. Best at structural turning points.
  * EMOTIONAL_RUPTURE: unexpected betrayal, confession, or sudden silence where there should be words. Best for drama/romance arcs.
  * INTERRUPTED_ACTION: cut mid-gesture, mid-word, mid-step. Best for routine series transitions.
  Record chosen type in hook_type as: cliffhanger/response_freeze, cliffhanger/revelation, cliffhanger/emotional_rupture, or cliffhanger/interrupted_action.

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
6. ITEM ORIGIN — every retrieved object must come from a physically real place: "right hand moves to shoulder holster, draws pistol" / "opens bag hanging from left shoulder, removes phone" / "reaches into left breast pocket, produces badge wallet". NEVER write "pulls out a gun" or "takes out phone" — the model has no idea where the item was and will invent a location. The character's reference description defines where everything is carried.
7. MOVEMENT DIRECTION — all character movement must be stated camera-relative with exact phrasing:
   - "moving TOWARD the camera" — character approaches; grows larger in frame
   - "moving AWAY FROM the camera" — character retreats; grows smaller in frame
   - "moving LEFT across frame" / "moving RIGHT across frame" — lateral tracking
   NEVER rely on positional shorthand ("from end A to end B") — the model has no knowledge of which end is closer to camera. Always state the camera-relative vector explicitly in both visual_start and motion_prompt[0s].

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

VOICE BUDGET (hard technical limit): 24 characters per second × panel duration = maximum characters for dialogue + voiceover COMBINED. For a 6s panel: 144 chars total. For a 4s panel: 96 chars total. Exceeding this budget causes TTS to either truncate or produce garbled audio in I2V rendering — the line will not fit the clip. Count characters before writing. If dialogue uses 80 chars, voiceover has ≤64 chars remaining. If a panel has no dialogue, voiceover may use the full budget.

MANDATORY VOICE COVERAGE — HARD RULE:
Every panel MUST have either `dialogue` OR `voiceover` populated (or both). HARD FAILURE if both are empty.
A panel with both fields empty is dead screen for 80% of muted viewers. The caption alone cannot carry emotional weight without audio counterpoint.

DIALOGUE: ≤8 words, delivered in CU on speaker's face. Populate both `dialogue` and sync `voiceover` for inner counterpoint.
VOICEOVER: inner monologue text only — no voice/gender prefix in the text field. {target_language} language. HARD LIMIT: 4–5 words only for pivot panels (P7). It is a reactive flash — a thought that crosses the face before the character acts. Longer inner monologue is a novel; this is a phone screen.

VOICEOVER + DIALOGUE TIMING: When a panel has both voiceover and dialogue non-empty, set voiceover_timing to one of:
- "before_dialogue" — VO plays first, then the spoken line (default for inner reaction)
- "after_dialogue" — spoken line first, then VO (default for consequence beats)
- "under_dialogue" — VO runs simultaneously at low mix (use rarely — usually muddy)
- "during_silence" — VO plays in a silent gap within motion_prompt (mark gap in motion_prompt)
HARD DEFAULT: if voiceover is a reaction to dialogue, use "after_dialogue". Never leave timing ambiguous when both fields are populated.

`voiceover_settings` — required alongside every non-empty voiceover. Set: gender ("male"/"female"), actor (character name), age (approximate, as string), tone (comma-separated delivery descriptors: "scared, confused", "cold, commanding", "bitter, exhausted", "breathless, urgent"). Use {} when voiceover is empty.

DIALOGUE EXCHANGE CONTINUITY — HARD RULE (applies to ALL panels with dialogue, not just confrontation zone):
Any line of dialogue that is a direct question, demand, or a statement addressed to a specific person in the scene MUST receive its verbal response within the same panel OR the immediately following panel. NEVER cut away after a line that demands a verbal reply without showing that reply first.

Patterns that create "broken dialogue" — FORBIDDEN:
- Panel A: Character X asks a question → Panel B: Character Y reacts in silence or only in voiceover, question visually unanswered
- Panel A: Character X makes a demand → Panel B: Cut to a different emotional beat entirely, demand never answered
- Panel A: Character Y reveals information → Panel B: Character X reacts, but their VERBAL response to the revelation is dropped (voiceover doesn't count — the viewer expects X to SAY something aloud)
- Panel A: Character X addresses Character Y directly → Panel B: Character Y's voiceover carries the response that should be spoken dialogue — HARD FAILURE: move it to dialogue

HOW TO HANDLE MULTI-TURN EXCHANGES:
1. SHORT EXCHANGE (Q+A, ≤2 turns, total ≤80 chars): pack both sides into one panel's `dialogue` field.
   Format: `"Speaker1 (voice): Line1\nSpeaker2 (voice): Line2"`
   The camera holds on the LISTENER's face during the reaction turn — the emotional beat is in the face, not the speaker.
2. LONGER EXCHANGE (3–4 turns): allocate two consecutive panels, one turn per panel. Panel N shows the challenge (CU on speaker), Panel N+1 shows the counter (CU on responder). Do NOT skip the counter to advance the emotional arc — the counter IS the emotional arc.
3. REVELATION EXCHANGE ("Кто это?" / "Мой брат."): the trigger question has narrative value — include it. The revelation lands harder when the viewer sees the question that caused it. Both question and answer fit in one panel (total ≤40 chars).

EXCHANGE COMPLETENESS CHECK (before finalizing any confrontation panel):
- Does this panel's dialogue leave an open question that the next panel doesn't answer? → HARD FAILURE: include the answer in the next panel's dialogue.
- Does the next panel's dialogue line presuppose an exchange the viewer never heard? → HARD FAILURE: include the trigger line in this panel.
- Is the voiceover carrying a response that should be spoken dialogue? → HARD FAILURE: move it to dialogue. Inner monologue supplements speech; it never replaces it when the character would realistically speak.

CAPTION CONTRACT (caption field — required for EVERY panel):
`caption` is a persistent bottom-third text overlay, always visible regardless of audio state. It is a HOOK, not a summary.
Rules:
- ≤40 characters
- NEVER narrates the action currently visible on screen (WRONG: "He called her number." — the viewer can see this)
- Delivers the emotional punch, subtext, or an open question that makes the viewer need to see what happens next
- RIGHT: "Thirty-one nights. One cracked screen." — adds subtext invisible on screen
- RIGHT: "She laughed. With someone else." — delivers the emotional wound
- SELF-TEST: if a stranger saw only the image + caption, would they pause their scroll? If not, rewrite.

sound_design=silence CLARIFICATION: `sound_design=silence` means the ambient/music/SFX channels are zeroed. The voiceover TTS track plays independently and is NOT silenced. NEVER write "complete silence" or "no sound" when a voiceover is present — write "ambient silence, voiceover only." Complete silence = audio team will mute TTS = caption is the only thing muted viewers see.

SOUND DESIGN (sound_design) — required for EVERY panel:
- Capture the sonic atmosphere of this exact panel moment, separate from dialogue/voiceover.
- Plan sonic contrast deliberately: sustained silence broken by a sharp sound is more powerful than continuous noise — for the 20-40% watching with audio. For the 60-80% watching muted, silence = nothing. Never design a beat that only lands if the viewer can hear the absence of sound.
- Sonic contrast panels (sound_design=silence) are valid ONLY when the same panel also has a voiceover line. A silent panel without voiceover is a dead screen for muted viewers. Do NOT mandate silence panels — use them only when they serve both audio-on AND audio-off audiences simultaneously.
- For j_cut transitions: describe the next scene's audio that bleeds in ("J-cut: rain ambient from next scene starts at 5s mark").
- Examples: "silence", "low-frequency hum builds", "amplified footstep at 2s, then silence", "heartbeat rises to bass drop on cut", "glass crack at 4s, then pin-drop silence", "distant thunder, growing".

TRANSITION TO NEXT PANEL (transition_to_next):
- match_cut: plan visual_end of this panel to share a geometric shape or motion vector with visual_start of the next. In motion_prompt, explicitly name the match: "visual_end matches next panel via [circular shape / upward sweep / falling diagonal / vertical line]."
- jump_cut: intentional jarring cut — reduce duration to 2–3s. Use in escalation bursts and micro-expression clusters for beat-synced pace.
- smash_cut: maximum contrast — silence cuts to noise, stillness cuts to chaos, or vice versa. Capture contrast in sound_design.
- j_cut: next panel's audio begins audibly 1–2s before the visual cut. Describe the audio in sound_design.
- hard_cut: standard clean cut (default).

PANEL TYPE (panel_type):
- narrative: the only valid value. Every panel shows characters in action — faces, hands, power dynamics.

**IMPORTANT: EACH SCENE MUST HAVE EXACTLY 9 PANELS following the structure above.**

SCENE-LEVEL CAMERA AND LIGHTING MASTER:
For every scene, generate:
- camera_master: one sentence capturing the dominant lens (mm), angle, and primary lighting condition shared by all panels in this scene.
- lighting_master: one sentence capturing key light direction/color/quality, fill ratio, and any visible practicals. All panels must stay within this lighting DNA — deviations must be noted in that panel's lights_and_camera.

LOCATION REFERENCE NAMING — populate location_references per panel using EXACT split view names:
- Room refs are split into two views. Choose based on WHERE THE CAMERA IS POSITIONED, not based on
  which character is on screen. Use all prose signals to determine camera side:
  - `{Room-Name}-View-From-Entrance` — camera is at/near the entrance door, looking INTO the room.
    Use when: shooting the character(s) at the far wall/desk; OR wide two-shot from entrance side;
    OR "window behind [subject]" and window is the far wall (camera on entrance side).
  - `{Room-Name}-View-To-Entrance` — camera is deep inside the room, looking TOWARD the entrance.
    Use when: camera is past the visitor/near-entrance zone; OR "entrance/door behind [subject]"
    (entrance wall is visible in background behind subject = camera is on the far/window side).
  Key rule: the background element "behind [subject]" is on the wall OPPOSITE the camera.
    "window behind her" → camera at entrance side → View-From-Entrance.
    "entrance behind him" → camera at far/desk side → View-To-Entrance.
  Key rule: two-shot with both characters in one frame → use whichever view best matches
    the room background depth (typically View-From-Entrance for desk-facing wide shots).
- Vehicle refs are split into three views:
  - `{Vehicle-Name}-Exterior` — camera outside the vehicle
  - `{Vehicle-Name}-Interior-From-Entrance` — camera inside, looking in from the driver/main door side
  - `{Vehicle-Name}-Interior-To-Entrance` — camera inside, looking toward the entrance from the rear
- Outdoor refs are split into two views. Choose based on camera direction relative to the PRIMARY DIRECTION defined in the location's compass layout:
  - `{Outdoor-Name}-View-Primary` — camera faces the PRIMARY DIRECTION (toward the canonical background landmark).
    Use when: shooting toward the far-end landmark; OR background element is the canonical far-end feature.
  - `{Outdoor-Name}-View-Opposite` — camera faces the OPPOSITE direction (180-degree turn; left/right SWAPPED).
    Use when: camera faces the entry/approach side; OR the canonical landmark is behind the camera.
  Key rule: the background element "behind [subject]" is OPPOSITE the camera direction.
    "archway behind her" + archway is the PRIMARY-end landmark → camera faces Opposite → View-Opposite.
    "open street behind him" + street is the near/entry end → camera faces Primary → View-Primary.
- Names must match existing refs EXACTLY (letters, digits, hyphens) — a mismatch silently skips the reference image during rendering.
