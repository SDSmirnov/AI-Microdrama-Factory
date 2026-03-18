"""Setup commands: init, styles, casting, refs."""
import logging
import sys
from pathlib import Path

from lib.commands.common import _make_llm
from lib.core.project import Project, load_project
from lib.studio.artist import auto_cast_characters, remake_room_refs, render_character_refs, run_room_anchors
from lib.studio.stylist import analyze_novel, generate_custom_prompts

logger = logging.getLogger(__name__)


def cmd_init(args):
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
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
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
    logger.info(f"\n🎬 Done. Run: make casting NOVEL={args.novel}")


def cmd_casting(args):
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    text = Path(args.novel).read_text(encoding='utf-8')
    auto_cast_characters(text, prompts, config, llm, project)
    logger.info(f"\n✅ Done. Reference JSONs in {project.ref_dir}/")


def cmd_refs(args):
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    render_character_refs(prompts, config, llm, project)
    logger.info(f"\n✅ Done. Reference PNGs in {project.ref_dir}/")


def cmd_remake_room_refs(args):
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    remake_room_refs(config, llm, project)
    logger.info(f"\n✅ Done. Split view PNGs in {project.ref_dir}/")


def cmd_room_anchors(args):
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    run_room_anchors(project, llm)
    logger.info(f"\n✅ Done. Anchor points written to ref JSONs in {project.ref_dir}/")


def register(sub):
    sub.add_parser('init', help='Validate env and create directories').set_defaults(func=cmd_init)

    p = sub.add_parser('styles', help='Generate custom_prompts/ for a style')
    p.add_argument('novel', help='Novel text file')
    p.set_defaults(func=cmd_styles)

    p = sub.add_parser('casting', help='Identify characters and save reference JSONs')
    p.add_argument('novel', help='Novel text file')
    p.set_defaults(func=cmd_casting)

    p = sub.add_parser('refs', help='Render missing character reference portraits from existing JSONs')
    p.set_defaults(func=cmd_refs)

    p = sub.add_parser(
        'remake-room-refs',
        help='Split Room/Vehicle refs into separate per-view refs and render them',
    )
    p.set_defaults(func=cmd_remake_room_refs)

    p = sub.add_parser(
        'room-anchors',
        help='Generate spatial anchor_points for View-From-Entrance room refs (idempotent)',
    )
    p.set_defaults(func=cmd_room_anchors)
