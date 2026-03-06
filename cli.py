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
    python cli.py apply-qa [--scene N] [--frame start|end|static|both]
    python cli.py accept-qa
    python cli.py rebuild-storyboard [SCENE|all]
    python cli.py refinement SCENE PANEL [--frame start|end|both]
    python cli.py animation PROVIDER SCENE PANEL [--frame start|end]

    # Post-production tools
    python cli.py autocut --json scene.json --clips-dir clips/ --out-dir cut/
    python cli.py imgedit output.png "make the sky purple" source.png [ref.png ...]
    python cli.py tts speech "Female [tone sad]: Hello world" out.wav
    python cli.py tts sfx "Loud explosion" 3 expl.mp3
    python cli.py voiceover [--out-dir cinematic_render/voiceover] [--output voiceover.sh]
    python cli.py dub video.mp4 output.mp3 [context.txt]
    python cli.py duck video.mp4 dubbed.mp3 output.mp3
"""
import argparse
import datetime
import json
import logging
import os
import re
import shlex
import shutil
import stat
import sys
from pathlib import Path

from PIL import Image

from lib.animation.grok import GrokAnimator
from lib.animation.veo import VeoAnimator
from lib.audio.dubbing import run_dubbing
from lib.audio.ducking import run_ducking
from lib.audio.tts import OPENROUTER_VOICE_MAP, generate_sfx, generate_speech, parse_speech_input
from lib.core.project import Project, load_project
from lib.core.utils import grid_dims
from lib.llm.gemini import GeminiLLM
from lib.llm.grok import GrokLLM
from lib.llm.openrouter import OpenRouterLLM
from lib.studio.artist import (
    auto_cast_characters,
    export_image_prompt,
    load_character_refs,
    render_character_refs,
    render_panels,
    render_scene_grids,
)
from lib.studio.critic import print_summary, run_quality_gate
from lib.studio.cutter import run_autocut
from lib.studio.director import run_continuity_pass
from lib.core.utils import load_metadata
from lib.studio.editor import load_quality_report, refine_panel
from lib.studio.retoucher import edit_image as retoucher_edit_image
from lib.studio.screenwriter import (
    SYSTEM_PROMPT,
    analyze_scenes_master,
    merge_scenes,
    run_scenes_pipeline,
)
from lib.studio.stylist import analyze_novel, generate_custom_prompts

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
        if not project.gemini_api_key:
            logger.error("❌ IMG_AI_API_KEY or GOOGLE_API_KEY not set")
            sys.exit(1)
        return GeminiLLM(
            api_key=project.gemini_api_key,
            text_model=project.text_model,
            image_model=project.image_model,
        )
    elif llm_type == "grok":
        if not project.grok_api_key:
            logger.error("❌ XAI_API_KEY not set")
            sys.exit(1)
        return GrokLLM(api_key=project.grok_api_key)
    else:  # openrouter (default)
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
    project = Project()
    project.ensure_dirs()
    errors = project.validate_env(llm_type=args.llm)
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
    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_llm(args.llm, project, system_prompt=SYSTEM_PROMPT)

    text = Path(args.novel).read_text(encoding='utf-8')
    auto_cast_characters(text, prompts, config, llm, project)
    logger.info(f"\n✅ Done. Reference JSONs in {project.ref_dir}/")


def cmd_refs(args):
    """Render missing character reference portraits from existing JSONs."""
    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_llm(args.llm, project, system_prompt=SYSTEM_PROMPT)

    render_character_refs(prompts, config, llm, project)
    logger.info(f"\n✅ Done. Reference PNGs in {project.ref_dir}/")


def cmd_screenplay(args):
    """Run full screenplay + scene keyframe pipeline."""
    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_llm(args.llm, project, system_prompt=SYSTEM_PROMPT)
    load_character_refs(project)

    text = Path(args.novel).read_text(encoding='utf-8')

    data = analyze_scenes_master(
        text, prompts, config, llm,
        max_workers=project.max_workers,
        character_info=project.character_info,
        output_dir=project.output_dir,
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
    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_llm(args.llm, project, system_prompt=SYSTEM_PROMPT)
    load_character_refs(project)

    episodes_path = project.output_dir / "animation_episodes.json"
    if not episodes_path.exists():
        logger.error("❌ animation_episodes.json not found. Run 'screenplay' first.")
        sys.exit(1)

    episodes_data = json.loads(episodes_path.read_text(encoding='utf-8'))
    episodes_list = episodes_data.get('episodes', [])

    scene_arg = args.scene if hasattr(args, 'scene') else 'all'
    if scene_arg != 'all':
        target = int(scene_arg)
        episodes = [e for e in episodes_list if e.get('episode_id') == target]
    else:
        episodes = episodes_list

    all_scenes = run_scenes_pipeline(
        episodes, episodes_list, prompts, config, llm,
        output_dir=project.output_dir,
        character_info=project.character_info,
    )

    logger.info(f"\n✅ Done. {len(all_scenes)} scene(s) processed.")

    if not all_scenes:
        return

    # Upsert processed scenes into animation_metadata.json (single source of truth)
    meta_path = project.output_dir / "animation_metadata.json"
    if meta_path.exists():
        try:
            metadata = json.loads(meta_path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            logger.error(f"❌ Corrupt animation_metadata.json: {e}. Back up and delete the file before retrying.")
            sys.exit(1)
    else:
        metadata = {}

    new_ep_ids = {s.get('episode_id') for s in all_scenes if s.get('episode_id')}
    metadata['scenes'] = merge_scenes(metadata, all_scenes, new_ep_ids, project.panels_dir)
    metadata.setdefault('config', config)
    meta_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info(f"✅ animation_metadata.json updated: {len(metadata['scenes'])} total scene(s)")


def cmd_consistency(args):
    """Run continuity enforcer to sync references and scene prompts."""
    project = Project()
    project.ensure_dirs()
    llm = _make_vision_llm(args.llm, project)
    dry_run = args.dry_run
    if dry_run:
        logger.info("ℹ️  Dry-run mode: ref JSONs will be enriched but PNGs will NOT be regenerated. Run `make refs` to render.")
    out = run_continuity_pass(llm, ref_dir=project.ref_dir, max_workers=project.max_workers, output_dir=project.output_dir, dry_run=dry_run)
    logger.info(f"✅ animation_metadata.json updated in-place: {out}")


def cmd_storyboard(args):
    """Render scene grid images or individual panels."""
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
        output_dir=project.output_dir,
    )
    print_summary(report, threshold)

    if report.get('needs_refinement', 0) > 0:
        sys.exit(1)


def cmd_apply_qa(args):
    """Refine all panels flagged needs_refinement=true in quality_report.json."""
    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_vision_llm(args.llm, project)

    report_path = project.output_dir / "quality_report.json"
    if not report_path.exists():
        logger.error("❌ quality_report.json not found. Run 'qa' first.")
        sys.exit(1)

    report = json.loads(report_path.read_text(encoding='utf-8'))
    panels = [p for p in report.get('panels', []) if p.get('needs_refinement')]

    if args.scene is not None:
        panels = [p for p in panels if p['scene_id'] == args.scene]

    if not panels:
        logger.info("✅ No panels need refinement.")
        return

    logger.info(f"🔧 {len(panels)} panel(s) flagged for refinement.")

    metadata = load_metadata(project.output_dir / "animation_metadata.json")
    quality_prompts = load_quality_report(project.output_dir / "quality_report.json")

    # BUG-7 fix: when --frame not explicitly given, infer from config format
    # to avoid silently failing on static-only projects with default 'both'.
    if args.frame == 'both':
        frame_types = config.get('slicing', {}).get('frame_types', [])
        if frame_types and frame_types != ['start', 'end']:
            # e.g. ['static'] → use 'static'; ['start','end'] → keep 'both'
            frames = frame_types
        else:
            frames = ['start', 'end']
    else:
        frames = [args.frame]

    success = 0
    total = 0
    for panel_info in panels:
        scene_id = panel_info['scene_id']
        panel_id = panel_info['panel_id']
        for frame_type in frames:
            total += 1
            if refine_panel(scene_id, panel_id, frame_type, metadata, prompts, config, llm, quality_prompts, project=project):
                success += 1

    logger.info(f"\n✅ {success}/{total} frame(s) refined.")


def cmd_refinement(args):
    """Refine specific panel(s) by reference."""
    project, prompts, config = load_project(use_custom=args.custom_prompts)
    llm = _make_vision_llm(args.llm, project)

    metadata = load_metadata(project.output_dir / "animation_metadata.json")
    quality_prompts = load_quality_report(project.output_dir / "quality_report.json")

    frames = ['start', 'end'] if args.frame == 'both' else [args.frame]

    success = 0
    for frame_type in frames:
        if refine_panel(
            args.scene_id, args.panel_id, frame_type,
            metadata, prompts, config, llm, quality_prompts, project=project
        ):
            success += 1

    logger.info(f"\n✅ {success}/{len(frames)} frames refined.")


def cmd_autocut(args):
    """AI-analyze and trim animation clips against panel metadata."""
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
    project, _, _ = load_project(use_custom=False)
    llm = _make_llm(args.llm, project)
    try:
        retoucher_edit_image(
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


def cmd_voiceover(args):
    """Generate voiceover.sh — a shell script with one tts call per panel voiceover."""
    project = Project()
    meta_path = project.output_dir / "animation_metadata.json"
    if not meta_path.exists():
        logger.error("❌ animation_metadata.json not found. Run 'screenplay' first.")
        sys.exit(1)

    metadata = json.loads(meta_path.read_text(encoding='utf-8'))
    out_dir = args.out_dir

    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"mkdir -p {shlex.quote(out_dir)}",
        "",
    ]
    count = 0

    for scene in metadata.get('scenes', []):
        scene_id = scene['scene_id']
        for panel in scene.get('panels', []):
            panel_idx = panel.get('panel_index', 0)
            vo_text = (panel.get('voiceover') or '').strip()
            if not vo_text:
                continue

            # Strip "Male/Female Voiceover:" prefix for filename slug
            slug = re.sub(r'^[A-Za-z ]+voiceover\s*:\s*', '', vo_text, flags=re.IGNORECASE)
            slug = re.sub(r'^[A-Za-z]+\s*:\s*', '', slug)
            slug = re.sub(r'\W+', '-', slug, flags=re.UNICODE).strip('-').lower()
            slug = slug[:40]
            if not slug:
                slug = "vo"

            out_file = f"{out_dir}/scene_{scene_id:03d}_{panel_idx:02d}_{slug}.wav"
            lines.append(
                f"python cli.py --llm \"${{LLM:-openrouter}}\" tts speech {shlex.quote(vo_text)} {shlex.quote(out_file)}"
            )
            count += 1

    lines.append("")
    script_path = Path(args.output)
    script_path.write_text("\n".join(lines), encoding='utf-8')
    script_path.chmod(script_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    logger.info(f"✅ {script_path} written: {count} voiceover(s)")


def cmd_duck(args):
    """Auto-duck original audio during dubbed speech segments."""
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


def cmd_accept_qa(args):
    """Accept refined panels: backup originals, promote refined PNGs into panels/."""
    project = Project()
    refined_dir = project.refined_dir
    panels_dir = project.panels_dir

    refined_pngs = sorted(refined_dir.glob("*_refined.png"))
    # Exclude files inside backup subdirectories
    refined_pngs = [p for p in refined_pngs if p.parent == refined_dir]

    if not refined_pngs:
        logger.info("✅ No refined panels found in refined/. Nothing to accept.")
        return

    date_str = datetime.date.today().strftime("%Y%m%d")
    backup_dir = refined_dir / f"backup-{date_str}"
    # Handle same-day collisions
    if backup_dir.exists():
        suffix = 1
        while (refined_dir / f"backup-{date_str}-{suffix}").exists():
            suffix += 1
        backup_dir = refined_dir / f"backup-{date_str}-{suffix}"
    backup_dir.mkdir(parents=True)
    logger.info(f"📁 Backup dir: {backup_dir}")

    accepted = 0
    skipped = 0
    for refined_png in refined_pngs:
        # e.g. 001_02_start_refined.png → 001_02_start.png
        stem = refined_png.stem  # "001_02_start_refined"
        if not stem.endswith("_refined"):
            logger.warning(f"⚠️  Unexpected filename pattern, skipping: {refined_png.name}")
            skipped += 1
            continue

        original_stem = stem[: -len("_refined")]  # "001_02_start"
        original_name = original_stem + ".png"
        original_path = panels_dir / original_name

        # 1. Backup original panel (before overwriting)
        if original_path.exists():
            shutil.copy2(original_path, backup_dir / original_name)
            logger.info(f"  💾 Backed up original: {original_name}")
        else:
            logger.warning(f"  ⚠️  Original panel not found: {original_path}")

        # 2. Promote refined PNG into panels/ (overwrite original)
        panels_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(refined_png, original_path)
        logger.info(f"  ✅ Promoted: {refined_png.name} → panels/{original_name}")

        # 3. Move refined PNG (and its JSON sidecar) to backup
        shutil.move(str(refined_png), backup_dir / refined_png.name)
        json_sidecar = refined_png.with_suffix(".json")
        if json_sidecar.exists():
            shutil.move(str(json_sidecar), backup_dir / json_sidecar.name)

        accepted += 1

    logger.info(f"\n✅ Accepted {accepted} refined panel(s). Backup: {backup_dir}")
    if skipped:
        logger.info(f"   ⚠️  Skipped {skipped} unexpected file(s).")


def cmd_rebuild_storyboard(args):
    """Rebuild scene_NNN_grid_combined.png from current panels/, backup originals."""
    project = Project()
    panels_dir = project.panels_dir
    output_dir = project.output_dir

    meta_path = output_dir / "animation_metadata.json"
    if not meta_path.exists():
        logger.error("❌ animation_metadata.json not found. Run 'screenplay' first.")
        sys.exit(1)

    metadata = json.loads(meta_path.read_text(encoding='utf-8'))
    config = metadata.get('config', {})
    panels_per_scene = config.get('format', {}).get('panels_per_scene', 9)
    cols, rows = grid_dims(panels_per_scene)

    scene_filter = None
    if hasattr(args, 'scene') and args.scene and args.scene != 'all':
        scene_filter = int(args.scene)

    scenes = metadata.get('scenes', [])
    if scene_filter is not None:
        scenes = [s for s in scenes if s['scene_id'] == scene_filter]

    if not scenes:
        logger.error(f"❌ No scenes found{' for scene ' + str(scene_filter) if scene_filter else ''}.")
        sys.exit(1)

    date_str = datetime.date.today().strftime("%Y%m%d")
    rebuilt = 0
    skipped = 0

    for scene in scenes:
        sid = scene['scene_id']
        panel_count = len(scene.get('panels', []))
        if panel_count == 0:
            logger.warning(f"  ⚠️  Scene {sid}: no panels in metadata, skipping")
            skipped += 1
            continue

        # Collect panel images in order
        panel_imgs = []
        missing = []
        for pidx in range(1, panel_count + 1):
            # Prefer _static, fall back to _start
            for suffix in ('_static', '_start'):
                p = panels_dir / f"{sid:03d}_{pidx:02d}{suffix}.png"
                if p.exists():
                    panel_imgs.append(p)
                    break
            else:
                missing.append(pidx)

        if missing:
            logger.warning(f"  ⚠️  Scene {sid}: missing panel(s) {missing}, skipping")
            skipped += 1
            continue

        # Determine grid size from the first panel
        sample = Image.open(panel_imgs[0])
        pw, ph = sample.size
        sample.close()

        grid_w, grid_h = pw * cols, ph * rows
        grid = Image.new('RGB', (grid_w, grid_h))

        for i, img_path in enumerate(panel_imgs):
            r, c = divmod(i, cols)
            panel_img = Image.open(img_path).convert('RGB')
            if panel_img.size != (pw, ph):
                panel_img = panel_img.resize((pw, ph), Image.LANCZOS)
            grid.paste(panel_img, (c * pw, r * ph))
            panel_img.close()

        grid_path = output_dir / f"scene_{sid:03d}_grid_combined.png"

        # Backup existing grid
        if grid_path.exists():
            backup_name = f"scene_{sid:03d}_grid_combined_backup-{date_str}.png"
            # Handle same-day collisions
            backup_path = output_dir / backup_name
            collision = 1
            while backup_path.exists():
                backup_path = output_dir / f"scene_{sid:03d}_grid_combined_backup-{date_str}-{collision}.png"
                collision += 1
            shutil.copy2(grid_path, backup_path)
            logger.info(f"  💾 Backed up: scene_{sid:03d}_grid_combined.png → {backup_path.name}")

        grid.save(grid_path)
        logger.info(f"  ✅ Scene {sid}: rebuilt grid ({panel_count} panels, {cols}x{rows})")
        rebuilt += 1

    logger.info(f"\n✅ Rebuilt {rebuilt} grid(s). Skipped {skipped}.")


def cmd_animation(args):
    """Generate video clips from panel images."""
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

        static_files = sorted(panels_dir.glob("*_static.png"))
        start_files = sorted(panels_dir.glob("*_start.png"))
        if not static_files and not start_files:
            logger.error(f"No panel images found in {panels_dir}")
            sys.exit(1)

        scene_filter = None
        if hasattr(args, 'scene') and args.scene and args.scene != 'all':
            scene_filter = f"{int(args.scene):03d}"

        # Prefer _static panels (single-frame render), fall back to _start/_end pairs
        if static_files:
            for i, start_path in enumerate(static_files):
                parts = start_path.stem.split("_")
                if scene_filter and parts[0] != scene_filter:
                    continue
                key = "_".join(parts[:2])
                panel_meta = lookup.get(key, {})
                # _static has no separate end frame
                animator.animate(start_path, None, panel_meta, i, out_dir)
        else:
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
    p = sub.add_parser('consistency', help='Run continuity enforcer')
    p.add_argument('--dry-run', action=argparse.BooleanOptionalAction, default=True,
                   help='Skip image regeneration (default: on); use --no-dry-run to render refs')

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

    # apply-qa
    p = sub.add_parser('apply-qa', help='Refine all needs_refinement panels from quality_report.json')
    p.add_argument('--scene', type=int, default=None, help='Filter by scene ID')
    p.add_argument('--frame', choices=['start', 'end', 'static', 'both'], default='both',
                   help='Frame type to refine (default: both)')
    p.add_argument('--custom-prompts', action='store_true')

    # accept-qa
    sub.add_parser('accept-qa', help='Promote refined panels into panels/, backup originals')

    # rebuild-storyboard
    p = sub.add_parser('rebuild-storyboard', help='Rebuild scene grid images from current panels/, backup originals')
    p.add_argument('scene', nargs='?', default='all', help='Scene number or "all"')

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

    # voiceover
    p = sub.add_parser('voiceover', help='Generate voiceover.sh script from animation_metadata.json')
    p.add_argument('--out-dir', default='cinematic_render/voiceover',
                   help='Output directory for generated .wav files (default: cinematic_render/voiceover)')
    p.add_argument('--output', default='voiceover.sh',
                   help='Path for the generated shell script (default: voiceover.sh)')

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
        'apply-qa': cmd_apply_qa,
        'accept-qa': cmd_accept_qa,
        'rebuild-storyboard': cmd_rebuild_storyboard,
        'refinement': cmd_refinement,
        'animation': cmd_animation,
        'autocut': cmd_autocut,
        'imgedit': cmd_imgedit,
        'tts': cmd_tts,
        'voiceover': cmd_voiceover,
        'dub': cmd_dub,
        'duck': cmd_duck,
    }

    def _log_command(event: str):
        ts = datetime.datetime.now().isoformat(timespec='seconds')
        argv = shlex.join(sys.argv[1:])
        with open('project.log', 'a', encoding='utf-8') as f:
            f.write(f"[{ts}] [{event}] {argv}\n")

    _log_command('start')
    try:
        dispatch[args.command](args)
    except FileNotFoundError as e:
        logger.error(f"❌ {e}")
        sys.exit(1)
    finally:
        _log_command('ended')


if __name__ == '__main__':
    main()
