
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
(Applies to panel_type=narrative only. For atmosphere_insert: fill question 3 with the single environmental element that carries all the drama; fill question 4 with how that element changes state. Skip questions 1–2.)

**visual_start must answer three questions in one image:**
1. WHO has power right now, and WHO doesn't? — Show it through spatial position, posture, or a prop.
2. WHAT specific emotion is visible on the primary face? — Write the physics: "jaw set, lips compressed, eyes tracking her hands." The AI renders what you describe.
3. WHAT detail signals something is at stake? — A door left open, a phone face-down, hands too close, a glass at the edge of a table.

**visual_end must show a state transition with dramatic weight — not a completed action:**
- A decision made visible, a boundary crossed, a contradiction revealed.
- NEVER write visual_end as "the action is done." visual_end is a NEW UNSTABLE STATE.

**ARC BRIDGE EXCEPTION — any episode's final panel (arc_bridge):**
visual_end must show physical suspension: the action is mid-motion and frozen.
The hand is raised, the finger is 1cm from the target, the mouth open and the word unspoken.
The drama has not crossed its threshold. The cut happens before the action completes.
motion_prompt MUST end before the action resolves — describe the approach and the last frame before completion, then stop.
Plan a match_cut shape in visual_end that will connect to the next episode's arc_pickup visual_start.

**ARC PICKUP EXCEPTION — any episode's first panel (arc_pickup):**
visual_start continues from the previous episode's arc_bridge visual_end: same location, same character, same physical position, 1–2 seconds later.
motion_prompt begins from where the bridge ended — the action now completes.
Voiceover carries the character's inner decision at the moment of crossing.

**motion_prompt DRAMATIC PHYSICS — hesitation and micro-decision carry more drama than the action itself:**
WRONG: "He picks up the phone and calls."
RIGHT: "At 0s phone sits on table, hand rests 10cm to the right. At 1.5s fingers move left, stop 3cm from phone. At 3.0s index finger contacts screen but does not press. At 5.0s hand withdraws into a fist — phone uncalled."

## 9-PANEL STRUCTURE BY EPISODE TYPE

### arc_open — First Episode of the Arc Unit

Mandatory panel structure:
- P1: cold_open — most arresting image, zero context, maximum visual tension. hook_type: cold_open. [≈0–6s]
- P2: verbal_hook — character speaks the arc's central conflict in ≤8 words: ultimatum, threat, confession, or challenge. CU on speaker's face. hook_type: verbal_hook. [≈7s mark]
- P3: context — orient the viewer through action, not exposition. One MS or WIDE shot.
- P4: first_escalation — first obstacle, complication, or pressure arrives.
- P5: emotional_capture — point of no return: an action taken, a line crossed, a secret revealed. hook_type: emotional_capture. [≈30s mark]
- P6: rising_action — stakes raised further. A new obstacle or revelation that makes escape impossible.
- P7: atmosphere_insert — panel_type: atmosphere_insert. No dialogue, no character close-ups. Duration 3–4s.
- P8: mid_revelation — new information changes the context of everything shown so far. Sets up what follows.
- P9: arc_bridge — hook_type: arc_bridge. Physical suspension: action frozen mid-motion at the threshold. sound_design: silence. motion_prompt ends before the action resolves.

### arc_mid — Middle Episode (only in N=3 arcs)

Mandatory panel structure:
- P1: arc_pickup — hook_type: arc_pickup. Same location/moment as previous arc_bridge, 1–2 seconds later. Voiceover carries the inner decision.
- P2: escalation_return — pressure from arc_open returns with increased force.
- P3: complication — a new obstacle, dimension, or character reframes the situation.
- P4: rising_pressure — the complication compounds; no clear exit visible.
- P5: atmosphere_insert — panel_type: atmosphere_insert. Duration 3–4s.
- P6: new_revelation — information that reframes arc_open's events and makes arc_close's confrontation inevitable.
- P7: stakes_raised — the cost of the new revelation becomes visible and irreversible.
- P8: pre_confrontation — the collision between forces is now inevitable; characters are on the collision course, closing distance.
- P9: arc_bridge — hook_type: arc_bridge. Physical suspension. sound_design: silence. motion_prompt ends before action resolves.

### arc_close — Final Episode of the Arc Unit

arc_close behavior differs slightly by arc length (N):

**N=2 arc (arc_close follows arc_open directly):**
Confrontation must build fast — no arc_mid pre-warmed it. P2 is immediate escalation, not a slow pickup.
- P1: arc_pickup — hook_type: arc_pickup.
- P2: escalation_return — immediate return of full arc_open pressure plus new weight from mid_revelation.
- P3: confrontation_build — collision now inevitable; characters accelerate toward it.
- P4: confrontation_peak — maximum conflict. ECU on face. The fulcrum.

**N=3 arc (arc_close follows arc_mid):**
The confrontation is already boiling. Arrive at it immediately.
- P1: arc_pickup — hook_type: arc_pickup.
- P2: confrontation_build — collision is already in motion from arc_mid.pre_confrontation.
- P3: confrontation_peak — maximum conflict. ECU on face. The fulcrum.
- P4: peak_intensity — the confrontation at its absolute summit before it breaks.

**Panels P5–P9 are identical regardless of N:**
- P5: atmosphere_insert — panel_type: atmosphere_insert. Duration 3–4s. Transition in via smash_cut.
- P6: twist — one fact changes everything. Arrives visually: a prop, a reflection, a door opening.
- P7: reversal — power dynamic inverts. Delivered through physical action or discovery.
- P8: consequence — the visible, irreversible cost of the reversal. Not resolution — the aftermath is still open.
- P9: cliffhanger — hook_type: cliffhanger. Freeze on maximum unresolved tension. One visible element, two possible interpretations. End mid-breath. Never resolve. Never summarize. [The Button]

### transition episode
Atmosphere-only. ALL 9 panels are atmosphere_insert. No dialogue, no character conflict, no close-ups.
Serves as visual bridge between two arc units. See episode_type_transition.md for full spec.

## MOTION PROMPTS

MOTION_PROMPT PHYSICAL REALISM — the video model renders every word literally:
1. Physical movements only, no emotional language. Use joint angles, degrees, distances.
   WRONG: "he recoils in horror"  RIGHT: "at 1.5s his eyes open wide, jaw drops ~2 cm, upper body leans back 10°"
2. No spectacle verbs: erupts/sprays/fountains/explodes → describe the minimal physical event.
3. No speed metaphors: "blurring speed" → use explicit timestamps and distances.
4. Anatomically correct scale: a tear is a 2–3 mm bead, not "rivers".
5. Ask before writing: could the AI render this as a grotesque artifact? If yes, rewrite.

MOTION PROMPTS for vertical format:
- Prefer vertical camera movements: tilt up/down, vertical dolly, snap zoom into eyes
- Match motion intensity to emotional_beat (dread = slow creep, shock = snap cut energy, rage = handheld shake)
- For shock/revelation panels: "camera snap-zooms into subject's eyes over 0.5s"
- Duration ~6s per panel; motion should resolve visually but not narratively

## CINEMATOGRAPHY TECHNIQUES

TILT REVEAL — vertical-format signature:
Reveal information progressively top-to-bottom or bottom-to-top.
Mandatory for at least one confrontation or twist panel per arc unit.

MICRO-EXPRESSION CLUSTER — rapid escalation:
2–3 consecutive ECU panels (arc_open.p3–p5 or arc_mid.p2–p4) at 1–2s each with transition_to_next=jump_cut.
Each shows the same face in a different emotion: calm → surprise → fear.
Locked ECU, no camera movement — only face micro-muscle shifts.

BOKEH / SELECTIVE FOCUS — attention direction:
In escalation and twist panels, shallow DOF isolates a single foreground object.
lights_and_camera: "shallow DOF, [object] sharp in foreground, subject/background as bokeh."

SHADOW & SILHOUETTE — indirect reveal (escalation/confrontation):
Show threat, emotion, or subject through shadow or silhouette — never directly.

REFLECTION REVEAL — hidden truth (twist panels):
Character's real state in a reflective surface while their face performs the opposite.

RACK FOCUS — prop-to-face revelation (escalation/confrontation):
Camera static. Foreground object sharp, face as bokeh. At peak, pull focus to face.

MATCH CUT — visual shape continuity:
Plan visual_end of one panel to share a geometric shape or motion vector with visual_start of the next.
MANDATORY: at least one match_cut per episode in the escalation zone.
MANDATORY: plan the arc_bridge → arc_pickup seam as a match_cut across the episode boundary.

## SOUND

DIALOGUE: ≤8 words, CU on speaker's face. Populate both `dialogue` and `voiceover` for inner counterpoint.
VOICEOVER: inner monologue revealing what the image cannot show. Russian language.

SOUND DESIGN (sound_design) — required for EVERY panel:
- Deliberate sonic contrast: sustained silence broken by a sharp sound > continuous noise.
- MANDATORY: at least one panel per episode must have sound_design="silence" as setup for the next panel's sonic event.
- arc_bridge (any): sound_design=silence — the episode cut is a sonic reset.
- arc_pickup (any): begins into silence, then rebuilds.
- For j_cut: describe the next panel's audio that bleeds in.

TRANSITION TO NEXT PANEL (transition_to_next):
- match_cut: share geometric shape or motion vector with next visual_start. Name the match explicitly in motion_prompt.
- jump_cut: jarring cut, reduce duration to 2–3s. Use in escalation bursts and micro-expression clusters.
- smash_cut: maximum contrast — silence cuts to noise, stillness cuts to chaos.
- j_cut: next panel's audio begins 1–2s before the visual cut.
- hard_cut: standard clean cut (default).
- arc_bridge → arc_pickup (episode boundary): plan as match_cut in both visual_end of bridge and visual_start of pickup.

PANEL TYPE (panel_type):
- narrative: standard story panel.
- atmosphere_insert: exactly one per episode (arc_open.p7 / arc_mid.p5 / arc_close.p5). Duration 3–4s. No dialogue, no character close-ups.
  * ENVIRONMENTAL: 1–2 macro-scale elements. visual_start: "minimalism: [element], [light condition], hyper-realistic. No people, no faces."
  * TEXTURE/DETAIL: extreme macro of a single physical surface. Shallow DOF, fills the frame.
  Transition in/out via smash_cut or match_cut.

**IMPORTANT: EACH SCENE MUST HAVE EXACTLY 9 PANELS following the structure above.**

SCENE-LEVEL CAMERA AND LIGHTING MASTER:
- camera_master: dominant lens (mm), angle, primary lighting condition — shared by all panels in this scene.
- lighting_master: key light direction/color/quality, fill ratio, visible practicals.
