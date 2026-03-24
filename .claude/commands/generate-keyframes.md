Episode number to process: $ARGUMENTS

Steps:
1. Read `cinematic_render/animation_episodes.json`
2. Extract the episode where `episode_id` equals $ARGUMENTS. Note its `episode_type` (`pov_a` / `pov_b` / `confrontation` / `transition`) and `pov_character`.
3. If $ARGUMENTS > 1, extract the **previous episode** (`episode_id` = $ARGUMENTS − 1) and note its `visual_continuity_rules` — enforce these in every panel of this episode.
4. Check if `custom_prompts/scenery.md` exists — use it; otherwise use `lib/prompting/vertical_9_16_microdrama/scenery.md`. Read it.
5. Check if `custom_prompts/setting.md` exists — use it; otherwise use `prompts/setting.md` (legacy fallback). Read it.
6. Check if `custom_prompts/config.json` exists — use it; otherwise use `lib/prompting/vertical_9_16_microdrama/config.json`. Read it for `panels_per_scene` and `animation.enabled`.
6b. Read `lib/prompting/vertical_9_16_microdrama/screenplay_scene.md` — this is the authoritative panel generation rulebook. All cinematography rules, motion protocols, panel structure, voice budget, and output field contracts come from this file.
7. List all `.png` files in `ref_thriller/` — these are the available character/location references.
8. Generate scene keyframes following all instructions below, applying the episode-type rules for the extracted `episode_type`. Set `episode_id` = $ARGUMENTS in every scene object.
9. Write output to `cinematic_render/animation_episode_scenes_{episode_id:03d}.json` (zero-padded to 3 digits).
10. **Update `cinematic_render/animation_metadata.json` (single source of truth):**
   - If the file exists, read it. Remove all scenes where `episode_id` equals $ARGUMENTS. Find the `scene_id` of the last remaining scene (or 0 if none). Assign sequential `scene_id` values to the new scenes starting from that value + 1. Insert the new scenes, keeping all others, sorted by `scene_id`. Preserve the existing `config` key if present, otherwise set it from the config loaded in step 5.
   - If the file does not exist, create it as `{"scenes": [...new scenes with scene_id starting at 1...], "config": <config from step 5>}`.
   - Write the result back to `cinematic_render/animation_metadata.json`.

---

Apply the scenery template instructions from the loaded `scenery.md`, setting context from `setting.md`, and ALL panel generation rules from the loaded `screenplay_scene.md` — including the independence protocol, motion protocols, cinematography techniques, voice budget, panel arc structure, post-write audit, and dialogue exchange continuity rules.

## ROLE: MASTER CINEMATOGRAPHER — KEYFRAME GENERATION

You prepare keyframe assets for AI-based Image-To-Video story visualization. You are generating production-ready panel descriptions that drive image and video generation models.

## CONTEXT

- Available character/location references (from `ref_thriller/` PNGs): use only names matching these files for the `references` field
- `panels_per_scene`: from config.json (default: 9)
- `animation.enabled`: from config.json — determines whether to use `visual_start`/`visual_end` or a single visual

## PANEL DESCRIPTION RULES

Follow ALL field contracts and constraints from the loaded `screenplay_scene.md`. Key fields per panel:

- `motion_intent` — one sentence: what does the character want to achieve in this physical moment? Required before writing `motion_prompt`.
- `visual_start` — 70+ words, state JUST BEFORE [0s] begins (not mid-action, not residual from previous panel).
- `visual_end` — 70+ words, state after the micro-action; new unstable state, not a completion.
- `motion_prompt` — 100+ words, timestamped. Physical movements only. ITEM ORIGIN: every retrieved object must come from a physically real place stated in the character's ref. Follow all motion protocols from screenplay_scene.md (temporal compression, combat collapse, motion budget, hesitation constraints, tableau failure rule, post-write audit).
- `motion_prompt_reversed` — always leave `""` — populated by `/reversal-pass`.
- `is_reversed` — see screenplay_scene.md.
- `lights_and_camera` — lens, angle, DOF, key light. Must be identical between start/end.
- `dialogue` — ≤8 words per line, Russian. Follow dialogue exchange continuity rules from screenplay_scene.md.
- `voiceover` — inner monologue in Russian, no voice/gender prefix in the field. Hard limit: 4–5 words for pivot panels (P7). Reveals subtext only — never narrates what is visible.
- `voiceover_settings` — required alongside every non-empty voiceover: `{"gender": "male"/"female", "actor": "character name", "age": "approximate as string", "tone": "comma-separated delivery descriptors"}`. Use `{}` when voiceover is empty.
- `emotional_beat` — one of: `tension`, `revelation`, `grief`, `desire`, `defiance`, `dread`, `relief`, `rage`, `longing`, `shock`, `shame`, `triumph`.
- `hook_type` — uses `/` notation: `cold_open/status_reversal`, `cold_open/impossible_situation`, `cold_open/hidden_identity`, `cold_open/ticking_clock`, `cold_open/revelation`; `cliffhanger/response_freeze`, `cliffhanger/revelation`, `cliffhanger/emotional_rupture`, `cliffhanger/interrupted_action`; or: `verbal_hook`, `escalation`, `emotional_capture`, `crystallization`, `confrontation`, `pivot`, `twist`, `tension_peak`, `backlink`, `none`.
- `text_safe_composition` — `true` when key subjects are in middle 65% of frame height.
- `caption` — required for every panel. ≤40 characters. A hook, not a summary — emotional subtext or open question that makes a viewer pause their scroll. SELF-TEST: if a stranger saw only the image + caption, would they pause? Rewrite until yes.
- `panel_type` — always `"narrative"`.
- `transition_to_next` — `match_cut` / `jump_cut` / `smash_cut` / `j_cut` / `hard_cut`.
- `sound_design` — required for every panel. See screenplay_scene.md for silence-panel rules.
- `duration` — 6–8s default; 2–3s for jump_cut escalation panels; P1 hard cap 3s (autocut leaves only 2–4s visible).
- `references` — character/object ref names from `ref_thriller/` (no extension).
- `location_references` — see naming rules below.

### SCENE-LEVEL FIELDS
- `camera_master` — one sentence: dominant lens (mm), angle, primary lighting condition shared by all panels.
- `lighting_master` — one sentence: key light direction/color/quality, fill ratio, visible practicals.

### INDEPENDENCE PROTOCOL — NON-NEGOTIABLE

Each panel is rendered by a separate image-generation model with ZERO context.
- **FORBIDDEN**: "same as before", "same POV", "same framing", "as in panel N", "continues from", "identical to", "as established".
- **REQUIRED in every panel**: location details, shot type, camera angle, lighting. Character reference images are injected separately — describe ONLY scene-specific deviations (costume changes, carried items, injuries, transient state). Signature visual tells must be mentioned at CU/ECU range.
- **POV CAMERA LAW**: a shot from [Character X]'s POV means Character X CANNOT appear anywhere in frame.

### LOCATION_REFERENCES NAMING

Use exact split-view names:
- **Room**: `{Room-Name}-View-From-Entrance` (camera at door, looking in) or `{Room-Name}-View-To-Entrance` (camera inside, looking toward door). Key rule: background element "behind [subject]" is on the wall OPPOSITE the camera.
- **Vehicle**: `{Vehicle-Name}-Exterior` / `{Vehicle-Name}-Interior-From-Entrance` / `{Vehicle-Name}-Interior-To-Entrance`.
- **Outdoor**: `{Outdoor-Name}-View-Primary` (camera faces the PRIMARY DIRECTION defined in the ref compass layout) or `{Outdoor-Name}-View-Opposite` (180-degree turn; left/right SWAPPED). Key rule: "archway behind her" + archway is the PRIMARY-end landmark → View-Opposite. "open street behind him" + street is the near/entry end → View-Primary.
- Names must match existing refs EXACTLY — a mismatch silently skips the reference image during rendering.

## EPISODE-TYPE SPECIFIC RULES

Apply these rules based on the `episode_type` extracted in step 2:

### POV-A / POV-B Episodes
- Depict events exclusively from the POV character's perspective. The other character is absent, peripheral, or seen from a distance — never given equal screen weight.
- **Backlink mandatory**: Panel 2 or 3 MUST use `hook_type: "backlink"`, `duration: 3`, no `dialogue`. Flash memory cut: ECU on POV character's face → memory image → back to present. `voiceover` carries the inner echo of the previous chapter's most charged moment.
- `references`: only include the POV character and props/locations they interact with.

### Confrontation Episodes
- Both characters present throughout. Early panels establish spatial tension, middle panels alternate ECU between faces, final panel is unresolved cliffhanger. No backlink needed.

### Transition Episodes (time-gap bridges)
- ALL panels: `panel_type: "narrative"`, `duration: 3`. Environmental/location shots only — no character close-ups.
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
          "motion_intent": "One sentence: what does the character want to achieve in this physical moment?",
          "visual_start": "70+ word description of initial static state at t=(-0.1s)...",
          "visual_end": "70+ word description of new unstable state after micro-action...",
          "motion_prompt": "100+ word timestamped motion instruction...",
          "is_reversed": false,
          "motion_prompt_reversed": "",
          "lights_and_camera": "Camera: 50mm anamorphic, shallow DOF. Key light: 45° right, warm tungsten. Fill: soft left.",
          "dialogue": "",
          "voiceover": "",
          "voiceover_settings": {"gender": "female", "actor": "Character-Name", "age": "30", "tone": "scared, confused"},
          "emotional_beat": "tension",
          "hook_type": "cold_open/status_reversal",
          "text_safe_composition": true,
          "panel_type": "narrative",
          "transition_to_next": "hard_cut",
          "sound_design": "low-frequency hum builds",
          "caption": "≤40 chars — hook, not summary",
          "duration": 3,
          "references": ["Character-Name"],
          "location_references": ["Location-View-From-Entrance"]
        }
      ]
    }
  ]
}
```
