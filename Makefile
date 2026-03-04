NOVEL          ?= s01e03.txt
STYLE          ?= vertical_microdrama
SCENE     ?= all
PANEL     ?= all
PROVIDER  ?= veo
LLM       ?= openrouter
CUSTOM    ?= --custom-prompts

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
REFS           ?=
VOICEOVER_DIR  ?= cinematic_render/voiceover
VOICEOVER_SH   ?= voiceover.sh

.PHONY: help init workdirs styles casting refs screenplay scenes consistency storyboard qa apply-qa refinement animation \
        autocut imgedit tts voiceover dub duck

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

init:  ## Validate env and create directories
	python cli.py init

workdirs:  ## Create video working directories
	mkdir -p video/scenes video/music video/sound video/clips

styles:  ## Generate custom_prompts/ for STYLE preset
	python cli.py --llm $(LLM) styles $(NOVEL) --style $(STYLE)

casting:  ## Identify characters/locations and save reference JSONs
	python cli.py --llm $(LLM) casting $(NOVEL) $(CUSTOM)

refs:  ## Render missing character reference portraits from existing JSONs
	python cli.py --llm $(LLM) refs $(CUSTOM)

screenplay:  ## Run full screenplay + scene keyframe pipeline
	python cli.py --llm $(LLM) screenplay $(NOVEL) $(CUSTOM)

scenes:  ## Generate keyframes for episode SCENE (or all)
	python cli.py --llm $(LLM) scenes $(SCENE) $(CUSTOM)

consistency:  ## Run continuity enforcer to sync references
	python cli.py --llm $(LLM) consistency

storyboard:  ## Render scene grid images or individual panels
	python cli.py --llm $(LLM) storyboard $(SCENE) $(PANEL) $(CUSTOM)

qa:  ## Run grid quality gate for SCENE (pass SCENE=N to filter; omit for all)
	python cli.py --llm $(LLM) qa $(if $(filter-out all,$(SCENE)),--scene $(SCENE),)

apply-qa:  ## Refine all needs_refinement panels from quality_report.json (SCENE=N to filter)
	python cli.py --llm $(LLM) apply-qa $(if $(filter-out all,$(SCENE)),--scene $(SCENE),) $(CUSTOM)

refinement:  ## Refine panel PANEL in scene SCENE (both must be integers, e.g. SCENE=1 PANEL=3)
	python cli.py --llm $(LLM) refinement $(SCENE) $(PANEL)

animation:  ## Generate video clips using PROVIDER (veo|grok)
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

dub:  ## Smart-dub VIDEO → OUTPUT mp3 (optionally guided by CONTEXT file)
	python cli.py dub $(VIDEO) $(OUTPUT) $(CONTEXT)

duck:  ## Duck original audio in VIDEO wherever DUBBED track speaks → OUTPUT mp3
	python cli.py duck $(VIDEO) $(DUBBED) $(OUTPUT)
