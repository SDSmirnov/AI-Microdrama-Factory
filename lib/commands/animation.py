"""Animation commands: animation, autocut, quick-play."""
import json
import logging
import os
import sys
import argparse
from pathlib import Path

from lib.animation.grok import GrokAnimator
from lib.animation.grok_openrouter import GrokOpenRouterAnimator
from lib.animation.veo import VeoAnimator
from lib.commands.common import _make_llm, _make_vision_llm
from lib.core.project import Project, load_project
from lib.studio.cutter import run_autocut

logger = logging.getLogger(__name__)


def _video_aspect(config: dict) -> str:
    return os.getenv('AI_VIDEO_ASPECT') or config['image_generation'].get('aspect_ratio', '9:16')


def cmd_animation(args):
    project = Project()
    _, prompts, config = load_project(style=args.style)
    video_ar = _video_aspect(config)
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
        animator = VeoAnimator(api_key=project.gemini_api_key, ref_dir=project.ref_dir,
                               aspect_ratio=video_ar, prompts=prompts)

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

        panel_filter = None
        if hasattr(args, 'panel') and args.panel and args.panel != 'all':
            panel_filter = f"{int(args.panel):02d}"

        failures = 0
        if static_files:
            for i, start_path in enumerate(static_files):
                parts = start_path.stem.split("_")
                if scene_filter and parts[0] != scene_filter:
                    continue
                if panel_filter and parts[1] != panel_filter:
                    continue

                key = "_".join(parts[:2])
                panel_meta = lookup.get(key, {})
                if animator.animate(start_path, None, panel_meta, i, out_dir) is None:
                    failures += 1
        else:
            for i, start_path in enumerate(start_files):
                parts = start_path.stem.split("_")
                if scene_filter and parts[0] != scene_filter:
                    continue
                if panel_filter and parts[1] != panel_filter:
                    continue
                key = "_".join(parts[:2])
                panel_meta = lookup.get(key, {})
                end_path = panels_dir / start_path.name.replace('_start', '_end')
                if animator.animate(start_path, end_path if end_path.exists() else None,
                                    panel_meta, i, out_dir) is None:
                    failures += 1
        if failures:
            logger.error(f"❌ {failures} panel(s) failed to animate")
            sys.exit(1)

    elif args.provider == "grok":
        grok_api_key = os.getenv('XAI_API_KEY', '')
        if not grok_api_key:
            logger.error("❌ XAI_API_KEY not set")
            sys.exit(1)
        scene_filter = int(args.scene) if getattr(args, 'scene', None) not in (None, 'all') else None
        panel_filter = int(args.panel) if getattr(args, 'panel', None) not in (None, 'all') else None
        animator = GrokAnimator(api_key=grok_api_key, aspect_ratio=video_ar, prompts=prompts)
        try:
            animator.run_all(meta_file, panels_dir, out_dir, scene_filter=scene_filter, panel_filter=panel_filter)
        except RuntimeError as e:
            logger.error(f"❌ {e}")
            sys.exit(1)

    elif args.provider == "grok-openrouter":
        if not project.openrouter_api_key:
            logger.error("❌ OPENROUTER_API_KEY not set")
            sys.exit(1)
        scene_filter = int(args.scene) if getattr(args, 'scene', None) not in (None, 'all') else None
        panel_filter = int(args.panel) if getattr(args, 'panel', None) not in (None, 'all') else None
        from lib.studio.artist import load_character_refs
        load_character_refs(project)
        animator = GrokOpenRouterAnimator(api_key=project.openrouter_api_key,
                                         project=project, prompts=prompts,
                                         aspect_ratio=video_ar)
        try:
            animator.run_all(meta_file, panels_dir, out_dir, scene_filter=scene_filter, panel_filter=panel_filter)
        except RuntimeError as e:
            logger.error(f"❌ {e}")
            sys.exit(1)

    else:
        logger.error(f"❌ Unknown provider: {args.provider}")
        sys.exit(1)

    logger.info(f"\n✅ Done. Clips in {out_dir}/")


def cmd_master_shot(args):
    """Item 8b: experimental 2s static reference clip of a scene's
    arrangement (skip-if-exists; DRY=1 dumps)."""
    project = Project()
    if not project.openrouter_api_key:
        logger.error("❌ OPENROUTER_API_KEY not set")
        sys.exit(1)
    meta_file = project.output_dir / "animation_metadata.json"
    if not meta_file.exists():
        logger.error("❌ animation_metadata.json not found")
        sys.exit(1)
    from lib.studio.artist import load_character_refs
    load_character_refs(project)
    metadata = json.loads(meta_file.read_text(encoding='utf-8'))
    scene = next((s for s in metadata.get('scenes', [])
                  if int(s['scene_id']) == int(args.scene)), None)
    if scene is None:
        logger.error("❌ scene %s not found in animation_metadata.json",
                     args.scene)
        sys.exit(1)
    animator = GrokOpenRouterAnimator(api_key=project.openrouter_api_key,
                                      project=project,
                                      aspect_ratio=_video_aspect(load_project(style=args.style)[2]))
    out = animator.master_shot(scene, project.panels_dir,
                               project.output_dir / "clips")
    if out:
        logger.info("\n✅ Master shot: %s", out)


def cmd_stress_refs(args):
    """Item 9: identity stress test — N neutral-action clips of one
    character ref, then the vision-QA identity pass."""
    project = Project()
    if not project.openrouter_api_key:
        logger.error("❌ OPENROUTER_API_KEY not set")
        sys.exit(1)
    from lib.studio.artist import load_character_refs
    load_character_refs(project)
    metadata = None
    meta_file = project.output_dir / "animation_metadata.json"
    if meta_file.exists():
        metadata = json.loads(meta_file.read_text(encoding='utf-8'))
    animator = GrokOpenRouterAnimator(api_key=project.openrouter_api_key,
                                      project=project)
    out_dir = project.output_dir / "stress_tests"
    animator.stress_refs(args.name, args.gens, out_dir, metadata=metadata)
    if args.no_judge:
        logger.info("\n✅ Stress clips in %s (human review fallback)", out_dir)
        return
    vision = _make_vision_llm(args.llm, project)
    animator.judge_stress(args.name, out_dir, vision_llm=vision)
    logger.info("\n✅ Stress report: %s", out_dir / "report.jsonl")


def cmd_autocut(args):
    project, _, _ = load_project(style=args.style)
    if args.model:
        project.text_model = args.model
    llm = _make_vision_llm(args.llm, project)
    try:
        run_autocut(
            llm=llm,
            json_path=args.json,
            clips_dir=args.clips_dir,
            out_dir=args.out_dir,
            min_fidelity=args.min_fidelity,
            edge_trim=args.edge_trim,
        )
    except RuntimeError as e:
        logger.error(f"❌ {e}")
        sys.exit(1)
    logger.info(f"\n✅ Done. Trimmed clips in {args.out_dir}/")


def cmd_quick_play(args):
    from lib.studio.quickplay import build_quickplay
    project = Project()
    episodes_path = Path(args.json) if args.json else project.output_dir / "animation_episodes.json"
    if not episodes_path.exists():
        logger.error("❌ %s not found", episodes_path)
        sys.exit(1)
    llm = _make_llm(args.llm, project)
    build_quickplay(episodes_path, Path(args.output), llm,
                    workers=args.workers, target_seconds=args.target_seconds)


def register(sub):
    p = sub.add_parser('quick-play',
                       help='Synthesize quickplay.json for 10-second multi-ref clips (Seedance/Kling/Grok)')
    p.add_argument('--json', default=None,
                   help='Source animation_episodes.json (default: cinematic_render/animation_episodes.json)')
    p.add_argument('--output', default='cinematic_render/quickplay.json',
                   help='Output path (default: cinematic_render/quickplay.json)')
    p.add_argument('--workers', type=int, default=5,
                   help='Parallel LLM synthesis workers (default: 5)')
    p.add_argument('--target-seconds', type=int, choices=[6, 8, 10, 15], default=10,
                   help='Target clip duration in seconds (default: 10)')
    p.set_defaults(func=cmd_quick_play)

    p = sub.add_parser('animation', help='Generate video clips')
    p.add_argument('provider', choices=['veo', 'grok', 'grok-openrouter'], help='Animation provider')
    p.add_argument('scene', nargs='?', default='all', help='Scene number or "all"')
    p.add_argument('panel', nargs='?', default='all', help='Panel number or "all"')
    p.set_defaults(func=cmd_animation)

    p = sub.add_parser('master-shot',
                       help='Experimental: 2s static reference clip of one scene arrangement (grok-openrouter)')
    p.add_argument('scene', type=int, help='Scene number')
    p.set_defaults(func=cmd_master_shot)

    p = sub.add_parser('stress-refs',
                       help='Identity stress test: N neutral-action clips of one character ref + vision QA pass')
    p.add_argument('name', help='Character ref name (e.g. "Private-Hu")')
    p.add_argument('--gens', type=int, default=None,
                   help='Number of generations (default: 5, action bank cycled)')
    p.add_argument('--llm', default=None, help='Vision LLM override for the identity pass')
    p.add_argument('--no-judge', action='store_true',
                   help='Skip the vision identity pass (human review fallback)')
    p.set_defaults(func=cmd_stress_refs)

    p = sub.add_parser('autocut', help='AI-trim animation clips vs panel metadata')
    p.add_argument('--json', required=True, help='Path to scene JSON (e.g. animation_metadata.json)')
    p.add_argument('--clips-dir', required=True, help='Directory containing source clip_NNN_PPP.mp4 files')
    p.add_argument('--out-dir', required=True, help='Output directory for trimmed clips')
    p.add_argument('--model', default='google/gemini-3.8-flash', help='Model override for clip analysis backend')
    p.add_argument('--min-fidelity', type=int, default=3, help='Min fidelity score to keep clip (default: 3)')

    def _edge_trim(value):
        v = float(value)  # Item 10a: negative rejected at parse time
        if v < 0:
            raise argparse.ArgumentTypeError("--edge-trim must be >= 0")
        return v

    p.add_argument('--edge-trim', type=_edge_trim, default=0.0,
                   help='Trim head and tail by this many seconds before writing (default: 0.0)')
    p.set_defaults(func=cmd_autocut)
