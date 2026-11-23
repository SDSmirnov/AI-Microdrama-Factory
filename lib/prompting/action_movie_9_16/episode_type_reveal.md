## EPISODE TYPE: REVEAL — DISCOVERY THAT REFRAMES THE STORY

This episode builds to one moment of new information. Every earlier panel moves the character physically toward it.

### RHYTHM

Panels run 5–{{VIDEO_MAX_SECONDS}}s and lengthen toward the reveal. Adapt this shape to the source:
- **Approach [MS, CU]** — ordinary activity with something slightly wrong: a door that should be closed, a light that should be off.
- **Signal [CU, ECU]** — the character notices. Not the reveal — the first wrong detail, and the first flicker on the face.
- **Advance [MS]** — the deliberate physical approach: the hand on the handle, the pause, the step in. Ambient sound thins out.
- **The reveal [WS, ECU, or reversed]** — complete and unambiguous. A space or a body: WS. An object or text: ECU. A face or identity: use `is_reversed: true` so the clear face is the final frame.
- **Reaction [ECU]** — the face that now knows: a swallow, the jaw, the eyes. Hold it. Do not resolve — the next episode begins in the changed world.

### SEEDING

Plant at least two signals before the reveal that read differently afterwards — an object in the wrong place at the edge of an MS, a reflection that shows more than the direct view. Name each seed in the panel's STAKE line. Seeds come from the source; do not invent evidence.

### REVERSED REVEAL

For `is_reversed: true`: `visual_start` is the obscured state (shadow, back to camera, document folded), `visual_end` the clear state. Write `motion_prompt` chronologically and leave `motion_prompt_reversed` empty.

### SOUND

Normal ambient during the approach; a wrong sound intrudes and stops at the signal; ambient near-silence on the advance. At the reveal use one diegetic sound or none. No music stings.

### FORBIDDEN

- The reveal arriving with no approach
- A partial reveal — it must be visually complete in its panel
- Resolving the reaction inside this episode
- Music described in `sound_design`
