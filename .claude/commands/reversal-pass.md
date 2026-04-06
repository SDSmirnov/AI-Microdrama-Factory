Scene file for reversal pass: $ARGUMENTS

Steps:
1. Read the scene JSON file at `$ARGUMENTS`
2. Find all panels where `is_reversed` is `true`
3. If no reversed panels exist, output "No reversed panels found — nothing to do." and stop.
4. Check if `custom_prompts/setting.md` exists — use it; otherwise use `prompts/setting.md` (legacy fallback). Read it for visual style context.
5. Generate `motion_prompt_reversed` and `visual_start_explicit` for each flagged panel following all instructions below.
6. For each reversed panel in the JSON:
   - Set `motion_prompt_reversed` to the generated value
   - Swap `visual_start` ↔ `visual_end`, then replace the new `visual_start` with `visual_start_explicit`
   - Replace `motion_prompt` with the generated `motion_prompt_reversed`
7. Write the updated JSON back to the same file path (overwrite).
8. **Update `cinematic_render/animation_metadata.json` (single source of truth):**
   - Read `animation_metadata.json`. For each updated scene, find the matching entry by `scene_id` and update only the affected panels (replace the full panel object for any panel that had `is_reversed: true`).
   - Write the updated metadata back to `animation_metadata.json`.

---

## ROLE: MASTER CINEMATOGRAPHER — REVERSAL PASS

You are writing motion prompts for AI Image-to-Video generation for panels that use **Reverse Reveal** animation.

## HOW REVERSE REVEAL WORKS

The panel was written in normal chronological order:
- `visual_start` = before the action (e.g., "fog fills the frame, nothing visible")
- `visual_end` = after the action (e.g., "hedgehog stands in clearing, knife drawn")

For rendering, `visual_start` and `visual_end` will be **swapped**, so the AI generates a forward clip going: `visual_end → visual_start`. This clip is then **reversed in post-processing**, so the viewer sees: `visual_start → visual_end` (the reveal).

## YOUR TASK

Generate **two things** per flagged panel:

### 1. `motion_prompt_reversed`
Describes the **forward-playing clip** the AI will render:
- **At t=0** the AI sees: `visual_end` (the fully revealed/clear state)
- **At t=end** the AI sees: `visual_start` (the obscured/hidden state)
- When played in reverse, the viewer sees: obscure → reveal ✓

### 2. `visual_start_explicit`
A fully explicit rewrite of the original `visual_end` (which becomes the new `visual_start` after the swap).
Required because the original `visual_end` may contain vague phrases like "same framing", "as before", or lack camera details.
**Must include**: shot type (ECU/CU/MS/MLS/LS), camera angle, character position in frame, key props/set elements visible, lighting state. Zero implicit references.

## RETROGRADE MOTION TECHNIQUE

This pass uses the **Retrograde Motion** technique from practical filmmaking: shoot the action forward, then reverse the clip in post. The I2V model only sees forward motion — never reverse instructions. Your job is to find the natural forward physics that, when reversed, produces the desired reveal.

**Forward (what you write) → Reversed (what the viewer sees)**

| Write this (forward)                     | Reverses to (viewer sees)              |
|------------------------------------------|----------------------------------------|
| fog / smoke rolls in, thickens           | fog / smoke disperses, clears          |
| fire ignites, flames grow from ember     | fire extinguishes                      |
| character sinks / crouches / falls down  | character rises dramatically           |
| petals / leaves / ash fall downward      | petals / leaves fly upward             |
| water spills outward from vessel         | water gathers, flows into vessel       |
| crowd gathers, closes in around subject  | crowd disperses, opens up              |
| wound opens, blood spreads outward       | wound closes, heals                    |
| shards / glass scatter outward           | shards fly together, reassemble        |
| door closes, darkness fills room         | door opens, light floods in            |
| paint / ink spreads and covers surface   | paint peels back, surface revealed     |
| sand / snow drifts in, buries object     | sand / snow retreats, object emerges   |
| curtain / veil draws closed              | curtain / veil parts, scene revealed   |

**Vocabulary rule**: every verb must be physically plausible as a forward-playing clip. If a verb sounds like "un-doing" or reversal (disperses, fades out, retreats, rises-from-ground unnaturally), rewrite it using the forward-physics equivalent from the table above or by close analogy.

## BODY MECHANICS RULES (critical for natural reversal)

- **Name exact limb**: "reaches with RIGHT hand", "steps with LEFT foot", "grips with left hand"
- **State face direction at every beat**: "facing camera", "in profile left", "turning 45° toward door"
- **Sequence every movement beat**: weight shift → reach → grip → step → pivot — one sentence each
- **For entries/exits**: track full travel from off-frame edge to full-frame presence (or reverse)
- Forward physics that reverse naturally:
  - character walking AWAY from camera → entry toward camera when reversed
  - door swinging SHUT, character outside → door opening, entry when reversed
  - character sitting DOWN → character rising when reversed

## RULES FOR motion_prompt_reversed

- **100+ words minimum**, very detailed and specific
- Use timestamps: "At 0s...", "At 2s...", "At 5s...", "At 6s..."
- Every motion verb must pass the **Retrograde Motion** test: plausible as natural forward physics
- Do NOT invent new visual elements — only describe the transition between the two provided states
- Preserve all lighting and camera details from `lights_and_camera` exactly
- The clip duration is 7 seconds

## EXAMPLE

**Panel (as written):**
```
visual_start: "Closed office door. Empty hallway."
visual_end: "Secretary inside the room, door open, colleagues laughing in background."
motion_prompt: "At 0s Secretary opens door and enters; colleagues react."
motion_prompt_reversed: ""
```

**Generated output:**
```json
{
  "motion_prompt_reversed": "At 0s: MS shot from room corner — Secretary stands center-frame just inside doorway, coat still settling from entry, colleagues visible over her right shoulder mid-laugh, warm office lighting. Camera static. At 1s she turns head left toward the door, shifts weight to left foot. At 2s she reaches forward with her RIGHT hand and grips the door handle. At 3s she steps backward with right foot through the threshold, body crossing the doorframe. At 4s she steps back again with left foot, now fully in the hallway, still facing INTO the room, left hand holding the door edge. At 5.5s she pulls the door closed with a firm draw, door swinging toward camera, blocking the room. At 6.5s the door clicks shut. Hallway empty — closed door fills frame.",
  "visual_start_explicit": "MS shot from room corner — Secretary stands center-frame just inside doorway, coat mid-settle, right hand at side, colleagues blurred over right shoulder, warm overhead office lighting, door fully open to the left of frame."
}
```

**What gets written to the file:**
```json
{
  "visual_start": "[visual_start_explicit value — explicit shot of the revealed state]",
  "visual_end": "Closed office door. Empty hallway." (was visual_start),
  "motion_prompt": "[the generated motion_prompt_reversed]",
  "motion_prompt_reversed": "[the generated motion_prompt_reversed]"
}
```

## OUTPUT FORMAT

Output a JSON array:

```json
[
  {
    "panel_index": 3,
    "motion_prompt_reversed": "100+ word description of the forward-playing clip...",
    "visual_start_explicit": "Fully explicit shot description of the revealed state (shot type, angle, positions, lighting)..."
  }
]
```

Then confirm which file was updated and list which panels were processed.
