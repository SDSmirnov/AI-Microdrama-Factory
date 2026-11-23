# Vertical Microdrama AI Factory

**AI-Microdrama-Factory** is a Python pipeline that turns a text story (a book, a script) into a cinematic vertical video. Google Gemini writes the screenplay and designs characters and places, an image model renders the frames, and Veo or Grok Imagine animates them. Based on the **AI-Story-To-Movie** code.

```
INPUT(Story.TXT) | OUTPUT(Movie.MP4)
```

## ACHTUNG / DISCLAIMER

WARNING DISCLAIMER #1: This is an experimental pipeline, not a magic "Make me an Oscar-winning movie while I drink my coffee" red button. Be prepared for manual edits, re-generations, and unexpected API costs.

WARNING DISCLAIMER #2: The project works, but it requires time, patience, and money for Veo/Gemini quotas. If you want a movie "at the snap of a finger" — this isn't for you, go to Netflix.

WARNING DISCLAIMER #3: If the project doesn't work for you, then "Keep sawing, Shura, keep sawing" (Russian idiom meaning: keep grinding/debugging until it works).

WARNING DISCLAIMER #4: Project Status: Proof of Concept. Not maintained. API compatibility not guaranteed.

---

## Key Features

* **Book preparation:** splits a full novel into filmable episodes, fixes physical and logical errors in the prose, and builds a story bible of every character, place and object with how each one looks at each point of the story.
* **Style Master:** picks the genre, atmosphere and visual style from the text.
* **Auto-Casting:** creates reference cards and images for characters, rooms, vehicles and outdoor places, so faces and sets stay the same from shot to shot.
* **Consistent sets:** rooms get a floor plan first, then views from several camera positions, each checked by an AI judge against the views before it.
* **Cinematic Storyboarding:** breaks the text into scenes and panels, with start and end frames for animation.
* **Spatial Blocking:** who sits or stands where is tracked as data, not prose. Code works out where each person appears in the frame and draws a 3D mannequin sketch of the shot; a continuity ledger flags unexplained moves, seat swaps and wardrobe changes.
* **Video Generation:** animates frames with Google Veo, Grok (xAI SDK) or Grok via OpenRouter.
* **Sound:** voiceover and dubbing with distinct voices, ElevenLabs sound effects, karaoke subtitles, Suno music prompts.
* **Flexible Styling:** five built-in style presets; a style can extend another, and a project can override any prompt in `custom_prompts/`.

## How it works

```
full book ──► episodes ──► fixed prose ──► story bible
                                              │
          reference cards + images ◄──────────┘   (characters, rooms, vehicles, places)
                    │
                    ▼
     screenplay: episodes → scenes → panels   (cinematic_render/animation_metadata.json)
                    │
                    ▼
     panel images (checked by AI QA) ──► video clips ──► cut, voice, subtitles
```

Every step is a command of `cli.py`, and most have a `make` target. The book steps cache their LLM calls, and finished refs, room views and panels are skipped on re-runs. Internals (terms, stages, modules) are described in [CLAUDE.md](CLAUDE.md).

## Install

```bash
pip install -r requirements.txt
```

This includes the audio libraries and PyVista. System tools, needed only by some commands:

| Tool | Used by |
|------|---------|
| `ffmpeg` | `autocut`, audio/video work |
| `blender` on `PATH` (default 3D engine), or `AI_RENDER3D=auto` to use the installed PyVista | 3D sketches: `room-views`, `room-sketches`, `blocking-sketches`. PyVista is faster (~0.6 s vs 7–13 s per sketch) and runs headless. Skip room sketches with `NO_SKETCHES=1`. |

## API keys

| Variable | Needed for |
|----------|-----------|
| `OPENROUTER_API_KEY` | `--llm openrouter` |
| `IMG_AI_API_KEY` (or `GOOGLE_API_KEY`) | `--llm gemini`, Veo animation, TTS, dubbing |
| `XAI_API_KEY` | `animation grok` |
| `ELEVEN_API_KEY` | `tts sfx` |

`make init` checks the key for the selected `LLM` (Makefile default `gemini`; use `make init LLM=openrouter` for OpenRouter).

Set `TARGET_LANGUAGE` (default `Russian`) before generating: it is the language of dialogue, voiceover and captions. Model names, concurrency, image size, seeds, OpenRouter routing and video settings can be overridden with `AI_*` variables; the full list is in [CLAUDE.md](CLAUDE.md#environment).

## Quick Start

The `Makefile` defaults are `LLM=gemini`, `STYLE=vertical_9_16_long_arc`, `PROVIDER=grok`, `NOVEL=s01e23.txt`. Override them on the command line (or in a project Makefile).

**One command:**

```bash
make production NOVEL=s01e01.txt
```

`production` resumes the screenplay from `cinematic_render/pipeline_state.json`, which does not know which novel it belongs to: use a separate series directory per episode, or run `make screenplay NOVEL=...` yourself for the next one.

**From a whole book:**

```bash
make book BOOK=fullbook.txt          # split → fix → story bible; episodes land in book-split/s01eNNN.txt
make production NOVEL=book-split/s01e001.txt
```

**Step by step** (what `production` does, roughly):

```bash
make init                                    # check API key, create directories
make styles NOVEL=s01e01.txt                 # optional: project prompt overrides in custom_prompts/
make bible                                   # optional: story bible from book-split/*.txt
make casting NOVEL=s01e01.txt                # reference cards in ref_thriller/*.json
make detail-rooms NOVEL=s01e01.txt           # name furniture and positions in each room
make room-plan                               # floor plans (review ref_thriller/*.plan.png)
make room-views                              # room and outdoor images, checked by QA
make screenplay NOVEL=s01e01.txt             # scenes and panels
make consistency DRY_RUN=1                   # align refs with scenes (without DRY_RUN=1 it re-renders PNGs)
make refs NO_ROOMS=1                         # character, vehicle and object images
make disposition SCENE=all                   # place actors on room anchors
make spatial-rewrite SCENE=all               # fix panel text that contradicts the placement
make panel-by-panel-with-qa SCENE=all        # panel images with QA and refinement
make animation PROVIDER=veo                  # clips (veo | grok | grok-openrouter)
```

Open the results in the web viewer: `make webserver` → http://localhost:5005/web/index.html

## Make chains

| Target | What it runs |
|--------|--------------|
| `book` | `split-book` into `book-split/raw/` (once) → `logic-book` → `bible` → `logic-book LOGIC_BIBLE=1` (fix the bible's continuity conflicts) → `bible` |
| `production` | `init` → `styles` (fresh project only) → `bible` → `casting` → `detail-rooms` → `room-plan` → `room-views` → `screenplay` → `consistency` → `refs` → `disposition` → `spatial-rewrite` → `panel-by-panel-with-qa` |
| `draft-with-sketches` | same set-building as `production`, then `screenplay` → … → grid `storyboard` |
| `draft` | quick grid storyboard without the room QA chain |

A chain stops at the first failing step: for example, a room whose truth view fails QA stops it before the screenplay uses that room. `casting` uses the bible only when the novel's file name matches a bible chapter (`book-split/s01e001.txt` → `s01e001`); otherwise it warns and casts from the text alone. `make help` lists every target.

## Docker

The image contains the code; each series lives in its own directory, mounted at runtime. One image, many series.

```bash
docker build -t ai-microdrama-factory:latest .     # once, from the repo root
```

```
my-series/
  docker-compose.yml   # copy from repo root
  .env                 # copy .env.example, fill in API keys
  custom_prompts/
  ref_thriller/
  cinematic_render/
  s01e01.txt
```

```bash
# --llm and --style go before the command
docker compose run --rm factory --llm gemini scenes 1
docker run --rm -v $(pwd):/project --env-file .env ai-microdrama-factory:latest --llm gemini scenes 1
docker compose up webserver                        # → http://localhost:5005/web/index.html
```

The image has no Blender; it sets `AI_RENDER3D=auto`, so sketches render with PyVista.

## Style presets

The screenplay picks each scene's panel count from the style's `panel_count_options` (4–12 panels). Select a style with the global `--style` flag (CLI default `vertical_9_16_microdrama`; Makefile default `vertical_9_16_long_arc`).

| Style | Format | Use |
|-------|--------|-----|
| `vertical_9_16_microdrama` | 9:16 | DramaBox/ReelShort-style serial drama: one POV, each episode a hook-to-cliffhanger unit, 3-episode series |
| `vertical_9_16_long_arc` | 9:16 | Arcs of 2–3 episodes (`episodes_count`) running open → mid → close as one hook-to-cliffhanger |
| `vertical_9_16_generic` | 9:16 | Neutral starting point; series of 1/2/3/5 episodes |
| `action_movie_9_16` | 9:16 | Action shorts: action, chase, dialogue, reveal episodes |
| `action_movie_16_9_wide` | 16:9 | Widescreen action short films |

Prompts live in `lib/prompting/<style>/`. A style can extend another (`"extends"` in `config.json`) and patch individual sections of its parent's prompts. A project's `custom_prompts/*.md` replace the style's files of the same name; `custom_prompts/config.json` is merged into the style config key by key.

## CLI reference

```bash
python cli.py --help
python cli.py --llm {openrouter|gemini|debug|manual} [--style <preset>] <command> ...
```

`--llm debug` logs prompts to disk without calling any API; `--llm manual` prints each prompt and reads your reply.

**Book**
- `split-book <novel> [--output-dir book-split] [--season 1]`
- `logic <novel-or-dir> [--output path] [--bible] [--force] [--workers N]`
- `bible <chapter.txt ...> [--force] [--chunk-chars N] [--gleanings N]`

**References**
- `init`
- `styles <novel>`
- `casting [<novel>] [--all] [--no-update]`
- `detail-rooms <novel> [--force]`
- `room-plan [--rooms a,b] [--force]`
- `room-views [--rooms a,b] [--no-sketches] [--force] [--allow-unverified-vfe] [--allow-unverified-vte]`
- `refs [--no-rooms] [--types Outdoor,Vehicle] [--entrance-views-only]`
- older tools: `remake-room-refs [--json-only]`, `room-anchors`, `room-sketches`, `extra-room-refs-qa [--threshold N] [--max-attempts N] [--view NAME]`

**Screenplay**
- `screenplay <novel> [--episodes-only] [--resume]`
- `scenes [scene|all]`, `reverse-refine <scene>`
- `continuity-check [scene|all] [--strict]`
- `positions [scene|all] [--write]`
- `blocking-sketches [scene|all] [--dry-run] [--force] [--export DIR] [--blender CMD]` (alias `car-sketches`)
- `disposition [scene|all]`, `spatial-rewrite [scene|all]`
- `consistency [--dry-run|--no-dry-run]`

**Images**
- `storyboard [scene|all] [panel|all]`, `rebuild-storyboard [scene|all]`
- `panel-by-panel-with-qa <scene|all> [panel|all] [--threshold N] [--max-attempts N] [--skip-existing]`
- `full-frame --scene N --panel N [--aspect-ratio 16:9]`
- `extra-panel <narrative.txt> --scene N --index N_M`
- `imgedit <output> "<instruction>" <image> [ref_image ...]`

**Video**
- `animation <veo|grok|grok-openrouter> [scene|all] [panel|all]`
- `quick-play [--json FILE] [--output FILE] [--workers N] [--target-seconds 6|8|10|15]`
- `master-shot <scene>` (experimental), `stress-refs <name> [--gens N] [--no-judge]`
- `autocut --json <metadata.json> --clips-dir <dir> --out-dir <dir> [--min-fidelity N]`

**Audio and text**
- `voiceover [--out-dir <dir>] [--output <script.sh>]`
- `tts speech "<voice/tone text>" <output>`, `tts sfx "<prompt>" <duration> <output>`
- `dub <video.mp4> <output.mp3> [context.txt] [--plan-cache FILE] [--transcription-cache FILE]`
- `duck <video.mp4> <dubbed.mp3> <output.mp3>`
- `srt <video.mp4> <output.srt> [--transcription-cache FILE]`
- `dynamic-subtitles <input> <output> --srt <file> [--no-whisper] [--language LANG] [--font-size N] [--margin-v N] [--word-srt-output FILE] [--ass-output FILE] [--overlay-only] [--overlay-fps N]`
- `suno-prompt`, `summary <novel> [--output chapter_summary.txt]`

## Outputs

| Path | Contents |
|------|----------|
| `book-split/` | episodes `s01eNNN.txt`; `raw/` split before fixing; `appendix/` setup notes and review of fixes |
| `story_bible/` | `story_bible.json` and a readable `story_bible.md` |
| `ref_thriller/` | reference cards `<name>.json` + `<name>.png`; places as one file pair per view (`<room>-View-From-Entrance`, `<car>-Exterior`, `<street>-View-Primary`, …); floor plans `*.plan.png` |
| `cinematic_render/animation_metadata.json` | the screenplay: all scenes and panels |
| `cinematic_render/panels/` | panel images `NNN_PP_{static,start,end}.png` and their QA results |
| `cinematic_render/scene_NNN_grid_combined.png` | storyboard grid per scene |
| `cinematic_render/clips/`, `cut/` | video clips, auto-trimmed clips |
| `cinematic_render/voiceover/`, `voiceover.sh` | voiceover audio and its script |
| `cinematic_render/extra_panels/`, `full_frames/` | extra shots, wide re-renders |
| `chapter_summary.txt`, `suno_prompt.txt` | context for the next chapter, music prompt |

## Project layout

```text
cli.py, Makefile
lib/core/        # config, prompt loader, JSON schemas
lib/llm/         # OpenRouter, Gemini, debug, manual backends
lib/prompting/   # style presets
lib/studio/      # pipeline stages
lib/commands/    # CLI command registration
lib/animation/   # Veo and Grok animators
lib/audio/       # TTS, dubbing, ducking, subtitles
tests/           # python -m pytest
web/             # static viewer (make webserver)
```

---

**License:** WTFPL
**(c) 2026, E.Z. AI-Story-to-Movie Project**
