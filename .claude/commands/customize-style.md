Arguments: $ARGUMENTS
Expected format: `<novel_file> <style_preset>`
Example: `s01e01.txt vertical_9_16_microdrama`

Parse $ARGUMENTS into `novel_file` (first token) and `style_preset` (second token).

## Style Presets

Look up the preset for `style_preset` from the table below:

| Key | Name | Format | Panels | Aspect | Resolution | needs_start_end | needs_dialogue | needs_captions | camera_style |
|-----|------|--------|--------|--------|------------|----------------|----------------|----------------|--------------|
| `vertical_9_16_microdrama` | Vertical MicroDrama - Realistic Cinematic | single_grid_animation | 9 | 9:16 | 2K | true | true | false | cinematic_fpov |
| `vertical_9_16_dark_romance` | Vertical Dark Romance - Realistic Cinematic | single_grid_animation | 9 | 9:16 | 2K | true | true | false | cinematic_fpov |
| `vertical_9_16_long_arc` | Vertical Long Arc - Realistic Cinematic | single_grid_animation | 9 | 9:16 | 2K | true | true | false | cinematic_fpov |

If `style_preset` is not in the table, default to `vertical_9_16_microdrama`.

## Steps

1. Read `novel_file`
2. Analyze the novel and extract metadata (same as `/analyze-novel`):
   - genre, setting (period/location/world_type), pov, tone, main_character (name + description), special_elements, visual_atmosphere
3. Read template files from `lib/prompting/<style_preset>/`: `style.md`, `casting.md`, `scenery.md`, `imagery.md`, `setting.md`
4. Create directory `custom_prompts/` if it doesn't exist
5. Generate and write each of the 6 files below using the loaded preset values and novel metadata
6. At the end, print a summary of all files written

---

## FILE 1: custom_prompts/style.md

Generate using this prompt (mentally execute it and write the result):

> Based on the extracted novel metadata and target visual style **{preset.name}**:
>
> Generate a complete `style.md` file following the structure from the loaded `lib/prompting/<style_preset>/style.md` template. Fill ALL `{{placeholder}}` values with specific values appropriate for **{preset.name}** style.
>
> Guidelines for this style:
> - Camera equipment and techniques specific to this medium (e.g., Arri Alexa for cinematic)
> - Rendering style: photorealistic — match the medium
> - Atmosphere keywords derived from the novel's tone
> - Color grading matching both the style and novel's atmosphere
> - Technical specs: resolution = **{preset.resolution}**, aspect_ratio = **{preset.aspect_ratio}**
>
> Return ONLY the filled markdown content — no explanations, no meta-commentary.

Write the output to `custom_prompts/style.md`.

---

## FILE 2: custom_prompts/casting.md

Generate using this prompt:

> Based on the extracted novel metadata and visual style **{preset.name}**:
>
> Generate a complete `casting.md` file following the structure from the loaded `lib/prompting/<style_preset>/casting.md` template. Fill ALL `{{placeholder}}` values.
>
> Adjust character description format for **{preset.name}**:
> - **Realistic Cinematic**: photorealistic actor descriptions with specific physical features, ethnicity, age, clothing textures
>
> Reference shot aspect ratio for this style: `9:16`.
>
> Return ONLY the filled markdown content.

Write the output to `custom_prompts/casting.md`.

---

## FILE 3: custom_prompts/scenery.md

Generate using this prompt:

> Based on the extracted novel metadata, visual style **{preset.name}**, format **{preset.format}**, panels_per_scene **{preset.panels_per_scene}**:
>
> Generate a complete `scenery.md` file following the structure from the loaded `lib/prompting/<style_preset>/scenery.md` template. Fill ALL `{{placeholder}}` values.
>
> Key adjustments for this style:
> - `needs_start_end` = **{preset.needs_start_end}**
>   - If `true`: include START/END keyframe instructions (panel duration 6–8s for animation)
>   - If `false`: focus on a single key moment per panel (static image, N/A duration)
> - Camera POV style: **{preset.camera_style}** — cinematic_fpov: shooter first-person POV, over-shoulder, immersive
> - Composition conventions: match **{preset.name}** genre norms
>
> Return ONLY the filled markdown content.

Write the output to `custom_prompts/scenery.md`.

---

## FILE 4: custom_prompts/imagery.md

Generate using this prompt:

> For visual style **{preset.name}**, format **{preset.format}**, resolution **{preset.resolution}**, aspect ratio **{preset.aspect_ratio}**, panels per scene **{preset.panels_per_scene}**:
>
> Generate a complete `imagery.md` file following the structure from the loaded `lib/prompting/<style_preset>/imagery.md` template. Fill ALL `{{placeholder}}` values.
>
> Specify:
> - Grid structure: single image with `{preset.panels_per_scene}` panels in grid layout
>   - `single_grid_animation`: animation-targeted, panels show key visual moments (visual_start)
> - Exact row × column count for `{preset.panels_per_scene}` panels
> - Composition rules specific to **{preset.name}** (e.g., film grain for cinematic)
> - Visual consistency requirements
> - Special rendering instructions appropriate to the medium
>
> Return ONLY the filled markdown content.

Write the output to `custom_prompts/imagery.md`.

---

## FILE 5: custom_prompts/setting.md

This file is generated by template substitution — no LLM generation needed.

Read `lib/prompting/<style_preset>/setting.md` and replace these placeholders using the extracted novel metadata:

| Placeholder | Value from novel metadata |
|------------|--------------------------|
| `{{genre_description}}` | `genre` list joined with `, ` |
| `{{setting_description}}` | `setting` object as readable text |
| `{{atmosphere_description}}` | `tone` list joined with `, ` |
| `{{pov_character}}` | `main_character.name` |
| `{{narrator_style}}` | `pov` |
| `{{visual_tone}}` | `tone` list joined with `, ` |
| `{{special_visual_elements}}` | `special_elements` list, each on new line with `  - ` prefix |
| `{{hero_visual_description}}` | `main_character.description` |
| `{{composition_preferences}}` | `{preset.camera_style}` |
| `{{world_specific_details}}` | `visual_atmosphere` list, each on new line with `  - ` prefix |

Write the substituted content to `custom_prompts/setting.md`.

---

## FILE 6: custom_prompts/config.json

Copy `lib/prompting/<style_preset>/config.json` verbatim to `custom_prompts/config.json`. This ensures all fields (transitions, multi_pov, vertical safe zones, etc.) are preserved correctly as a deep-merge override base.
