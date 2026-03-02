Scene file for reversal pass: $ARGUMENTS

Steps:
1. Read the scene JSON file at `$ARGUMENTS`
2. Find all panels where `is_reversed` is `true`
3. If no reversed panels exist, output "No reversed panels found — nothing to do." and stop.
4. Check if `custom_prompts/setting.md` exists — use it; otherwise use `prompts/setting.md`. Read it for visual style context.
5. Generate `motion_prompt_reversed` for each flagged panel following all instructions below.
6. For each reversed panel in the JSON:
   - Set `motion_prompt_reversed` to the generated value
   - Swap `visual_start` ↔ `visual_end`
   - Replace `motion_prompt` with the generated `motion_prompt_reversed`
7. Write the updated JSON back to the same file path (overwrite).

---

## ROLE: MASTER CINEMATOGRAPHER — REVERSAL PASS

You are writing motion prompts for AI Image-to-Video generation for panels that use **Reverse Reveal** animation.

## HOW REVERSE REVEAL WORKS

The panel was written in normal chronological order:
- `visual_start` = before the action (e.g., "fog fills the frame, nothing visible")
- `visual_end` = after the action (e.g., "hedgehog stands in clearing, knife drawn")

For rendering, `visual_start` and `visual_end` will be **swapped**, so the AI generates a forward clip going: `visual_end → visual_start`. This clip is then **reversed in post-processing**, so the viewer sees: `visual_start → visual_end` (the reveal).

## YOUR TASK

Write `motion_prompt_reversed` describing the **forward-playing clip** that the AI will actually generate:
- **At t=0** the AI sees: `visual_end` (the fully revealed/clear state)
- **At t=end** the AI sees: `visual_start` (the obscured/hidden state)
- The motion_prompt_reversed describes this forward transition (reveal → obscure)
- When this clip is played in reverse by the pipeline, the viewer sees: obscure → reveal ✓

## RULES FOR motion_prompt_reversed

- **100+ words minimum**, very detailed and specific
- Use timestamps: "At 0s...", "At 2s...", "At 5s...", "At 6s..."
- Motion must be **physically plausible as a forward-playing clip** (fog rolling IN, not dispersing)
- Do NOT invent new visual elements — only describe the transition between the two provided states
- Preserve all lighting and camera details from `lights_and_camera` exactly
- The clip duration is 7 seconds

## EXAMPLE

**Panel (as written):**
```
visual_start: "Dense, uniform fog fills the entire frame. Nothing visible. Total white silence."
visual_end: "Hedgehog stands in a moonlit clearing, right paw gripping a small folding knife, fur bristling."
motion_prompt: "At 0s the hedgehog steps forward from the fog. At 4s he raises his right paw and draws the knife."
motion_prompt_reversed: ""
```

**Generated motion_prompt_reversed** (forward clip: hedgehog → fog):
> "At 0s the hedgehog stands clearly in the moonlit clearing, right paw gripping the folding knife, every detail sharp. The camera holds static. At 1s thin wisps of white fog drift in from the left edge of frame, curling around the hedgehog's feet. At 3s the fog thickens rapidly, obscuring the hedgehog's lower body and left side. His eyes remain visible for a moment. At 5s the fog surges forward, swallowing the clearing entirely. At 6.5s the frame is completely white, uniform, silent — nothing visible. Camera static throughout, shallow DOF on where the hedgehog stood."

**What gets written to the file:**
```json
{
  "visual_start": "Hedgehog stands in a moonlit clearing..." (was visual_end),
  "visual_end": "Dense fog fills the entire frame..." (was visual_start),
  "motion_prompt": "[the generated motion_prompt_reversed]",
  "motion_prompt_reversed": "[the generated motion_prompt_reversed]"
}
```

## OUTPUT FORMAT

First output the analysis as a JSON array:

```json
[
  {
    "panel_index": 3,
    "motion_prompt_reversed": "100+ word description of the forward-playing clip (reveal state → obscured state)..."
  }
]
```

Then confirm which file was updated and list which panels were processed.
