# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

The project turns a Russian novel (episode files `s01e01.txt`, …) into cinematic keyframe images and video clips.

```
book ─split-book─► episodes ─logic─► fixed prose ─bible─► story bible
     ─casting─► reference cards (characters, rooms, vehicles, places) ─refs / room-views─► reference PNGs
     ─screenplay─► scenes + panels (animation_metadata.json) ─storyboard / panel-by-panel-with-qa─► panel PNGs
     ─animation─► clips ─autocut / tts / dub / subtitles─► finished video
```

Three model backends:

| Job | Backend | Selected by |
|-----|---------|-------------|
| Text | OpenRouter (default), Gemini, `debug` (logs prompts, no API), `manual` (you type the reply) | `--llm` |
| Images | OpenRouter or Gemini | `--llm` |
| Video | Veo, Grok (xAI SDK), Grok via OpenRouter | `animation <provider>` |

## Everyday commands

```bash
make help                                    # every target with a one-line description
make production NOVEL=s01e01.txt             # recommended end-to-end chain (see "Make chains")
make symlink-lib DIR=../my-series            # link cli.py, lib, web, Makefile.base into a series dir (its Makefile: `include Makefile.base`)
python cli.py --llm gemini --style vertical_9_16_long_arc <command> ...   # --llm and --style go BEFORE the command
python -m pytest                               # test suite (~650 tests, a few minutes)
make test                                      # same, via the Makefile
make test-fast                                 # skip the slow Blender render tests (~20 s)
make lint                                      # ruff check
```

Makefile defaults: `LLM=gemini`, `STYLE=vertical_9_16_long_arc`, `PROVIDER=grok`, `NOVEL=s01e23.txt`, `SCENE=all`, `PANEL=all`. The CLI's own `--style` default is `vertical_9_16_microdrama`. Make variables map to CLI flags (`FORCE=1` → `--force`, `ROOMS=a,b` → `--rooms a,b`, `DRY_RUN=1` → `--dry-run`); read the target in the `Makefile` for the exact mapping. `AI_*` make variables are exported to the CLI as environment variables.

## Environment

API keys (only the ones your backends need):

| Variable | Needed for |
|----------|-----------|
| `OPENROUTER_API_KEY` | `--llm openrouter` (CLI default) |
| `IMG_AI_API_KEY` (or `GOOGLE_API_KEY`) | `--llm gemini` (Makefile default), Veo, TTS, dubbing |
| `XAI_API_KEY` | `animation grok` |
| `ELEVEN_API_KEY` | `tts sfx` |

Optional overrides, grouped. Defaults in parentheses.

- **Models:** `AI_TEXT_MODEL` (`google/gemini-4-hydrogen`), `AI_IMAGE_MODEL` (`google/gemini-nano-banana-2.1`), `AI_GEMINI_MODEL` (`google/gemini-3.8-flash`), `AI_QA_MODEL` (= text model; judge for `consistency`, `autocut`, `stress-refs`). `room-views` and `panel-by-panel-with-qa` ignore `AI_QA_MODEL`: they always judge with `QA_JUDGE_MODEL` = `google/gemini-3.8-flash` at low reasoning effort (`lib/core/project.py`).
- **Language:** `TARGET_LANGUAGE` (`Russian`) — language of dialogue, voiceover and captions.
- **Throughput:** `AI_CONCURRENCY` (10 text workers), `AI_IMAGE_CONCURRENCY` (5 image workers), `AI_LOG_LEVEL` (`INFO`).
- **Image format:** `AI_ASPECT_RATIO`, `AI_IMAGE_SIZE`, `AI_PANEL_IMAGE_SIZE`, `AI_REF_ASPECT_RATIO` (default to the style's `config.json`; when set they override it); `AI_REF_DIR` (`ref_thriller`).
- **Seeds:** `AI_SEED` (21), `AI_SEED_STRICT=1` (same seed on every call instead of per-call variation).
- **OpenRouter:** `AI_IMAGE_BACKEND` (`auto` | `chat` | `image`), `AI_ROUTING_SORT` (`price` | `throughput` | `latency`), `AI_ROUTING_ORDER` (provider list), `AI_ROUTING_MODEL_SUFFIX` (`:floor` | `:nitro`).
- **Gemini:** `AI_SAFETY_LEVEL=default` restores SDK safety defaults (otherwise permissive).
- **Story:** `AI_EPISODES_COUNT` (`long_arc` arc length, 2 or 3).
- **Blocking and 3D sketches:** `AI_BLOCKING` (`sketch` = text block + 3D sketch, `text`, `off`; old name `AI_CAR_BLOCKING` still read), `AI_RENDER3D` (`blender` | `pyvista` | `auto` = pyvista when installed), `AI_DRIVE_SIDE` (`lhd` | `rhd`; a vehicle JSON's `drive_side` wins), `AI_PANEL_ANCHOR_BLOCK=0` (drop the anchor block from panel render and QA prompts).
- **Audio:** `AI_WHISPER_MODEL` (`medium`), `AI_WHISPER_DEVICE` (`cpu`), `AI_WHISPER_COMPUTE` (`int8`) for `dub` and `dynamic-subtitles`; `dub` uses `AI_TEXT_MODEL`.
- **Video:** `AI_VIDEO_TIMEOUT` (600 s Veo polling), `AI_VIDEO_MODEL` (`x-ai/grok-imagine-video-1.5`), `AI_VIDEO_ASPECT` (style aspect), `AI_VIDEO_RESOLUTION` (`720p`), `AI_VIDEO_MAX_REFS` (8 refs per clip), `AI_ERA_LOCK` (e.g. `1990s`; adds an era-drift guard line, off by default).

## Docker

The image contains the code (`/app`); a series directory (`docker-compose.yml`, `.env`, `custom_prompts/`, `ref_thriller/`, `cinematic_render/`, novel `.txt` files) is mounted at `/project`.

```bash
docker build -t ai-microdrama-factory:latest .                                              # once, from repo root
docker run --rm -v $(pwd):/project --env-file .env ai-microdrama-factory:latest <command> [args]
docker compose run --rm factory <command> [args]                                            # same, via compose
docker compose up webserver                                                                 # viewer: http://localhost:5005/web/index.html
```

The image has no Blender; it sets `AI_RENDER3D=auto`, so 3D sketches render through pyvista (headless EGL).

## Key concepts

Read these first; the stage descriptions below rely on them.

- **Ref (reference card).** A `ref_thriller/<name>.json` description plus its `<name>.png` image. Every character, room, vehicle, outdoor place and recurring object has refs; panels name the refs they show so faces and places stay consistent.
- **Character variation.** A separate ref `<Name>-<Variant-Label>` (a costume, an injury, a later look) linked to the base by `character_ref`; the base lists them in `variations`. Each panel actor picks one through `visual_ref`.
- **Views.** A place is several refs, one per camera position, all rendered empty (no people):
  - Room — 8 views: `View-From-Entrance` (**VFE**), `View-To-Entrance` (**VTE**), `View-From-Left-Wall`, `View-From-Right-Wall`, `View-Center-To-Far`, `View-Center-To-Entrance`, `View-By-Far-Wall`, `View-By-Entrance` (`artist/view_catalog.py`).
  - Vehicle — `Exterior`, `Interior-From-Entrance`, `Interior-To-Entrance`.
  - Outdoor place — 4 headings from one camera *station*: `View-Primary` (ahead), `View-Ortho-Primary` (right), `View-Opposite` (behind), `View-Ortho-Opposite` (left).
- **Room coordinates.** x runs image-left → image-right as seen from the entrance; y runs entrance → far wall. "Left wall" always means the wall on the left in VFE.
- **Anchors.** `anchor_points` on the VFE (or outdoor `View-Primary`) JSON: positioned, sized doors, windows, furniture and standing zones. They are the room's geometry; sketches, actor positions and panel cameras are computed from them. Their ids come from the room's `room_vocabulary` (kebab-case named positions such as `bar-counter`, written by `detail-rooms`).
- **Truth chain.** VFE is the base truth for a room, VTE is rendered from VFE, and every other view is derived from VFE + VTE + a 3D sketch. A view may only be used as truth after it passed QA. A new VFE image invalidates VTE and the derived views, and drops VFE anchors that did not come from the floor plan; a new VTE invalidates the derived views. A sketch change never marks VTE stale; a changed plan sketch marks VFE stale. A passed view is skipped only while its PNG hash matches `qa.png_sha256`, so a hand-edited PNG is QA'd again. Outdoor places work the same way with `View-Primary` as the only truth.
- **3D sketch.** A flat-colour render of the anchors (Blender, or pyvista in Docker) from the view's camera. It fixes camera, perspective and object placement; materials come from the truth images. Where a sketch exists (VFE from the floor plan, derived views, panels) it is image 1 in the render prompt and geometry-only truth in QA; VTE renders from VFE alone.
- **QA bands.** Room views are scored on style, architecture and geometry; the *minimum* decides: `< 5` full re-render, `5–7` re-render with corrections, `8` targeted image edit, `≥ 9` accept (`critic.decide_room_view_action`). A candidate replaces the live PNG only when it scores better; an API error marks the view `blocked`.
- **`needs_regenerate`.** A flag on a ref JSON whose PNG is stale; `refs` and `room-views` re-render flagged refs.
- **Story bible.** `story_bible/story_bible.json`: every entity of the whole book with facts, visual features and look variants tied to story time (periods), plus continuity conflicts between chapters. Refs created from it carry `bible_hash`; a changed bible makes `casting` rewrite those refs. Entity names: the model copies proper names in the text's own script (nominative), never transliterating; code romanizes them (`archivist.latin_name`, same table as `ref_key`), so one name gives one key in every chunk.
- **Panel.** One shot of a scene. The screenplay picks each scene's panel count from the style's `panel_count_options` (e.g. 4, 6, 9, 10, 12); each panel has a static frame and optional start/end frames for image-to-video.
- **Blocking.** Who stands where in a panel, computed in code rather than left to prose: car seats (`vehicle_position`) or room positions (anchor + relation, resolved to coordinates). Code projects them through the panel camera into a text block (frame side, depth, facing) and a mannequin sketch. Car blocking applies to panels whose location ref ends in `-Interior-From-Entrance` / `-Interior-To-Entrance`; it reads `body` (`sedan` | `suv` | `suv3` | `minivan`) and `drive_side` from the vehicle JSON, its VEHICLE BLOCKING block replaces the anchor block in render, refinement and QA and overrides the panel text's lens and frame sides, and its sketch goes only to full renders, not image edits.
- **Shared prompt rules.** A rule that the render, critique and QA prompts must all agree on is one constant used everywhere: `room_geometry.BEHIND_CAMERA` (what each view cannot see), `prompts.DOOR_HANDEDNESS` (door mechanism, hinge side, state; a wrong-handed door is a high-severity QA issue), `prompts.NO_LABEL_TEXT` (anchor ids must never appear as lettering in images), `qa_gate.CRITICAL_TAGGING` (which panel defects the judge tags `[CRITICAL]`; appended to every style's panel-QA prompt). Change the constant, not one prompt.
- **Ledger.** `ledger.py` tracks each character's place, seat and wardrobe from panel to panel and scene to scene, and flags changes the story does not explain.

## Pipeline stages

Most stages are a `cli.py` subcommand and a `make` target of the same name. Exceptions: `quick-play` is `make quick-and-dirty-play`; book-mode `logic` is `make logic-book` (`make logic` is single-file only); `master-shot` and `stress-refs` have no make target. The tables give the purpose; the detailed rules (thresholds, retries, cache keys) are in each module's docstring and code, so read the module before changing a stage.

### 1. Book preparation (once per book)

| Command | Module | What it does | Writes |
|---------|--------|--------------|--------|
| `split-book` | `bookbinder` | Cuts a full novel into filmable episodes (sliding window of whole chapters, ~6000 words; the model returns verbatim split anchors). Drops back matter (`Примечания`, `Notes`, …) first. | `book-split/s<SS>eNNN.txt` |
| `logic` (book mode: `make logic-book`) | `fixer` | Makes the prose filmable: fixes physical, spatial, temporal and causal errors, scales superhero action down to what actors can do, and writes a setup appendix (room sizes, required objects, distances, state before the scene). | file mode: `<novel>_fixed.txt`; book mode: `book-split/<ep>.txt` + `book-split/appendix/<ep>.md` (setup) + `<ep>.claims.md` (review) |
| `logic --bible` (`make logic-book LOGIC_BIBLE=1`) | `fixer` | Rewrites only the sentences the bible flagged as contradicting earlier chapters. Applied once per conflict set. | same episode files |
| `bible` | `archivist` | Whole-book story bible (see Key concepts). Multi-pass: extract entities per chunk and re-read for missed ones → build a timeline → merge names → write each entity's look per period. Setup appendices fill gaps the story leaves open but never override the story. | `story_bible/story_bible.{json,md}` |

`make book BOOK=fullbook.txt` runs the whole chain: `split-book` into `BOOK_RAW` = `book-split/raw/` (skipped when it already has episodes) → `logic-book` → `bible` → `logic-book LOGIC_BIBLE=1` → `bible`. `logic` and `bible` cache every LLM call by content hash (`book-split/.logic/`, `story_bible/.cache/`), so re-runs only redo what changed; `split-book` has no cache. Failed episodes or entities exit 2.

### 2. References

| Command | Module | What it does |
|---------|--------|--------------|
| `styles` | `stylist` | Analyzes the novel and writes `custom_prompts/` overrides for the style. Overwrites existing overrides. |
| `casting` | `bible_casting` / `artist.catalog` | Writes ref JSONs. When the bible has a chapter whose id is the novel's file stem (`s01e001.txt` → `s01e001`), or with `--all`: code decides which refs exist (base look + one variation per variant in the chapter's story time, every view of every place), the model writes each entity's content. Up-to-date refs are skipped; stale ones are rewritten and their derived data dropped (`--no-update` keeps them). Otherwise (no bible, stem not in it, or a bible from an older `archivist.VERSION`) it only logs a warning and falls back to text casting, which names refs differently. |
| `detail-rooms` | `artist.room_detail` | Names the furniture and positions of each room (`room_vocabulary`; each entry an `object`, a `zone` or `room-wide` — the room itself, its size or light, never placed) and rewrites every view description to use them; one self-critique round per step. Marks PNGs `needs_regenerate`. `--force` redoes rooms already done. |
| `room-plan` | `room_plan` | Floor plan before any image: the model writes VFE `anchor_points`; code checks them (overlaps, objects through walls, missing named positions, zones standing on furniture, an entrance door, a walkable path to every zone and door, door swings) and sends failures back once. Writes `*.plan.png` (top-down, for humans only). |
| `room-views` | `room_qa` | The truth chain for rooms and outdoor places: VFE (QA'd against its description) → VTE → anchors and sketches → derived views, each with the QA loop. A passed VFE is locked unless `--force`. A failed truth view (VFE, VTE, outdoor `View-Primary`) leaves the rest of its place unrendered; `--allow-unverified-vfe` / `--allow-unverified-vte` override. Exits 2, stopping make chains, when a truth view fails or fails to render (a failed VTE QA is excused by `--allow-unverified-vte`, a failed VFE / View-Primary by `--allow-unverified-vfe`). A derived view that fails QA or render (`render_failed`) is only reported. |
| `refs` | `artist.ref_render` | Renders missing or stale ref PNGs. `--no-rooms` leaves rooms and outdoor places to `room-views`; `--types Outdoor,Vehicle` filters. |

Older or manual tools: `remake-room-refs` (split a single-image place ref into views; adds missing outdoor views), `room-anchors` (anchors for VFE/View-Primary refs without them; `room-views` runs it itself), `room-sketches` (sketches for derived views), `extra-room-refs-qa` (QA loop for derived views only).

### 3. Screenplay

| Command | Module | What it does |
|---------|--------|--------------|
| `screenplay` | `screenwriter` | Episodes → scenes → panels, written into `cinematic_render/animation_metadata.json` (the single source of truth for later stages). `--resume` skips finished phases. Exits 2 before any call when a room VFE or outdoor View-Primary has no `anchor_points` (`--allow-missing-anchors` / `ALLOW_MISSING_ANCHORS=1` writes those scenes without blocking); `scenes` does the same. |
| `scenes` | `screenwriter` | The scene part of `screenplay` for chosen episodes; upserts into the metadata. |
| `reverse-refine` | `screenwriter` | Re-runs only the reversal pass on an episode's raw JSON. |
| `continuity-check` | `ledger` | Reports unexplained moves, seat swaps, wardrobe changes and unseen entrances. `--strict` exits 1. |
| `positions` | `positions`, `room_blocking` | Resolves actor positions and panel cameras from anchors; replaces model cameras that contradict their view. `--write` saves them. |
| `blocking-sketches` (`car-sketches`) | `blocking_sketch` | Blocking text block + cached mannequin sketch per panel (cars and anchored places). `--dry-run` prints blocks; `--export DIR` writes A/B test packs. |
| `disposition` | `screenwriter` | Writes `visual_disposition` per panel from room anchors; consecutive panels sharing an anchor ref are grouped. |
| `spatial-rewrite` | `screenwriter` | Fixes `visual_start` / `motion_prompt` that contradict `visual_disposition`. Backs up the metadata first. |
| `consistency` | `director` | Enriches ref JSONs from how scenes use them (rooms excluded) and aligns panel visuals to the refs. CLI default `--dry-run` writes JSON only (follow with `refs`); **`make consistency` without `DRY_RUN=1` passes `--no-dry-run` and re-renders PNGs.** |

How a scene is written:

1. **Pass 1 — architecture:** panels and their shot requirements (`drama_requirements`).
2. **Pass 1A — state:** who is in frame, where, wearing which `visual_ref`.
3. **Pass 1B — placement:** each actor gets an anchor + relation + posture (never coordinates); code resolves them to positions.
4. **Pass 2 — visual:** the frame description, given the computed blocking so text and render agree on frame sides.
5. **Pass 3 — motion and audio.**
6. **Reversal pass:** for panels marked `is_reversed` (a reveal that is filmed backwards: fog clearing, a reflection forming) writes `motion_prompt_reversed` and an explicit start frame `visual_start_explicit`.

Continuity is enforced in code between passes: every scene declares `transition_in` (`continuous` | `time_skip` | `new_location`) and its entry and exit state, and Pass 1A sees the previous scene's last panel (except after a `new_location` cut). When the ledger finds an unexplained change, `panel_lint` finds a hard-rule violation, or a placement matches no anchor, the pass is retried once and the better answer kept.

### 4. Images

| Command | What it does |
|---------|--------------|
| `storyboard [scene] [panel]` | Renders scene grids or single panels. |
| `panel-by-panel-with-qa <scene\|all> [panel]` | Renders each panel, QA's it, refines up to `--max-attempts` (3). A refinement never replaces a better earlier attempt. Results in `panels/NNN_PP_static.qa.json`; `--skip-existing` skips passed, unchanged panels and only QA's (no re-render) existing panels that never passed. A judge failure is not refined. Exits non-zero if any panel failed. |
| `rebuild-storyboard` | Rebuilds grids from `panels/`. |
| `full-frame --scene N --panel N [--aspect-ratio 16:9]` | Re-renders a panel at a wider aspect ratio. |
| `extra-panel` | Renders an extra shot not in the screenplay (e.g. a reaction shot). |

### 5. Video and post-production

`animation <veo|grok|grok-openrouter>` (image-to-video per panel), `quick-play` (multi-ref clip plan), `master-shot` (experimental), `stress-refs` (identity stress test), `autocut`, `voiceover`, `tts`, `dub`, `duck`, `srt` (Whisper, split at sentence ends), `dynamic-subtitles` (karaoke subtitles, burned in or as an overlay), `suno-prompt`, `summary`, `imgedit`.

## Make chains

Each chain stops at the first failing step (for example `room-views` exiting 2). `bible` runs only when `CHAPTERS` (default `book-split/*.txt`) is non-empty.

| Target | Steps |
|--------|-------|
| `production` (recommended) | `init` → `styles` (only if `custom_prompts/style.md` is missing) → `bible` (if `book-split/*.txt` exist) → `casting` → `detail-rooms` → `room-plan` → `room-views` → `screenplay RESUME=1` → `consistency DRY_RUN=1` → `refs NO_ROOMS=1` → `disposition` → `spatial-rewrite` → `panel-by-panel-with-qa SKIP_EXISTING=1` |
| `draft-with-sketches` | `bible` → `casting` → `detail-rooms` → `room-plan` → `room-views` → `refs NO_ROOMS=1` → `screenplay` → `disposition` → `spatial-rewrite` → `storyboard` |
| `draft` (no truth chain) | `bible` → `casting` → `detail-rooms` → `refs` → `room-anchors` → `remake-room-refs` → `screenplay` → `disposition` → `spatial-rewrite` → `storyboard` |
| `book` | see Book preparation |

Rooms run before `screenplay` because the screenplay reads their anchors.

`cinematic_render/pipeline_state.json` stores the novel's `source_sha256`; `screenplay` with another novel drops all resume progress.

## Code layout

```
cli.py           # entry point; commands registered from lib/commands/
lib/core/        # project.py (config, model defaults), prompts.py (style loader, shared prompt rules), schemas.py,
                 # state.py (pipeline_state.json), utils.py, puppet.py (camera rig, 180° rule)
lib/llm/         # backends (OpenRouter, Gemini, debug, manual), routing.py, seeds.py
lib/prompting/   # style presets (see Prompt system)
lib/studio/      # pipeline stages (module per stage, named in the tables above), plus:
  artist/        #   ref and panel rendering (catalog, ref_render, room_views, room_detail, panels, grids, fullframe, …)
  screenwriter/  #   episodes, passes (1–3), enforce (ledger/lint/positions), scenes, reversal, spatial, pipeline
  critic.py      #   QA judges for panels, room views and descriptions; qa_gate.py (hard geometry defects), promotion.py (best attempt wins)
  render3d/      #   3D sketch scenes, furniture/mannequin meshes, Blender and pyvista engines
  room_geometry.py, room_models.py, blocking.py, vehicle_geometry.py   # shared geometry
  editor.py, retoucher.py, cutter.py, quickplay.py
lib/commands/    # argparse registration per area
lib/animation/   # Veo, Grok, Grok-via-OpenRouter animators; video prompt builder; per-clip ref selection
lib/audio/       # TTS, SFX, dubbing, ducking, subtitles
tests/           # unittest suite
```

## Prompt system

| Location | Role |
|----------|------|
| `lib/prompting/<style>/` | The style's prompts (`*.md`) and `config.json`, shipped with the code |
| `custom_prompts/` | Per-project overrides (written by `styles`), applied last: a `*.md` replaces the whole file, `config.json` is deep-merged per key |
Styles: `vertical_9_16_microdrama`, `vertical_9_16_long_arc`, `vertical_9_16_generic`, `action_movie_9_16`, `action_movie_16_9_wide`. `config.json` sets format (`single_grid_animation` | `single_grid`), panels per scene, aspect ratio, resolution, dialogue, captions, transitions and `episodes_count`.

A style dir holds the stage prompts (`casting.md`, `screenplay.md`, `pass1_architecture.md`, `pass1a_state.md`, `pass2_visual.md`, `pass3_motion_audio.md`, `qa.md`, `book-shrinker.md`, …) and `episode_type_<type>.md` files: an episode whose `episode_type` has a matching file gets it as its type block.

**Inheritance.** `config.json` may set `"extends": "<parent>"`; configs deep-merge and prompts resolve from the root ancestor down (`prompts.resolve_style_file`). In a child style:
- `name.md` replaces the inherited file;
- `name.patch.md` edits it: `<!-- replace: ## Exact Heading -->` replaces that section (empty body deletes it), `<!-- append -->` appends.

A patch heading that matches no section or several, a missing or cyclic parent, or both `name.md` and `name.patch.md` in one dir raise at load time. **Renaming a heading in a parent style breaks its children's patches** — run `tests/test_style_extends.py`.

Action styles also use `format.framing_note` (grid prompt framing) and `animation_prohibitions.md` (replaces the default prohibitions in grok-openrouter video prompts).

## Outputs

```
book-split/                   # episodes (s01eNNN.txt), raw/ split, appendix/ setup notes, .logic/ cache
story_bible/                  # story_bible.json, story_bible.md, .cache/
ref_thriller/                 # <name>.json + <name>.png per ref (views as <place>-View-*.{json,png});
                              # .room_qa/ staged candidates, .blocking_sketches/ cached sketches, *.plan.png, *.sketch.png
cinematic_render/
  animation_episodes.json             # episode breakdown
  animation_episode_scenes_NNN.json   # raw keyframes per episode (+ _refined.json)
  animation_metadata.json             # merged scenes — single source of truth
  blocking_sketches.json
  scene_NNN_grid_combined.png
  panels/NNN_PP_{static,start,end}.png, NNN_PP_static.qa.json
  refined/, clips/, cut/, voiceover/, extra_panels/, full_frames/
chapter_summary.txt, suno_prompt.txt, voiceover.sh
```

## Schemas

Structured-output schemas live in `lib/core/schemas.py`. The ones you meet most:

- `SCREENPLAY_SCHEMA` — episodes and their scenes, including the scene contract (`transition_in`, `entry_state`, `exit_state`) and required `background_activity` (`density` must be `none` for private places, non-`none` for public ones).
- `SCENE_SCHEMA` — scene keyframes: camera and lighting masters, per-character trajectories, panel fields (motion, audio, voiceover, transitions, `state`, `drama_requirements`).
- `PANEL_STATE_SCHEMA` — who is where in a panel: actors (pose, gaze, `in_frame`, `visual_ref`, `vehicle_position` — `none` outside vehicles), props, anchors (Pass 1A → Pass 2).
- `DRAMA_REQUIREMENTS_SCHEMA` — shot scale, angle, composition, focus (Pass 1 → later passes).
- `CHARACTER_SCHEMA` — ref descriptions, including `variations`, `character_ref`, `context`.
- `ROOM_VOCABULARY_SCHEMA`, `ROOM_DETAIL_SCHEMA` — `detail-rooms` outputs.
- `REVERSAL_SCHEMA`, `SCENE_REWRITE_SCHEMA` — reversal pass and continuity enforcer.

## API errors

Token-bucket rate limits: OpenRouter 20 RPM text, 10 RPM images, 5 RPM video; Gemini 30 RPM. 429/500/502/503 and timeouts retry with exponential backoff (3 attempts in total). 401, 402 and spend-limit/disabled-key 403s stop the command (`SystemExit`); other 403s (e.g. a blocked request) fail only that call.

## Code Style Guidelines

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
