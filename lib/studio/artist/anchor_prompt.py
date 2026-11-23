"""Anchor prompting: anchor ids, entrance points, spatial visibility block."""
import json
import logging

from lib.core.project import Project
from lib.core.utils import safe_name
from lib.studio.artist.view_catalog import _OUTDOOR_VIEW_SUFFIXES, _X_AXIS_VIEWS
from lib.studio.artist.view_geometry import (
    _VIEW_CAMERA, _VIEW_FACING_WALL, _VIEW_POSITION_LABEL, view_camera,
    _is_wall_camera, _project_image_x, _view_hfov, _view_rig,
)
from lib.studio.room_geometry import resolve_room_height_m

logger = logging.getLogger(__name__)


def _anchor_id(obj: dict) -> str:
    """The name panels use for an anchor: its kebab-case `id`. `label` is free display text
    ("Heavy watertight hatch (open)") and only stands in for anchors saved without an id."""
    return obj.get('id') or obj.get('label', '')


def _anchor_title(obj: dict) -> str:
    name, label = _anchor_id(obj), obj.get('label', '')
    return f'{name} ({label})' if label and label != name else name


def _extract_camera_anchor_labels(camera_position: str, anchor_points: dict) -> set[str]:
    """Parse a camera_position string (e.g. 'near master-bed') and return the anchor ids it names."""
    if not camera_position or not anchor_points:
        return set()
    cp = camera_position.lower()
    cp_hyphenated = cp.replace(' ', '-')
    ids = {_anchor_id(obj) for obj in anchor_points.get('objects', [])}
    return {i for i in ids if i and (i in cp_hyphenated or i.replace('-', ' ') in cp)}


def _anchor_visibility_block(anchor_points: dict, view_suffix: str, camera_anchor_labels: frozenset = frozenset(),
                             camera_xy: tuple[float, float] | None = None,
                             camera_inset_m: float = 0.0,
                             room_height_m: float | None = None) -> str:
    """Produce camera setup header + per-object projected position data for a render prompt.

    Camera header describes position, facing wall, H-FOV, and perspective rules.
    For each visible anchor object outputs view-space coordinates:
      img_x   — normalised [0=image-left … 1=image-right] lateral position in this view
      depth   — normalised distance from camera along the viewing axis; also in metres when room_m present
      z       — object height (0=floor, 1=ceiling; unchanged across views)
      span    — projected footprint width in image-x (from width_x or depth_y depending on axis)

    Objects at or behind the camera plane (depth ≤ 0.02) are listed as NOT VISIBLE.
    Returns empty string when anchor_points is absent or has no objects.

    Wall views measure depth from the cut plane camera_inset_m into the room;
    the lens and the camera's distance behind that cut come from _view_rig,
    as in the sketch (room_height_m defaults to the anchors' own height).

    camera_xy — a panel's own camera position in room coords. The view's canonical camera
    sits on a wall; a panel camera usually does not, so depth and the behind-camera split
    are measured from camera_xy. Its lens is unknown here, so lateral position is given as
    an offset from the camera axis instead of an image-x fraction.
    """
    objects = anchor_points.get('objects', []) if anchor_points else []
    if not objects or view_suffix not in _VIEW_CAMERA:
        return ''

    cx, cy, fdx, fdy = view_camera(view_suffix, anchor_points)
    if camera_xy:
        cx, cy = camera_xy
    room_m: list = anchor_points.get('room_m') or []
    # Match the sketch camera: wall-mounted views step 0.5 m into the room.
    # This hides wall-mounted objects at the camera (they are behind the lens
    # and the sketch culls them), instead of telling the model they are visible.
    inset_applied = bool(
        camera_inset_m and not camera_xy and _is_wall_camera(cx, cy)
        and len(room_m) >= 2
    )
    if inset_applied:
        room_w0, room_d0 = float(room_m[0]), float(room_m[1])
        if room_w0 > 0:
            cx += fdx * camera_inset_m / room_w0
        if room_d0 > 0:
            cy += fdy * camera_inset_m / room_d0
    # Depth axis physical dimension: Y-axis views → room depth (room_m[1]); X-axis views → room width (room_m[0])
    depth_dim_m: float | None = (
        float(room_m[1]) if fdy != 0 and len(room_m) >= 2 else
        float(room_m[0]) if fdx != 0 and len(room_m) >= 1 else None
    )
    # Lateral axis: Y-axis views project room-X to image-X; X-axis views project room-Y to image-X.
    lateral_is_y = view_suffix in _X_AXIS_VIEWS
    lateral_dim_m: float | None = (
        float(room_m[1]) if lateral_is_y and len(room_m) >= 2 else
        float(room_m[0]) if not lateral_is_y and len(room_m) >= 1 else None
    )

    def _offset_label(lat: float) -> str:
        """Signed offset from the camera axis (positive = image-right), in metres when known."""
        if abs(lat) < 0.03:  # under ~15 cm in a 5 m room: closer than anchor estimates are accurate
            return 'on camera axis'
        size = f'{abs(lat) * lateral_dim_m:.1f}m' if lateral_dim_m else f'{abs(lat):.2f} of room span'
        return f"{size} {'right' if lat > 0 else 'left'} of camera axis"

    def _x_label(v: float) -> str:
        if v < 0.25:
            return 'image-left'
        if v > 0.75:
            return 'image-right'
        if v < 0.42:
            return 'left-of-center'
        if v > 0.58:
            return 'right-of-center'
        return 'image-center'

    def _depth_label(d: float) -> str:
        if d < 0.15:
            return 'near-camera'
        if d < 0.40:
            return 'mid-ground'
        if d < 0.70:
            return 'background'
        return 'far-background'

    def _z_label(z: float) -> str:
        if z < 0.15:
            return 'floor-level'
        if z < 0.45:
            return 'table-height'
        if z < 0.75:
            return 'mid-height'
        return 'ceiling-level'

    # ── Camera header ──────────────────────────────────────────────────────────
    pos_label = _VIEW_POSITION_LABEL.get(view_suffix, '')
    facing = _VIEW_FACING_WALL.get(view_suffix, '')
    if room_height_m is None:
        room_height_m, _ = resolve_room_height_m(anchor_points, '')
    hfov, back = (_view_rig(view_suffix, room_m, room_height_m) if inset_applied
                  else (_view_hfov(view_suffix, room_m), 0.0))
    # Physical camera position in metres when room_m available
    room_w = float(room_m[0]) if len(room_m) >= 1 else None
    room_d = float(room_m[1]) if len(room_m) >= 2 else None
    pos_m = ''
    if room_w and room_d:
        left_edge, near_edge = ('left edge', 'near end') if view_suffix in _OUTDOOR_VIEW_SUFFIXES else ('left wall', 'entrance')
        pos_m = f'  ({cx * room_w:.1f}m from {left_edge}, {cy * room_d:.1f}m from {near_edge})'
    # Apparent size ∝ 1 / distance from the lens, which stands `back` behind depth 0.
    back_frac = back / depth_dim_m if depth_dim_m else 0.0
    size_ratio = (1.0 + back_frac) / (0.25 + back_frac)
    perspective_note = (
        f"  Perspective: objects at depth 0.25 appear ~{size_ratio:.1f}× larger than at depth 1.0; "
        "closer objects sit lower in frame, farther objects converge toward the horizon "
        "(eye-level ≈ z=0.45). Lateral spread widens near camera, compresses toward center at depth."
    )
    cam_lines = [
        'CAMERA SETUP:',
        f"  Position: room_x={cx:.2f}, room_y={cy:.2f}{pos_m}  — {'this shot camera' if camera_xy else pos_label}",
        f'  Facing:   {facing}',
        *([] if camera_xy else [f'  H-FOV:    ~{hfov:.0f}°']),
        *([f'  Cut:      the room is cut {camera_inset_m:.1f} m inside the camera wall — that wall '
           'and everything before the cut are hidden; depth 0 is the cut']
          if inset_applied else []),
        *([f'  Camera:   {back - camera_inset_m:.1f} m behind the wall, outside the room (fourth wall '
           'removed, as on a film set) — natural perspective, no wide-angle distortion']
          if back > camera_inset_m else
          [f'  Camera:   {back:.1f} m behind the cut, inside the room'] if back > 0 else []),
        perspective_note,
    ]

    # ── Per-object projection ──────────────────────────────────────────────────
    visible: list[str] = []
    hidden: list[str] = []

    for obj in objects:
        ox = float(obj.get('x', 0.5))
        oy = float(obj.get('y', 0.5))
        oz = float(obj.get('z', 0.3))
        wx = float(obj.get('width_x', 0.0))
        dy = float(obj.get('depth_y', 0.0))

        depth = (ox - cx) * fdx + (oy - cy) * fdy

        is_cam_anchor = _anchor_id(obj) in camera_anchor_labels
        cam_remark = '  ← CAMERA POSITION: camera lens is placed here' if is_cam_anchor else ''

        # depth ≤ 0.02: at or behind the camera plane
        if depth <= 0.02 and camera_xy and is_cam_anchor:
            # The lens sits at this object: it has a footprint, so an edge may still be in frame.
            visible.append(
                f"  - {_anchor_title(obj)}  ← CAMERA POSITION: lens is at this object — "
                "foreground edge at most, never in mid or far background"
            )
            continue
        if depth <= 0.02:
            suffix = ' ← CAMERA POSITION: at/behind camera — MUST NOT appear in this view' if is_cam_anchor else ''
            hidden.append(f"  - {_anchor_title(obj)}{suffix}")
            continue

        img_x = _project_image_x(ox, oy, view_suffix)
        footprint = dy if lateral_is_y else wx
        half = footprint / 2.0
        span_lo = max(0.0, img_x - half)
        span_hi = min(1.0, img_x + half)

        dist_str = f', ~{depth * depth_dim_m:.1f}m' if depth_dim_m else ''
        # A shot camera with known metres uses the DEPTH bands of pass2_visual.md (FG ≤1.5 m,
        # MG 1.5–4 m, BG >4 m), so this block and visual_start cannot disagree; the
        # room-fraction labels would call 1.1 m "background" in a 2.5 m room.
        depth_m = depth * depth_dim_m if camera_xy and depth_dim_m else None
        depth_label = (
            _depth_label(depth) if depth_m is None else
            'FG' if depth_m <= 1.5 else 'MG' if depth_m <= 4 else 'BG'
        )
        # Image-right is the forward vector rotated clockwise: (fdy, -fdx).
        lateral_str = (
            _offset_label((ox - cx) * fdy - (oy - cy) * fdx) if camera_xy else
            f"img_x≈{img_x:.2f} ({_x_label(img_x)})"
        )
        line = (
            f"  - {_anchor_title(obj)}{cam_remark}\n"
            f"    {lateral_str}"
            f"  depth≈{depth:.2f} ({depth_label}{dist_str})"
            f"  z≈{oz:.2f} ({_z_label(oz)})"
        )
        if footprint > 0.02 and not camera_xy:
            line += f"  span img_x {span_lo:.2f}–{span_hi:.2f}"
        if is_cam_anchor:
            line += '  — do NOT render this object in mid or far background'
        visible.append(line)

    if not visible and not hidden:
        return ''

    lines: list[str] = cam_lines + ['']
    if visible:
        lines.append(
            'OBJECTS AHEAD OF THIS CAMERA (offset from camera axis, depth along it):' if camera_xy else
            'OBJECTS VISIBLE FROM THIS CAMERA ANGLE (view-space coordinates):'
        )
        lines.extend(visible)
    if hidden:
        lines.append('OBJECTS BEHIND THE CAMERA — MUST NOT APPEAR IN THIS IMAGE:')
        lines.extend(hidden)
    return '\n'.join(lines) + '\n'


def _load_entrance_anchor_points(name: str, view_suffix: str | None, project: Project) -> dict:
    """Load anchor_points from the canonical sibling JSON (View-From-Entrance for rooms,
    View-Primary for outdoor locations), if available.

    Falls back to any anchor_points already embedded in the char dict.
    Returns empty dict when unavailable.
    """
    canonical = 'View-Primary' if view_suffix in _OUTDOOR_VIEW_SUFFIXES else 'View-From-Entrance'
    if view_suffix and view_suffix != canonical:
        base = name[: -(len(view_suffix) + 1)]
        entrance_json = project.ref_dir / f"{safe_name(f'{base}-{canonical}')}.json"
        if entrance_json.exists():
            try:
                data = json.loads(entrance_json.read_text(encoding='utf-8'))
                ap = data.get('anchor_points')
                if ap:
                    return ap
            except Exception as e:
                logger.warning(f"⚠️  Unreadable {entrance_json.name}: {e}")
    return {}

