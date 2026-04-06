"""Animation commands: animation, autocut."""
import json
import logging
import os
import sys

from lib.animation.grok import GrokAnimator
from lib.animation.veo import VeoAnimator
from lib.commands.common import _make_vision_llm
from lib.core.project import Project, load_project
from lib.studio.cutter import run_autocut

logger = logging.getLogger(__name__)


def cmd_animation(args):
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
        animator = VeoAnimator(api_key=project.gemini_api_key, ref_dir=project.ref_dir)

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

        if static_files:
            for i, start_path in enumerate(static_files):
                parts = start_path.stem.split("_")
                if scene_filter and parts[0] != scene_filter:
                    continue
                if panel_filter and parts[1] != panel_filter:
                    continue

                key = "_".join(parts[:2])
                panel_meta = lookup.get(key, {})
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
        scene_filter = int(args.scene) if getattr(args, 'scene', None) not in (None, 'all') else None
        panel_filter = int(args.panel) if getattr(args, 'panel', None) not in (None, 'all') else None
        animator = GrokAnimator(api_key=grok_api_key)
        animator.run_all(meta_file, panels_dir, out_dir, scene_filter=scene_filter, panel_filter=panel_filter)

    else:
        logger.error(f"❌ Unknown provider: {args.provider}")
        sys.exit(1)

    logger.info(f"\n✅ Done. Clips in {out_dir}/")


def cmd_autocut(args):
    project, _, _ = load_project(style=args.style)
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


def register(sub):
    p = sub.add_parser('animation', help='Generate video clips')
    p.add_argument('provider', choices=['veo', 'grok'], help='Animation provider')
    p.add_argument('scene', nargs='?', default='all', help='Scene number or "all"')
    p.add_argument('panel', nargs='?', default='all', help='Panel number or "all"')
    p.set_defaults(func=cmd_animation)

    p = sub.add_parser('autocut', help='AI-trim animation clips vs panel metadata')
    p.add_argument('--json', required=True, help='Path to scene JSON (e.g. animation_metadata.json)')
    p.add_argument('--clips-dir', required=True, help='Directory containing source clip_NNN_PPP.mp4 files')
    p.add_argument('--out-dir', required=True, help='Output directory for trimmed clips')
    p.add_argument('--model', default='gemini-2.5-flash', help='Model override for clip analysis backend')
    p.add_argument('--min-fidelity', type=int, default=3, help='Min fidelity score to keep clip (default: 3)')
    p.set_defaults(func=cmd_autocut)
