# The repo's own directory, even when a series dir includes this file through its Makefile.base symlink.
CODE_DIR := $(patsubst %/,%,$(dir $(realpath $(lastword $(MAKEFILE_LIST)))))
LINKS    := cli.py lib web Makefile
NOVEL          ?= s01e23.txt
TARGET_LANGUAGE ?= Russian
BOOK           ?= $(NOVEL)
BOOK_OUT       ?= book-split
BOOK_RAW       ?= $(BOOK_OUT)/raw
SPLIT_OUT      ?= $(BOOK_OUT)
CHAPTERS       ?= $(sort $(wildcard $(BOOK_OUT)/*.txt))
SEASON         ?= 1
STYLE          ?= vertical_9_16_long_arc
SCENE     ?= all
PANEL     ?= all
PROVIDER  ?= grok
LLM       ?= gemini
# Project Makefiles set AI_* overrides as make variables; the CLI reads them from the environment.
export TARGET_LANGUAGE $(filter AI_%,$(.VARIABLES))

# Post-production defaults
JSON        ?= cinematic_render/animation_metadata.json
# quick-play: source episodes JSON and output; empty = the CLI defaults
EPISODES    ?=
QUICKPLAY   ?=
CLIPS_DIR   ?= cinematic_render/clips
OUT_DIR     ?= cinematic_render/cut
VIDEO       ?=
DUBBED      ?=
OUTPUT      ?= output.mp3
IMG_OUTPUT  ?= output.png
CONTEXT     ?=
TYPE        ?= speech
TEXT        ?=
DURATION    ?= 3
IMAGE       ?=
EDIT        ?=
FRAME      ?= both
THRESHOLD  ?= 5
ROOM_THRESHOLD ?= 9
MAX_ATTEMPTS ?= 3
REFS           ?=
VOICEOVER_DIR  ?= cinematic_render/voiceover
VOICEOVER_SH   ?= voiceover.sh
NARRATIVE      ?=
INDEX          ?=
AR             ?= 16:9

.PHONY: help init workdirs styles book logic-book bible casting detail-rooms refs refs-entrance remake-room-refs room-anchors room-plan room-sketches car-sketches blocking-sketches positions continuity-check room-views extra-room-refs-qa screenplay scenes reverse-refine disposition spatial-rewrite consistency storyboard rebuild-storyboard animation \
        autocut imgedit tts voiceover dub duck summary split-book panel-by-panel-with-qa extra-panel suno-prompt logic draft draft-with-sketches production full-frame quick-and-dirty-play symlink-lib \
        srt dynamic-subtitles dynamic-subtitles-overlay webserver lint test test-fast test-cov

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

symlink-lib:  ## Link cli.py, lib, web and Makefile.base from the repo into DIR (default: current dir); real files there are left alone
	@dir=$(abspath $(or $(DIR),$(CURDIR))); \
	test "$$dir" != "$(CODE_DIR)" || { echo "symlink-lib: run with DIR=<series dir>, not the repo itself" >&2; exit 1; }; \
	mkdir -p "$$dir"; \
	for f in $(LINKS); do \
	  dst="$$dir/$$f"; [ $$f = Makefile ] && dst="$$dir/Makefile.base"; \
	  if [ -e "$$dst" ] && [ ! -L "$$dst" ]; then echo "skip $$dst: not a symlink" >&2; continue; fi; \
	  ln -sfn "$(CODE_DIR)/$$f" "$$dst" && echo "$$dst -> $(CODE_DIR)/$$f"; \
	done

init:  ## Validate env (for LLM) and create directories
	python cli.py --llm $(LLM) init

workdirs:  ## Create video working directories
	mkdir -p video/scenes video/music video/sound video/clips

styles:  ## Generate custom_prompts/ for STYLE preset (ANCHOR_ONLY=1: only setting.md's real-world anchor)
	python cli.py --llm $(LLM) --style $(STYLE) styles $(NOVEL) $(if $(ANCHOR_ONLY),--anchor-only,)

bible:  ## Whole-book story bible → story_bible/ (CHAPTERS="a.txt b.txt", default BOOK_OUT/*.txt; BIBLE_FORCE=1 ignores cache; BIBLE_CHUNK=20000 BIBLE_GLEANINGS=2)
	python cli.py --llm $(LLM) --style $(STYLE) bible $(CHAPTERS) $(if $(BIBLE_FORCE),--force,) $(if $(BIBLE_CHUNK),--chunk-chars $(BIBLE_CHUNK),) $(if $(BIBLE_GLEANINGS),--gleanings $(BIBLE_GLEANINGS),)

casting:  ## Reference JSONs: planned from the story bible when it has NOVEL's chapter, else from the text (CAST_ALL=1 CAST_NO_UPDATE=1)
	python cli.py --llm $(LLM) --style $(STYLE) casting $(if $(CAST_ALL),--all,$(NOVEL)) $(if $(CAST_NO_UPDATE),--no-update,)

detail-rooms:  ## Enrich room ref descriptions with named furniture, equipment, per-character anchors
	python cli.py --llm $(LLM) --style $(STYLE) detail-rooms $(NOVEL) $(if $(FORCE),--force,)

refs:  ## Render missing/stale reference PNGs (NO_ROOMS=1 skips Room views; TYPES=Outdoor,Vehicle filters)
	python cli.py --llm $(LLM) --style $(STYLE) refs $(if $(NO_ROOMS),--no-rooms,) $(if $(TYPES),--types $(TYPES),)

remake-room-refs:  ## Split Room/Vehicle refs into separate per-view refs and render them (CREATE_ONLY=1 → JSONs only)
	python cli.py --llm $(LLM) --style $(STYLE) remake-room-refs $(if $(CREATE_ONLY),--json-only,)

refs-entrance:  ## Render only the two entrance-axis room views (run before room-anchors)
	python cli.py --llm $(LLM) --style $(STYLE) refs --entrance-views-only

room-anchors:  ## Generate spatial anchor_points for room/outdoor primary views
	python cli.py --llm $(LLM) --style $(STYLE) room-anchors

room-plan:  ## Floor plan first: checked VFE anchors from the description, *.plan.png to review (ROOMS=a,b FORCE=1)
	python cli.py --llm $(LLM) --style $(STYLE) room-plan $(if $(ROOMS),--rooms $(ROOMS),) $(if $(FORCE),--force,)

room-sketches:  ## Render bare 3D sketches for derived room views (requires Blender on PATH)
	python cli.py --llm $(LLM) --style $(STYLE) room-sketches

room-views:  ## Truth-aware room + outdoor chains: truth view QA → anchors/sketch → derived views + QA
	python cli.py --llm $(LLM) --style $(STYLE) room-views $(if $(ROOMS),--rooms $(ROOMS),) $(if $(NO_SKETCHES),--no-sketches,) $(if $(FORCE),--force,) $(if $(ALLOW_UNVERIFIED_VTE),--allow-unverified-vte,) $(if $(ALLOW_UNVERIFIED_VFE),--allow-unverified-vfe,)

extra-room-refs-qa:  ## Legacy: QA and auto-regenerate derived room views (ROOM_THRESHOLD=9, MAX_ATTEMPTS=3)
	python cli.py --llm $(LLM) --style $(STYLE) extra-room-refs-qa --threshold $(ROOM_THRESHOLD) $(if $(MAX_ATTEMPTS),--max-attempts $(MAX_ATTEMPTS),) $(if $(VIEW),--view $(VIEW),)

book:  ## Whole book: split-book into BOOK_RAW (once) → logic → bible → logic on bible conflicts → bible
	@ls $(BOOK_RAW)/*.txt >/dev/null 2>&1 || $(MAKE) split-book SPLIT_OUT=$(BOOK_RAW)
	$(MAKE) logic-book
	$(MAKE) bible
	$(MAKE) logic-book LOGIC_BIBLE=1
	$(MAKE) bible

logic-book:  ## Book mode: BOOK_RAW episodes → BOOK_OUT prose + BOOK_OUT/appendix setup (cached); LOGIC_BIBLE=1 fixes bible conflicts
	python cli.py --llm $(LLM) --style $(STYLE) logic $(if $(LOGIC_BIBLE),$(BOOK_OUT) --bible,$(BOOK_RAW) --output $(BOOK_OUT)) $(if $(WORKERS),--workers $(WORKERS),)

logic:  ## Fix logic/physics/space bugs and generate scene prerequisites appendix (NOVEL=file.txt)
	python cli.py --llm $(LLM) logic $(NOVEL) $(if $(OUTPUT),--output $(OUTPUT),) $(if $(WORKERS),--workers $(WORKERS),)

screenplay:  ## Run full screenplay + scene keyframe pipeline (EPISODES_ONLY=true → stop after animation_episodes.json; RESUME=1 → skip finished phases; ALLOW_MISSING_ANCHORS=1 → do not exit 2 on places without anchors)
	python cli.py --llm $(LLM) --style $(STYLE) screenplay $(NOVEL) $(if $(filter true,$(EPISODES_ONLY)),--episodes-only,) $(if $(RESUME),--resume,) $(if $(ALLOW_MISSING_ANCHORS),--allow-missing-anchors,)

scenes:  ## Generate keyframes for episode SCENE (or all)
	python cli.py --llm $(LLM) --style $(STYLE) scenes $(SCENE) $(if $(ALLOW_MISSING_ANCHORS),--allow-missing-anchors,)

reverse-refine:  ## Refinement + reversal pass on existing raw episode JSON (SCENE=N required)
	python cli.py --llm $(LLM) --style $(STYLE) reverse-refine $(SCENE)

continuity-check:  ## Story ledger check: unexplained moves/seat swaps/wardrobe changes (SCENE=N|all [STRICT=1])
	python cli.py --llm $(LLM) --style $(STYLE) continuity-check $(SCENE) $(if $(STRICT),--strict,)

disposition:  ## Spatial disposition pass: write visual_disposition per panel (SCENE=N required)
	cp cinematic_render/animation_metadata.json cinematic_render/animation_metadata_before_disposition.json
	python cli.py --llm $(LLM) --style $(STYLE) disposition $(SCENE)

spatial-rewrite:  ## Fix visual_start/motion_prompt contradictions using visual_disposition (run after disposition; SCENE=N or omit for all)
	cp cinematic_render/animation_metadata.json cinematic_render/animation_metadata_before_spatial_rewrite.json
	python cli.py --llm $(LLM) --style $(STYLE) spatial-rewrite $(SCENE)

consistency:  ## Continuity enforcer: enrich ref JSONs + align scene prompts (Room views untouched); DRY_RUN=1 → no PNG renders (follow with make refs)
	python cli.py --llm $(LLM) --style $(STYLE) consistency $(if $(DRY_RUN),--dry-run,--no-dry-run)

storyboard:  ## Render scene grid images or individual panels
	python cli.py --llm $(LLM) --style $(STYLE) storyboard $(SCENE) $(PANEL)

blocking-sketches:  ## Blocking per panel (car seats, room/outdoor positions) + Blender sketches (SCENE=N|all [DRY_RUN=1] [FORCE=1])
	python cli.py --llm $(LLM) --style $(STYLE) blocking-sketches $(SCENE) $(if $(DRY_RUN),--dry-run,) $(if $(FORCE),--force,)

car-sketches: blocking-sketches

positions:  ## Resolve actor positions + panel cameras from anchors (SCENE=N|all [WRITE=1])
	python cli.py --llm $(LLM) --style $(STYLE) positions $(SCENE) $(if $(WRITE),--write,)

rebuild-storyboard:  ## Rebuild scene grid images from current panels/ (backup originals)
	python cli.py rebuild-storyboard $(SCENE)

animation:  ## Generate video clips using PROVIDER (veo|grok|grok-openrouter)
	python cli.py animation $(PROVIDER) $(SCENE) $(PANEL)

autocut:  ## AI-trim clips in CLIPS_DIR using JSON metadata → OUT_DIR
	python cli.py autocut --json $(JSON) --clips-dir $(CLIPS_DIR) --out-dir $(OUT_DIR)

imgedit:  ## Edit IMAGE with EDIT instruction (+ optional REFS); save to IMG_OUTPUT
	python cli.py --llm $(LLM) imgedit $(IMG_OUTPUT) "$(EDIT)" $(IMAGE) $(REFS)

tts:  ## Generate audio: TYPE=speech TEXT="..." OUTPUT=out.wav  or  TYPE=sfx TEXT="..." DURATION=3
	@if [ "$(TYPE)" = "sfx" ]; then \
	  python cli.py tts sfx "$(TEXT)" $(DURATION) $(OUTPUT); \
	else \
	  python cli.py --llm $(LLM) tts speech "$(TEXT)" $(OUTPUT); \
	fi

voiceover:  ## Generate VOICEOVER_SH script with tts calls for all panel voiceovers
	python cli.py voiceover --out-dir $(VOICEOVER_DIR) --output $(VOICEOVER_SH)

srt:  ## Transcribe VIDEO with Whisper → OUTPUT SRT for manual editing
	python cli.py srt $(VIDEO) $(OUTPUT)

dub:  ## Smart-dub VIDEO → OUTPUT mp3 (optionally guided by CONTEXT file)
	python cli.py dub $(VIDEO) $(OUTPUT) $(CONTEXT)

duck:  ## Duck original audio in VIDEO wherever DUBBED track speaks → OUTPUT mp3
	python cli.py duck $(VIDEO) $(DUBBED) $(OUTPUT)

dynamic-subtitles:  ## Burn karaoke subtitles: INPUT=x.mp4 OUTPUT=x.sub.mp4 SRT=x.srt
	python cli.py dynamic-subtitles $(INPUT) $(OUTPUT) --srt $(SRT)

dynamic-subtitles-overlay:  ## Transparent subtitle overlay: INPUT=x.mp4 OUTPUT=x.overlay.mov SRT=x.srt
	python cli.py dynamic-subtitles $(INPUT) $(OUTPUT) --srt $(SRT) --overlay-only

summary:  ## Generate chapter_summary.txt context for the next chapter
	python cli.py --llm $(LLM) summary $(NOVEL) --output chapter_summary.txt

suno-prompt:  ## Generate Suno instrumental prompt from animation_episodes.json → suno_prompt.txt
	python cli.py --llm $(LLM) suno-prompt

split-book:  ## Split BOOK into filmable 3-POV episode chunks → BOOK_OUT/s0SeNNN.txt (BOOK=file STYLE=... SEASON=N)
	python cli.py --llm $(LLM) --style $(STYLE) split-book $(BOOK) --output-dir $(SPLIT_OUT) --season $(SEASON)

full-frame:  ## Re-render panel at wider AR using source PNG as reference (SCENE=N PANEL=N [AR=16:9])
	@[ "$(SCENE)" != "all" ] || (echo "❌ SCENE must be set to an integer, e.g. make full-frame SCENE=1 PANEL=4"; exit 1)
	@[ "$(PANEL)" != "all" ] || (echo "❌ PANEL must be set to an integer, e.g. make full-frame SCENE=1 PANEL=4"; exit 1)
	python cli.py --llm $(LLM) --style $(STYLE) full-frame --scene $(SCENE) --panel $(PANEL) --aspect-ratio $(AR)

extra-panel:  ## Generate extra micro-panel not in screenplay (SCENE=N INDEX=4_5 NARRATIVE=file.txt)
	@[ -n "$(NARRATIVE)" ] || (echo "❌ NARRATIVE must be set, e.g. make extra-panel NARRATIVE=extra.txt SCENE=1 INDEX=4_5"; exit 1)
	@[ "$(SCENE)" != "all" ] || (echo "❌ SCENE must be set to an integer, e.g. make extra-panel SCENE=1"; exit 1)
	@[ -n "$(INDEX)" ] || (echo "❌ INDEX must be set in N_M format, e.g. make extra-panel INDEX=4_5"; exit 1)
	python cli.py --llm $(LLM) --style $(STYLE) extra-panel $(NARRATIVE) --scene $(SCENE) --index $(INDEX)

TARGET_SECONDS ?= 10

quick-and-dirty-play:  ## Synthesize quickplay.json for multi-ref clips (Seedance/Kling/Grok); TARGET_SECONDS=6|8|10|15
	python cli.py --llm $(LLM) quick-play $(if $(EPISODES),--json $(EPISODES),) $(if $(QUICKPLAY),--output $(QUICKPLAY),) $(if $(WORKERS),--workers $(WORKERS),) --target-seconds $(TARGET_SECONDS)

draft:  ## Full draft pipeline: bible → casting → detail-rooms → refs → room-anchors → remake-room-refs → screenplay → disposition → spatial-rewrite → storyboard
	@[ -z "$(CHAPTERS)" ] || $(MAKE) bible
	$(MAKE) casting
	$(MAKE) detail-rooms
	$(MAKE) refs
	$(MAKE) room-anchors
	$(MAKE) remake-room-refs
	$(MAKE) screenplay
	$(MAKE) disposition
	$(MAKE) spatial-rewrite
	$(MAKE) storyboard

draft-with-sketches:  ## Geometry-first draft: rooms via room-plan → room-views, then screenplay → grid storyboard
	@[ -z "$(CHAPTERS)" ] || $(MAKE) bible
	$(MAKE) casting
	$(MAKE) detail-rooms
	$(MAKE) room-plan
	$(MAKE) room-views
	$(MAKE) refs NO_ROOMS=1
	$(MAKE) screenplay
	$(MAKE) disposition
	$(MAKE) spatial-rewrite
	$(MAKE) storyboard

panel-by-panel-with-qa:  ## Render panels one-by-one with inline QA+refine (SCENE=N|all [PANEL=N] [THRESHOLD=5] [MAX_ATTEMPTS=3] [SKIP_EXISTING=1])
	python cli.py --llm $(LLM) --style $(STYLE) panel-by-panel-with-qa $(SCENE) $(PANEL) --threshold $(THRESHOLD) --max-attempts $(MAX_ATTEMPTS) $(if $(SKIP_EXISTING),--skip-existing,)

# styles overwrites custom_prompts/, so it runs only on a fresh project. room-views renders and anchors rooms
# and outdoor locations before the screenplay (it reads their anchors); the other refs render after consistency.
production:  ## init → styles → bible → casting → detail-rooms → room-plan → room-views → screenplay → consistency → refs → disposition → spatial-rewrite → panel-by-panel QA
	$(MAKE) init
	@[ -f custom_prompts/style.md ] || $(MAKE) styles
	@[ -z "$(CHAPTERS)" ] || $(MAKE) bible
	$(MAKE) casting
	$(MAKE) detail-rooms
	$(MAKE) room-plan
	$(MAKE) room-views
	$(MAKE) screenplay RESUME=1
	$(MAKE) consistency DRY_RUN=1
	$(MAKE) refs NO_ROOMS=1
	$(MAKE) disposition SCENE=all
	$(MAKE) spatial-rewrite SCENE=all
	$(MAKE) panel-by-panel-with-qa SCENE=all SKIP_EXISTING=1

webserver:  ## Start static web server on :5005 and open Chrome at web/index.html
	@python3 web/gen_server_info.py
	@echo "Starting server at http://localhost:5005/web/index.html"
	@(sleep 1 && google-chrome --new-tab "http://localhost:5005/web/index.html" 2>/dev/null &) &
	python3 -m http.server 5005 --directory .

lint:  ## Lint code (ruff: pyflakes + syntax errors)
	ruff check

test:  ## Run the test suite (pytest; unittest-style tests included)
	python -m pytest

test-fast:  ## Run tests without slow Blender renders
	python -m pytest -m "not blender and not render3d"

test-cov:  ## Run tests with a coverage report for lib/
	python -m pytest --cov=lib --cov-report=term-missing -m "not blender and not render3d"
