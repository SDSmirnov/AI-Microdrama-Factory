<!-- append -->
## ARC-SPECIFIC VISUAL RULES

### arc_bridge panel (hook_type: arc_bridge) — PN of every non-final episode

`visual_end` must show **physical suspension**: the action is mid-motion and frozen 1cm from completion.
- Hand raised, finger 1cm from target — not touching
- Mouth open, word unspoken — not yet spoken
- Door mid-swing, 10cm from frame — not yet open
- Character mid-step, weight forward — not yet planted

The drama has NOT crossed its threshold. `visual_end` is the last frame before completion: its BODY_DETAIL MUST describe the physical threshold position (e.g., `"finger 1 cm above button surface, hovering"`).
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
