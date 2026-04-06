# PASS 1 — SCENE ARCHITECTURE

Declare the **narrative skeleton** for this scene. This is a planning pass only.

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

**Use trajectories when writing every panel stub:**
- `goal` → every `motion_intent` must serve a declared goal. An intent that serves no trajectory is a dead gesture.
- `obstacle` → determines who controls space, who holds the prop, who is cornered
- `tactic` → shapes `dialogue_seed` subtext: what the character appears to say vs. what they are actually doing
- `emotional_arc` → at the declared turning-point panel, the `scale` should shift to CU/ECU to capture the crack
- `arc` → the final panel's `hook_type` and `motion_intent` must reflect the declared outcome

**TRAJECTORY AUDIT (run after writing all panel stubs, before finalizing):**
1. Does every panel's `motion_intent` serve at least one character's declared `goal` or `tactic`? Intents that serve no trajectory → rewrite.
2. Is the declared turning-point panel's `scale` CU or ECU? If not → fix.
3. Does the final panel's `hook_type` and `motion_intent` match the declared `arc` outcome? If not → rewrite.

---

## 9-PANEL MICRO-ACT STRUCTURE

(TRANSITION episodes override this entirely — see episode_type block. All panels are environmental.)

- **P1 — cold_open** `duration ≤4s (hard cap)`: Drop INTO ongoing action. Something is already 50%+ complete at frame 0.
  Choose hook archetype: `cold_open/status_reversal` | `cold_open/impossible_situation` | `cold_open/hidden_identity` | `cold_open/ticking_clock` | `cold_open/revelation`
  FORBIDDEN: character sitting/standing/looking without active conflict; setup poses; anticipation poses.

- **P2 — verbal_hook** `duration ≤4s (hard cap)`: Central conflict stated in ≤8 words — ultimatum, threat, confession, or challenge. CU on speaker. NOT exposition — dialogue names stakes mid-confrontation.
  FORBIDDEN: character entering frame; turning to camera; setup before the line.

- **P3 — escalation** `duration 4–5s`: First pressure or obstacle. Self-contained power-dynamic image: power, primary emotion, and stake object readable without P1–P2 context.

- **P4 — emotional_capture** `duration 6s`: Point of no return — action, revelation, or commitment that makes finishing the episode feel necessary. Escalates from P3 in emotional temperature, not just plot.

- **P5 — crystallization** `duration 6–7s`: Stakes become visceral and irreversible. STRONGEST THUMBNAIL: CU/ECU face, recognizable ambiguous emotion, no key subject in text-overlay zone.

- **P6 — confrontation** `duration 6s`: Peak conflict, ECU on face.

- **P7 — pivot** `duration 3–4s`: ECU reaction at maximum pressure, before the twist. NO dialogue — `dialogue_seed` must be voiceover inner monologue of 4–5 words only. Hard failure if empty or >5 words.

- **P8 — twist** `duration 6s`: One fact changes everything.

- **P9 — intermediate episodes: tension_peak**: Maximum escalation, no resolution. Protagonist at peak pressure — threat is closest, choice is seconds away. `dialogue_seed` must be 4–5-word inner monologue voiceover: the held thought before the next episode's response.
- **P9 — final episode: cliffhanger**: RESPONSE PRESSURE FREEZE — protagonist has just received a devastating action, revelation, or demand. Freeze at the moment BEFORE their response. NEVER freeze on a revelation itself (satisfies the viewer) — freeze on the protagonist's face as they absorb it.
  SERIES THUMBNAIL: the final frame of `visual_end` is the series unlock card. Requirements: (1) protagonist face in CU/ECU — ambiguous emotion, readable as either fear OR determination; (2) a stake object visible in frame; (3) no key subject in bottom 20% text zone.
  Choose (rotate — never repeat same type twice in a row across series): `cliffhanger/response_freeze` | `cliffhanger/revelation` | `cliffhanger/emotional_rupture` | `cliffhanger/interrupted_action`

---

## SCALE GUIDANCE PER HOOK TYPE

| hook_type | default scale |
|-----------|---------------|
| cold_open | MS or CU (action in progress) |
| verbal_hook | CU (speaker's face) |
| escalation | MS (power dynamic + stake object readable) |
| emotional_capture | CU or MS |
| crystallization | CU or ECU (thumbnail quality) |
| confrontation | ECU |
| pivot | ECU |
| twist | CU or ECU |
| tension_peak / cliffhanger | ECU |

For 4–6 panel scenes: compress arc — P1=cold_open, P2=verbal_hook, middle panels=escalation/confrontation, penultimate=pivot/twist, final=tension_peak/cliffhanger.
