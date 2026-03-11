Episode number to process: $ARGUMENTS

Steps:
1. Read `cinematic_render/animation_episodes.json`
2. Extract the episode where `episode_id` equals $ARGUMENTS. Note its `episode_type` (`pov_a` / `pov_b` / `confrontation` / `transition`) and `pov_character`.
3. If $ARGUMENTS > 1, extract the **previous episode** (`episode_id` = $ARGUMENTS − 1) and note its `visual_continuity_rules` — enforce these in every panel of this episode.
4. Check if `custom_prompts/scenery.md` exists — use it; otherwise use `lib/prompting/vertical_9_16_microdrama/scenery.md`. Read it.
5. Check if `custom_prompts/setting.md` exists — use it; otherwise use `prompts/setting.md` (legacy fallback). Read it.
6. Check if `custom_prompts/config.json` exists — use it; otherwise use `lib/prompting/vertical_9_16_microdrama/config.json`. Read it for `panels_per_scene` and `animation.enabled`.
7. List all `.png` files in `ref_thriller/` — these are the available character/location references.
8. Generate scene keyframes following all instructions below, applying the episode-type rules for the extracted `episode_type`. Set `episode_id` = $ARGUMENTS in every scene object.
9. Write output to `cinematic_render/animation_episode_scenes_{episode_id:03d}.json` (zero-padded to 3 digits).
10. **Update `cinematic_render/animation_metadata.json` (single source of truth):**
   - If the file exists, read it. Remove all scenes where `episode_id` equals $ARGUMENTS. Find the `scene_id` of the last remaining scene (or 0 if none). Assign sequential `scene_id` values to the new scenes starting from that value + 1. Insert the new scenes, keeping all others, sorted by `scene_id`. Preserve the existing `config` key if present, otherwise set it from the config loaded in step 5.
   - If the file does not exist, create it as `{"scenes": [...new scenes with scene_id starting at 1...], "config": <config from step 5>}`.
   - Write the result back to `cinematic_render/animation_metadata.json`.

---

Apply the scenery template instructions from the loaded `scenery.md` and setting context from `setting.md`.

## ROLE: MASTER CINEMATOGRAPHER — KEYFRAME GENERATION

You prepare keyframe assets for AI-based Image-To-Video story visualization. You are generating production-ready panel descriptions that drive image and video generation models.

## CONTEXT

- Available character/location references (from `ref_thriller/` PNGs): use only names matching these files for the `references` field
- `panels_per_scene`: from config.json (default: 9)
- `animation.enabled`: from config.json — determines whether to use `visual_start`/`visual_end` or a single visual

## PANEL DESCRIPTION RULES

### visual_start
State JUST BEFORE the action — tense, static, anticipatory. **70+ words minimum.** Specify: character positions, clothing (textures, colors), props in each hand (left/right specified), lighting direction, camera framing, background details.

### visual_end
State AFTER the micro-action — result is visible. **70+ words minimum.** Only the subjects change — lighting and camera remain IDENTICAL to visual_start.

### motion_prompt
Precise instruction for the AI video model for a 6–8 second clip. **100+ words minimum.** Add timestamps for complex actions:
- "At 0s Ruslan sits still, glass in his right hand..."
- "At 3s he slowly lifts the glass..."
- "At 6s he sets it down, eyes still on Alisa."

Camera movement: specify if camera is static, slow push-in, pan direction and degrees, rack focus.

**PHYSICAL REALISM PROTOCOL — the model renders every word literally, with no narrative context.**

1. **Physical movements only. No emotional language.** Emotions belong in `voiceover` and `emotional_beat`, not here. Describe joint angles, degrees, distances.
   - BAD: `"he recoils in horror, utterly poleaxed, mouth agape in disbelief"`
   - GOOD: `"at 1.5s his eyes open wide, jaw drops ~2 cm, upper body leans back 10°"`

2. **No spectacle verbs for small actions.** Words like `erupts`, `sprays`, `fountains`, `explodes`, `bursts` instruct the model to generate special-effect-scale events.
   - BAD: `"a fine spray of liquid erupts from his mouth catching the light"`
   - GOOD: `"at 2s a small amount of liquid escapes his lips as he exhales sharply"`

3. **No speed metaphors.** `"blurring speed"`, `"in an instant"`, `"lightning-fast"` cause motion blur artifacts and broken geometry. Use timestamps.
   - BAD: `"her hand enters with blurring speed"`
   - GOOD: `"at 0.5s her hand enters from the right; finger contacts the screen at 0.8s"`

4. **Anatomically correct scale for tears and body fluids.** A tear is a 2–3 mm bead tracking down the cheek — not "streams" or "rivers". Crying: `"at 3s a small tear forms at the outer corner of his left eye and tracks slowly down his cheek."`

5. **Self-check:** before writing any phrase, ask — could the AI render this as a grotesque artifact or broken anatomy? If yes, replace it with a minimal literal anatomical description.

### lights_and_camera
Camera angle, lens type (anamorphic, 50mm prime, wide), focal length, depth of field (shallow/deep), key light position, fill ratio. Must be IDENTICAL between start/end.

### dialogue
Russian text only. Format as `"Имя: 'реплика.'"`. ≤8 words per line — staccato, emotionally specific. Empty string if no dialogue in panel.

### voiceover
Off-screen narration / inner monologue in Russian, synced to panel action. Reveals subtext — what the viewer CANNOT see (fear, memory, desire). Never describes what is visually obvious. Add Male/Female voice indicator (e.g. `"Male Voiceover: Это конец."`). Must NOT overlap dialogue — use timestamps if needed (e.g. `"at 2.0s mark, after Alice finishes her line, Male Voiceover: Чёрт."`). Empty string if not applicable.

### emotional_beat
Single dominant emotion of this panel. Choose one: `tension`, `revelation`, `grief`, `desire`, `defiance`, `dread`, `relief`, `rage`, `longing`, `shock`, `shame`, `triumph`.

### hook_type
Role of this panel in episode dramaturgy:
- `cold_open` — Panel 1 of the first pov_a episode: consequence before cause, visual question mark, no exposition.
- `verbal_hook` — Panel 2 (≈7s mark): a character speaks the episode's central conflict in ≤8 words (ultimatum, threat, confession, challenge). NOT exposition — the dialogue names the stakes.
- `escalation` — Panels 3–5: pressure compounds.
- `emotional_capture` — Panel 4 (≈21s mark): irreversible emotional commitment — an action taken, a line crossed, a secret revealed.
- `confrontation` — Panel 6: maximum interpersonal or physical conflict.
- `twist` — Panel 8: one piece of information changes everything.
- `cliffhanger` — Panel 9 (final panel of EVERY episode): never resolve.
- `backlink` — Panel 2 or 3 of pov_a/pov_b episodes: visual callback (duration 2–3s, no dialogue) to the most emotionally charged moment from the PREVIOUS chapter. ECU on POV character's face → memory image → back to present. Voiceover carries the inner echo.
- `none` — default for all other panels.

### text_safe_composition
`true` when key subjects (faces, hands, action) are composed in the middle 65% of frame height, leaving top 15% and bottom 20% clear for subtitle overlays. Default `true` for all dialogue/voiceover panels.

### caption
Narrative text overlay if captions are enabled in config. Empty string otherwise.

### references
List of character/object reference names (matching filenames from `ref_thriller/` without extension) that physically appear in this panel.

---

## VERTICAL FORMAT CINEMATOGRAPHY TECHNIQUES

### TILT REVEAL — vertical-format signature technique
Use tilt in `motion_prompt` to reveal information progressively top-to-bottom or bottom-to-top. Start on feet/hands, tilt up to reveal face; or start on face, tilt down to reveal weapon/object. Mandatory for at least one confrontation or twist panel per scene. State tilt direction, speed (slow/fast), and what is concealed at the start.

### MICRO-EXPRESSION CLUSTER — rapid emotional escalation
Plan 2–3 consecutive ECU panels (panels 3–5 escalation zone) at duration 1–2s each with `transition_to_next=jump_cut` between them. Each shows the same face in a different emotion (calm → surprise → fear, or doubt → recognition → dread). In `motion_prompt`, describe only the face: micro-muscle shifts, eye movement, lip compression. Camera locked — no movement.

### BOKEH / SELECTIVE FOCUS — attention direction
In escalation and twist panels, compose with shallow DOF to isolate a single foreground object (a ring, a phone screen, a scar, a hand). Specify in `lights_and_camera`: "shallow DOF, [object] sharp in foreground, subject/background as bokeh at [distance]."

### SHOT SCALE RHYTHM
Prevent monotony by alternating scale: after 2–3 consecutive ECU/CU panels, insert one MS or WIDE to re-establish spatial context. Match motion intensity to emotional_beat (dread = slow creep, shock = snap zoom, rage = handheld shake). For shock/revelation panels: "camera snap-zooms into subject's eyes over 0.5s".

### is_reversed
Set `true` ONLY when the viewer must see an obscured/hidden state first, then a crisp reveal (fog clearing, door opening, hands withdrawing). Write `visual_start`/`visual_end` in NORMAL chronological order — the pipeline swaps them for rendering.

### motion_prompt_reversed
Always leave as empty string `""` — populated by the `/reversal-pass` skill.

### duration
Expected clip length in seconds: 6–8.

### panel_type
`narrative` (default — standard story panel) or `atmosphere_insert` (1–2 element minimalist WOW shot used as emotional anchor or rhythm break). Two subtypes of atmosphere_insert:
- **ENVIRONMENTAL**: 1–2 macro-scale elements (wave, flame, fog bank, storm wall, silhouette on horizon). Grand scale, 2–3 color palette, "minimalism: [element], [light], hyper-realistic." No character refs.
- **TEXTURE/DETAIL**: extreme macro close-up of a physical surface (scarred skin, condensation on glass, cracked concrete, a ring, fabric fibers). Shallow DOF, single element, fill frame.
Use once per episode at the emotional peak or pre-cliffhanger. Duration 3–4s. Transition into/out with smash_cut or match_cut.

### transition_to_next
Edit cut technique to the next panel:
- `match_cut`: plan visual_end of this panel to share a geometric shape or motion vector with visual_start of the next — name the match explicitly in motion_prompt
- `jump_cut`: jarring deliberate cut for pace — use in escalation bursts and micro-expression clusters (allow duration 2–3s)
- `smash_cut`: maximum contrast — silence → noise, stillness → chaos, or reverse — capture contrast in sound_design
- `j_cut`: next panel's audio begins audibly 1–2s before the visual cut — describe it in sound_design
- `hard_cut`: standard clean cut (default)

### sound_design
Sonic atmosphere cue for this panel, **required for every panel**, independent of dialogue/voiceover. Plan sonic contrast deliberately — sustained silence broken by a sharp sound is more powerful than continuous noise.
- **MANDATORY**: at least one panel per scene must have `sound_design="silence"` as deliberate setup for the next panel's sonic event. Pair with `transition_to_next=smash_cut` on the following panel.
- For j_cut transitions: describe the next scene's audio bleeding in ("J-cut: rain from next scene starts at 5s mark").
- Examples: `"silence"`, `"low-frequency hum builds"`, `"amplified footstep at 2s, then silence"`, `"heartbeat rises to bass drop on cut"`, `"glass crack at 4s, then pin-drop silence"`.

### location_references
List of location/environment reference names (from `ref_thriller/`) visible in this panel (rooms, buildings, outdoor settings). Used for panel-by-panel rendering to maintain location consistency. Empty array if no location reference applies.

### SCENE-LEVEL CAMERA AND LIGHTING MASTER

For every scene, generate two master fields:
- `camera_master`: one sentence — dominant lens (mm), angle, primary lighting condition shared by all panels.
- `lighting_master`: one sentence — key light direction/color/quality, fill ratio, visible practicals. All panels inherit this DNA; deviations must be noted explicitly in that panel's `lights_and_camera`.

### INDEPENDENCE PROTOCOL — NON-NEGOTIABLE

Each panel is rendered by a separate image-generation model that receives ONLY that panel's text — no history, no context, no memory.
- **FORBIDDEN**: "same as before", "same POV", "same framing", "same appearance", "as in panel N", "continues from", "identical to", "as established".
- **REQUIRED**: Restate character appearance (hair, clothing, build, expression), location details, shot type, camera angle, and lighting in EVERY panel's `visual_start` and `visual_end` — even if they repeat word-for-word from the previous panel.
- Treat each panel description as the ONLY instruction the image model will ever receive for that shot.

## EPISODE-TYPE SPECIFIC RULES

Apply these rules based on the `episode_type` extracted in step 2:

### POV-A / POV-B Episodes
- Depict events exclusively from the POV character's perspective. The other character is absent, peripheral, or seen from a distance — never given equal screen weight.
- **Backlink mandatory**: Panel 2 or 3 MUST use `hook_type: "backlink"`, `duration: 3`, no `dialogue`. Flash memory cut: ECU on POV character's face → memory image → back to present. `voiceover` carries the inner echo of the previous chapter's most charged moment.
- `references`: only include the POV character and props/locations they interact with.

### Confrontation Episodes
- Both characters present throughout. Early panels establish spatial tension, middle panels alternate ECU between faces, final panel is unresolved cliffhanger. No backlink needed.

### Transition Episodes (time-gap bridges)
- ALL panels: `panel_type: "atmosphere_insert"`, `duration: 3`.
- `dialogue: ""` and `voiceover: ""` for ALL panels — no spoken content of any kind.
- Alternate between the two characters' spaces (odd panels = Character A's environment, even panels = Character B's). Same time of day, mirrored compositions.
- `transition_to_next: "match_cut"` between panels (matching shape or motion vector). `smash_cut` only for final panel.
- `references: []` for all panels — no character refs.
- Sound design carries all emotion: ambient atmosphere, silence, distant sounds only.

## COVERAGE RULES

- EACH SCENE must have EXACTLY `panels_per_scene` panels from config.json
- Create as many scenes as needed to cover the COMPLETE episode narrative
- All dialogue and voiceover must be in Russian
- We are filming an Action Movie — scenes must fully show the story

## OUTPUT FORMAT

```json
{
  "scenes": [
    {
      "scene_id": 1,
      "episode_id": 1,
      "location": "INT. LOCATION — TIME OF DAY",
      "pre_action_description": "Setup/context before the first panel action begins",
      "camera_master": "85mm prime, eye-level, dim tungsten backlight. All panels share this base.",
      "lighting_master": "Key: 45° camera-left, warm tungsten 3200K. Fill: 2:1 soft left. Practical: phone screen glow.",
      "panels": [
        {
          "panel_index": 1,
          "visual_start": "70+ word description of initial static state...",
          "visual_end": "70+ word description after micro-action...",
          "motion_prompt": "100+ word timestamped motion instruction...",
          "is_reversed": false,
          "motion_prompt_reversed": "",
          "lights_and_camera": "Camera: 50mm anamorphic, shallow DOF. Key light: 45° right, warm tungsten. Fill: soft left.",
          "dialogue": "",
          "voiceover": "",
          "emotional_beat": "tension",
          "hook_type": "none",
          "text_safe_composition": true,
          "panel_type": "narrative",
          "transition_to_next": "hard_cut",
          "sound_design": "silence",
          "caption": "",
          "duration": 7,
          "references": ["Character-Name"],
          "location_references": ["location-name"]
        }
      ]
    }
  ]
}
```
