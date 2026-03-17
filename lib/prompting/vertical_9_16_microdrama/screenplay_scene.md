
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

## VERTICAL MICRODRAMA CINEMATOGRAPHY — 9 PANELS PER SCENE

**PORTRAIT FRAME (9:16). Every decision is made for a phone screen held vertically.**

FRAMING HIERARCHY:
- ECU (Extreme Close-Up): eyes, hands, objects — for peak emotional moments
- CU (Close-Up): face from chin to forehead — default for dialogue and reaction
- MS (Medium Shot): chest up — confrontation, spatial relationship between characters
- WIDE: only when the environment is the dramatic agent (threat, scale, isolation)

ANGLE VARIETY RULE: No two consecutive panels may share the same shot scale AND the same camera angle. If P3 = CU / eye-level, then P4 must change at least one dimension: scale (ECU / MS / WIDE) OR angle (low / high / over-shoulder / oblique). Monotone shot sequences collapse rhythm. Force a change at every cut.

SAFE ZONE RULE: Compose all key subjects within the middle 65% of frame height.
Top 15% and bottom 20% must be visually clear (sky, wall, floor — no faces, no action).
Set text_safe_composition: true when this is achieved.

VISUAL DRAMATIC INTENSITY — WHAT GOES IN EVERY NARRATIVE FRAME:

**visual_start must answer four questions in one image:**
1. WHO has power right now, and WHO doesn't? — Show it through spatial position (standing over / cornered), posture (open vs. closed), or a prop (who holds the phone, the contract, the weapon).
2. WHAT specific emotion is visible on the primary face? — Not "he looks angry." Write the physics: "jaw set, lips compressed, eyes tracking her hands rather than her face." The AI renders what you describe.
3. WHAT detail signals something is at stake? — A door left open, a phone face-down, hands too close together, a glass at the edge of a table. One object carries the threat without naming it.
4. IS the character's signature visual tell present? — For any CU or ECU, the character's defining prop, mark, or gesture (as documented in their reference) must be explicitly described as visible, OR motion_prompt must explain why it is off-frame. Signature tells are the "fairy tale anchor" — without them, characters become generic faces. Never omit them at close range.

**visual_end must show a state transition with dramatic weight — not a completed action:**
- A decision made visible: the hand that finally reaches, eyes that finally meet, fingers releasing a grip that was held for panels.
- A boundary crossed: physical proximity breached, an object picked up or put down that shifts the power dynamic.
- A contradiction revealed: the suppressed smile when they should be devastated, the flash of real fear behind a performed confidence.
- NEVER write visual_end as "the action is done." visual_end is a NEW UNSTABLE STATE — it demands resolution in the next panel.

**motion_prompt DEFAULT — characters move. Every panel must have visible full-body physical action:**
People walk across rooms, gesture emphatically, turn away, step closer, grab objects, push past someone, sit down hard, stand up fast. A 6-second clip is a movie clip — something must visibly happen in physical space. Micro-expressions alone are dead screen.
WRONG: "character stands facing camera, jaw tightens, eyes shift left"
RIGHT: "At 0s Alisa strides from the door toward the table, 3 quick steps. At 3s she stops 80cm away, leans forward, plants both hands flat on the table surface. At 5s she locks eyes with him without breaking contact."
Default motion: at least one full-body or large-limb movement. Facial detail augments movement — never replaces it.

**motion_prompt HESITATION — use ONLY for a single life-altering decision moment (≤1 panel per episode, never P1–P3):**
Reserve for the exact instant a character faces a choice that changes everything: a trigger they may or may not pull, a call they may or may not make, a door they may or may not open. Maximum 3 seconds of visible deliberation before action resolves.
WRONG: applying hesitation to confrontation, argument, revelation, or any panel where narrative momentum must continue.
RIGHT: "At 0s hand hovers 5cm above the phone. At 2s finger descends and presses call. At 3s phone is already at ear — decision made."
If you are tempted to write hesitation for any other reason: don't. Move the character instead.

9-PANEL MICRO-ACT STRUCTURE (mandatory rhythm for pov_a / pov_b / confrontation episodes):
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
- Panel 3: escalation — first pressure or obstacle. [15s DEPTH TEST: this panel must be a second entry point — a viewer who missed P1-P2 must read the power dynamic, primary emotion, and stake object from this panel alone. Duration: 4–5s.]
- Panel 4: emotional_capture — point of no return: an action, revelation, or commitment the viewer cannot abandon. Must escalate from panel 3 in emotional temperature, not just plot. This is the "21-second lock" — if the viewer is still here, they are captured. [≈21s mark. Duration: 6s.]
- Panel 5: crystallization — stakes become visceral and irreversible; no exit. [30s COMPLETION TRIGGER: the episode's POINT OF NO RETURN. Also the strongest thumbnail candidate: compose for legibility as a static image, CU or ECU face with a recognizable ambiguous emotion, no key subject in text-overlay zone. Duration: 6–7s.]
- Panel 6: confrontation — peak conflict, ECU on face
- Panel 7: peak — maximum emotional intensity, the scene's fulcrum
- Panel 8: twist — one fact changes everything
- Panel 9: cliffhanger — freeze on maximum unresolved tension; end mid-breath [≈60–90s mark, the Button]. DIAGNOSTIC: the cliffhanger must end on an OPEN QUESTION, never a closed reveal. YOUTUBE NEXT-EPISODE THUMBNAIL: the final FRAME of visual_end is displayed as a static "next video" card. Require: (1) a face in CU/ECU showing an ambiguous, legible emotion that invites the question "what happens next?"; (2) a stake object visible in frame; (3) no key subject in bottom 20% text zone. The final frame must be click-worthy as a standalone image — it is simultaneously the cliffhanger and the next episode's implicit call-to-action. Reveals satisfy — the viewer gets the answer and leaves. Questions compel — the viewer must return to find out. WRONG: "We see Alisa is lying — the truth is now known." RIGHT: "Ruslan's eyes narrow on something we cannot yet see — what did he find?" If your P9 answers anything, move the answer to the next episode's P2 and end P9 on the moment just before.
  Choose one of four cliffhanger types based on context AND prior episode cliffhangers (rotate — never repeat the same type twice in a row):
  * PHYSICAL THREAT: character in immediate danger. Use sparingly — only at true climactic episodes. RISK: overuse causes fatigue; the viewer stops fearing.
  * SHOCKING REVELATION: new information reframes everything shown so far. Requires logical preparation in earlier panels — cannot arrive without a seed. Best at structural turning points.
  * EMOTIONAL RUPTURE: unexpected reaction, betrayal, or sudden silence where there should be words. Best for drama and romance arcs.
  * INTERRUPTED ACTION: cut mid-gesture, mid-word, mid-step. Best for routine episode transitions — lowest intensity, highest versatility.
  Record the chosen type in hook_type as: cliffhanger/physical_threat, cliffhanger/revelation, cliffhanger/emotional_rupture, or cliffhanger/interrupted_action.

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
VOICEOVER: inner monologue revealing what the image cannot show. {target_language} language.

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
- narrative: the only valid value. Every panel shows characters in action — faces, hands, power dynamics.

**IMPORTANT: EACH SCENE MUST HAVE EXACTLY 9 PANELS following the structure above.**

SCENE-LEVEL CAMERA AND LIGHTING MASTER:
For every scene, generate:
- camera_master: one sentence capturing the dominant lens (mm), angle, and primary lighting condition shared by all panels in this scene.
- lighting_master: one sentence capturing key light direction/color/quality, fill ratio, and any visible practicals. All panels must stay within this lighting DNA — deviations must be noted in that panel's lights_and_camera.

LOCATION REFERENCE NAMING — populate location_references per panel using EXACT split view names:
- Room refs are split into two views. Pick the one matching the camera angle in this panel:
  - `{Room-Name}-View-From-Entrance` — camera is at or near the entrance door, looking INTO the room
  - `{Room-Name}-View-To-Entrance` — camera is at the far end of the room, looking BACK toward the entrance
- Vehicle refs are split into three views:
  - `{Vehicle-Name}-Exterior` — camera outside the vehicle
  - `{Vehicle-Name}-Interior-From-Entrance` — camera inside, looking in from the driver/main door side
  - `{Vehicle-Name}-Interior-To-Entrance` — camera inside, looking toward the entrance from the rear
- Names must match existing refs EXACTLY (letters, digits, hyphens) — a mismatch silently skips the reference image during rendering.
