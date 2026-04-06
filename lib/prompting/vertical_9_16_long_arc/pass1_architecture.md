# PASS 1 — SCENE ARCHITECTURE (long_arc)

Declare the **narrative skeleton** for this scene. Planning pass only.

## What to produce
For each panel output ONLY:
- `panel_index`, `hook_type`, `duration`, `scale`, `motion_intent`, `dialogue_seed`

**`motion_intent` PHYSICAL VERB LAW**: every `motion_intent` string MUST contain a concrete physical action verb (locomotion, prop interaction, or large-limb displacement ≥10cm): walk, turn, grab, open, close, step, push, pull, reach, rise, collapse, cross.
FORBIDDEN: emotion-only descriptions ("Robert processes the news", "Amanda's desperation shows"). Those describe inner state with no physical anchor.
WRONG: `"Robert pushes back, verbalizing the first major obstacle"` → no physical verb.
RIGHT: `"Robert steps back 20cm and shakes his head while delivering the legal objection"` → locomotion + head motion anchor the scene.
- `drama_requirements` — cinematic intent declared at architecture level:
  - `shot_scale`: copy from `scale` exactly
  - `camera_angle`: vertical framing bias serving the power dynamic (Eye-level/Low-angle/High-angle/Dutch-angle/Bird's-eye/Worm's-eye)
  - `composition_style`: layout law (Centered/Rule-of-thirds/Over-the-shoulder/Leading-lines/Symmetry/Frame-within-a-frame)
  - `focus_priority.primary_target`: WHO or WHAT the camera looks at — the subject of dramatic interest. **Pass 1B uses this as the area of interest to derive camera geometry and view selection.**
  - `focus_priority.secondary_target`: reaction subject or rack-focus target (null if none)
  - `focus_priority.focus_depth`: Shallow/Deep/Rack-focus
  - `movement_intent.type`: camera movement (Static/Pan/Tilt/Dolly-in/Dolly-out/Truck/Pedestal/Handheld-shake)
    **CAMERA MOVEMENT QUOTA (hard rule)**: At most 50% of panels in a scene may use `Static`. Minimum 40% must use a non-Static type.
    Defaults by shot type: CU/ECU in confrontation → `Handheld-shake` (micro-tremor 0.5–1°, viewer tension).
    ECU revelation/pivot → `Dolly-in` (slow push, 5–10cm). MS tracking → `Truck` or `Pan`. Arc_bridge → `Static` (the freeze is earned).
  - `narrative_vibe`: emotional goal of the shot (e.g. "Claustrophobic", "Triumphant", "Voyeuristic")

## FORBIDDEN in this pass
- `visual_start`, `visual_end`, or any image/environment description
- `motion_prompt` or any timestamped motion steps
- Lighting, set dressing, prop details
- Spatial camera geometry: `camera_x/y/z`, `location_references`, `camera_position` — those are Pass 1B

---

## SCENE TRAJECTORIES — fill BEFORE writing any panel stubs

For every named character present in this scene declare:
- **goal** — what they want to achieve by scene end (objective, not action)
- **obstacle** — what blocks them (external: another character, locked door; internal: fear, conflicting desire)
- **tactic** — how they approach the obstacle (strategy, not actions)
- **emotional_arc** — "enters [state] → [shift] at P[N] → exits [state]" — commit to a specific panel
- **arc** — what changed: win / loss / transformation / stalemate (one sentence)

---

## PANEL STRUCTURE BY EPISODE TYPE

> **Panel count scaling:** positions below assume N=9. For other counts: emotional_capture at P⌈N×0.56⌉, pivot at P⌈N×0.78⌉, arc_bridge/cliffhanger always at PN.

---

### arc_open — First Episode of Arc Unit

- **P1** `hook_type: cold_open/[archetype]` `duration: 3` (HARD CAP): Interaction already in progress, action 50%+ complete at frame 0. Apply YOUTUBE COLD AUDIENCE TEST — P1 must be readable to a cold viewer with zero context.
  Choose archetype: `cold_open/status_reversal` | `cold_open/impossible_situation` | `cold_open/hidden_identity` | `cold_open/ticking_clock` | `cold_open/revelation`
  FORBIDDEN: character sitting/looking/waiting; setup poses.
- **P2** `hook_type: verbal_hook` `duration ≤4s`: Arc's central conflict delivered mid-confrontation in ≤8 words. CU. Already mid-delivery at frame 0.
- **P3** `hook_type: context` `scale: MS or WS`: Orient viewer through action, not exposition.
- **P4** `hook_type: first_escalation`: First obstacle, complication, or pressure.
- **P⌈N×0.56⌉** `hook_type: emotional_capture`: Point of no return — action taken, line crossed, secret revealed.
- **P⌈N×0.67⌉** `hook_type: rising_action`: Stakes raised further; escape impossible.
- **P⌈N×0.78⌉** `hook_type: pivot` `duration: 3–4s` `scale: ECU`: Reaction at peak pressure. `dialogue_seed` = inner monologue 4–5 words ONLY. HARD FAILURE if empty or >5 words.
- **P(N-1)** `hook_type: mid_revelation`: New information changes context of everything prior.
- **PN** `hook_type: arc_bridge` `scale: CU or ECU`: Physical suspension — action frozen mid-motion 1cm from threshold. `dialogue_seed` must be voiceover (4–5 words). Plan match_cut geometry for arc_pickup connection.

---

### arc_mid — Middle Episode (N=3 arcs only)

- **P1** `hook_type: arc_pickup` `scale: matches arc_bridge`: Continues from previous arc_bridge. Same location, same physical position, 1–2 seconds later. `dialogue_seed` = inner decision 4–5 words.
- **P2** `hook_type: escalation_return`: Pressure from arc_open returns with increased force.
- **P3** `hook_type: complication`: New obstacle or dimension reframes the situation.
- **P4** `hook_type: rising_pressure`: Complication compounds; no exit.
- **P⌈N×0.56⌉** `hook_type: pivot` `duration: 3–4s` `scale: ECU`: `dialogue_seed` = inner monologue 4–5 words. Hard failure if empty or >5 words.
- **P⌈N×0.67⌉** `hook_type: new_revelation`: Reframes arc_open events; makes arc_close inevitable.
- **P⌈N×0.78⌉** `hook_type: stakes_raised`: Cost of revelation becomes visible and irreversible.
- **P(N-1)** `hook_type: pre_confrontation`: Collision now inevitable; characters closing distance.
- **PN** `hook_type: arc_bridge`: Physical suspension. `dialogue_seed` = voiceover 4–5 words.

---

### arc_close — Final Episode of Arc Unit

**N=2 arc** (arc_close follows arc_open directly):
- P1: `arc_pickup` — P2: `escalation_return` (immediate, full pressure) — P3: `confrontation_build` — P4: `confrontation_peak` (ECU)

**N=3 arc** (arc_close follows arc_mid):
- P1: `arc_pickup` — P2: `confrontation_build` — P3: `confrontation_peak` (ECU) — P4: `peak_intensity`

**Closing tail — always 5 panels ending at PN:**
- **P(N-4)** `hook_type: pivot` `scale: ECU` `duration: 3–4s`: After peak confrontation, smash_cut in. `dialogue_seed` = inner monologue 4–5 words. Hard failure if empty or >5 words.
- **P(N-3)** `hook_type: twist`: One fact changes everything. Arrives visually (prop, reflection, door).
- **P(N-2)** `hook_type: reversal`: Power dynamic inverts through physical action or discovery.
- **P(N-1)** `hook_type: consequence`: Visible, irreversible cost. Not resolution.
- **PN** `hook_type: cliffhanger/[type]` `scale: ECU`: Open question — never a closed reveal. Never summarize. End mid-breath.
  Choose: `cliffhanger/physical_threat` | `cliffhanger/revelation` | `cliffhanger/emotional_rupture` | `cliffhanger/interrupted_action` (rotate — never repeat same type twice in a row).

---

### transition episode

All panels (P1 through PN): `hook_type: transition`, no character close-ups, no dialogue. Environmental bridge between arc units. Refer to episode_type_transition.md for full spec.

---

## YOUTUBE COLD AUDIENCE TEST — mandatory for arc_open.P1 and arc_pickup.P1

YouTube delivers mid-season arcs to cold audiences. If they cannot read the situation within 3 seconds, they scroll.

For P1's `motion_intent` to pass this test, a stranger with zero context must be able to infer:
1. **WHO has power** — spatial position, posture, prop ownership (not backstory)
2. **WHERE** — one visible environmental detail (desk+skyline=office, rain-streaked window=cafe)
3. **WHAT conflict is active RIGHT NOW** — a physical action or reaction visible in frame

If any answer requires prior episode knowledge → the `motion_intent` must be reframed.

---

## ARC_BRIDGE RULES (for PN planning)

`motion_intent` for arc_bridge: "freeze action 1cm from completion threshold — the hand does not touch, the word does not land, the door does not open."
The suspension is the FINAL beat of the clip. The clip must approach the threshold first (kinetic approach), then freeze.
`dialogue_seed`: voiceover inner monologue — 4–5 words, the held thought before crossing.

## ARC_PICKUP RULES (for P1 planning)

`motion_intent` for arc_pickup: "complete the action that arc_bridge suspended — cross the threshold the previous episode froze at."
`scale` must match the arc_bridge's scale (the pickup is a geometric continuation).
SCENE JUMP HARD RULE: if the arc_pickup is in a DIFFERENT location or a different moment in time → it is NOT an arc_pickup. Assign `hook_type: cold_open` instead.
