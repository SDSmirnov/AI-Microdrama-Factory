
## INDEPENDENCE PROTOCOL — NON-NEGOTIABLE
Each panel is rendered by a separate image-generation model that receives ONLY that panel's text — no history, no context, no memory.
- FORBIDDEN: "same as before", "same POV", "same framing", "same appearance", "as in panel N", "continues from", "identical to", "as established".
- REQUIRED: Restate character appearance (hair, clothing, build, expression), carry items (bag on shoulder, holster, wallet pocket — wherever they keep things), location details, shot type, camera angle, and lighting in EVERY panel's visual_start and visual_end — even if they repeat word-for-word from the previous panel.
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
1. WHO has power right now, and WHO doesn't? — Show it through spatial position, posture, or a prop.
2. WHAT specific emotion is visible on the primary face? — Write the physics: "jaw set, lips compressed, eyes tracking her hands." The AI renders what you describe.
3. WHAT detail signals something is at stake? — A door left open, a phone face-down, hands too close, a glass at the edge of a table.
4. IS the character's signature visual tell present? — For any CU or ECU, the character's defining prop, mark, or gesture (as documented in their reference) must be explicitly described as visible, OR motion_prompt must explain why it is off-frame. Signature tells are the "fairy tale anchor" — without them, characters become generic faces. Never omit them at close range.

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
- P1: cold_open — IN MEDIAS RES. The viewer drops into mid-action, mid-confrontation, or mid-consequence. Something is ALREADY HAPPENING when the frame opens. Choose one of five hook archetypes that fits the source scene:
  * STATUS REVERSAL: protagonist caught in humiliation or subjugation — the viewer asks "how will they turn this around?" (exploits the human drive for justice)
  * IMPOSSIBLE SITUATION: no visible exit — the viewer asks "how do they get out of this?"
  * HIDDEN IDENTITY: someone in frame is not who they appear — the viewer asks "who is this really?"
  * TICKING CLOCK: a deadline or countdown is already in motion — the viewer asks "will they make it?"
  * SHOCKING REVELATION: something just happened off-frame — the viewer asks "what was that?"
  Record the chosen hook archetype in hook_type as: cold_open/status_reversal, cold_open/impossible_situation, cold_open/hidden_identity, cold_open/ticking_clock, or cold_open/revelation. A hand already extended with money. Eyes already locked in a challenge. A door that just slammed. An object mid-fall. The opening image must make the viewer ask "what the hell is happening RIGHT NOW?" — not "I wonder what will happen." The cold_open is NOT necessarily the chronological start of the episode: if the source scene opens with travel, setup, or neutral context, SKIP IT and open on the arc's first moment of tension or power shift instead. REQUIRED: a visible power dynamic (who is exerting pressure, who is cornered), a stake object already in play, or a micro-action already in motion — face showing strain, hand mid-gesture, body already reacting. FORBIDDEN for cold_open: character sitting/looking/waiting/traveling without active conflict; establishing location shots; beauty-without-stakes (reflections in windows, city lights on a passive face, a character at rest); any shot where the answer to "what is at stake right now?" is "nothing yet." hook_type: cold_open. [≈0–6s]
- P2: verbal_hook — character speaks the arc's central conflict in ≤8 words: ultimatum, threat, confession, or challenge. CU on speaker's face. hook_type: verbal_hook. [≈7s mark]
- P3: context — orient the viewer through action, not exposition. One MS or WIDE shot.
- P4: first_escalation — first obstacle, complication, or pressure arrives.
- P5: emotional_capture — point of no return: an action taken, a line crossed, a secret revealed. hook_type: emotional_capture. [≈30s mark]
- P6: rising_action — stakes raised further. A new obstacle or revelation that makes escape impossible.
- P7: pivot — ECU reaction shot at peak pressure, before the revelation. Duration 3–4s.
- P8: mid_revelation — new information changes the context of everything shown so far. Sets up what follows.
- P9: arc_bridge — hook_type: arc_bridge. Physical suspension: action frozen mid-motion at the threshold. sound_design: silence. motion_prompt ends before the action resolves.

### arc_mid — Middle Episode (only in N=3 arcs)

Mandatory panel structure:
- P1: arc_pickup — hook_type: arc_pickup. Same location/moment as previous arc_bridge, 1–2 seconds later. Voiceover carries the inner decision.
- P2: escalation_return — pressure from arc_open returns with increased force.
- P3: complication — a new obstacle, dimension, or character reframes the situation.
- P4: rising_pressure — the complication compounds; no clear exit visible.
- P5: pivot — ECU reaction shot at peak pressure, before the new revelation. Duration 3–4s.
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
- P5: pivot — ECU reaction shot after peak confrontation, before the twist. Duration 3–4s. Transition in via smash_cut.
- P6: twist — one fact changes everything. Arrives visually: a prop, a reflection, a door opening.
- P7: reversal — power dynamic inverts. Delivered through physical action or discovery.
- P8: consequence — the visible, irreversible cost of the reversal. Not resolution — the aftermath is still open.
- P9: cliffhanger — Freeze on maximum unresolved tension. One visible element, two possible interpretations. End mid-breath. Never resolve. Never summarize. [The Button]. DIAGNOSTIC: the cliffhanger must end on an OPEN QUESTION, never a closed reveal. Reveals satisfy — the viewer gets the answer and leaves. Questions compel — the viewer must return to find out. WRONG: "We see the truth is now known." RIGHT: "Eyes narrow on something we cannot yet see — what did they find?" If your P9 answers anything, move the answer to the next arc's opening and end here on the moment just before.
  Choose one of four cliffhanger types based on context AND prior arc cliffhangers (rotate — never repeat the same type twice in a row):
  * PHYSICAL THREAT: character in immediate danger. Use sparingly — only at true climactic arcs. RISK: overuse causes fatigue; the viewer stops fearing.
  * SHOCKING REVELATION: new information reframes everything shown so far. Requires logical preparation in earlier panels — cannot arrive without a seed. Best at structural turning points.
  * EMOTIONAL RUPTURE: unexpected reaction, betrayal, or sudden silence where there should be words. Best for drama and romance arcs.
  * INTERRUPTED ACTION: cut mid-gesture, mid-word, mid-step. Best for routine arc transitions — lowest intensity, highest versatility.
  Record the chosen type in hook_type as: cliffhanger/physical_threat, cliffhanger/revelation, cliffhanger/emotional_rupture, or cliffhanger/interrupted_action.

### transition episode
Environmental-only. ALL 9 panels: no character close-ups, no dialogue, no conflict.
Serves as visual bridge between two arc units. See episode_type_transition.md for full spec.

## MOTION PROMPTS

MOTION_PROMPT PHYSICAL REALISM — the video model renders every word literally:
1. Physical movements only, no emotional language. Use joint angles, degrees, distances.
   WRONG: "he recoils in horror"  RIGHT: "at 1.5s his eyes open wide, jaw drops ~2 cm, upper body leans back 10°"
2. No spectacle verbs: erupts/sprays/fountains/explodes → describe the minimal physical event.
3. No speed metaphors: "blurring speed" → use explicit timestamps and distances.
4. Anatomically correct scale: a tear is a 2–3 mm bead, not "rivers".
5. Ask before writing: could the AI render this as a grotesque artifact? If yes, rewrite.
6. ITEM ORIGIN — every retrieved object must come from a physically real place: "right hand moves to shoulder holster, draws pistol" / "opens bag hanging from left shoulder, removes phone" / "reaches into left breast pocket, produces badge wallet". NEVER write "pulls out a gun" or "takes out phone" — the model has no idea where the item was. The character's reference description defines where everything is carried.

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
VOICEOVER: inner monologue revealing what the image cannot show. {target_language} language.

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
- narrative: the only valid value. Every panel shows characters in action — faces, hands, power dynamics.

**IMPORTANT: EACH SCENE MUST HAVE EXACTLY 9 PANELS following the structure above.**

SCENE-LEVEL CAMERA AND LIGHTING MASTER:
- camera_master: dominant lens (mm), angle, primary lighting condition — shared by all panels in this scene.
- lighting_master: key light direction/color/quality, fill ratio, visible practicals.
