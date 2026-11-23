"""Bare 3D room sketches rendered from anchor_points.

The sketch is a geometry reference for image generation: it carries camera
position, perspective and object placement, but no materials. render3d builds
and renders the scenes; this module builds the spec and commits the PNGs.
"""
import json
import logging
import math
import re
import tempfile
from pathlib import Path

from lib.core.utils import atomic_write, safe_name
from lib.studio.blocking import Camera, basis
from lib.studio.render3d.factory import get_engine
from lib.studio.render3d.shapes import contains, room_scenes
from lib.studio.artist import _ROOM_VIEWS, _VIEW_CAMERA, _is_wall_camera, _view_aspect_ratio, _view_rig
from lib.studio.artist.view_geometry import view_camera
from lib.studio.artist.view_catalog import _OUTDOOR_VIEW_SUFFIXES
from lib.studio.room_geometry import CAMERA_HEIGHT_M, WALL_INSET_M, resolve_room_height_m
from lib.studio.room_models import (
    CATEGORY_HEX,
    DEFAULT_FOOTPRINT_M,
    DEFAULT_HEIGHT_M,
    FLOOR_STANDING,
    PROP_MAX_HEIGHT_M,
    PROP_MAX_SPAN_M,
    SKIP_CATEGORY,
    THIN,
    WALL_MOUNTED,
    ZERO_FOOTPRINT,
    classify_object,
    keyword_dims_m,
    srgb_hex_to_linear,
)

logger = logging.getLogger(__name__)

MAX_SKETCH_DIMENSION = 1024


def sketch_path(ref_dir: Path, view_name: str) -> Path:
    return ref_dir / f"{safe_name(view_name)}.sketch.png"


def _fraction(value, low=0.0, high=1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(high, max(low, number))


def _pixel_size(aspect: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in aspect.split(':'))
    except (ValueError, AttributeError):
        width, height = 4, 3
    scale = MAX_SKETCH_DIMENSION / max(width, height)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _is_full_height_wall(obj: dict, category: str) -> bool:
    """True for wall-spanning features that should reach the ceiling.

    Old anchor sets describe these by id/label ("fireplace-feature-wall",
    "far-window-wall", "display-shelving-wall") but carry no height. Rendering
    them with the default 1.2 m window / 2.4 m panel height makes them float or
    look like strips instead of the floor-to-ceiling walls they are.
    """
    if category not in ('window', 'panel', 'shelf'):
        return False
    text = f" {obj.get('id', '')} {obj.get('label', '')} ".lower()
    return any(
        token in text
        for token in (' feature wall ', ' window wall ', ' shelving wall ',
                      ' full height wall ', ' floor to ceiling wall ')
    )


def _hinge_sign(hinge_side, along_x: bool) -> int:
    """-1/+1 = hinges toward the low/high end of the door's run; 0 = unknown or off-axis."""
    return {('x0', True): -1, ('x1', True): 1, ('y0', False): -1, ('y1', False): 1}.get(
        (hinge_side, along_x), 0)


def _cut(objects: list[dict], position: list[float], forward: tuple[float, float],
         back: float) -> dict:
    """Section cut `back` metres ahead of the camera, at WALL_INSET_M into the room.

    Objects centred before the cut are hidden whole, as the anchor block lists
    them hidden. The clip plane stops at the nearest kept object's front face so
    none is sliced, and never falls short of the wall's inner face.
    """
    def depth(obj):
        return sum((c - p) * f for c, p, f in zip(obj['center_m'], position, forward))

    def half_extent(obj):
        sx, sy, _ = obj['size_m']
        return max(sx, sy) / 2 if obj['yaw_degrees'] else (sx if forward[0] else sy) / 2

    culled = [o['id'] for o in objects if depth(o) < back]
    kept_front = [depth(o) - half_extent(o) for o in objects if depth(o) >= back]
    clip = (max(back - WALL_INSET_M + 0.02, min([back, *kept_front])) if back > 0 else None)
    return {'culled_ids': culled, 'clip_start_m': clip}


_FACADE = re.compile(r'\b(facades?|façades?|buildings?|storefronts?|shopfronts?)\b')
OUTDOOR_HEIGHT_M = 18.0  # a five-storey street front; anchors' room_height_m wins


def build_sketch_spec(anchor_points: dict, view_names: list[str], config: dict,
                      visual_desc: str = '') -> dict:
    """Convert anchor_points into a render spec for the Blender-side script."""
    room_m = anchor_points.get('room_m')
    if not isinstance(room_m, (list, tuple)) or len(room_m) != 2:
        raise ValueError('anchor_points.room_m must contain [width_m, depth_m]')
    width_m, depth_m = float(room_m[0]), float(room_m[1])
    if width_m <= 0 or depth_m <= 0:
        raise ValueError('room dimensions must be positive')
    room_h, height_source = resolve_room_height_m(anchor_points, visual_desc)
    outdoor = any(n.endswith(f'-{s}') for n in view_names for s in _OUTDOOR_VIEW_SUFFIXES)
    if outdoor and height_source != 'anchor_points.room_height_m':
        room_h, height_source = OUTDOOR_HEIGHT_M, 'outdoor default'

    objects = []
    for obj in anchor_points.get('objects', []):
        width_x = _fraction(obj.get('width_x'))
        depth_y = _fraction(obj.get('depth_y'))
        category = classify_object(obj)
        if category == SKIP_CATEGORY:
            continue
        kw_height, kw_span, kw_depth = keyword_dims_m(obj)
        explicit_h = obj.get('height_m')
        has_explicit_h = isinstance(explicit_h, (int, float)) and explicit_h > 0
        height_m = (float(explicit_h) if has_explicit_h
                    else kw_height or DEFAULT_HEIGHT_M[category])

        # Roof spans, ceiling panels and skylights sit in the top 15% of the
        # room. Their wall-sized default height would render as a thick slab
        # floating in the middle of the view, so treat them as thin surfaces.
        if (not has_explicit_h and category in ('panel', 'window')
                and _fraction(obj.get('z')) >= 0.85):
            height_m = min(height_m, 0.25)

        full_height_wall = not has_explicit_h and (
            _is_full_height_wall(obj, category)
            or outdoor and bool(_FACADE.search(f"{obj.get('id', '')} {obj.get('label', '')}".lower())))
        local_footprint = False

        # Floor-standing furniture is based at z=0: anchor z often encodes a
        # visual position, not the physical centre, and floats tables/chairs.
        if full_height_wall:
            size_z = room_h
            center_z = room_h / 2
        elif category in FLOOR_STANDING and not (  # a wall shelf set hangs: short, its underside above the counters
                category == 'shelf' and has_explicit_h and height_m < 1.2
                and _fraction(obj.get('z')) * room_h - height_m / 2 > 0.8):
            size_z = min(height_m, room_h)
            center_z = size_z / 2
        elif category == 'artwork':
            # Wall art hangs at human height. Old anchor sets normalise z to a
            # 3 m room, so a 6 m room would otherwise put a painting at 3.6 m.
            size_z = min(height_m, room_h)
            center_z = min(max(_fraction(obj.get('z')) * room_h, 1.0), 2.4)
        else:
            center_z = _fraction(obj.get('z')) * room_h
            half = max(0.03, height_m / 2)
            low, high = max(0.0, center_z - half), min(room_h, center_z + half)
            if high - low < 0.06:
                center_z = min(max(center_z, 0.03), room_h - 0.03)
                size_z = 0.06
            else:
                center_z = (low + high) / 2
                size_z = high - low

        facing = obj.get('facing_degrees_y', -1)
        size_x = max(0.05, width_x * width_m)
        size_y = max(0.05, depth_y * depth_m)
        if (has_explicit_h and explicit_h < PROP_MAX_HEIGHT_M and max(size_x, size_y) < PROP_MAX_SPAN_M
                and category not in THIN):  # a jug or a tap: drawn as a table or box it would misplace the room
            continue
        center_x = _fraction(obj.get('x')) * width_m
        center_y = _fraction(obj.get('y')) * depth_m

        # Legacy anchors describe wall features by their projected footprint in
        # the entrance view, so a feature can be declared wider across the room
        # than along its wall (the mansion fireplace: 3 m x 1 m). Rendering that
        # literally builds a partition jutting into the room. Snap full-height
        # wall features to their nearest wall and keep the long axis along it.
        if full_height_wall:
            xf = _fraction(obj.get('x'))
            yf = _fraction(obj.get('y'))
            nearest_wall = min(
                (xf, 'left'), (1.0 - xf, 'right'),
                (yf, 'entrance'), (1.0 - yf, 'far'),
                key=lambda item: item[0],
            )[1]
            span = max(size_x, size_y)
            thickness = 0.02 if outdoor else min(min(size_x, size_y), 0.5)  # a facade slab would bury its doors and windows
            if nearest_wall in ('left', 'right'):
                center_x = thickness / 2 if nearest_wall == 'left' else width_m - thickness / 2
                size_x, size_y = thickness, span
            else:
                center_y = thickness / 2 if nearest_wall == 'entrance' else depth_m - thickness / 2
                size_x, size_y = span, thickness
        elif width_x < ZERO_FOOTPRINT and depth_y < ZERO_FOOTPRINT:
            # Zero-footprint anchors (31% of legacy objects) carry no size and
            # would render as 5 cm posts. Use a plausible footprint: wall items
            # on their nearest wall, free-standing ones along their facing.
            default_span, default_depth = DEFAULT_FOOTPRINT_M[category]
            span, thickness = kw_span or default_span, kw_depth or default_depth
            if category in WALL_MOUNTED:
                xf = _fraction(obj.get('x'))
                yf = _fraction(obj.get('y'))
                nearest_wall = min(
                    (xf, 'left'), (1.0 - xf, 'right'),
                    (yf, 'entrance'), (1.0 - yf, 'far'),
                    key=lambda item: item[0],
                )[1]
                if nearest_wall in ('left', 'right'):
                    center_x = thickness / 2 if nearest_wall == 'left' else width_m - thickness / 2
                    size_x, size_y = thickness, span
                else:
                    center_y = thickness / 2 if nearest_wall == 'entrance' else depth_m - thickness / 2
                    size_x, size_y = span, thickness
            else:
                # Local model size, turned to the facing below; kept inside
                # the room whatever the yaw.
                size_x, size_y = span, thickness
                local_footprint = True
                reach = min(max(span, thickness) / 2, width_m / 2, depth_m / 2)
                center_x = min(max(center_x, reach), width_m - reach)
                center_y = min(max(center_y, reach), depth_m - reach)

        # width_x/depth_y are world-axis extents. Rotating a long row (server
        # racks, counters) would turn its footprint across the room, so only
        # near-square props follow the declared facing. Local +Y is the back
        # of the procedural models, so yaw = facing points the front along the
        # schema direction (0 = toward entrance, 90 = toward x=1).
        squareish = abs(size_x - size_y) <= 0.25 * max(size_x, size_y)
        yaw = (float(facing) if (squareish or local_footprint)
               and isinstance(facing, (int, float)) and facing >= 0 else 0.0)
        door, along_x = {}, size_x >= size_y
        if category == 'door':  # wall-aligned; the model needs which way the room is
            wall = min((center_x, 'left'), (width_m - center_x, 'right'),
                       (center_y, 'entrance'), (depth_m - center_y, 'far'))[1]
            yaw, along_x = 0.0, wall in ('entrance', 'far')
            door = {'inward': {'left': [1, 0], 'right': [-1, 0], 'entrance': [0, 1], 'far': [0, -1]}[wall],
                    'opens': obj.get('opens') or '', 'leaf_state': obj.get('leaf_state') or ''}
        objects.append({
            'id': obj.get('id') or obj.get('label', f'object-{len(objects)}'),
            'category': category,
            'color': srgb_hex_to_linear(CATEGORY_HEX[category]),
            'center_m': [center_x, center_y, center_z],
            'size_m': [size_x, size_y, size_z],
            'yaw_degrees': yaw,
            'hinge_sign': _hinge_sign(obj.get('hinge_side'), along_x),
            **door,
        })

    views = []
    for name in view_names:
        suffix = next((s for s in sorted(_VIEW_CAMERA, key=len, reverse=True) if name.endswith(f'-{s}')), None)
        if suffix is None:
            raise ValueError(f'unknown view suffix in: {name}')
        cx, cy, fdx, fdy = view_camera(suffix, anchor_points)
        # Wall views cut the room WALL_INSET_M inside the camera wall; the
        # camera stands `back` metres behind that cut, outside the room when a
        # natural lens needs the distance. Center and By-* views already encode
        # their own distance from a wall: no cut, canonical position.
        wall_camera = _is_wall_camera(cx, cy) and suffix not in _OUTDOOR_VIEW_SUFFIXES  # outdoors: no wall to cut
        hfov, back = _view_rig(suffix, (width_m, depth_m), room_h)
        step = WALL_INSET_M - back if wall_camera else 0.0
        position = [cx * width_m + fdx * step, cy * depth_m + fdy * step]
        if back == 0:
            position = [min(width_m - 0.05, max(0.05, position[0])),
                        min(depth_m - 0.05, max(0.05, position[1]))]
        pixel_w, pixel_h = _pixel_size(
            _view_aspect_ratio(suffix, (width_m, depth_m), config, room_h)
        )
        views.append({
            'name': name,
            'suffix': suffix,
            'position_m': [*position, CAMERA_HEIGHT_M],
            **(_cut(objects, position, (fdx, fdy), back) if wall_camera else {}),
            'forward': [fdx, fdy],
            'hfov_degrees': hfov,
            'width_px': pixel_w,
            'height_px': pixel_h,
        })

    return {
        'room_m': [width_m, depth_m, room_h],
        'objects': objects,
        'views': views,
        'meta': {'room_height_source': height_source},
    }


def _view_meta(spec: dict) -> dict:
    """Per view, per object: image x (as Blender's world_to_camera_view, mirrored behind the lens), in_front, visible."""
    meta = {}
    for view in spec['views']:
        pos = view['position_m']
        target = view.get('target_m') or [pos[0] + view['forward'][0], pos[1] + view['forward'][1], pos[2]]
        tan_h = math.tan(math.radians(view['hfov_degrees']) / 2)
        cam = Camera(tuple(pos), tuple(target), view['hfov_degrees'],
                     math.degrees(2 * math.atan(tan_h * view['height_px'] / view['width_px'])))
        f, r, u = basis(cam)
        culled = set(view.get('culled_ids', ())) | {o['id'] for o in spec['objects'] if contains(o, pos)}
        meta[view['name']] = {}
        for obj in spec['objects']:
            d = [c - p for c, p in zip(obj['center_m'], pos)]
            z = sum(a * b for a, b in zip(d, f))
            depth = z if abs(z) > 1e-9 else 1e-9
            x = 0.5 + sum(a * b for a, b in zip(d, r)) / depth / (2 * tan_h)
            y = 0.5 + sum(a * b for a, b in zip(d, u)) / depth / (2 * math.tan(math.radians(cam.vfov) / 2))
            in_front = bool(z > 0 and obj['id'] not in culled)
            meta[view['name']][obj['id']] = {'img_x': x, 'in_front': in_front,
                                             'visible': bool(in_front and 0 <= x <= 1 and 0 <= y <= 1)}
    return meta


def _render_views(spec_path: Path, meta_path: Path, blender_cmd: str) -> None:
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    get_engine(blender_cmd=blender_cmd).render(list(zip(room_scenes(spec), map(Path, spec['outputs']))))
    meta_path.write_text(json.dumps(_view_meta(spec)), encoding='utf-8')


def render_sketches(project, config: dict, blender_cmd: str = 'blender',
                    meta_dir: Path | None = None,
                    room_filter: set[str] | None = None) -> dict[str, Path]:
    """Render sketches for every derived room view that has entrance anchors.

    room_filter limits the run to the given room base names (case-insensitive).

    PNGs are staged in a temporary directory and committed only after all
    renders succeed. View JSONs are marked stale only when sketch bytes change.
    meta_dir, when given, receives projection metadata for verification.
    """
    from lib.studio.artist import load_character_refs

    load_character_refs(project)
    wanted = {name.lower() for name in room_filter} if room_filter else None
    entrance_suffix = 'View-From-Entrance'
    derived_suffixes = [s for s, _ in _ROOM_VIEWS if s != entrance_suffix]
    groups = []
    for name, info in project.character_info.items():
        kind = info.get('type')
        primary = entrance_suffix if kind == 'Room' else 'View-Primary' if kind == 'Outdoor' else None
        if not primary or not name.endswith(f'-{primary}') or not info.get('anchor_points'):
            continue
        base = name[: -(len(primary) + 1)]
        if wanted and base.lower() not in wanted and name.lower() not in wanted:
            continue
        if kind == 'Room':  # a floor plan predates VFE, so VFE renders from its sketch too
            view_names = [f'{base}-{s}' for s in ([entrance_suffix] if info.get('floor_plan') else []) + derived_suffixes]
        else:  # outdoor: Opposite plus whichever cross-axis views the location has
            view_names = [f'{base}-{s}' for s in sorted(_OUTDOOR_VIEW_SUFFIXES - {'View-Primary'})
                          if s == 'View-Opposite' or f'{base}-{s}' in project.character_info]
        groups.append((info, base, view_names, kind == 'Outdoor'))

    if not groups:
        logger.info('  No anchored rooms or outdoor locations found; nothing to sketch.')
        return {}

    staged: list[list] = []
    changed: list[str] = []
    with tempfile.TemporaryDirectory(prefix='room-sketches-') as tmp:
        tmp_dir = Path(tmp)
        for entrance_info, base, view_names, outdoor in groups:
            anchors = entrance_info['anchor_points']
            try:
                spec = build_sketch_spec(
                    anchors, view_names, config, entrance_info.get('visual_desc', '')
                )
            except ValueError as exc:
                logger.warning(f'  Sketch skipped for {base}: {exc}')
                continue
            spec['outdoor'] = outdoor

            spec_path = tmp_dir / f'{safe_name(base)}.spec.json'
            meta_path = tmp_dir / f'{safe_name(base)}.meta.json'
            outputs = [str(tmp_dir / f'{safe_name(name)}.sketch.png') for name in view_names]
            spec['outputs'] = outputs
            spec_path.write_text(json.dumps(spec, indent=2), encoding='utf-8')
            try:
                _render_views(spec_path, meta_path, blender_cmd)
            except RuntimeError as exc:
                logger.error(f'  Sketch failed for {base}: {exc}')
                raise
            if meta_dir is not None:
                meta_dir.mkdir(parents=True, exist_ok=True)
                (meta_dir / f'{safe_name(base)}.meta.json').write_bytes(meta_path.read_bytes())
            meta = json.loads(meta_path.read_text(encoding='utf-8')) if outdoor else {}
            blank = {name for name, objs in meta.items() if not any(o['visible'] for o in objs.values())}
            for name in sorted(blank):  # a bare horizon passed as geometry truth contradicts the description
                logger.warning(f'  ⚠️  {name}: no anchored landmark in frame — no sketch; it renders from '
                               'View-Primary and its description (add anchors on that side to get one)')
            staged.append([view_names, outputs, blank])

        commit_plan = []
        for view_names, outputs, blank in staged:
            for name, out_path in zip(view_names, outputs):
                target = sketch_path(project.ref_dir, name)
                if name in blank:
                    if target.exists():
                        target.unlink()
                        changed.append(name)
                    continue
                current = Path(out_path).read_bytes()
                if not current:
                    raise RuntimeError(f'empty sketch for {name}')
                commit_plan.append((name, target,
                                    target.read_bytes() if target.exists() else None, current))

        rendered: dict[str, Path] = {}
        try:
            for name, target, previous, current in commit_plan:
                staged_target = target.with_name(target.name + '.tmp')
                staged_target.write_bytes(current)
                staged_target.replace(target)
                rendered[name] = target
                if previous != current:
                    changed.append(name)
        except OSError as exc:
            for name, target, previous, current in commit_plan:
                if previous is None:
                    target.unlink(missing_ok=True)
                else:
                    staged_target = target.with_name(target.name + '.tmp')
                    staged_target.write_bytes(previous)
                    staged_target.replace(target)
            raise RuntimeError(f'failed to commit sketches: {exc}') from exc

    for name in changed:
        # VTE does not render from its sketch.
        if name.endswith('-View-To-Entrance'):
            continue
        json_path = project.ref_dir / f'{safe_name(name)}.json'
        if not json_path.exists():
            continue
        data = json.loads(json_path.read_text(encoding='utf-8'))
        if data.get('needs_regenerate'):
            continue
        data['needs_regenerate'] = True
        atomic_write(json_path, json.dumps(data, indent=2))
        project.character_info[name] = data
    logger.info(f'  Rendered {len(rendered)} sketch(es); marked {len(changed)} view(s) stale')
    return rendered
