"""Split Room/Vehicle/Outdoor refs into per-view renders with inline QA."""
import json
import logging
from pathlib import Path
from typing import Optional

from PIL import Image

from lib.core.project import Project
from lib.core.utils import atomic_write, safe_name
from lib.llm.base import BaseLLM
from lib.studio.artist.anchor_prompt import _load_entrance_anchor_points
from lib.studio.artist.catalog import load_character_refs
from lib.studio.artist.ref_render import _render_single_ref
from lib.studio.artist.view_catalog import (
    _ensure_view_metadata, _MULTIPANEL_MARKERS, _OUTDOOR_VIEWS, _ROOM_VIEWS, _truth_ref_suffixes,
    _VEHICLE_VIEWS, _view_logline,
)
from lib.studio.artist.view_geometry import _parse_room_dims, _view_aspect_ratio
from lib.studio.room_geometry import resolve_room_height_m

logger = logging.getLogger(__name__)


def _qa_and_refine_room_view(
    view_name: str,
    view_png_path: Path,
    truth_refs: list[tuple[str, Path]],
    view_data: dict,
    config: dict,
    project: Project,
    llm: BaseLLM,
    max_attempts: int = 3,
    threshold: int = 7,
) -> None:
    """QA a rendered room view and regenerate if consistency/geometry fails.

    truth_refs — list of (view_suffix, png_path) pairs used as ground truth.
    View-To-Entrance uses only [View-From-Entrance]; all other views use both.
    """
    from lib.studio.critic import analyze_room_view

    view_suffix = next(
        (s for s, _ in _ROOM_VIEWS if view_name.endswith(f'-{s}')),
        view_name.rsplit('-', 1)[-1],
    )
    # Load anchor_points for geometry-aware QA
    anchor_points = view_data.get('anchor_points') or _load_entrance_anchor_points(
        view_name, view_suffix, project
    )

    # Physical framing target, matching the render prompt and the sketch.
    dims = None
    room_m = anchor_points.get('room_m') if isinstance(anchor_points, dict) else None
    if isinstance(room_m, (list, tuple)) and len(room_m) >= 2:
        dims = (float(room_m[0]), float(room_m[1]))
    else:
        dims = _parse_room_dims(view_data.get('visual_desc', ''))
    expected_aspect = None
    if dims:
        room_h, _ = resolve_room_height_m(
            anchor_points if isinstance(anchor_points, dict) else {},
            view_data.get('visual_desc', ''),
        )
        expected_aspect = _view_aspect_ratio(view_suffix, dims, config, room_h)

    sketch_png = project.ref_dir / f"{safe_name(view_name)}.sketch.png"

    for attempt in range(1, max_attempts + 1):
        if not view_png_path.exists():
            logger.warning(f"  ⚠️  QA: PNG missing for {view_name}, skipping")
            return

        source_views: list[tuple[str, Image.Image]] = []
        for suffix, png_path in truth_refs:
            if png_path.exists():
                img = Image.open(png_path)
                source_views.append((suffix, img.copy()))
                img.close()

        if not source_views:
            logger.warning(f"  ⚠️  QA: no truth PNGs available for {view_name}, skipping")
            return

        with Image.open(view_png_path) as vi:
            view_img = vi.copy()

        sketch_img = Image.open(sketch_png).copy() if sketch_png.exists() else None

        result = analyze_room_view(
            llm=llm,
            view_img=view_img,
            source_views=source_views,
            view_suffix=view_suffix,
            visual_desc=view_data.get('visual_desc', ''),
            threshold=threshold,
            anchor_points=anchor_points or None,
            expected_aspect=expected_aspect,
            sketch_img=sketch_img,
        )
        for _, img in source_views:
            img.close()
        view_img.close()
        if sketch_img is not None:
            sketch_img.close()

        con = result['consistency_score']
        geo = result['geometry_score']
        need = result['needs_regeneration']
        logger.info(
            f"    QA {view_name} attempt {attempt}: consistency={con}/10 geometry={geo}/10 "
            + ("🔴 regenerate" if need else "🟢 OK")
        )
        for issue in result.get('issues', []):
            logger.info(f"      ⚠️  {issue}")

        if not need:
            return

        if attempt < max_attempts:
            regen_prompt = result.get('regeneration_prompt', '')
            if regen_prompt:
                patched = dict(view_data)
                patched['visual_desc'] = (
                    f"{view_data.get('visual_desc', '')}. CORRECTION REQUIRED: {regen_prompt}"
                )
                entrance_path = next(
                    (p for s, p in truth_refs if s == 'View-From-Entrance'), None
                )
                if entrance_path:
                    base = view_name[: -(len(view_suffix) + 1)]
                    patched['style_reference'] = f"{base}-View-From-Entrance"
                logger.info(f"    🔄 Regenerating {view_name} (attempt {attempt + 1})...")
                _render_single_ref(patched, config, project, llm, force=True)

    logger.warning(f"  ❌ {view_name} QA failed after {max_attempts} attempts")


def remake_room_refs(config: dict, llm: BaseLLM, project: Project, create_only: bool = False):
    """Split monolithic Room/Vehicle refs into per-view refs and add any missing views.

    create_only creates the JSON files without rendering PNGs or running QA.

    Handles two cases:
    1. Monolithic refs (no view suffix) — split into all views, render each.
    2. Already-split rooms missing new views (e.g. only have From/To-Entrance but
       not the 4+ new 8-point views) — derives them from the existing View-From-Entrance.

    All room views use View-From-Entrance as style_reference for material consistency.
    Original combined ref JSON/PNG are left untouched (not deleted).
    """
    load_character_refs(project)

    all_view_suffixes = {v[0] for v in _ROOM_VIEWS + _VEHICLE_VIEWS + _OUTDOOR_VIEWS}

    # Case 1: monolithic refs — split into all views
    to_split = [
        (name, info)
        for name, info in project.character_info.items()
        if info.get('type') in ('Room', 'Vehicle', 'Outdoor')
        and not any(name.endswith(f'-{s}') for s in all_view_suffixes)
    ]

    # Case 2: rooms that have View-From-Entrance but are missing some of the 8 views.
    # Identify base names from existing View-From-Entrance refs.
    _entrance_suffix = 'View-From-Entrance'
    to_upgrade: list[tuple[str, dict]] = []
    for name, info in project.character_info.items():
        if info.get('type') == 'Room' and name.endswith(f'-{_entrance_suffix}'):
            base = name[: -(len(_entrance_suffix) + 1)]
            missing = [
                (suffix, instr) for suffix, instr in _ROOM_VIEWS
                if suffix != _entrance_suffix
                and not (project.ref_dir / f"{safe_name(f'{base}-{suffix}')}.json").exists()
            ]
            if missing:
                to_upgrade.append((base, info, missing))  # type: ignore[arg-type]

    # Case 3: outdoor locations (older two-view casts) missing some of the four station views.
    to_complete = [
        (name, info, [(s, i) for s, i in _OUTDOOR_VIEWS[1:]
                      if not (project.ref_dir / f"{safe_name(name[:-len('View-Primary')] + s)}.json").exists()])
        for name, info in list(project.character_info.items())
        if info.get('type') == 'Outdoor' and name.endswith('-View-Primary')
    ]
    to_complete = [item for item in to_complete if item[2]]

    if not to_split and not to_upgrade and not to_complete:
        logger.info("  ✅ All room views are up to date.")
        return

    logger.info(f"  📋 {len(to_split)} ref(s) to split, {len(to_upgrade)} room(s) to upgrade.")

    for name, info in to_split:
        rtype = info['type']
        views = (_ROOM_VIEWS if rtype == 'Room' else _VEHICLE_VIEWS if rtype == 'Vehicle'
                 else _OUTDOOR_VIEWS)

        orig_desc = info['visual_desc']
        is_multipanel = any(m in orig_desc.lower() for m in _MULTIPANEL_MARKERS)
        if is_multipanel:
            logger.info(f"  🔍 Multi-panel visual_desc detected for {name} — will use LLM to extract per-view descriptions")

        # Parse room dimensions once for aspect ratio selection
        dims = _parse_room_dims(orig_desc) if rtype == 'Room' else None

        entrance_ref_name: Optional[str] = None   # first rendered view (View-From-Entrance)
        to_entrance_ref_name: Optional[str] = None  # View-To-Entrance; second truth for QA

        for view_suffix, view_instruction in views:
            view_name = f"{name}-{view_suffix}"
            view_json_path = project.ref_dir / f"{safe_name(view_name)}.json"

            if view_json_path.exists():
                logger.info(f"  ⏭  Skip JSON {view_name} (exists)")
                try:
                    existing = json.loads(view_json_path.read_text(encoding='utf-8'))
                    if _ensure_view_metadata(existing):
                        atomic_write(view_json_path, json.dumps(existing, indent=2))
                    project.character_info[view_name] = existing
                except Exception as e:
                    logger.warning(f"⚠️  Unreadable {view_json_path.name}: {e}")
            else:
                if is_multipanel:
                    view_desc = _extract_view_desc(orig_desc, view_suffix, view_instruction, llm)
                else:
                    view_desc = f"{orig_desc}. {view_instruction}"
                # JSON-only creation has no render pass to attach the material
                # reference later, so set it on every derived view up front.
                # Outdoor views all turn around View-Primary's station, so they share its materials.
                if view_suffix != views[0][0] and (rtype == 'Outdoor' or create_only and rtype == 'Room'):
                    style_ref = f"{name}-{views[0][0]}"
                elif view_suffix == 'View-To-Entrance' and entrance_ref_name:
                    style_ref = entrance_ref_name
                else:
                    style_ref = ''
                new_ref: dict = {
                    'name': view_name,
                    'logline_subject_info': _view_logline(info.get('logline_subject_info', ''), view_suffix),
                    'visual_desc': view_desc,
                    'video_visual_desc': info.get('video_visual_desc', ''),
                    'type': rtype,
                    'style_reference': style_ref,
                }
                if dims and rtype == 'Room':
                    new_ref['room_dims'] = list(dims)
                if rtype == 'Room':
                    new_ref['truth_refs'] = _truth_ref_suffixes(view_suffix)
                    new_ref['qa_corrections'] = []
                    if view_suffix != 'View-From-Entrance':
                        new_ref['qa'] = {'status': 'pending'}
                view_json_path.write_text(json.dumps(new_ref, indent=2), encoding='utf-8')
                project.character_info[view_name] = new_ref
                logger.info(f"  ✅ Created JSON: {view_name}")

            if create_only:
                continue

            view_png_path = project.ref_dir / f"{safe_name(view_name)}.png"

            # For Outdoor primary view: copy the original PNG directly (already a valid primary)
            if rtype == 'Outdoor' and entrance_ref_name is None and not view_png_path.exists():
                orig_png = project.ref_dir / f"{safe_name(name)}.png"
                if orig_png.exists():
                    view_png_path.write_bytes(orig_png.read_bytes())
                    project.character_images[view_name] = str(view_png_path)
                    logger.info(f"    📋  Copied original → {view_png_path}")

            if not view_png_path.exists():
                _render_single_ref(project.character_info[view_name], config, project, llm)
            elif view_name not in project.character_images:
                project.character_images[view_name] = str(view_png_path)

            if entrance_ref_name is None:
                entrance_ref_name = view_name
            if view_suffix == 'View-To-Entrance':
                to_entrance_ref_name = view_name

            # QA pass: all room views except View-From-Entrance
            if rtype == 'Room' and view_suffix != 'View-From-Entrance':
                truth: list[tuple[str, Path]] = []
                if entrance_ref_name:
                    ep = project.ref_dir / f"{safe_name(entrance_ref_name)}.png"
                    truth.append(('View-From-Entrance', ep))
                if view_suffix != 'View-To-Entrance' and to_entrance_ref_name:
                    tp = project.ref_dir / f"{safe_name(to_entrance_ref_name)}.png"
                    truth.append(('View-To-Entrance', tp))
                if truth:
                    _qa_and_refine_room_view(
                        view_name, view_png_path, truth,
                        project.character_info[view_name], config, project, llm,
                    )

        logger.info(f"  ✅ Split complete: {name} → {len(views)} views")
        # Clear any stale needs_regenerate from the monolithic ref — it's superseded by views.
        if info.get('needs_regenerate'):
            mono_json_path = project.ref_dir / f"{safe_name(name)}.json"
            info.pop('needs_regenerate')
            atomic_write(mono_json_path, json.dumps(info, indent=2))

    # Case 2: upgrade rooms that have View-From-Entrance but are missing new views.
    for base, entrance_info, missing_views in to_upgrade:
        entrance_ref_name = f"{base}-{_entrance_suffix}"
        to_entrance_ref_name = f"{base}-View-To-Entrance"
        logger.info(f"  🔄 Upgrading {base}: adding {len(missing_views)} missing view(s)")

        orig_desc = entrance_info['visual_desc']
        is_multipanel = any(m in orig_desc.lower() for m in _MULTIPANEL_MARKERS)
        dims = _parse_room_dims(orig_desc)

        for view_suffix, view_instruction in missing_views:
            view_name = f"{base}-{view_suffix}"
            view_json_path = project.ref_dir / f"{safe_name(view_name)}.json"

            if not view_json_path.exists():
                if is_multipanel:
                    view_desc = _extract_view_desc(orig_desc, view_suffix, view_instruction, llm)
                else:
                    view_desc = f"{orig_desc}. {view_instruction}"
                # Missing views exclude the entrance view. In JSON-only mode set
                # the material reference on all of them; otherwise preserve the
                # existing View-To-Entrance-only behavior.
                style_ref = (entrance_ref_name if create_only
                             or view_suffix == 'View-To-Entrance' else '')
                new_ref: dict = {
                    'name': view_name,
                    'logline_subject_info': _view_logline(entrance_info.get('logline_subject_info', ''), view_suffix),
                    'visual_desc': view_desc,
                    'video_visual_desc': entrance_info.get('video_visual_desc', ''),
                    'type': 'Room',
                    'style_reference': style_ref,
                }
                if dims:
                    new_ref['room_dims'] = list(dims)
                new_ref['truth_refs'] = _truth_ref_suffixes(view_suffix)
                new_ref['qa_corrections'] = []
                if view_suffix != 'View-From-Entrance':
                    new_ref['qa'] = {'status': 'pending'}
                view_json_path.write_text(json.dumps(new_ref, indent=2), encoding='utf-8')
                project.character_info[view_name] = new_ref
                logger.info(f"  ✅ Created JSON: {view_name}")
            else:
                try:
                    existing = json.loads(view_json_path.read_text(encoding='utf-8'))
                    if _ensure_view_metadata(existing):
                        atomic_write(view_json_path, json.dumps(existing, indent=2))
                    project.character_info[view_name] = existing
                except Exception as e:
                    logger.warning(f"⚠️  Unreadable {view_json_path.name}: {e}")

            if create_only:
                continue

            view_png_path = project.ref_dir / f"{safe_name(view_name)}.png"
            if not view_png_path.exists():
                _render_single_ref(project.character_info[view_name], config, project, llm)
            elif view_name not in project.character_images:
                project.character_images[view_name] = str(view_png_path)

            # QA pass
            truth: list[tuple[str, Path]] = []
            ep = project.ref_dir / f"{safe_name(entrance_ref_name)}.png"
            truth.append(('View-From-Entrance', ep))
            if view_suffix != 'View-To-Entrance':
                tp = project.ref_dir / f"{safe_name(to_entrance_ref_name)}.png"
                truth.append(('View-To-Entrance', tp))
            _qa_and_refine_room_view(
                view_name, view_png_path, truth,
                project.character_info[view_name], config, project, llm,
            )

        logger.info(f"  ✅ Upgrade complete: {base}")

    for primary, info, missing in to_complete:
        base = primary[: -len('View-Primary')]
        logger.info(f"  🔄 Adding {len(missing)} station view(s) to {base[:-1]}")
        for view_suffix, view_instruction in missing:
            view_name = f"{base}{view_suffix}"
            new_ref = {
                'name': view_name,
                'logline_subject_info': _view_logline(info.get('logline_subject_info', ''), view_suffix),
                'visual_desc': f"{info['visual_desc']}. {view_instruction}",
                'video_visual_desc': info.get('video_visual_desc', ''),
                'type': 'Outdoor',
                'style_reference': primary,
            }
            atomic_write(project.ref_dir / f"{safe_name(view_name)}.json", json.dumps(new_ref, indent=2))
            project.character_info[view_name] = new_ref
            logger.info(f"  ✅ Created JSON: {view_name}")
            if not create_only:
                _render_single_ref(new_ref, config, project, llm)

    logger.info("  ✅ remake-room-refs done.")


_VIEW_DESC_SCHEMA = {
    'type': 'object',
    'properties': {'visual_desc': {'type': 'string'}},
    'required': ['visual_desc'],
}


def _extract_view_desc(original_desc: str, view_suffix: str, view_instruction: str,
                       llm: BaseLLM) -> str:
    """Use LLM to extract a clean single-panel visual description for one view.

    Called only when original_desc contains multi-panel layout markers.
    Returns the rewritten description, or original_desc on failure.
    """
    prompt = (
        f"The following room reference has a multi-panel visual_desc that describes "
        f"multiple camera angles (e.g. TOP/BOTTOM or left/right panels) in one block.\n\n"
        f"original visual_desc:\n{original_desc}\n\n"
        f"Extract and rewrite ONLY the part relevant to this single view:\n"
        f"View: {view_suffix}\nView instruction: {view_instruction}\n\n"
        f"Rules:\n"
        f"- Return a single coherent paragraph describing only this one camera angle.\n"
        f"- Remove all multi-panel layout language (TOP, BOTTOM, panels, etc.).\n"
        f"- Keep all specific details: furniture, materials, colours, lighting, props.\n"
        f"- Do NOT add new details not present in the original.\n"
        f"Return JSON: {{\"visual_desc\": \"...\"}}"
    )
    try:
        result = llm.make_json(prompt, schema=_VIEW_DESC_SCHEMA)
        desc = result.get('visual_desc', '').strip()
        if desc:
            return desc
    except Exception as e:
        logger.warning(f"  ⚠️  LLM view-desc extraction failed: {e}")
    return original_desc
