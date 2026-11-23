# Character Casting Template

## Task
Analyze text for KEY characters/locations/objects/rooms/vehicles and generate photorealistic character references.
Those references will be used for vertical cinematic shots and AI video animation.
IMPORTANT: Think as **Master Cinematographer** for 9:16 portrait format — faces dominate, close-ups are primary.

## Character Description Format
For each NEW character:
- **Name**: Full name
- **Visual Description**: Photorealistic actor description with specific physical features, ethnicity, age, clothing textures
  - Face: Facial structure, eyes, hair color/style, ethnicity
  - Build: Height in cm (a number, e.g. "~178 cm" — it sets relative scale between characters in shared frames), build, posture
  - Clothing: Contemporary attire with specific fabric textures
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
      a secure building, a keycard or lanyard — when the era has them and the story does not say the
      character carries nothing.
    State WHERE items are carried and WHAT the carrier looks like (e.g. "tan leather bifold in left
    breast pocket", "black structured tote hanging from right shoulder").
    Visual Description draws only what shows: a bag, a holster, a watch, a pocket's bulge. Pocket contents
    and props used once (a photo, a banknote, a knife taken out in one scene) are not drawn — they get
    their own Object refs.
- **Behavioral Signature**: How this character behaves under pressure — derive from their decisions, speech patterns, and reactions in the source text.
  - Default power move: their go-to strategy to assert control or dominance
  - Deflection strategy: how they redirect or absorb pressure when threatened
  - Involuntary tells WITH their triggers: the physical or verbal tic that betrays their true state (lying, fear, want) — a tic is usable acting data only when its trigger is named ("touches left cuff link **whenever numbers are questioned**")
  - Mask + crack clause, closing the field: "However, when <X> — the visible change" — the crack that shows through the held mask
  - Observable body behavior only (no inner monologue); together with Physical Vocabulary keep within 60 words
  E.g. "Under pressure: retreats to bureaucratic procedure — cites rules, demands paperwork. Power move: silence and stillness while the other person fills the void. Tell: touches left cuff link whenever numbers are questioned. However, when cornered by rank — the bureaucratic patience cracks into a clipped, faster cadence and he grips the desk edge."
- **Physical Vocabulary**: How this character habitually occupies space — derive from their role, psychology, and body language in the source.
  - Default posture: how they hold themselves at rest vs. under pressure
  - Space use: how they move through a room (invade / retreat / orbit / anchor to one spot)
  - Named gait: ONE recognizable walk with its rhythm/speed — e.g. "officer's unhurried parade step, heel strikes audible", "priest-quick shuffle"
  - Softening target: what the gait's sharpness gives way to when the character relaxes — e.g. "at home the parade step melts into a flat heel-first walk"
  - Signature gestures: 1–2 recurring physical behaviors that define this character on screen
  - Observable body behavior only; together with Behavioral Signature keep within 60 words
  E.g. "Never sits during confrontation — paces or leans against a surface. Closing distance deliberately by 20cm when he wants something. Named gait: officer's unhurried parade step, heel strikes audible. Softening target: at home the parade step melts into a flat heel-first walk. Hands always visible and deliberately still (controlled restraint)."
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
- **Lighting**: Soft studio lighting with faint warm side-light simulating interior ambiance
- **Background**: Solid deep-charcoal backdrop
- **Quality**: 8K resolution, sharp focus, photorealistic skin texture

## Important for rooms:

### Room visual_desc — use entrance-relative wall layout (MANDATORY format):
Write the room description as a wall-by-wall inventory named relative to the entrance: ENTRANCE WALL, FAR WALL, LEFT WALL, RIGHT WALL (left/right as seen when entering).
FORBIDDEN for rooms: compass directions (North/South/East/West) — every downstream pass uses entrance-relative names only.
Example format:
```
ROOM SIZE: medium office, ~5×4 m, 2.7 m ceiling, parquet floor, white plaster walls.
ENTRANCE WALL: solid wood door center, narrow built-in bookshelf to the left of door, coat hook to the right.
FAR WALL (opposite the entrance): single casement window with roll blinds, centered, city view.
RIGHT WALL (right when entering): L-shaped work desk with laptop, monitor, desk lamp, filing cabinet underneath.
LEFT WALL (left when entering): two visitor chairs in dark leather, small side table between them, framed art above.
CENTER: no obstructions, open floor space.
CEILING/FLOOR: recessed LED strip lighting, warm tone; dark oak parquet.
```
This format MUST be used for every Room ref so that per-view renders know exactly what is visible from each angle.

- For every room generate TWO SEPARATE ref entries (two distinct names, two distinct JSON objects):
  1. `{Room-Name}-View-From-Entrance` — wide shot from the entrance doorway looking toward the opposite wall. Shows: opposite wall, left wall, right wall, center. Single portrait image, empty room.
  2. `{Room-Name}-View-To-Entrance` — wide shot from the opposite end of the room looking BACK toward the entrance wall and door. Shows: entrance wall with door, and the wall features behind the viewer's back (rear furniture, windows, decor only visible from this angle). Single portrait image, empty room.
     Set `style_reference` to `{Room-Name}-View-From-Entrance` so furniture materials and style are consistent.
     CRITICAL — LEFT/RIGHT ARE SWAPPED in this view (180° turn from entrance): what was on the LEFT WALL (left when entering) is now on the RIGHT side of the image; what was on the RIGHT WALL (right when entering) is now on the LEFT. Label each wall with its screen side in this view — e.g. "RIGHT WALL (image-left when facing entrance)" and "LEFT WALL (image-right when facing entrance)". Never reuse From-Entrance left/right phrasing here.

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

### Outdoor visual_desc — one camera station, four headings (MANDATORY format):
Every outdoor location is shot like a street-view panorama: the camera stands at ONE spot, the STATION (the origin),
and turns in place. AHEAD (+Y) is View-Primary, RIGHT (+X) is View-Ortho-Primary, BEHIND (−Y) is View-Opposite,
LEFT (−X) is View-Ortho-Opposite. Describe what each heading sees, all relative to the PRIMARY DIRECTION.
FORBIDDEN: compass directions (North/South/East/West) — every downstream pass uses these relative names only.
- Streets: the station is in the roadway, where a passing or parked car would be; AHEAD runs ALONG the street, and the
  story's main facade (the café, the house the scene plays at) is on the RIGHT, so View-Ortho-Primary faces it head-on.
  Describe the full cross-section: near facade, its sidewalk, the roadway and lanes, the far sidewalk, the far facades.
- Crossroads: the station is the intersection centre; AHEAD and BEHIND follow one street, RIGHT and LEFT the cross street.
- Open ground (beach, field, forest, cemetery): the station is where the action happens; AHEAD faces the key landmark.
Example format:
```
LOCATION TYPE: two-lane city street with shopfronts, ~40 m stretch, ~20 m facade to facade.
STATION: in the near lane, beside the café entrance.
AHEAD (+Y, View-Primary, along the street): roadway receding, café awning running along the RIGHT edge, far-side shopfronts along the LEFT, traffic light at the end of the block.
RIGHT (+X, View-Ortho-Primary, facing the near facade head-on): curb, 4 m sidewalk with two café tables, glass café frontage under a green awning, brick apartment floors above.
BEHIND (−Y, View-Opposite): roadway receding the other way; café facade now along the LEFT edge, far side along the RIGHT, corner burger stand at the block end.
LEFT (−X, View-Ortho-Opposite, across the street): far lane, curb, sidewalk with a newsstand, row of five-storey facades.
GROUND: asphalt with lane markings, concrete sidewalks.
SKY/ATMOSPHERE: late afternoon, warm low sun, long shadows.
KEY LANDMARKS: café entrance (RIGHT), newsstand (LEFT), traffic light (AHEAD), burger stand (BEHIND).
```
This format MUST be used for every Outdoor ref so that per-view renders and anchor generation know exactly what is visible from each heading.

- For every outdoor location generate FOUR SEPARATE ref entries (four distinct names, four distinct JSON objects),
  all empty (no people), single image each; entries 2–4 set `style_reference` to `{Outdoor-Name}-View-Primary`:
  1. `{Outdoor-Name}-View-Primary` — from the station, facing AHEAD (the PRIMARY DIRECTION).
  2. `{Outdoor-Name}-View-Opposite` — from the station, turned 180°. CRITICAL: left and right are SWAPPED — what was on the
     LEFT in View-Primary is on the RIGHT here.
  3. `{Outdoor-Name}-View-Ortho-Primary` — from the station, turned 90° RIGHT: what lined View-Primary's RIGHT side is
     straight ahead, head-on; View-Primary's distance runs off to the image-LEFT.
  4. `{Outdoor-Name}-View-Ortho-Opposite` — from the station, turned 90° LEFT: what lined View-Primary's LEFT side is
     straight ahead, head-on; View-Primary's distance runs off to the image-RIGHT.

## Visual Description
- Must be verbose, precise, and contain specific features so that AI model can implement without hallucinations

---
