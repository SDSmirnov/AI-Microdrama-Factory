<!-- replace: ## Task -->
## Task
Analyze text for KEY characters/locations/objects/rooms/vehicles and generate photorealistic character references.
Those references will be used for vertical microdrama shots and AI video animation.
IMPORTANT: Think as **Master Cinematographer** for 9:16 portrait format — faces dominate, close-ups are primary.

<!-- replace: ## Character Description Format -->
## Character Description Format
For each NEW character:
- **Name**: Full name
- **Visual Description**: Photorealistic actor description with specific physical features, ethnicity, age, clothing textures
  - Face: Facial structure, eyes, hair color/style, ethnicity
  - Build: Height in cm (a number, e.g. "~178 cm" — it sets relative scale between characters in shared frames), build, posture
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

<!-- replace: ## Reference Generation -->
## Reference Generation
- **Shot Type**: Close-up portrait (3:4 aspect ratio)
- **Expression**: Neutral, composed — with slight underlying tension
- **Lighting**: Soft studio lighting with faint warm side-light simulating luxury interior ambiance
- **Background**: Solid deep-charcoal backdrop
- **Quality**: 8K resolution, sharp focus, photorealistic skin texture
