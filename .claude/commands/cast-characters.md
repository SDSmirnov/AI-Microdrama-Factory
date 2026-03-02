Novel file: $ARGUMENTS

Steps:
1. Read the novel file at `$ARGUMENTS`
2. Check if `custom_prompts/casting.md` exists — use it; otherwise use `prompts/casting.md`. Read it.
3. Check if `custom_prompts/setting.md` exists — use it; otherwise use `prompts/setting.md`. Read it.
4. List all `.png` files in `ref_thriller/` — these are already-generated references; only describe NEW ones.
5. Generate character/location/object descriptions following all instructions below.
6. For each new reference, write its metadata to `ref_thriller/{safe_name}.json` where `safe_name` is the name lowercased with spaces replaced by underscores (e.g., `ref_thriller/ruslan_vikonov.json`).
7. Output the ready-to-use image generation prompt for each new reference.

---

Apply the casting template instructions and visual style from the loaded `casting.md` and `setting.md`.

## ROLE: MASTER CINEMATOGRAPHER — CASTING

Think as a Master Cinematographer analyzing what will physically appear on screen when the entire story is filmed. Identify every KEY reference that needs a visual anchor image.

## REFERENCE TYPES TO IDENTIFY

- **Character**: Protagonist, antagonists, supporting cast with screen time
- **Location**: Distinct physical spaces (exterior establishing shots)
- **Room**: Interior spaces with distinct visual identity
- **Vehicle**: Cars, ships, spacecraft — exterior + interior views
- **Object**: Props with meaningful screen presence (weapons, devices, documents)
- **Interface**: Screens, dashboards, UI elements

## DESCRIPTION RULES

- `name`: Clean identifier — letters, digits, hyphens only. No quotes, punctuation, or parentheses.
- `visual_desc`: 100+ words. Precise enough for AI image generation with zero hallucination. Include: facial structure, eye shape/color, hair style/color, skin tone, build/height, clothing with textures and colors, distinctive features, age.
- `video_visual_desc`: 30–50 words. Shorter version for use inside scene panel prompts.
- `style_reference`: Name of an existing reference image to use as visual style base, or same `name` if entirely new.
- `type`: Character / Location / Object / Room / Vehicle / Interface

## BACKGROUND RULES FOR IMAGE GENERATION PROMPTS

- Characters → **empty/solid neutral backdrop**
- Locations → **empty space, no people**
- Objects → **blank background**
- Vehicles → **blank background, empty, no people**
- Rooms → **empty room, no people**

## SPECIAL MULTI-PANEL FORMATS

**Rooms** — generate a 2-panel vertical image:
- TOP: View from the door
- BOTTOM: View toward the door

**Vehicles** — generate a 3-panel vertical image:
- TOP: Exterior view
- MIDDLE: Interior from entrance, wide shot
- BOTTOM: Interior toward entrance, wide shot

## IMAGE GENERATION PROMPT TEMPLATE

For each new reference, output a ready-to-copy image generation prompt:

**Character**: `CINEMATIC REFERENCE FOR CHARACTER: {name}. {visual_desc}. Close-up portrait, neutral expression, uniform studio lighting, solid neutral backdrop, 8K resolution, sharp focus.`

**Location/Room/Vehicle/Object/Interface**: `CINEMATIC REFERENCE FOR {TYPE}: {name}. {visual_desc}. Empty, no people. {appropriate shot type}. 8K resolution.`

## OUTPUT FORMAT

```json
[
  {
    "name": "reference-name",
    "visual_desc": "Verbose 100+ word description for image generation",
    "type": "Character|Location|Object|Room|Vehicle|Interface",
    "video_visual_desc": "Concise 30-50 word description for use in scene prompts",
    "style_reference": "reference-name-or-existing-ref"
  }
]
```

After the JSON, list each reference with its image generation prompt under a `## Image Generation Prompts` heading.
