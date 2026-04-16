# Vertical Microdrama AI Factory

**AI-Microdrama-Factory** is an automated Python pipeline for converting text stories (books, scripts) into cinematic videos. The project utilizes advanced models—Google Gemini, and Grok Imagine or Veo to create scripts, generate characters, render frames, and animate them. Based on **AI-Story-To-Movie** code.

```bash
INPUT(Story.TXT) | OUTPUT(Movie.MP4)

```

## ACHTUNG / DISCLAIMER

WARNING DISCLAIMER #1: This is an experimental pipeline, not a magic "Make me an Oscar-winning movie while I drink my coffee" red button. Be prepared for manual edits, re-generations, and unexpected API costs.

WARNING DISCLAIMER #2: The project works, but it requires time, patience, and money for Veo/Gemini quotas. If you want a movie "at the snap of a finger" — this isn't for you, go to Netflix.

WARNING DISCLAIMER #3: If the project doesn't work for you, then "Keep sawing, Shura, keep sawing" (Russian idiom meaning: keep grinding/debugging until it works).

WARNING DISCLAIMER #4: Project Status: Proof of Concept. Not maintained. API compatibility not guaranteed.

---

## Key Features

* **Style Master:** Automatically determines the genre, atmosphere, and visual style based on the text of the story.
* **Auto-Casting:** Identifies key characters, creates detailed descriptions for them, and generates reference images to maintain facial consistency across different scenes.
* **Cinematic Storyboarding:** Breaks the text into scenes and panels, generating `Start` (action beginning) and `End` (result) frame pairs for smooth animation.
* **Video Generation (Google Veo):** Turns static frame pairs into 4-8 second video clips with high temporal consistency.
* **Smart Dubbing:** Creates an audio track with role distribution (narrator, characters) and SFX (sound effects) generation via ElevenLabs.
* **Flexible Styling:** Supports presets: Realism, Anime, Comic Book, Graphic Novel, etc.

-

Serialized novel text in, AI-first short-form video assets out.

```
Novel -> screenplay JSON -> scene keyframes -> grid/panel renders -> clips -> autocut/audio post
```

## What This Repository Contains

- End-to-end CLI pipeline in `cli.py` with Makefile wrappers.
- Style-specific prompt system in `lib/prompting/<style>/`, with optional `custom_prompts/` overlay.
- Rendering and production outputs in `cinematic_render/`.
- Character/location/object reference cards and portraits in `ref_thriller/`.

Core pipeline stages:

0. `split-book`: split a full novel into filmable episode chunks → `book-split/s<SS>eNNN.txt`.
0b. `logic`: fix logic/physics/space continuity bugs in novel text + generate scene prerequisites appendix → `<novel>_fixed.txt`.
1. `styles`: analyze novel + generate `custom_prompts/` overlay on top of `lib/prompting/<style>/`.
2. `casting`: detect references and write `ref_thriller/*.json`.
2b. `detail-rooms`: enrich room ref `visual_desc` with named furniture, equipment, and per-character anchors. Marks existing PNGs as `needs_regenerate` — run `refs` after. Accepts `FORCE=1` to re-process rooms already marked `details_applied`.
3. `refs`: render missing reference portraits `ref_thriller/*.png`.
3b. `remake-room-refs`: split monolithic Room/Vehicle/Outdoor refs into per-view variants (View-From-Entrance/View-To-Entrance, Exterior/Interior-*, View-Primary/View-Opposite) and render each as a separate PNG. New projects generate multi-view refs directly from `casting`; run this only to migrate old monolithic refs.
3c. `room-anchors`: generate spatial `anchor_points` for View-From-Entrance room refs (doors, windows, furniture landmarks used by the disposition pass).
4. `screenplay`: generate episodes/scenes/reversal pass and `animation_metadata.json`.
5. `scenes`: generate keyframes for specific episode(s) via **4-pass pipeline** (architecture → state/`visual_ref` → visual → motion_audio) + reversal pass; upserts into metadata.
5b. `reverse-refine`: re-run reversal pass only on an existing raw episode JSON without re-querying keyframes. Requires `SCENE=N`.
5c. `disposition`: spatial disposition pass — writes `visual_disposition` per panel using room `anchor_points`. Handles panels with mixed room refs within a single scene by grouping consecutive panels that share the same anchor. Requires `SCENE=N` or `all`.
5d. `spatial-rewrite`: fixes `visual_start`/`motion_prompt` spatial contradictions using `visual_disposition` (run after `disposition`). Accepts `SCENE=N` or `all`. Backs up `animation_metadata.json` before writing.
6. `consistency`: continuity enforcer — enrich ref JSONs from scene/location usage, re-align panel visuals to approved refs. Default: `--dry-run` (JSON only); use `--no-dry-run` or follow with `make refs` to regenerate PNGs.
7. `storyboard`: render scene grids or individual panel images.
7b. `panel-by-panel-with-qa`: render each panel one at a time with inline QA + refinement loop (up to `--max-attempts` retries). Requires `SCENE=N`.
7c. `full-frame`: re-render an existing panel at a wider aspect ratio using the source PNG as reference. Requires `SCENE=N PANEL=N`; optional `AR=16:9`. Writes `cinematic_render/full_frames/NNN_PP_fullframe_<ar>.png`.
8. `rebuild-storyboard`: rebuild scene grid images from current `panels/`.
9. `animation`: generate clips with `veo` or `grok`.
10. `autocut`, `voiceover`, `tts`, `dub`, `duck`: post-production helpers.
11. `srt`: transcribe video → SRT subtitle file (Whisper). Segments are auto-split at sentence boundaries (`.`, `!`, `?`) using word-level timestamps, producing shorter and more readable entries.
12. `dynamic-subtitles`: burn karaoke-style subtitles; word-level or phrase-level timing; optional transparent overlay output.
13. `suno-prompt`: generate Suno instrumental music prompt from episode metadata → `suno_prompt.txt`.
14. `extra-panel`: generate a micro-panel not in the original screenplay → `cinematic_render/extra_panels/`.
15. `summary`: AI-generated context summary of episode data for the next chapter → `chapter_summary.txt`.

## Install

```bash
pip install -r requirements.txt
```

Optional runtime dependencies (needed only for specific commands):

- `pydub`, `moviepy`, `faster-whisper` for `dub`/`duck`.
- `elevenlabs` SDK for `tts sfx`.
- System `ffmpeg` binary for `autocut` (and generally useful for audio/video workflows).

## Docker

The image bakes in the code; per-series data (`custom_prompts/`, `ref_thriller/`, `cinematic_render/`, novel `.txt` files) lives outside and is mounted at runtime. One image, many series.

**Build the image** (once, from repo root):

```bash
docker build -t ai-microdrama-factory:latest .
```

**Per-series layout:**

```
my-series/
  docker-compose.yml   # copy from repo root
  .env                 # copy .env.example, fill in API keys
  custom_prompts/
  ref_thriller/
  cinematic_render/
  s01e01.txt
```

**Run CLI commands** (from series dir):

```bash
# via compose
docker compose run --rm factory scenes --llm gemini SCENE=1

# or directly
docker run --rm -v $(pwd):/project --env-file .env ai-microdrama-factory:latest scenes --llm gemini SCENE=1
```

**Run the web viewer:**

```bash
docker compose up webserver
# → http://localhost:5005/web/index.html
```

## Environment Variables

Main:

- `OPENROUTER_API_KEY`: required for default `--llm openrouter` text/image pipeline.
- `IMG_AI_API_KEY` or `GOOGLE_API_KEY`: required for Gemini-backed tasks (Veo animation, Gemini LLM backend, TTS, dubbing).
- `XAI_API_KEY`: required for `animation grok`.
- `ELEVEN_API_KEY`: required for `tts sfx`.

Optional overrides:

- `AI_TEXT_MODEL` (default: `gemini-2.5-pro`)
- `AI_IMAGE_MODEL` (default: `google/gemini-3-pro-image-preview`)
- `AI_GEMINI_MODEL` (default: `gemini-2.5-flash`)
- `AI_CONCURRENCY` (default: `10`) — text/LLM thread pool workers
- `AI_IMAGE_CONCURRENCY` (default: `5`) — image generation thread pool workers
- `AI_LOG_LEVEL` (default: `INFO`)
- `AI_ASPECT_RATIO` — override image aspect ratio (e.g. `9:16`)
- `AI_IMAGE_SIZE` — override image resolution (e.g. `2K`)
- `AI_REF_ASPECT_RATIO` — override reference portrait aspect ratio
- `AI_VIDEO_TIMEOUT` (default: `600`) — Veo polling hard limit in seconds
- `TARGET_LANGUAGE` (default: `English`) — dialogue/voiceover/caption language for generated text

Note: `make init` validates `OPENROUTER_API_KEY`.

## Quick Start

```bash
# 0) (optional) Split full novel into episode chunks
make split-book BOOK=fullbook.txt STYLE=vertical_9_16_microdrama SEASON=1

# 1) Validate env and create output directories
make init

# 2) (optional) Generate custom_prompts/ overrides for the chosen style
make styles NOVEL=s01e01.txt STYLE=vertical_9_16_microdrama

# 3) Create/update reference cards
make casting NOVEL=s01e01.txt

# 3b) Enrich room refs with named furniture/equipment/anchor positions
make detail-rooms NOVEL=s01e01.txt

# 4) Render missing reference portraits
make refs

# 5) Build screenplay + scene keyframes + metadata
make screenplay NOVEL=s01e01.txt

# 6) Optional continuity pass (updates animation_metadata.json in-place)
make consistency

# 7) Render scene grids (or panel images via PANEL=<n>)
make storyboard SCENE=all PANEL=all

# 8) Rebuild scene grids if needed
make rebuild-storyboard SCENE=all

# 9) Animate clips
make animation PROVIDER=veo SCENE=all PANEL=all
```

## Make Targets

Use `make help` to list all targets. `make draft` runs the full pipeline shortcut: `casting → detail-rooms → refs → room-anchors → remake-room-refs → screenplay → disposition → spatial-rewrite → storyboard`. Current targets:

- `init`, `workdirs`
- `split-book`, `logic`, `styles`, `casting`, `detail-rooms`, `refs`, `remake-room-refs`, `room-anchors`
- `screenplay`, `scenes`, `reverse-refine`, `disposition`, `spatial-rewrite`, `consistency`
- `storyboard`, `panel-by-panel-with-qa`, `full-frame`, `rebuild-storyboard`, `animation`
- `autocut`, `voiceover`, `imgedit`, `tts`, `dub`, `duck`, `srt`, `dynamic-subtitles`
- `suno-prompt`, `summary`, `draft`, `webserver`

Important defaults from `Makefile`:

```makefile
NOVEL    ?= s01e03.txt
BOOK     ?= $(NOVEL)
BOOK_OUT ?= book-split
SEASON   ?= 1
STYLE    ?= vertical_9_16_microdrama
SCENE    ?= all
PANEL    ?= all
PROVIDER ?= veo
LLM      ?= openrouter
FRAME    ?= both
```

## CLI Reference

```bash
python cli.py --help
python cli.py --llm {openrouter|gemini|grok|debug} <command> ...
```

`--llm debug` uses LogDebugLLM — logs all prompts/responses to disk without calling any API (useful for testing prompt structure offline).

Commands (all accept `--style <preset>` where relevant; default: `vertical_9_16_microdrama`):

- `init`
- `split-book <novel> [--output-dir book-split] [--season 1]`
- `logic <novel> [--output path] [--workers N]`
- `styles <novel> --style <preset>`
- `casting <novel>`
- `detail-rooms <novel> [--force]`
- `refs`
- `remake-room-refs`
- `room-anchors`
- `screenplay <novel>`
- `scenes [scene|all]`
- `reverse-refine <scene>`
- `disposition [scene|all]`
- `spatial-rewrite [scene|all]`
- `consistency [--dry-run|--no-dry-run]`
- `storyboard [scene|all] [panel|all]`
- `rebuild-storyboard [scene|all]`
- `panel-by-panel-with-qa <scene> [panel|all] [--threshold N] [--max-attempts N]`
- `full-frame --scene N --panel N [--aspect-ratio 16:9]`
- `animation <veo|grok> [scene|all] [panel|all]`
- `autocut --json <metadata.json> --clips-dir <dir> --out-dir <dir> [--min-fidelity N]`
- `voiceover [--out-dir <dir>] [--output <script.sh>]`
- `imgedit <output> "<instruction>" <image> [ref_image ...]`
- `tts speech "<voice/tone text>" <output>`
- `tts sfx "<prompt>" <duration> <output>`
- `dub <video.mp4> <output.mp3> [context.txt] [--plan-cache FILE] [--transcription-cache FILE]`
- `duck <video.mp4> <dubbed.mp3> <output.mp3>`
- `srt <video.mp4> <output.srt> [--transcription-cache FILE]`
- `dynamic-subtitles <input> <output> --srt <file> [--no-whisper] [--language LANG] [--font-size N] [--margin-v N] [--word-srt-output FILE] [--ass-output FILE] [--overlay-only] [--overlay-fps N]`
- `suno-prompt`
- `extra-panel <narrative.txt> --scene N --index N_M`
- `summary <novel> [--output chapter_summary.txt]`

## Style Presets (`--style`)

Built-in styles in `lib/prompting/`:

- `vertical_9_16_microdrama` (single_grid_animation, 9 panels, 9:16) — default. Optimized for DramaBox/ReelShort serialized drama. Single POV throughout; episodes grouped into 3-episode series (open → mid × N → close). Episode types: `pov`, `transition`. Each episode is one hook-to-cliffhanger unit.
- `vertical_9_16_long_arc` (single_grid_animation, 9 panels, 9:16). Episodes grouped into arc units spanning 2 or 3 episodes (controlled by `episodes_count` in `config.json`). Each arc unit runs arc_open → [arc_mid] → arc_close as a single hook-to-cliffhanger.
- `vertical_9_16_generic` (single_grid_animation, 9 panels, 9:16). Style-agnostic fallback. Single POV, configurable series size (1/2/3/5 episodes via `episodes_count`). Use as a neutral starting point for genres not served by the other presets.

The `--style` flag is a global CLI option, not a subcommand argument. It selects the prompt directory and config. `custom_prompts/` files (if present) overlay on top.

## Outputs

Primary generated files:

- `cinematic_render/animation_episodes.json`
- `cinematic_render/animation_episode_scenes_NNN.json`
- `cinematic_render/animation_episode_scenes_NNN_refined.json`
- `cinematic_render/animation_metadata.json`
- `cinematic_render/scene_NNN_grid_combined.png`
- `cinematic_render/panels/NNN_PP_{static|start|end}.png`
- `cinematic_render/refined/*_refined.png`
- `cinematic_render/clips/clip_*.mp4`
- `cinematic_render/cut/clip_*_cut.mp4` + JSON reports (after `autocut`)
- `cinematic_render/voiceover/*.wav` + `voiceover.sh` (after `voiceover`)
- `cinematic_render/extra_panels/NNN_INDEX_static.png` (after `extra-panel`)
- `cinematic_render/full_frames/NNN_PP_fullframe_<ar>.png` (after `full-frame`)
- `chapter_summary.txt` (after `summary`)
- `suno_prompt.txt` (after `suno-prompt`)

Reference artifacts:

- `ref_thriller/*.json`
- `ref_thriller/*.png`
- `ref_thriller/*-View-From-Entrance.{json,png}` — room refs (after `casting` or `remake-room-refs`)
- `ref_thriller/*-View-To-Entrance.{json,png}` — room refs
- `ref_thriller/*-Exterior.{json,png}`, `*-Interior-From-Entrance.{json,png}`, `*-Interior-To-Entrance.{json,png}` — vehicle refs
- `ref_thriller/*-View-Primary.{json,png}`, `*-View-Opposite.{json,png}` — outdoor refs

## Project Layout

```text
cli.py
Makefile
lib/
  core/        # project/env/prompts loader/schemas/puppet engine
  llm/         # OpenRouter, Gemini, Grok, Debug adapters
  prompting/   # style preset directories (vertical_9_16_microdrama/, vertical_9_16_long_arc/, vertical_9_16_generic/)
  studio/      # stylist/screenwriter/artist/critic/director/editor/cutter/retoucher/bookbinder
  commands/    # argparse command registration (setup/screenplay/storyboard/animation/audio)
  animation/   # Veo and Grok animators
  audio/       # tts/dubbing/ducking/dynamic_subtitles
prompts/       # legacy fallback prompts (used only if lib/prompting/<style>/ is missing)
custom_prompts/ # optional user override files (overlay on top of lib/prompting/<style>/)
book-split/    # episode chunks written by split-book
cinematic_render/ # all pipeline outputs
ref_thriller/  # character/location reference cards (*.json + *.png)
```

## Claude Slash Commands

Manual/iterative flow also exists in `.claude/commands/`:

- `/analyze-novel`
- `/customize-style`
- `/cast-characters`
- `/render-references`
- `/write-screenplay`
- `/generate-keyframes`
- `/refine-scene`
- `/reversal-pass`
- `/make-summary`

Note: `split-book`, `extra-panel` are Python CLI-only (no slash command equivalent).

---

**License:** WTFPL
**(c) 2026, E.Z. AI-Story-to-Movie Project**
