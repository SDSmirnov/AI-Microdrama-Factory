Arguments: $ARGUMENTS
Expected format: `<novel_file> <style_preset>`
Example: `s01e01.txt realistic_movie`

Parse $ARGUMENTS into `novel_file` (first token) and `style_preset` (second token).

## Style Presets

Look up the preset for `style_preset` from the table below:

| Key | Name | Format | Panels | Aspect | Resolution | needs_start_end | needs_dialogue | needs_captions | camera_style |
|-----|------|--------|--------|--------|------------|----------------|----------------|----------------|--------------|
| `vertical_microdrama` | Vertical MicroDrama - Realistic Cinematic | single_grid_animation | 9 | 9:16 | 2K | true | true | false | cinematic_fpov |
| `realistic_movie` | Realistic Cinematic | single_grid_animation | 9 | 16:9 | 2K | true | true | false | cinematic_fpov |
| `anime` | Anime Style | single_grid | 6 | 16:9 | 2K | false | true | false | dynamic_angles |
| `comic_book` | Comic Book | single_grid | 9 | 2:3 | 2K | false | true | false | comic_dramatic |
| `graphic_novel` | Graphic Novel | single_grid | 6 | 2:3 | 2K | false | false | true | artistic_composition |
| `watchmen_style` | The Watchmen Comic | single_grid | 9 | 2:3 | 2K | false | true | true | symmetrical_grounded |

If `style_preset` is not in the table, default to `realistic_movie`.

## Steps

1. Read `novel_file`
2. Analyze the novel and extract metadata (same as `/analyze-novel`):
   - genre, setting (period/location/world_type), pov, tone, main_character (name + description), special_elements, visual_atmosphere
3. Read `prompts/style.md`, `prompts/casting.md`, `prompts/scenery.md`, `prompts/imagery.md`, `prompts/setting.md`
4. Create directory `custom_prompts/` if it doesn't exist
5. Generate and write each of the 6 files below using the loaded preset values and novel metadata
6. At the end, print a summary of all files written

---

## FILE 1: custom_prompts/style.md

Generate using this prompt (mentally execute it and write the result):

> Based on the extracted novel metadata and target visual style **{preset.name}**:
>
> Generate a complete `style.md` file following the structure from the loaded `prompts/style.md` template. Fill ALL `{{placeholder}}` values with specific values appropriate for **{preset.name}** style.
>
> Guidelines for this style:
> - Camera equipment and techniques specific to this medium (e.g., Arri Alexa for cinematic, digital anime studio for anime, ink/scan process for comics)
> - Rendering style: photorealistic / cel-shaded / ink-and-halftone / painted — match the medium
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
> Generate a complete `casting.md` file following the structure from the loaded `prompts/casting.md` template. Fill ALL `{{placeholder}}` values.
>
> Adjust character description format for **{preset.name}**:
> - **Realistic Cinematic**: photorealistic actor descriptions with specific physical features, ethnicity, age, clothing textures
> - **Anime Style**: anime character design — hair style/color/length, eye shape/color, costume details, chibi-to-realistic ratio
> - **Comic Book**: bold distinctive features, iconic costume design, strong silhouette, high contrast traits
> - **Graphic Novel**: artistic expressive features, painterly details, emotional visual language
> - **The Watchmen Comic**: grounded realistic features with symbolic costume/design elements, psychological depth in visual traits
>
> Reference shot aspect ratio for this style: `3:4` (default for all styles).
>
> Return ONLY the filled markdown content.

Write the output to `custom_prompts/casting.md`.

---

## FILE 3: custom_prompts/scenery.md

Generate using this prompt:

> Based on the extracted novel metadata, visual style **{preset.name}**, format **{preset.format}**, panels_per_scene **{preset.panels_per_scene}**:
>
> Generate a complete `scenery.md` file following the structure from the loaded `prompts/scenery.md` template. Fill ALL `{{placeholder}}` values.
>
> Key adjustments for this style:
> - `needs_start_end` = **{preset.needs_start_end}**
>   - If `true`: include START/END keyframe instructions (panel duration 6–8s for animation)
>   - If `false`: focus on a single key moment per panel (static image, N/A duration)
> - Camera POV style: **{preset.camera_style}**
>   - `cinematic_fpov`: shooter first-person POV, over-shoulder, immersive
>   - `dynamic_angles`: anime-style dramatic angles, speed lines, expressive framing
>   - `comic_dramatic`: bold foreshortening, action diagonals, heroic low angles
>   - `artistic_composition`: painterly composition, negative space, mood-driven framing
>   - `symmetrical_grounded`: Watchmen-style fixed symmetric panels, ground-level camera, clinical detachment
> - Composition conventions: match **{preset.name}** genre norms
>
> Return ONLY the filled markdown content.

Write the output to `custom_prompts/scenery.md`.

---

## FILE 4: custom_prompts/imagery.md

Generate using this prompt:

> For visual style **{preset.name}**, format **{preset.format}**, resolution **{preset.resolution}**, aspect ratio **{preset.aspect_ratio}**, panels per scene **{preset.panels_per_scene}**:
>
> Generate a complete `imagery.md` file following the structure from the loaded `prompts/imagery.md` template. Fill ALL `{{placeholder}}` values.
>
> Specify:
> - Grid structure: single image with `{preset.panels_per_scene}` panels in grid layout
>   - `single_grid_animation`: animation-targeted, panels show key visual moments (visual_start)
>   - `single_grid`: static, one image per panel
> - Exact row × column count for `{preset.panels_per_scene}` panels
> - Composition rules specific to **{preset.name}** (e.g., film grain for cinematic, halftone dots for comic, cel shading for anime, ink lines for graphic novel)
> - Visual consistency requirements
> - Special rendering instructions appropriate to the medium
>
> Return ONLY the filled markdown content.

Write the output to `custom_prompts/imagery.md`.

---

## FILE 5: custom_prompts/setting.md

This file is generated by template substitution — no LLM generation needed.

Read `prompts/setting.md` and replace these placeholders using the extracted novel metadata:

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

Generate this JSON deterministically from the preset values — no LLM needed:

```json
{
  "format": {
    "type": "{preset.format}",
    "panels_per_scene": {preset.panels_per_scene}
  },
  "image_generation": {
    "aspect_ratio": "{preset.aspect_ratio}",
    "resolution": "{preset.resolution}",
    "image_size": "{preset.resolution}"
  },
  "animation": {
    "enabled": {preset.needs_start_end},
    "keyframe_type": "start_end" if needs_start_end else "static"
  },
  "slicing": {
    "enabled": true,
    "frame_types": ["start", "end"] if needs_start_end else ["static"]
  },
  "dialogue": {
    "enabled": {preset.needs_dialogue},
    "placement": "captions" if needs_captions else "metadata_only"
  },
  "captions": {
    "enabled": {preset.needs_captions}
  },
  "reference_characters": {
    "enabled": true,
    "auto_cast": true
  }
}
```

Fill in the actual boolean and string values from the preset — do not write template syntax. Write the result to `custom_prompts/config.json`.
