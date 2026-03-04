Episode number to process: $ARGUMENTS

Steps:
1. Read `cinematic_render/animation_episodes.json`
2. Extract the episode where `episode_id` equals $ARGUMENTS
3. Check if `custom_prompts/scenery.md` exists — use it; otherwise use `prompts/scenery.md`. Read it.
4. Check if `custom_prompts/setting.md` exists — use it; otherwise use `prompts/setting.md`. Read it.
5. Check if `custom_prompts/config.json` exists — use it; otherwise use `prompts/config.json`. Read it for `panels_per_scene` and `animation.enabled`.
6. List all `.png` files in `ref_thriller/` — these are the available character/location references.
7. Generate scene keyframes following all instructions below. Set `episode_id` = $ARGUMENTS in every scene object.
8. Write output to `cinematic_render/animation_episode_scenes_{episode_id:03d}.json` (zero-padded to 3 digits).
9. **Update `cinematic_render/animation_metadata.json` (single source of truth):**
   - If the file exists, read it. Remove all scenes where `episode_id` equals $ARGUMENTS. Find the `scene_id` of the last remaining scene (or 0 if none). Assign sequential `scene_id` values to the new scenes starting from that value + 1. Insert the new scenes, keeping all others, sorted by `scene_id`. Preserve the existing `config` key if present, otherwise set it from the config loaded in step 5.
   - If the file does not exist, create it as `{"scenes": [...new scenes with scene_id starting at 1...], "config": <config from step 5>}`.
   - Write the result back to `cinematic_render/animation_metadata.json`.

---

Apply the scenery template instructions from the loaded `scenery.md` and setting context from `setting.md`.

## ROLE: MASTER CINEMATOGRAPHER — KEYFRAME GENERATION

You prepare keyframe assets for AI-based Image-To-Video story visualization. You are generating production-ready panel descriptions that drive image and video generation models.

## CONTEXT

- Available character/location references (from `ref_thriller/` PNGs): use only names matching these files for the `references` field
- `panels_per_scene`: from config.json (default: 9)
- `animation.enabled`: from config.json — determines whether to use `visual_start`/`visual_end` or a single visual

## PANEL DESCRIPTION RULES

### visual_start
State JUST BEFORE the action — tense, static, anticipatory. **70+ words minimum.** Specify: character positions, clothing (textures, colors), props in each hand (left/right specified), lighting direction, camera framing, background details.

### visual_end
State AFTER the micro-action — result is visible. **70+ words minimum.** Only the subjects change — lighting and camera remain IDENTICAL to visual_start.

### motion_prompt
Precise instruction for the AI video model for a 6–8 second clip. **100+ words minimum.** Add timestamps for complex actions:
- "At 0s Ruslan sits still, glass in his right hand..."
- "At 3s he slowly lifts the glass..."
- "At 6s he sets it down, eyes still on Alisa."

Camera movement: specify if camera is static, slow push-in, pan direction and degrees, rack focus.

### lights_and_camera
Camera angle, lens type (anamorphic, 50mm prime, wide), focal length, depth of field (shallow/deep), key light position, fill ratio. Must be IDENTICAL between start/end.

### dialogue
Russian text only. Format as `"Имя: 'реплика.'"`. ≤8 words per line — staccato, emotionally specific. Empty string if no dialogue in panel.

### voiceover
Off-screen narration / inner monologue in Russian, synced to panel action. Reveals subtext — what the viewer CANNOT see (fear, memory, desire). Never describes what is visually obvious. Empty string if not applicable.

### emotional_beat
Single dominant emotion of this panel. Choose one: `tension`, `revelation`, `grief`, `desire`, `defiance`, `dread`, `relief`, `rage`, `longing`, `shock`, `shame`, `triumph`.

### hook_type
Role of this panel in episode dramaturgy: `cold_open` | `escalation` | `confrontation` | `twist` | `cliffhanger` | `none`. Panel 1 of Episode 1 MUST be `cold_open`. Final panel of every episode MUST be `cliffhanger`.

### text_safe_composition
`true` when key subjects (faces, hands, action) are composed in the middle 65% of frame height, leaving top 15% and bottom 20% clear for subtitle overlays. Default `true` for all dialogue/voiceover panels.

### caption
Narrative text overlay if captions are enabled in config. Empty string otherwise.

### references
List of reference names (matching filenames from `ref_thriller/` without extension) that physically appear in this panel.

### is_reversed
Set `true` ONLY when the viewer must see an obscured/hidden state first, then a crisp reveal (fog clearing, door opening, hands withdrawing). Write `visual_start`/`visual_end` in NORMAL chronological order — the pipeline swaps them for rendering.

### motion_prompt_reversed
Always leave as empty string `""` — populated by the `/reversal-pass` skill.

### duration
Expected clip length in seconds: 6–8.

## COVERAGE RULES

- EACH SCENE must have EXACTLY `panels_per_scene` panels from config.json
- Create as many scenes as needed to cover the COMPLETE episode narrative
- All dialogue and voiceover must be in Russian
- We are filming an Action Movie — scenes must fully show the story

## OUTPUT FORMAT

```json
{
  "scenes": [
    {
      "scene_id": 1,
      "episode_id": 1,
      "location": "INT. LOCATION — TIME OF DAY",
      "pre_action_description": "Setup/context before the first panel action begins",
      "panels": [
        {
          "panel_index": 1,
          "visual_start": "70+ word description of initial static state...",
          "visual_end": "70+ word description after micro-action...",
          "motion_prompt": "100+ word timestamped motion instruction...",
          "is_reversed": false,
          "motion_prompt_reversed": "",
          "lights_and_camera": "Camera: 50mm anamorphic, shallow DOF. Key light: 45° right, warm tungsten. Fill: soft left.",
          "dialogue": "",
          "voiceover": "",
          "emotional_beat": "tension",
          "hook_type": "none",
          "text_safe_composition": true,
          "caption": "",
          "duration": 7,
          "references": ["Character-Name", "location-name"]
        }
      ]
    }
  ]
}
```
