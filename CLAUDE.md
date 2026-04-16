# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This project converts a Russian novel (serialized as `s01e01.txt`, etc.) into AI-generated cinematic keyframe images suitable for video animation. It supports multiple LLM backends — OpenRouter (default), Google Gemini, Grok, and a local Debug backend — for text generation, and Google Gemini / Grok for image generation and animation.

## Environment Setup

Required API keys (depending on backend):

```bash
export OPENROUTER_API_KEY="your_key"   # required for default --llm openrouter
export IMG_AI_API_KEY="your_key"       # required for --llm gemini, Veo animation, TTS, dubbing
                                       # (also accepted as GOOGLE_API_KEY)
export XAI_API_KEY="your_key"          # required for --llm grok / animation grok
export ELEVEN_API_KEY="your_key"       # required for tts sfx
```

Optional overrides:
```bash
export AI_TEXT_MODEL="gemini-2.5-pro"                  # default
export AI_IMAGE_MODEL="google/gemini-3-pro-image-preview"  # default
export AI_GEMINI_MODEL="gemini-2.5-flash"              # default (Gemini-specific tasks)
export AI_CONCURRENCY="10"                             # text/LLM thread pool workers
export AI_IMAGE_CONCURRENCY="5"                        # image generation thread pool workers
export AI_SEED="42"                                    # image generation seed (openrouter)
export AI_LOG_LEVEL="DEBUG"                            # logging verbosity
export AI_ASPECT_RATIO="9:16"                          # image aspect ratio override (default: per config/preset)
export AI_IMAGE_SIZE="2K"                              # image resolution override (default: per config/preset)
export AI_REF_ASPECT_RATIO="9:16"                      # reference portrait aspect ratio override
export AI_VIDEO_TIMEOUT="600"                          # Veo polling hard limit in seconds (default: 600)
export TARGET_LANGUAGE="English"                       # dialogue/voiceover/caption language (default: English)
```

## Docker

The image bakes in code (`/app`); per-series data is mounted at `/project` at runtime.

```bash
# Build once (from repo root)
docker build -t ai-microdrama-factory:latest .

# Run any CLI command from a series directory
docker run --rm -v $(pwd):/project --env-file .env ai-microdrama-factory:latest <command> [args]

# Or via per-series docker-compose.yml
docker compose run --rm factory <command> [args]
docker compose up webserver   # static viewer → http://localhost:5005/web/index.html
```

Per-series directory layout: `docker-compose.yml` + `.env` + `custom_prompts/` + `ref_thriller/` + `cinematic_render/` + novel `.txt` files — all mounted as `/project`.

## Manual Workflow (Claude Code Skills)

The full pipeline is available as Claude Code slash commands in `.claude/commands/`. Run these in sequence instead of (or alongside) the Python scripts:

```bash
# Step 0 (optional): Split a full novel into filmable episode chunks
# → writes book-split/s01eNNN.txt
make split-book BOOK=fullbook.txt STYLE=vertical_9_16_microdrama SEASON=1

# Step 1: Analyze the novel — extracts metadata, recommends a visual style
/analyze-novel s01e01.txt

# Step 1b (optional): Generate custom_prompts/ overrides for a chosen style
# Available styles: vertical_9_16_microdrama | vertical_9_16_long_arc | vertical_9_16_generic
/customize-style s01e01.txt vertical_9_16_microdrama
# → writes override files to custom_prompts/ (style, casting, scenery, imagery, setting, config)
# → these overlay on top of lib/prompting/<style>/ at runtime

# Step 2: Generate character/location reference descriptions + image gen prompts
/cast-characters s01e01.txt

# Step 2b: Enrich room ref descriptions with named furniture, equipment, per-character anchors
# → updates visual_desc in ref_thriller/<room>-View-*.json; marks needs_regenerate on existing PNGs
make detail-rooms NOVEL=s01e01.txt

# Step 2c: Render missing reference portraits (runs Python — requires API key)
/render-references

# Step 2d (optional): Split Room/Vehicle refs into per-view variants (runs Python)
# → writes ref_thriller/<location>-View-From-Entrance.{json,png} etc.
make remake-room-refs

# Step 3: Break the novel into ~30 episodes with screenplay instructions
/write-screenplay s01e01.txt
# → writes cinematic_render/animation_episodes.json

# Step 4: Generate panel keyframes for a specific episode
/generate-keyframes 1
# → writes cinematic_render/animation_episode_scenes_001.json

# Step 4b (required for multi-scene episodes with recurring characters):
make consistency --no-dry-run
# → re-aligns character refs, prevents visual drift between scenes

# Step 5 (optional, ad-hoc): Manually refine visual descriptions post-generation
/refine-scene cinematic_render/animation_episode_scenes_001.json
# → writes cinematic_render/animation_episode_scenes_001_refined.json
# NOTE: refinement is no longer a required pipeline step — the 4-pass system in
# generate-keyframes handles this. Use only for targeted post-hoc corrections.

# Step 6 (optional, ad-hoc): Re-run reversal pass on an existing episode JSON
/reversal-pass cinematic_render/animation_episode_scenes_001_refined.json
# → updates the file in-place
# NOTE: reversal pass is now baked into generate-keyframes. Use only for corrections.

# Step 7 (optional): Generate chapter summary for continuity into next episode
/make-summary s01e01.txt
# → writes chapter_summary.txt
```

Each skill reads `lib/prompting/<style>/` as the primary source, then applies `custom_prompts/` overrides if present. Steps 4–7 repeat per episode. The Python script automates 4-pass generation in parallel; running manually gives full control over individual episodes.

**Note**: Actual image/grid rendering still requires the Python script — Claude cannot generate images directly.

**Note**: Steps 5 and 6 (`/refine-scene`, `/reversal-pass`) are optional manual tools — the reversal pass is now baked into `/generate-keyframes` (and the Python `scenes` command). Use them only for ad-hoc post-hoc corrections.

## Architecture

### Entry Point

**`cli.py`** — Single CLI with 20+ subcommands covering the full pipeline from text to video.
Uses `--llm {openrouter|gemini|grok|debug}` to select the backend. The `debug` backend (LogDebugLLM) logs all prompts/responses to disk without calling any API, useful for offline testing.

### Library Structure (`lib/`)

```
lib/
  core/        # Project config, path constants, prompts loader, JSON schemas, grid utils, puppet engine (camera rig + 3D layout)
  llm/         # BaseLLM ABC + backends: GeminiLLM, OpenRouterLLM, GrokLLM, LogDebugLLM
  prompting/   # Style preset directories (each: *.md prompts + config.json + book-shrinker.md)
    vertical_9_16_microdrama/
    vertical_9_16_long_arc/
    vertical_9_16_generic/
  studio/      # Production pipeline modules:
    stylist.py      — novel analysis + custom_prompts/ overlay generation
    screenwriter.py — episode/scene AI passes; 4-pass scene generation (architecture → state → visual → motion_audio); character variation selection via `visual_ref` per panel actor; reversal pass produces `visual_start_explicit`; disposition groups panels by shared anchor ref; puppet engine for 180-rule validation
    artist.py       — casting, reference rendering, room-view splitting, grid/panel image generation, slicing
    critic.py       — QA gate: fidelity/consistency scoring per panel
    director.py     — continuity enforcer: enriches refs, aligns scene prompts
    editor.py       — panel refinement using original + reference images
    cutter.py       — autocut: AI-trim animation clips
    retoucher.py    — image editing via LLM
    bookbinder.py   — split full novel into filmable episode chunks (sliding-window, anchor-based)
  commands/    # argparse command registration modules (setup, screenplay, storyboard, animation, audio)
  animation/   # Veo (Google) and Grok animators
  audio/       # TTS (Gemini/OpenRouter), SFX (ElevenLabs), dubbing (Whisper→TTS), ducking, dynamic subtitles
```

### Pipeline Stages (via `cli.py` subcommands)

All commands that load prompts accept the global `--style <preset>` flag (default: `vertical_9_16_microdrama`).

0. **`split-book`** (`bookbinder.split_book`): Splits a full novel into filmable episode chunks using a sliding-window, verbatim-anchor strategy. Reads `lib/prompting/<style>/book-shrinker.md`. Writes `book-split/s<SS>eNNN.txt`.
0b. **`logic`** (`fixer.fix_novel`): Fixes logic/physics/space continuity bugs in novel text and appends a scene prerequisites table. Accepts `--workers N` for parallel chapter processing. Writes `<novel>_fixed.txt` (or `--output` path).
1. **`styles`** (`stylist.analyze_novel` + `generate_custom_prompts`): Extracts genre/tone/characters; writes `custom_prompts/` overlay files on top of `lib/prompting/<style>/`
2. **`casting`** (`artist.auto_cast_characters`): Identifies characters/locations/objects from text; saves reference JSONs to `ref_thriller/`
2b. **`detail-rooms`** (`artist.detail_room_refs`): Enriches room ref `visual_desc` with named furniture, equipment, and per-character position anchors. Builds a shared `ROOM_VOCABULARY_SCHEMA` (kebab-case anchor labels) then rewrites each view's `visual_desc` via `ROOM_DETAIL_SCHEMA`. Marks `needs_regenerate` on existing PNGs so `refs` re-renders them. Accepts `--force` to re-process rooms already marked `details_applied`. Run after `casting`, before `refs`.
3. **`refs`** (`artist.render_character_refs`): Generates missing reference portrait PNGs
3b. **`remake-room-refs`** (`artist.remake_room_refs`): Splits monolithic Room/Vehicle/Outdoor refs into per-view variants — rooms get 6 views: `View-From-Entrance` / `View-To-Entrance` / `View-From-Left-Wall` / `View-From-Right-Wall` / `View-Center-To-Far` / `View-Center-To-Entrance`; vehicles get `Exterior` / `Interior-From-Entrance` / `Interior-To-Entrance`; outdoor locations get `View-Primary` / `View-Opposite`. All room views use `View-From-Entrance` as the style reference for material/lighting consistency. Renders each view as a separate PNG (empty, no people). Run after `refs` when location consistency matters across all camera angles.
3c. **`room-anchors`** (`artist.run_room_anchors`): Generates `anchor_points` for View-From-Entrance room refs — spatial landmarks (doors, windows, furniture positions) used by the disposition pass.
4. **`screenplay`** (`screenwriter.analyze_scenes_master`): Episodes → 4-pass scene generation → reversal pass; writes `animation_metadata.json`
5. **`scenes`** (`screenwriter.run_scenes_pipeline`): Per-episode keyframe generation via **4-pass pipeline** (Pass 1: architecture, Pass 1A: character state/`visual_ref` selection, Pass 2: visual with To-Entrance mirroring, Pass 3: motion+audio) + reversal pass; upserts into `animation_metadata.json`
5b. **`reverse-refine`** (`screenwriter.process_single_scene`): Reversal pass only on an already-generated raw episode JSON (`animation_episode_scenes_NNN.json`) without re-querying keyframes. Requires `SCENE=N`.
5c. **`disposition`** (`screenwriter.apply_spatial_disposition_pass`): Spatial disposition pass — uses room `anchor_points` to write `visual_disposition` per panel. Groups consecutive panels by shared anchor ref so mixed-ref scenes (e.g., hallway → kitchen) are processed independently per anchor group. Run after `room-anchors`. Requires `SCENE=N` or `all`.
5d. **`spatial-rewrite`** (`screenwriter.apply_spatial_rewrite_pass`): Fixes `visual_start`/`motion_prompt` spatial contradictions using `visual_disposition` written by the disposition pass. Rewrites affected panel fields to be consistent with the resolved anchor layout. Run after `disposition`. Accepts `SCENE=N` or `all` (default). Backs up `animation_metadata.json` before writing.
6. **`consistency`** (`director.run_continuity_pass`): Enriches ref JSONs from scene/location usage; re-aligns `visual_start`/`visual_end`/`lights_and_camera` to approved references. Default `--dry-run` enriches JSONs only — run `make refs` after to regenerate PNGs. Pass `--no-dry-run` to regenerate PNGs in one step.
7. **`storyboard`** (`artist.render_scene_grids` / `render_panels`): Generates grid images or individual panel PNGs
7b. **`panel-by-panel-with-qa`** (`artist.render_panel` + `critic.analyze_panel` inline): Renders each panel one at a time, runs QA, and refines in-place up to `--max-attempts` times. Requires `SCENE=N`; optional `PANEL=N` to target one panel.
7c. **`full-frame`** (`artist.render_full_frame_panel`): Re-renders an existing panel at a wider aspect ratio using the source PNG as reference. Requires `SCENE=N PANEL=N`; optional `AR=16:9` override. Writes `cinematic_render/full_frames/NNN_PP_fullframe_<ar>.png`.
8. **`rebuild-storyboard`**: Rebuilds grid images from current `panels/`
9. **`animation`** (`animation.VeoAnimator` / `GrokAnimator`): Image-to-video per panel
13. **Post-production**: `autocut`, `voiceover`, `tts`, `dub`, `duck`, `srt`, `dynamic-subtitles`
14. **`extra-panel`** (`artist.render_extra_panel`): Generates a micro-panel not in the original screenplay (e.g., for reaction shots between existing panels); writes to `cinematic_render/extra_panels/`
15. **`summary`**: AI-generated context summary of current episode data for use in the next chapter prompt; writes to `chapter_summary.txt`
16. **`suno-prompt`**: Generates a Suno-compatible instrumental music prompt from `animation_episodes.json` metadata; writes `suno_prompt.txt`.
17. **`srt`**: Transcribes a video with Whisper → SRT subtitle file. Accepts `--transcription-cache` to skip re-transcription. Whisper segments are automatically split at sentence boundaries (`.`, `!`, `?`) using word-level timestamps via `_split_on_sentences()`, preventing overly long multi-sentence entries.
18. **`dynamic-subtitles`**: Burns karaoke-style dynamic subtitles onto video (phrase-level or word-level). Supports `--no-whisper` (even word split), `--overlay-only` (transparent .mov/.webm instead of burned video), `--word-srt-output`, `--ass-output`, and `--overlay-fps`.

### Prompt System

| Directory | Purpose |
|-----------|---------|
| `lib/prompting/<style>/` | Primary style-specific prompts + `config.json` (shipped with codebase) |
| `custom_prompts/` | User override files; deep-merged on top of `lib/prompting/<style>/` at runtime |
| `prompts/` | Legacy fallback only (used if `lib/prompting/<style>/` dir is missing) |

`lib/prompting/<style>/` contains: `style.md`, `casting.md`, `scenery.md`, `imagery.md`, `setting.md`, `screenplay.md`, `screenplay_episodes.md`, `qa.md`, `refinement_arc_rule.md`, `config.json`, `book-shrinker.md`, `motion_dynamics.md`, plus the 4-pass scene generation prompts (`pass1_architecture.md`, `pass1a_state.md`, `pass2_visual.md`, `pass3_motion_audio.md`), and episode-type-specific files that vary by style:
- `microdrama`: `episode_type_pov.md`, `episode_type_transition.md`
- `generic`: `episode_type_pov.md`, `episode_type_confrontation.md`, `episode_type_transition.md`
- `long_arc`: `episode_type_arc_open.md`, `episode_type_arc_mid.md`, `episode_type_arc_close.md`, `episode_type_duel.md`, `episode_type_transition.md`

Available built-in styles: `vertical_9_16_microdrama`, `vertical_9_16_long_arc`, `vertical_9_16_generic`

`config.json` controls format type (`single_grid_animation` or `single_grid`), panels per scene, aspect ratio, resolution, animation mode, slicing, dialogue, captions, transitions, and `episodes_count` (series size: 1/2/3/5 for `generic`; arc length for `long_arc`: 2 or 3 episodes per unit).

### Output Structure

```
cinematic_render/
  animation_episodes.json           # Master screenplay breakdown
  animation_episode_scenes_NNN.json # Per-episode raw keyframes
  animation_episode_scenes_NNN_refined.json  # Refined keyframes
  animation_metadata.json           # Final merged scenes (single source of truth)
  quality_report.json               # QA results per panel
  scene_NNN_grid_combined.png       # Full grid image per scene
  panels/
    NNN_PP_static.png               # Sliced panel images (static frame)
    NNN_PP_start.png                # Start frame (for I2V animation)
    NNN_PP_end.png                  # End frame (for I2V animation)
  refined/
    NNN_PP_static_refined.png       # Refined panels (before acceptance)
  clips/
    clip_NNN_PPP.mp4                # Generated animation clips
  cut/
    clip_NNN_PPP_trimmed.mp4        # Auto-trimmed clips (after autocut)
  voiceover/
    scene_NNN_PP_slug.wav           # Generated voiceover audio
  extra_panels/
    NNN_INDEX_static.png            # Extra micro-panels
  full_frames/
    NNN_PP_fullframe_<ar>.png       # Wide-AR re-renders (after full-frame)
chapter_summary.txt                 # AI context summary for next chapter
suno_prompt.txt                     # Suno AI music prompt (after suno-prompt)
voiceover.sh                        # Executable voiceover generation script
ref_thriller/
  character-name.png   # Reference portrait
  character-name.json  # Character visual metadata (includes anchor_points after room-anchors)
  location-View-From-Entrance.png   # 6-point room views (after remake-room-refs)
  location-View-From-Entrance.json
  location-View-To-Entrance.png
  location-View-To-Entrance.json
  location-View-From-Left-Wall.png        # Camera on image-left wall (x=0), looking toward image-right wall
  location-View-From-Left-Wall.json
  location-View-From-Right-Wall.png       # Camera on image-right wall (x=1), looking toward image-left wall
  location-View-From-Right-Wall.json
  location-View-Center-To-Far.png    # Center camera, looking toward far wall
  location-View-Center-To-Far.json
  location-View-Center-To-Entrance.png  # Center camera, looking toward entrance
  location-View-Center-To-Entrance.json
  vehicle-Exterior.png              # Vehicle ref variants
  vehicle-Interior-From-Entrance.png
  vehicle-Interior-To-Entrance.png
  outdoor-location-View-Primary.png   # Outdoor ref variants (facing primary direction)
  outdoor-location-View-Primary.json
  outdoor-location-View-Opposite.png  # Outdoor ref variants (180° turn, left/right swapped)
  outdoor-location-View-Opposite.json
```

### Rate Limiting

Built-in token-bucket rate limiters: 25 RPM for refinement calls, 20 RPM for image generation. Automatic retry with exponential backoff on 500/503 errors (max 3 retries).

### JSON Schemas

Structured output schemas in `lib/core/schemas.py` enforce the AI response format:
- `SCREENPLAY_SCHEMA` — episode-level breakdown (`episode_type`, `chapter_id`, `pov_character` for pov episodes, `visual_continuity_rules`); each episode contains `scenes[]` with per-scene fields: `scene_local_id`, `location`, `panel_count`, `scene_instructions`, `initial_disposition`, and **required** `background_activity` (`crowd_type`, `density` enum: none/sparse/moderate/busy/crowded, `movement`, `focal_plane`) — LLM must always set `density='none'` for private/empty locations (apartment, interrogation room, abandoned warehouse) and a non-none density for public/semi-public (café, bank, street); Pass 2 renders background figures in MS/WS panels when density≠none; Pass 3 adds ambient motion layer
- `SCENE_SCHEMA` — scene-level keyframes: `camera_master`/`lighting_master` per scene, `scene_trajectories` (per-character goal/obstacle/tactic/arc), full panel fields (`motion_intent`, `motion_action`, motion, reversal, sound, `voiceover_settings`, `voiceover_timing`, transitions, `state`, `drama_requirements`)
- `PANEL_STATE_SCHEMA` — per-panel spatial snapshot: actors (position, pose, `chest_direction`, `gaze_target`, `motion_action`, `in_frame`, `visual_ref`), props, `complete_disposition`, `anchor_refs`, environment. Produced by Pass 1A; consumed by Pass 2.
- `DRAMA_REQUIREMENTS_SCHEMA` — cinematic shot instructions per panel: `shot_scale`, `camera_angle`, `composition_style`, `focus_priority`, `movement_intent`, `narrative_vibe`. Produced by **Pass 1**; consumed by Pass 1A (`in_frame` derivation), Pass 1B (camera axis / view selection via `focus_priority.primary_target`), and Pass 2 (projection).
- `CHARACTER_SCHEMA` — reference descriptions; characters support `variations` (list of variation ref slugs, e.g. `['Alisa-Gown']`), `character_ref` (parent ref name for variation entries), `context` (scene trigger for when variation applies)
- `REVERSAL_SCHEMA` — produced by the reversal pass: `panel_index`, `motion_prompt_reversed`, and `visual_start_explicit` (explicit frame description for the reversed start pose)
- `SCENE_REWRITE_SCHEMA` — used by the continuity enforcer to align `visual_start`, `visual_end`, and `lights_and_camera` to approved refs
- `ROOM_VOCABULARY_SCHEMA` — produced by `detail-rooms` pass 1: `named_positions[]` with kebab-case `id` and view-neutral `description` (furniture type, exact room location, orientation, items); shared across all views of a room
- `ROOM_DETAIL_SCHEMA` — produced by `detail-rooms` pass 2: `enriched_visual_desc` string rewriting a single camera view's `visual_desc` to incorporate all named positions from `ROOM_VOCABULARY_SCHEMA`
- `bookbinder._WINDOW_SCHEMA` — split-point anchors returned by `split-book` LLM call

### Code Style Guidelines

Code must be idiomatic, concise, precise and terse, self-documenting.

## Протокол проверки: «ПРИДИРА»
- Используй этот блок вопросов перед выкладкой:
  - **КАКОГО ХУЯ? (Причинность/данные)** — процитируй участок кода; отметь отсутствие валидации входа, магические константы, неучтённые edge-case, скрытые зависимости. Решение: валидируй URL/ID, задокументируй константы, добавь тест.
  - **НАХУЯ? (Мотивация решений)** — процитируй выбор алгоритма/флага; спроси, оправдана ли сложность и дефолты. Решение: обоснуй в комментарии/PR или упростить.
  - **СХУЯЛИ? (Обоснованность возможностей)** — процитируй доступ к ресурсу/TTL/контракту; убедись, что соблюдены права, схемы, лимиты. Решение: навеси проверку, явный API/фича-флаг, соблюдай договорённости.
  - **ДАНУНАХУЙ (Deus Ex Machina)** — процитируй «всё сработало» без ошибок; отметь отсутствие таймаутов/ретраев/фоллбеков/логирования. Решение: добавить таймауты, ретраи, деградацию, логировать и всплывать ошибки.
- Для каждой претензии: Цитата → Претензия → Решение. Просто жалобы без поправки не принимаются.

## Протокол «Говно, переделывай»
1. Перепроверь свой ответ, пойми, почему он «говно», выпиши все замечания.
2. Переделай ответ, перепроверь, почему он снова «говно».
3. Выдай улучшенный ответ, ещё раз проверь, почему он «говно».
4. Устрани все замечания, выдай финальный ответ.

Протоколы "ПРИДИРА" и "Говно, переделывай" использовать всегда
