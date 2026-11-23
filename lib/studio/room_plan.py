"""Floor plan first: anchors written from the description before any image exists, checked in code.

The plan becomes the View-From-Entrance anchors; its sketch then guides the VFE render and QA,
so the image follows the layout instead of the layout being read back from the image.
"""
import json
import logging
import math
import textwrap
from collections import deque
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont

from lib.core.utils import atomic_write, safe_name
from lib.studio.room_models import CATEGORY_HEX, ZERO_FOOTPRINT, is_spot

logger = logging.getLogger(__name__)

VFE = 'View-From-Entrance'
BODY_M = 0.2          # half a person's width: aisles narrower than 0.4 m are walls
WALL_TOL_M = 0.2      # doors and windows within this of a wall are on it
OVERLAP_M = 0.05      # interpenetration both ways beyond this is a clash
AISLE_M = 0.6  # floor a person stands in: behind a counter, beside a table
REACH_M = 0.4         # a spot counts as reached from a free cell this close
CELL_M = 0.1
UNSIZED = ('patch', 'panel', 'artwork')  # surfaces and wall decor take their size from the room
NOT_OBSTACLES = {'door', 'window', 'patch', 'panel', 'artwork'}
NESTS = {frozenset({'chair', 'table'}), frozenset({'chair', 'counter'})}  # chairs tuck under tables, stools under bar tops

PLAN_RULES = (
    "\nPLAN MODE — no image of this room exists yet: this layout is the source of truth every view is rendered "
    "from.\n"
    "- Take every size and distance in metres literally: x = metres from the image-left wall / room width, "
    "y = metres from the entrance wall / room depth. Use the stated ROOM SIZE for room_m and room_height_m.\n"
    "- Every NAMED POSITION below appears exactly once with its id verbatim: furniture, fixtures and openings as "
    "objects, standing spots and open floor as zones.\n"
    "- Every piece of furniture gets its real footprint (width_x, depth_y) and height_m; no zero footprints.\n"
    "- Every door gets hinge_side, opens (its mechanism; none for an open doorway) and leaf_state, as described.\n"
    "- Doors and windows sit on a wall (x or y at 0 or 1). Keep the swing of every inward door free of furniture. Keep a walkable path at least 0.6 m wide from the "
    "entrance door to every zone and every other door.\n"
    "- If the description puts two objects in the same floor space, shorten or shift the less important one and "
    "say so in its notes.\n"
)


def _num(v) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


def _footprint(o: dict) -> tuple[float, float, float, float]:
    (cx, cy, _), (sx, sy, _) = o['center_m'], o['size_m']
    a = math.radians(o.get('yaw_degrees') or 0)
    hx = (abs(sx * math.cos(a)) + abs(sy * math.sin(a))) / 2
    hy = (abs(sx * math.sin(a)) + abs(sy * math.cos(a))) / 2
    return cx - hx, cy - hy, cx + hx, cy + hy


TURN = {'ajar': 30.0, 'open': 90.0, 'folded': 172.0}


def _leaves(o: dict, unknown: str = 'inward') -> list[tuple[tuple, tuple, tuple, float, bool]]:
    """Hinged leaves of a door: (hinge point, toward free end, into the room, width, swings outward)."""
    opens = o.get('opens') or unknown
    if opens not in ('inward', 'outward', 'double-inward', 'double-outward', 'bifold'):
        return []
    (cx, cy, _), (sx, sy, _) = o['center_m'], o['size_m']
    n = tuple(o.get('inward') or ((0, 1) if sx >= sy else (1, 0)))
    u = (1.0, 0.0) if n[1] else (0.0, 1.0)
    run = sx if n[1] else sy
    hs = o.get('hinge_sign') or -1
    out = opens.endswith('outward')
    if opens.startswith('double'):
        return [((cx + e * run / 2 * u[0], cy + e * run / 2 * u[1]), (-e * u[0], -e * u[1]), n, run / 2, out)
                for e in (-1, 1)]
    return [((cx + hs * run / 2 * u[0], cy + hs * run / 2 * u[1]), (-hs * u[0], -hs * u[1]), n,
             run / (2 if opens == 'bifold' else 1), out)]


def _in_swing(box, hinge, free, inward, radius) -> bool:
    x0, y0, x1, y1 = box
    steps = [i / 10 for i in range(11)]
    for fx in steps:
        for fy in steps:
            dx, dy = x0 + (x1 - x0) * fx - hinge[0], y0 + (y1 - y0) * fy - hinge[1]
            if dx * free[0] + dy * free[1] > 0.02 and dx * inward[0] + dy * inward[1] > 0.02 \
                    and math.hypot(dx, dy) < radius - 0.02:
                return True
    return False


def _obstacles(spec: dict) -> list[dict]:
    return [o for o in spec['objects'] if o['category'] not in NOT_OBSTACLES
            and o['size_m'][2] >= 0.3 and o['center_m'][2] - o['size_m'][2] / 2 < 1.0]


def _inside(obstacles: list[dict], x: float, y: float) -> str:
    return next((f" (inside {o['id']})" for o in obstacles
                 if (b := _footprint(o))[0] <= x <= b[2] and b[1] <= y <= b[3]), '')


def _clearance(obstacles: list[dict], w: float, d: float, x: float, y: float) -> tuple[float, str, str]:
    """Free floor across the narrower axis through (x, y) and the two things bounding it."""
    best = None
    for axis, pos, other, size, walls in ((0, x, y, w, ('left wall', 'right wall')),
                                          (1, y, x, d, ('entrance wall', 'far wall'))):
        lo, hi = (0.0, walls[0]), (size, walls[1])
        for o in obstacles:
            b = _footprint(o)
            if b[1 - axis] <= other <= b[3 - axis]:
                if b[2 + axis] <= pos:
                    lo = max(lo, (b[2 + axis], o['id']))
                elif b[axis] >= pos:
                    hi = min(hi, (b[axis], o['id']))
        if best is None or hi[0] - lo[0] < best[0]:
            best = (hi[0] - lo[0], lo[1], hi[1])
    return best


def _on_wall(x: float, y: float, w: float, d: float) -> tuple[str, float]:
    return min((x, 'left'), (w - x, 'right'), (y, 'entrance'), (d - y, 'far'), key=lambda t: t[0])[::-1]


def _inside_point(x: float, y: float, w: float, d: float) -> tuple[float, float]:
    """The floor spot just inside an opening."""
    wall, _ = _on_wall(x, y, w, d)
    step = BODY_M + CELL_M
    return {'left': (step, y), 'right': (w - step, y), 'entrance': (x, step), 'far': (x, d - step)}[wall]


def _reachable(obstacles: list[dict], w: float, d: float, start: tuple[float, float]) -> set[tuple[int, int]]:
    nx, ny = int(w / CELL_M), int(d / CELL_M)
    boxes = [_footprint(o) for o in obstacles]

    def free(i, j):
        x, y = (i + 0.5) * CELL_M, (j + 0.5) * CELL_M
        return BODY_M - CELL_M / 2 <= x <= w - BODY_M + CELL_M / 2 and BODY_M - CELL_M / 2 <= y <= d - BODY_M + CELL_M / 2 \
            and not any(x0 - BODY_M < x < x1 + BODY_M and y0 - BODY_M < y < y1 + BODY_M for x0, y0, x1, y1 in boxes)

    first = (min(nx - 1, int(start[0] / CELL_M)), min(ny - 1, int(start[1] / CELL_M)))
    if not free(*first):
        return set()
    seen, todo = {first}, deque([first])
    while todo:
        i, j = todo.popleft()
        for c in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
            if c not in seen and 0 <= c[0] < nx and 0 <= c[1] < ny and free(*c):
                seen.add(c)
                todo.append(c)
    return seen


def _near(cells: set, x: float, y: float) -> bool:
    return any(math.hypot((i + 0.5) * CELL_M - x, (j + 0.5) * CELL_M - y) <= REACH_M for i, j in cells)


def placeable(vocabulary: list[dict] | None) -> list[dict]:
    """Named positions a plan must place; a room-wide entry (size, light, the room itself) has no spot."""
    return [p for p in vocabulary or [] if p.get('kind') != 'room-wide']


def validate_plan(anchors: dict, spec: dict, vocabulary: list[dict] | None = None) -> list[str]:
    """Plain-language problems a renderer cannot fix: clashes, blocked spots, openings off walls, missing ids."""
    w, d, _ = spec['room_m']
    issues = []
    ids = {o.get('id') for o in anchors.get('objects', [])} | {z.get('id') for z in anchors.get('zones', [])}
    missing = [p['id'] for p in placeable(vocabulary) if p.get('id') and p['id'] not in ids]
    if missing:
        issues.append(f"named positions missing from objects and zones: {', '.join(missing)}")

    spots = [o.get('id') for o in anchors.get('objects', []) if is_spot(o)]
    if spots:
        issues.append(f"standing spots listed as objects, move them to zones: {', '.join(spots)}")

    category = {o['id']: o['category'] for o in spec['objects']}

    def sizeless(o: dict) -> bool:
        w_, d_, h_ = _num(o.get('width_x')), _num(o.get('depth_y')), _num(o.get('height_m'))
        if category[o['id']] in ('door', 'window'):
            return max(w_, d_) <= 0
        return min(w_, d_, h_) <= 0 or max(w_, d_) < ZERO_FOOTPRINT  # the sketch would draw it at a default size

    unsized = [o.get('id') for o in anchors.get('objects', [])
               if category.get(o.get('id')) not in (None, *UNSIZED) and sizeless(o)]
    if unsized:
        issues.append(f"no real size (width_x, depth_y, height_m): {', '.join(unsized)}")
    for o in anchors.get('objects', []):
        if category.get(o.get('id')) in ('door', 'window'):  # openings straddle their wall; checked below
            continue
        x, y = _num(o.get('x')) * w, _num(o.get('y')) * d
        hx, hy = _num(o.get('width_x')) * w / 2, _num(o.get('depth_y')) * d / 2
        if x - hx < -OVERLAP_M or y - hy < -OVERLAP_M or x + hx > w + OVERLAP_M or y + hy > d + OVERLAP_M:
            issues.append(f"{o.get('id')} extends outside the {w:g} x {d:g} m room "
                          f"(x {x - hx:.2f}–{x + hx:.2f} m, y {y - hy:.2f}–{y + hy:.2f} m)")

    openings = [o for o in spec['objects'] if o['category'] in ('door', 'window')]
    for o in openings:
        wall, gap = _on_wall(*o['center_m'][:2], w, d)
        if gap > WALL_TOL_M:
            issues.append(f"{o['id']} ({o['category']}) stands {gap:.2f} m from the nearest wall ({wall}); "
                          "openings belong in a wall")
        u, length = (o['center_m'][0], w) if wall in ('entrance', 'far') else (o['center_m'][1], d)
        half = max(o['size_m'][:2]) / 2
        if u - half < -OVERLAP_M or u + half > length + OVERLAP_M:
            issues.append(f"{o['id']} ({o['category']}) runs past the corner of the {wall} wall "
                          f"({u - half:.2f}–{u + half:.2f} m along a {length:g} m wall)")

    obstacles = _obstacles(spec)
    for i, a in enumerate(obstacles):
        for b in obstacles[i + 1:]:
            if frozenset({a['category'], b['category']}) in NESTS:
                continue
            ax0, ay0, ax1, ay1 = _footprint(a)
            bx0, by0, bx1, by1 = _footprint(b)
            ox, oy = min(ax1, bx1) - max(ax0, bx0), min(ay1, by1) - max(ay0, by0)
            if ox > OVERLAP_M and oy > OVERLAP_M:
                issues.append(f"{a['id']} and {b['id']} occupy the same floor: {ox:.2f} x {oy:.2f} m around "
                              f"x={(max(ax0, bx0) + ox / 2):.2f} m, y={(max(ay0, by0) + oy / 2):.2f} m")

    for door in openings:
        for hinge, free, inward, width, out in _leaves(door, unknown=''):  # only a stated mechanism is checked
            for o in obstacles if not out else ():
                if _in_swing(_footprint(o), hinge, free, inward, width):
                    issues.append(f"{o['id']} stands in the swing of {door['id']} ({width:.2f} m leaf opening inward)")

    entrances = [o for o in openings if o['category'] == 'door' and _on_wall(*o['center_m'][:2], w, d)[0] == 'entrance']
    if not entrances:
        issues.append("no door on the entrance wall (y=0): the camera of View-From-Entrance stands in it")
        return issues
    entrance = entrances[0]
    cells = _reachable(obstacles, w, d, _inside_point(*entrance['center_m'][:2], w, d))
    if not cells:
        issues.append(f"the floor inside {entrance['id']} is blocked")
        return issues
    zones = [(z.get('id'), _num(z.get('x')) * w, _num(z.get('y')) * d) for z in anchors.get('zones', [])]
    if on_furniture := [t + inside for t, x, y in zones if (inside := _inside(obstacles, x, y))]:
        issues.append(f"zones stand on furniture, move each to the free floor beside it: {', '.join(on_furniture)}")
    zones = [z for z in zones if not _inside(obstacles, *z[1:])]
    targets = zones + [(o['id'], *_inside_point(*o['center_m'][:2], w, d)) for o in openings
                       if o['category'] == 'door' and o is not entrance]
    blocked = [t + _inside(obstacles, x, y) for t, x, y in targets if not _near(cells, x, y)]
    for t, x, y in zones:
        gap, a, b = _clearance(obstacles, w, d, x, y)
        if gap < AISLE_M:
            issues.append(f"{t} has {gap:.2f} m of floor between {a} and {b}; a person needs {AISLE_M:g} m")
    if blocked:
        issues.append(f"no walkable path ({2 * BODY_M:.1f} m wide) from {entrance['id']} to: {', '.join(blocked)}")
    return issues


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def render_plan_png(spec: dict, anchors: dict, path, title: str = '', issues=()) -> None:
    """Top-down plan for people: far wall at the top, image-left on the left, ids as labels, camera wedge."""
    w, d, _ = spec['room_m']
    scale = 800 / max(w, d)
    m, chars = 60, round(w * scale / 7)  # the default font lacks dashes and Cyrillic; long issues wrap
    lines = [line for i in issues for line in textwrap.wrap('! ' + i.replace('–', '-').encode('ascii', 'replace')
                                                             .decode(), chars, subsequent_indent='  ')]
    footer = 22 * (len(lines) + 1)
    img = Image.new('RGB', (round(w * scale) + 2 * m, round(d * scale) + 2 * m + footer), 'white')
    draw = ImageDraw.Draw(img)
    small, big = _font(13), _font(16)

    def px(x, y):
        return m + x * scale, m + (d - y) * scale

    placed = []

    def label(x, y, text, colour, anchor):
        box = draw.textbbox((x, y), text, font=small, anchor=anchor)
        while any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in placed):
            y += 15
            box = draw.textbbox((x, y), text, font=small, anchor=anchor)
        placed.append(box)
        labels.append(((x, y), text, colour, anchor))

    labels = []


    draw.rectangle([*px(0, d), *px(w, 0)], outline='black', width=4)
    for o in sorted(spec['objects'], key=lambda o: o['category'] in NOT_OBSTACLES):
        x0, y0, x1, y1 = _footprint(o)
        (ax, ay), (bx, by) = px(x0, y1), px(x1, y0)
        colour = CATEGORY_HEX.get(o['category'], '#999999')
        if o['category'] == 'door':
            draw.rectangle([ax, ay, bx, by], fill='white', outline=colour, width=3)
            _plan_door(draw, o, px, scale, colour)
        else:
            draw.rectangle([ax, ay, bx, by], fill=colour if o['category'] not in NOT_OBSTACLES else None,
                           outline=colour, width=2)
        label((ax + bx) / 2, (ay + by) / 2, o['id'], 'black', 'mm')
    for z in anchors.get('zones', []):
        cx, cy = px(_num(z.get('x')) * w, _num(z.get('y')) * d)
        draw.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill='#d35400')
        label(cx, cy + 9, z.get('id', ''), '#a04000', 'ma')
    for view in spec['views']:
        (cx, cy), fx, fy = px(*view['position_m'][:2]), *view['forward']
        half = math.radians(view['hfov_degrees'] / 2)
        for s in (-1, 1):
            dx = fx * math.cos(half) - s * fy * math.sin(half)
            dy = fy * math.cos(half) + s * fx * math.sin(half)
            draw.line([cx, cy, cx + dx * 0.25 * d * scale, cy - dy * 0.25 * d * scale], fill='#2c3e50', width=2)
        draw.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill='#2c3e50')
    for xy, text, colour, anchor in labels:  # last, so no shape paints over them
        draw.text(xy, text, fill=colour, font=small, anchor=anchor, stroke_width=2, stroke_fill='white')
    draw.line([m, m - 25, m + scale, m - 25], fill='black', width=3)
    draw.text((m + scale + 8, m - 25), '1 m', fill='black', font=small, anchor='lm')
    draw.text((m + 70 + scale, m - 25), f"{title}  {w:g} x {d:g} m, far wall at top", fill='black', font=big, anchor='lm')
    y = round(d * scale) + 2 * m - 10
    for line in lines or ['OK: plan checks passed']:
        draw.text((m, y), line, fill='#c0392b' if issues else '#1e8449', font=small)
        y += 22
    img.save(path)


def _plan_door(draw, o, px, scale, colour) -> None:
    """Swing arcs and leaves at their state for hinged doors; track, pocket, garage and revolving symbols otherwise."""
    opens, state = o.get('opens') or 'inward', o.get('leaf_state') or 'closed'
    for hinge, free, inward, width, out in _leaves(o):
        n = (-inward[0], -inward[1]) if out else inward
        (hx, hy), r = px(*hinge), width * scale
        a, b = (math.degrees(math.atan2(-v[1], v[0])) for v in (free, n))
        if round((b - a) % 360) != 90:
            a, b = b, a
        draw.arc([hx - r, hy - r, hx + r, hy + r], a, b, fill=colour, width=1)
        t = math.radians(min(TURN.get(state, 0.0), 85.0 if opens == 'bifold' else 180.0))
        lx, ly = free[0] * math.cos(t) + n[0] * math.sin(t), free[1] * math.cos(t) + n[1] * math.sin(t)
        draw.line([hx, hy, hx + lx * r, hy - ly * r], fill=colour, width=3)
    if _leaves(o) or opens == 'none':
        return
    (cx, cy, _), (sx, sy, _) = o['center_m'], o['size_m']
    n = tuple(o.get('inward') or ((0, 1) if sx >= sy else (1, 0)))
    u = (1.0, 0.0) if n[1] else (0.0, 1.0)
    run, hs = (sx if n[1] else sy), o.get('hinge_sign') or -1
    shown = {'ajar': 0.5, 'open': 0.0, 'folded': 0.0}.get(state, 1.0)

    def seg(u0, u1, v, **kw):
        draw.line([*px(cx + u0 * u[0] + v * n[0], cy + u0 * u[1] + v * n[1]),
                   *px(cx + u1 * u[0] + v * n[0], cy + u1 * u[1] + v * n[1])], fill=colour, **kw)

    if opens == 'sliding':
        shift = hs * run * (1 - shown)
        seg(shift - run / 2, shift + run / 2, 0.08, width=4)
    elif opens == 'pocket':
        seg(hs * run / 2, hs * run * 1.5, 0, width=1)              # the pocket in the wall
        if shown:
            seg(-hs * run / 2, -hs * run / 2 + hs * run * shown, 0, width=4)
    elif opens in ('roll-up', 'up-and-over'):
        for k in range(8):
            seg(-run / 2 + k * run / 8, -run / 2 + (k + 0.5) * run / 8, 0.06, width=2)
    elif opens == 'revolving':
        c, r = px(cx, cy), run / 2 * scale
        draw.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], outline=colour, width=2)
        draw.line([c[0] - r * 0.7, c[1] - r * 0.7, c[0] + r * 0.7, c[1] + r * 0.7], fill=colour, width=2)
        draw.line([c[0] - r * 0.7, c[1] + r * 0.7, c[0] + r * 0.7, c[1] - r * 0.7], fill=colour, width=2)


def plan_path(ref_dir, vfe_name: str):
    return ref_dir / f"{safe_name(vfe_name)}.plan.png"


def run_room_plans(project, llm, config: dict, rooms=None, force: bool = False, attempts: int = 2) -> dict:
    """Write a checked floor plan into each room's View-From-Entrance anchors.

    Rooms that already carry anchor_points (a plan, or anchors read from rendered views) are kept unless force.
    A plan that still fails its checks after `attempts` is saved with its issues and reported.
    """
    from lib.studio.artist import load_character_refs, remake_room_refs
    from lib.studio.artist.room_anchors import _generate_room_anchors
    from lib.studio.room_sketch import build_sketch_spec

    remake_room_refs(config, llm, project, create_only=True)
    load_character_refs(project)
    wanted = {r.lower() for r in rooms} if rooms else None
    summary = {'planned': [], 'with_issues': {}, 'failed': [], 'skipped': []}
    for name, info in sorted(project.character_info.items()):
        if info.get('type') != 'Room' or not name.endswith(f'-{VFE}'):
            continue
        base = name[: -len(VFE) - 1]
        if wanted and base.lower() not in wanted and name.lower() not in wanted:
            continue
        if info.get('anchor_points') and not force:
            summary['skipped'].append(base)
            continue
        vocabulary = info.get('room_vocabulary') or []
        places = placeable(vocabulary)
        named, context = (''.join(f"  [{p.get('id')}] {p.get('description', '')}\n" for p in vocabulary
                                  if (p in places) == placed) for placed in (True, False))
        rules = (PLAN_RULES + (f"\nNAMED POSITIONS:\n{named}" if named else '')
                 + (f"\nROOM-WIDE (size, light and atmosphere for the whole room; no object or zone):\n{context}"
                    if context else ''))
        extra, best = rules, None
        for attempt in range(1, attempts + 1):
            anchors = _generate_room_anchors(info, llm, extra=extra)
            try:
                spec = build_sketch_spec(anchors, [name], config, info.get('visual_desc', '')) if anchors else None
            except ValueError as exc:
                anchors, spec, issues = None, None, [str(exc)]
            else:
                issues = validate_plan(anchors, spec, vocabulary) if spec else ['no layout returned']
            logger.info(f"  📐 {base}: plan attempt {attempt} — {len(issues)} issue(s)")
            if spec and (best is None or len(issues) < len(best[2])):
                best = (anchors, spec, issues)
            if not issues:
                break
            previous = f"\nYOUR PREVIOUS LAYOUT:\n{json.dumps(anchors, separators=(',', ':'))}\n" if anchors else '\n'
            extra = (rules + previous + "IT FAILED THESE CHECKS — return it corrected: fix every one, keep everything "
                     "else unchanged:\n" + ''.join(f"- {i}\n" for i in issues))
        if best is None:
            logger.warning(f"  ⚠️  {base}: no usable plan")
            summary['failed'].append(base)
            continue
        anchors, spec, issues = best
        render_plan_png(spec, anchors, plan_path(project.ref_dir, name), base, issues)
        json_path = project.ref_dir / f"{safe_name(name)}.json"
        data = json.loads(json_path.read_text(encoding='utf-8'))
        data['anchor_points'] = anchors
        data['floor_plan'] = {'issues': issues, 'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        if (project.ref_dir / f"{safe_name(name)}.png").exists():
            data['needs_regenerate'] = True  # the image predates its layout
        atomic_write(json_path, json.dumps(data, indent=2))
        project.character_info[name] = data
        summary['planned'].append(base)
        if issues:
            summary['with_issues'][base] = issues
            for issue in issues:
                logger.warning(f"  ⚠️  {base} plan: {issue}")
    return summary
