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
- **Behavioral Signature**: How this character behaves under pressure — derive from their decisions, speech patterns, and reactions in the source text.
  - Default power move: their go-to strategy to assert control or dominance
  - Deflection strategy: how they redirect or absorb pressure when threatened
  - Involuntary tell: the physical or verbal tic that betrays their true state (lying, fear, want)
  E.g. "Under pressure: retreats to bureaucratic procedure — cites rules, demands paperwork, buys time through process. Power move: silence and stillness while the other person fills the void. Tell: touches left cuff link when lying."
- **Physical Vocabulary**: How this character habitually occupies space — derive from their role, psychology, and body language in the source.
  - Default posture: how they hold themselves at rest vs. under pressure
  - Space use: how they move through a room (invade / retreat / orbit / anchor to one spot)
  - Signature gestures: 1–2 recurring physical behaviors that define this character on screen
  E.g. "Never sits during confrontation — paces or leans against a surface. Invades space deliberately when he wants something, closing distance by 20cm. Hands always visible and deliberately still (controlled restraint). Retreating is not in his vocabulary — turns his back instead of stepping away."
  NOTE: these behavioral patterns are character psychology — when realized in panel descriptions (visual_start / motion_prompt), "invades" becomes "camera sees him rotate to side profile, chest directed at [Other], closing 20cm"; "retreats" becomes "camera sees him in three-quarter rear profile, neck turned back." Use the compound camera-visible form per the INTER-CHARACTER BODY ORIENTATION LAW.

## Character Appearance Variations

When a character's outfit or visual context changes significantly across scenes (e.g. casual vs. formal, day vs. night, home vs. event), generate **separate variation refs** for each distinct look.

### When to generate variations
- Different clothing contexts (work uniform, evening gown, casualwear, nightwear)
- Major time-of-day transitions that change attire (morning home → evening event)
- Post-event states (post-gym, disheveled after confrontation, hospital gown)
- Do NOT generate variations for minor accessory changes (tie on/off, jacket removed)

### Primary character ref
The primary ref (e.g. `Alisa`) captures **permanent identity**: face, build, hair, skin.
- `visual_desc` / `video_visual_desc`: neutral everyday appearance + face baseline
- `variations`: list all variation slug names (e.g. `["Alisa-Jeans", "Alisa-Gown", "Alisa-Bathrobe"]`)
- `behavioral_signature` / `physical_vocabulary`: set here (variations inherit if left empty)

### Variation ref
Each variation (e.g. `Alisa-Gown`) captures the **outfit/context delta**:
- `name`: `{ParentName}-{VariantLabel}` — e.g. `Alisa-Gown`, `Alisa-Bathrobe`
- `character_ref`: exact name of parent ref (e.g. `Alisa`)
- `context`: when this variation applies — used by the scene generator to auto-select.
  E.g. `"Evening formal event or theater attendance. Worn when Alisa is at an upscale social venue."`
- `visual_desc`: FULL photorealistic description — face (copied from parent) + outfit + accessories.
  Variation image is rendered standalone; the parent face ref is not shown alongside it.
- `video_visual_desc`: outfit + distinguishing features only. Face/build not needed — inherits from parent.
- `style_reference`: set to the parent character ref name for face consistency.
- `behavioral_signature` / `physical_vocabulary`: leave empty (inherited from parent at runtime).

### Example
```
Primary: Alisa
  visual_desc: "Slim woman in her late 20s, sharp Slavic features..."
  variations: ["Alisa-Jeans", "Alisa-Gown", "Alisa-Bathrobe"]

Variation: Alisa-Jeans
  character_ref: "Alisa"
  context: "Casual home setting, morning or daytime. Default everyday wear."
  style_reference: "Alisa"

Variation: Alisa-Gown
  character_ref: "Alisa"
  context: "Evening formal event, theater, dress code required."
  style_reference: "Alisa"

Variation: Alisa-Bathrobe
  character_ref: "Alisa"
  context: "Night or late evening at home. Post-event or pre-sleep."
  style_reference: "Alisa"
```

## Location/Object/Room/Vehicle/Outdoor/Interface Description Format
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
     CRITICAL — LEFT/RIGHT ARE SWAPPED in this view (180° turn from entrance): what was on the WEST wall (left when entering) is now on the RIGHT side of the image; what was on the EAST wall (right when entering) is now on the LEFT. Label each wall with its correct screen side in visual_desc — e.g. "EAST WALL (left when facing entrance)" and "WEST WALL (right when facing entrance)". Never reuse From-Entrance left/right phrasing here.

## Important for vehicles:
- For every vehicle generate THREE SEPARATE ref entries:
  1. `{Vehicle-Name}-Exterior` — full exterior, three-quarter front angle, studio lighting.
  2. `{Vehicle-Name}-Interior-From-Entrance` — interior looking IN from driver/main door. Dashboard, seats, controls, cabin details.
     Set `style_reference` to `{Vehicle-Name}-Exterior`.
  3. `{Vehicle-Name}-Interior-To-Entrance` — interior looking TOWARD the entrance from the back seat.
     Rear cabin, headrests, door panels, details not visible from entrance side.
     Set `style_reference` to `{Vehicle-Name}-Interior-From-Entrance`.

## Important for outdoor locations:

Open-air locations (streets, parks, courtyards, alleyways, rooftops, riverbanks, etc.) use type=Outdoor.

### Outdoor visual_desc — use compass layout (MANDATORY format):
Assign the primary camera direction first, then describe all four compass directions consistently.
Example format:
```
LOCATION TYPE: narrow cobblestone alley, ~20 m long, 4 m wide.
PRIMARY DIRECTION (camera faces): North — toward the archway at the far end.
NORTH (background / far end): stone archway spanning full width, dim street lamp above, worn brick wall on both sides converging to arch.
SOUTH (foreground / behind viewer): alley entrance, open street, daylight spill.
EAST (right when facing North): continuous brick wall, moss patches, one iron drainpipe at mid-alley.
WEST (left when facing North): row of three wooden doors, one slightly ajar, small flower pot at base of middle door.
GROUND: uneven cobblestones, shallow puddle near EAST wall at mid-point.
SKY/ATMOSPHERE: overcast, cool diffuse light, slight fog.
KEY LANDMARKS: iron drainpipe (EAST, mid-alley), three wooden doors (WEST, mid-alley), stone archway (far North).
```
This format MUST be used for every Outdoor ref so that per-view renders and anchor generation know exactly what is visible from each angle.

- For every outdoor location generate TWO SEPARATE ref entries (two distinct names, two distinct JSON objects):
  1. `{Outdoor-Name}-View-Primary` — wide establishing shot facing the PRIMARY DIRECTION. Shows background/far-end landmarks, left and right sides, foreground ground. Single portrait image, empty location, no people.
  2. `{Outdoor-Name}-View-Opposite` — wide establishing shot facing the OPPOSITE direction (180-degree turn). CRITICAL: left and right are SWAPPED — what was on the LEFT in View-Primary is on the RIGHT here. Shows the foreground-side features (formerly behind the camera). Single portrait image, empty location, no people.
     Set `style_reference` to `{Outdoor-Name}-View-Primary` so materials and atmosphere are consistent.

## Visual Description
- Must be verbose, precise, and contain specific features so that AI model can efficiently implement without hallucinations

---
