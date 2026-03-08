"""Storyboard commands: storyboard, qa, apply-qa, accept-qa, rebuild-storyboard, refinement, imgedit, extra-panel."""
import datetime
import json
import logging
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

from lib.commands.common import _make_llm, _make_vision_llm
from lib.core.project import Project, load_project
from lib.core.schemas import SCENE_SCHEMA
from lib.core.utils import atomic_write, grid_dims, load_metadata
from lib.llm.base import retry_on_errors
from lib.studio.artist import (
    load_character_refs,
    render_extra_panel,
    render_panels,
    render_scene_grids,
)
from lib.studio.critic import print_summary, run_quality_gate
from lib.studio.editor import load_quality_report, refine_panel
from lib.studio.retoucher import edit_image as retoucher_edit_image

logger = logging.getLogger(__name__)


def cmd_storyboard(args):
    project, prompts, config = load_project(style=args.style)
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
    project, prompts, config = load_project(style=args.style)
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
        prompts=prompts,
    )
    print_summary(report, threshold)
    if report.get('needs_refinement', 0) > 0:
        sys.exit(1)


def cmd_apply_qa(args):
    project, prompts, config = load_project(style=args.style)
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
    if args.frame == 'both':
        frame_types = config.get('slicing', {}).get('frame_types', [])
        if frame_types and frame_types != ['start', 'end']:
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
    project, prompts, config = load_project(style=args.style)
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


def cmd_accept_qa(args):
    project = Project()
    refined_dir = project.refined_dir
    panels_dir = project.panels_dir

    refined_pngs = [p for p in sorted(refined_dir.glob("*_refined.png")) if p.parent == refined_dir]
    if not refined_pngs:
        logger.info("✅ No refined panels found in refined/. Nothing to accept.")
        return

    date_str = datetime.date.today().strftime("%Y%m%d")
    backup_dir = refined_dir / f"backup-{date_str}"
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
        stem = refined_png.stem
        if not stem.endswith("_refined"):
            logger.warning(f"⚠️  Unexpected filename pattern, skipping: {refined_png.name}")
            skipped += 1
            continue

        original_stem = stem[: -len("_refined")]
        original_name = original_stem + ".png"
        original_path = panels_dir / original_name

        if original_path.exists():
            shutil.copy2(original_path, backup_dir / original_name)
            logger.info(f"  💾 Backed up original: {original_name}")
        else:
            logger.warning(f"  ⚠️  Original panel not found: {original_path}")

        panels_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(refined_png, original_path)
        logger.info(f"  ✅ Promoted: {refined_png.name} → panels/{original_name}")

        shutil.move(str(refined_png), backup_dir / refined_png.name)
        json_sidecar = refined_png.with_suffix(".json")
        if json_sidecar.exists():
            shutil.move(str(json_sidecar), backup_dir / json_sidecar.name)
        accepted += 1

    logger.info(f"\n✅ Accepted {accepted} refined panel(s). Backup: {backup_dir}")
    if skipped:
        logger.info(f"   ⚠️  Skipped {skipped} unexpected file(s).")


def cmd_rebuild_storyboard(args):
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

        panel_imgs = []
        missing = []
        for pidx in range(1, panel_count + 1):
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

        sample = Image.open(panel_imgs[0])
        pw, ph = sample.size
        sample.close()

        grid = Image.new('RGB', (pw * cols, ph * rows))
        for i, img_path in enumerate(panel_imgs):
            r, c = divmod(i, cols)
            panel_img = Image.open(img_path).convert('RGB')
            if panel_img.size != (pw, ph):
                panel_img = panel_img.resize((pw, ph), Image.LANCZOS)
            grid.paste(panel_img, (c * pw, r * ph))
            panel_img.close()

        grid_path = output_dir / f"scene_{sid:03d}_grid_combined.png"
        if grid_path.exists():
            backup_name = f"scene_{sid:03d}_grid_combined_backup-{date_str}.png"
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


def cmd_imgedit(args):
    project, _, _ = load_project(style=args.style)
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


def cmd_extra_panel(args):
    if not re.match(r'^\d+_\d+$', args.index):
        logger.error(f"❌ --index must be N_M format (e.g. 4_5), got: {args.index!r}")
        sys.exit(1)

    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project, system_prompt=prompts['screenplay'])
    load_character_refs(project)

    meta_path = project.output_dir / "animation_metadata.json"
    if not meta_path.exists():
        logger.error("❌ animation_metadata.json not found. Run 'screenplay' first.")
        sys.exit(1)

    metadata = json.loads(meta_path.read_text(encoding='utf-8'))
    scene = next((s for s in metadata.get('scenes', []) if s['scene_id'] == args.scene), None)
    if scene is None:
        logger.error(f"❌ Scene {args.scene} not found in animation_metadata.json")
        sys.exit(1)

    prev_idx, next_idx = (int(x) for x in args.index.split('_'))
    panels = scene.get('panels', [])
    prev_panel = next((p for p in panels if p['panel_index'] == prev_idx), None)
    next_panel = next((p for p in panels if p['panel_index'] == next_idx), None)

    if prev_panel is None:
        logger.warning(f"⚠️  Panel {prev_idx} not found in scene {args.scene} — context will be partial")
    if next_panel is None:
        logger.warning(f"⚠️  Panel {next_idx} not found in scene {args.scene} — context will be partial")

    narrative = Path(args.narrative).read_text(encoding='utf-8')

    char_block = ""
    if project.character_info:
        lines = [f"- {n}: {i.get('video_visual_desc') or i.get('visual_desc', '')}"
                 for n, i in project.character_info.items()]
        char_block = "CHARACTER/LOCATION REFERENCES:\n" + "\n".join(lines)

    prev_ctx = f"Panel {prev_idx} visual_end: {prev_panel['visual_end']}" if prev_panel else f"Panel {prev_idx}: not found"
    next_ctx = f"Panel {next_idx} visual_start: {next_panel['visual_start']}" if next_panel else f"Panel {next_idx}: not found"

    prompt = f"""\
Generate EXACTLY ONE extra micro-panel to insert between panels {prev_idx} and {next_idx} in scene {args.scene}.

## SCENE CONTEXT
Scene {args.scene}: {scene.get('location', '')}
Camera master: {scene.get('camera_master', 'N/A')}
Lighting master: {scene.get('lighting_master', 'N/A')}
{prev_ctx}
{next_ctx}

{char_block}

## INDEPENDENCE LAW (non-negotiable)
This panel is rendered by a model with ZERO memory of any other panel.
Fully restate character appearance, location, shot type, lighting in visual_start and visual_end.
NEVER write "same as before", "same POV", "continues from", etc.

## NARRATIVE FOR THIS EXTRA PANEL
{narrative}

Return a single scene (scene_id={args.scene}) containing exactly 1 panel (panel_index=1).
Match camera_master and lighting_master from context above verbatim in lights_and_camera.
All dialogues, voiceovers and captions MUST be in Russian.
"""

    @retry_on_errors(max_retries=3, backoff_factor=2)
    def _call():
        return llm.make_json(prompt, SCENE_SCHEMA)

    result = _call()
    if not result or 'scenes' not in result or not result['scenes']:
        logger.error("❌ LLM failed to generate extra panel")
        sys.exit(1)

    extra_scene = result['scenes'][0]
    extra_panels = extra_scene.get('panels', [])
    if not extra_panels:
        logger.error("❌ LLM returned scene with no panels")
        sys.exit(1)

    panel = extra_panels[0]
    out_data = {
        "scene_id": args.scene,
        "index": args.index,
        "location": extra_scene.get('location', scene.get('location', '')),
        "camera_master": extra_scene.get('camera_master', scene.get('camera_master', '')),
        "lighting_master": extra_scene.get('lighting_master', scene.get('lighting_master', '')),
        "panel": panel,
    }

    out_json = project.output_dir / f"extra_animation_{args.scene}_{args.index}.json"
    atomic_write(out_json, json.dumps(out_data, ensure_ascii=False, indent=2))
    logger.info(f"✅ Extra panel JSON: {out_json}")

    extra_panels_dir = project.output_dir / "extra_panels"
    out_png = extra_panels_dir / f"{args.scene:03d}_{args.index}_static.png"
    aspect_ratio = config['image_generation'].get('aspect_ratio', '9:16')
    render_extra_panel(extra_scene, panel, out_png, aspect_ratio, project, llm, prompts)


def register(sub):
    p = sub.add_parser('storyboard', help='Render scene grids or panels')
    p.add_argument('scene', nargs='?', default='all', help='Scene number or "all"')
    p.add_argument('panel', nargs='?', default='all', help='Panel number or "all"')
    p.set_defaults(func=cmd_storyboard)

    p = sub.add_parser('qa', help='Run grid quality gate')
    p.add_argument('--scene', type=int, nargs='+', help='Scene ID(s) to check')
    p.add_argument('--panel', type=int, nargs='+', help='Panel ID(s) (requires single --scene)')
    p.add_argument('--threshold', type=int, default=5, help='Fidelity threshold (default: 5)')
    p.set_defaults(func=cmd_qa)

    p = sub.add_parser('apply-qa', help='Refine all needs_refinement panels from quality_report.json')
    p.add_argument('--scene', type=int, default=None, help='Filter by scene ID')
    p.add_argument('--frame', choices=['start', 'end', 'static', 'both'], default='both',
                   help='Frame type to refine (default: both)')
    p.set_defaults(func=cmd_apply_qa)

    sub.add_parser('accept-qa', help='Promote refined panels into panels/, backup originals').set_defaults(func=cmd_accept_qa)

    p = sub.add_parser('rebuild-storyboard', help='Rebuild scene grid images from current panels/, backup originals')
    p.add_argument('scene', nargs='?', default='all', help='Scene number or "all"')
    p.set_defaults(func=cmd_rebuild_storyboard)

    p = sub.add_parser('refinement', help='Refine a specific panel')
    p.add_argument('scene_id', type=int)
    p.add_argument('panel_id', type=int)
    p.add_argument('--frame', choices=['start', 'end', 'static', 'both'], default='both')
    p.set_defaults(func=cmd_refinement)

    p = sub.add_parser('imgedit', help='Edit an image via selected --llm backend')
    p.add_argument('output', help='Output image path')
    p.add_argument('instruction', help='Edit instruction (e.g. "make the sky purple")')
    p.add_argument('images', nargs='+', help='Source image(s); first is target, rest are references')
    p.add_argument('--aspect-ratio', default='16:9', help='Output aspect ratio (default: 16:9)')
    p.add_argument('--image-size', default='2K', help='Output resolution (default: 2K)')
    p.set_defaults(func=cmd_imgedit)

    p = sub.add_parser('extra-panel', help='Generate an extra micro-panel not in the original screenplay')
    p.add_argument('narrative', help='Text file describing the extra panel narrative')
    p.add_argument('--scene', type=int, required=True, help='Scene ID to insert the panel into')
    p.add_argument('--index', required=True,
                   help='Insertion index in N_M format, e.g. 4_5 (between panels 4 and 5)')
    p.set_defaults(func=cmd_extra_panel)
