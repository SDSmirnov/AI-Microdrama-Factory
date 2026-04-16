NOVEL          ?= s01e23.txt
TARGET_LANGUAGE ?= Russian
BOOK           ?= $(NOVEL)
BOOK_OUT       ?= book-split
SEASON         ?= 1
STYLE          ?= vertical_9_16_long_arc
SCENE     ?= all
PANEL     ?= all
PROVIDER  ?= grok
LLM       ?= gemini

# Post-production defaults
JSON        ?= cinematic_render/animation_metadata.json
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
MAX_ATTEMPTS ?= 3
REFS           ?=
VOICEOVER_DIR  ?= cinematic_render/voiceover
VOICEOVER_SH   ?= voiceover.sh
NARRATIVE      ?=
INDEX          ?=
AR             ?= 16:9

.PHONY: help init workdirs styles casting detail-rooms refs remake-room-refs room-anchors extra-room-refs-qa screenplay scenes reverse-refine disposition spatial-rewrite consistency storyboard rebuild-storyboard animation \
        autocut imgedit tts voiceover dub duck summary split-book panel-by-panel-with-qa extra-panel suno-prompt logic draft full-frame quick-and-dirty-play

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

init:  ## Validate env and create directories
	python cli.py init

workdirs:  ## Create video working directories
	mkdir -p video/scenes video/music video/sound video/clips

styles:  ## Generate custom_prompts/ for STYLE preset
	python cli.py --llm $(LLM) --style $(STYLE) styles $(NOVEL)

casting:  ## Identify characters/locations and save reference JSONs
	python cli.py --llm $(LLM) --style $(STYLE) casting $(NOVEL)

detail-rooms:  ## Enrich room ref descriptions with named furniture, equipment, per-character anchors
	python cli.py --llm $(LLM) --style $(STYLE) detail-rooms $(NOVEL) $(if $(FORCE),--force,)

refs:  ## Render missing character reference portraits from existing JSONs
	python cli.py --llm $(LLM) --style $(STYLE) refs

remake-room-refs:  ## Split Room/Vehicle refs into separate per-view refs and render them
	python cli.py --llm $(LLM) --style $(STYLE) remake-room-refs

room-anchors:  ## Generate spatial anchor_points for View-From-Entrance room refs
	python cli.py --llm $(LLM) --style $(STYLE) room-anchors

extra-room-refs-qa:  ## QA and auto-regenerate the 4 derived room views (threshold=7, max-attempts=3)
	python cli.py --llm $(LLM) --style $(STYLE) extra-room-refs-qa $(if $(THRESHOLD),--threshold $(THRESHOLD),) $(if $(MAX_ATTEMPTS),--max-attempts $(MAX_ATTEMPTS),) $(if $(VIEW),--view $(VIEW),)

logic:  ## Fix logic/physics/space bugs and generate scene prerequisites appendix (NOVEL=file.txt)
	python cli.py --llm $(LLM) logic $(NOVEL) $(if $(OUTPUT),--output $(OUTPUT),) $(if $(WORKERS),--workers $(WORKERS),)

screenplay:  ## Run full screenplay + scene keyframe pipeline (EPISODES_ONLY=true → stop after animation_episodes.json)
	python cli.py --llm $(LLM) --style $(STYLE) screenplay $(NOVEL) $(if $(filter true,$(EPISODES_ONLY)),--episodes-only,)

scenes:  ## Generate keyframes for episode SCENE (or all)
	python cli.py --llm $(LLM) --style $(STYLE) scenes $(SCENE)

reverse-refine:  ## Refinement + reversal pass on existing raw episode JSON (SCENE=N required)
	python cli.py --llm $(LLM) --style $(STYLE) reverse-refine $(SCENE)

disposition:  ## Spatial disposition pass: write visual_disposition per panel (SCENE=N required)
	cp cinematic_render/animation_metadata.json cinematic_render/animation_metadata_before_disposition.json
	python cli.py --llm $(LLM) --style $(STYLE) disposition $(SCENE)

spatial-rewrite:  ## Fix visual_start/motion_prompt contradictions using visual_disposition (run after disposition; SCENE=N or omit for all)
	cp cinematic_render/animation_metadata.json cinematic_render/animation_metadata_before_spatial_rewrite.json
	python cli.py --llm $(LLM) --style $(STYLE) spatial-rewrite $(SCENE)

consistency:  ## Run continuity enforcer to sync references (dry-run by default; use RENDER=--no-dry-run to regenerate PNGs)
	python cli.py --llm $(LLM) --style $(STYLE) consistency --no-dry-run

storyboard:  ## Render scene grid images or individual panels
	python cli.py --llm $(LLM) --style $(STYLE) storyboard $(SCENE) $(PANEL)

rebuild-storyboard:  ## Rebuild scene grid images from current panels/ (backup originals)
	python cli.py rebuild-storyboard $(SCENE)

animation:  ## Generate video clips using PROVIDER (veo|grok)
	python cli.py animation $(PROVIDER) $(SCENE)

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
	python cli.py --llm $(LLM) --style $(STYLE) split-book $(BOOK) --output-dir $(BOOK_OUT) --season $(SEASON)

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
	python cli.py --llm $(LLM) quick-play $(if $(JSON),--json $(JSON),) $(if $(OUTPUT),--output $(OUTPUT),) $(if $(WORKERS),--workers $(WORKERS),) --target-seconds $(TARGET_SECONDS)

draft:  ## Full draft pipeline: casting → detail-rooms → refs → room-anchors → remake-room-refs → screenplay → disposition → spatial-rewrite → storyboard
	$(MAKE) casting
	$(MAKE) detail-rooms
	$(MAKE) refs
	$(MAKE) room-anchors
	$(MAKE) remake-room-refs
	$(MAKE) screenplay
	$(MAKE) disposition
	$(MAKE) spatial-rewrite
	$(MAKE) storyboard

panel-by-panel-with-qa:  ## Render panels one-by-one with inline QA+refine (SCENE=N [PANEL=N] [THRESHOLD=5] [MAX_ATTEMPTS=3])
	@[ "$(SCENE)" != "all" ] || (echo "❌ SCENE must be set to an integer, e.g. make panel-by-panel-with-qa SCENE=1"; exit 1)
	python cli.py --llm $(LLM) --style $(STYLE) panel-by-panel-with-qa $(SCENE) $(PANEL) --threshold $(THRESHOLD) --max-attempts $(MAX_ATTEMPTS)

webserver:  ## Start static web server on :5005 and open Chrome at web/index.html
	@python3 web/gen_server_info.py
	@echo "Starting server at http://localhost:5005/web/index.html"
	@(sleep 1 && google-chrome --new-tab "http://localhost:5005/web/index.html" 2>/dev/null &) &
	python3 -m http.server 5005 --directory .
