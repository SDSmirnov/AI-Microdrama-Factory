# Scene 001 — Mansion Exterior

**Setup:** INITIAL SPATIAL DISPOSITION:
The Groom and Bride stand on the top step at the main-doors of the mansion, facing the courtyard. The Reporter stands in the courtyard-center, facing them and the camera. 

## Character Reference Descriptions

_Use these to maintain visual consistency when prompting the model:_

### Groom
Handsome man, late 20s, Northern European, dark brown hair, blue eyes, wearing stylish black-rimmed glasses and a classic black tuxedo with a bow tie. Carries a smartphone in his inner jacket pocket and wears a slim steel watch.

### Wheelchair
A modern, empty manual wheelchair with a lightweight black carbon-fiber frame and black nylon seating.

### Bride
Elegant woman, mid-20s, Slavic features, platinum blonde hair in an updo, wearing a white silk wedding dress and a white fur wrap.

### Reporter
Energetic woman, late 40s, Eastern European, brown hair, wearing rectangular glasses, a grey wool coat, and a 'CN NEWS' logo scarf.

### Elderly-Man
Elderly man, late 70s, Caucasian, with thinning grey hair and a proud smile, wearing a dark formal overcoat and seated in a wheelchair.

### CN-NEWS-Microphone
A black broadcast microphone with a square, blue foam windscreen featuring the white 'CN NEWS' logo.

### Wedding-Bouquet
An elegant wedding bouquet of white peonies and cream roses, with stems wrapped in white satin ribbon.

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


Location: Mansion Exterior
Setup: INITIAL SPATIAL DISPOSITION:
The Groom and Bride stand on the top step at the main-doors of the mansion, facing the courtyard. The Reporter stands in the courtyard-center, facing them and the camera. 
Scene camera master: 50mm prime lens bias, primarily eye-level, capturing the scene with a cinematic and slightly intimate feel despite the grand setting.
Scene lighting master: Bright, high-contrast midday sun acts as the key light, casting sharp, well-defined shadows. The white wedding dress and reflective surfaces create brilliant highlights, with minimal fill light, emphasizing the starkness between light and shadow.
CONSISTENCY RULE: All instances of the same character across all panels must have IDENTICAL face, hair, clothing, body proportions.
NO CAPTIONS!
**CRITICAL FORMAT:** Single image containing 9 panels (each 9:16) arranged in a 3×3 grid.
Each cell is a VERTICAL frame designed for mobile viewing.
SAFE ZONE per panel: compose key subjects (faces, hands, focal action) within the middle 65% of panel height.
Top 15% and bottom 20% of each panel must remain visually uncluttered (background only — sky, wall, floor).
Faces and close-ups are the primary dramatic instrument — this is vertical microdrama, not widescreen cinema.
Shallow depth of field. Subjects sharp, backgrounds contextual only.

IMPORTANT: Generate SINGLE 2K 9:16 image with 9 panels in 3×3 grid layout.

Panel 1: [COLD_OPEN] [confrontation]
  Visual: Medium shot, camera at courtyard-center. The Reporter is at frame-center in the foreground, chest directed toward the mansion, holding a microphone up as if mid-sentence. In the background, the Groom and Bride stand at frame-center on the top step of the mansion's grand staircase, smiling for the cameras. He is in a black tuxedo, his arm around her waist. She is in a luxurious white wedding dress, her hand on his chest. The grand mansion facade with its massive columns and doors looms behind them under a bright, clear sky.
  Camera: MS, eye-level, 50mm lens. The scene is brightly lit by the midday sun, creating harsh shadows and brilliant highlights. The focus is on the Reporter in the foreground, with the couple in the background slightly softer.
  Dialogue: Репортер (female): Пресса уже окрестила это «свадьбой века»!

Panel 2: [VERBAL_HOOK] [tension]
  Visual: Wide shot, camera at courtyard-center. The Groom and Bride are at frame-center in the mid-ground, standing on the top step of the stairs, turning to look at each other. To their frame-left, the Elderly-Man is visible at the base of the stairs in his wheelchair. In the foreground, the Reporter stands at frame-center, slightly lowering her microphone. The entire scene is filled with an unseen crowd, their presence implied by the energy and a shower of golden confetti beginning to fall. The mansion facade provides a grand backdrop under the bright sun.
  Camera: WS, eye-level, 50mm lens. Bright, direct sunlight illuminates the entire courtyard, creating high contrast. Deep focus keeps the couple, the Elderly-Man, and the Reporter all relatively sharp.
  Dialogue: Толпа (male/female): Горько! Горько! Горько!

Panel 3: [ESCALATION] [desire]
  Visual: Close-up shot, camera at entrance-threshold, looking up slightly at the couple on the top step. The Groom at frame-left and the Bride at frame-right are facing each other, their faces just inches apart, eyes locked. He is in his black tuxedo, she in her white dress. His hand is visible on the small of her back. Her hand rests on his chest. Golden confetti is frozen in the air around them, catching the bright sunlight. The background is a soft-focus blur of the mansion's ornate doorway.
  Camera: CU, low-angle, 50mm lens. The key light is the high sun, creating strong highlights and shadows on their faces. The shallow depth of field isolates them completely from the background.

Panel 4: [EMOTIONAL_CAPTURE] [triumph]
  Visual: Medium shot, camera at entrance-threshold. The Groom at frame-left pulls the Bride at frame-right into a deep kiss. His arm is wrapped securely around her, asserting possession. Her body is pressed against his, one hand on his shoulder, the other holding her bouquet. They are on the top step of the mansion stairs, surrounded by a heavy shower of golden confetti that glitters in the bright sunlight. The background is the out-of-focus grand entrance of the mansion, creating a sense of a fairy-tale moment.
  Camera: MS, eye-level, 50mm lens. Bright, direct sunlight from above creates a dramatic rim light. The confetti creates a dynamic, glittering texture across the frame. Shallow depth of field keeps the focus entirely on the couple.

Panel 5: [CRYSTALLIZATION] [revelation]
  Visual: Close-up shot on the Elderly-Man, positioned near the base of the mansion stairs. He is seated in his modern black wheelchair, wearing a dark formal overcoat. His face, etched with wrinkles, is turned toward the off-screen couple, a gentle, proud smile on his lips. His deep-set eyes are glistening with unshed tears of joy. The background is a soft-focus blur of the sunlit courtyard and the cheering crowd. His hands are raised, just about to come together in applause.
  Camera: CU, eye-level, 50mm lens. The bright sun acts as a key light, highlighting the texture of his aged skin and the moisture in his eyes. Shallow depth of field isolates his emotional reaction.

Panel 6: [CONFRONTATION] [triumph]
  Visual: Medium shot, camera at entrance-threshold. The Groom and Bride have just broken their kiss and are laughing, looking into each other's eyes on the top step of the mansion stairs. He is in his black tuxedo, she in her white dress. His hands are positioned on her waist, ready to lift. She holds her wedding bouquet, her arms ready to go around his neck. The air is still thick with the last of the falling golden confetti, sparkling in the bright sunlight against the backdrop of the mansion's grand doors.
  Camera: MS, eye-level, 50mm lens. Bright, direct sunlight creates a halo effect around them. The motion of the lift is frozen, capturing a moment of dynamic energy.

Panel 7: [PIVOT] [confrontation]
  Visual: Extreme close-up on the Groom's face. He is holding the Bride (who is just out of the lower frame) and has turned his head slightly toward the camera. His expression is one of pure, unadulterated triumph, a confident and charming smile playing on his lips. His blue eyes, behind stylish black-rimmed glasses, are sparkling with victory. The bright sunlight catches the side of his face. The background is a complete blur of the sunlit courtyard.
  Camera: ECU, eye-level, 50mm lens. Harsh key light from the sun highlights the details of his expression and the glint in his glasses. Extremely shallow depth of field obliterates the background.

Panel 8: [TWIST] [dread]
  Visual: Medium shot from the courtyard-center. The Groom, still holding the Bride in his arms, is pivoting on the top step of the stairs. His back is beginning to turn to the camera as he prepares to enter the mansion. The massive, ornate wooden doors behind him are open, revealing the dark, opulent hall within. The Bride, cradled in his arms, looks over his shoulder. In the foreground, the Reporter and the Elderly-Man in his wheelchair are visible as blurred figures, watching the couple's departure.
  Camera: MS, eye-level, 50mm lens. The lighting is defined by extreme contrast between the sunlit exterior and the dark interior. The camera's focus follows the couple as they move away.

Panel 9: [TENSION_PEAK] [dread]
  Visual: Extreme close-up on the massive, dark wood double doors of the mansion, viewed from the exterior. The two doors are swinging shut, with only a narrow vertical sliver of bright daylight visible between them. The ornate brass handles are just about to meet. The polished wood reflects the bright sunlight of the courtyard. The texture of the heavy wood grain is visible and imposing. The focus is sharp on the closing gap.
  Camera: ECU, eye-level, 50mm lens. The lighting is the bright, direct sun of the courtyard, creating harsh reflections on the polished wood and brass. The focus is tack-sharp on the seam where the doors meet.

```
