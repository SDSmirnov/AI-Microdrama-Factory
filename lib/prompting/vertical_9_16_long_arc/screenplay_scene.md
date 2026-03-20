
## SCREENPLAY_INSTRUCTIONS — YOUR PANEL-BY-PANEL BLUEPRINT

The episode JSON you receive contains a `screenplay_instructions` field with a per-panel blueprint (P1…P9).
For each panel, use its blueprint fields as **direct inputs**:
- `POWER` → drives spatial composition in `visual_start` (who is standing/sitting/cornered, who holds the prop)
- `EMOTION` → drives the primary face physics in `visual_start` and `visual_end`
- `STAKE OBJECT` → must appear as a visible element in `visual_start`; use for bokeh/rack focus where noted
- `STATE` → defines the dramatic delta between `visual_start` and `visual_end`
- `DIALOGUE SEED` → starting point for `dialogue`/`voiceover`; expand to full ≤8-word line
- `hook_type` in the bracket → set panel's `hook_type` field to the value after the `/`
- `SCALE` in the bracket → set the shot scale in `lights_and_camera`
- `LOCATION` in the bracket → set the scene location; for INTERCUT episodes, alternate locations per the INTERCUT rule
- `MATCH CUT SHAPE` (arc_bridge panel only) → plan visual_end geometry and `transition_to_next=match_cut`

For arc_bridge panels: `visual_end` must freeze the action at the threshold described in `MATCH CUT SHAPE` — hand 1cm away, word unspoken, door mid-swing.
For arc_pickup panels: `visual_start` must resume from the previous arc_bridge `visual_end` — same location, same physical position, 1–2 seconds later.

If `screenplay_instructions` lacks a blueprint entry for a panel (e.g. transition episodes), infer from narrative context.

## YOUTUBE COLD AUDIENCE TEST (mandatory for every arc_open.P1 and arc_pickup.P1)

YouTube delivers mid-season arcs to cold audiences — viewers who have never seen this series. They can land on arc 4, episode 1 with zero prior context. If they cannot read the situation within 3 seconds of P1, they scroll.

Cover the voiceover and dialogue in your mental image of P1's visual_start. Can a complete stranger read:
1. **WHO has power?** — visible through spatial position, posture, distance, or prop ownership. Not through backstory.
2. **WHERE are they?** — one visible environmental detail (desk + skyline = office, rain-streaked window = cafe, steering wheel = car).
3. **WHAT conflict is active RIGHT NOW?** — a physical action or reaction visible in the frame. Not backstory tension — current tension.

If any answer requires knowledge of prior episodes: rewrite visual_start.
FORBIDDEN: "the viewer already knows she betrayed him" — not visible on screen without context. Make the current conflict state PHYSICALLY READABLE through posture, distance, object placement, and immediate action.

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
Voiceover carries the character's inner decision at the moment of crossing — 4–5 words max.

**motion_prompt DEFAULT — characters move. Every panel must have visible full-body physical action:**
People walk, gesture, turn, approach, retreat, grab objects, lean in, stand up, sit down. A 6-second clip must show something visibly happening in physical space. Micro-expressions alone are dead screen.
WRONG: "character stands facing camera, jaw tightens, eyes shift left"
RIGHT: "At 0s Alisa strides from the door to the table, 3 quick steps. At 3s she leans forward and plants both hands flat on the surface. At 5s she locks eyes with him."
Default: at least one full-body or large-limb movement per panel.

**MOTION BUDGET — 6 seconds is a large amount of real time. Use it:**
A real human takes 0.2s to press a button, 0.5s to pick up a phone, 1s to stand up from a chair, 2s to cross a small room, 4–6s to run 30 meters. The AI defaults to writing one micro-gesture and stretching it to fill the clip — this produces near-static footage. Plan the motion_prompt as a complete physical arc that REALISTICALLY takes ~6s to execute:
- 6s budget: enter a room (1s) + approach someone (1.5s) + grab their wrist (0.5s) + force them to look at you (1s) + deliver line (2s)
- NOT: "slowly, deliberately raises the phone toward his ear over 6 seconds"
- NOT: "holds finger over the send button, hesitating, for the duration of the clip"
Fill the time. If the core action takes 1s, add what happens before and after — the approach, the reaction, the consequence. A panel where nothing new happens between second 1 and second 5 is a failed panel. Each timestamped beat in motion_prompt must describe a DIFFERENT physical state than the previous beat.

**motion_prompt HESITATION — use ONLY for a single life-altering decision moment (≤1 panel per episode, never P1–P3):**
Reserve for the exact instant a character faces a choice that changes everything. Maximum 3 seconds of deliberation before the action resolves.
WRONG: applying hesitation to confrontation, argument, revelation, or any panel where narrative momentum must continue.
RIGHT: "At 0s hand hovers 5cm above the phone. At 2s finger descends and presses call. At 3s phone is at ear — decision made."
If tempted to write hesitation for any other reason: don't. Move the character instead.
HARD ENFORCEMENT: If a single gesture or held position spans more than 3 seconds without a physical state change in the motion_prompt — HARD FAILURE. A thumb hovering for 6 seconds is 3 seconds of usable footage wasted. Add what happens before (approach) and after (contact, response) to fill the clip.

## 9-PANEL STRUCTURE BY EPISODE TYPE

### arc_open — First Episode of the Arc Unit

Mandatory panel structure:
- P1: cold_open — EXPLANATION HOOK, interaction already in progress. The viewer sees something happening and needs to understand it: "what IS this?", "who IS this person?", "why ARE they doing that?". Duration: 3s HARD CAP — set `duration: 3`, never 4, never 6.
  TECHNICAL CONSTRAINT: after autocut, only 1–2s of the 3s clip is visible. motion_prompt[0s] MUST describe an ongoing physical action — NOT a character position or setup pose. "At 0s: [action already in progress]".
  SELF-AUDIT: if motion_prompt[0s] contains "stands motionless", "sits still", "is perfectly still", "waits", "gazes", "stares" as primary state → HARD FAILURE. Rewrite.
  YOUTUBE ENTRY TEST: cover voiceover and dialogue. Can a stranger identify power, location, and active conflict from visual_start alone? If not, rewrite.
  Choose one of five hook archetypes:
  * STATUS REVERSAL: protagonist caught in humiliation or subjugation — the viewer asks "why is this happening to them?"
  * IMPOSSIBLE SITUATION: no visible exit — the viewer asks "how did they end up here?"
  * HIDDEN IDENTITY: someone acting in an unexpected way — the viewer asks "who IS this person really?"
  * TICKING CLOCK: a deadline or countdown already running — the viewer asks "what happens when it hits zero?"
  * SHOCKING REVELATION: someone reacting to something we haven't seen — the viewer asks "what did they just find out?"
  Record hook archetype in hook_type as: cold_open/status_reversal, cold_open/impossible_situation, cold_open/hidden_identity, cold_open/ticking_clock, or cold_open/revelation.
  REQUIRED in visual_start: characters actively doing something — arguing mid-sentence, mid-physical interaction, mid-reaction.
  FORBIDDEN: character sitting/looking/waiting; establishing shots; beauty-without-stakes; anticipation poses (hand hovering, "about to" act); any shot where the answer to "what is happening RIGHT NOW?" is "nothing yet." hook_type: cold_open. [≈0–3s, hard cap 4s]
- P2: verbal_hook — character delivers the arc's central conflict mid-confrontation in ≤8 words: ultimatum, threat, confession, or challenge. CU on speaker's face. Already mid-delivery at 0s. Duration hard cap: 4s. hook_type: verbal_hook. [≈4–7s]
- P3: context — orient the viewer through action, not exposition. One MS or WIDE shot.
- P4: first_escalation — first obstacle, complication, or pressure arrives.
- P5: emotional_capture — point of no return: an action taken, a line crossed, a secret revealed. hook_type: emotional_capture. [≈30s mark]
- P6: rising_action — stakes raised further. A new obstacle or revelation that makes escape impossible.
- P7: pivot — ECU reaction shot at peak pressure, before the revelation. Duration 3–4s. No dialogue — voiceover MANDATORY: 4–5 words of inner monologue, nothing more. Without it: a silent face with no text = dead screen for 80% of muted viewers = swipe. HARD FAILURE if voiceover is empty OR exceeds 5 words on any pivot panel.
- P8: mid_revelation — new information changes the context of everything shown so far. Sets up what follows.
- P9: arc_bridge — hook_type: arc_bridge. Physical suspension: action frozen mid-motion at the threshold. sound_design: silence. motion_prompt ends before the action resolves.

### arc_mid — Middle Episode (only in N=3 arcs)

Mandatory panel structure:
- P1: arc_pickup — hook_type: arc_pickup. Same location/moment as previous arc_bridge, 1–2 seconds later. Voiceover carries the inner decision — 4–5 words max.
- P2: escalation_return — pressure from arc_open returns with increased force.
- P3: complication — a new obstacle, dimension, or character reframes the situation.
- P4: rising_pressure — the complication compounds; no clear exit visible.
- P5: pivot — ECU reaction shot at peak pressure, before the new revelation. Duration 3–4s. No dialogue — voiceover MANDATORY: 4–5 words of inner monologue, nothing more. HARD FAILURE if voiceover is empty OR exceeds 5 words.
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
- P5: pivot — ECU reaction shot after peak confrontation, before the twist. Duration 3–4s. Transition in via smash_cut. No dialogue — voiceover MANDATORY: 4–5 words of inner monologue, nothing more. HARD FAILURE if voiceover is empty OR exceeds 5 words.
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

VOICE BUDGET (hard technical limit): 16 characters per second × panel duration = maximum characters for dialogue + voiceover COMBINED. For a 6s panel: 96 chars total. For a 4s panel: 64 chars total. Exceeding this budget causes TTS to either truncate or produce garbled audio in I2V rendering — the line will not fit the clip. Count characters before writing. If dialogue uses 50 chars, voiceover has ≤46 chars remaining. If a panel has no dialogue, voiceover may use the full budget. A panel with both a full dialogue line AND a full voiceover line will almost always exceed budget — choose one or split across panels.

DIALOGUE: ≤8 words per speaker line, CU on speaker's face. Populate both `dialogue` and `voiceover` for inner counterpoint.
VOICEOVER: inner monologue revealing what the image cannot show. {target_language} language. HARD LIMIT: 4–5 words only. It is a reactive flash — a thought that crosses the face before the character acts. Longer inner monologue is a novel; this is a phone screen.

DIALOGUE EXCHANGE CONTINUITY — HARD RULE (applies to ALL panels with dialogue, not just confrontation zone):
Any line of dialogue that is a direct question, demand, or a statement addressed to a specific person in the scene MUST receive its verbal response within the same panel OR the immediately following panel. NEVER cut away after a line that demands a verbal reply without showing that reply first.

This applies regardless of hook_type — emotional_capture, rising_action, complication, confrontation, all of them. If a character speaks TO another character and that other character would realistically say something back, the reply cannot be silently replaced by voiceover or a reaction ECU.

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
- For silent panels with no voiceover (a hard failure on its own — see above): the caption is the ONLY text the muted viewer sees. It must carry full emotional weight.

sound_design=silence CLARIFICATION: `sound_design=silence` means the ambient/music/SFX channels are zeroed. The voiceover TTS track plays independently and is NOT silenced. NEVER write "complete silence" or "no sound" when a voiceover is present — write "ambient silence, voiceover only." Complete silence = audio team will mute TTS = caption is the only thing muted viewers see.

SOUND DESIGN (sound_design) — required for EVERY panel:
- Deliberate sonic contrast: sustained silence broken by a sharp sound > continuous noise — for the 20-40% watching with audio. For the 60-80% watching muted, silence = nothing. Never design a beat that only lands if the viewer can hear the absence of sound.
- Sonic contrast panels (sound_design=silence) are valid ONLY when the same panel also has a voiceover line. A silent panel without voiceover is a dead screen for muted viewers. Do NOT mandate silence panels — use them only when they serve both audio-on AND audio-off audiences simultaneously.
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
- Names must match existing refs EXACTLY (letters, digits, hyphens) — a mismatch silently skips the reference image during rendering.
