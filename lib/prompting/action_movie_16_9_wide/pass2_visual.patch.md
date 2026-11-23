<!-- replace: ### PORTRAIT FRAME (9:16) — action geography first -->
### WIDESCREEN FRAME (16:9) — staging in width and depth

FRAMING HIERARCHY:
- WS: the whole space across the frame — every combatant, their cover, the exits. The default for action.
- MS: full bodies or knees-up, normally two or more characters with the distance between them visible
- CU: one face, with the room or the other character still present beside or behind it; over-the-shoulder for exchanges
- ECU: eyes, hands, trigger, one object — an insert, used sparingly

LATERAL STAGING: place opposing characters on opposite sides of the frame and keep them there. Use the width for the gap between them and for the route one of them must cross.

DEPTH STAGING: put action on two planes — a foreground figure or piece of cover at one side, the threat or the exit deep in the frame. State which plane is in focus.

ONE SHOT — ONE SCALE LAW: A single frame cannot combine incompatible scales.
IMPOSSIBLE: ECU face + floor detail in the same frame (opposite camera directions).
If you need both face reaction AND floor object → use two consecutive panels.

<!-- replace: ### SAFE ZONE -->
### FRAME EDGES

Keep faces and decisive action clear of the outer 5% of the frame on every side.

<!-- replace: ## CINEMATIC TECHNIQUES — VISUAL DESIGN -->
## CINEMATIC TECHNIQUES — VISUAL DESIGN

**TWO-SHOT** — hold both parties of a confrontation in one frame: profiles facing each other across the width, the stake prop or the gap between them at frame-center.

**DEPTH REVEAL** — compose visual_start with the foreground subject sharp and a doorway, window or corridor deep in the frame; visual_end brings the second plane into play (a figure appears there, or focus pulls to it). Requires `focus_priority.focus_depth = "Rack-focus"` or `"Deep"` declared in Pass 1.

**LATERAL MOVE** — for `Truck` and `Pan` panels, state where the subject starts and ends across the frame ("enters at frame-left third, ends at frame-right third beside the pillar").

**REFLECTION REVEAL** — when a panel involves hidden identity or dual reality:
Compose visual_start with a mirror, window glass, or reflective surface visible and sharp.
The reflection shows what the character is feeling — camera is on their performing face, truth is in the reflection.
- Window/mirror: character faces away, their true expression visible only in the reflection.
- Vehicle glass or a dark screen: eyes reflected show calculation while the voice stays calm.

**MATCH CUT GEOMETRY** — for `transition_to_next: match_cut` (determined in Pass 3):
Design `visual_end` so its dominant shape/vector matches the `visual_start` of the following panel.
- Circular: glass rim → clock face → eye iris → tunnel end
- Horizontal line: table edge → horizon → car roofline → corridor floor
- Lateral sweep: a runner crossing frame → a vehicle crossing frame → a door sliding
- Falling diagonal: body slumping → rain streaking glass → torn paper falling
Name the intended geometry in `lights_and_camera`: `"MATCH CUT: lateral sweep → next panel."`
