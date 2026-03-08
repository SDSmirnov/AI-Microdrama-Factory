
## INDEPENDENCE PROTOCOL — NON-NEGOTIABLE
Each panel is rendered by a separate image-generation model that receives ONLY that panel's text — no history, no context, no memory.
- FORBIDDEN: "same as before", "same framing", "continues from", "as established", "same appearance", "as in panel N".
- REQUIRED: Restate character appearance (hair, clothing, build, expression), location details, shot type, lighting, and interpersonal distance in EVERY panel's visual_start and visual_end — even if they repeat word-for-word from the previous panel.
- Treat each panel description as the ONLY instruction the image model will ever receive for that shot.

## VERTICAL DARK ROMANCE CINEMATOGRAPHY — 9 PANELS PER SCENE

**PORTRAIT FRAME (9:16). The phone screen held vertically is an intimate space — everything happens close.**

FRAMING HIERARCHY (dark romance defaults lean close):
- ECU (Extreme Close-Up): eyes, hands, lips, objects — for desire, restraint, revelation
- CU (Close-Up): face from jaw to forehead — the default for any emotionally loaded moment
- MS (Medium Shot): chest up — used when interpersonal distance is the dramatic agent (two people who are too close, or too far)
- WIDE: only when space itself is the statement (he is across the room; the room is enormous; she is alone in it)

SAFE ZONE RULE: Key subjects (faces, hands, objects) within the middle 65% of frame height.
Top 15% and bottom 20% must be visually clear. Set text_safe_composition: true when achieved.

VISUAL DRAMATIC INTENSITY — WHAT GOES IN EVERY NARRATIVE FRAME:
(For atmosphere_insert panels: fill question 3 with the single object or environmental element that carries all the emotional weight; fill question 4 with how that element changes state.)

**visual_start must answer three questions:**
1. WHO holds the power right now, and how is that visible — through spatial position (standing, seated, at the door vs. in the room), through who has moved toward whom, through who holds the prop?
2. WHAT physical indicator of suppressed desire is visible on the primary face? Not "she wants him" — write the physics: "lower lid slightly heavy, gaze tracking 10cm below his eyes, lips parted 2mm, inhale held." The AI renders what you describe.
3. WHAT single charged object or environmental detail tells the viewer what is at stake without naming it — a glass set down on his side of the desk, a door that is not quite closed, a phone placed face-down, a hand 5cm from another hand?

**visual_end must show a shift in the desire/restraint dynamic — not a resolved action:**
- The slip: the moment the controlled surface cracks for one panel — an eye that stays too long, a hand that almost, a breath that becomes audible
- The recovery: the deliberate re-imposition of control — more devastating than the slip because it names what was felt
- The reveal: one character sees something they were not meant to see — expression, a message, a reaction — and has to pretend they didn't
- NEVER write visual_end as resolution. visual_end is a new unstable state — it demands the next panel.

**motion_prompt DESIRE PHYSICS — hesitation carries more charge than action:**
The moment before: the 0.3s of stillness before the decision. The hand that moves toward and stops. The eye that breaks contact first. The breath taken before speaking that is then not spoken.
WRONG: "He moves closer to her."
RIGHT: "At 0s he stands 80cm from her, facing forward. At 2s his weight shifts left — not a step, a lean. At 4s 60cm between them. At 5.5s he stops. The 60cm stays. At 6s his gaze drops to her shoulder, then returns to her face."
The stillness after motion is the climax.

9-PANEL MICRO-ACT STRUCTURE (mandatory rhythm for pov_a / pov_b / connection episodes):
(TRANSITION episodes override this entirely — see episode_type block. All 9 panels are atmosphere_insert with no dialogue.)
- Panel 1: cold_open — maximum sensory impact, desire before context, the reaction before we see the cause [≈0–6s]
- Panel 2: verbal_hook — one character speaks the episode's central charge into existence with ≤8 words: ambiguous, weighted, double-meaning. CU on speaker's face as they say it. Silence after. [≈7s mark]
- Panel 3: escalation — the first sign that normal rules don't apply here
- Panel 4: emotional_capture — the acknowledgment: a physical betrayal of internal state that the character immediately suppresses. This is the lock. [≈21s mark]
- Panel 5: escalation — something narrows. Space, options, pretense.
- Panel 6: confrontation — maximum proximity or maximum restraint; they are in the same frame, too close or pointedly distant
- Panel 7: peak — the threshold: one more moment and something irreversible happens
- Panel 8: twist — one action, one word, one look that changes the entire emotional geometry
- Panel 9: cliffhanger — freeze on the new impossible status quo. Something has changed that cannot be unchanged. [≈54–63s, the Button]

MOTION PROMPTS for vertical dark romance format:
- Prefer slow, deliberate motion: slow tilt toward a face, a hand that moves in measured centimetres, a head turn that arrives a beat late
- Match motion intensity to emotional_beat: restraint = slowed movements with exact timestamps; desire = a quick involuntary micro-motion followed by deliberate stillness; revelation = snap to ECU on face
- SIGNATURE TECHNIQUE: The Still Pan — camera moves slowly, character does not. The camera closing in while the character holds still creates unbearable proximity.
- Duration ≈6s per panel; motion should be visible, meaningful, and physically incomplete — the action that stops before it finishes is the hook

MOTION_PROMPT PHYSICAL REALISM — the video model renders every word literally:
1. Physical movements only. No emotional language in motion_prompt — emotions go in voiceover and emotional_beat. Use joint angles, distances, timestamps.
   WRONG: "she trembles with suppressed longing"  RIGHT: "at 3s her left hand tightens on the desk edge — knuckles visible, 5mm of whitening — then releases"
2. No metaphor verbs for physical actions. Erupts/floods/blazes → describe the actual physical event.
3. No speed metaphors. Use explicit timestamps and distances.
4. Anatomically correct scale — a tear is a 2–3mm bead, a breath is a 3cm chest rise.
5. Before writing any phrase: ask — could the AI render this as broken anatomy or grotesque artifact? If yes, rewrite as plain physical event.

TILT REVEAL — vertical signature technique:
Use slow vertical tilt to reveal information progressively. In dark romance: start on hands (the ring, the glass, the document), tilt up to face. Or start on face, tilt down to the object that names what they really want.
Mandatory for at least one connection or twist panel per scene. State: tilt direction, speed, what is concealed at start.

PROXIMITY PROGRESSION TECHNIQUE — plan deliberately:
Map each panel's interpersonal distance in lights_and_camera or visual_start: "120cm separation / 80cm / 40cm / 40cm (neither moves) / 30cm / withdrawal to 80cm." The distance is the plot.

REFLECTION TECHNIQUE — dual truth:
When a character's performed emotion and real emotion diverge, show the real one in a reflective surface — dark phone screen, window at night, polished marble, a still drink.
"At 2s, the camera frames the dark surface of a phone screen. His reflection shows the jaw muscle moving — he is not as calm as his voice sounds."

SELECTIVE FOCUS — attention as direction:
In charged panels, compose with shallow DOF: foreground object sharp (a hand, a ring, a glass), subject's face as deliberate bokeh behind it. Rack focus to face at emotional peak — the object becomes bokeh and the face becomes real.

DIALOGUE: ≤8 words. Ambiguous. The meaning in the gap between words. Delivered in CU on speaker's face. Populate both `dialogue` and `voiceover` — the voiceover is the interior translation of what was just said vs. what was meant.
VOICEOVER: inner monologue revealing what the image cannot show — the gap between performed calm and actual desire. Russian language. Quiet, private, the thing she would never say aloud.

SOUND DESIGN (sound_design) — required for EVERY panel:
- Dark romance sonic palette: near-silence, ambient room tone, the sound of fabric, a glass set down, breath, rain on a window, a distant clock
- Sustained silence before a charged moment is worth more than any score
- MANDATORY: at least one panel per scene must have sound_design="silence — only breath audible" as deliberate setup for the next panel's spoken line or sonic event
- J-cuts: next scene's ambient sound bleeding in before the visual cut creates seamless intimacy

PANEL TYPE:
- narrative: standard story panel with character presence and desire/restraint dynamic
- atmosphere_insert: MANDATORY — exactly one per pov/connection episode, at panel 7 or 8. A single object or environmental detail that carries the episode's entire emotional charge with no character present:
  * OBJECT: extreme macro of the prop that connects them (a glass with her lipstick on the rim, a book with his handwriting, a ring left on a surface)
  * ENVIRONMENT: the space they just left — empty chair, the window he stood at, the door now closed
  Duration 3–4s. No dialogue, no voiceover. The sound from the surrounding panels spills over this image.

**EACH SCENE MUST HAVE EXACTLY 9 PANELS following the structure above.**

SCENE-LEVEL CAMERA AND LIGHTING MASTER:
For every scene, generate:
- camera_master: dominant lens (mm), angle, and primary lighting condition shared by all panels.
- lighting_master: key light direction/color/quality, fill ratio, visible practicals. All panels must stay within this DNA — state deviations explicitly in that panel's lights_and_camera.
