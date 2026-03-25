Scene file to refine: $ARGUMENTS

Steps:
1. Read the scene JSON file at `$ARGUMENTS`
2. Extract the episode number from the filename (e.g., `animation_episode_scenes_003.json` → episode 3)
3. Read `cinematic_render/animation_episodes.json` and extract that episode for context
4. If episode > 1, also extract the previous episode for continuity context
5. Read `cinematic_render/animation_metadata.json` if it exists — find the scene that immediately precedes the first scene in this file (by `scene_id`) and note its last panel's `visual_end` as the **cross-scene terminal frame** for Rule 4.
6. Check if `custom_prompts/scenery.md` exists — use it; otherwise use `lib/prompting/vertical_9_16_microdrama/scenery.md`. Read it.
7. Check if `custom_prompts/setting.md` exists — use it; otherwise use `prompts/setting.md` (legacy fallback). Read it.
8. For each name in any panel's `references` array, try to read `ref_thriller/{name_lowercased_underscored}.json` and extract `video_visual_desc`
9. Refine every scene following all instructions below.
10. Write the result to the same path with `_refined` inserted before `.json` (e.g., `animation_episode_scenes_003_refined.json`)
11. **Update `cinematic_render/animation_metadata.json` (single source of truth):**
    - Read `animation_metadata.json`. For each refined scene, find the matching entry by `scene_id` and replace it. If a scene has no matching `scene_id` in metadata (was added manually), append it.
    - Write the updated metadata back to `animation_metadata.json`.

---

Apply the scenery template from `scenery.md` and setting context from `setting.md`.

## ROLE: MASTER CINEMATOGRAPHER — REFINEMENT PASS

Your task: analyze each scene and enhance every visual description, motion prompt, and camera instruction to produce precise, unambiguous results for AI image and video generation. Eliminate all vagueness and ambiguity.

## REFINEMENT CHECKLIST

### RULE 1 — SELF-CONTAINED PANELS
Each panel will be rendered INDEPENDENTLY — no pipeline shares context between panels.
Every panel MUST contain all required visual information inline:
- Repeat the character's full visual appearance in `visual_start` and `visual_end` (hair, clothing, build, distinguishing features) — NEVER write "same as before" or "continues from panel N".
- Repeat location details (architecture, lighting, props, atmosphere) in every panel.
- Repeat the exact shot type and camera angle (ECU / CU / MS / WIDE + lens + angle) in every panel and in `lights_and_camera` — never say "same framing".

### RULE 2 — SPATIAL DISPOSITION IN visual_start
`visual_start` must explicitly state the spatial arrangement at t=0:
- Who is present, where they stand/sit relative to camera and each other.
- Body orientation (facing camera / three-quarter / profile / turned away).
- Distance from camera (foreground / mid-ground / background).
- Dominant expression, posture, gesture at t=0.
- Background elements visible from this camera angle.
Example: "MEDIUM SHOT. Ivan (30s, dark stubble, grey hoodie) stands LEFT of frame, facing RIGHT toward camera at 45°, arms crossed, jaw tight. Behind him: rain-streaked window, blurred city lights bokeh."

### RULE 3 — is_reversed FLAG FOR GROK IMAGINE
Panels will be animated as 6-second clips by Grok Imagine, which does NOT support image references.
The only way to show a character or object ENTERING the frame is reverse playback.

Set `is_reversed=true` for any panel where:
- A character enters the scene, walks in, or appears from off-screen.
- An object comes into view (door opens revealing someone, fog clears, etc.).
- Someone approaches the camera from a distance.
- `visual_end` shows a presence that is ABSENT in `visual_start`.
- A character's FACE is hidden at `visual_start` (back to camera, hood up, silhouette, turned away)
  and is REVEALED during the motion (turns around, removes hood, steps into light facing camera).
  Shoot the character turning AWAY (face → back), reverse so viewer sees the face reveal.

### visual_start / visual_end (70+ words each)
- Replace vague terms: not "a suit" but "charcoal wool double-breasted suit with white pocket square"
- Specify which hand holds objects: "in his RIGHT hand", "left hand resting on knee"
- Describe textures: silk, matte leather, brushed steel, cracked concrete
- Include character posture, gaze direction, micro-expressions
- Background: distance, depth layers, out-of-focus elements
- Ensure character appearance matches their `video_visual_desc` from loaded reference JSONs

### motion_intent
Every panel must have `motion_intent` — one sentence stating what the character wants to achieve physically in this clip. If missing or vague ("character moves toward her"), rewrite it as a goal-driven statement ("Alisa crosses the room to reclaim the document before he reads it"). If you cannot state why the character moves, the panel has no dramatic content — rewrite the panel content to give it one.

### motion_prompt (100+ words, timestamped)
- Add precise timestamps: "At 0s...", "At 2s...", "At 5s...", "At 7s..."
- Specify camera movement explicitly: "camera remains static", "slow push-in over 4 seconds", "pan 15° left"
- Describe facial expressions evolving over time
- Physical actions must be achievable in 6–8 seconds — no teleportation, no scene jumps
- Include audio cues if they drive the visual: "glass clinks against table"

**PHYSICAL REALISM PROTOCOL — apply during refinement pass. The video model renders every phrase literally.**

1. **Physical movements only. No emotional language.** Strip all interpretive adjectives (`"poleaxed"`, `"barely-controlled panic"`, `"utter disbelief"`). Replace with anatomical descriptions: joint angles, degrees, distances, durations.
2. **No spectacle verbs for small actions.** Flag and rewrite any use of `erupts`, `sprays`, `fountains`, `explodes`, `bursts`, `ejaculates` for human actions — these generate special-effect-scale artifacts.
3. **No speed metaphors.** Replace `"blurring speed"`, `"in an instant"`, `"lightning-fast"`, `"snapped"` with explicit timestamps and distances.
4. **Anatomically correct scale.** A tear: 2–3 mm bead. Choking on liquid: small amount escapes the lips, not a spray. Over-reactive emotions (ping-pong-ball tears, vomit-fountain coffee) are the direct result of dramatic language in motion_prompt — remove it.
5. **Self-check every phrase:** could the AI render this as a grotesque artifact? If yes — rewrite as a plain physical movement.

### lights_and_camera
- Specify lens (e.g., "50mm anamorphic prime")
- Depth of field: "shallow DOF, subject sharp, background bokeh"
- Key light: direction (45° camera-left), color temperature (warm tungsten 3200K / cool daylight 5600K)
- Fill light ratio: "2:1 fill", "minimal fill for hard shadows"
- Any practical lights visible in frame (lamp, screen glow, neon sign)
- Camera angle must remain IDENTICAL between visual_start and visual_end

### Narrative Continuity
- Verify character outfits, props, and physical states match the previous episode's `visual_continuity_rules`
- If a character was established carrying something, they must still carry it unless the scene explicitly removes it
- Location details must be consistent with earlier scenes in the same location

### voiceover
- Must reveal subtext — fear, memory, desire — that the IMAGE cannot show
- Must NOT describe what is visually obvious ("she runs" is banned; "she knows she won't make it" is correct)
- Must be in Russian, synced to the action timing of the panel. No voice/gender prefix in the text field.
- Hard limit: 4–5 words for pivot panels (P7). Inner monologue is a flash — not a sentence.
- If empty, consider whether inner monologue would deepen the panel — add it if so

### voiceover_settings
- Required alongside every non-empty `voiceover`. Add if missing.
- Format: `{"gender": "male"/"female", "actor": "character name", "age": "approximate as string", "tone": "comma-separated delivery descriptors e.g. scared, confused"}`
- Use `{}` when voiceover is empty.

### emotional_beat / hook_type / text_safe_composition
- Verify `emotional_beat` accurately names the single dominant emotion of the panel
- Verify `hook_type` matches the panel's narrative role (cold_open / escalation / confrontation / twist / cliffhanger / none)
- Verify `text_safe_composition` is `true` for any panel with dialogue or voiceover
- Do not change these unless they are clearly wrong

### panel_type / transition_to_next / sound_design
- Verify `panel_type` is `"narrative"` for every panel.
- Verify `transition_to_next` is set correctly: `match_cut` must name the matching visual element in `motion_prompt`; `jump_cut` panels should have duration 2–3s; `j_cut` panels must describe the bleeding audio in `sound_design`.
- Verify `sound_design` is present for every panel. At least one panel per scene must have `sound_design="silence"` paired with `transition_to_next=smash_cut` on the following panel. If missing or generic, write a specific sonic cue.

### location_references
- Verify `location_references` lists any room, building, or outdoor location refs (from `ref_thriller/`) visible in this panel. Add any missing location refs. Leave empty if truly no location reference applies.
- Use exact split-view names:
  - **Room**: `{Room-Name}-View-From-Entrance` or `{Room-Name}-View-To-Entrance` — choose based on camera side. Background element "behind [subject]" is on the wall OPPOSITE the camera.
  - **Vehicle**: `{Vehicle-Name}-Exterior` / `{Vehicle-Name}-Interior-From-Entrance` / `{Vehicle-Name}-Interior-To-Entrance`.
  - **Outdoor**: `{Outdoor-Name}-View-Primary` (camera faces PRIMARY DIRECTION toward canonical background landmark) or `{Outdoor-Name}-View-Opposite` (180° turn; left/right SWAPPED). "archway behind her" + archway is PRIMARY-end → View-Opposite. "open street behind him" + street is near/entry end → View-Primary.
  - Names must match existing refs EXACTLY — a mismatch silently skips the reference image during rendering.

### RULE 4 — CROSS-SCENE SPATIAL CONTINUITY

Panel 1's `visual_start` MUST be spatially compatible with the cross-scene terminal frame identified in step 5 (previous scene's last panel `visual_end`): same environment, same lighting condition, same character positions — unless this scene opens in a different location or after a time-skip, in which case state that **explicitly** in panel 1's `visual_start` (e.g. "CUT TO: new location, 10 minutes later").

### RULE 5 — CROSS-PANEL SPATIAL CONTINUITY

Characters do not teleport between panels. Each panel's `visual_start` at t=0 must be spatially compatible with the previous panel's `visual_end`, unless a `hard_cut` or location change is established. If a character was LEFT of frame at the end of panel N, they cannot be RIGHT of frame at the start of panel N+1 without a stated camera repositioning or character movement. Build a spatial anchor chain from the existing panel endpoints and check each panel against it.

### RULE 6 — EMOTIONAL ARC INTEGRITY

Verify and enforce the 9-panel arc structure. Do NOT allow resolution before panel 9:
- Panel 1: `cold_open` | Panel 2: `context` | Panels 3–5: `escalation`
- Panel 6: `confrontation` | Panel 7: `peak` | Panel 8: `twist` | Panel 9: `cliffhanger`

Each panel's `emotional_beat` and `hook_type` must align with its arc position. Correct mismatches.

### RULE 7 — CAMERA AND LIGHTING MASTER COMPLIANCE

Every panel's `lights_and_camera` must stay within the scene's `camera_master` and `lighting_master` DNA. Deviations for dramatic effect are allowed but must be flagged explicitly in that field (e.g. "deviation from master: snap to 24mm wide for panic effect, then return to established 85mm CU").

### Reference Alignment
- For each character in `references`, ensure visual descriptions match their `video_visual_desc` exactly
- Do not invent new physical traits not established in reference JSONs

## OUTPUT FORMAT

Return the complete refined data in the same JSON structure as the input file (the full `{"scenes": [...]}` object with all scenes included).
