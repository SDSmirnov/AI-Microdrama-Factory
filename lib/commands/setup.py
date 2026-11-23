"""Setup commands: init, styles, casting, refs."""
import logging
import sys
from pathlib import Path

from lib.commands.common import _make_llm, _make_vision_llm
from lib.core.project import QA_JUDGE_MODEL, QA_REASONING_EFFORT, Project, load_project
from lib.studio.archivist import CHUNK_CHARS, GLEANINGS
from lib.studio.artist import auto_cast_characters, detail_room_refs, remake_room_refs, render_character_refs, run_room_anchors
from lib.studio.critic import ROOM_QA_PASS_THRESHOLD, run_room_view_qa
from lib.studio.room_qa import run_room_views
from lib.studio.room_sketch import render_sketches
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
    if args.anchor_only:
        from lib.studio.stylist import CUSTOM_DIR, analyze_anchor, with_anchor
        path = CUSTOM_DIR / 'setting.md'
        if not path.exists():
            logger.error(f"❌ {path} missing: run `make styles` first")
            sys.exit(1)
        if not (anchor := analyze_anchor(text, llm)):
            logger.error("❌ no usable world anchor in the reply")
            sys.exit(1)
        path.write_text(with_anchor(path.read_text(encoding='utf-8'), anchor), encoding='utf-8')
        logger.info(f"🌍 {anchor['analog']} → {path} (re-run `make bible`: its prompts read the anchor)")
        return
    novel_data = analyze_novel(text, llm)
    if not novel_data:
        logger.error("❌ Failed to analyze novel")
        sys.exit(1)
    logger.info("\n📊 Novel metadata:")
    logger.info(f"  Genre: {', '.join(novel_data.get('genre', []))}")
    logger.info(f"  POV:   {novel_data.get('pov', 'N/A')}")
    logger.info(f"  Lead:  {novel_data.get('main_character', {}).get('name', 'N/A')}")
    generate_custom_prompts(novel_data, args.style, llm)
    logger.info(f"\n🎬 Done. Run: make casting NOVEL={args.novel}")


def cmd_casting(args):
    """The story bible plans the refs when it has the chapter (or --all); else casting reads the text."""
    from lib.studio.archivist import chapter_window, load_bible
    from lib.studio.bible_casting import cast_from_bible
    project, prompts, config = load_project(style=args.style)
    if not (args.all or args.novel):
        logger.error("❌ casting needs a novel file or --all")
        sys.exit(1)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    bible = load_bible(project.bible_dir)
    chapter = None if args.all else Path(args.novel).stem
    if bible and (chapter is None or chapter_window(bible, chapter) is not None):
        if not config.get('reference_characters', {}).get('enabled', True):
            logger.info("ℹ️  Casting disabled in config")
            return
        s = cast_from_bible(bible, chapter, prompts, llm, project, update=not args.no_update)
        logger.info(f"\n✅ Bible casting: {len(s['written'])} written, {s['current']} current, "
                    f"{len(s['linked'])} linked, {len(s['failed'])} failed, {len(s['orphans'])} orphan(s). "
                    f"Reference JSONs in {project.ref_dir}/")
        if s['failed']:
            logger.error(f"❌ No entry returned for: {', '.join(s['failed'])}. Re-run casting to retry them.")
            sys.exit(2)
        return
    if args.all:
        logger.error(f"❌ --all needs a story bible ({project.bible_dir}/story_bible.json): run `make bible`")
        sys.exit(1)
    if bible:
        logger.warning(f"  ⚠️  story bible has no chapter {chapter!r} — casting from the text")
    text = Path(args.novel).read_text(encoding='utf-8')
    auto_cast_characters(text, prompts, config, llm, project)
    logger.info(f"\n✅ Done. Reference JSONs in {project.ref_dir}/")


def cmd_bible(args):
    from lib.core.prompts import world_anchor
    from lib.studio.archivist import SYSTEM_PROMPT, build_bible, foreshadowed
    project, prompts, _ = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=SYSTEM_PROMPT)  # not the screenplay's film-making rules
    if not (world := world_anchor(prompts.get('setting', ''))):
        logger.warning("  ⚠️  setting.md has no real-world anchor: the bible reads without an era guard "
                       "(make styles ANCHOR_ONLY=1 adds one)")
    paths = [Path(p) for p in args.chapters]
    if missing := [str(p) for p in paths if not p.is_file()]:
        logger.error(f"❌ Missing chapter files: {', '.join(missing)}")
        sys.exit(1)
    bible, failed = build_bible(paths, llm, project.bible_dir, project.max_workers, force=args.force,
                                chunk_chars=args.chunk_chars, gleanings=args.gleanings, world=world)
    rank = {p['id']: i for i, p in enumerate(bible['periods'])}
    entities = bible['entities'].values()
    early = sum(len(foreshadowed(e, rank)) for e in entities)
    variants = sum(len(e.get('variants') or []) for e in entities)
    clashes = sum(len(e.get('conflicts') or []) for e in entities)
    raw = [e['ref_name'] for e in entities if e.get('consolidated') is False]
    logger.info(f"\n✅ Bible: {len(bible['entities'])} entities over {len(bible['periods'])} story period(s), "
                f"{early} feature(s) drawn before first named, {variants} variant(s), {clashes} conflict(s). "
                f"Review {project.bible_dir}/story_bible.md")
    if failed or raw:
        logger.error(f"❌ Incomplete: chapters {failed or '-'}, unconsolidated {raw or '-'}. Re-run (cached calls are kept).")
        sys.exit(2)


def cmd_detail_rooms(args):
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    text = Path(args.novel).read_text(encoding='utf-8')
    detail_room_refs(text, llm, project, force=args.force)
    logger.info(f"\n✅ Done. Enriched room descriptions in {project.ref_dir}/")


def cmd_refs(args):
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    render_character_refs(prompts, config, llm, project,
                          entrance_views_only=getattr(args, 'entrance_views_only', False),
                          no_rooms=getattr(args, 'no_rooms', False),
                          types={t.strip() for t in (getattr(args, 'types', '') or '').split(',')
                                 if t.strip()} or None)
    logger.info(f"\n✅ Done. Reference PNGs in {project.ref_dir}/")


def cmd_remake_room_refs(args):
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    remake_room_refs(config, llm, project, create_only=getattr(args, 'create_only', False))
    logger.info(f"\n✅ Done. Split view PNGs in {project.ref_dir}/")


def cmd_room_sketches(args):
    project, _, config = load_project(style=args.style)
    try:
        rendered = render_sketches(project, config, blender_cmd=getattr(args, 'blender', 'blender'))
    except RuntimeError as exc:
        logger.error(f"  Room sketch rendering failed: {exc}")
        sys.exit(1)
    logger.info(f"\n✅ Done. {len(rendered)} sketch(es) in {project.ref_dir}/")


def cmd_room_anchors(args):
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    run_room_anchors(project, llm)
    logger.info(f"\n✅ Done. Anchor points written to ref JSONs in {project.ref_dir}/")


def cmd_room_plan(args):
    from lib.studio.room_plan import run_room_plans
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    rooms = [r for r in (args.rooms or '').split(',') if r.strip()] or None
    s = run_room_plans(project, llm, config, rooms=rooms, force=args.force)
    logger.info(f"\n✅ Plans: {len(s['planned'])} written ({len(s['with_issues'])} with issues), "
                f"{len(s['skipped'])} kept, {len(s['failed'])} failed. Review *.plan.png in {project.ref_dir}/")
    if s['failed']:
        sys.exit(2)


def cmd_room_views(args):
    project, prompts, config = load_project(style=args.style)
    # Renders and QA share one backend (image_model is unchanged); anchors keep the text model.
    llm = _make_vision_llm(
        args.llm, project, system_prompt=prompts['screenplay'],
        model=QA_JUDGE_MODEL, reasoning_effort=QA_REASONING_EFFORT,
    )
    rooms = [r for r in (args.rooms or '').split(',') if r.strip()] or None
    summary = run_room_views(
        project,
        llm,
        config,
        rooms=rooms,
        use_sketches=not getattr(args, 'no_sketches', False),
        pass_threshold=args.pass_threshold,
        max_attempts=args.max_attempts,
        edit_attempts=args.edit_attempts,
        allow_unverified_vte=getattr(args, 'allow_unverified_vte', False),
        allow_unverified_vfe=getattr(args, 'allow_unverified_vfe', False),
        force=getattr(args, 'force', False),
        blender_cmd=getattr(args, 'blender', 'blender'),
        model=QA_JUDGE_MODEL,
        anchor_llm=_make_llm(args.llm, project, system_prompt=prompts['screenplay']),
    )
    if summary.get('failed_vfe'):
        logger.warning(
            f"  ⚠️  VFE failed description QA for: {', '.join(summary['failed_vfe'])}; "
            "their other views were not rendered. Fix the VFE or re-run with "
            "--allow-unverified-vfe."
        )
    passed = len(summary.get('passed_vte', []))
    failed = len(summary.get('failed_vte', []))
    logger.info(f"\n✅ Room views done: {passed} VTE passed, {failed} failed")
    if failed:
        logger.warning(
            "  ⚠️  Derived views for failed rooms were not rendered. "
            "Re-run with --allow-unverified-vte to override."
        )
    outdoor = summary.get('outdoor', {})
    if outdoor.get('locations'):
        logger.info(f"✅ Outdoor views done: {len(outdoor['locations']) - len(outdoor['failed'])} verified, "
                    f"{len(outdoor['failed'])} failed")
    if outdoor.get('failed'):
        errors = ', '.join(f"{b} ({outdoor['locations'][b].get('error')})" for b in outdoor['failed'])
        logger.warning(f"  ⚠️  Outdoor locations failed: {errors}. A failed View-Primary blocks its station views; "
                       "fix it or re-run with --allow-unverified-vfe.")
    # Stop the make chain: the screenplay would pick room views that were never rendered.
    blocked = (
        any(room.get('error') for room in summary.get('rooms', {}).values())
        or (failed and not getattr(args, 'allow_unverified_vte', False))
        or outdoor.get('failed')
    )
    if blocked:
        sys.exit(2)


def cmd_extra_room_refs_qa(args):
    project, _, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project)
    view_filter = args.view.split(',') if getattr(args, 'view', None) else None
    summary = run_room_view_qa(
        llm=llm,
        project=project,
        max_attempts=args.max_attempts,
        threshold=args.threshold,
        view_filter=view_filter,
    )
    passed = sum(1 for v in summary.values() if v['passed'])
    total = len(summary)
    logger.info(f"\n✅ Done: {passed}/{total} derived room views passed QA (threshold={args.threshold})")


def register(sub):
    sub.add_parser('init', help='Validate env and create directories').set_defaults(func=cmd_init)

    p = sub.add_parser('styles', help='Generate custom_prompts/ for a style')
    p.add_argument('novel', help='Novel text file')
    p.add_argument('--anchor-only', action='store_true',
                   help="Only (re)write setting.md's real-world anchor; the rest of custom_prompts/ stays")
    p.set_defaults(func=cmd_styles)

    p = sub.add_parser('casting', help='Save reference JSONs: planned from the story bible when it has the chapter, '
                                       'else identified from the text')
    p.add_argument('novel', nargs='?', help='Novel text file (its stem is the bible chapter id)')
    p.add_argument('--all', action='store_true', help='Bible casting for every chapter (needs the bible)')
    p.add_argument('--no-update', action='store_true',
                   help='Keep refs written from an older bible (or before it) as they are; only link them')
    p.set_defaults(func=cmd_casting)

    p = sub.add_parser('bible', help='Whole-book story bible: chunked multi-pass collector → entities, features, variants by story time')
    p.add_argument('chapters', nargs='+', help='Chapter files in story order (their stems are chapter ids)')
    p.add_argument('--force', action='store_true', help='Ignore cached LLM calls')
    p.add_argument('--chunk-chars', type=int, default=CHUNK_CHARS,
                   help=f'Chunk size in characters, paragraph-aligned (default: {CHUNK_CHARS})')
    p.add_argument('--gleanings', type=int, default=GLEANINGS,
                   help=f'Max "what did you miss" re-reads per chunk (default: {GLEANINGS})')
    p.set_defaults(func=cmd_bible)

    p = sub.add_parser(
        'detail-rooms',
        help='Enrich room ref visual_desc with named furniture, equipment, and per-character anchors',
    )
    p.add_argument('novel', help='Novel text file')
    p.add_argument('--force', action='store_true', help='Re-process rooms already marked details_applied')
    p.set_defaults(func=cmd_detail_rooms)

    p = sub.add_parser('refs', help='Render missing character reference portraits from existing JSONs')
    p.add_argument('--entrance-views-only', action='store_true',
                   help='Render only View-From-Entrance and View-To-Entrance for rooms')
    p.add_argument('--no-rooms', action='store_true',
                   help='Skip Room and Outdoor views (rendered and QA-gated by room-views)')
    p.add_argument('--types', default='',
                   help='Comma-separated ref types to render, e.g. Outdoor,Vehicle (default: all)')
    p.set_defaults(func=cmd_refs)

    p = sub.add_parser(
        'remake-room-refs',
        help='Split Room/Vehicle refs into separate per-view refs and render them',
    )
    p.add_argument('--json-only', action='store_true', dest='create_only',
                   help='Create missing view JSONs without rendering PNGs or running QA')
    p.set_defaults(func=cmd_remake_room_refs)

    p = sub.add_parser(
        'room-sketches',
        help='Render bare 3D room sketches from anchor_points (requires Blender on PATH)',
    )
    p.add_argument('--blender', default='blender', help='Blender executable (default: blender)')
    p.set_defaults(func=cmd_room_sketches)

    p = sub.add_parser(
        'room-anchors',
        help='Generate spatial anchor_points for View-From-Entrance room refs (idempotent)',
    )
    p.set_defaults(func=cmd_room_anchors)

    p = sub.add_parser(
        'room-plan',
        help='Floor plan first: write checked View-From-Entrance anchors from the description before any render (+ *.plan.png)',
    )
    p.add_argument('--rooms', default=None, help='Comma-separated room base names (default: all)')
    p.add_argument('--force', action='store_true', help='Re-plan rooms that already have anchor_points')
    p.set_defaults(func=cmd_room_plan)

    p = sub.add_parser(
        'room-views',
        help='Truth-aware room and outdoor chains: VFE → VTE QA → anchors/sketch → derived views + QA; outdoor View-Primary QA → anchors/station sketches → three station views + QA',
    )
    p.add_argument('--rooms', default=None,
                   help='Comma-separated room or outdoor base names to process (default: all)')
    p.add_argument('--no-sketches', action='store_true',
                   help='Skip Blender sketches; derived views use VFE + VTE only')
    p.add_argument('--force', action='store_true',
                   help='Re-render VFE/VTE/derived views even when PNGs exist')
    p.add_argument('--allow-unverified-vte', action='store_true',
                   help='Render derived views even when the VTE did not pass QA')
    p.add_argument('--allow-unverified-vfe', action='store_true',
                   help='Build VTE/derived views (outdoor: station views) even when the VFE (outdoor: View-Primary) failed description QA')
    p.add_argument('--pass-threshold', type=int, default=ROOM_QA_PASS_THRESHOLD,
                   help=f'Overall score required to accept a view (default: {ROOM_QA_PASS_THRESHOLD})')
    p.add_argument('--max-attempts', type=int, default=3,
                   help='Max QA attempts per view (default: 3)')
    p.add_argument('--edit-attempts', type=int, default=1,
                   help='Max targeted edits per QA attempt (default: 1)')
    p.add_argument('--blender', default='blender', help='Blender executable (default: blender)')
    p.set_defaults(func=cmd_room_views)

    p = sub.add_parser(
        'extra-room-refs-qa',
        help='QA and auto-regenerate the 4 derived room views (left-wall, right-wall, center×2)',
    )
    p.add_argument('--threshold', type=int, default=ROOM_QA_PASS_THRESHOLD,
                   help=f'Min score to pass (default: {ROOM_QA_PASS_THRESHOLD})')
    p.add_argument('--max-attempts', type=int, default=3, help='Max regeneration attempts per view (default: 3)')
    p.add_argument('--view', default=None,
                   help='Comma-separated view suffixes to limit QA (default: all 4 derived views)')
    p.set_defaults(func=cmd_extra_room_refs_qa)
