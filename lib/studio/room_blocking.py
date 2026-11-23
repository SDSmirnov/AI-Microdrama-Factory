"""Room and outdoor blocking: panel camera from its view, actor positions → frame side, depth, facing."""
import math
import re
from dataclasses import dataclass

from lib.core.utils import VIEW_CANONICAL
from lib.studio.artist.view_catalog import _VIEW_CAMERA_PHRASES
from lib.studio.artist.view_geometry import _VIEW_CAMERA, _is_wall_camera, _view_rig, view_camera
from lib.studio.blocking import (
    SCALE_FRAME_M, Camera, equivalent_focal_mm, facing, frame_fovs, parse_aspect, placement, scale_of,
)
from lib.studio.positions import IN_VEHICLE, HEAD_Z, Pose, location_anchors, match_anchor, resolve
from lib.studio.room_geometry import CAMERA_HEIGHT_M, WALL_INSET_M, WALL_NAMES, resolve_room_height_m
from lib.studio.room_models import srgb_hex_to_linear
from lib.studio.room_sketch import _cut, build_sketch_spec
from lib.studio.vehicle_geometry import MANNEQUIN_COLORS

_CONSISTENT = 0.35   # max normalized distance of an LLM camera_x/y from its view's camera
_WIDE_HFOV_MAX = 70  # a room view's fit-the-wall lens is too wide for a panel frame
_DEPTH_BANDS = (1.5, 4.0)
_ON_WALL_M = 0.8
_NEAR_AXIS_M = 1.5
# Short-side lens per tight scale (≈ 35/45/50/70 mm full-frame); the camera dollies to fit SCALE_FRAME_M.
_TIGHT_SHORT_FOV = {'MS': 37.0, 'MCU': 30.0, 'CU': 27.0, 'ECU': 19.5}
_TOWARD_VIEW = math.cos(math.radians(60))  # a named camera or a partner counts only within 60° of the view axis
_OTS_REACH_M = 1.3  # a partner this close to the subject, on the camera side, frames an over-the-shoulder
_SEATED_EYE_M = 1.2
_MAX_NAMED_LENS_MM = 100  # a named camera that would need a longer lens is too far for the shot: dolly instead


@dataclass(frozen=True)
class RoomBlocking:
    location: str
    suffix: str
    camera: Camera
    poses: dict[str, Pose]
    room_m: tuple[float, float]
    room_h: float
    anchors: dict
    note: str | None   # LLM camera contradicting the view, replaced by the view camera
    aspect: tuple[int, int]
    cut_back: float    # wall views: camera distance behind the section cut, as in the room-view sketches
    ots: str | None = None  # partner framed as the out-of-focus foreground shoulder

    def __hash__(self):
        return hash((self.location, self.suffix, self.camera, tuple(self.poses.items()), self.aspect))

    def colors(self) -> dict[str, str]:
        return {name: MANNEQUIN_COLORS[i % len(MANNEQUIN_COLORS)][0] for i, name in enumerate(self.poses)}


def view_suffix(location_ref: str) -> str | None:
    return next((s for s in sorted(_VIEW_CAMERA, key=len, reverse=True) if location_ref.endswith(f'-{s}')), None)


def _subject(panel: dict, poses: dict[str, Pose]) -> str | None:
    target = (panel.get('drama_requirements') or {}).get('focus_priority') or {}
    target = (target.get('primary_target', '') if isinstance(target, dict) else str(target)).lower()
    framed = [a.get('name') for a in panel.get('state', {}).get('actors', []) if a.get('in_frame') and a.get('name') in poses]
    return next((n for n in framed if n.lower() in target or target in n.lower() and target), framed[0] if framed else None)


_BODY_TOP = {'standing': 1.75, 'seated': 1.35, 'kneeling': 1.15, 'crouching': 1.05, 'lying': 0.7}


def _inside_body(point, pose: Pose, room_m) -> bool:
    """Point within a mannequin: 0.3 m around the hip axis, or along a lying body (it extends behind the head)."""
    if point[2] > _BODY_TOP[pose.posture]:
        return False
    hx, hy = pose.metres(room_m)
    if pose.posture == 'lying':
        rad = math.radians(pose.facing_deg)
        fx, fy = math.sin(rad), -math.cos(rad)
        t = min(1.6, max(0.0, -((point[0] - hx) * fx + (point[1] - hy) * fy)))
        hx, hy = hx - fx * t, hy - fy * t
    return math.hypot(point[0] - hx, point[1] - hy) < 0.3


def _clear_view(x: float, y: float, z: float, forward: tuple[float, float], poses: dict[str, Pose], room_m,
                skip: str | None, inside: bool) -> tuple[float, float, float]:
    """Step past anyone in the first half-metre of the lens, then back off out of any body.

    inside: the camera stands in the room, so it stays there (only wall views have a section cut)."""
    w, d = room_m
    fdx, fdy = forward
    keep = (lambda px, py: (min(w - 0.1, max(0.1, px)), min(d - 0.1, max(0.1, py)))) if inside else (lambda px, py: (px, py))
    for name, other in poses.items():
        ox, oy = other.metres(room_m)
        ahead, side = (ox - x) * fdx + (oy - y) * fdy, (ox - x) * fdy - (oy - y) * fdx
        if name != skip and 0 < ahead < 0.5 and abs(side) < 0.35:
            shift = 0.4 if side <= 0 else -0.4
            x, y = keep(x + fdy * shift, y - fdx * shift)
    for _ in range(10):
        if not any(_inside_body((x, y, z), other, room_m) for other in poses.values()):
            break
        nx, ny = keep(x - fdx * 0.15, y - fdy * 0.15)
        if (nx, ny) == (x, y):  # against the wall: stop rather than leave the room
            break
        x, y = nx, ny
    return x, y, z


def _head(pose: Pose, room_m, drop: float = 0.0) -> tuple[float, float, float]:
    x, y = pose.metres(room_m)
    return x, y, HEAD_Z[pose.posture] - drop


def _toward(origin, target, forward, min_dist: float = 0.5) -> bool:
    dx, dy = target[0] - origin[0], target[1] - origin[1]
    n = math.hypot(dx, dy)
    return n > min_dist and (dx * forward[0] + dy * forward[1]) / n >= _TOWARD_VIEW


def _named_camera(panel: dict, anchors: dict, room_m, target, forward) -> tuple[float, float, float] | None:
    """camera_position naming an anchor ('inside taxi at street-curb') that looks at the target along the view."""
    text = panel.get('camera_position') or ''
    for token in re.findall(r'[a-z0-9]+(?:-[a-z0-9]+)+', text.lower()) or [text]:
        item = match_anchor(token, anchors, strict=True)
        if not item:
            continue
        ax, ay = float(item.get('x', 0.5)) * room_m[0], float(item.get('y', 0.5)) * room_m[1]
        if not _toward((ax, ay), target, forward):
            return None
        dx, dy = target[0] - ax, target[1] - ay
        n = math.hypot(dx, dy)
        step = min(0.5, n / 3)  # off a wall or furniture face, toward the subject
        seated = IN_VEHICLE.search(text) or re.search(r'\b(?:seated|sitting)\b', text, re.I)
        return ax + dx / n * step, ay + dy / n * step, _SEATED_EYE_M if seated else CAMERA_HEIGHT_M
    return None


def _ots_partner(subject: str, poses: dict[str, Pose], room_m, forward) -> str | None:
    """The nearest other person within reach of the subject and on the camera side of them."""
    sx, sy, _ = _head(poses[subject], room_m)
    near = [(math.dist(_head(p, room_m)[:2], (sx, sy)), n) for n, p in poses.items() if n != subject]
    near = [(dist, n) for dist, n in near
            if dist < _OTS_REACH_M and _toward(_head(poses[n], room_m), (sx, sy), forward, min_dist=0.05)]
    return min(near)[1] if near else None


def panel_camera(panel: dict, suffix: str, poses: dict[str, Pose], room_m, room_h: float,
                 aspect: tuple[int, int], anchors: dict | None = None) -> tuple[Camera, str | None, float, str | None]:
    """(camera, contradiction note, wall-cut distance — 0 unless the view camera stands behind a wall, OTS partner)."""
    w, d = room_m
    cx, cy, fdx, fdy = view_camera(suffix, anchors)
    hfov, back = _view_rig(suffix, list(room_m), room_h)
    step = WALL_INSET_M - back if _is_wall_camera(cx, cy) else 0.0
    x, y = cx * w + fdx * step, cy * d + fdy * step
    note, cut = None, back if step else 0.0
    scale, subject = scale_of(panel), _subject(panel, poses)
    framed = sum(1 for a in panel.get('state', {}).get('actors', []) if a.get('in_frame') and a.get('name') in poses)
    tight = scale != 'WS' and subject and not (framed >= 2 and scale == 'MS')
    lx, ly = panel.get('camera_x'), panel.get('camera_y')
    if not tight and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in (lx, ly)):
        if math.hypot(lx - cx, ly - cy) <= _CONSISTENT:
            x, y, cut = lx * w, ly * d, 0.0
        else:
            note = f'camera_x/y ({lx:.2f}, {ly:.2f}) contradict {suffix}; the view camera is used'
    lz = panel.get('camera_z')
    z = lz * room_h if isinstance(lz, (int, float)) and 0 < lz <= 1 else CAMERA_HEIGHT_M
    pos, ots = (x, y, z), None
    framed_poses = [poses[a['name']] for a in panel.get('state', {}).get('actors', [])
                    if a.get('in_frame') and a.get('name') in poses]
    if tight:
        aim = _head(poses[subject], room_m, 0.25 if scale == 'MS' else 0.0)
    else:
        heads = [_head(p, room_m, 0.3) for p in framed_poses] or [(x + fdx, y + fdy, z)]
        aim = tuple(sum(c) / len(heads) for c in zip(*heads))
    group_width = None
    if not tight and scale == 'MS' and len(framed_poses) >= 2:
        spread = [p.metres(room_m)[0] * fdy - p.metres(room_m)[1] * fdx for p in framed_poses]  # along the view's right
        group_width = max(spread) - min(spread) + 1.2
    named = _named_camera(panel, anchors, room_m, aim, (fdx, fdy)) if anchors else None
    if named:
        # the story's camera: stand where camera_position says, aim at the subject, lens from the framing and distance
        pos = _clear_view(*named, (fdx, fdy), poses, room_m, subject, inside=True)
        width = SCALE_FRAME_M[scale] if tight else group_width
        if width is None:
            camera = Camera(pos, aim, *frame_fovs(min(hfov, _WIDE_HFOV_MAX), aspect, 'h'))
        else:
            camera = Camera(pos, aim, *frame_fovs(math.degrees(2 * math.atan(width / 2 / max(0.3, math.dist(pos, aim)))),
                                                  aspect, 'short'))
        if width is None or equivalent_focal_mm(camera) <= _MAX_NAMED_LENS_MM:
            return camera, None, 0.0, None
    if tight and scale != 'ECU' and (ots := _ots_partner(subject, poses, room_m, (fdx, fdy))):
        # dialogue coverage: behind the partner's shoulder, looking at the subject
        px, py, pz = _head(poses[ots], room_m)
        sx, sy, _ = aim
        n = math.hypot(sx - px, sy - py)
        ux, uy = (sx - px) / n, (sy - py) / n
        # keep screen direction: the partner's shoulder lands on their side of the subject in this view
        side = 1.0 if (px - sx) * fdy - (py - sy) * fdx >= 0 else -1.0  # +1: partner on the view's right
        ox, oy = -fdy * side * 0.25, fdx * side * 0.25  # camera steps the other way
        pos = (min(w - 0.1, max(0.1, px - ux * 0.55 + ox)), min(d - 0.1, max(0.1, py - uy * 0.55 + oy)),
               min(pz, aim[2] + 0.1))
        short = _TIGHT_SHORT_FOV[scale]
        hfov, vfov = frame_fovs(max(8.0, min(short * 1.4, math.degrees(2 * math.atan(
            SCALE_FRAME_M[scale] * 1.4 / 2 / math.dist(pos, aim))))), aspect, 'short')  # room for the shoulder
        return Camera(pos, aim, hfov, vfov), None, 0.0, ots
    if group_width:
        # a group MS frames the people, not the whole room: dolly in until they fill the frame width
        short = _TIGHT_SHORT_FOV['MS']
        back = group_width / 2 / math.tan(math.radians(frame_fovs(short, aspect, 'short')[0]) / 2)
        start = (min(w - 0.1, max(0.1, aim[0] - fdx * back)), min(d - 0.1, max(0.1, aim[1] - fdy * back)))
        pos = _clear_view(*start, CAMERA_HEIGHT_M, (fdx, fdy), poses, room_m, None, inside=True)
        return Camera(pos, aim, *frame_fovs(short, aspect, 'short')), note, 0.0, None
    if tight:
        # dolly in along the view axis: the view decides the side, the scale decides the distance
        pose = poses[subject]
        sx, sy = pose.metres(room_m)
        target = (sx, sy, HEAD_Z[pose.posture] - (0.25 if scale == 'MS' else 0.0))
        short = _TIGHT_SHORT_FOV[scale]
        back = SCALE_FRAME_M[scale] / 2 / math.tan(math.radians(short) / 2)
        cz = target[2] + (0.6 if pose.posture == 'lying' else 0.0)  # someone lying is framed from above
        start = (min(w - 0.1, max(0.1, sx - fdx * back)), min(d - 0.1, max(0.1, sy - fdy * back)))
        pos, cut = _clear_view(*start, cz, (fdx, fdy), poses, room_m, subject, inside=True), 0.0
        hfov, vfov = frame_fovs(short, aspect, 'short')
    else:
        pos = _clear_view(x, y, z, (fdx, fdy), poses, room_m, None, inside=0 <= x <= w and 0 <= y <= d)
        target = (pos[0] + fdx * 10, pos[1] + fdy * 10, z)
        hfov, vfov = frame_fovs(min(hfov, _WIDE_HFOV_MAX), aspect, 'h')
    return Camera(pos, target, hfov, vfov), note, cut, None


def panel_blocking(panel: dict, scene: dict | None, lookup, aspect: str = '9:16') -> RoomBlocking | None:
    """None outside anchored rooms/outdoor locations or when no in-frame actor resolves."""
    ref = (panel.get('location_references') or [(scene or {}).get('location', '')])[0]
    suffix = view_suffix(ref)
    anchors = location_anchors(ref, lookup) if suffix else None
    if not anchors:
        return None
    poses = resolve(panel, anchors)
    if not any(a.get('in_frame') and a.get('name') in poses for a in panel.get('state', {}).get('actors', [])):
        return None
    room_m = tuple(anchors['room_m'])
    room_h, _ = resolve_room_height_m(anchors)
    ratio = parse_aspect(aspect)
    camera, note, cut, ots = panel_camera(panel, suffix, poses, room_m, room_h, ratio, anchors)
    return RoomBlocking(ref.rsplit(f'-{suffix}', 1)[0], suffix, camera, poses, room_m, room_h, anchors, note, ratio, cut, ots)


def actor_lines(b: RoomBlocking, with_sketch: bool = False, colors: dict[str, str] | None = None) -> list[str]:
    lines = []
    for name, pose in b.poses.items():
        sx, sy = pose.metres(b.room_m)
        head_z = HEAD_Z[pose.posture]
        head, chest = (sx, sy, head_z), (sx, sy, max(0.3, head_z - 0.45))
        text, visible, head_on = placement(b.camera, head, chest, _DEPTH_BANDS)
        where = f"{pose.posture}{f', at [{pose.anchor}]' if pose.anchor else ''}"
        tag = f' [{colors[name]} mannequin]' if with_sketch and visible and colors and name in colors else ''
        if not visible:
            lines.append(f'- {name} ({where}): {text} — do not draw this person.')
            continue
        rad = math.radians(pose.facing_deg)
        turn = f'; {facing(b.camera, head, (math.sin(rad), -math.cos(rad)))}' if head_on else ''
        if name == b.ots:
            turn += '; over-the-shoulder foreground: their back and shoulder, out of focus'
        lines.append(f'- {name}{tag} ({where}): {text}{turn}.')
    return lines


def background_line(b: RoomBlocking) -> str | None:
    """The wall the camera axis meets past its target, and the anchors on it near that point (rooms only)."""
    if VIEW_CANONICAL.get(b.suffix, b.suffix) != 'View-From-Entrance':
        return None
    (cx, cy, _), (tx, ty, _) = b.camera.position, b.camera.target
    dx, dy = tx - cx, ty - cy
    w, d = b.room_m
    hits = {wall: t for wall, t in (('x0', -tx / dx if dx < 0 else None), ('x1', (w - tx) / dx if dx > 0 else None),
                                    ('y0', -ty / dy if dy < 0 else None), ('y1', (d - ty) / dy if dy > 0 else None))
            if t is not None}
    if not hits:
        return None
    wall = min(hits, key=hits.get)
    t = max(hits[wall], 0.0)
    hx, hy = tx + t * dx, ty + t * dy

    def gaps(o):
        ox, oy = o.get('x', 0.5) * w, o.get('y', 0.5) * d
        to_wall = {'x0': ox, 'x1': w - ox, 'y0': oy, 'y1': d - oy}[wall]
        return to_wall, math.hypot(ox - hx, oy - hy)

    near = sorted((g[1], o.get('id') or o.get('label', '')) for o in b.anchors.get('objects', [])
                  if (g := gaps(o))[0] <= _ON_WALL_M and g[1] <= _NEAR_AXIS_M)
    objects = f" — on it near the camera axis: {', '.join(f'[{i}]' for _, i in near[:3])}" if near else ''
    return f'Background behind the subject: the {WALL_NAMES[wall]}{objects}.'


def blocking_block(b: RoomBlocking, with_sketch: bool = False, colors: dict[str, str] | None = None) -> str:
    lines = [
        'ROOM BLOCKING — AUTHORITATIVE (positions resolved from the location anchors; overrides frame-left/right, '
        'distance and facing wording elsewhere in this prompt):',
        f"Camera: {b.location}, {_VIEW_CAMERA_PHRASES.get(b.suffix, b.suffix)}; lens ≈ {equivalent_focal_mm(b.camera)} mm full-frame equivalent.",
        *filter(None, [background_line(b)]),
        *actor_lines(b, with_sketch, colors),
    ]
    if with_sketch:
        lines.append('IMAGE 1 is a 3D blocking sketch of this exact camera: copy its camera position, lens, perspective, '
                     'furniture layout and each coloured mannequin\'s place, posture and head direction. It carries NO '
                     'materials, colours, clothing or faces — mannequins become the referenced characters; grey shapes '
                     'take the location reference\'s materials.')
    return '\n'.join(lines)


def sketch_spec(b: RoomBlocking, max_px: int = 1024) -> dict:
    """One-view sketch spec (render3d.shapes.room_scenes): the room's objects, this panel's camera and a mannequin per actor."""
    spec = build_sketch_spec(b.anchors, [], {})
    cam = b.camera
    fx, fy = cam.target[0] - cam.position[0], cam.target[1] - cam.position[1]
    n = math.hypot(fx, fy) or 1.0
    forward = (fx / n, fy / n)
    w, h = b.aspect
    scale = max_px / max(w, h)
    mannequins = []
    for (name, pose), (_, hex_) in zip(b.poses.items(), MANNEQUIN_COLORS * 4):
        sx, sy = pose.metres(b.room_m)
        rad = math.radians(pose.facing_deg)
        yaw = math.degrees(math.atan2(-math.sin(rad), -math.cos(rad)))  # anchor facing → model yaw (0 = +y)
        mannequins.append({'id': re.sub(r'[^a-z0-9]+', '-', name.lower()), 'color': srgb_hex_to_linear(hex_),
                           'hip': [sx, sy], 'head': [sx, sy, HEAD_Z[pose.posture]], 'yaw_pitch': [yaw, 0.0],
                           'body_yaw': yaw, 'posture': pose.posture, 'seat_z': 0.45})
    view = {'name': f'{b.location}-panel', 'suffix': b.suffix, 'position_m': list(cam.position),
            'target_m': list(cam.target), 'forward': list(forward), 'hfov_degrees': cam.hfov,
            'width_px': max(1, round(w * scale)), 'height_px': max(1, round(h * scale)), 'mannequins': mannequins,
            **(_cut(spec['objects'], list(cam.position[:2]), forward, b.cut_back) if b.cut_back else {})}
    return {'room_m': spec['room_m'], 'objects': spec['objects'], 'outdoor': b.suffix in ('View-Primary', 'View-Opposite'),
            'views': [view]}


def annotate(scenes: list[dict], lookup, aspect: str = '9:16') -> dict:
    """Write resolved actor `pos` and the derived camera onto anchored panels, in place.

    Camera fields: camera_x/y/z (normalized, corrected when they contradicted the view), camera_look_x/y/z,
    camera_hfov. Returns {'panels', 'placed', 'in_frame', 'camera_fixed': [(scene, panel, note)]}.
    """
    stats = {'panels': 0, 'placed': 0, 'in_frame': 0, 'camera_fixed': []}
    for scene in scenes:
        for panel in scene.get('panels', []):
            for actor in panel.get('state', {}).get('actors', []):
                actor.pop('pos', None)
            b = panel_blocking(panel, scene, lookup, aspect)
            if not b:
                continue
            stats['panels'] += 1
            w, d = b.room_m
            for actor in panel.get('state', {}).get('actors', []):
                pose = b.poses.get(actor.get('name'))
                stats['in_frame'] += bool(actor.get('in_frame'))
                if pose:
                    actor['pos'] = pose.as_dict(b.room_m)
                    stats['placed'] += bool(actor.get('in_frame'))
            (x, y, z), (tx, ty, tz) = b.camera.position, b.camera.target
            panel.update(camera_x=round(x / w, 3), camera_y=round(y / d, 3), camera_z=round(z / b.room_h, 3),
                         camera_look_x=round(tx / w, 3), camera_look_y=round(ty / d, 3),
                         camera_look_z=round(tz / b.room_h, 3), camera_hfov=round(b.camera.hfov, 1))
            if b.note:
                stats['camera_fixed'].append((scene.get('scene_id'), panel.get('panel_index'), b.note))
    return stats
