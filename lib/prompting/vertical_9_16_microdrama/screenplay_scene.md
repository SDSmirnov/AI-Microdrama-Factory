
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
(Applies to panel_type=narrative only. For atmosphere_insert: skip questions 1–2; fill question 3 with the single environmental element that carries all the drama — scale, texture, or color temperature is the conflict; and fill question 4 with how that element changes state: wave rising or cresting, ember dying or flaring, fog thickening or thinning.)

**visual_start must answer three questions in one image:**
1. WHO has power right now, and WHO doesn't? — Show it through spatial position (standing over / cornered), posture (open vs. closed), or a prop (who holds the phone, the contract, the weapon).
2. WHAT specific emotion is visible on the primary face? — Not "he looks angry." Write the physics: "jaw set, lips compressed, eyes tracking her hands rather than her face." The AI renders what you describe.
3. WHAT detail signals something is at stake? — A door left open, a phone face-down, hands too close together, a glass at the edge of a table. One object carries the threat without naming it.

**visual_end must show a state transition with dramatic weight — not a completed action:**
- A decision made visible: the hand that finally reaches, eyes that finally meet, fingers releasing a grip that was held for panels.
- A boundary crossed: physical proximity breached, an object picked up or put down that shifts the power dynamic.
- A contradiction revealed: the suppressed smile when they should be devastated, the flash of real fear behind a performed confidence.
- NEVER write visual_end as "the action is done." visual_end is a NEW UNSTABLE STATE — it demands resolution in the next panel.

**motion_prompt DRAMATIC PHYSICS — hesitation and micro-decision carry more drama than the action itself:**
The moment before the action: the 0.5s of held breath, the hand that moves toward and slows, the eyes that almost look away but don't. Write these as timestamped physical events. The withdrawal IS the drama. The held pause IS the tension.
WRONG: "He picks up the phone and calls."
RIGHT: "At 0s phone sits on table, hand rests 10cm to the right. At 1.5s fingers move left, stop 3cm from phone. At 3.0s index finger contacts screen but does not press. At 5.0s hand withdraws into a fist on the table — phone uncalled."
The physical hesitation tells the viewer everything about the character's internal state without a single word.

9-PANEL MICRO-ACT STRUCTURE (mandatory rhythm for pov_a / pov_b / confrontation episodes):
(TRANSITION episodes override this entirely — see episode_type block. All 9 panels are atmosphere_insert with no dialogue, no character conflict structure.)
- Panel 1: cold_open — most arresting image, zero context, maximum tension or beauty [≈0–6s]
- Panel 2: verbal_hook — a character speaks the episode's central conflict into existence with ≤8 words: an ultimatum, threat, confession, or challenge. Delivery in CU on speaker's face. NOT exposition — the setting orients; the dialogue names the stakes. [≈7s mark]
- Panel 3: escalation — first pressure or obstacle
- Panel 4: emotional_capture — point of no return: an action, revelation, or commitment the viewer cannot abandon. Must escalate from panel 3 in emotional temperature, not just plot. This is the "21-second lock" — if the viewer is still here, they are captured. [≈21s mark]
- Panel 5: escalation — complication, stakes raised further; no exit
- Panel 6: confrontation — peak conflict, ECU on face
- Panel 7: peak — maximum emotional intensity, the scene's fulcrum
- Panel 8: twist — one fact changes everything
- Panel 9: cliffhanger — freeze on maximum unresolved tension; end mid-breath [≈60–90s mark, the Button]

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
- atmosphere_insert: MANDATORY — exactly one per pov/confrontation episode, at panel 7 or 8 (emotional peak / pre-cliffhanger). Exception: transition episodes use atmosphere_insert for ALL 9 panels — the episode_type block defines their full structure. A single minimalist WOW shot with no dialogue, no character close-ups. Two subtypes:
  * ENVIRONMENTAL: 1–2 macro-scale elements only (crashing wave, wall of flame, fog swallowing a city, storm wall, lone tree in wind). Grand scale, 2–3 color palette. visual_start: "minimalism: [element], [light condition], hyper-realistic. No people, no faces." No character refs needed.
  * TEXTURE/DETAIL: extreme macro of a single physical surface — cracked concrete, condensation on cold glass, a scar, a burning letter, fabric under tension. Reveals what the story is made of. Shallow DOF, single element, fills the frame.
  Duration 3–4s. Transition in via smash_cut or match_cut; transition out via smash_cut or match_cut.
  The voiceover or sound from the surrounding panels spills over this image — the abstract visual amplifies the emotion without explaining it.

**IMPORTANT: EACH SCENE MUST HAVE EXACTLY 9 PANELS following the structure above.**

SCENE-LEVEL CAMERA AND LIGHTING MASTER:
For every scene, generate:
- camera_master: one sentence capturing the dominant lens (mm), angle, and primary lighting condition shared by all panels in this scene.
- lighting_master: one sentence capturing key light direction/color/quality, fill ratio, and any visible practicals. All panels must stay within this lighting DNA — deviations must be noted in that panel's lights_and_camera.
