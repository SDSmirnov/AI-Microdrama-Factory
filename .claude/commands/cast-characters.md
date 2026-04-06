Novel file: $ARGUMENTS

Steps:
1. Read the novel file at `$ARGUMENTS`
2. Check if `custom_prompts/casting.md` exists — use it; otherwise use `lib/prompting/vertical_9_16_microdrama/casting.md`. Read it.
3. Check if `custom_prompts/setting.md` exists — use it; otherwise use `prompts/setting.md`. Read it.
4. List all `.json` files in `ref_thriller/` and read each one to get existing references (name + logline_subject_info). Only generate NEW ones not already covered.
5. Generate character/location/object descriptions following all instructions below.
6. For each new reference, write its metadata to `ref_thriller/{safe_name}.json` where `safe_name` is the name lowercased with spaces replaced by underscores (e.g., `ref_thriller/ruslan_vikonov.json`).
7. Output the ready-to-use image generation prompt for each new reference.

---

Apply ALL rules from the loaded `casting.md` and `setting.md` exactly — including reference types, character EDC (Everyday Carry), compass-layout formats for rooms and outdoor locations, multi-entry formats for rooms/vehicles/outdoor, and image generation prompt templates.

## ROLE: MASTER CINEMATOGRAPHER — CASTING

Think as a Master Cinematographer analyzing what will physically appear on screen when the entire story is filmed. Identify every KEY reference that needs a visual anchor image.

## DEDUPLICATION RULES

Match by IDENTITY, not by name. If a character/place in the text is the same entity as an existing reference (same role, same location, same object) — SKIP IT, even if the name differs slightly. Only add a NEW entry if it is genuinely a different entity. If unsure, prefer reusing an existing reference over creating a new one.

## OUTPUT FORMAT

```json
[
  {
    "name": "reference-name",
    "logline_subject_info": "One-sentence role/identity in the story",
    "visual_desc": "Verbose 100+ word description for image generation",
    "type": "Character|Location|Object|Room|Vehicle|Interface|Outdoor",
    "video_visual_desc": "Concise 30-50 word description for use in scene prompts",
    "style_reference": "reference-name-or-existing-ref"
  }
]
```

**Multi-entry types** (generate multiple JSON objects per source entity — follow naming conventions from casting.md exactly):
- **Room** → `{Room-Name}-View-From-Entrance` + `{Room-Name}-View-To-Entrance`
- **Vehicle** → `{Vehicle-Name}-Exterior` + `{Vehicle-Name}-Interior-From-Entrance` + `{Vehicle-Name}-Interior-To-Entrance`
- **Outdoor** → `{Outdoor-Name}-View-Primary` + `{Outdoor-Name}-View-Opposite`

After the JSON, list each reference with its image generation prompt under a `## Image Generation Prompts` heading.
