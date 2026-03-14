# Character Casting Template

## Task
Analyze text for KEY characters/locations/objects/rooms/vehicles and generate photorealistic character references.
Those references will be used for vertical microdrama shots and AI video animation.
IMPORTANT: Think as **Master Cinematographer** for 9:16 portrait format — faces dominate, close-ups are primary.

## Character Description Format
For each NEW character:
- **Name**: Full name
- **Visual Description**: Photorealistic actor description with specific physical features, ethnicity, age, clothing textures
  - Face: Facial structure, eyes, hair color/style, ethnicity
  - Build: Height, build, posture
  - Clothing: Contemporary luxury attire with specific fabric textures
  - Age: Specific age or range
  - Distinctive features: Accessories, grooming, habitual gesture
  - **Everyday Carry (EDC)**: Infer realistic carried items from gender, profession, and social context.
    Real people do not operate via GTA inventory — they carry things somewhere physical.
    - Men: wallet placement (breast pocket / back pocket / money clip), phone pocket, keys
      (car fob + home keyring), work badge/ID if applicable, any occupational items
      (detective: badge wallet + holster; exec: slim briefcase or portfolio)
    - Women: bag type (clutch / crossbody / tote / handbag / backpack — pick the right one for her archetype),
      what it visibly contains or implies (wallet, phone, keys, cosmetics pouch, notebook, etc.)
    - Both: if the character drives, they have car keys; if they live alone, home keys; if they work in
      a secure building, a keycard or lanyard. Do not omit these unless the character is explicitly
      described as having nothing on them.
    State WHERE items are carried and WHAT the carrier looks like (e.g. "tan leather bifold in left
    breast pocket", "black structured tote hanging from right shoulder").

## Location/Object/Room/Vehicle/Interface Description Format
For each NEW reference:
- Name: Full name
- Visual Description: Photorealistic environment description
- Distinctive features

## **IMPORTANT Background RULES** TO STATE IN INSTRUCTIONS
- For characters - use EMPTY BACKGROUND
- For locations/places - use SHOW EMPTY SPACE WITHOUT PEOPLE
- For objects - use BLANK BACKGROUND
- For vehicles and rooms - use BLANK BACKGROUND, SHOW THEM EMPTY, WITHOUT PEOPLE

## Reference Generation
- **Shot Type**: Close-up portrait (3:4 aspect ratio)
- **Expression**: Neutral, composed — with slight underlying tension
- **Lighting**: Soft studio lighting with faint warm side-light simulating luxury interior ambiance
- **Background**: Solid deep-charcoal backdrop
- **Quality**: 8K resolution, sharp focus, photorealistic skin texture

## Important for rooms:

### Room visual_desc — use compass wall layout (MANDATORY format):
Write the room description as a wall-by-wall inventory using cardinal directions.
Assign the entrance door to a wall first, then describe all four walls consistently.
Example format:
```
ROOM SIZE: medium office, ~5×4 m, 2.7 m ceiling, parquet floor, white plaster walls.
NORTH WALL (entrance): solid wood door center, narrow built-in bookshelf to the left of door, coat hook to the right.
SOUTH WALL (opposite): single casement window with roll blinds, centered, city view.
EAST WALL (right when entering): L-shaped work desk with laptop, monitor, desk lamp, filing cabinet underneath.
WEST WALL (left when entering): two visitor chairs in dark leather, small side table between them, framed art above.
CENTER: no obstructions, open floor space.
CEILING/FLOOR: recessed LED strip lighting, warm tone; dark oak parquet.
```
This format MUST be used for every Room ref so that per-view renders know exactly what is visible from each angle.

- For every room generate TWO SEPARATE ref entries (two distinct names, two distinct JSON objects):
  1. `{Room-Name}-View-From-Entrance` — wide shot from the entrance doorway (e.g. NORTH WALL) looking toward the opposite wall (e.g. SOUTH WALL). Shows: opposite wall, left wall, right wall, center. Single portrait image, empty room.
  2. `{Room-Name}-View-To-Entrance` — wide shot from the opposite end of the room looking BACK toward the entrance wall and door. Shows: entrance wall with door, and the wall features behind the viewer's back (rear furniture, windows, decor only visible from this angle). Single portrait image, empty room.
     Set `style_reference` to `{Room-Name}-View-From-Entrance` so furniture materials and style are consistent.

## Important for vehicles:
- For every vehicle generate THREE SEPARATE ref entries:
  1. `{Vehicle-Name}-Exterior` — full exterior, three-quarter front angle, studio lighting.
  2. `{Vehicle-Name}-Interior-From-Entrance` — interior looking IN from driver/main door. Dashboard, seats, controls, cabin details.
     Set `style_reference` to `{Vehicle-Name}-Exterior`.
  3. `{Vehicle-Name}-Interior-To-Entrance` — interior looking TOWARD the entrance from the back seat.
     Rear cabin, headrests, door panels, details not visible from entrance side.
     Set `style_reference` to `{Vehicle-Name}-Interior-From-Entrance`.

## Visual Description
- Must be verbose, precise, and contain specific features so that AI model can efficiently implement without hallucinations

---
