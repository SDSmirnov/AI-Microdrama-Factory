"""Editorial commands: logic (logic/physics/space fix + scene prerequisites appendix)."""
import logging
import sys
from pathlib import Path

from lib.commands.common import _make_llm
from lib.core.project import load_project
from lib.core.utils import atomic_write
from lib.studio.fixer import fix_novel

logger = logging.getLogger(__name__)


def cmd_logic(args):
    project, prompts, _config = load_project(style=args.style)
    llm = _make_llm(args.llm, project)
    setting = prompts.get('setting', '')
    source = Path(args.novel)
    if source.is_dir():
        return _logic_book(args, project, llm, setting, source)
    text = source.read_text(encoding='utf-8')

    output_path = Path(args.output) if args.output else (
        Path(args.novel).with_name(Path(args.novel).stem + '_fixed.txt')
    )

    result = fix_novel(text, llm, max_workers=args.workers, setting=setting)
    if not result:
        logger.error("❌ fix_novel returned empty result")
        sys.exit(1)

    atomic_write(output_path, result)
    logger.info(f"\n✅ Done. Fixed text + appendix → {output_path}")


def _logic_book(args, project, llm, setting: str, source: Path):
    """Episode directory mode: raw episodes → fixed prose + setup appendix; --bible: the bible's conflicts."""
    from lib.studio.archivist import load_bible
    from lib.studio.fixer import fix_book, fix_book_conflicts
    if args.bible:
        bible = load_bible(project.bible_dir)
        if not bible:
            logger.error(f"❌ --bible needs {project.bible_dir}/story_bible.json: run `make bible`")
            sys.exit(1)
        fixed, failed = fix_book_conflicts(source, bible, llm, args.workers, setting, force=args.force)
        logger.info(f"\n✅ Conflicts fixed in {len(fixed)} episode(s). Re-run `make bible` to check them.")
    else:
        if not args.output:
            logger.error("❌ a directory of raw episodes needs --output DIR for the fixed ones")
            sys.exit(1)
        failed = fix_book(source, Path(args.output), llm, args.workers, setting, force=args.force)
        logger.info(f"\n✅ Fixed episodes → {args.output}/, setup appendix → {args.output}/appendix/")
    if failed:
        logger.error(f"❌ No usable fix for: {', '.join(failed)}. Re-run to retry (the others are cached).")
        sys.exit(2)


def register(sub):
    p = sub.add_parser(
        'logic',
        help='Fix logic/physics/space bugs in novel text and generate scene prerequisites appendix',
    )
    p.add_argument('novel', help='Novel text file, or a directory of raw episode files (book mode)')
    p.add_argument('--output', default=None,
                   help='File: output file (default: <novel>_fixed.txt). Directory: where fixed episodes go')
    p.add_argument('--bible', action='store_true',
                   help='Book mode: fix the story bible\'s cross-episode conflicts in this directory of fixed episodes')
    p.add_argument('--force', action='store_true', help='Book mode: ignore cached fixes')
    p.add_argument('--workers', type=int, default=5, help='Parallel chapter workers (default: 5)')
    p.set_defaults(func=cmd_logic)
