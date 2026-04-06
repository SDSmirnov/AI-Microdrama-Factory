# PASS 1A — PANEL STATE CHAIN

Track the **physical state of all actors and props** across every panel.
This is a spatial/physical planning pass — no camera, no visual description, no dialogue.

## What to produce
For each panel:
- `state` — complete physical snapshot: `actors[]`, `props[]`, `complete_disposition`, `environment`
- `motion_action` — scene-level plain-English summary of what all actors do in this panel

## FORBIDDEN in this pass
- Camera angles, shot scale, lighting, visual descriptions
- `visual_start`, `visual_end`, `motion_prompt`
- Dialogue, voiceover, or any audio content

---

## STATE CHAIN LAW

`state[i]` is the **freeze-frame JUST BEFORE the `motion_action` of panel `i` begins**.
The action has not started yet. Do not show mid-action or post-action body positions.
`state[i+1]` must be derivable from `state[i]` plus the `motion_action` of panel `i`.
If you cannot derive the next state from the current state and the declared action, the action is incomplete — add the missing physical steps.

**Every actor present in the scene** must be listed in `actors[]` in EVERY panel, regardless of `in_frame` status.
A character who "leaves the room" still has a state — they are at the door / in the hallway / off-frame but their last known position is recorded.

---

## ACTOR STATE FIELDS

```
name            — character reference slug
position        — relative to room anchors AND other actors (see TOPOLOGICAL MODEL)
                  FORBIDDEN: compass directions (N/S/E/W). Use anchor-relative direction instead.
                  Format: "[anchor], [distance] toward [anchor2] from [OtherActor]"
                  WRONG: "at [textured-rug], 1m North of Jane"
                  RIGHT: "at [textured-rug], 1m toward [entrance-door] from Jane"
                  WRONG: "standing in the center of the room"
                  RIGHT: "midway between [entrance-door] and [panoramic-window], 1m from Jane"
pose            — body posture: "standing, arms crossed", "seated, leaning forward", "crouching behind sofa"
gaze_target     — what or who they are looking at, or null
head_direction  — named target only — no compass prefix
                  WRONG: "North toward Jane" / "South toward window"
                  RIGHT: "toward Jane" / "toward [panoramic-window]" / "down at the phone"
chest_direction — body front orientation — named target only — no compass prefix
                  WRONG: "North" / "South toward The-Man"
                  RIGHT: "toward The-Man" / "toward [entrance-door]" / "away from Jane"
motion_action   — what THIS actor does during this panel (e.g. "walks to the table", "shifts weight to left foot, arms cross")
  **PASSIVE MOTION LAW**: `"stays still"` / `"stands still"` / `"watches"` / `"listens"` alone are HARD FAILURES.
  Every character present in a scene has a stake in what's happening — encode it as a body action.
  If the character is not the primary actor, use a reactive physical proxy: shifts weight, tightens grip, adjusts position, turns slightly, handles prop.
  WRONG: `"stays still, watching Robert"` → HARD FAILURE.
  RIGHT: `"shifts weight onto right foot, arms tighten around the blanket as Robert speaks"` → reactive physicality.
vehicle_position — required when the scene is inside or immediately adjacent to a vehicle; null otherwise.
                  Use ONLY these labels (no compass, no vague "back seat"):
                  Interior: "driver seat" | "front passenger seat" | "rear left seat (behind driver)" |
                            "rear right seat (behind front passenger)" | "rear center seat" | "cargo area"
                  Exterior: "at the driver door (outside)" | "at the front passenger door (outside)" |
                            "at the rear left door (outside)" | "at the rear right door (outside)" |
                            "on the hood" | "on the roof" | "in the trunk"
in_frame        — boolean: is this actor physically within the camera frame at this panel's declared scale.
                  PRIMARY RULE: if `drama_requirements.focus_priority.primary_target` in the Pass 1 skeleton names THIS actor → in_frame=true regardless of distance. The camera will be positioned to capture them.
                  Scale-distance rules (apply to ALL other actors):
                  ECU — only the immediate subject or an object within ~30cm of the lens focal point. in_frame=false for everyone else.
                  CU  — primary subject and any actor physically within ~1m of them. in_frame=false for actors beyond 1m.
                  MS  — actors within ~3–4m of the primary subject. in_frame=false for actors beyond 4m.
                  WS  — any actor in the location may be in_frame=true.
                  If unsure: default to in_frame=false. A missed actor causes no harm; a falsely present actor causes I2V hallucination.
```

---

## PROP STATE FIELDS

```
name        — prop reference slug
position    — relative to room anchors or actor anatomy
prop_change — physical/state change during this panel (e.g. "slid to floor edge", "picked up by Jane")
              Use "unchanged — [last known state]" when a prop is present but not actively changing.
```

## PROP TRACKING LAW

Once a prop appears in any panel's `props[]`, it MUST appear in EVERY subsequent panel through the last panel.
The only valid reason to drop a prop is an explicit removal: "thrown off-screen", "pocketed", "exits with character", "lands off-frame and is no longer in this room."
For panels where the prop has no active change, write: `prop_change: "unchanged — [last known state from when it was last active]"`.

FORBIDDEN: a prop disappearing from `props[]` between panels without a documented removal action. This is a continuity hard failure.

Ignore background set dressing (furniture, wall art, fixtures) — only track props that have been actively introduced or interacted with by a character.

---

## TOPOLOGICAL MODEL — positions use relations, never coordinates

All positions must be expressed as:
1. **Relative to location anchors** — named landmarks from the room ref (door, table, window, sofa, mirror): "by the entrance door", "at the far end of the table", "near the floor-length window"
2. **Relative to other actors** — distance and direction: "1.5m behind Jack", "shoulder-to-shoulder with Jane on her right side", "blocking the door, 30cm from John"

FORBIDDEN: absolute coordinates, compass directions (N/S/E/W), pixel positions, "left side of room" without anchor reference.

**complete_disposition** — a single prose sentence integrating all actors and key props. MUST use named anchors from ROOM ANCHOR POINTS verbatim — enclose each anchor name in brackets. FORBIDDEN: compass directions (N/S/E/W), "center of room", "left side of room", any invented location name.
Example: "Jack stands at [entrance-door], body squared toward Jane who is backed against [panoramic-window-south], the [grey-textured-rug] between them; the knife is on the [glass-coffee-table] 40cm from Jack's right hand."

**anchor_refs** — array of every anchor name (copy-pasted verbatim from ROOM ANCHOR POINTS) that appears in `complete_disposition`. Required when anchor data is present; empty array only when no anchor data was provided.

---

## CONTINUITY CHECK

After generating all panels, verify:
1. Does every actor's position in panel[i+1].state.actors match their position after executing panel[i].motion_action? If not → fix the state.
2. Does any actor teleport (position changes without a motion_action accounting for it)? → HARD FAILURE. Add the missing movement.
3. Are ALL scene actors listed in EVERY panel's state? → If any are missing → HARD FAILURE.
4. Does any prop appear in panel[N].props[] but not in panel[N+1].props[] without an explicit removal motion_action? → HARD FAILURE. Add the prop with prop_change: "unchanged — [last known state]".
