# PASS 3 — MOTION + AUDIO

Generate `motion_prompt`, `dialogue`, `voiceover`, `sound_design`, `duration`, and related fields.
Input: `visual_start` + `visual_end` from Pass 2 and `motion_intent` + `motion_action` from Passes 1/1A.

## What to produce
`motion_prompt`, `is_reversed`, `motion_prompt_reversed`, `dialogue`, `voiceover`, `voiceover_settings`,
`voiceover_timing`, `emotional_beat`, `hook_type` (refined), `transition_to_next`, `sound_design`, `caption`, `duration`

---

## IS_REVERSED — DECISION RULE

The I2V model does NOT support image references — it cannot show a character *entering* the frame while staying reference-accurate. The only workaround is **reverse playback**: render the character *leaving*, then play the clip backwards.

Set `is_reversed: true` for any panel where:
- A character enters the scene, walks in, or appears from off-screen.
- An object comes into view (door opens revealing someone, fog clears to show a figure, etc.).
- Someone approaches the camera from a distance.
- `visual_end` shows a presence that is **ABSENT** in `visual_start`.
- A character's FACE is hidden at `visual_start` (back to camera, hood up, silhouette, turned away) and is **REVEALED** during the motion (turns around, removes hood, steps into light facing camera). Shoot the character turning AWAY (face → back), reverse so viewer sees the face reveal.

When `is_reversed: true`:
1. Write `visual_start` and `visual_end` in **normal chronological order** — start = before the action, end = after. The pipeline swaps them automatically before rendering.
2. Write `motion_prompt` in normal chronological order (the pipeline generates `motion_prompt_reversed`).
3. Leave `motion_prompt_reversed` as an **empty string**.

When `is_reversed: false`: set `motion_prompt_reversed` to `""`.

---

## MOTION PROMPT

Describe what happens physically during the ~6s clip using the MANDATORY FORMAT below.

**JUST BEFORE ACTION LAW**: At 0s every in-frame actor MUST be in the pre-action pose from `visual_start`. The image model renders `visual_start` as the first frame — if motion_prompt opens mid-action, the rendered frame and the animation diverge. FORBIDDEN: "At 0s arm is already mid-swing", "At 0s she is already turning". EXCEPTION: `cold_open` P1 panels only.

### MANDATORY FORMAT

```
0s [ACTOR_A]: [POSE_TAG], [KEY_BODY_DETAIL verbatim from visual_start BODY_DETAIL].
0s [ACTOR_B]: [POSE_TAG], [KEY_BODY_DETAIL verbatim from visual_start BODY_DETAIL].  ← one line per in-frame actor
[T1s]→[T2s]: [ACTOR] [BODY_PART or "full body"] [MECHANICAL_VERB] [MEASUREMENT] to [NAMED_ANCHOR or PERSON_NAME].
[T2s]→[T3s]: [ACTOR] [BODY_PART] [MECHANICAL_VERB] [MEASUREMENT]. CONCURRENT: [BODY_PART] [VERB] if any.
[T3s]→6s: [ACTOR] settle — [BODY_PART] [FINAL_POSITION or DISPLACEMENT_cm].
OFF-FRAME: [NAME] is off-frame.  ← append only if character is in scene but not in frame; no actions
```

**Per-beat requirements — all 5 must be present in every timed line:**
1. **WHO** — character name (not "he", "she", "they")
2. **WHAT_PART** — specific body part or `"full body"` for locomotion
3. **MECHANICAL_VERB** — `grips` `pivots` `extends` `presses` `steps` `drops` `raises` `retracts` `rotates` `crosses` `retreats` `slides` `locks` `turns` `leans` `pulls` `pushes` `reaches` `releases` `tilts` `swings` — no emotional verbs
4. **MEASUREMENT** — explicit quantity from motion_dynamics.md or real-world estimate: `20 cm`, `45°`, `3 steps`, `0.8 m/s` — absent measurement = HARD FAILURE
5. **WHERE** — named anchor slug from `anchor_points` or canonical person name — NEVER bare `"forward"`, `"toward him"`, `"away"`, `"inward"`, `"outward"`

**Beat is HARD FAILURE if:** body state is identical to the previous beat (no change = video freeze artifact).

**100-word minimum** applies to the full motion_prompt. Camera tracking goes in `lights_and_camera`, not here.
- PROP POSITION INHERITANCE: if visual_end of previous panel fixed a prop location, open this panel with that EXACT position — same anatomy word, same distance. "shoulder" ≠ "neck" ≠ "collarbone". Approximation is a hard failure when it produces a physically different starting state.
- NEVER: "toward camera", "away from camera", "toward the lens", "toward viewer" — applies to ALL motion subjects: full body, limbs, body parts (head, torso, eyes, chin, gaze). "His head turns toward the camera" = HARD FAILURE.
- When `drama_requirements.movement_intent.type = "Pan"`, motion_prompt contains the world-space character action; the pan instruction belongs exclusively in lights_and_camera.

**motion_action → motion_prompt expansion**: expand the Pass 1A `motion_action` ("Jane walks to sofa; Jack stands") into a fully timestamped arc. Every beat must be a DIFFERENT physical state than the previous beat.

### CU/ECU BACKGROUND EXCLUSION LAW

For panels with `scale=CU` or `scale=ECU`, background characters who are outside the frame (per Pass 1A `in_frame=false`) MUST NOT receive any timed motion description in `motion_prompt`.

**HARD FAILURES:**
- "In the background, [Character] tightens her grip on the cane." → FORBIDDEN at CU/ECU. I2V will hallucinate this character into the frame.
- "At 3s, [Character] steps forward in the background." → FORBIDDEN. Remove entirely.
- Any reaction, body mechanic, micro-expression, or prop state change for an out-of-frame character → FORBIDDEN.

**Correct handling:** If an off-frame character's presence must be acknowledged, write exactly one neutral note at the END of `motion_prompt`: "[Character] is off-frame." No actions, no reactions, no position changes.

This applies to ALL out-of-frame characters regardless of their dramatic importance to the scene.

### MOTION BUDGET — 6 seconds is real time. Use it.

Real durations: button press 0.2s, pick up phone 0.5s, stand from chair 1s, cross small room 2s.
Plan a complete physical arc: approach (1.5s) + action (1s) + reaction/settle (3.5s).
If the core action takes <2s, add what happens before (approach) and after (contact, response, consequence).
A panel where nothing new happens between second 1 and second 5 is a failed panel.

### LIVING POSE LAW — humans are never still

A person at rest is not motionless. Autonomous nervous system produces continuous low-amplitude motion that must appear in every in-frame character at all times.

**Minimum idle budget per character per second in frame:**

| State | Required idle motion (at least one per second) |
|-------|------------------------------------------------|
| Listening | weight shift (2–5cm), small head tilt (3–8°), eye track to speaker or glance away then back, hand settles/resettles on surface, finger curls or uncurls, breathing-driven chest rise (~1cm/breath) |
| Thinking / internal | gaze breaks to neutral space then returns, jaw works slightly, free hand moves to face then drops, posture micro-adjusts (shoulder 1–2cm) |
| Talking | head nods accent the phrases (5–15° per accent beat), free hand rises for gesture then returns, torso turns slightly toward or away from listener between sentences, eyebrows move with emotional tone |
| Stressed / waiting | foot weight transfer every 2–3s, fingers drum or press together, thumb rubs index finger, lips compress and release |

**HOW TO APPLY in motion_prompt:**
- Every timed beat must include idle motion for ALL in-frame characters — even those not the primary actor.
- Interleave idle motion with the primary action: while one character performs the main action, describe the other's idle layer as a CONCURRENT note.
- DO NOT stack idle motions into one dump at the end. Distribute across the timeline.

WRONG: `"0s→4s: Robert speaks. 4s→6s: Amanda nods once."` — 4 seconds of Amanda frozen.
RIGHT: `"0s→2s: Robert speaks, head nodding on emphasis. CONCURRENT: Amanda's weight shifts 3cm onto her right foot, left hand resettles on her knee. 2s→4s: Robert's free hand lifts 10cm and drops back. CONCURRENT: Amanda's chin tilts 5° tracking his face. 4s→6s: Robert jaw releases. CONCURRENT: Amanda draws a slow breath, chest rises 1cm, shoulders settle."`

### TEMPORAL COMPRESSION LAW

If a physical action sequence takes ≤4 seconds in real life → encode as ONE panel.
WRONG: "running" P3 + "shouts while running" P4 + "door hits face" P5 (3 panels for 4 real seconds).
RIGHT: one panel, motion_prompt covers sprint + shout + door impact + hold.
Any `transition_to_next=hard_cut` between two panels that both describe parts of the SAME physical action = red flag, merge them.

### SLOW-MOTION CONSTRAINT

Do NOT write speed transitions within a single clip (normal speed → slow-mo or vice versa). Video models render the entire clip at one speed.
If slow-motion is needed for a key impact moment, set the entire clip's motion to slow-motion in both motion_prompt and `lights_and_camera` — never as a mid-clip transition.
WRONG: "At 3s the impact happens; time slows to half speed." RIGHT: "Clip is slow-motion throughout. At 0s arm is mid-swing. At 1.5s fist contacts jaw in slow motion. Camera holds on falling figure."

### ACTION-THEN-REACTION LAW

A physical action (strike, cut, fall, grab, garment drop) COMPLETES within its panel.
Reaction shots come AFTER — never interleaved.
Any cut/strike/garment event taking ≤3 real seconds = ONE panel. Next panel opens on OUTCOME STATE.

### COMBAT / CONTACT SEQUENCES

Wind-up + strike + target reaction = one continuous arc of ≤4 seconds = ONE panel.
Impact + immediate consequence (push→stumble, shove→door, throw→crash) = one clip.

### TABLEAU FAILURE — HARD ENFORCEMENT

Any segment where the only visible motion is eye movement, micro-expression, or breathing for ≥2 consecutive seconds = TABLEAU FAILURE.
WRONG: "From 1s to 3.5s, her eyes slowly scan his posture." — 2.5s of eye motion only.
WRONG: "At 0s the scene is held in tense silence, no one moves." — dead screen regardless of emotional intent.
RIGHT: fill the segment with approach, turn, reach, grab, step back, or any large-limb action.
EXCEPTION: `pivot` panels in ECU format are exempt ONLY if BOTH:
(a) an environmental element moves continuously (wind in hair, light pulse, curtain flutter), AND
(b) at least one **large-limb action** per 2s segment — torso turn, arm raise/drop, head pivot ≥15°, step, weight shift onto opposite foot. Micro-expressions (blink, jaw clench, eye movement) do NOT qualify.
If neither → still HARD FAILURE.
ENVIRONMENTAL-ONLY MOTION RULE: smoke, dust, curtain, or light shift does NOT exempt characters from movement. A panel where characters are described as "motionless" while environmental elements move is ALWAYS a HARD FAILURE.

### FALLEN/INCAPACITATED CHARACTER — CONTENT MODERATION RULE

I2V platforms apply post-generation content moderation. A human body lying completely still on the floor = classified as a dead body = clip blocked regardless of context.

**HARD RULE**: any panel where a character falls, is struck down, or collapses MUST NOT end on full gravitational rest (all limbs static, no motion).

**Required**: the clip must end BEFORE the body reaches complete stillness — OR include active motion in the settle phase:
- Character attempts to rise: `"left arm presses 3 cm into carpet"`, `"head lifts 2 cm"`
- Reactive limb motion: `"right leg slides 5 cm along carpet"`, `"fingers flex 5°"`
- Environmental cover: debris still moving, dust settling, prop still rolling

**PREFERRED ALTERNATIVE**: cut the panel at impact + immediate consequence (~2–3s). Open the next panel with the character already in the fallen state, now attempting to move. This splits the blocked content cluster across two panels and eliminates the dead-body settle entirely.

### PHYSICAL VOCABULARY — replace emotion words with body mechanics

| Emotion | Physical encoding |
|---------|------------------|
| Fear/Dread | retreats 10–15cm, spine presses to wall, shoulders rise, eyes sweep to exit |
| Anger/Rage | slams palm, jabs finger toward [Target], steps 20cm toward [Target], jaw clamps, chin juts 3–5cm toward [Target]'s face |
| Shame/Guilt | gaze drops, chin drops toward chest, shoulders curl inward over sternum, arms self-hug, weight transfers onto rear foot |
| Grief | shoulders collapse 3–5cm, hands drop, gaze defocuses, jaw releases |
| Contempt | upper lip tightens unilaterally, head tilts back 5–10°, weight rearward |
| Shock | brows flash up 0.3s then soften, body stills 0.5s, hands freeze, then reactive motion |
| Desire | closes distance 10–15cm, rotates from three-quarter toward side profile directed at [Other], chin lifts 3° |
| Dominance | steps 20cm toward [Other], side profile chest directed squarely at [Other] while [Other]'s gaze breaks away |
| Doubt/Uncertainty | gaze breaks to frame-right then returns, weight shifts to one foot, hand lifts toward chin then drops, blink rate increases |
| Relief | shoulders drop 2cm, jaw releases visible tension, chest drops on exhale through nose, fist opens |

No spectacle verbs: erupts/sprays/explodes → describe minimal physical event.
No speed metaphors: use explicit timestamps and centimeter distances.
FORBIDDEN VISUALS in motion_prompt: tears (any form), sweat, breath vapor, oral liquids — replace with body-action equivalents.
FORBIDDEN BREATH VISUALS: any description where an exhale or breath is *visible* — "visible breath", "wisp of breath", "vapor from nose/mouth", "steam from mouth", "condensation from lips", "breath dissipates", "breath cloud", "fog of breath", "visible exhale" — ALL FORBIDDEN. Breath is invisible in cinematic I2V; the model renders it as smoke/fog artifact. Encode exhale purely as body mechanics: "chest drops 1cm on exhale", "shoulders settle 2cm", "jaw releases tension".
FORBIDDEN METAPHORS: figurative/poetic language describing physical state. Write the literal anatomical event.
  WRONG: "his hand remaining a fixed iron shackle on her arm" / "she crumbles like paper" / "his gaze pins her to the wall"
  RIGHT: "his hand maintains a firm grip on her forearm, fingers not releasing" / "her knees buckle 5cm, weight transfers onto rear foot" / "his gaze holds steady on [Target]'s face, chin juts 3° toward [Target]"
FORBIDDEN BARE DIRECTIONS: "forward", "backward", "toward", "away", "inward", "outward" without a named anchor or target.
  I2V models interpret bare direction words as relative to camera — "steps forward" = steps toward lens, "arm extends forward" = arm reaches toward lens, "head juts forward" = head moves toward lens.
  Every direction MUST resolve to a named destination or named person. This applies equally to full-body locomotion, limb extensions, head/torso micro-movements, and weight shifts.
  WRONG: "steps forward" / "leans toward him" / "moves away" / "turns inward" / "arm extends forward" / "head juts forward" / "weight shifts forward onto lead foot" / "walks away from the camera"
  RIGHT: "steps toward [entrance-door]" / "leans toward [Jane] across the table" / "retreats to the [sofa-wall]" / "turns to face the [window]" / "arm extends toward [Client]" / "head juts 10cm toward [Amanda]" / "weight transfers onto lead foot" / "walks from [her-desk] toward [Self-Service-Terminal]"

### SPATIAL LANGUAGE

Frame-space (viewer perspective): always prefix "frame-": frame-left, frame-right, upper-frame-left.
Anatomy: always possessive: "his left hand", "her right shoulder". When both matter: "his right hand (frame-left)".
NEVER bare "left" / "right" for spatial positions.

### ITEM ORIGIN

Every object retrieved must come from a named physical location:
- RIGHT: "right hand moves to shoulder holster, draws pistol"
- WRONG: "pulls out a gun"
The character's reference description defines where everything is carried.

---

## CINEMATIC MOTION TECHNIQUES

**TILT REVEAL** — use in confrontation or twist: start on feet/hands, slow tilt to face (or reverse).
Mandatory for at least one confrontation or twist panel per scene.

**MATCH CUT** — plan visual_end of one panel to share a shape/vector with visual_start of the next.
Mandatory: at least one match_cut in the escalation zone (panels 3–5).

**MICRO-EXPRESSION CLUSTER** — 2–3 consecutive ECU panels at 1–2s each, `transition_to_next=jump_cut`.
Each shows a different micro-emotion: calm→surprise→fear, doubt→recognition→dread. Locked ECU on eyes only.

**SHADOW / SILHOUETTE** — show threat through shadow on wall or backlit silhouette; never the subject directly.

**RACK FOCUS** — compose `visual_start` with foreground object sharp + subject as background bokeh.
FORBIDDEN in motion_prompt: "rack focus pulls", "focus shifts" — I2V cannot change focal plane.
If both focus states needed: two separate panels with hard_cut.

---

## AMBIENT BACKGROUND MOTION

When a `BACKGROUND ACTIVITY` block is injected, append a single `AMBIENT:` note at the **end** of `motion_prompt` — after all primary actor timed beats.

**Format:**
```
AMBIENT: [crowd_type] in [depth_plane] — [continuous movement description].
```
Example:
```
AMBIENT: bank clerks and customers in mid-to-far background — slow drift between teller counters, occasional paper exchange, continuous low-level ambient motion throughout clip.
```

**Hard rules:**
- ONE `AMBIENT:` line only — no timestamps, no per-beat progression.
- Only for panels where Pass 2 wrote a `BGD:` line (i.e., MS/MWS/WS/XWS panels). Skip at CU/ECU/Macro.
- Background figures are NEVER given individual timed actions. "At 2s, a customer walks to the counter" → HARD FAILURE.
- `AMBIENT:` motion must not be louder or more complex than the primary actor beats combined. One sentence maximum.
- Background figures do NOT appear in `references[]` and must NOT receive reactions, expressions, or prop interactions.
- Background figures may NOT enter or exit frame during the clip.

---

## AUDIO

### VOICE BUDGET (hard technical limit)
24 characters/second × duration = max chars for `dialogue` + `voiceover` COMBINED.
6s panel = 144 chars. 4s panel = 96 chars. Count before writing — TTS truncates on overflow.

### MANDATORY VOICE COVERAGE
Every panel MUST have `dialogue` OR `voiceover` populated. Both empty = HARD FAILURE.

### CONSTANT CHANGE LAW
At every second: either visible physical motion OR subtitle text appearing on screen.
Two consecutive seconds with neither = viewer assumes stream is frozen = swipe.

### SILENCE IS INVISIBLE
For 60–80% of muted viewers, "dramatic silence" = dead screen. A panel with `sound_design=silence` + no voiceover + no dialogue = HARD FAILURE. Every "silent" panel MUST have voiceover for muted viewers.

### DIALOGUE
- ≤8 words per line. Staccato. Emotionally specific.
- Include speaker name + gender indicator.
- Delivered in CU on speaker's face.

### VOICEOVER
- Inner monologue only — no voice/gender prefix in the text field. Those go in `voiceover_settings`.
- Never narrates the obvious.
- INNER MONOLOGUE HARD LIMIT: 4–5 words for pivot panels (P7). "He knows." / "Not now."

### VOICEOVER + DIALOGUE TIMING
When both non-empty, set `voiceover_timing`:
- `before_dialogue` — VO plays first, then spoken line (default for inner reaction)
- `after_dialogue` — spoken line first, then VO (default for consequence beats)
- `under_dialogue` — simultaneous low mix (use rarely)
- `during_silence` — VO in a silent gap (mark gap in motion_prompt)

HARD DEFAULT: if voiceover is a reaction to dialogue (character heard something and thinks), use `after_dialogue`. Never leave timing ambiguous when both fields are populated.

### POV ENFORCEMENT
If episode declares `pov_character`, ALL inner monologue must be from that character's perspective.

### DIALOGUE EXCHANGE CONTINUITY
A direct question, demand, or addressed statement MUST receive its verbal response in the same panel OR the next panel immediately.
FORBIDDEN: cut away after an unanswered question. Moving a spoken response to voiceover = HARD FAILURE.

**HOW TO HANDLE MULTI-TURN EXCHANGES:**
1. SHORT EXCHANGE (Q+A, ≤2 turns, total ≤80 chars): pack both sides into one panel's `dialogue` field.
   Format: `"Speaker1 (voice): Line1\nSpeaker2 (voice): Line2"` — camera holds on LISTENER's face during the reaction turn.
2. LONGER EXCHANGE (3–4 turns): two consecutive panels. Panel N = challenge (CU on speaker), Panel N+1 = counter (CU on responder). Do NOT skip the counter to advance the emotional arc — the counter IS the arc.

**EXCHANGE COMPLETENESS CHECK:**
- Does this panel's dialogue leave an open question the next panel doesn't answer? → HARD FAILURE.
- Does the next panel presuppose an exchange the viewer never heard? → Include the trigger line in this panel.
- Is voiceover carrying a response that should be spoken dialogue? → HARD FAILURE: move it to dialogue.

### ACTION THREAD LAW

Any physical action introduced in a panel creates an OPEN THREAD. The next panel MUST resolve it.

OPEN THREAD — any panel where:
- A character moves toward someone/something but hasn't arrived
- Physical contact is attempted but not completed (reaching for object, arm raised to strike)
- An object is handed, pointed, or picked up but the recipient hasn't reacted

RESOLUTION RULE — the NEXT panel's `visual_start` MUST show one of:
1. **COMPLETION**: the action reached its endpoint ("his hand now closes around her wrist")
2. **INTERRUPTION**: another event stopped the action — stated explicitly in `visual_start`
3. **TIME-SKIP**: only valid with `transition_to_next=hard_cut` + location/time change

FORBIDDEN:
- Panel N: "she reached for the phone" → Panel N+1: unrelated beat, phone outcome unknown
- Panel N: arm raised → Panel N+1: both characters in pre-gesture positions, no explanation

### SOUND DESIGN

`sound_design` field required for EVERY panel. Captures sonic atmosphere separate from dialogue/voiceover.
- `sound_design=silence` means ambient/music/SFX channels are zeroed. The voiceover TTS track is NOT silenced.
- NEVER write "complete silence" or "no sound at all" when a voiceover is present — write `"ambient silence, voiceover only"`.
- Plan sonic contrast deliberately: sustained silence broken by a sharp sound is more powerful than continuous noise.
- For j_cut transitions: describe next scene's audio bleeding in: `"J-cut: rain ambient from next scene starts at 5s"`

### CAPTION CONTRACT
`caption` = persistent bottom-third hook overlay. ≤40 characters.
NEVER narrates the visible action. Delivers subtext or an open question that makes the viewer scroll-stop.
WRONG: "He called her number." RIGHT: "Thirty-one nights. One cracked screen."
SELF-TEST: if a stranger saw only the image + caption, would they pause their scroll? If no → rewrite.

### TRANSITION TYPES

Set `transition_to_next` per panel:
- `hard_cut` — standard clean cut (default)
- `match_cut` — visual_end geometry shares a shape/vector with next panel's visual_start. Name the match in motion_prompt: `"MATCH CUT: upward diagonal to next panel."`
- `jump_cut` — intentional jarring cut, 2–3s duration. Use in escalation bursts and micro-expression clusters.
- `smash_cut` — maximum contrast: silence cuts to noise, stillness to chaos. Capture contrast in sound_design.
- `j_cut` — next panel's audio begins 1–2s before the visual cut. Describe the audio in sound_design.

---

## POST-WRITE MOTION AUDIT (run on EVERY panel before finalizing)

1. **FREEZE CHECK**: any segment ≥2s with no change in physical body state → HARD FAILURE. Add motion. **LIVING POSE CHECK**: scan every in-frame character — does each have at least one idle motion token (weight shift, head tilt, breath rise, hand reposition, eye track) per second of screen time? Any character frozen for ≥1s without idle motion → HARD FAILURE. Apply the LIVING POSE LAW table.
2. **VOICE CHECK**: both `dialogue` and `voiceover` empty → HARD FAILURE.
3. **INTENT CHECK**: every beat in `motion_prompt` serves `motion_intent`? Dead beats ("remains still", "holds position", "the characters are motionless", "stands watching") → replace with purposeful action. SECONDARY CHARACTER CHECK: if `motion_action` for a secondary character was "stays still / watches" → expand into a body-level reactive action (weight shift, grip change, head turn ≥15°, prop adjustment) for every timed beat they appear in.
4. **TIMING LAW CHECK**: `visual_start` BODY_DETAIL matches `0s [ACTOR]` line verbatim? If mid-action or residual from previous panel → rewrite both. Does the first timed beat describe the subject ALREADY mid-action (arm mid-swing, body already turning)? → HARD FAILURE. The `0s` line must be the pre-action pose. EXCEPTION: `cold_open` P1 only.
5. **COMBAT CHECK**: two consecutive panels both describe parts of the same impact sequence → merge into one.
6. **FORBIDDEN VISUALS CHECK**: scan ALL visual_start, visual_end, and motion_prompt for: tears (any form — running, filling, glinting, "eyes brimming", "tear tracks", "moisture"), sweat (glistening, dripping, damp/shiny skin), breath vapor or mouth condensation, any oral liquid (saliva, drool, spittle) → HARD FAILURE. Replace with body-action equivalents: jaw clenches, lip bites, chin trembles, shoulders collapse, chest heaves.
   Also scan for ANY **visible breath** description: "visible breath", "wisp of breath", "vapor from nose/mouth", "steam from mouth", "breath dissipates", "breath cloud", "fog of breath", "visible exhale" → HARD FAILURE. Breath is invisible in cinema. Encode as body mechanics only.
7. **THREAD CHECK**: does panel N leave a physical action unresolved? Does panel N+1's visual_start open on the outcome? If not → rewrite panel N+1's visual_start.
8. **GAZE CHECK**: "looks at camera", "stares into lens", "gazes at viewer" without "DIRECT CAMERA ADDRESS" label → HARD FAILURE.
9. **CAMERA-MOVEMENT CONFLATION CHECK**: "toward camera", "away from camera", "toward the lens", "walks away from the camera" in motion_prompt → HARD FAILURE. This rule applies equally to body parts: "his head turns toward the camera", "her gaze drifts toward the lens", "chin lifts toward viewer" → HARD FAILURE. Replace with world-space target: "his head turns toward [entrance-door]", "her gaze tracks toward [Charlotte]". Also scan every direction word — "forward", "backward", "inward", "outward", "away", "toward" — for a named anchor or person immediately after. Missing target → HARD FAILURE. This covers ALL of: full-body locomotion ("steps forward" → "steps toward [door]"), limb extension ("arm extends forward" → "arm extends toward [Client]"), head/torso micro-motion ("head juts forward" → "head juts toward [Amanda]"), weight transfer ("weight shifts forward" → "weight transfers onto lead foot"), and posture lean ("leans forward" → "leans toward [Igor] across the desk"). PAN SPECIAL CASE: if `drama_requirements.movement_intent.type = "Pan"`, confirm motion_prompt contains the world-space character action the camera follows, and that the pan instruction itself is NOT in motion_prompt (belongs in lights_and_camera only).
10. **METAPHOR CHECK**: scan motion_prompt for figurative/poetic language ("iron grip", "crumbles", "melts", "pins her", "shackle", "floods") → HARD FAILURE. Replace with literal anatomical description.
11. **INTER-CHARACTER ORIENTATION CHECK**: every visual_start ACTOR line with 2+ characters has a PROFILE slot with an enumerated token (`FRONTAL`, `3Q-FRONT`, `SIDE`, `3Q-REAR`, `BACK`) AND a GAZE_TARGET pointing to the other character or an anchor? Missing PROFILE token → HARD FAILURE. Also check: `FRONTAL` for a character whose GAZE_TARGET is another person at frame-left or frame-right → CONTRADICTION (FRONTAL means facing the lens, not another character), HARD FAILURE.
12. **CU/ECU BACKGROUND EXCLUSION CHECK**: scan motion_prompt for timed actions attributed to characters with `in_frame=false` (those beyond ~1m at CU, anyone other than the subject at ECU). Any "In the background, [Character] does X" at CU/ECU scale → HARD FAILURE. Replace with "[Character] is off-frame." at end of prompt or remove entirely.
13. **IS_REVERSED CHECK**: does `visual_end` contain any character or object that is ABSENT in `visual_start`? Does any character enter the frame, approach from a distance, or reveal their face (was hidden → now visible)? If YES and `is_reversed=false` → HARD FAILURE. Set `is_reversed=true` and verify `motion_prompt_reversed` is left as `""`.
