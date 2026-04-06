# PASS 1 — SCENE ARCHITECTURE

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
    ECU revelation/pivot → `Dolly-in` (slow push, 5–10cm). MS tracking → `Truck` or `Pan`. Cliffhanger → `Static` (the freeze is earned).
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

## PANEL STRUCTURE — SOURCE-FAITHFUL CHRONOLOGICAL FLOW

Panels follow the source text in strict chronological order. No dramatic positions are mandated — the story dictates what each panel shows.

### OPENING PANELS (P1–P2)
Drop into the scene with the primary action already underway or just beginning.
P1 `duration`: 3–5s. Action must be visible from frame 0. Static setup shots are forbidden.
P1 `hook_type`: `scene_open`

### MID-SCENE PANELS (P3–P[N-2])
Follow action, dialogue, and emotional shifts in source order.
Vary `scale` across panels — place ECU at the scene's emotional peak (wherever the source puts it).
Dialogue exchanges follow the source verbatim: every spoken line in the source gets a panel.
Do not reorder or condense exchanges.

### CLOSING PANELS (P[N-1]–PN)
End where the source ends. If the source ends quietly — end quietly.
Do NOT invent escalation, cliffhangers, or dramatic peaks not present in the source.
PN `hook_type`: `scene_close`

---

## HOOK TYPES

| hook_type | When to use |
|-----------|-------------|
| `scene_open` | P1 — opens the scene |
| `dialogue_exchange` | Panels carrying back-and-forth dialogue |
| `action` | Physical action panels |
| `revelation` | A character learns or realizes something |
| `emotional_beat` | Face carries the scene's emotional weight, minimal or no dialogue |
| `scene_close` | PN — closes the scene |

---

## SCALE GUIDANCE

- P1: MS or CU — show who is doing what from the start
- Dialogue panels: CU on the speaking face
- Physical action: MS or WS to show spatial relationship
- Emotional peak (wherever source places it): ECU
- PN: scale matches the scene's emotional temperature at close — don't force ECU if the source ends in WS

---

## SOURCE FIDELITY IN PASS 1

`motion_intent` must reflect only what the source text has the character doing. Do not invent dramatic goals absent from the source.
`dialogue_seed` must come directly from a line or thought in the source — never fabricated.

For panels covering pure action without dialogue: leave `dialogue_seed` as empty string.
