"""Car-interior blocking: seats, shots and projection shared by the prompt block and the Blender sketch.

Vehicle frame: x = toward the vehicle's right, y = toward the hood (0 = front hip point), z = up from the floor.
"""
import math
import os
import re
from dataclasses import dataclass

from lib.studio.blocking import (
    Camera, basis, equivalent_focal_mm, facing, frame_fovs, lateral, parse_aspect, placement, scale_of, tight_fov,
)
from lib.studio.room_models import srgb_hex_to_linear

INTERIOR_SUFFIXES = ('-Interior-From-Entrance', '-Interior-To-Entrance')

SEATS = ('driver', 'front-passenger', 'rear-left', 'rear-center', 'rear-right',
         'third-left', 'third-center', 'third-right')
SIDE_SEATS = tuple(s for s in SEATS if not s.endswith('center'))

# Assigned in seat order; distinct from the grey cabin.
MANNEQUIN_COLORS = (
    ('red', '#d62828'), ('blue', '#1d6fd6'), ('yellow', '#f2c400'), ('green', '#2a9d3f'),
    ('magenta', '#c2188f'), ('cyan', '#10a5b8'), ('orange', '#ef7d10'), ('purple', '#6a3fc1'),
)


@dataclass(frozen=True)
class Body:
    label: str
    half_width: float      # inner half width at shoulder height
    front_x: float         # |x| of the front seats
    rear_x: float          # |x| of the outer rear seats
    rear_y: float          # rear-row hip point
    third_y: float | None  # third-row hip point, None = two rows
    rear_wall_y: float     # rear glass (sedan parcel shelf / SUV tailgate)
    roof_z: float
    belt_z: float          # window sill height
    cushion_z: float       # seat cushion top
    dash_y: float = 0.62   # dashboard rear face
    hood_len: float = 1.1
    trunk_len: float = 0.0  # sedan trunk behind the rear glass


BODIES = {
    'sedan': Body('sedan', 0.72, 0.36, 0.44, -0.92, None, -1.38, 1.12, 0.62, 0.30, trunk_len=0.95),
    'suv': Body('2-row SUV', 0.78, 0.40, 0.48, -0.98, None, -2.00, 1.25, 0.68, 0.34),
    'suv3': Body('3-row SUV', 0.80, 0.40, 0.48, -0.98, -1.88, -2.55, 1.28, 0.68, 0.34),
    'minivan': Body('minivan', 0.80, 0.42, 0.50, -1.02, -1.95, -2.60, 1.35, 0.62, 0.36),
}

_BODY_KEYWORDS = (
    ('minivan', ('minivan', 'minibus', 'people carrier', ' van ')),
    ('suv3', ('third row', 'third-row', 'three-row', '3-row', '7-seat', 'seven-seat', '8-seat')),
    ('suv', ('suv', 'crossover', 'jeep', 'land cruiser', 'escalade', 'range rover', 'g-wagon')),
)

HEAD_ABOVE_CUSHION = 0.66   # seated eye/head-centre height above the cushion
HEAD_BEHIND_HIP = 0.12      # reclined torso puts the head behind the hip point



@dataclass(frozen=True)
class Occupant:
    name: str
    seat: str
    color: str = 'red'
    color_hex: str = '#d62828'
    gaze_seat: str | None = None   # seat of the occupant they look at
    gaze: str = 'forward'          # forward | window | down | <seat>


# --------------------------------------------------------------------------- seats

def drive_side(vehicle_info: dict | None = None) -> str:
    side = ((vehicle_info or {}).get('drive_side') or os.getenv('AI_DRIVE_SIDE') or 'lhd').lower()
    return side if side in ('lhd', 'rhd') else 'lhd'


def seat_xy(seat: str, body: Body, side: str = 'lhd') -> tuple[float, float]:
    """Hip point of a seat. The driver sits on the vehicle's left in LHD cars."""
    driver_sign = -1 if side == 'lhd' else 1
    if seat == 'driver':
        return driver_sign * body.front_x, 0.0
    if seat == 'front-passenger':
        return -driver_sign * body.front_x, 0.0
    row, _, lateral = seat.partition('-')
    y = body.rear_y if row == 'rear' else body.third_y
    if y is None:
        raise ValueError(f'{body.label} has no {row} row')
    return {'left': -body.rear_x, 'center': 0.0, 'right': body.rear_x}[lateral], y


def head_point(seat: str, body: Body, side: str = 'lhd') -> tuple[float, float, float]:
    x, y = seat_xy(seat, body, side)
    return x, y - HEAD_BEHIND_HIP, body.cushion_z + HEAD_ABOVE_CUSHION


def seat_label(seat: str, side: str = 'lhd') -> str:
    """Human seat name; rear seats also say whom they sit behind."""
    behind = {'left': 'driver' if side == 'lhd' else 'front passenger',
              'right': 'front passenger' if side == 'lhd' else 'driver'}
    row, _, lateral = seat.partition('-')
    if seat in ('driver', 'front-passenger'):
        return seat.replace('-', ' ') + ' seat'
    where = f'behind the {behind[lateral]}' if lateral in behind else 'middle'
    return f"{seat.replace('-', ' ')} seat ({where})"


_OUTSIDE = re.compile(r'\b(outside|sidewalk|curb|street|on the road)\b')

_SEAT_PATTERNS = (
    ('third-center', r'third[- ]row.*(middle|cent(er|re))|(middle|cent(er|re)).*third[- ]row'),
    ('third-left', r'third[- ]row.*left|left.*third[- ]row'),
    ('third-right', r'third[- ]row.*right|right.*third[- ]row'),
    ('rear-center', r'(middle|cent(er|re)) of the (rear|back)|(rear|back)[- ](middle|cent(er|re))|(middle|cent(er|re)) (rear|back) seat'),
    ('rear-driver-side', r'(rear|back)\b[^.;]*driver|behind the driver'),
    ('rear-passenger-side', r'(rear|back)\b[^.;]*passenger|behind the (front )?passenger'),
    ('rear-left', r'(rear|back)[- ]left|left (rear|back)'),
    ('rear-right', r'(rear|back)[- ]right|right (rear|back)'),
    ('driver', r"driver'?s? seat|behind the wheel"),
    ('front-passenger', r'(front[- ])?passenger seat|shotgun|front[- ]passenger'),
)


def infer_seat(text: str | None, side: str = 'lhd') -> str | None:
    if not text:
        return None
    if text in SEATS:
        return text
    low = text.lower()
    if _OUTSIDE.search(low) and 'seat' not in low:
        return None
    for seat, pattern in _SEAT_PATTERNS:
        if re.search(pattern, low):
            if seat == 'rear-driver-side':
                return 'rear-left' if side == 'lhd' else 'rear-right'
            if seat == 'rear-passenger-side':
                return 'rear-right' if side == 'lhd' else 'rear-left'
            return seat
    return None


# --------------------------------------------------------------------------- vehicle lookup

def vehicle_base(panel: dict, scene: dict | None = None) -> str | None:
    for name in panel.get('location_references') or [(scene or {}).get('location', '')]:
        for suffix in INTERIOR_SUFFIXES:
            if name and name.endswith(suffix):
                return name[: -len(suffix)]
    return None


def resolve_body(infos: list[dict]) -> str:
    for info in infos:
        if info.get('body') in BODIES:
            return info['body']
    text = ' ' + ' '.join(f"{i.get('visual_desc', '')} {i.get('video_visual_desc', '')}" for i in infos).lower() + ' '
    return next((key for key, words in _BODY_KEYWORDS if any(w in text for w in words)), 'sedan')


def _norm(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '', (name or '').lower())


def _mention(text: str, actor: dict) -> int | None:
    """Where the actor is named in text, or None. 'Kidnapper' names The-Kidnapper."""
    norm = _norm(text)
    keys = {_norm(actor.get('name', '')), _norm(actor.get('visual_ref', ''))} - {''}
    found = [norm.find(k) for k in keys if k in norm] + [0 for k in keys if norm and norm in k]
    return min(found) if found else None


def _matches(text: str, actor: dict) -> bool:
    return _mention(text, actor) is not None


def occupants(panel: dict, side: str, body: Body) -> list[Occupant]:
    """Seated actors; legacy panels without vehicle_position fall back to the position text."""
    seated = {}
    for actor in panel.get('state', {}).get('actors', []):
        explicit = actor.get('vehicle_position')
        seat = infer_seat(explicit if explicit else actor.get('position'), side)
        if seat and (body.third_y is not None or not seat.startswith('third')):
            seated.setdefault(seat, actor)
    seated = sorted(seated.items(), key=lambda item: SEATS.index(item[0]))
    result = []
    for i, (seat, actor) in enumerate(seated):
        gaze_text = (actor.get('gaze_target') or '').lower()
        hits = [(pos, s) for s, other in seated if other is not actor
                if (pos := _mention(gaze_text, other)) is not None]
        gaze_seat = min(hits)[1] if hits else None  # 'X, then Y' looks at X
        gaze = (gaze_seat or ('down' if re.search(r'\b(phone|lap|down|hands|floor)\b', gaze_text)
                              else 'window' if re.search(r'\b(window|door)', gaze_text) else 'forward'))
        color, hex_ = MANNEQUIN_COLORS[i % len(MANNEQUIN_COLORS)]
        result.append(Occupant(actor.get('visual_ref') or actor.get('name', f'occupant-{i}'),
                               seat, color, hex_, gaze_seat, gaze))
    return result


# --------------------------------------------------------------------------- shots

SHOT_DESCRIPTIONS = {
    'windshield-front': 'outside the car over the hood, looking in through the windshield at the front row',
    'windshield-driver': 'outside, through the windshield, a single on the driver',
    'windshield-passenger': 'outside, through the windshield, a single on the front passenger',
    'rear-center-forward': 'behind the rear seats at head height, looking forward over the occupants toward the windshield',
    'front-center-back': 'between the two front seats at head height, looking back at the rear seat',
    'mirror-back': 'at the rear-view mirror under the roof, looking back over the whole cabin',
    'rear-window': 'outside behind the car, looking in through the rear window',
}
_SHOT_RE = re.compile(r'^(?:(pov|ots):(?P<a>[a-z-]+)>(?P<b>[a-z-]+)|side-(?P<side>[a-z-]+)|'
                      r'dash-(?P<dash>driver|front-passenger)|lap-(?P<lap>[a-z-]+))$')


def describe_shot(shot: str, side: str = 'lhd') -> str:
    if shot in SHOT_DESCRIPTIONS:
        return SHOT_DESCRIPTIONS[shot]
    m = _SHOT_RE.match(shot)
    if not m:
        return shot
    if m['a']:
        a, b = seat_label(m['a'], side), seat_label(m['b'], side)
        return (f'point of view from the {a}, looking at the {b}' if m[1] == 'pov'
                else f'over the shoulder of the occupant of the {a}, looking at the {b}')
    if m['side']:
        return f"outside the car at the {seat_label(m['side'], side)} window, looking in at that occupant in profile"
    if m['dash']:
        return f"dashboard-mounted camera facing the {seat_label(m['dash'], side)}"
    return f"top-down insert onto the lap of the {seat_label(m['lap'], side)}"


def shot_subject_seat(shot: str) -> str | None:
    m = _SHOT_RE.match(shot)
    if not m:
        return {'windshield-driver': 'driver', 'windshield-passenger': 'front-passenger'}.get(shot)
    return m['b'] or m['side'] or m['dash'] or m['lap']


def valid_shot(shot: str | None, body: Body, side: str = 'lhd') -> bool:
    if not shot:
        return False
    if shot in SHOT_DESCRIPTIONS:
        return True
    m = _SHOT_RE.match(shot)
    if not m:
        return False
    seats = [s for s in (m['a'], m['b'], m['side'], m['dash'], m['lap']) if s]
    if not all(s in SEATS for s in seats) or (m['side'] and m['side'] not in SIDE_SEATS) or (m['a'] and m['a'] == m['b']):
        return False
    return body.third_y is not None or not any(s.startswith('third') for s in seats)


def _primary_seat(panel: dict, occ: list[Occupant]) -> str | None:
    target = ((panel.get('drama_requirements') or {}).get('focus_priority') or {})
    target = target.get('primary_target', '') if isinstance(target, dict) else str(target)
    actors = {a.get('visual_ref') or a.get('name'): a for a in panel.get('state', {}).get('actors', [])}
    for o in occ:
        if target and _matches(target, actors.get(o.name, {'name': o.name})):
            return o.seat
    refs = {_norm(r) for r in panel.get('references', [])}
    candidates = ([o for o in occ if actors.get(o.name, {}).get('in_frame')]
                  or [o for o in occ if _norm(o.name) in refs] or occ)
    return candidates[0].seat if candidates else None


def choose_shot(panel: dict, occ: list[Occupant], body: Body, side: str = 'lhd') -> tuple[str, str]:
    """(shot id, reason): vehicle_shot, else camera_position keywords, else who is in frame."""
    explicit = panel.get('vehicle_shot')
    if valid_shot(explicit, body, side):
        return explicit, 'vehicle_shot'
    seats = {o.seat: o for o in occ}
    actors = {a.get('visual_ref') or a.get('name'): a for a in panel.get('state', {}).get('actors', [])}
    framed = [o for o in occ if actors.get(o.name, {}).get('in_frame')]
    subject = _primary_seat(panel, occ)
    cam = (panel.get('camera_position') or '').lower()

    def front(seat):
        return seat in ('driver', 'front-passenger')

    if cam:
        if re.search(r'\b(directly over|overhead|top[- ]down|bird)', cam) and subject:
            return f'lap-{subject}', 'camera_position: overhead'
        if 'mirror' in cam:
            return 'mirror-back', 'camera_position: mirror'
        if 'rear window' in cam or 'back window' in cam:
            return 'rear-window', 'camera_position: rear window'
        if 'windshield' in cam or 'hood' in cam:
            if subject and len(framed) <= 1 and front(subject):
                return ('windshield-driver' if subject == 'driver' else 'windshield-passenger'), 'camera_position: windshield'
            return 'windshield-front', 'camera_position: windshield'
        if re.search(r'\bdash(board)?\b', cam) and subject in ('driver', 'front-passenger'):
            return f'dash-{subject}', 'camera_position: dashboard'
        if re.search(r'between[- ]the[- ]front[- ]seats|between[- ]front[- ]seats|center console|centre console', cam):
            return 'front-center-back', 'camera_position: between front seats'
        if re.search(r'\b(outside|exterior)\b', cam) and subject in SIDE_SEATS and len(framed) <= 1:
            return f'side-{subject}', 'camera_position: outside window'
        owner_text = cam.split('pov')[0] if 'pov' in cam else ''
        pov_actor = next((o for o in occ if owner_text and _matches(owner_text, actors.get(o.name, {'name': o.name}))), None)
        cam_seat = pov_actor.seat if pov_actor else infer_seat(cam, side)
        if cam_seat and subject and cam_seat != subject:
            mode = 'pov' if 'pov' in cam or cam_seat not in seats else 'ots'
            return f'{mode}:{cam_seat}>{subject}', 'camera_position: seat'

    if subject is None:
        return 'mirror-back', 'no seated occupants'
    if len(framed) >= 2:
        rows = {front(o.seat) for o in framed}
        if rows == {False}:
            return 'front-center-back', 'two-shot in the rear row'
        if rows == {True}:
            return 'windshield-front', 'two-shot in the front row'
        return 'mirror-back', 'front and rear occupants in frame'
    gaze = seats[subject].gaze_seat if subject in seats else None
    if gaze:
        return f'ots:{gaze}>{subject}', 'single, looking at another occupant'
    if front(subject):
        return ('windshield-driver' if subject == 'driver' else 'windshield-passenger'), 'single in the front row'
    return 'front-center-back', 'single in the rear row'


# --------------------------------------------------------------------------- camera

def build_camera(shot: str, body: Body, side: str, scale: str, aspect: tuple[int, int],
                 subject: str | None = None, group: bool = False) -> Camera:
    """Tight scales re-aim at the subject and narrow the lens; a group MS keeps the mount's framing."""
    head = lambda s: head_point(s, body, side)  # noqa: E731
    front_z = body.cushion_z + HEAD_ABOVE_CUSHION
    rear_wall = body.rear_wall_y
    hw = body.half_width
    hidden = None
    m = _SHOT_RE.match(shot)
    subject = shot_subject_seat(shot) or subject

    if shot == 'windshield-front':
        pos, tgt, fov = (0.0, body.dash_y + 1.15, front_z + 0.1), (0.0, -0.25, front_z - 0.12), 46
    elif shot in ('windshield-driver', 'windshield-passenger'):
        hx, hy, hz = head(subject)
        pos, tgt, fov = (-hx * 0.4, body.dash_y + 1.05, hz + 0.04), (hx, hy, hz - 0.02), 42
    elif shot == 'rear-center-forward':
        pos, tgt, fov = (0.22, (body.third_y or body.rear_y) - 0.5, front_z + 0.12), (0.0, body.dash_y + 0.6, front_z - 0.15), 60
    elif shot == 'front-center-back':
        pos, tgt, fov = (0.0, -0.05, front_z), (0.0, body.rear_y - 0.6, front_z - 0.08), 48
    elif shot == 'mirror-back':
        pos, tgt, fov = (0.0, body.dash_y + 0.05, body.roof_z - 0.1), (0.0, body.rear_y - 0.35, front_z - 0.12), 64
    elif shot == 'rear-window':
        pos, tgt, fov = (0.0, rear_wall - body.trunk_len - 0.8, front_z + 0.12), (0.0, 0.0, front_z - 0.05), 50
    elif m and m['side']:
        hx, hy, hz = head(subject)
        sign = 1 if hx > 0 else -1
        pos, tgt, fov = (sign * (hw + 1.0), hy + 0.05, hz), (hx, hy, hz - 0.03), 46
    elif m and m['dash']:
        hx, hy, hz = head(subject)
        pos, tgt, fov = (hx * 0.15, body.dash_y - 0.04, hz - 0.06), (hx, hy, hz), 52
    elif m and m['lap']:
        x, y = seat_xy(subject, body, side)
        pos, tgt, fov = (x, y + 0.12, body.cushion_z + 0.78), (x, y + 0.32, body.cushion_z + 0.05), 50
    elif m and m['a']:
        ax, ay, az = head(m['a'])
        bx, by, bz = head(m['b'])
        if by < ay - 0.3:  # turned around: look past the inner edge of the own headrest
            ax = math.copysign(min(abs(ax), 0.1), ax) if ax else 0.0
            ay -= 0.12
        if m[1] == 'pov':
            pos, hidden = (ax, ay + 0.06, az), m['a']
        else:
            dx, dy = ax - bx, ay - by
            n = math.hypot(dx, dy) or 1.0
            ux, uy = dx / n, dy / n
            px, py = -uy, ux
            centre = (0.0, (0.0 + body.rear_y) / 2)
            if px * (centre[0] - ax) + py * (centre[1] - ay) < 0:
                px, py = -px, -py
            # behind the owner, then sideways toward the cabin centre so the owner keeps to a frame edge
            pos = (max(-hw + 0.08, min(hw - 0.08, ax + ux * 0.15 + px * 0.22)),
                   ay + uy * 0.15 + py * 0.22, min(az + 0.05, body.roof_z - 0.06))
        tgt, fov = (bx, by, bz - 0.02), 50
    else:
        raise ValueError(f'unknown shot: {shot}')

    if scale != 'WS' and subject and not (m and m['lap']) and not (group and scale == 'MS'):
        hx, hy, hz = head(subject)
        tgt = (hx, hy, hz - (0.2 if scale == 'MS' else 0.0))  # MS frames to the chest
        if hidden == subject:
            hidden = None
        hfov, vfov = tight_fov(fov, aspect, scale, math.dist(pos, tgt))
    else:
        hfov, vfov = frame_fovs(fov, aspect, 'h')
    return Camera(tuple(pos), tuple(tgt), hfov, vfov, hidden)


def head_yaw(o: Occupant, body: Body, side: str) -> tuple[float, float]:
    """(yaw, pitch) in degrees; yaw 0 = toward the hood, +90 = toward the vehicle's left (−x)."""
    hx, hy, hz = head_point(o.seat, body, side)
    if o.gaze_seat:
        tx, ty, _ = head_point(o.gaze_seat, body, side)
        return math.degrees(math.atan2(-(tx - hx), ty - hy)), 0.0
    if o.gaze == 'window':
        return (90.0 if hx < 0 else -90.0), 0.0
    return 0.0, (-35.0 if o.gaze == 'down' else 0.0)


def _facing(cam: Camera, o: Occupant, body: Body, side: str) -> str:
    yaw = math.radians(head_yaw(o, body, side)[0])
    return facing(cam, head_point(o.seat, body, side), (-math.sin(yaw), math.cos(yaw)))


def _placement(cam: Camera, o: Occupant, body: Body, side: str) -> tuple[str, bool, bool]:
    if cam.hidden_seat == o.seat:
        return 'the camera IS this person (POV) — not visible', False, False
    hx, hy, hz = head_point(o.seat, body, side)
    return placement(cam, (hx, hy, hz), (hx, hy + 0.05, body.cushion_z + 0.3))


def _inside_cabin(cam: Camera, body: Body) -> bool:
    x, y, z = cam.position
    return abs(x) < body.half_width + 0.02 and body.rear_wall_y < y < body.dash_y + 0.25 and z < body.roof_z


def _door(cam: Camera, o: Occupant, body: Body, side: str) -> str:
    x, y = seat_xy(o.seat, body, side)
    if not x:
        return ''
    if abs(cam.position[0]) > body.half_width and cam.position[0] * x > 0:
        return 'their door window frames them in the foreground'
    side_of = lateral(cam, (math.copysign(body.half_width, x), y, body.belt_z + 0.2))
    return f'their own door and window on {side_of}' if side_of else 'their own door is behind the camera'


def _background(cam: Camera, body: Body) -> str:
    f, _, _ = basis(cam)
    y = cam.position[1]
    if f[2] < -0.7:
        return 'Background: seat cushion, lap and footwell (top-down).'
    if not _inside_cabin(cam, body):
        if y > body.dash_y:
            return ('Camera outside, in front of the car: hood edge, windshield frame and A-pillars in the '
                    'foreground; the cabin and rear seats behind the occupants.')
        if y < body.rear_wall_y:
            return ('Camera outside, behind the car: rear-glass frame in the foreground; headrests and the '
                    'occupants, then the windshield with the road ahead.')
        return 'Camera outside at a side window: door and window frame in the foreground; the far-side windows behind the occupants.'
    if f[1] < -0.5:
        return ('Background: the seat rows behind and the rear window / tailgate glass, with the road receding; '
                'the windshield and dashboard are behind the camera and NOT visible.')
    if f[1] > 0.5:
        return 'Background: the dashboard and the windshield, with the road ahead.'
    return f"Background: the vehicle's {'right' if f[0] > 0 else 'left'}-side doors and windows."


@dataclass(frozen=True)
class Blocking:
    vehicle: str
    body_key: str
    side: str
    shot: str
    reason: str
    camera: Camera
    occupants: tuple[Occupant, ...]
    aspect: tuple[int, int]

    @property
    def body(self) -> Body:
        return BODIES[self.body_key]


def panel_blocking(panel: dict, scene: dict | None, lookup, aspect: str = '9:16') -> Blocking | None:
    """`lookup(name) -> ref JSON | None`."""
    base = vehicle_base(panel, scene)
    if not base:
        return None
    infos = [i for i in (lookup(f'{base}{s}') for s in ('-Exterior', *INTERIOR_SUFFIXES)) if i]
    body_key = resolve_body(infos)
    body = BODIES[body_key]
    side = drive_side(next((i for i in infos if i.get('drive_side')), None))
    occ = occupants(panel, side, body)
    seated = {o.name for o in occ}
    in_frame = [a for a in panel.get('state', {}).get('actors', []) if a.get('in_frame')]
    def outside(a):
        return a.get('vehicle_position') == 'outside' or bool(_OUTSIDE.search((a.get('position') or '').lower()))

    # someone in frame half in the car (leaning out of a door, at the rear glass) breaks seat geometry
    if not seated & {a.get('visual_ref') or a.get('name') for a in in_frame} or any(
            (a.get('visual_ref') or a.get('name')) not in seated and not outside(a) for a in in_frame):
        return None
    shot, reason = choose_shot(panel, occ, body, side)
    ratio = parse_aspect(aspect)
    cam = build_camera(shot, body, side, scale_of(panel), ratio, _primary_seat(panel, occ), group=len(in_frame) >= 2)
    return Blocking(base, body_key, side, shot, reason, cam, tuple(occ), ratio)


def blocking_block(b: Blocking, with_sketch: bool = False) -> str:
    body = b.body
    wheel = 'left' if b.side == 'lhd' else 'right'
    rows = 2 if body.third_y is None else 3
    lines = [
        'VEHICLE BLOCKING — AUTHORITATIVE (computed from 3D seat geometry; it overrides any lens, '
        'camera position, frame-left/right, seat or visibility wording elsewhere in this prompt):',
        f'Vehicle: {b.vehicle}, {body.label}, {rows} seat rows, steering wheel on the vehicle\'s {wheel} side.',
        f'Shot: {b.shot} — camera {describe_shot(b.shot, b.side)}; lens ≈ {equivalent_focal_mm(b.camera)} mm full-frame equivalent.',
        _background(b.camera, body),
    ]
    for o in b.occupants:
        place, visible, head = _placement(b.camera, o, body, b.side)
        details = [_facing(b.camera, o, body, b.side)] if head else []
        tail = ''.join(f'; {d}' for d in [*details, _door(b.camera, o, body, b.side)] if d) if visible \
            else ' — do not draw this person'
        sketch = f' [{o.color} mannequin]' if with_sketch and visible else ''
        lines.append(f'- {o.name}{sketch} — {seat_label(o.seat, b.side)}: {place}{tail}.')
    f, r, _ = basis(b.camera)
    if abs(f[1]) > 0.5:
        left_on = 'frame-right' if r[0] < 0 else 'frame-left'
        lines.append(f"The vehicle's left side appears on {left_on} in this shot "
                     f"(camera faces the {'hood' if f[1] > 0 else 'rear'}).")
    lines.append(f'Physical rules: exactly {rows} seat rows; one person per seat, seated upright and belted-in posture '
                 'unless the action says otherwise; heads below the roof liner; only the listed people are in the car.')
    if with_sketch:
        lines.append('IMAGE 1 is a 3D blocking sketch of this exact camera: copy its camera position, lens, perspective, '
                     'seat layout, pillars and window openings, and each coloured mannequin\'s place, size and head '
                     'direction. It carries NO materials, colours, clothing or faces — mannequins become the referenced '
                     'characters; grey cabin shapes take the vehicle reference\'s materials; empty window openings are '
                     'tinted glass with the scene\'s exterior behind them.')
    return '\n'.join(lines)


def sketch_spec(b: Blocking, max_px: int = 1024) -> dict:
    body = b.body
    w, h = b.aspect
    scale = max_px / max(w, h)
    return {
        'body': {k: getattr(body, k) for k in Body.__dataclass_fields__ if k != 'label'},
        'drive_side': b.side,
        'seats': {s: [*seat_xy(s, body, b.side)] for s in SEATS
                  if body.third_y is not None or not s.startswith('third')},
        'occupants': [{
            'name': o.name, 'seat': o.seat, 'color': srgb_hex_to_linear(o.color_hex),
            'hip': [*seat_xy(o.seat, body, b.side)],
            'head': [*head_point(o.seat, body, b.side)],
            'yaw_pitch': [*head_yaw(o, body, b.side)],
            'hidden': b.camera.hidden_seat == o.seat,
        } for o in b.occupants],
        'camera': {'position': list(b.camera.position), 'target': list(b.camera.target),
                   'hfov': b.camera.hfov},
        'width_px': max(1, round(w * scale)), 'height_px': max(1, round(h * scale)),
    }
