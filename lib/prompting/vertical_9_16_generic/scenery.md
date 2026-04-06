## Reverse Reveal (`is_reversed`)

Some panels need to be animated by AI Image-to-Video in reversed order — the audience starts seeing an obscured / empty / hidden state and gradually the true subject is revealed.
Panels will be animated as 6 to 8 second clips by the AI video model, which does NOT support image references.
The only way to show a character or object ENTERING the frame is reverse playback:
- render the character LEAVING, then play the clip reversed.

Set is_reversed=true for any panel where:
- A character enters the scene, walks in, or appears from off-screen.
- An object comes into view (door opens revealing someone, fog clears to show a figure, etc.).
- Someone approaches the camera from a distance.
- visual_end shows a presence that is ABSENT in visual_start.
- A character's FACE is hidden at visual_start (back to camera, hood up, silhouette, turned away)
  and is REVEALED during the motion (turns around, removes hood, steps into light facing camera).
  Shoot the character turning AWAY (face → back), reverse so viewer sees the face reveal.

### How to use
1. **Set `is_reversed: true`** on the panel.
2. Write `visual_start` and `visual_end` **in normal chronological order** (start = before the action, end = after). The pipeline will **swap them automatically** before rendering.
3. Write `motion_prompt` in normal chronological order — it is kept as the **narrative record**.
4. Leave `motion_prompt_reversed` as an **empty string** — it will be populated by the reversal pass.

### When to use
- A character's face must be the **final, crisp reveal** (reflection materialises in a window)
- A scene opens on abstraction / bokeh / darkness and builds toward reveal

## Output Schema Fields
- scene_id: Scene number
- location: Setting description
- pre_action_description: Context before action — what just happened narratively
- panels[]:
  - panel_index: Panel number (1–9)
  - visual_start: Initial static state (70+ words, 9:16 vertical framing, lighting specified)
  - visual_end: State after micro-action (70+ words)
  - motion_prompt: Precise 5–6s action description with timestamps (100+ words)
  - lights_and_camera: Camera position, lens approximation, lighting setup for this panel
  - dialogue: Exact spoken line shown on screen if this panel carries dialogue (empty string if none)
  - duration: Expected seconds (5–6)
