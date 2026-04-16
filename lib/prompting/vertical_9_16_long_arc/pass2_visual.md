# PASS 2 — VISUAL STATICS (long_arc)

Generate `visual_start`, `visual_end`, `lights_and_camera`, and `references` for each panel.
Input: panel state from Pass 1A + panel skeleton (scale, motion_intent) from Pass 1.

---

## SCENE MASTER — declare FIRST, before writing any panel

Generate `camera_master` and `lighting_master` at the response root before the panels array.

**camera_master** — one sentence: dominant lens (mm), angle bias, primary lighting condition shared by ALL panels as their baseline.
Example: "85mm CU bias, eye-level, harsh midday daylight from panoramic windows, deep East-wall shadows."

**lighting_master** — one sentence: key light direction/color/quality, fill ratio, any visible practicals. ALL panels inherit this DNA.
LIGHTING CONTINUITY CONTRACT: every panel's `lights_and_camera` must remain within this baseline.
Acceptable deviations: practical lamp switched on/off, character blocks the key light, candle flickers.
HARD FAILURE: inventing a new time-of-day, new key-light source, or atmospheric condition (twilight, storm, golden hour) not present in `visual_continuity_rules`.
When a panel deviates for dramatic effect, flag it explicitly in `lights_and_camera`: "deviation from master: snap to 24mm wide for panic effect, then return to established 85mm CU".

---

## ARC-SPECIFIC VISUAL RULES

### arc_bridge panel (hook_type: arc_bridge) — PN of every non-final episode

`visual_end` must show **physical suspension**: the action is mid-motion and frozen 1cm from completion.
- Hand raised, finger 1cm from target — not touching
- Mouth open, word unspoken — not yet spoken
- Door mid-swing, 10cm from frame — not yet open
- Character mid-step, weight forward — not yet planted

The drama has NOT crossed its threshold. `visual_end` is the last frame before completion.
Plan `visual_end` geometry to enable a match_cut: the shape/composition must connect geometrically to the arc_pickup `visual_start` of the next episode.

### arc_pickup panel (hook_type: arc_pickup) — P1 of every non-first episode

`visual_start` must **resume** from the previous arc_bridge `visual_end`:
- Same location, same character
- Same physical position that arc_bridge froze at (hand 1cm away, mid-step, etc.)
- 1–2 seconds later in time — the threshold is now being crossed

`visual_start` is NOT a new establishing shot — it is a geometric continuation of the arc_bridge frame.
SCENE JUMP HARD RULE: if arc_pickup is in a different location or time → it is NOT an arc_pickup. Treat as `cold_open` with a standard establishing frame.

### YOUTUBE COLD AUDIENCE TEST — mandatory for arc_open.P1 and arc_pickup.P1

`visual_start` must answer three questions WITHOUT prior episode knowledge:
1. **WHO has power?** — visible through spatial position, posture, distance, or prop ownership
2. **WHERE are they?** — one visible environmental detail (desk+skyline=office, steering wheel=car)
3. **WHAT conflict is active RIGHT NOW?** — a physical action or reaction in the frame

If any answer requires knowing previous episodes → rewrite `visual_start`.

## What to produce
- `visual_start` — structured attribute record in MANDATORY FORMAT below. TIMING: freeze-frame JUST BEFORE motion begins.
- `visual_end` — structured attribute record in MANDATORY FORMAT below. State AFTER motion completes; ≥2 attribute values MUST differ from visual_start.
- `lights_and_camera` — shot scale, angle, lens, lighting
- `references[]` — character/prop slugs physically visible in this panel
- `location_references[]` — location view slug matching camera direction (copy from Pass 1B when available)
- `camera_position` — textual landmark name (copy from Pass 1B when available)
- `camera_x`, `camera_y`, `camera_z` — camera coordinates (copy from Pass 1B when available; derive only as fallback when 1B was skipped)
- `text_safe_composition` — true when key subjects are in middle 65% of frame height
- `panel_type` — always "narrative"

**Consumed from upstream — do NOT recompute:**
- `drama_requirements` — already declared in Pass 1; injected via DRAMA REQUIREMENTS block below. Copy verbatim into output if schema requires it; never override.
- Camera placement (`camera_x/y/z`, `location_references`, `visual_disposition`) — authoritative from Pass 1B when anchors are present.

## FORBIDDEN in this pass
- `motion_prompt` or timestamped motion steps
- Dialogue, voiceover, audio content

---

## MANDATORY FORMAT — VISUAL_START AND VISUAL_END

`visual_start` and `visual_end` are structured attribute records, NOT prose. Write each field as a sequence of labeled lines in the order below. No narrative sentences, no connecting prose between lines. After the last line — nothing else.

**Required line structure:**

```
[SCALE] [LENS]mm [ANGLE] cam@[CAMERA_POSITION_ANCHOR]
[ACTOR_NAME]: frame-[LEFT|CENTER|RIGHT] [FG|MG|BG], [PROFILE]→gaze:[GAZE_TARGET],chest->[CHEST_TARGET],head->[HEAD_TARGET], [POSE], [BODY_DETAIL_1], [BODY_DETAIL_2 or omit]
... (one ACTOR line per in_frame=true actor)
BG: [NAMED_WALL or SURFACE], [ELEMENT_1] [sharp|soft|heavy-bokeh], [ELEMENT_2 or —]
BGD: [DENSITY] [CROWD_TYPE], [DEPTH_PLANE], heavy-bokeh   ← MANDATORY in EVERY MS/MWS/WS/XWS panel when BACKGROUND ACTIVITY block is present; OMIT at ECU/CU/Macro; missing BGD = checklist failure
LIGHT: [KEY_DIRECTION], [QUALITY], [COLOR_TEMP], fill 1:[N]
PROP: [SLUG] at [ANCHOR_or_BODY_PART], [STATE]   ← include only for stake objects or prop state changes
CONTEXT: [≤15 words — scene-specific visual fact not encodable above]  ← omit if not needed
```

**Vocabulary constraints — only these tokens allowed per slot:**

| Slot | Valid tokens |
|---|---|
| SCALE | `ECU` `CU` `MCU` `MS` `MWS` `WS` `XWS` |
| ANGLE | `eye-level` `low-angle` `high-angle` `dutch-tilt` `overhead` |
| DEPTH | `FG` (≤1.5 m) `MG` (1.5–4 m) `BG` (>4 m) |
| PROFILE | `FRONTAL` `3Q-FRONT` `SIDE` `3Q-REAR` `BACK` |
| POSE | `standing` `seated` `crouched` `prone` `leaning` `kneeling` `half-risen` `perched` |
| FOCUS | `sharp` `soft` `heavy-bokeh` |
| QUALITY | `hard` `soft` `diffuse` `rim` `flat` |
| COLOR_TEMP | `warm` (≈3000 K) `neutral` (≈5500 K) `cold` (≈7000 K) or exact K value |

PROFILE is derived from camera direction and actor position with respect to actor body and head rotation.
Example:
- actor is by far wall, camera at the doorway, actor looks at the doorway -> PROFILE: 3Q-FRONT or FRONTAL
- actor in the doorway, camera at the doorway, actor comes in and looks inside the room -> PROFILE: 3Q-REAR or REAR

**GAZE_TARGET** — named anchor slug, canonical person name, or `lens(DIRECT-ADDRESS)`. Never blank or vague ("ahead", "nowhere", "distance").

**BODY_DETAIL** — encode ALL emotional/physical state as anatomy + measurement. Forbidden vocabulary:
- FORBIDDEN adjectives: `tense`, `nervous`, `determined`, `cold`, `afraid`, `calculating`, `intense`, `anxious` — any term describing internal psychological state
- FORBIDDEN metaphors: `"iron grip"`, `"frozen in place"`, `"crumbles"`, `"walls closing in"`, `"eyes burning"` — figurative language of any kind
- REQUIRED format: body part + position + optional measurement — `"right hand grips table-edge, knuckles raised 2 mm"`, `"chin dropped 15° below neutral, gaze fixed on desk surface"`, `"left shoulder raised 3 cm, arms crossed self-hug"`, `"jaw 2 mm open, lower lip retracted"`, `"spine pressed flat to entrance-door"`, `"weight on right foot, left heel raised 1 cm"`

**visual_end additional rules:**
- ACTOR BODY_DETAIL must differ from visual_start in ≥2 lines (any combination of actor / BG / PROP lines)
- At least one BODY_DETAIL or PROP line must describe an incomplete or unstable position: `"right hand 2 cm from door handle, not yet touching"`, `"glass at table-edge, tipped 15°"`, `"arm raised to shoulder height, hand open"` — the action is NOT done
- NEVER write `"settles"`, `"relaxes"`, `"resolves"`, `"the action is done"` in visual_end — it must be MORE precarious, not resolved
- arc_bridge special rule: `visual_end` IS the suspension state — the BODY_DETAIL MUST describe the physical threshold position (e.g., `"finger 1 cm above button surface, hovering"`)

**HARD FAILURES:**
- Any narrative sentence not tagged with a labeled line prefix (`BG:`, `LIGHT:`, `PROP:`, `CONTEXT:`)
- Any slot containing a psychological-state adjective or metaphor
- visual_end with all ACTOR + BG values identical to visual_start
- ACTOR line for an `in_frame=false` actor; missing ACTOR line for any `in_frame=true` actor
- Missing BG line or LIGHT line

---

## visual_start IS A CAMERA PROJECTION

`visual_start` is not a free description — it is the `complete_disposition` from Pass 1A
**projected through the camera** at the declared `scale` and angle.

Projection rules:
1. Take the actor positions from `state.actors` — translate to frame-space using ANCHOR-TO-FRAME-SPACE PROJECTION below
2. Apply `drama_requirements.shot_scale` — determine what fits in frame at that scale
3. Apply `drama_requirements.camera_angle` — determine what is above/below lens
4. Apply `drama_requirements.focus_priority` — what is sharp vs. bokeh
5. Add lighting from `lights_and_camera`

RESULT: every element in `visual_start` must be derivable from the state + camera — no invented details.

### ANCHOR-TO-FRAME-SPACE PROJECTION — mandatory when ROOM ANCHOR POINTS are provided

Each panel is rendered independently with zero memory of prior panels. Frame positions must be
computed from anchor coordinates every time — never assumed from context.

**STEP 1 — Assign camera coordinates and determine orientation.**

All anchor coordinates are normalized [0,1] fractions:
  X=0 = image-left wall (as seen in View-From-Entrance image), X=1 = image-right wall.
  Y=0 = entrance wall, Y=1 = far wall. Center = (0.5, 0.5).

**Assign camera_x / camera_y / camera_z** by looking up `camera_position` in `anchor_points.objects[]`
then `anchor_points.zones[]`, reading the anchor's (x, y), and adjusting for "near / beside" offsets.
If the camera position is not on a wall (center-room or floating), use the anchor's coordinates directly.
Set camera_z: 0.55 = standing eye-level; 0.45 = seated; 0.18 = ground; 0.80 = overhead crane.

Identify which wall the camera is on from camera_x / camera_y:
- camera_y ≤ 0.15 → **Entrance axis** (looking toward far wall)
- camera_y ≥ 0.85 → **Far-wall axis** (looking toward entrance)
- camera_x ≤ 0.15 → **Image-left-wall axis** (looking right)
- camera_x ≥ 0.85 → **Image-right-wall axis** (looking left)
- otherwise → **Center-room** (see below)

Confirm with `location_references` when ambiguous:
`View-From-Entrance` / `View-Primary` → Entrance axis.
`View-To-Entrance` / `View-Opposite` / `Interior-To-Entrance` → Far-wall axis.

Apply the matching projection rule (center band = [0.35, 0.65] on the lateral axis):

| Camera axis | Lateral variable | frame-LEFT | frame-RIGHT | Depth (foreground → background) |
|---|---|---|---|---|
| **Entrance** (y≈0, looking toward y=1) | x | x < 0.35 | x > 0.65 | low Y → high Y |
| **Far-wall** (y≈1, looking toward y=0) | 1 − x | x > 0.65 | x < 0.35 | high Y → low Y |
| **Image-left-wall** (x≈0, looking toward x=1) | y | y < 0.35 | y > 0.65 | low X → high X |
| **Image-right-wall** (x≈1, looking toward x=0) | 1 − y | y > 0.65 | y < 0.35 | high X → low X |
| **Center-room** | determined by character's `chest_direction` | toward lower x or y | toward higher x or y | by distance |

**STEP 1B — PROFILE token derivation (mandatory for every in_frame actor).**

`camera_direction` = the direction the camera faces. Derive it from `location_references` (or from `camera_direction` if provided in CAMERA PLACEMENT):

| location_references suffix | camera_direction |
|---|---|
| `View-From-Entrance` / `View-Center-To-Far` / `View-By-Far-Wall` / `View-Primary` / `Interior-From-Entrance` | **toward far wall** (camera at y≈0, looking toward y=1) |
| `View-To-Entrance` / `View-Center-To-Entrance` / `View-By-Entrance` / `View-Opposite` / `Interior-To-Entrance` | **toward entrance** (camera at y≈1, looking toward y=0) |
| `View-From-Left-Wall` | **toward right wall** (camera at x≈0, looking toward x=1) |
| `View-From-Right-Wall` | **toward left wall** (camera at x≈1, looking toward x=0) |

For each actor, compare `actor.chest_direction` with `camera_direction`:

| chest_direction vs camera_direction | PROFILE |
|---|---|
| Same direction (both toward far wall, or both toward entrance, etc.) | `BACK` |
| ~45° off camera direction (oblique, same general hemisphere) | `3Q-REAR` |
| ~90° off camera direction (perpendicular / lateral) | `SIDE` |
| ~135° off camera direction (oblique, facing-camera hemisphere) | `3Q-FRONT` |
| Opposite direction (actor faces toward the camera position) | `FRONTAL` |

**CRITICAL EXAMPLES — apply mechanically:**
- Camera: `View-From-Entrance` (toward far wall). Actor chest: "toward [modular-sofa]" (sofa is mid-room, deeper than actor) → chest points toward y>actor.y → **same direction as camera** → `BACK`
- Camera: `View-From-Entrance` (toward far wall). Actor chest: "toward [entrance-doorway]" (entrance is y≈0, same wall as camera) → chest points toward camera → `FRONTAL`
- Camera: `View-To-Entrance` (toward entrance). Actor chest: "toward Alisa" where Alisa is at entrance → chest faces entrance = same direction as camera → `BACK`
- Camera: `View-From-Entrance` (toward far wall). Actor chest: "toward [left-wall]" → perpendicular to camera axis → `SIDE`

**ACTOR AT CAMERA POSITION**: if actor is at the SAME anchor as the camera (e.g., actor at entrance-doorway AND camera at entrance-doorway), camera is BEHIND or BESIDE the actor → actor faces AWAY from camera → use `BACK` (or `3Q-REAR` if chest is slightly angled).

HARD FAILURE: writing `FRONTAL` for an actor whose `chest_direction` points in the same direction as `camera_direction`.

**STEP 2 — Project each `in_frame=true` actor to a frame zone:**
Match the actor's `position` description to their nearest anchor in `anchor_points.objects[]`.
Read the anchor's coordinates and apply the STEP 1 rule for the active camera axis.
- Center band ≈ middle 30% of the room's lateral dimension. Objects within this band = "frame-center".
- Outside the center band: "frame-left" or "frame-right" per STEP 1.
- For depth: apply the Depth column from STEP 1 → "foreground", "mid-ground", "background".

**DEPTH WHEN ACTOR IS AT CAMERA POSITION**: if an actor's anchor is at the same wall as the camera (entrance actor when camera is Entrance axis, far-wall actor when camera is Far-wall axis, etc.), that actor is in **FG** (foreground, ≤1.5 m), not BG. HARD FAILURE: placing an actor at the same wall as the camera in BG.

**STEP 3 — `in_frame` CONTRACT (HARD RULE):**
Every actor with `in_frame=true` in `state.actors` MUST appear explicitly in `visual_start` with a frame
position. An actor with `in_frame=true` written as "off-screen" or omitted entirely is a HARD FAILURE.
Conversely, actors with `in_frame=false` must NOT be placed inside the frame.

**STEP 4 — Write `visual_start` and `visual_end` using MANDATORY FORMAT.**

Apply the projection rules from STEPS 1–3 to fill the format slots. The result is the MANDATORY FORMAT record, not free prose.

HARD FAILURE: any `visual_start` or `visual_end` whose first line is not in the form `[SCALE] [LENS]mm [ANGLE] cam@[ANCHOR]` when anchor_points are available.

FORBIDDEN: copying frame positions from a different panel. Every panel computes its own projection.
FORBIDDEN: using `visual_disposition_hint` screen directions for a `To-Entrance`/`Opposite` panel —
use `visual_disposition_hint_to_entrance` instead, which already encodes the inverted mapping.

**STEP 5 — ECU/CU LOCAL BACKGROUND — geometric derivation (mandatory for shot_scale ECU or CU):**

At ECU and CU scale the camera is physically ~0.3–1 m from the subject. The background is NOT the
wide-room vista — it is the local slice of the room immediately BEHIND the subject's head/shoulders.

**Compute the background wall using coordinates:**

1. Camera is at (camera_x, camera_y). Subject is at their nearest anchor (sub_x, sub_y).
2. Direction vector D = (sub_x − camera_x, sub_y − camera_y). This is the direction the camera looks.
3. Extend the line PAST the subject: background_point = (sub_x + t·Dx, sub_y + t·Dy), t > 0.
4. Find which wall this line exits through first (smallest positive t):
   - Hits x=0 (image-left wall) when t = −sub_x / Dx  (if Dx < 0)
   - Hits x=1 (image-right wall) when t = (1 − sub_x) / Dx  (if Dx > 0)
   - Hits y=0 (entrance wall) when t = −sub_y / Dy  (if Dy < 0)
   - Hits y=1 (far wall) when t = (1 − sub_y) / Dy  (if Dy > 0)
   - The **smallest positive t wins** → that is the background wall.

5. Cross-check with the subject's `facing_degrees_y`: the background should be roughly OPPOSITE the
   subject's facing direction (the wall their back is toward). Facing 90° → back toward x=0 wall.
   If geometry and facing contradict, trust the camera→subject→wall projection (step 2–4).

**Background wall → what to describe:**

| Wall hit | What fills the tight background |
|---|---|
| x=0 (image-left wall) | Objects on the left wall at the subject's depth: counter, shelves, mounted fixtures |
| x=1 (image-right wall) | Objects on the right wall at the subject's depth: bookcase, cabinet, paneling |
| y=0 (entrance wall) | Entrance wall: door frame, door surface, wall beside entry |
| y=1 (far wall) | Far wall: window, curtains, moulding, wall texture |

**Rule**: describe the background in 1–2 phrases naming only the objects/surfaces on that wall,
slightly out-of-focus. Do NOT describe the room as a wide vista. Do NOT name a structural element
on the opposite wall.

HARD FAILURE: `visual_start` for ECU/CU that says "the room stretches behind him" / "the full
living room behind her" / describes a wide vista — forbidden at these scales.
HARD FAILURE: naming the entrance door behind a character whose geometric background is the far wall,
or vice versa — the background MUST match the camera→subject→wall projection.

**visual_start TIMING LAW**: visual_start = the split second BEFORE motion begins.
- WRONG: residual state of the previous panel's outcome
- RIGHT: exactly the state described in `state` (which is the outcome of the previous panel's motion_action)
- EXCEPTION: cold_open P1 — visual_start describes the action already in progress at 50%+

**visual_end must show a NEW UNSTABLE STATE** — a decision made visible, a contradiction revealed.
NEVER write visual_end as "the action is done." It is the world one beat after the action — more precarious, not resolved.

---

## INDEPENDENCE PROTOCOL — non-negotiable

Each panel is rendered by a separate image model with ZERO context from other panels.

REQUIRED in every `visual_start` and `visual_end`:
- Location details (architecture, lighting, atmosphere)
- Shot type and camera angle
- Character deviations from reference (costume change, carried item, injury, transient state)
  DO NOT repeat canonical appearance (hair, build, usual outfit) — those are in the reference images.
  DO repeat: scene-specific props carried, injuries, signature visual tells visible at CU/ECU range.

FORBIDDEN: "same as before", "same framing", "continues from panel N", "as established".

---

## CINEMATOGRAPHY LAWS

### PORTRAIT FRAME (9:16) — faces dominate

FRAMING HIERARCHY:
- ECU: eyes, hands, objects — peak emotional moments
- CU: face chin-to-forehead — default for dialogue and reaction
- MS: chest up — confrontation, spatial relationships
- WS: only when the environment IS the dramatic agent

ONE SHOT — ONE SCALE LAW: A single frame cannot combine incompatible scales.
IMPOSSIBLE: ECU face + floor detail in lower frame (opposite camera directions).
If you need both face reaction AND floor object → use two consecutive panels.

### CAMERA-FACING ORIENTATION

**Solo shots** — state one of:
- "faces visible to camera" (frontal, default for CU/ECU)
- "three-quarter profile to camera"
- "back to camera" (only when intentional dramatic choice)

**Multi-character shots** — use the compound form ONLY:
- "camera sees [A] in side profile, chest directed toward [B] at frame-[X]" — confrontation
- "camera sees [A] in three-quarter profile, chest angled toward [B] at frame-[X]" — approach / ambivalence
- "camera sees [A] in three-quarter rear profile, neck turned back toward [B] at frame-[X]" — reluctant attention
- "camera sees [A]'s back, body fully to [B] at frame-[X]" — rejection / vulnerability
CONTRADICTION: "faces visible to camera" + "half-turned toward [B]" = HARD FAILURE.

### GAZE DIRECTION

Characters look at each other or at the object of attention — NEVER at the lens by default.
- Dialogue panels: speaker's gaze toward listener's frame-position
- Reaction panels: gaze toward the stimulus source
- Direct camera address: deliberate device, ≤1 per episode, must be labeled explicitly

### POV CAMERA LAW

A shot described as "from [Character X]'s perspective" or "[Character X]'s POV" means the camera occupies X's eye position.
Character X CANNOT appear anywhere in that frame — not in background, not in periphery, not at all. A character cannot see themselves.
If Character X must be visible: drop POV framing, use over-the-shoulder, reaction shot, or standard two-shot instead.

### ANGLE VARIETY

No two consecutive panels may share the same shot scale AND the same camera angle.
If P3 = CU / eye-level → P4 must change scale OR angle. Monotone sequences collapse rhythm.

### SAFE ZONE

Key subjects in middle 65% of frame height. Top 15% and bottom 20% clear for subtitles/UI.

---

## VISUAL DRAMATIC INTENSITY — four questions for every frame

`visual_start` must answer all four:
1. **WHO has power, and WHO doesn't?** — spatial position (standing over / cornered), posture, or prop (who holds the weapon/contract/phone)
2. **WHAT specific emotion is visible?** — write the physics: "jaw set, lips compressed, eyes tracking her hands rather than her face"
3. **WHAT signals something is at stake?** — a prop at a table edge, a door ajar, hands too close. If scene_instructions names a STAKE OBJECT: `"FEATURED PROP: [name] — [position, focus state]"` is MANDATORY.
4. **IS the signature visual tell present?** — for CU/ECU, the character's defining prop or gesture must be described as visible, OR motion_prompt must explain why it's off-frame.

---

## P1 FULL CAST LAW

When P1's `scale` is NOT ECU or Macro, `visual_start` MUST include ALL actors named in `INITIAL DISPOSITION`.
- WRONG: P1 CU shows only Jane — Mike is in the scene but absent from frame.
- RIGHT: P1 MS — Jane frame-left in three-quarter profile, Mike frame-right in side profile, both visible.

If P1 IS ECU/Macro: state explicitly "[Other actor] is behind the camera / off-frame" in visual_start.

---

## CINEMATIC TECHNIQUES — VISUAL DESIGN

**TILT REVEAL** — design visual_start from feet/hands, visual_end on face (or reverse).
Required: at least one confrontation or twist panel per scene must use tilt reveal composition.
Plan: visual_start shows lower body / prop in frame; visual_end shows face. Requires `drama_requirements.movement_intent.type = "Tilt"` declared in Pass 1.

**REFLECTION REVEAL** — when a twist panel involves hidden identity or dual reality:
Compose visual_start with a mirror, window glass, or reflective surface visible and sharp.
The reflection shows what the character is feeling — camera is on their performing face, truth is in the reflection behind them.
- Phone screen: "camera frames the dark phone screen — character's eyes reflected in the glass show cold calculation while off-screen voice sounds warm and reassuring."
- Window/mirror: character faces away, their true expression visible only in the reflection behind them.
- Liquid surface: close-up of wine, water, or rain puddle — a distorted face reflected.

**MATCH CUT GEOMETRY** — for `transition_to_next: match_cut` (determined in Pass 3):
Design `visual_end` so its dominant shape/vector matches the `visual_start` of the following panel.
Concrete shape pairs to plan deliberately:
- Circular: glass rim → clock face → eye iris → tunnel end
- Vertical line: door frame → standing figure → knife blade → pillar
- Upward sweep: hand rising → bird launching → smoke curling → head tilting back
- Falling diagonal: body slumping → rain streaking glass → torn letter falling
Name the intended geometry in `lights_and_camera`: `"MATCH CUT: upward diagonal → next panel."` Mandatory: at least one match_cut in the escalation zone per scene.

---

## BACKGROUND PRESENCE LAW

Any character listed in `visual_continuity_rules` CHARACTER POSITIONS as present in this location
MUST appear in at least every third non-ECU/macro panel as a named background element.
Vanishing entirely = spatial hard failure.

**COUNTER RULE**: a character's own dedicated panel (where they are the PRIMARY subject) does NOT reset the background-presence counter for other characters. The counter resets only when the character appears as a non-primary background element in another character's panel. Count only non-ECU/macro panels when applying the "every third" limit.

Valid exceptions (state explicitly in visual_start):
1. ECU/Macro so tight no second person can fit
2. Character is behind the camera axis — state: "[Name] is behind the camera, off-frame"
3. Camera aimed in direction that geometrically excludes character's position — the character's spatial position from `initial_disposition` must make this geometrically clear

---

## CU/ECU FRAME EXCLUSION LAW

At tight shot scales, the camera frame physically cannot contain distant actors. Violating this causes the image model to composite absent characters and the I2V model to hallucinate animated background figures.

**Scale distance limits (mirror the Pass 1A `in_frame` rules):**
- ECU — only the immediate subject and objects/body-parts within ~30cm. No other character may appear in `visual_start`, `visual_end`, or `references[]`.
- CU — primary subject and any actor physically within ~1m. All others are excluded from frame descriptions and `references[]`.
- MS — actors within ~3–4m. Actors beyond 4m are excluded.
- WS — all actors in the location may appear.

**HARD FAILURES at CU/ECU:**
- `visual_start` or `visual_end` contains "in the background, [Character] does X" → FORBIDDEN. A background character at CU/ECU range is geometrically impossible.
- `references[]` includes a character who is >1m from the primary subject at CU scale, or anyone other than the immediate subject at ECU scale → HARD FAILURE. Remove them.
- Any detailed reaction ("her knuckles turn white", "his jaw clenches") for an out-of-frame character → HARD FAILURE. The image model cannot render it; the I2V model will hallucinate it.

**If a background character's reaction is dramatically necessary:** split into a separate panel (reaction shot at appropriate scale) rather than embedding it as background detail.

---

## BACKGROUND LIFE — rendering live environments

When a `BACKGROUND ACTIVITY` block is injected, the location contains unnamed extras. The `BGD:` line is **not optional** — it is required in every eligible panel and its absence is a checklist failure.

**Coverage rule — MANDATORY:** Before writing any panel, count how many panels in this batch are at `MS`, `MWS`, `WS`, or `XWS` scale. Each of those panels MUST contain a `BGD:` line in both `visual_start` and `visual_end`. A dramatic or emotionally intense panel does NOT exempt it — on the contrary, oblivious background workers during a horror beat amplify the protagonist's isolation.

**Scale gate — HARD RULE:** `BGD:` line only at `MS`, `MWS`, `WS`, `XWS`. Forbidden at `ECU`, `CU`, `Macro`. At tight scales the background is geometrically out of frame.

**BGD: line format:**
```
BGD: [density] [crowd_type], [depth_plane], heavy-bokeh
```
Example:
```
BGD: moderate bank clerks at teller counters and customers mid-transaction, mid-to-far ground, heavy-bokeh
```

**State progression within a scene:** The BGD description should reflect the crowd's evolving narrative state across panels — do not copy-paste identically from P1 to P9. Let the background react to the drama at the appropriate pace:
- Scene open: crowd oblivious, normal activity
- Mid-scene escalation: some figures glancing toward the action, slowing down
- Dramatic peak: crowd frozen, all attention on the event

This state progression is encoded in `crowd_type`/movement description, not in density (density is fixed per the screenplay's `background_activity` block).

**Content rules:**
- Background figures are ALWAYS at the declared `focal_plane` (typically mid-to-far), ALWAYS `heavy-bokeh`. Never sharp.
- Never describe individual background extras by name — describe them as type and approximate count: "two clerks", "a group of patrons".
- Never describe their expressions or specific actions in `visual_start`/`visual_end` — only spatial presence and crowd state.
- Do NOT include background extras in `references[]` — they are unnamed and have no ref slugs.
- Background figures must never overlap the primary actors' face zone (upper 65% of frame center).

**visual_end rule:** The `BGD:` line may show a subtle state shift (crowd turning to look, slowing) but must not be the change that satisfies the ≥2-attribute-diff requirement — that must come from primary ACTOR or PROP lines.

---

## REFERENCES CONTRACT

`references[]` contains ONLY characters and props physically visible in this panel's `visual_start` or `visual_end`.
FORBIDDEN: listing a character because they appear later in the scene or because they are mentioned in dialogue (off-screen voice ≠ visible).
All slugs must exactly match canonical casting ref names — a mismatch silently skips the reference image.

**BODY-PART/ACCESSORY RULE**: An ECU of a named character's body part or personal accessory (hand, foot, shoe, watch, ring, bag) counts as that character being physically present — include them in `references`.

**BACKGROUND PRESENCE OVERRIDE**: if a character must appear per BACKGROUND PRESENCE LAW, they ARE physically visible and MUST be included in `references`. The "ONLY visible" default does not override the spatial presence requirement — background characters are visible characters.

**PROP NAME CONTRACT**: all prop and character IDs in `references[]` must use EXACTLY the canonical slugs from the casting refs (e.g. "black-eagle-head-cane", not "ergonomic-cane-prop" or "the cane"). A name mismatch silently skips the reference image at render time.

---

## LOCATION REFERENCE NAMING

`location_references[]`, `camera_position`, and `camera_x/y/z` are derived together — they must agree.

**When Pass 1B camera data is present (CAMERA PLACEMENT block above):** copy `camera_position`, `camera_x/y/z`, and `location_references` verbatim. Do NOT re-derive.

**Fallback only — when Pass 1B was skipped (no anchor data):**

**Step 1 — place the camera** (use drama_requirements.focus_priority + visual intent):
Name the physical landmark the camera is closest to in `camera_position` (from ROOM ANCHOR POINTS).
Read the anchor's x/y, adjust for any "near / beside" offset, assign as `camera_x` / `camera_y`.
Set `camera_z`: 0.55 = standing eye-level; 0.45 = seated or low-angle; 0.80 = crane/overhead.

**Step 2 — select the view using camera_x AND camera_y (8-point coverage)**:

Priority order — first rule that matches wins:
1. `camera_y ≤ 0.20` → `View-From-Entrance` — near entrance, looking INTO the room toward far wall.
2. `camera_y ≥ 0.80` → `View-To-Entrance` — at far wall, looking TOWARD the entrance.
3. `camera_x ≤ 0.20` → `View-From-Left-Wall` — on the image-left wall (x=0), looking toward the image-right wall (x=1).
4. `camera_x ≥ 0.80` → `View-From-Right-Wall` — on the image-right wall (x=1), looking toward the image-left wall (x=0).
5. center-room (0.20–0.80 on both axes): use the background-element rule:
   - far wall behind subjects → `View-Center-To-Far`
   - entrance wall behind subjects → `View-Center-To-Entrance`
6. SPECIAL — use ONLY when the shot explicitly requires wall-proximity framing:
   - `View-By-Far-Wall` — camera 1m from far wall/window; wall fills frame; silhouette-against-light shots.
   - `View-By-Entrance` — camera 1m from entrance wall; door fills frame; threshold/doorway close-up shots.

AVAILABILITY: side-wall, center, and by-wall views may not exist for every room. If the slug does not appear in ROOM ANCHOR POINTS, fall back to `View-From-Entrance` (camera_y ≤ 0.5) or `View-To-Entrance` (camera_y > 0.5). NEVER write a slug that does not appear in the anchor data or its listed counterparts.

**Rooms — eight views:**
- `{Room}-View-From-Entrance` — entrance axis; X coordinates map left/right directly.
- `{Room}-View-To-Entrance` — entrance axis reversed; L/R **swapped**, depth reversed.
- `{Room}-View-From-Left-Wall` — lateral axis; **Y** drives L/R (low Y = entrance side = frame-left). X drives depth.
- `{Room}-View-From-Right-Wall` — lateral axis mirrored; **1−Y** drives L/R (low Y = entrance side = frame-right). 1−X drives depth.
- `{Room}-View-Center-To-Far` — center/entrance axis; same L/R as View-From-Entrance. Shallower depth.
- `{Room}-View-Center-To-Entrance` — center/entrance axis reversed; L/R **swapped** vs View-From-Entrance.
- `{Room}-View-By-Far-Wall` — 1m from far wall; same L/R as View-From-Entrance. Far wall fills frame; no mid-room furniture.
- `{Room}-View-By-Entrance` — 1m from entrance; L/R **swapped** (same as View-To-Entrance). Door fills frame; no mid-room furniture.

**Vehicles — three views:** `{Vehicle}-Exterior` / `{Vehicle}-Interior-From-Entrance` / `{Vehicle}-Interior-To-Entrance`

**Outdoor — two views:**
- `{Outdoor}-View-Primary` — camera faces the primary direction (toward canonical background landmark).
- `{Outdoor}-View-Opposite` — camera faces the opposite direction (180°; left/right swapped).
- **KEY RULE**: "archway behind her" + archway is the PRIMARY-end landmark → camera faces Opposite → View-Opposite.

Names must match existing refs EXACTLY — lowercase, hyphens only, no spaces, no capitalisation. A single letter difference silently skips the reference image. Copy the slug from ROOM ANCHOR POINTS verbatim.

### SPATIAL CORRECTION BY VIEW TYPE

The ANCHOR-TO-FRAME-SPACE PROJECTION table (STEP 1 above) already defines the projection rules for all 4 wall axes. Quick reference:

**View-From-Entrance / View-Center-To-Far / View-By-Far-Wall** (camera at y≈0, center, or near far wall; looking toward y=1):
Entrance axis — lateral = X. `x < 0.35` → frame-left; `x > 0.65` → frame-right. Depth: low-Y foreground → high-Y background.
View-By-Far-Wall: far wall fills ~80% of frame — no mid-room furniture, characters silhouetted against window.

**View-To-Entrance / View-Center-To-Entrance / View-By-Entrance** (camera at y≈1, center, or near entrance; looking toward y=0):
180° turn — **L/R SWAPPED** and **depth reversed**. Derive from negated X: `x_mirrored = 1 − x`.
`x < 0.35` in room → frame-right in this view. High-Y objects are foreground; entrance is background.
View-By-Entrance: entrance door fills ~80% of frame — no mid-room furniture.
If zones have `visual_disposition_hint_to_entrance`, use it as the `visual_start` starting point.

**View-From-Left-Wall** (camera x≈0, looking toward x=1 wall):
Image-left-wall axis — lateral = **Y**. `y < 0.35` (entrance side) → frame-left. `y > 0.65` (far side) → frame-right.
Depth: low-X near/foreground → high-X (image-right wall) background.

**View-From-Right-Wall** (camera x≈1, looking toward x=0 wall):
Image-right-wall axis — lateral = **1−Y**. `y > 0.65` (far side) → frame-left. `y < 0.35` (entrance side) → frame-right.
Depth: high-X near/foreground → low-X (image-left wall) background.
