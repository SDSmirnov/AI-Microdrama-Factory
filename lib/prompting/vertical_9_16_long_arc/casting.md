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
- For every room generate a single 2-panel image, panels stacked vertically:
  - TOP: View from the door
  - BOTTOM: View to the door

## Important for vehicles:
- For every vehicle generate a single 3-panel image, panels stacked vertically:
  - TOP: View outside
  - MIDDLE: View inside from the entrance, wide shot
  - BOTTOM: View inside to the entrance, wide shot

## Visual Description
- Must be verbose, precise, and contain specific features so that AI model can efficiently implement without hallucinations

---
