## Reverse Reveal (`is_reversed`)

Some panels need to be animated in reversed order — the audience starts seeing an obscured or empty state and gradually the true subject is revealed.
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
2. Write `visual_start` and `visual_end` in normal chronological order (start = before, end = after). The pipeline swaps them automatically before rendering.
3. Write `motion_prompt` in normal chronological order — it is the narrative record. The pipeline generates `motion_prompt_reversed` automatically.
4. Leave `motion_prompt_reversed` as an empty string.

### When to use
- A character's face must be the final, crisp, reference-accurate reveal
- A scene opens on abstraction/bokeh/darkness and builds toward character reveal
- Examples: city-light bokeh sharpening into a face, a frosted window clearing, shadow dissolving to expression

### Example
```json
{
  "is_reversed": true,
  "visual_start": "The rain-streaked cafe window shows only blurred warm light and diffuse shapes. No face visible.",
  "visual_end": "Alisa's face is now clearly visible in the glass reflection — pale green eyes scanning forward, expression unreadable. The cafe interior softly blurred behind her.",
  "motion_prompt": "At 0s Alisa turns her gaze toward the window. At 3s her reflection sharpens as a car passes outside. At 6s her full face is visible in the glass, jaw slightly set.",
  "motion_prompt_reversed": ""
}
```

## Output Schema Fields
- scene_id: Scene number
- location: Setting description
- pre_action_description: Context before action — what just happened narratively
- panels[]:
  - panel_index: Panel number (1–9)
  - visual_start: Initial dramatic state (70+ words, 9:16 vertical framing, lighting specified)
  - visual_end: State after the panel's core action (70+ words)
  - motion_prompt: Precise 6s action description with timestamps at every beat (100+ words)
  - lights_and_camera: Camera position, shot scale, lens approximation, lighting setup
  - dialogue: Exact spoken line if this panel carries dialogue (empty string if none)
  - voiceover: Inner monologue — reveals subtext the image cannot show; NEVER narrates the visible
  - duration: 6 (always — hard cap)
