"""Actor positions in a location's anchor frame (x: image-left→right of the entrance/primary view,
y: entrance→far), from a Pass 1B placement or, for legacy panels, the position text.

The LLM names an anchor and a relation; code computes the metres.
"""
import math
import re
from dataclasses import dataclass

from lib.studio.ledger import area_of
from lib.studio.room_models import FLOOR_STANDING, classify_object
from lib.studio.vehicle_geometry import SEATS

RELATIONS = ('at', 'on', 'in-front-of', 'behind', 'left-of', 'right-of', 'beside')
POSTURES = ('standing', 'seated', 'lying', 'kneeling', 'crouching')
HEAD_Z = {'standing': 1.6, 'seated': 1.2, 'kneeling': 1.0, 'crouching': 0.9, 'lying': 0.35}
_SITTABLE = {'chair', 'sofa', 'bed'}
_GAP_M = 0.35        # standing clearance from furniture
_PERSONAL_M = 0.45   # minimum distance between two people
_MARGIN_M = 0.25     # distance kept from the location bounds
_STOP = {'the', 'a', 'an', 'of', 'on', 'at', 'in', 'to', 'by', 'near', 'and', 'with', 'his', 'her', 'its', 'their'}
_RELATION_TEXT = (
    ('in-front-of', r'\bin front of\b'), ('behind', r'\bbehind\b'),
    ('left-of', r'\b(?:to the )?(?:image-)?left(?: side)? of\b'), ('right-of', r'\b(?:to the )?(?:image-)?right(?: side)? of\b'),
    ('beside', r'\b(?:beside|next to|alongside)\b'), ('on', r'\b(?:on|in|onto) the\b'),
)
# 'in a stationary taxi … at the [street-curb]': inside a vehicle, not standing at the anchor
IN_VEHICLE = re.compile(r'\b(?:in|inside|into)\s+(?:an?\s+|the\s+|his\s+|her\s+|their\s+)?(?:\w+\s+){0,2}'
                         r'(?:taxi|cab|car|suv|van|truck|limo(?:usine)?|bus|sedan|vehicle)\b', re.I)
_POSTURE_TEXT = (('lying', r'\b(?:lying|lies|lie down|in bed|sprawled)\b'), ('seated', r'\b(?:seated|sitting|sits|sat)\b'),
                 ('kneeling', r'\bkneel'), ('crouching', r'\b(?:crouch|squat)'))


@dataclass(frozen=True)
class Pose:
    x: float            # normalized, anchor frame
    y: float
    facing_deg: float   # anchor convention: 0 = toward the entrance (y=0), 90 = toward image-right (x=1)
    posture: str
    anchor: str | None
    source: str         # placement | text | None when guessed

    def metres(self, room_m) -> tuple[float, float]:
        return self.x * room_m[0], self.y * room_m[1]

    def as_dict(self, room_m) -> dict:
        xm, ym = self.metres(room_m)
        return {'x': round(self.x, 3), 'y': round(self.y, 3), 'x_m': round(xm, 2), 'y_m': round(ym, 2),
                'facing_deg': round(self.facing_deg), 'posture': self.posture, 'anchor': self.anchor, 'source': self.source}


def location_anchors(location_ref: str, lookup) -> dict | None:
    """anchor_points shared by every view of the location (rooms: entrance view, outdoor: primary view)."""
    base = area_of(location_ref)
    for suffix in ('-View-From-Entrance', '-View-Primary'):
        info = lookup(f'{base}{suffix}') or {}
        anchors = info.get('anchor_points')
        if anchors and _room_m(anchors):
            return anchors
    return None


def _room_m(anchors: dict):
    room = anchors.get('room_m')
    return room if isinstance(room, (list, tuple)) and len(room) == 2 and min(room) > 0 else None


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r'[^a-z0-9]+', (text or '').lower()) if t and t not in _STOP}


def match_anchor(text: str, anchors: dict, strict: bool = False) -> dict | None:
    """Exact id, else the anchor whose id words best cover the text ('chair on street side of key table')."""
    items = [*anchors.get('objects', []), *anchors.get('zones', [])]
    key = re.sub(r'[^a-z0-9]+', '-', (text or '').lower()).strip('-')
    exact = next((i for i in items if i.get('id') == key), None)
    if exact:
        return exact
    words = _tokens(text)
    best, best_score = None, 0.75 if strict else 0.6
    for item in items:
        target = _tokens(item.get('id', '')) or _tokens(item.get('label', ''))
        score = len(words & target) / len(target) if target else 0
        if score > best_score or (best and score == best_score and len(target) > len(_tokens(best.get('id', '')))):
            best, best_score = item, score
    return best


def _posture(text: str) -> str:
    return next((p for p, pattern in _POSTURE_TEXT if re.search(pattern, text, re.I)), 'standing')


def _relation(text: str, anchor_start: int) -> str:
    """The relation word closest before the anchor mention."""
    head = text[:anchor_start].lower() if anchor_start >= 0 else text.lower()
    hits = [(m.end(), rel) for rel, pattern in _RELATION_TEXT for m in re.finditer(pattern, head)]
    return max(hits)[1] if hits else 'at'


def legacy_placement(actor: dict, anchors: dict, others: list[str]) -> dict | None:
    """Placement parsed from the position text: '[anchor]' mentions, then actor-relative phrases."""
    text = actor.get('position') or ''
    posture = _posture(f"{text} {actor.get('pose', '')}")
    found = [(m, item) for m in re.finditer(r'\[([^\]]+)\]', text) if (item := match_anchor(m[1], anchors))]
    if posture in ('seated', 'lying'):  # 'seated at the [table], in the [chair]' sits on the chair
        found.sort(key=lambda hit: classify_object(hit[1]) not in _SITTABLE)
    if found:
        m, item = found[0]
        return {'anchor': item['id'], 'relation': _relation(text, m.start()), 'target': '', 'posture': posture}
    for name in others:
        found = re.search(re.escape(name.split('-')[-1]) if '-' in name else re.escape(name), text, re.I)
        if found:
            return {'anchor': '', 'relation': _relation(text, found.start()), 'target': name, 'posture': posture}
    item = match_anchor(text, anchors, strict=True)
    if item:
        return {'anchor': item['id'], 'relation': _relation(text, -1), 'target': '', 'posture': posture}
    return None


def _unit(vx: float, vy: float) -> tuple[float, float]:
    n = math.hypot(vx, vy) or 1.0
    return vx / n, vy / n


def _footprint(obj: dict, room_m) -> tuple[float, float]:
    return max(0.0, float(obj.get('width_x') or 0)) * room_m[0], max(0.0, float(obj.get('depth_y') or 0)) * room_m[1]


def _facing_vec(obj: dict, toward_centre: tuple[float, float]) -> tuple[float, float]:
    deg = obj.get('facing_degrees_y')
    if isinstance(deg, (int, float)) and deg >= 0:
        rad = math.radians(deg)
        return math.sin(rad), -math.cos(rad)
    return toward_centre


def _offset(relation: str, base: tuple[float, float], extent: tuple[float, float], front: tuple[float, float],
            centre: tuple[float, float], distance: float | None) -> tuple[float, float]:
    """Point at `relation` of a base with half-extents (along x, along y)."""
    bx, by = base
    if relation in ('left-of', 'right-of', 'beside'):
        sign = -1 if relation == 'left-of' else 1 if relation == 'right-of' else (1 if centre[0] >= bx else -1)
        return bx + sign * (extent[0] + (distance or 0.5)), by
    if relation in ('in-front-of', 'behind'):
        fx, fy = front if relation == 'in-front-of' else (-front[0], -front[1])
        reach = abs(fx) * extent[0] + abs(fy) * extent[1]
        return bx + fx * (reach + (distance or 0.6)), by + fy * (reach + (distance or 0.6))
    cx, cy = _unit(centre[0] - bx, centre[1] - by)  # 'at': the side facing the open floor
    reach = abs(cx) * extent[0] + abs(cy) * extent[1]
    return bx + cx * (reach + (distance or _GAP_M)), by + cy * (reach + (distance or _GAP_M))


def _place(p: dict, anchors: dict, room_m, placed: dict[str, tuple[float, float, tuple]]) -> tuple | None:
    """(x_m, y_m, anchor id, facing vector, sits on the anchor); None when its anchor/target is unknown."""
    w, d = room_m
    centre = (w / 2, d / 2)
    relation = p.get('relation') if p.get('relation') in RELATIONS else 'at'
    distance = p.get('distance_m') if isinstance(p.get('distance_m'), (int, float)) and p['distance_m'] > 0 else None
    target = placed.get(p.get('target') or '')
    if target:
        tx, ty, _, tface, _ = target
        point = _offset(relation, (tx, ty), (0.2, 0.2), tface, centre, distance)
        return (*point, None, _unit(tx - point[0], ty - point[1]), False)
    item = match_anchor(p.get('anchor', ''), anchors)
    if not item:
        return None
    base = (float(item.get('x', 0.5)) * w, float(item.get('y', 0.5)) * d)
    to_centre = _unit(centre[0] - base[0], centre[1] - base[1])
    fw, fd = _footprint(item, room_m)
    sit = classify_object(item) in _SITTABLE and (relation in ('on', 'at', 'left-of', 'right-of')
                                                  and p.get('posture') in ('seated', 'lying') or relation == 'on')
    if sit:  # left/right on a sofa or bed: that half of it
        shift = {'left-of': -fw / 4, 'right-of': fw / 4}.get(relation, 0.0)
        return (base[0] + shift, base[1], item['id'], _facing_vec(item, to_centre), True)
    point = _offset(relation, base, (fw / 2, fd / 2), _facing_vec(item, to_centre), centre, distance)
    return (*point, item['id'], _unit(base[0] - point[0], base[1] - point[1]), False)


def _settle(points: dict[str, list], anchors: dict, room_m, seated_on: dict[str, str]) -> None:
    """Keep people inside the bounds, out of floor-standing furniture, and apart."""
    w, d = room_m
    blocks = []
    for obj in anchors.get('objects', []):
        fw, fd = _footprint(obj, room_m)
        if classify_object(obj) in FLOOR_STANDING and fw > 0.1 and fd > 0.1:
            blocks.append((obj.get('id'), float(obj.get('x', 0)) * w, float(obj.get('y', 0)) * d, fw / 2, fd / 2))
    for name, pt in points.items():
        for oid, ox, oy, hx, hy in blocks:
            if oid == seated_on.get(name) or abs(pt[0] - ox) >= hx or abs(pt[1] - oy) >= hy:
                continue
            gaps = [(hx - (pt[0] - ox), (1, 0)), (hx + (pt[0] - ox), (-1, 0)), (hy - (pt[1] - oy), (0, 1)), (hy + (pt[1] - oy), (0, -1))]
            gap, (dx, dy) = min(gaps)
            pt[0] += dx * (gap + 0.3)
            pt[1] += dy * (gap + 0.3)
        pt[0] = min(w - _MARGIN_M, max(_MARGIN_M, pt[0]))
        pt[1] = min(d - _MARGIN_M, max(_MARGIN_M, pt[1]))
    names = list(points)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pa, pb = points[a], points[b]
            dist = math.hypot(pb[0] - pa[0], pb[1] - pa[1])
            if dist < _PERSONAL_M:
                ux, uy = _unit(pb[0] - pa[0], pb[1] - pa[1]) if dist > 1e-6 else (1.0, 0.0)
                pb[0] = min(w - _MARGIN_M, max(_MARGIN_M, pb[0] + ux * (_PERSONAL_M - dist)))
                pb[1] = min(d - _MARGIN_M, max(_MARGIN_M, pb[1] + uy * (_PERSONAL_M - dist)))


def _named(name: str, text: str) -> bool:
    """'Frelaine' or 'Stanton' names Stanton Frelaine; 'Kidnapper' names The-Kidnapper."""
    return any(re.search(rf'\b{re.escape(t)}\b', text) for t in re.split(r'[- ]+', name.lower()) if len(t) > 2 and t != 'the')


def _deg(vx: float, vy: float) -> float:
    return math.degrees(math.atan2(vx, -vy)) % 360


def resolve(panel: dict, anchors: dict) -> dict[str, Pose]:
    """Character name → pose for every actor whose placement resolves; others are left out, not guessed."""
    room_m = _room_m(anchors)
    if not room_m:
        return {}
    actors = panel.get('state', {}).get('actors', [])
    names = [a.get('name', '') for a in actors]
    todo = []
    for a in actors:
        if a.get('vehicle_position') in SEATS or (not a.get('placement') and IN_VEHICLE.search(a.get('position') or '')):
            continue  # inside a vehicle: car blocking owns them, the room has no place for them
        p = a.get('placement') or legacy_placement(a, anchors, [n for n in names if n != a.get('name')])
        if p:
            todo.append((a, p, 'placement' if a.get('placement') else 'text'))
    todo.sort(key=lambda item: bool(item[1].get('target')))  # people placed relative to others go last
    placed: dict[str, tuple] = {}
    for a, p, _ in todo:
        got = _place(p, anchors, room_m, placed)
        if got:
            placed[a['name']] = got
    points = {n: [v[0], v[1]] for n, v in placed.items()}
    _settle(points, anchors, room_m, {n: v[2] for n, v in placed.items() if v[4]})
    poses = {}
    for a, p, source in todo:
        name = a['name']
        if name not in placed:
            continue
        x, y = points[name]
        face = placed[name][3]
        looks_at = (a.get('gaze_target') or a.get('position') or '').lower()
        gaze = next((points[n] for n in points if n != name and _named(n, looks_at)), None)
        if gaze:
            face = _unit(gaze[0] - x, gaze[1] - y)
        posture = p.get('posture') if p.get('posture') in POSTURES else 'standing'
        poses[name] = Pose(x / room_m[0], y / room_m[1], _deg(*face), posture, placed[name][2], source)
    return poses


def coverage(scenes: list[dict], lookup) -> dict:
    """In-frame actors placed, by source, over panels whose location has anchors."""
    stats = {'panels': 0, 'in_frame': 0, 'placed': 0, 'placement': 0, 'text': 0, 'unresolved': []}
    for scene in scenes:
        for panel in scene.get('panels', []):
            anchors = location_anchors((panel.get('location_references') or [scene.get('location', '')])[0], lookup)
            if not anchors:
                continue
            stats['panels'] += 1
            poses = resolve(panel, anchors)
            for a in panel.get('state', {}).get('actors', []):
                if not a.get('in_frame'):
                    continue
                stats['in_frame'] += 1
                pose = poses.get(a.get('name'))
                if pose:
                    stats['placed'] += 1
                    stats[pose.source] += 1
                else:
                    stats['unresolved'].append((scene.get('scene_id'), panel.get('panel_index'), a.get('name'),
                                                (a.get('position') or '')[:80]))
    return stats
