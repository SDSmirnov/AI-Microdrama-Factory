"""Storyboard commands: storyboard, qa, apply-qa, accept-qa, rebuild-storyboard, refinement, imgedit, extra-panel, 3d-preview."""
import datetime
import json
import logging
import math
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
    render_panels,
    render_scene_grids,
)
from lib.studio.critic import analyze_panel, load_ref_catalog, print_summary, run_quality_gate
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
            if refine_panel(scene_id, panel_id, frame_type, metadata, config, llm, quality_prompts, project=project, prompts=prompts):
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
            metadata, config, llm, quality_prompts, project=project, prompts=prompts
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

# Cabinet oblique projection constants:
#   Receding Y axis at 45°, foreshortened to 0.5 true scale.
#   0.3536 = cos(45°) * 0.5
_AXO_F = 0.3536

# Color palette for panel-index coloring (up to 12 panels, wraps)
_PREVIEW_PALETTE = [
    (220,  50,  47), ( 38, 139, 210), ( 42, 161, 152), (181, 137,   0),
    (108, 113, 196), (211,  54, 130), (  0, 168, 107), (203,  75,  22),
    (100, 200, 100), (  0, 148, 255), (220, 150,  50), (150, 111, 214),
]

# View-To-* suffix → canonical primary ref suffix (for anchor_points lookup)
_TO_PRIMARY: dict[str, str] = {
    'View-To-Entrance':   'View-From-Entrance',
    'Interior-To-Entrance': 'Interior-From-Entrance',
    'View-Opposite':      'View-Primary',
}


def _to_primary_ref(ref: str) -> str:
    """Map a reversed-axis ref name to its canonical primary ref name."""
    for old, new in _TO_PRIMARY.items():
        if ref.endswith(f'-{old}'):
            return ref[: -len(old)] + new
    return ref


def _axo(x_m: float, y_m: float, z_m: float, scale: float, ox: float, oy: float) -> tuple[int, int]:
    """Cabinet oblique projection: room 3D (X=East, Y=depth, Z=up) → PIL pixels.

    ox/oy: pixel coordinate of the room origin (entrance floor corner).
    Receding axis: Y at 45°, foreshortened 0.5 (0.3536 = cos45 * 0.5).
    """
    rx = (x_m + y_m * _AXO_F) * scale
    ry = (y_m * _AXO_F + z_m) * scale   # raw Y-up; flipped via oy below
    return int(ox + rx), int(oy - ry)


def _resolve_panel_anchor(panel: dict, anchors_by_ref: dict) -> tuple[str | None, dict | None]:
    """Return (canonical_ref, anchor_points) for a single panel's location_references, or (None, None)."""
    for ref in panel.get('location_references', []):
        if ref.endswith(('-View-From-Entrance', '-View-Primary')) and ref in anchors_by_ref:
            return ref, anchors_by_ref[ref]
        canon = _to_primary_ref(ref)
        if canon in anchors_by_ref:
            return canon, anchors_by_ref[canon]
    return None, None


_FONT_REGULAR = [
    '/usr/share/fonts/liberation-sans-fonts/LiberationSans-Regular.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans.ttf',
]
_FONT_BOLD = [
    '/usr/share/fonts/liberation-sans-fonts/LiberationSans-Bold.ttf',
    '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
]


def _load_font(size: int, bold: bool = False):
    from PIL import ImageFont
    for path in (_FONT_BOLD if bold else _FONT_REGULAR):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    if bold:
        return _load_font(size, bold=False)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _render_3d_scene_preview(
    frames_with_anchors: list,   # [(PuppetFrame, anchor_points, ref_name), ...]
    scene: dict,
    output_path: Path,
    ref_dir: Path | None = None,
) -> None:
    """Render puppet layout as N horizontal rows, one per panel.

    Each row:
      [HEADER bar spanning full width — panel index, view type, ref name]
      [axonometric schematic] | gap | [reference photo at same height]

    Schematic: cabinet-oblique room with furniture (deduped labels), zones,
               camera glyph, character body+head.
    Photo: perspective ref image scaled to schematic height; gray placeholder if missing.
    Rows are stacked vertically; each row is padded to the widest row's width.
    """
    from PIL import Image, ImageDraw

    font_sm = _load_font(14)
    font_md = _load_font(16)
    font_hd = _load_font(19, bold=True)

    SCALE  = 75
    WALL_H = 2.5
    MARGIN = 55
    HEADER = 48
    GAP    = 6   # pixels between schematic and photo

    _RESAMPLE = getattr(getattr(Image, 'Resampling', None), 'LANCZOS', None) or Image.LANCZOS

    # Case-insensitive stem → path index (JSON 'name' is Title-Cased; files are lowercase)
    _ref_idx: dict[str, Path] = {}
    if ref_dir and ref_dir.is_dir():
        for _p in ref_dir.iterdir():
            if _p.suffix.lower() in ('.png', '.jpg', '.jpeg'):
                _ref_idx[_p.stem.lower()] = _p

    def _txt(draw, pos, text, font, color=(30, 30, 30)):
        """Text with 1px drop shadow for legibility on any background."""
        draw.text((pos[0] + 1, pos[1] + 1), text, fill=(0, 0, 0), font=font)
        draw.text(pos, text, fill=color, font=font)

    rows: list[Image.Image] = []

    for frame, anchor_points, ref_name in frames_with_anchors:
        ap = anchor_points or {}
        room_m = ap.get('room_m', [6.0, 8.0])
        W = float(room_m[0])
        D = float(room_m[1]) if len(room_m) > 1 else 8.0

        CW = int((W + D * _AXO_F) * SCALE) + 2 + 2 * MARGIN
        CH = int((D * _AXO_F + WALL_H) * SCALE) + 2 + 2 * MARGIN
        ox_b = float(MARGIN)
        oy_b = float(CH - MARGIN)

        def pt(x_m, y_m, z_m=0.0, _ox=ox_b, _oy=oy_b):
            return _axo(x_m, y_m, z_m, SCALE, _ox, _oy)

        color = _PREVIEW_PALETTE[frame.panel_index % len(_PREVIEW_PALETTE)]
        cam = frame.camera
        objects_data = ap.get('objects', [])
        zones_data   = ap.get('zones', [])

        # ── Axonometric schematic ─────────────────────────────────────────────
        schematic = Image.new('RGB', (CW, CH), (245, 245, 243))
        draw = ImageDraw.Draw(schematic)

        # Floor + walls
        draw.polygon([pt(0,0), pt(W,0), pt(W,D), pt(0,D)],
                     fill=(228, 228, 224), outline=(60, 60, 60))
        wc = (110, 110, 125)
        for gx, gy in [(0,0),(W,0),(W,D),(0,D)]:
            draw.line([pt(gx,gy,0), pt(gx,gy,WALL_H)], fill=wc, width=2)
        corners = [(0,0),(W,0),(W,D),(0,D)]
        for i in range(4):
            a, b = corners[i], corners[(i+1)%4]
            draw.line([pt(*a,0),      pt(*b,0)],      fill=wc,             width=2)
            draw.line([pt(*a,WALL_H), pt(*b,WALL_H)], fill=(160, 160, 175), width=1)
        mid = W / 2
        draw.line([pt(mid-0.6,0,0), pt(mid+0.6,0,0)], fill=(200,90,40), width=3)
        ep = pt(mid, 0, 0)
        _txt(draw, (ep[0]-14, ep[1]+4), 'ENT', font_sm, (190, 80, 30))

        # Furniture — rect per object, label only first occurrence of each name
        lc: dict[str,int] = {}
        for obj in objects_data:
            lbl = (obj.get('label') or obj.get('id',''))[:14]
            lc[lbl] = lc.get(lbl, 0) + 1
        lb2: set[str] = set()
        for obj in objects_data:
            px_, py_ = pt(float(obj.get('x',0)), float(obj.get('y',0)))
            lbl = (obj.get('label') or obj.get('id',''))[:14]
            draw.rectangle([px_-12, py_-8, px_+12, py_+8],
                           fill=(205,165,95), outline=(100,75,35), width=2)
            if lbl not in lb2:
                disp = lbl if lc[lbl] == 1 else f'{lbl} \xd7{lc[lbl]}'
                _txt(draw, (px_+15, py_-8), disp, font_sm, (90,65,25))
                lb2.add(lbl)

        # Zones
        for zone in zones_data:
            cx_, cy_ = pt(float(zone.get('x',0)), float(zone.get('y',0)))
            draw.line([cx_-10, cy_,    cx_+10, cy_   ], fill=(40,145,40), width=2)
            draw.line([cx_,    cy_-10, cx_,    cy_+10], fill=(40,145,40), width=2)
            _txt(draw, (cx_+13, cy_-9), zone.get('id',''), font_sm, (25,110,25))

        # Camera glyph
        lx = cam.look_at_x - cam.x
        ly = cam.look_at_y - cam.y
        n = math.hypot(lx, ly)
        if n > 1e-9: lx /= n; ly /= n
        else: lx, ly = 0.0, 1.0
        apex = pt(cam.x, cam.y, cam.z)
        tx_, ty_ = cam.x - lx*0.45, cam.y - ly*0.45
        wx_, wy_ = -ly*0.22, lx*0.22
        draw.polygon([apex, pt(tx_-wx_,ty_-wy_,cam.z), pt(tx_+wx_,ty_+wy_,cam.z)],
                     fill=color, outline=(20,20,20))
        cos20 = math.cos(math.radians(20)); sin20 = math.sin(math.radians(20))
        fov_c = tuple(min(c+60,255) for c in color)
        for s in (-1,1):
            fx = lx*cos20 - ly*(s*sin20); fy = lx*(s*sin20) + ly*cos20
            draw.line([apex, pt(cam.x+fx*2.5, cam.y+fy*2.5, cam.z)], fill=fov_c, width=2)

        # Characters
        for char in frame.characters.values():
            if not char.visible:
                cx_, cy_ = pt(char.x, char.y, char.z)
                draw.line([cx_-9,cy_-9,cx_+9,cy_+9], fill=(170,40,40), width=3)
                draw.line([cx_-9,cy_+9,cx_+9,cy_-9], fill=(170,40,40), width=3)
                _txt(draw, (cx_+12,cy_-9), f'({char.name[:10]})', font_sm, (160,40,40))
            else:
                p0 = pt(char.x, char.y, 0); p1 = pt(char.x, char.y, 1.7)
                draw.line([p0, p1], fill=color, width=3)
                hx, hy = p1
                draw.ellipse([hx-14,hy-14,hx+14,hy+14], fill=color, outline=(15,15,15), width=2)
                initials = ''.join(w[0].upper() for w in char.name.split()[:2])[:2]
                draw.text((hx-8,hy-9), initials, fill=(255,255,255), font=font_sm)
                _txt(draw, (hx+17,hy-8), char.name[:14], font_md, (20,20,20))

        # ── Reference photo scaled to schematic height ────────────────────────
        vt = (frame.view_type or '').lower()
        lookup = None
        if _ref_idx and ref_name:
            if 'to-entrance' in vt:
                alt = ref_name.replace('From-Entrance', 'To-Entrance')
                lookup = _ref_idx.get(alt.lower()) or _ref_idx.get(ref_name.lower())
            elif 'opposite' in vt:
                alt = ref_name.replace('View-Primary', 'View-Opposite')
                lookup = _ref_idx.get(alt.lower()) or _ref_idx.get(ref_name.lower())
            else:
                lookup = _ref_idx.get(ref_name.lower())

        ref_photo: Image.Image | None = None
        if lookup:
            try:
                raw = Image.open(lookup).convert('RGB')
                rw, rh = raw.size
                ref_photo = raw.resize((int(rw * CH / rh), CH), _RESAMPLE)
            except Exception as _e:
                logger.debug(f"  ref load failed: {_e}")

        if ref_photo is None:
            ref_photo = Image.new('RGB', (CW, CH), (210, 210, 210))
            ph_d = ImageDraw.Draw(ref_photo)
            ph_d.text((ref_photo.width // 2 - 45, CH // 2 - 8),
                      'no ref image', fill=(140,140,140), font=font_md)

        right_w = ref_photo.width
        row_w = CW + GAP + right_w

        # ── Assemble row: full-width header + schematic | photo ───────────────
        row = Image.new('RGB', (row_w, HEADER + CH), (255, 255, 255))
        rd = ImageDraw.Draw(row)
        rd.rectangle([0, 0, row_w, HEADER - 1], fill=color)
        lbl_hdr = f"P{frame.panel_index}  {frame.view_type}  {(ref_name or 'no anchor')[:55]}"
        rd.text((8, 8), lbl_hdr, fill=(255, 255, 255), font=font_hd)
        row.paste(schematic, (0,        HEADER))
        row.paste(ref_photo, (CW + GAP, HEADER))
        rows.append(row)

    if not rows:
        logger.warning(f"  ⚠️  Scene {scene.get('scene_id','?')}: no frames to preview")
        return

    # Stack rows vertically; pad each to max row width
    max_w   = max(r.width  for r in rows)
    total_h = sum(r.height for r in rows)
    out_img = Image.new('RGB', (max_w, total_h), (160, 160, 160))
    y_off = 0
    for row in rows:
        out_img.paste(row, (0, y_off))
        y_off += row.height

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(output_path)
    logger.info(f"  ✅ Scene {scene.get('scene_id','?')}: → {output_path.name}")


def cmd_3d_preview(args):
    """Render axonometric puppet layout preview for one or all scenes."""
    from lib.core import puppet as _puppet

    project, _, _ = load_project(style=args.style)
    load_character_refs(project)

    meta_path = project.output_dir / 'animation_metadata.json'
    if not meta_path.exists():
        logger.error("❌ animation_metadata.json not found. Run 'make scenes' first.")
        sys.exit(1)

    metadata = json.loads(meta_path.read_text(encoding='utf-8'))
    all_scenes = metadata.get('scenes', [])

    scene_filter = None
    if args.scene and args.scene != 'all':
        try:
            scene_filter = int(args.scene)
        except ValueError:
            logger.error("❌ SCENE must be an integer or 'all'.")
            sys.exit(1)

    scenes = (
        all_scenes if scene_filter is None
        else [s for s in all_scenes if s.get('scene_id') == scene_filter]
    )
    if not scenes:
        logger.error("❌ No matching scenes found in animation_metadata.json.")
        sys.exit(1)

    # Index anchor_points by canonical primary-view ref name (same strategy as cmd_disposition).
    # scene['location'] is free-style text — never match on it; use location_references instead.
    anchors_by_ref: dict = {
        name: info['anchor_points']
        for name, info in project.character_info.items()
        if info.get('type', '').lower() in ('room', 'outdoor')
        and name.endswith(('-View-From-Entrance', '-View-Primary'))
        and info.get('anchor_points')
    }
    if not anchors_by_ref:
        logger.error(
            "❌ No room/outdoor refs with anchor_points found. "
            "Run 'make room-anchors' then 'make disposition' first."
        )
        sys.exit(1)

    rendered = 0
    skipped = 0
    for scene in scenes:
        sid = scene.get('scene_id', 0)
        panels = scene.get('panels', [])
        if not panels:
            logger.warning(f"  ⚠️  Scene {sid}: no panels — skipping")
            skipped += 1
            continue

        # Resolve anchor per panel — panels may reference different rooms
        frames_with_anchors: list = []
        has_any_anchor = False
        for panel in panels:
            ref, ap = _resolve_panel_anchor(panel, anchors_by_ref)
            if ref and ap:
                has_any_anchor = True
            # build a single-panel pseudo-scene so build_scene_frames works
            panel_frames = _puppet.build_scene_frames([panel], ap or {})
            for frame in panel_frames:
                frames_with_anchors.append((frame, ap, ref or ''))

        if not has_any_anchor:
            logger.warning(
                f"  ⚠️  Scene {sid}: no anchor_points for any panel — skipping. "
                f"Refs: {list({r for p in panels for r in p.get('location_references', [])})}"
            )
            skipped += 1
            continue

        out = project.output_dir / f'preview_3d_scene_{int(sid):03d}.png'
        try:
            _render_3d_scene_preview(frames_with_anchors, scene, out, ref_dir=project.ref_dir)
            rendered += 1
        except Exception:
            logger.exception(f"  ❌ Scene {sid}: render failed")
            skipped += 1

    logger.info(f"\n✅ 3D preview: {rendered} rendered, {skipped} skipped.")


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
    p.add_argument('--max-attempts', type=int, default=3, dest='max_attempts',
                   help='Max refinement attempts per panel (default: 3)')
    p.set_defaults(func=cmd_panel_by_panel_qa)

    p = sub.add_parser(
        '3d-preview',
        help='Render axonometric puppet layout preview (camera + characters per panel)',
    )
    p.add_argument('scene', nargs='?', default='all', help='Scene number or "all" (default: all)')
    p.set_defaults(func=cmd_3d_preview)
