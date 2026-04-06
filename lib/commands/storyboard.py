"""Storyboard commands: storyboard, rebuild-storyboard, imgedit, extra-panel."""
import datetime
import json
import logging
import os
import re
import shutil
import sys
from pathlib import Path

from PIL import Image

from lib.commands.common import _make_llm, _make_vision_llm
from lib.core.project import Project, load_project
from lib.core.prompts import TARGET_LANGUAGE
from lib.core.schemas import SCENE_SCHEMA
from lib.core.utils import atomic_write, grid_dims, load_metadata
from lib.llm.base import retry_on_errors
from lib.studio.artist import (
    _render_single_panel,
    load_character_refs,
    render_extra_panel,
    render_full_frame_panel,
    render_panels,
    render_scene_grids,
)
from lib.studio.critic import analyze_panel, load_ref_catalog
from lib.studio.editor import refine_panel
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
        cols, rows, _ = grid_dims(panel_count)

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
All dialogues, voiceovers and captions MUST be in {TARGET_LANGUAGE}.
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


def cmd_full_frame(args):
    """Re-render an existing panel at a wider aspect ratio using the source PNG as reference."""
    project, prompts, config = load_project(style=args.style)
    llm = _make_llm(args.llm, project)
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

    panel = next((p for p in scene.get('panels', []) if p['panel_index'] == args.panel), None)
    if panel is None:
        logger.error(f"❌ Panel {args.panel} not found in scene {args.scene}")
        sys.exit(1)

    source_png = project.panels_dir / f"{args.scene:03d}_{args.panel:02d}_static.png"
    if not source_png.exists():
        logger.error(f"❌ Source panel not found: {source_png}. Run storyboard/panel render first.")
        sys.exit(1)

    aspect_ratio = args.aspect_ratio
    ar_slug = aspect_ratio.replace(':', 'x')
    full_frames_dir = project.output_dir / "full_frames"
    out_png = full_frames_dir / f"{args.scene:03d}_{args.panel:02d}_fullframe_{ar_slug}.png"

    render_full_frame_panel(scene, panel, source_png, out_png, aspect_ratio, project, llm, prompts)


def cmd_panel_by_panel_qa(args):
    """Render each panel in a scene, run QA, and refine in-place up to max_attempts times."""
    project, prompts, config = load_project(style=args.style)
    img_llm = _make_llm(args.llm, project)
    vision_llm = _make_vision_llm(args.llm, project)
    load_character_refs(project)

    scene_id = int(args.scene)
    panel_filter = int(args.panel) if args.panel not in (None, 'all') else None
    max_attempts = args.max_attempts
    threshold = args.threshold

    meta_path = project.output_dir / "animation_metadata.json"
    if not meta_path.exists():
        logger.error("❌ animation_metadata.json not found. Run 'screenplay' first.")
        sys.exit(1)

    metadata = load_metadata(meta_path)
    scene = next((s for s in metadata.get('scenes', []) if s['scene_id'] == scene_id), None)
    if scene is None:
        logger.error(f"❌ Scene {scene_id} not found in animation_metadata.json")
        sys.exit(1)

    panels = scene.get('panels', [])
    if panel_filter is not None:
        panels = [p for p in panels if p['panel_index'] == panel_filter]
    if not panels:
        logger.error(f"❌ No panels found for scene {scene_id}" + (f" panel {panel_filter}" if panel_filter else ""))
        sys.exit(1)

    aspect_ratio = config['image_generation'].get('aspect_ratio', '9:16')
    ref_catalog = load_ref_catalog(project.ref_dir)
    passed = 0

    for panel in panels:
        pid = panel['panel_index']
        logger.info(f"\n{'='*60}")
        logger.info(f"🎬 Scene {scene_id} · Panel {pid}/{len(panels)}")
        logger.info(f"{'='*60}")

        _render_single_panel(scene, panel, scene_id, 'static', aspect_ratio, project, img_llm, prompts)

        panel_path = project.panels_dir / f"{scene_id:03d}_{pid:02d}_static.png"
        if not panel_path.exists():
            logger.error(f"  ❌ Panel {pid} failed to render, skipping")
            continue

        for attempt in range(1, max_attempts + 1):
            logger.info(f"\n  🔍 QA (attempt {attempt}/{max_attempts})...")
            with Image.open(panel_path) as panel_img:
                panel_result = analyze_panel(
                    llm=vision_llm,
                    panel_img=panel_img,
                    panel_meta=panel,
                    scene_meta=scene,
                    ref_catalog=ref_catalog,
                    scene_id=scene_id,
                    panel_id=pid,
                    threshold=threshold,
                    prompts=prompts,
                )
            if not panel_result.get('needs_refinement'):
                logger.info(f"  ✅ Panel {pid} passed QA (fidelity={panel_result.get('fidelity', '?')})")
                passed += 1
                break

            if attempt == max_attempts:
                logger.warning(
                    f"  ⚠️  Panel {pid} still needs refinement after {max_attempts} attempt(s) "
                    f"(fidelity={panel_result.get('fidelity', '?')})"
                )
                break

            logger.info(f"  🔧 Refining panel {pid} (attempt {attempt})...")
            quality_prompts = {
                f"{scene_id}_{pid}": {
                    'refinement_prompt': panel_result.get('refinement_prompt', ''),
                    'fidelity': panel_result.get('fidelity', 10),
                    'composition_match': panel_result.get('composition_match', 10),
                }
            }
            logger.info(f"  🔧 Results: {scene_id} {pid} {panel_result}")

            refined_path = project.refined_dir / f"{scene_id:03d}_{pid:02d}_static_refined.png"
            if refined_path.exists():
                refined_path.unlink()

            if not refine_panel(scene_id, pid, 'static', metadata, config, vision_llm, quality_prompts, project=project, prompts=prompts):
                logger.error(f"  ❌ Refinement failed for panel {pid}, stopping retries")
                break

            if refined_path.exists():
                shutil.copy2(refined_path, panel_path)
                refined_path.unlink()
                sidecar = refined_path.with_suffix('.json')
                if sidecar.exists():
                    sidecar.unlink()
                logger.info(f"  ✅ Promoted refined → panels/{panel_path.name}")

    total = len(panels)
    logger.info(f"\n✅ Done: {passed}/{total} panel(s) passed QA.")
    if passed < total:
        sys.exit(1)


# ---------------------------------------------------------------------------
# 3D preview — axonometric puppet layout renderer
# ---------------------------------------------------------------------------

def register(sub):
    p = sub.add_parser('storyboard', help='Render scene grids or panels')
    p.add_argument('scene', nargs='?', default='all', help='Scene number or "all"')
    p.add_argument('panel', nargs='?', default='all', help='Panel number or "all"')
    p.set_defaults(func=cmd_storyboard)

    p = sub.add_parser('rebuild-storyboard', help='Rebuild scene grid images from current panels/, backup originals')
    p.add_argument('scene', nargs='?', default='all', help='Scene number or "all"')
    p.set_defaults(func=cmd_rebuild_storyboard)

    p = sub.add_parser('imgedit', help='Edit an image via selected --llm backend')
    p.add_argument('output', help='Output image path')
    p.add_argument('instruction', help='Edit instruction (e.g. "make the sky purple")')
    p.add_argument('images', nargs='+', help='Source image(s); first is target, rest are references')
    p.add_argument('--aspect-ratio', default='16:9', help='Output aspect ratio (default: 16:9)')
    p.add_argument('--image-size', default=os.getenv('AI_IMAGE_SIZE', '2K'),
                   help='Output resolution (default: AI_IMAGE_SIZE env or 2K)')
    p.set_defaults(func=cmd_imgedit)

    p = sub.add_parser('extra-panel', help='Generate an extra micro-panel not in the original screenplay')
    p.add_argument('narrative', help='Text file describing the extra panel narrative')
    p.add_argument('--scene', type=int, required=True, help='Scene ID to insert the panel into')
    p.add_argument('--index', required=True,
                   help='Insertion index in N_M format, e.g. 4_5 (between panels 4 and 5)')
    p.set_defaults(func=cmd_extra_panel)

    p = sub.add_parser(
        'panel-by-panel-with-qa',
        help='Render each panel, run QA, and refine in-place (up to --max-attempts times)',
    )
    p.add_argument('scene', type=int, help='Scene number')
    p.add_argument('panel', nargs='?', default='all', help='Panel number or "all" (default: all)')
    p.add_argument('--threshold', type=int, default=5, help='QA fidelity threshold (default: 5)')
    p.add_argument('--max-attempts', type=int, default=0, dest='max_attempts',
                   help='Max refinement attempts per panel (default: 3)')
    p.set_defaults(func=cmd_panel_by_panel_qa)

    p = sub.add_parser(
        'full-frame',
        help='Re-render an existing panel at a different AR using the source PNG as composition reference',
    )
    p.add_argument('--scene', type=int, required=True, help='Scene ID')
    p.add_argument('--panel', type=int, required=True, help='Panel index')
    p.add_argument('--aspect-ratio', default='16:9', dest='aspect_ratio',
                   help='Target aspect ratio (default: 16:9)')
    p.set_defaults(func=cmd_full_frame)

