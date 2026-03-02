Scene file to refine: $ARGUMENTS

Steps:
1. Read the scene JSON file at `$ARGUMENTS`
2. Extract the episode number from the filename (e.g., `animation_episode_scenes_003.json` → episode 3)
3. Read `cinematic_render/animation_episodes.json` and extract that episode for context
4. If episode > 1, also extract the previous episode for continuity context
5. Check if `custom_prompts/scenery.md` exists — use it; otherwise use `prompts/scenery.md`. Read it.
6. Check if `custom_prompts/setting.md` exists — use it; otherwise use `prompts/setting.md`. Read it.
7. For each name in any panel's `references` array, try to read `ref_thriller/{name_lowercased_underscored}.json` and extract `video_visual_desc`
8. Refine every scene following all instructions below.
9. Write the result to the same path with `_refined` inserted before `.json` (e.g., `animation_episode_scenes_003_refined.json`)

---

Apply the scenery template from `scenery.md` and setting context from `setting.md`.

## ROLE: MASTER CINEMATOGRAPHER — REFINEMENT PASS

Your task: analyze each scene and enhance every visual description, motion prompt, and camera instruction to produce precise, unambiguous results for AI image and video generation. Eliminate all vagueness and ambiguity.

## REFINEMENT CHECKLIST

### visual_start / visual_end (70+ words each)
- Replace vague terms: not "a suit" but "charcoal wool double-breasted suit with white pocket square"
- Specify which hand holds objects: "in his RIGHT hand", "left hand resting on knee"
- Describe textures: silk, matte leather, brushed steel, cracked concrete
- Include character posture, gaze direction, micro-expressions
- Background: distance, depth layers, out-of-focus elements
- Ensure character appearance matches their `video_visual_desc` from loaded reference JSONs

### motion_prompt (100+ words, timestamped)
- Add precise timestamps: "At 0s...", "At 2s...", "At 5s...", "At 7s..."
- Specify camera movement explicitly: "camera remains static", "slow push-in over 4 seconds", "pan 15° left"
- Describe facial expressions evolving over time
- Physical actions must be achievable in 6–8 seconds — no teleportation, no scene jumps
- Include audio cues if they drive the visual: "glass clinks against table"

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
- Must be in Russian, synced to the action timing of the panel
- If empty, consider whether inner monologue would deepen the panel — add it if so

### emotional_beat / hook_type / text_safe_composition
- Verify `emotional_beat` accurately names the single dominant emotion of the panel
- Verify `hook_type` matches the panel's narrative role (cold_open / escalation / confrontation / twist / cliffhanger / none)
- Verify `text_safe_composition` is `true` for any panel with dialogue or voiceover
- Do not change these unless they are clearly wrong

### Reference Alignment
- For each character in `references`, ensure visual descriptions match their `video_visual_desc` exactly
- Do not invent new physical traits not established in reference JSONs

## OUTPUT FORMAT

Return the complete refined data in the same JSON structure as the input file (the full `{"scenes": [...]}` object with all scenes included).
