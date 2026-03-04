#!/usr/bin/env python3
"""
cli.py — Single entry point for the video-book pipeline.

Usage:
    python cli.py init
    python cli.py styles s01e01.txt --style realistic_movie
    python cli.py casting s01e01.txt [--custom-prompts]
    python cli.py screenplay s01e01.txt [--custom-prompts]
    python cli.py scenes [SCENE|all] [--custom-prompts]
    python cli.py consistency
    python cli.py storyboard [SCENE|all] [--custom-prompts]
    python cli.py qa [--scene N [--panel N ...]] [--threshold N]
    python cli.py refinement SCENE PANEL [--frame start|end|both]
    python cli.py animation PROVIDER SCENE PANEL [--frame start|end]

    # Post-production tools
    python cli.py autocut --json scene.json --clips-dir clips/ --out-dir cut/
    python cli.py imgedit output.png "make the sky purple" source.png [ref.png ...]
    python cli.py tts speech "Female [tone sad]: Hello world" out.wav
    python cli.py tts sfx "Loud explosion" 3 expl.mp3
    python cli.py dub video.mp4 output.mp3 [context.txt]
    python cli.py duck video.mp4 dubbed.mp3 output.mp3
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(
    level=os.getenv('AI_LOG_LEVEL', 'INFO'),
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------

def _make_llm(llm_type: str, project, system_prompt: str = ""):
    """Build an LLM backend from --llm flag."""
    if llm_type == "gemini":
        from lib.llm.gemini import GeminiLLM
        if not project.gemini_api_key:
            logger.error("❌ IMG_AI_API_KEY or GOOGLE_API_KEY not set")
            sys.exit(1)
        return GeminiLLM(
            api_key=project.gemini_api_key,
            text_model=project.text_model,
            image_model=project.image_model,
        )
    elif llm_type == "grok":
        from lib.llm.grok import GrokLLM
        return GrokLLM(api_key=project.openrouter_api_key)
    else:  # openrouter (default)
        from lib.llm.openrouter import OpenRouterLLM
        if not project.openrouter_api_key:
            logger.error("❌ OPENROUTER_API_KEY not set")
            sys.exit(1)
        return OpenRouterLLM(
            api_key=project.openrouter_api_key,
            text_model=project.text_model,
            image_model=project.image_model,
            system_prompt=system_prompt,
        )


def _make_vision_llm(llm_type: str, project, system_prompt: str = ""):
    """Build a vision-capable BaseLLM backend for QA/continuity/refinement."""
    if llm_type == "grok":
        logger.error("❌ --llm grok is not supported for QA/continuity/refinement")
        sys.exit(1)
    return _make_llm(llm_type, project, system_prompt=system_prompt)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_init(args):
    """Validate env and ensure output directories exist."""
    from lib.core.project import Project
    project = Project()
    project.ensure_dirs()
    errors = project.validate_env()
    if errors:
        for e in errors:
            logger.error(f"  ❌ {e}")
        sys.exit(1)
    logger.info("✅ Init OK — all directories created, env vars validated.")
    logger.info(f"  text_model:  {project.text_model}")
    logger.info(f"  image_model: {project.image_model}")
    logger.info(f"  max_workers: {project.max_workers}")


def cmd_styles(args):
    """Analyze novel and generate custom_prompts/ for the chosen style."""
    from lib.core.project import load_project
    from lib.studio.stylist import analyze_novel, generate_custom_prompts
    from lib.studio.screenwriter import SYSTEM_PROMPT

    project, prompts, config = load_project(use_custom=False)
    llm = _make_llm(args.llm, project, system_prompt=SYSTEM_PROMPT)

    text = Path(args.novel).read_text(encoding='utf-8')
    novel_data = analyze_novel(text, llm)
    if not novel_data:
        logger.error("❌ Failed to analyze novel")
        sys.exit(1)

    logger.info(f"\n📊 Novel metadata:")
    logger.info(f"  Genre: {', '.join(novel_data.get('genre', []))}")
    logger.info(f"  POV:   {novel_data.get('pov', 'N/A')}")
    logger.info(f"  Lead:  {novel_data.get('main_character', {}).get('name', 'N/A')}")

    generate_custom_prompts(novel_data, args.style, llm)
    logger.info(f"\n🎬 Done. Run: make casting NOVEL={args.novel} CUSTOM=--custom-prompts")


def cmd_casting(args):
    """Identify characters/locations and save reference JSONs."""
    from lib.core.project import load_project
    from lib.studio.artist import auto_cast_characters
    from lib.studio.screenwriter import SYSTEM_PROMPT

    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_llm(args.llm, project, system_prompt=SYSTEM_PROMPT)

    text = Path(args.novel).read_text(encoding='utf-8')
    auto_cast_characters(text, prompts, config, llm, project)
    logger.info(f"\n✅ Done. Reference JSONs in {project.ref_dir}/")


def cmd_refs(args):
    """Render missing character reference portraits from existing JSONs."""
    from lib.core.project import load_project
    from lib.studio.artist import render_character_refs
    from lib.studio.screenwriter import SYSTEM_PROMPT

    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_llm(args.llm, project, system_prompt=SYSTEM_PROMPT)

    render_character_refs(prompts, config, llm, project)
    logger.info(f"\n✅ Done. Reference PNGs in {project.ref_dir}/")


def cmd_screenplay(args):
    """Run full screenplay + scene keyframe pipeline."""
    from lib.core.project import load_project
    from lib.studio.screenwriter import analyze_scenes_master, SYSTEM_PROMPT
    from lib.studio.artist import load_character_refs, export_image_prompt

    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_llm(args.llm, project, system_prompt=SYSTEM_PROMPT)
    load_character_refs(project)

    text = Path(args.novel).read_text(encoding='utf-8')

    data = analyze_scenes_master(
        text, prompts, config, llm,
        max_workers=project.max_workers,
        character_info=project.character_info,
    )

    if not data or 'scenes' not in data:
        logger.error("❌ Failed to generate screenplay.")
        sys.exit(1)

    # Embed config so downstream commands (qa, storyboard, etc.) have a single source of truth
    data.setdefault('config', config)

    meta_path = project.output_dir / "animation_metadata.json"
    meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    for scene in data['scenes']:
        export_image_prompt(scene, scene['scene_id'], prompts, config, project)

    logger.info(f"\n✅ Done. JSONs in {project.output_dir}/, prompts in {project.image_prompts_dir}/")


def cmd_scenes(args):
    """Generate keyframes for a specific episode (or all)."""
    from lib.core.project import load_project
    from lib.studio.screenwriter import (
        analyze_scenes_for_episode, process_single_scene, SYSTEM_PROMPT
    )
    from lib.studio.artist import load_character_refs

    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_llm(args.llm, project, system_prompt=SYSTEM_PROMPT)
    load_character_refs(project)

    episodes_path = project.output_dir / "animation_episodes.json"
    if not episodes_path.exists():
        logger.error("❌ animation_episodes.json not found. Run 'screenplay' first.")
        sys.exit(1)

    episodes_data = json.loads(episodes_path.read_text(encoding='utf-8'))
    episodes = episodes_data.get('episodes', [])

    scene_arg = args.scene if hasattr(args, 'scene') else 'all'
    if scene_arg != 'all':
        target = int(scene_arg)
        episodes = [e for e in episodes if e.get('episode_id') == target]

    all_episodes = []
    for ep in episodes:
        analyze_scenes_for_episode(
            ep['episode_id'], json.dumps(ep, ensure_ascii=False, indent=2), prompts, config, llm, all_episodes,
            character_info=project.character_info,
        )

    all_scenes = []
    scene_counter = 0
    for ep_counter, data in sorted(all_episodes, key=lambda x: x[0]):
        for scene in data.get('scenes', []):
            scene_counter += 1
            process_single_scene(ep_counter, scene_counter, scene, prompts, config, llm, all_scenes)

    logger.info(f"\n✅ Done. {len(all_scenes)} scene(s) processed.")

    if not all_scenes:
        return

    # Upsert processed scenes into animation_metadata.json (single source of truth)
    meta_path = project.output_dir / "animation_metadata.json"
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding='utf-8'))
        except Exception:
            metadata = {}
    else:
        metadata = {}

    new_ep_ids = {s.get('episode_id') for s in all_scenes if s.get('episode_id')}
    kept = [s for s in metadata.get('scenes', []) if s.get('episode_id') not in new_ep_ids]

    # Assign scene_ids: new scenes follow the kept scenes sequentially
    merged = sorted(kept, key=lambda s: s.get('scene_id', 0))
    next_id = (merged[-1]['scene_id'] + 1) if merged else 1
    for scene in all_scenes:
        scene['scene_id'] = next_id
        next_id += 1
        merged.append(scene)

    metadata['scenes'] = merged
    metadata.setdefault('config', config)
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info(f"✅ animation_metadata.json updated: {len(merged)} total scene(s)")


def cmd_consistency(args):
    """Run continuity enforcer to sync references and scene prompts."""
    from lib.core.project import Project
    from lib.studio.director import run_continuity_pass

    project = Project()
    llm = _make_vision_llm(args.llm, project)
    out = run_continuity_pass(llm, ref_dir=project.ref_dir, max_workers=project.max_workers)
    logger.info(f"✅ animation_metadata.json updated in-place: {out}")


def cmd_storyboard(args):
    """Render scene grid images or individual panels."""
    from lib.core.project import load_project
    from lib.studio.artist import load_character_refs, render_scene_grids, render_panels
    from lib.studio.screenwriter import SYSTEM_PROMPT

    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_llm(args.llm, project)
    load_character_refs(project)

    scene_filter = None
    if hasattr(args, 'scene') and args.scene and args.scene != 'all':
        scene_filter = int(args.scene)

    panel_filter = None
    if hasattr(args, 'panel') and args.panel and args.panel != 'all':
        panel_filter = int(args.panel)

    if panel_filter is not None:
        render_panels(prompts, config, llm, project, scene_filter=scene_filter, panel_filter=panel_filter)
    else:
        render_scene_grids(prompts, config, llm, project, scene_filter=scene_filter)

    logger.info(f"\n✅ Done.")


def cmd_qa(args):
    """Run grid quality gate."""
    from lib.core.project import Project
    from lib.studio.critic import run_quality_gate, print_summary

    project = Project()
    llm = _make_vision_llm(args.llm, project)

    scene_ids = args.scene if hasattr(args, 'scene') and args.scene else None
    panel_ids = args.panel if hasattr(args, 'panel') and args.panel else None
    threshold = args.threshold if hasattr(args, 'threshold') else 5

    report = run_quality_gate(
        llm=llm,
        ref_dir=project.ref_dir,
        scene_ids=scene_ids,
        panel_ids=panel_ids,
        threshold=threshold,
        max_workers=project.max_workers,
    )
    print_summary(report, threshold)

    if report.get('needs_refinement', 0) > 0:
        sys.exit(1)


def cmd_refinement(args):
    """Refine specific panel(s) by reference."""
    from lib.core.project import load_project
    from lib.studio.editor import (
        load_metadata, load_quality_report, refine_panel
    )

    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_vision_llm(args.llm, project)

    metadata = load_metadata()
    quality_prompts = load_quality_report()

    frames = ['start', 'end'] if args.frame == 'both' else [args.frame]

    success = 0
    for frame_type in frames:
        if refine_panel(
            args.scene_id, args.panel_id, frame_type,
            metadata, prompts, config, llm, quality_prompts
        ):
            success += 1

    logger.info(f"\n✅ {success}/{len(frames)} frames refined.")


def cmd_autocut(args):
    """AI-analyze and trim animation clips against panel metadata."""
    from lib.core.project import load_project
    from lib.studio.cutter import run_autocut

    project, _, _ = load_project(use_custom=False)
    if args.model:
        project.text_model = args.model
    llm = _make_vision_llm(args.llm, project)
    run_autocut(
        llm=llm,
        json_path=args.json,
        clips_dir=args.clips_dir,
        out_dir=args.out_dir,
        min_fidelity=args.min_fidelity,
    )
    logger.info(f"\n✅ Done. Trimmed clips in {args.out_dir}/")


def cmd_imgedit(args):
    """Edit an image using selected LLM backend + optional reference images."""
    from lib.core.project import load_project
    from lib.studio.retoucher import edit_image

    project, _, _ = load_project(use_custom=False)
    llm = _make_llm(args.llm, project)
    try:
        edit_image(
            output_path=args.output,
            instruction=args.instruction,
            source_images=args.images,
            llm=llm,
            aspect_ratio=args.aspect_ratio,
            image_size=args.image_size,
        )
        logger.info(f"\n✅ Done: {args.output}")
    except NotImplementedError as e:
        logger.error(f"❌ Selected backend does not support image editing: {e}")
        sys.exit(1)


def cmd_tts(args):
    """Generate speech or SFX (ElevenLabs)."""
    from lib.core.project import Project
    from lib.audio.tts import parse_speech_input, generate_speech, generate_sfx, OPENROUTER_VOICE_MAP

    output = Path(args.output)
    if args.tts_command == "speech":
        voice, tone, text = parse_speech_input(args.text)
        logger.info(f"Generating speech: [{voice}] [{tone}] {text[:60]}...")
        project = Project()
        llm = _make_llm(args.llm, project)
        vmap = OPENROUTER_VOICE_MAP if args.llm == "openrouter" else None
        ok = generate_speech(text, voice, tone, output, llm=llm, voice_map=vmap)
    else:  # sfx
        logger.info(f"Generating SFX: {args.prompt} ({args.duration}s)...")
        ok = generate_sfx(args.prompt, args.duration, output)

    if ok:
        logger.info(f"✅ Saved: {output}")
    else:
        logger.error("❌ Audio generation failed")
        sys.exit(1)


def cmd_dub(args):
    """Smart dubbing pipeline: transcribe → translate → TTS → assemble."""
    from lib.core.project import Project
    from lib.audio.dubbing import run_dubbing

    project = Project()
    run_dubbing(
        video_path=args.video,
        output_path=args.output,
        context_path=args.context or "",
        plan_cache=args.plan_cache,
        transcription_cache=args.transcription_cache,
        api_key=project.gemini_api_key,
    )
    logger.info(f"\n✅ Dubbing done: {args.output}")


def cmd_duck(args):
    """Auto-duck original audio during dubbed speech segments."""
    from lib.audio.ducking import run_ducking

    run_ducking(
        video_path=args.video,
        dubbed_path=args.dubbed,
        output_path=args.output,
        duck_db=args.duck_db,
        threshold_db=args.threshold,
        min_silence_ms=args.min_silence,
        fade_ms=args.fade,
        padding_ms=args.padding,
        do_normalize=args.normalize,
    )
    logger.info(f"\n✅ Ducking done: {args.output}")


def cmd_animation(args):
    """Generate video clips from panel images."""
    from lib.core.project import Project
    from lib.animation.veo import VeoAnimator
    from lib.animation.grok import GrokAnimator

    project = Project()
    panels_dir = project.panels_dir
    out_dir = project.output_dir / "clips"

    meta_file = project.output_dir / "animation_metadata.json"
    if not meta_file.exists():
        logger.error("❌ animation_metadata.json not found")
        sys.exit(1)

    if args.provider == "veo":
        if not project.gemini_api_key:
            logger.error("❌ IMG_AI_API_KEY not set")
            sys.exit(1)
        animator = VeoAnimator(
            api_key=project.gemini_api_key,
            ref_dir=project.ref_dir,
        )

        metadata = json.loads(meta_file.read_text(encoding='utf-8'))
        lookup = {}
        for scene in metadata.get('scenes', []):
            sid = scene['scene_id']
            for panel in scene['panels']:
                key = f"{sid:03d}_{panel['panel_index']:02d}"
                lookup[key] = panel

        start_files = sorted(panels_dir.glob("*_static.png"))
        if not start_files:
            start_files = sorted(panels_dir.glob("*_start.png"))
        if not start_files:
            logger.error(f"No panel images found in {panels_dir}")
            sys.exit(1)

        scene_filter = None
        if hasattr(args, 'scene') and args.scene and args.scene != 'all':
            scene_filter = f"{int(args.scene):03d}"

        for i, start_path in enumerate(start_files):
            parts = start_path.stem.split("_")
            if scene_filter and parts[0] != scene_filter:
                continue
            key = "_".join(parts[:2])
            panel_meta = lookup.get(key, {})
            end_path = panels_dir / start_path.name.replace('_start', '_end')
            animator.animate(start_path, end_path if end_path.exists() else None,
                             panel_meta, i, out_dir)

    elif args.provider == "grok":
        grok_api_key = os.getenv('XAI_API_KEY', '')
        if not grok_api_key:
            logger.error("❌ XAI_API_KEY not set")
            sys.exit(1)
        animator = GrokAnimator(api_key=grok_api_key)
        animator.run_all(meta_file, panels_dir, out_dir)

    else:
        logger.error(f"❌ Unknown provider: {args.provider}")
        sys.exit(1)

    logger.info(f"\n✅ Done. Clips in {out_dir}/")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Video-book pipeline CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--llm', choices=['openrouter', 'gemini', 'grok'], default='openrouter',
        help='LLM backend for text/image generation (default: openrouter)'
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # init
    sub.add_parser('init', help='Validate env and create directories')

    # styles
    p = sub.add_parser('styles', help='Generate custom_prompts/ for a style')
    p.add_argument('novel', help='Novel text file')
    p.add_argument('--style', default='realistic_movie',
                   help='Style preset: vertical_microdrama|realistic_movie|anime|comic_book|graphic_novel|watchmen_style')

    # casting
    p = sub.add_parser('casting', help='Identify characters and save reference JSONs')
    p.add_argument('novel', help='Novel text file')
    p.add_argument('--custom-prompts', action='store_true')

    # refs
    p = sub.add_parser('refs', help='Render missing character reference portraits from existing JSONs')
    p.add_argument('--custom-prompts', action='store_true')

    # screenplay
    p = sub.add_parser('screenplay', help='Full screenplay + keyframe pipeline')
    p.add_argument('novel', help='Novel text file')
    p.add_argument('--custom-prompts', action='store_true')

    # scenes
    p = sub.add_parser('scenes', help='Generate keyframes for episode(s)')
    p.add_argument('scene', nargs='?', default='all', help='Episode number or "all"')
    p.add_argument('--custom-prompts', action='store_true')

    # consistency
    sub.add_parser('consistency', help='Run continuity enforcer')

    # storyboard
    p = sub.add_parser('storyboard', help='Render scene grids or panels')
    p.add_argument('scene', nargs='?', default='all', help='Scene number or "all"')
    p.add_argument('panel', nargs='?', default='all', help='Panel number or "all"')
    p.add_argument('--custom-prompts', action='store_true')

    # qa
    p = sub.add_parser('qa', help='Run grid quality gate')
    p.add_argument('--scene', type=int, nargs='+', help='Scene ID(s) to check')
    p.add_argument('--panel', type=int, nargs='+', help='Panel ID(s) (requires single --scene)')
    p.add_argument('--threshold', type=int, default=5, help='Fidelity threshold (default: 5)')

    # refinement
    p = sub.add_parser('refinement', help='Refine a specific panel')
    p.add_argument('scene_id', type=int)
    p.add_argument('panel_id', type=int)
    p.add_argument('--frame', choices=['start', 'end', 'static', 'both'], default='both')
    p.add_argument('--custom-prompts', action='store_true')

    # animation
    p = sub.add_parser('animation', help='Generate video clips')
    p.add_argument('provider', choices=['veo', 'grok'], help='Animation provider')
    p.add_argument('scene', nargs='?', default='all', help='Scene number or "all"')
    p.add_argument('panel', nargs='?', default='all', help='Panel number or "all"')

    # autocut
    p = sub.add_parser('autocut', help='AI-trim animation clips vs panel metadata')
    p.add_argument('--json', required=True, help='Path to scene JSON (e.g. animation_metadata.json)')
    p.add_argument('--clips-dir', required=True, help='Directory containing source clip_NNN_PPP.mp4 files')
    p.add_argument('--out-dir', required=True, help='Output directory for trimmed clips')
    p.add_argument('--model', default='gemini-2.5-flash', help='Model override for clip analysis backend')
    p.add_argument('--min-fidelity', type=int, default=3, help='Min fidelity score to keep clip (default: 3)')

    # imgedit
    p = sub.add_parser('imgedit', help='Edit an image via selected --llm backend')
    p.add_argument('output', help='Output image path')
    p.add_argument('instruction', help='Edit instruction (e.g. "make the sky purple")')
    p.add_argument('images', nargs='+', help='Source image(s); first is target, rest are references')
    p.add_argument('--aspect-ratio', default='16:9', help='Output aspect ratio (default: 16:9)')
    p.add_argument('--image-size', default='2K', help='Output resolution (default: 2K)')

    # tts
    p = sub.add_parser('tts', help='Generate speech (Gemini TTS) or SFX (ElevenLabs)')
    tts_sub = p.add_subparsers(dest='tts_command', required=True)
    sp = tts_sub.add_parser('speech', help='Generate speech from text')
    sp.add_argument('text', help='Text with optional voice/tone: "Female [tone sad]: Hello"')
    sp.add_argument('output', help='Output audio file (wav/mp3)')
    sp = tts_sub.add_parser('sfx', help='Generate sound effect')
    sp.add_argument('prompt', help='Sound description')
    sp.add_argument('duration', type=float, help='Duration in seconds')
    sp.add_argument('output', help='Output audio file (mp3)')

    # dub
    p = sub.add_parser('dub', help='Smart AI dubbing pipeline (Whisper → Gemini → TTS)')
    p.add_argument('video', help='Input video file (MP4)')
    p.add_argument('output', help='Output dubbed audio (MP3)')
    p.add_argument('context', nargs='?', default='', help='Optional context text file path')
    p.add_argument('--plan-cache', default='dubbing_plan.json', help='Dubbing plan cache file')
    p.add_argument('--transcription-cache', default='transcription_cache.json', help='Whisper cache file')

    # duck
    p = sub.add_parser('duck', help='Auto-duck original audio during dubbed speech')
    p.add_argument('video', help='Input MP4 with original audio')
    p.add_argument('dubbed', help='Dubbed audio MP3')
    p.add_argument('output', help='Output MP3 with ducking applied')
    p.add_argument('--duck-db', type=float, default=-15, help='Volume reduction in dB (default: -15)')
    p.add_argument('--threshold', type=float, default=-40, help='Speech detection threshold dB (default: -40)')
    p.add_argument('--min-silence', type=int, default=300, help='Min silence gap ms (default: 300)')
    p.add_argument('--fade', type=int, default=50, help='Fade length ms (default: 50)')
    p.add_argument('--padding', type=int, default=100, help='Padding around speech ms (default: 100)')
    p.add_argument('--normalize', action='store_true', help='Normalize output volume')

    args = parser.parse_args()

    dispatch = {
        'init': cmd_init,
        'styles': cmd_styles,
        'casting': cmd_casting,
        'refs': cmd_refs,
        'screenplay': cmd_screenplay,
        'scenes': cmd_scenes,
        'consistency': cmd_consistency,
        'storyboard': cmd_storyboard,
        'qa': cmd_qa,
        'refinement': cmd_refinement,
        'animation': cmd_animation,
        'autocut': cmd_autocut,
        'imgedit': cmd_imgedit,
        'tts': cmd_tts,
        'dub': cmd_dub,
        'duck': cmd_duck,
    }
    dispatch[args.command](args)


if __name__ == '__main__':
    main()
