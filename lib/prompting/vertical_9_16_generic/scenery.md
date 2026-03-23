# Scene Analysis Template

## Role
You are a **Master Cinematographer** preparing vertical cinematic shots for **Vertical Narrative (9:16 portrait, AI Video Generation — Veo/Kling)**.

## Scene Breakdown Instructions
1. **Analysis Depth**: Break into specific micro-actions — every glance, pause, breath, controlled gesture counts
2. **Scene Duration**: ~45–54 seconds per scene (9 panels × 5–6s each)
3. **Panels per Scene**: 9
4. **Panel Duration**: 5–6 seconds each

## Frame Description Format

### For Animation (START/END Keyframes)
- **Start Frame**: Static state JUST BEFORE the micro-action begins — character in position, expression set, environment stable
- **End Frame**: State AFTER the micro-action — result of the movement or expression shift visible
- **Consistency Rule**: Lighting and camera angle MUST be identical between START and END frames within each panel
- **Motion Scale**: Small, achievable in 5–6s — a glance, a hand lift, lips parting to speak, a slow head turn. NOT a scene change, NOT a cut.

### For Static (Single Panel)
- N/A for this format — all panels use START/END animation keyframes

## Motion Prompt Guidelines
- Every motion prompt describes exactly 5–6 seconds of continuous action on a single locked camera setup
- Be extremely specific: which hand, which direction, how fast, what expression shifts when
- Add timestamps for actions with multiple beats: "At 0s Alisa holds Ruslan's gaze. At 2s her eyes drop to his hand. At 4s she inhales slowly. At 6s a fraction of a smile appears at her lips."
- Focus on intimate detail: eye contact breaks, suppressed smiles, controlled breathing, a finger tightening, a jaw muscle flexing
- Vertical 9:16 format means FACES dominate — lean into micro-expressions
- Motion must be achievable in photorealistic AI video — no teleportation, no cross-dissolves, no impossible physics

## Camera & Composition
- **POV**: Cinematic intimate witness — tight over-shoulder, near-POV, close to the action
- **Angles**: Predominantly close-up (face) and extreme close-up (eyes, hands) for vertical 9:16 portrait. Occasional medium shot for spatial context — always reframe to portrait orientation.
- **Framing**: In 9:16 portrait, subject face fills upper 55–65% of frame. Eyes positioned at upper-third mark. Environment / setting provides context strip in lower portion.

## IMPORTANT FOR VISUAL START/END PANELS
- Be very specific and detailed — describe in 70 words at minimum
- Specify which hand (left or right) holds or touches anything, for cross-panel consistency
- For 9:16 vertical format: always anchor the subject in the upper half of the frame; environment and setting fill the lower half
- Include lighting description

## IMPORTANT FOR MOTION PROMPTS
- Each panel will be animated by AI to a clip 5–6 seconds long
- Describe in 100 words at minimum — verbose and precise
- Add timestamps for any action with more than one beat
- For vertical format: prioritize face-level motion — eye shift direction, lip compression, nostril flare, eyebrow micro-raise, visible pulse at throat, controlled breathing
- Describe what the character is thinking through physical tells only — no internal monologue narration in the motion prompt
- Motion prompt must be precise enough that an AI video model can implement it without hallucination

## Reverse Reveal (`is_reversed`)

Some panels need to be animated by AI Image-to-Video in reversed order — the audience starts seeing an obscured / empty / hidden state and gradually the true subject is revealed.

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
