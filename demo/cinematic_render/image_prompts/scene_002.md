# Scene 002 — Mansion Hall

**Setup:** EPISODE ENTRY STATE:
  Continues from: The massive doors have just slammed shut, plunging the scene into silence.
  P1 opens on: The Groom, having just been enveloped in silence, begins to gently lowe

## Character Reference Descriptions

_Use these to maintain visual consistency when prompting the model:_

### Groom
Handsome man, late 20s, Northern European, dark brown hair, blue eyes, wearing stylish black-rimmed glasses and a classic black tuxedo with a bow tie. Carries a smartphone in his inner jacket pocket and wears a slim steel watch.

### Wedding-Bouquet
An elegant wedding bouquet of white peonies and cream roses, with stems wrapped in white satin ribbon.

### Bride
Elegant woman, mid-20s, Slavic features, platinum blonde hair in an updo, wearing a white silk wedding dress and a white fur wrap.

---

## Image Generation Prompt

```
# Visual Style Template

## Format Specification
FORMAT: Single 2K portrait grid (9 panel-pairs), 9:16 vertical orientation for DramaBox/ReelShort paywall microdrama
RESOLUTION: 2K
ASPECT_RATIO: 9:16

## Rendering Style
STYLE: Photorealistic Cinematic — contemporary drama
CAMERA: Sony Venice 2 / Arri Alexa Mini LF (9:16 portrait crop, vertical framing)
LENS: 35mm–85mm prime lenses, shallow depth of field, soft anamorphic oval bokeh on background elements
POST: Subtle 35mm digital film grain, deep shadow rolloff, rich skin-tone warmth, cinema-grade color grading

## Atmosphere
ATMOSPHERE: High-stakes emotional tension, opulent romance, psychological drama, stark contrast between public facade and private turmoil.
LIGHTING: High-key, soft lighting for public wedding scenes, contrasted with low-key, hard-edged chiaroscuro lighting for private confrontations. Motivated by practical sources like chandeliers, window light, and desk lamps to create dramatic shadows and highlight emotional states.
COLOR: A bifurcated color palette. Public scenes feature warm, golden tones, champagne whites, and soft pastels to emphasize opulence and romance. Private, tense scenes shift to cooler, desaturated blues and steely grays, with deep, crushed blacks to heighten the sense of isolation and conflict. Skin tones remain warm and natural across all scenes to ground the drama.

## Technical
RENDER: Photorealistic 2K, sharp focus on faces and detail objects, shallow DOF blurs interiors and backgrounds
GRAIN: Subtle 35mm digital grain — adds filmic texture without visible noise

# Image Generation Template

## Grid Layout
Render a SINGLE 2K 9:16 image with exactly 9 equal-sized panels in 3 columns × 3 rows. Each panel is 9:16 AR. Panels left-to-right, top-to-bottom: Panel 1 = top-left, Panel 9 = bottom-right.

## Composition Rules
1. **Emphasize Verticality**: Use the 9:16 aspect ratio to your advantage. Employ leading lines, subject framing, and negative space to guide the viewer's eye up and down the frame.
2. **Cinematic Shot Language**: Use the specified shot type (establishing, medium, close-up, extreme close-up) to build drama. The framing should feel like a scene cut by a professional editor.
3. **Rule of Thirds & Headroom**: Strictly adhere to the rule of thirds for subject placement. Pay close attention to cinematic headroom and lead room to create a balanced, professional composition.

## Visual Consistency
- **Lighting**: Lighting should be motivated, naturalistic, and moody to enhance the drama. Evolves only if dictated by narrative action (e.g., a character walks past a window).
- **Camera**: The "camera" should feel like a single prime lens (e.g., 35mm or 50mm). While angles and framing will change per shot, focal length and depth-of-field characteristics must remain consistent.
- **Subject Motion**: Subject positions must be logical and physically continuous. Avoid jarring jumps or "teleporting" subjects.

## Special Instructions
Render with photorealistic quality. Apply professional, subtle color grading to establish a specific mood. Incorporate a shallow depth of field (bokeh) to isolate subjects and create a cinematic feel. Add a light layer of realistic film grain for texture.

## Spatial Language Protocol
Two namespaces. No bare "left"/"right" ever.

**FRAME-SPACE** (viewer perspective — position, movement, gaze as seen on screen):
- Always prefix with "frame-": `frame-left`, `frame-right`, `upper-frame-left`, `frame-center`
- "moving toward frame-left" / "moving toward frame-right" — lateral tracking
- Character depth movement uses world-space destinations — "moves toward [person/door/window/furniture]", "retreats to the entrance", "crosses to the sofa" — NEVER "toward camera" or "away from camera". Camera tracking behavior goes in lights_and_camera.
- "eyes track toward frame-right" / "hand enters from frame-left" / "glances toward frame-left"
- NEVER bare "left" or "right" for spatial positions — "enters from the right" is FORBIDDEN

**ANATOMY** (body parts — always possessive, never a screen direction):
- "his left hand", "her right shoulder", "[name]'s right eye"
- Anatomical left/right is opposite to frame direction for a front-facing character
- When the frame position of a body part matters: "his right hand (frame-left) reaches forward"

NEVER rely on positional shorthand ("from end A to end B") — always state the camera-relative vector explicitly in both visual_start and motion_prompt[0s].

## Extreme Close-Up (ECU) Protocol
When the panel description calls for ECU, extreme close-up, or a tight shot on eyes/face/hands:
- Maximum facial resolution: visible skin pores and natural skin texture — photorealistic, NOT plastic or AI-smoothed.
- Micro-muscle detail: slight jaw tension, lid-weight over pupils, shadow under the lower lip, faint vein at the temple.
- Eyes: highly detailed irises, one sharp catchlight visible in the pupil per eye — the "soul light". Vibrant gaze, no dead-eye flatness.
- Hands: visible tendons, knuckle lines, natural skin creasing when gripped.

## Cinematic Beauty Standard (Foreground Characters)
Apply to all characters visible at CU or closer:
- **Skin**: dewy, hydrated glow with soft-focus natural pores — the "camera-ready" look without losing realism. No waxy or plastic finish.
- **Lighting**: volumetric rim light (golden-hour warmth OR cool blue edge) separates the subject from background. Cinematic highlights on cheekbones.
- **Eyes**: sharp catchlight, detailed iris texture, vibrant and alert — never glassy.
- **Color grade**: location-keyed signature below. Blacks are always true black; highlights always retain warmth. High contrast ratio. Premium studio-production quality.

## Location Color Signatures (use the matching signature per scene location)

Visual variety across a multi-episode series is not optional — monotone color grade kills mid-video retention. Each location type has its own color key. The contrast between signatures is what makes location changes VISIBLE IN THE EDIT without any title card.

**CORPORATE / POWER SPACES** (offices, boardrooms, banks, lobbies):
- Dominant: cool silver-blue + deep black
- Shadows: dark navy and charcoal
- Highlights: cold white from window or monitor glow
- Accent: single warm practical (coffee cup steam, desk lamp amber) — isolated, not dominant
- Emotional register: isolation, control, performance

**PRIVATE / OBSESSION SPACES** (character's car, empty apartment at night, night streets):
- Dominant: deep teal shadows with selective amber practicals (phone screen, streetlight cone, dashboard glow)
- Shadows: near-black with blue-green undertone
- Highlights: one sharp warm source per frame — everything else cold
- No fill — let the darkness take the rest
- Emotional register: loneliness, fixation, grief

**INTIMATE / CONFLICT SPACES** (cafes, apartments, restaurants, hotel rooms):
- Dominant: warm amber-gold from practical sources (candles, Edison bulbs, diffuse window light)
- Shadows: deep brown-black, never cold
- Highlights: creamy skin tones, soft catchlights
- Accent: cool shadow-side contrast to preserve dimension
- Emotional register: vulnerability, confrontation, desire

**EXTERIOR / WEATHER** (city streets in rain, courtyards, parks):
- Dominant: desaturated cool grey-blue
- Wet surfaces: reflective highlights from streetlights and headlights
- Colour accent: single neon or warm window glow in background — one focal point of warmth in a cold world
- Characters: elevated warm skin tone against cool environment — they stand out
- Emotional register: exposure, isolation, transition

## IMPORTANT
- **NO TEXT CAPTIONS/SUBTITLES**


# World & Setting Reference

## Genre & Tone
- **Genre**: Drama, Romance
- **Atmosphere**: Dramatic, Tense, Romantic
- **Visual Tone**: Dramatic, Tense, Romantic

## Setting
{"period": "Contemporary", "location": "A luxurious mansion during a high-society wedding", "world_type": "Realistic"}

## Protagonist
- **Name**: The Groom
- **Narrator Style**: Third-person omniscient
- **Visual Description**: A young man, heir to a business empire, wearing a classic black tuxedo. He appears charming and in love in public, but is left confused and dejected by the bride's sudden coldness in private, revealing the marriage is a sham.

## Composition Style
cinematic_fpov

## Special Visual Elements
  - Marriage of convenience
  - Corporate dynasty

## World-Specific Visual Details
  - High-society opulence
  - Grand mansion architecture
  - Contrast between bright public celebration and stark private tension


Location: Mansion Hall
Setup: EPISODE ENTRY STATE:
  Continues from: The massive doors have just slammed shut, plunging the scene into silence.
  P1 opens on: The Groom, having just been enveloped in silence, begins to gently lowe
Scene camera master: 50mm prime lens bias, primarily eye-level, with specific high/low angles for dramatic emphasis; captures the intimate and oppressive scale of the mansion hall.
Scene lighting master: Key light is the cool, diffuse, multi-colored light from a massive stained-glass skylight high above, creating long, soft shadows. Fill is minimal, relying on bounce from the polished marble floor. The overall mood is dim, somber, and cold, despite the opulent surroundings.
CONSISTENCY RULE: All instances of the same character across all panels must have IDENTICAL face, hair, clothing, body proportions.
NO CAPTIONS!
**CRITICAL FORMAT:** Single image containing 9 panels (each 9:16) arranged in a 3×3 grid.
Each cell is a VERTICAL frame designed for mobile viewing.
SAFE ZONE per panel: compose key subjects (faces, hands, focal action) within the middle 65% of panel height.
Top 15% and bottom 20% of each panel must remain visually uncluttered (background only — sky, wall, floor).
Faces and close-ups are the primary dramatic instrument — this is vertical microdrama, not widescreen cinema.
Shallow depth of field. Subjects sharp, backgrounds contextual only.

IMPORTANT: Generate SINGLE 2K 9:16 image with 9 panels in 3×3 grid layout.

Panel 1: [COLD_OPEN/STATUS_REVERSAL] [tension]
  Visual: Medium shot, camera at the entrance-area of a vast, opulent mansion hall. The Groom is at frame-center foreground, holding the Bride in a classic bridal carry. He wears a perfectly tailored black tuxedo and his face, seen in three-quarter profile, is filled with adoration as he gazes down at her. The Bride is cradled in his arms, her white silk dress and fur wrap a stark contrast to his dark suit. Behind them, the massive, dark wood entrance doors are closed, and the cavernous hall with its polished checkerboard marble floor stretches into the background toward a grand staircase. The scene is lit by cool, diffuse light from a high, unseen stained-glass skylight.
  Camera: 50mm lens, eye-level medium shot. The lighting is dim and cool, dominated by the diffuse light from the stained-glass skylight above, creating a somber, cathedral-like atmosphere. Shallow depth of field keeps the couple sharp against the slightly soft-focused grand staircase in the deep background.

Panel 2: [VERBAL_HOOK] [confrontation]
  Visual: Close-up on the Bride's face, filling the frame. She is looking slightly upward toward the off-screen Groom, a faint, polite smile on her lips. Her platinum blonde hair is perfectly styled, and her ice-blue eyes seem neutral. She wears a luxurious white fur wrap over her dress, and holds a white peony bouquet just visible at the bottom of the frame. The lighting is cool and diffuse, coming from above, highlighting her high cheekbones. The background is the blurred, dark wood paneling of the mansion hall. The Groom is off-frame.
  Camera: 50mm lens, eye-level close-up. Cool, diffuse top-light from the skylight emphasizes her facial structure, creating subtle shadows under her cheekbones and jaw. Extremely shallow depth of field completely blurs the background, isolating her expression.
  Dialogue: Невеста (ж): Шоу окончено.

Panel 3: [ESCALATION] [shock]
  Visual: Close-up on the Groom's face, filling the frame. He is looking slightly downward toward the off-screen Bride, his soft, loving smile just beginning to falter at the edges. Confusion flickers in his blue eyes behind his thin-rimmed glasses. He wears a classic black tuxedo and bow tie. The cool, diffuse light from the skylight above casts a soft glow on his features. The background is the blurred dark wood of the hall's entrance wall. The Bride is off-frame.
  Camera: 50mm lens, eye-level close-up. The cool, diffuse top-light catches the rim of his glasses and highlights the tension in his brow. Extremely shallow depth of field isolates his bewildered expression.

Panel 4: [ESCALATION] [confrontation]
  Visual: Medium shot from the entrance-area. The Bride is at frame-center, standing stiffly with a cold expression, her white dress stark against the dark hall. The Groom stands opposite her, his body language shifting from relaxed intimacy to a frozen, confused stillness. There is only a foot of polished marble floor between them. The grand staircase is visible in the distant background. The hall is dim, lit only by the cool, diffuse light from a high skylight, creating a sense of isolation.
  Camera: 50mm lens, eye-level medium shot. The focus is held on the space between them, keeping both figures slightly soft to emphasize the growing distance. The cool, dim light from the skylight makes the marble floor look like a cold, dark void.

Panel 5: [CRYSTALLIZATION] [rage]
  Visual: Extreme close-up on the Bride's face, angled slightly up at her. Her expression is a mask of cold contempt. Her ice-blue eyes are narrowed, fixed on the off-screen Groom with undisguised disgust. Her lips are pressed into a thin, hard line. The cool, diffuse light from the skylight carves sharp shadows under her cheekbones, making her look severe and unforgiving. A piece of her elegant platinum blonde updo is visible. The background is completely out of focus. The Groom is off-frame.
  Camera: 50mm lens, slight low-angle extreme close-up. The cool top-light creates a harsh, dramatic effect on her face, emphasizing her power. The depth of field is razor-thin, focusing solely on her eyes.
  Dialogue: Невеста (ж): Не смей ко мне приближаться.

Panel 6: [CONFRONTATION] [shock]
  Visual: Medium shot from the entrance-area. The Bride stands at frame-center, her body rigid with anger. Her right arm is raised, her hand gripping the white wedding bouquet tightly, poised to throw it. Her face is a mask of disgust, directed at the Groom. The Groom is in the foreground, his body language frozen, watching her with a stunned expression. The polished marble floor separates them. The vast, dim hall with its distant staircase forms the cold, empty background, lit by the skylight.
  Camera: 50mm lens, eye-level medium shot. Deep focus to keep both the Groom's reaction in the foreground and the Bride's action in the mid-ground sharp. The cool, dim light from the skylight highlights the white bouquet against the dark floor.

Panel 7: [PIVOT] [revelation]
  Visual: Extreme close-up on the Groom's face. His expression is caught in the middle of a flinch, eyes wide behind his glasses, mouth slightly open in shock from the bouquet hitting the floor off-screen. The muscles in his jaw are tight. The cool, diffuse light from the skylight reflects off his glasses, obscuring his eyes for a moment. The background is a complete blur of the dark hall. The Bride is off-frame.
  Camera: 50mm lens, eye-level extreme close-up. The lighting is cool and soft, but the proximity to the face makes every micro-expression stark and clear. Razor-thin depth of field isolates his face from the world.

Panel 8: [TWIST] [grief]
  Visual: Wide shot from the entrance-area, looking deep into the mansion hall. The Groom is a small, solitary figure in his black tuxedo, standing in the foreground near the frame-center, looking lost. The discarded white bouquet is a small patch of light on the dark marble floor near him. In the deep mid-ground, the Bride is walking away, her back to the camera, a determined figure in white ascending the grand staircase at the far end of the hall. The sheer scale of the hall, with its high ceiling and checkerboard floor, dwarfs them both, emphasizing their isolation.
  Camera: 35mm lens, eye-level wide shot. The deep focus keeps the entire hall sharp, from the Groom in the foreground to the Bride on the distant stairs. The cool, dim light from the skylight creates a vast, lonely atmosphere, with the marble floor reflecting the emptiness.

Panel 9: [TENSION_PEAK] [dread]
  Visual: Extreme close-up, high-angle shot looking down. The frame is dominated by the discarded wedding bouquet lying on the black and white checkerboard marble floor. The white peonies and cream roses are slightly bruised from the impact. The tip of the Groom's impeccably polished black dress shoe is visible at the upper edge of the frame, paused inches away from the flowers. The cool, diffuse light from the skylight above creates soft shadows around the bouquet, making it look like a funeral offering. The Groom's face is out of frame.
  Camera: 50mm lens, high-angle extreme close-up. The shot is focused sharply on the bouquet, with the Groom's shoe at the edge of the shallow depth of field. The cool top-light from the skylight illuminates the scene with a melancholic, sterile quality.

```
