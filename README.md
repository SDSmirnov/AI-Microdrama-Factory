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
1. `styles`: analyze novel + generate `custom_prompts/` overlay on top of `lib/prompting/<style>/`.
2. `casting`: detect references and write `ref_thriller/*.json`.
3. `refs`: render missing reference portraits `ref_thriller/*.png`.
4. `screenplay`: generate episodes/scenes/reversal pass and `animation_metadata.json`.
5. `scenes`: generate keyframes for specific episode(s) with cross-episode continuity rules and upsert into metadata.
6. `consistency`: continuity enforcer — enrich ref JSONs from scene/location usage, re-align panel visuals to approved refs. Default: `--dry-run` (JSON only); use `--no-dry-run` or follow with `make refs` to regenerate PNGs.
7. `storyboard`: render scene grids or individual panel images.
8. `qa`: run visual fidelity checks and produce `quality_report.json`.
9. `apply-qa`: auto-refine all panels flagged by QA.
10. `accept-qa`: promote refined panels into `panels/`, backup originals.
11. `rebuild-storyboard`: rebuild scene grid images from current `panels/`.
12. `refinement`: manually regenerate a specific panel frame.
13. `animation`: generate clips with `veo` or `grok`.
14. `autocut`, `voiceover`, `tts`, `dub`, `duck`: post-production helpers.
15. `extra-panel`: generate a micro-panel not in the original screenplay → `cinematic_render/extra_panels/`.
16. `summary`: AI-generated context summary of episode data for the next chapter → `chapter_summary.txt`.

## Install

```bash
pip install -r requirements.txt
```

Optional runtime dependencies (needed only for specific commands):

- `pydub`, `moviepy`, `faster-whisper` for `dub`/`duck`.
- `elevenlabs` SDK for `tts sfx`.
- System `ffmpeg` binary for `autocut` (and generally useful for audio/video workflows).

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

# 4) Render missing reference portraits
make refs

# 5) Build screenplay + scene keyframes + metadata
make screenplay NOVEL=s01e01.txt

# 6) Optional continuity pass (updates animation_metadata.json in-place)
make consistency

# 7) Render scene grids (or panel images via PANEL=<n>)
make storyboard SCENE=all PANEL=all

# 8) Run QA
make qa SCENE=all

# 9) Auto-refine all panels flagged by QA
make apply-qa SCENE=all

# 10) Accept refined panels (promotes to panels/, backs up originals)
make accept-qa

# 11) Rebuild scene grids from updated panels/
make rebuild-storyboard SCENE=all

# 12) Manually refine a specific panel if needed
make refinement SCENE=1 PANEL=3

# 13) Animate clips
make animation PROVIDER=veo SCENE=all PANEL=all
```

## Make Targets

Use `make help` to list all targets. Current targets:

- `init`, `workdirs`
- `split-book`, `styles`, `casting`, `refs`, `screenplay`, `scenes`, `consistency`
- `storyboard`, `qa`, `apply-qa`, `accept-qa`, `rebuild-storyboard`, `refinement`, `animation`
- `autocut`, `voiceover`, `imgedit`, `tts`, `dub`, `duck`
- `summary`, `webserver`

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
- `styles <novel> --style <preset>`
- `casting <novel>`
- `refs`
- `screenplay <novel>`
- `scenes [scene|all]`
- `consistency [--dry-run|--no-dry-run]`
- `storyboard [scene|all] [panel|all]`
- `qa [--scene N ...] [--panel N ...] [--threshold N]`
- `apply-qa [--scene N] [--frame start|end|static|both]`
- `accept-qa`
- `rebuild-storyboard [scene|all]`
- `refinement <scene_id> <panel_id> [--frame start|end|static|both]`
- `animation <veo|grok> [scene|all] [panel|all]`
- `autocut --json <metadata.json> --clips-dir <dir> --out-dir <dir> [--min-fidelity N]`
- `voiceover [--out-dir <dir>] [--output <script.sh>]`
- `imgedit <output> "<instruction>" <image> [ref_image ...]`
- `tts speech "<voice/tone text>" <output>`
- `tts sfx "<prompt>" <duration> <output>`
- `dub <video.mp4> <output.mp3> [context.txt]`
- `duck <video.mp4> <dubbed.mp3> <output.mp3>`
- `extra-panel <narrative.txt> --scene N --index N_M`
- `summary <novel> [--output chapter_summary.txt]`

## Style Presets (`--style`)

Built-in styles in `lib/prompting/`:

- `vertical_9_16_microdrama` (single_grid_animation, 9 panels, 9:16) — default

The `--style` flag is a global CLI option, not a subcommand argument. It selects the prompt directory and config. `custom_prompts/` files (if present) overlay on top.

## Outputs

Primary generated files:

- `cinematic_render/animation_episodes.json`
- `cinematic_render/animation_episode_scenes_NNN.json`
- `cinematic_render/animation_episode_scenes_NNN_refined.json`
- `cinematic_render/animation_metadata.json`
- `cinematic_render/image_prompts/` (per-scene image prompts)
- `cinematic_render/scene_NNN_grid_combined.png`
- `cinematic_render/panels/NNN_PP_{static|start|end}.png`
- `cinematic_render/quality_report.json`
- `cinematic_render/refined/*_refined.png`
- `cinematic_render/clips/clip_*.mp4`
- `cinematic_render/cut/clip_*_cut.mp4` + JSON reports (after `autocut`)
- `cinematic_render/voiceover/*.wav` + `voiceover.sh` (after `voiceover`)
- `cinematic_render/extra_panels/NNN_INDEX_static.png` (after `extra-panel`)
- `chapter_summary.txt` (after `summary`)

Reference artifacts:

- `ref_thriller/*.json`
- `ref_thriller/*.png`

## Project Layout

```text
cli.py
Makefile
lib/
  core/        # project/env/prompts loader/schemas
  llm/         # OpenRouter, Gemini, Grok, Debug adapters
  prompting/   # style preset directories (vertical_9_16_microdrama/)
  studio/      # stylist/screenwriter/artist/critic/director/editor/cutter/retoucher/bookbinder
  commands/    # argparse command registration (setup/screenplay/storyboard/animation/audio)
  animation/   # Veo and Grok animators
  audio/       # tts/dubbing/ducking
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
