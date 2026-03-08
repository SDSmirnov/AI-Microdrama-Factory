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
export AI_CONCURRENCY="10"                             # thread pool workers
export AI_SEED="42"                                    # image generation seed (openrouter)
export AI_LOG_LEVEL="DEBUG"                            # logging verbosity
export AI_ASPECT_RATIO="9:16"                          # image aspect ratio override (default: per config/preset)
export AI_IMAGE_SIZE="2K"                              # image resolution override (default: per config/preset)
export AI_REF_ASPECT_RATIO="9:16"                      # reference portrait aspect ratio override
```

## Manual Workflow (Claude Code Skills)

The full pipeline is available as Claude Code slash commands in `.claude/commands/`. Run these in sequence instead of (or alongside) the Python scripts:

```bash
# Step 1: Analyze the novel — extracts metadata, recommends a visual style
/analyze-novel s01e01.txt

# Step 1b (optional): Generate style-adapted custom_prompts/ for a chosen preset
# Presets: vertical_microdrama | realistic_movie | anime | comic_book | graphic_novel | watchmen_style
/customize-style s01e01.txt realistic_movie
# → writes all 6 files to custom_prompts/ (style, casting, scenery, imagery, setting, config)
# → subsequent skills automatically prefer custom_prompts/ over prompts/

# Step 2: Generate character/location reference descriptions + image gen prompts
/cast-characters s01e01.txt

# Step 2b: Render missing reference portraits (runs Python — requires API key)
/render-references

# Step 3: Break the novel into ~30 episodes with screenplay instructions
/write-screenplay s01e01.txt
# → writes cinematic_render/animation_episodes.json

# Step 4: Generate panel keyframes for a specific episode
/generate-keyframes 1
# → writes cinematic_render/animation_episode_scenes_001.json

# Step 5: Refine visual/motion descriptions for precision
/refine-scene cinematic_render/animation_episode_scenes_001.json
# → writes cinematic_render/animation_episode_scenes_001_refined.json

# Step 6: Generate reversed motion prompts for is_reversed panels
/reversal-pass cinematic_render/animation_episode_scenes_001_refined.json
# → updates the file in-place
```

Each skill reads `custom_prompts/` if available, falls back to `prompts/`. Steps 4–6 repeat per episode. Steps 4–6 are what the Python script automates in parallel; running them manually gives full control over individual episodes.

**Note**: Actual image/grid rendering still requires the Python script — Claude cannot generate images directly.

## Architecture

### Entry Point

**`cli.py`** — Single CLI with 20+ subcommands covering the full pipeline from text to video.
Uses `--llm {openrouter|gemini|grok|debug}` to select the backend. The `debug` backend (LogDebugLLM) logs all prompts/responses to disk without calling any API, useful for offline testing.

### Library Structure (`lib/`)

```
lib/
  core/        # Project config, path constants, prompts loader, JSON schemas, grid utils
  llm/         # BaseLLM ABC + backends: GeminiLLM, OpenRouterLLM, GrokLLM, LogDebugLLM
  studio/      # Production pipeline modules:
    stylist.py      — novel analysis + custom_prompts/ generation
    screenwriter.py — episode/scene/reversal AI passes
    artist.py       — casting, reference rendering, grid/panel image generation, slicing
    critic.py       — QA gate: fidelity/consistency scoring per panel
    director.py     — continuity enforcer: enriches refs, aligns scene prompts
    editor.py       — panel refinement using original + reference images
    cutter.py       — autocut: AI-trim animation clips
    retoucher.py    — image editing via LLM
  animation/   # Veo (Google) and Grok animators
  audio/       # TTS (Gemini/OpenRouter), SFX (ElevenLabs), dubbing (Whisper→TTS), ducking
```

### Pipeline Stages (via `cli.py` subcommands)

1. **`styles`** (`stylist.analyze_novel` + `generate_custom_prompts`): Extracts genre/tone/characters; writes style-adapted prompts to `custom_prompts/`
2. **`casting`** (`artist.auto_cast_characters`): Identifies characters/locations/objects from text; saves reference JSONs to `ref_thriller/`
3. **`refs`** (`artist.render_character_refs`): Generates missing reference portrait PNGs
4. **`screenplay`** (`screenwriter.analyze_scenes_master`): Episodes → scenes → refinement → reversal pass; writes `animation_metadata.json`
5. **`scenes`** (`screenwriter.run_scenes_pipeline`): Per-episode keyframe generation with cross-episode continuity rules; upserts into `animation_metadata.json`
6. **`consistency`** (`director.run_continuity_pass`): Enriches ref JSONs from scene/location usage; re-aligns `visual_start`/`visual_end`/`lights_and_camera` to approved references. Default `--dry-run` enriches JSONs only — run `make refs` after to regenerate PNGs. Pass `--no-dry-run` to regenerate PNGs in one step.
7. **`storyboard`** (`artist.render_scene_grids` / `render_panels`): Generates grid images or individual panel PNGs
8. **`qa`** (`critic.run_quality_gate`): Visual fidelity/consistency scoring; writes `quality_report.json`
9. **`apply-qa`** / **`refinement`** (`editor.refine_panel`): Regenerates flagged panels using reference images
10. **`accept-qa`**: Promotes refined PNGs into `panels/`, backs up originals
11. **`rebuild-storyboard`**: Rebuilds grid images from current `panels/`
12. **`animation`** (`animation.VeoAnimator` / `GrokAnimator`): Image-to-video per panel
13. **Post-production**: `autocut`, `voiceover`, `tts`, `dub`, `duck`
14. **`extra-panel`** (`artist.render_extra_panel`): Generates a micro-panel not in the original screenplay (e.g., for reaction shots between existing panels); writes to `cinematic_render/extra_panels/`
15. **`summary`**: AI-generated context summary of current episode data for use in the next chapter prompt; writes to `chapter_summary.txt`

### Prompt System

| Directory | Purpose |
|-----------|---------|
| `prompts/` | Base templates with `{{placeholder}}` syntax |
| `custom_prompts/` | Style-adapted versions, generated by `cli.py styles` |

Each directory contains: `style.md`, `casting.md`, `scenery.md`, `imagery.md`, `setting.md`, `config.json`

`config.json` controls format type (`single_grid_animation` or `single_grid`), panels per scene, aspect ratio, resolution, animation mode, slicing, dialogue, and captions.

### Output Structure

```
cinematic_render/
  animation_episodes.json           # Master screenplay breakdown
  animation_episode_scenes_NNN.json # Per-episode raw keyframes
  animation_episode_scenes_NNN_refined.json  # Refined keyframes
  animation_metadata.json           # Final merged scenes
  scene_NNN_grid_combined.png       # Full grid image per scene
  panels/
    NNN_PP_static.png                    # Sliced panel images
  extra_panels/
    NNN_INDEX_static.png                 # Extra micro-panels
chapter_summary.txt                 # AI context summary for next chapter
ref_thriller/
  character-name.png   # Reference portrait
  character-name.json  # Character visual metadata
```

### Rate Limiting

Built-in token-bucket rate limiters: 25 RPM for refinement calls, 20 RPM for image generation. Automatic retry with exponential backoff on 500/503 errors (max 3 retries).

### JSON Schemas

Four structured output schemas enforce the AI response format:
- `SCREENPLAY_SCHEMA` — episode-level breakdown with continuity rules
- `SCENE_SCHEMA` — scene-level keyframes including `camera_master` / `lighting_master` per scene and full panel fields (motion, reversal, sound, transitions)
- `CHARACTER_SCHEMA` — reference character/location/object descriptions
- `SCENE_REWRITE_SCHEMA` — used by the continuity enforcer to align `visual_start`, `visual_end`, and `lights_and_camera` to approved refs

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
