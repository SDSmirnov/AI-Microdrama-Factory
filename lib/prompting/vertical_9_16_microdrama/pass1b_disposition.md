# PASS 1B — CAMERA PLACEMENT + SPATIAL DISPOSITION

Decide camera position and write spatial disposition for each panel.
Input: Pass 1 panel skeletons (scale, hook_type, motion_intent, drama_requirements) + Pass 1A actor states (positions, chest_direction, complete_disposition).
Output: camera_position, camera_x/y/z, location_references, visual_disposition per panel.

## WHAT TO PRODUCE

For each panel:
- `camera_position` — nearest named anchor from ROOM ANCHOR POINTS (textual landmark, e.g. "near entrance-door")
- `camera_x` — camera X in [0,1]: 0 = image-left wall, 1 = image-right wall
- `camera_y` — camera Y in [0,1]: 0 = entrance wall, 1 = far wall
- `camera_z` — camera height Z: 0.18 = ground/low, 0.45 = seated, 0.55 = eye-level standing, 0.80 = overhead crane
- `location_references[]` — view slug(s) derived from camera position (see VIEW SELECTION below)
- `visual_disposition` — camera-agnostic, anchor-grounded disposition prose

## FORBIDDEN IN THIS PASS

- Visual descriptions, lighting, shot composition, `visual_start`/`visual_end`
- screen-left / screen-right / frame-left / frame-right in `visual_disposition` — it is camera-agnostic
- Compass directions (North/South/East/West) anywhere
- Invented anchor names not present in ROOM ANCHOR POINTS

---

## STEP 1 — CLASSIFY EACH PANEL

Classify using `scale` from Pass 1 and `hook_type`:

| Class | Condition |
|---|---|
| **A — FACE SHOT** | scale is CU or ECU, OR hook_type contains `cold_open` / `pivot` / `crystallization` / `twist` |
| **B — TWO-SHOT** | scale MS or WS with ≥2 actors having `in_frame=true` |
| **C — ACTION / WIDE SINGLE** | scale WS/MS with one primary actor, or explicit movement panels |
| **D — INSERT** | scale Macro — single object or body part only |

---

## STEP 2 — DETERMINE CAMERA AXIS

### Class A — FACE SHOT

Primary source: `drama_requirements.focus_priority.primary_target` from Pass 1 names the subject actor.
Find that actor in `state.actors[]` → use their `chest_direction` as the axis signal.

| chest_direction value | Camera axis |
|---|---|
| contains "entrance" / "door" / "toward entrance" | camera at entrance wall → camera_y ≈ 0.10 |
| contains "window" / "far wall" / "away from entrance" | camera at far wall → camera_y ≈ 0.90 |
| contains "image-left wall" / "toward left" | camera on image-left wall → camera_x ≈ 0.10 |
| contains "image-right wall" / "toward right" | camera on image-right wall → camera_x ≈ 0.90 |
| lateral / profile | maintain the established scene axis; do NOT place camera on a lateral wall just to show a profile |

If chest_direction is absent: use narrative context — character being confronted usually faces toward the camera.

**Over-the-shoulder / POV**: apply the axis rule to the TARGET character (the one whose face is visible), not the source.

### Class B — TWO-SHOT

Find the axis that captures both actors in partial profile (side-by-side or across from each other).
- If actors face each other along the entrance/far-wall axis → use entrance axis (camera_y ≈ 0.10, View-From-Entrance)
- If actors face each other along the lateral axis → use lateral axis (camera_x ≈ 0.10 or 0.90)
- **NEVER place camera on a lateral wall** for two-shots where actors face each other along the entrance/far-wall axis — the camera would see their backs.

### Class C — ACTION / WIDE SINGLE

Prefer the axis that captures the direction of movement:
- Actor moves away from entrance toward far wall → From-Entrance camera (camera_y ≈ 0.10)
- Actor moves toward entrance → From-Entrance or To-Entrance; prefer the one that shows the actor's face
- When in doubt: **preserve the previous panel's camera axis** for spatial continuity

### Class D — INSERT

Place camera 0.2–0.5 m from the object. Use the nearest anchor to the object.
camera_z depends on object height: 0.18 for floor-level objects, 0.55 for table-height.

---

## STEP 3 — ASSIGN camera_x, camera_y, camera_z

After determining the axis:
1. Look up the nearest relevant anchor in ROOM ANCHOR POINTS
2. Read its (x, y) coordinates
3. Offset toward the wall the camera is on (e.g. if camera is at entrance wall: set camera_y = anchor.y × 0.5 to stay near y=0)
4. Set camera_z: 0.55 default; 0.45 for seated angles; 0.18 for ground; 0.80 for crane/overhead

---

## STEP 4 — SELECT location_references

Apply 8-POINT VIEW SELECTION (priority order — first rule that matches wins):

1. `camera_y ≤ 0.20` → `{Room}-View-From-Entrance`
2. `camera_y ≥ 0.80` → `{Room}-View-To-Entrance`
3. `camera_x ≤ 0.20` → `{Room}-View-From-Left-Wall`
4. `camera_x ≥ 0.80` → `{Room}-View-From-Right-Wall`
5. center-room (0.20–0.80 on both axes):
   - far wall (y=1) behind subjects → `{Room}-View-Center-To-Far`
   - entrance wall (y=0) behind subjects → `{Room}-View-Center-To-Entrance`
6. SPECIAL — only when shot explicitly requires wall-proximity framing:
   - `{Room}-View-By-Far-Wall` — camera 1 m from far wall, wall fills frame (silhouette/window shots)
   - `{Room}-View-By-Entrance` — camera 1 m from entrance, door fills frame (threshold shots)

**AVAILABILITY**: only use slugs that appear in ROOM ANCHOR POINTS or their listed counterparts (opposite-direction views).
Fallback: `View-From-Entrance` (camera_y ≤ 0.5) or `View-To-Entrance` (camera_y > 0.5).
**HARD FAILURE**: a slug not in ROOM ANCHOR POINTS or its listed counterparts.

---

## STEP 5 — WRITE visual_disposition

Write a compact, camera-agnostic string anchoring every actor to named room landmarks.

Rules:
- Use ONLY named anchor objects from ROOM ANCHOR POINTS (e.g. sofa, entrance-door, coffee-table, panoramic-window)
- Express relations as: "near [sofa]", "standing at [entrance-door]", "backed against [panoramic-window]", "seated at [glass-table] facing [sofa]"
- Include every actor listed in `state.actors`, regardless of `in_frame` status
- Out-of-frame actors: state their last known anchor position — "off-frame, last at [entrance-door]"
- FORBIDDEN: screen-left/right, frame-left/right, North/South/East/West
- FORBIDDEN: "same as before", "unchanged" — each panel's visual_disposition is fully self-contained
- FORBIDDEN: anchor names not verbatim from ROOM ANCHOR POINTS

---

## 180-RULE CONTINUITY

Do not flip the camera axis between consecutive panels without a narrative reason.

- From-Entrance and To-Entrance are **opposite axes** — switching between them is a 180° cut. FORBIDDEN unless:
  1. A character explicitly crosses the room and the motion_action documents it
  2. The scene location changes
- Lateral views (From-Left-Wall, From-Right-Wall) are orthogonal axes — acceptable for reaction cutaways
- Prefer axis continuity when motion_action does not document a crossing

---

## VEHICLE SCENES

For scenes inside or adjacent to a vehicle, use:
- `{Vehicle}-Exterior` — outside the vehicle
- `{Vehicle}-Interior-From-Entrance` — inside, camera near door, looking in
- `{Vehicle}-Interior-To-Entrance` — inside, camera past occupants, looking toward door

For vehicle interiors: use `vehicle_position` from `state.actors` to derive camera axis (driver side vs. passenger side).

---

## OUTDOOR SCENES

- `{Location}-View-Primary` — camera faces the primary direction (toward canonical background landmark)
- `{Location}-View-Opposite` — camera faces 180° opposite; left/right swapped vs. View-Primary

Use View-Opposite when the subject is moving toward the camera (retreating), or when the canonical background landmark is behind the subject.
