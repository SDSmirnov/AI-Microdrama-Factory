<!-- replace: ## Output Schema Fields -->
## Output Schema Fields
- scene_id: Scene number
- location: Setting description
- pre_action_description: Context before action — what just happened narratively
- panels[]:
  - panel_index: Panel number (1–9)
  - visual_start: Initial static state (70+ words, 16:9 widescreen framing, lighting specified)
  - visual_end: State after micro-action (70+ words)
  - motion_prompt: Precise 5–6s action description with timestamps (100+ words)
  - lights_and_camera: Camera position, lens approximation, lighting setup for this panel
  - dialogue: Exact spoken line shown on screen if this panel carries dialogue (empty string if none)
  - duration: Expected seconds (5–6)
