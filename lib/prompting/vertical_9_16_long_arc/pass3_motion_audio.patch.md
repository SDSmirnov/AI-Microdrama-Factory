<!-- append -->
## ARC-SPECIFIC MOTION RULES

### arc_bridge panel — motion_prompt ends before resolution

The motion_prompt MUST NOT complete the action. The clip approaches the threshold and stops.

Structure:
1. **Kinetic approach** (0s–5s): character moves toward the threshold with full physical commitment
2. **Suspension** (final 0.5–1s): motion decelerates and freezes — hand stops 1cm short, word begins but doesn't land

WRONG: `"At 5s the hand presses the button."` — action completed, arc_bridge broken.
RIGHT: `"At 5s the finger is 1cm above the button, hovering — the clip ends here."`

`sound_design` for arc_bridge: always `"silence"` — the suspension is aurally complete.
`transition_to_next`: always `"match_cut"` — the geometry must connect to arc_pickup.

### arc_pickup panel — motion_prompt begins from suspension

The motion_prompt MUST start from the exact physical position where arc_bridge froze.

Structure:
1. **Completion** (0s–1s): the suspended action now crosses the threshold
2. **Consequence** (1s–end): the result of crossing — physical, emotional, narrative

`motion_prompt[0s]`: describes the suspended position from arc_bridge, then the threshold crossing.
`voiceover`: inner decision at the moment of crossing — 4–5 words maximum.
`transition_to_next`: `"hard_cut"` unless the action flows into P2 as a match_cut.

### VOICE CHECK for arc_bridge — MODIFIED RULE
`dialogue` may be empty for arc_bridge panels. `voiceover` MUST be populated (inner monologue 4–5 words — the held thought before crossing).
