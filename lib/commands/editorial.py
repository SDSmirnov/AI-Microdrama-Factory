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
    text = Path(args.novel).read_text(encoding='utf-8')
    setting = prompts.get('setting', '')

    output_path = Path(args.output) if args.output else (
        Path(args.novel).with_name(Path(args.novel).stem + '_fixed.txt')
    )

    result = fix_novel(text, llm, max_workers=args.workers, setting=setting)
    if not result:
        logger.error("❌ fix_novel returned empty result")
        sys.exit(1)

    atomic_write(output_path, result)
    logger.info(f"\n✅ Done. Fixed text + appendix → {output_path}")


def register(sub):
    p = sub.add_parser(
        'logic',
        help='Fix logic/physics/space bugs in novel text and generate scene prerequisites appendix',
    )
    p.add_argument('novel', help='Input novel text file')
    p.add_argument('--output', default=None, help='Output file (default: <novel>_fixed.txt)')
    p.add_argument('--workers', type=int, default=5, help='Parallel chapter workers (default: 5)')
    p.set_defaults(func=cmd_logic)
