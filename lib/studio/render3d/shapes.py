"""Engine-neutral sketch geometry: room objects, car cabin and mannequins as world-space meshes.

Builders draw through _link_mesh_object, which records Mesh objects; engines only render the result.
Materials are plain linear RGB tuples. Groups name the anchor object a mesh belongs to, for culling.
"""
import math
import threading
from contextlib import contextmanager

from lib.studio.render3d.scene import Mesh, Scene, View

_SINK: list[Mesh] | None = None
_LOCK = threading.Lock()


@contextmanager
def _collect():
    """Gather every mesh the builders link while the block runs; one builder at a time."""
    global _SINK
    with _LOCK:
        _SINK = []
        try:
            yield _SINK
        finally:
            _SINK = None


def _make_material(name, rgb):
    return tuple(rgb)


def _link_mesh_object(name, verts, faces, location, material, yaw_degrees=0.0):
    a = math.radians(yaw_degrees)
    c, s = math.cos(a), math.sin(a)
    mesh = Mesh(name, [(location[0] + x * c - y * s, location[1] + x * s + y * c, location[2] + z) for x, y, z in verts],
                [tuple(f) for f in faces], tuple(material))
    _SINK.append(mesh)
    return mesh


CREATED: dict[str, list] = {}


def _shade(rgb, factor):
    return tuple(min(1.0, max(0.0, c * factor)) for c in rgb)


def _local(center, yaw_degrees, lx, ly, lz):
    angle = math.radians(yaw_degrees)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return (center[0] + lx * cos_a - ly * sin_a,
            center[1] + lx * sin_a + ly * cos_a,
            center[2] + lz)


def _rotate_xyz(x, y, z, pitch_x=0.0, roll_y=0.0):
    if pitch_x:
        ax = math.radians(pitch_x)
        ca, sa = math.cos(ax), math.sin(ax)
        y, z = y * ca - z * sa, y * sa + z * ca
    if roll_y:
        ay = math.radians(roll_y)
        cb, sb = math.cos(ay), math.sin(ay)
        x, z = x * cb + z * sb, -x * sb + z * cb
    return (x, y, z)


def _prism_geom(sx_bot, sy_bot, sx_top, sy_top, sz,
                shift_top_x=0.0, shift_top_y=0.0, pitch_x=0.0, roll_y=0.0):
    bx, by = max(0.004, sx_bot) / 2, max(0.004, sy_bot) / 2
    tx, ty = max(0.004, sx_top) / 2, max(0.004, sy_top) / 2
    hz = max(0.004, sz) / 2
    raw = [
        (-bx, -by, -hz),
        (bx, -by, -hz),
        (bx, by, -hz),
        (-bx, by, -hz),
        (-tx + shift_top_x, -ty + shift_top_y, hz),
        (tx + shift_top_x, -ty + shift_top_y, hz),
        (tx + shift_top_x, ty + shift_top_y, hz),
        (-tx + shift_top_x, ty + shift_top_y, hz),
    ]
    verts = [_rotate_xyz(x, y, z, pitch_x, roll_y) for (x, y, z) in raw]
    faces = [
        (0, 3, 2, 1),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return verts, faces


def _chamfer_geom(sx, sy, sz, bevel=0.012, pitch_x=0.0, roll_y=0.0):
    sx, sy, sz = max(0.004, sx), max(0.004, sy), max(0.004, sz)
    b = min(bevel, sx * 0.22, sy * 0.22, sz * 0.28)
    if b < 0.002:
        return _prism_geom(sx, sy, sx, sy, sz, pitch_x=pitch_x, roll_y=roll_y)

    hx, hy, hz = sx / 2, sy / 2, sz / 2
    ix, iy, iz = hx - b, hy - b, hz - b
    raw = [
        (-ix, -iy, -hz), (ix, -iy, -hz), (ix, iy, -hz), (-ix, iy, -hz),
        (-hx, -hy, -iz), (hx, -hy, -iz), (hx, hy, -iz), (-hx, hy, -iz),
        (-hx, -hy, iz), (hx, -hy, iz), (hx, hy, iz), (-hx, hy, iz),
        (-ix, -iy, hz), (ix, -iy, hz), (ix, iy, hz), (-ix, iy, hz),
    ]
    verts = [_rotate_xyz(x, y, z, pitch_x, roll_y) for (x, y, z) in raw]
    faces = [
        (0, 3, 2, 1),
        (12, 13, 14, 15),
        (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
        (4, 5, 9, 8), (5, 6, 10, 9), (6, 7, 11, 10), (7, 4, 8, 11),
        (8, 9, 13, 12), (9, 10, 14, 13), (10, 11, 15, 14), (11, 8, 12, 15),
    ]
    return verts, faces


def _frustum_geom(radius1, radius2, depth, segments=20, axis='Z'):
    r1 = max(0.0, radius1)
    r2 = max(0.0, radius2)
    hz = max(0.004, depth) / 2
    n = max(6, segments)

    def _orient(px, py, pz):
        if axis == 'X':
            return (pz, py, -px)
        if axis == 'Y':
            return (px, pz, -py)
        return (px, py, pz)

    verts = []
    faces = []
    if r1 > 1e-5 and r2 > 1e-5:
        for i in range(n):
            a = 2 * math.pi * i / n
            ca, sa = math.cos(a), math.sin(a)
            verts.append(_orient(ca * r1, sa * r1, -hz))
        for i in range(n):
            a = 2 * math.pi * i / n
            ca, sa = math.cos(a), math.sin(a)
            verts.append(_orient(ca * r2, sa * r2, hz))
        faces.append(tuple(range(n - 1, -1, -1)))
        faces.append(tuple(range(n, 2 * n)))
        for i in range(n):
            j = (i + 1) % n
            faces.append((i, j, n + j, n + i))
    elif r1 > 1e-5:
        for i in range(n):
            a = 2 * math.pi * i / n
            verts.append(_orient(math.cos(a) * r1, math.sin(a) * r1, -hz))
        verts.append(_orient(0.0, 0.0, hz))
        apex = n
        faces.append(tuple(range(n - 1, -1, -1)))
        for i in range(n):
            j = (i + 1) % n
            faces.append((i, j, apex))
    else:
        verts.append(_orient(0.0, 0.0, -hz))
        for i in range(n):
            a = 2 * math.pi * i / n
            verts.append(_orient(math.cos(a) * r2, math.sin(a) * r2, hz))
        faces.append(tuple(range(1, n + 1)))
        for i in range(n):
            j = (i + 1) % n
            faces.append((0, 1 + j, 1 + i))
    return verts, faces


def _icosphere_geom(radius, subdivisions=1):
    r = max(0.005, radius)
    t = (1.0 + math.sqrt(5.0)) / 2.0
    raw_verts = [
        (-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0),
        (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
        (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1),
    ]
    verts = []
    for x, y, z in raw_verts:
        length = math.sqrt(x * x + y * y + z * z)
        verts.append((x / length, y / length, z / length))

    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    for _ in range(subdivisions):
        mid_cache = {}
        new_faces = []

        def _mid(i1, i2):
            key = (min(i1, i2), max(i1, i2))
            if key not in mid_cache:
                v1, v2 = verts[i1], verts[i2]
                mx, my, mz = (v1[0] + v2[0]) / 2, (v1[1] + v2[1]) / 2, (v1[2] + v2[2]) / 2
                length = math.sqrt(mx * mx + my * my + mz * mz)
                mid_cache[key] = len(verts)
                verts.append((mx / length, my / length, mz / length))
            return mid_cache[key]

        for a, b, c in faces:
            ab = _mid(a, b)
            bc = _mid(b, c)
            ca = _mid(c, a)
            new_faces.extend([(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)])
        faces = new_faces

    scaled = [(x * r, y * r, z * r) for (x, y, z) in verts]
    return scaled, faces


def _add_box(name, center, size, material, yaw_degrees=0.0):
    verts, faces = _prism_geom(size[0], size[1], size[0], size[1], size[2])
    return _link_mesh_object(name, verts, faces, center, material, yaw_degrees)


def _box(obj, name, mats, mat, lx, ly, lz, sx, sy, sz, pitch_x=0.0, roll_y=0.0):
    verts, faces = _prism_geom(sx, sy, sx, sy, sz, pitch_x=pitch_x, roll_y=roll_y)
    created = _link_mesh_object(
        f"{obj['id']}-{name}",
        verts,
        faces,
        _local(obj['center_m'], obj['yaw_degrees'], lx, ly, lz),
        mats[mat],
        obj['yaw_degrees'],
    )
    CREATED.setdefault(obj['id'], []).append(created)
    return created


def _chamfer_box(obj, name, mats, mat, lx, ly, lz, sx, sy, sz,
                 bevel=0.012, pitch_x=0.0, roll_y=0.0):
    verts, faces = _chamfer_geom(sx, sy, sz, bevel=bevel, pitch_x=pitch_x, roll_y=roll_y)
    created = _link_mesh_object(
        f"{obj['id']}-{name}",
        verts,
        faces,
        _local(obj['center_m'], obj['yaw_degrees'], lx, ly, lz),
        mats[mat],
        obj['yaw_degrees'],
    )
    CREATED.setdefault(obj['id'], []).append(created)
    return created


def _prism(obj, name, mats, mat, lx, ly, lz, sx_bot, sy_bot, sx_top, sy_top, sz,
           shift_top_x=0.0, shift_top_y=0.0, pitch_x=0.0, roll_y=0.0):
    verts, faces = _prism_geom(
        sx_bot, sy_bot, sx_top, sy_top, sz,
        shift_top_x=shift_top_x, shift_top_y=shift_top_y,
        pitch_x=pitch_x, roll_y=roll_y,
    )
    created = _link_mesh_object(
        f"{obj['id']}-{name}",
        verts,
        faces,
        _local(obj['center_m'], obj['yaw_degrees'], lx, ly, lz),
        mats[mat],
        obj['yaw_degrees'],
    )
    CREATED.setdefault(obj['id'], []).append(created)
    return created


def _cyl(obj, name, mats, mat, lx, ly, lz, radius, depth, axis='Z', segments=20):
    r = max(0.005, radius)
    verts, faces = _frustum_geom(r, r, depth, segments=segments, axis=axis)
    created = _link_mesh_object(
        f"{obj['id']}-{name}",
        verts,
        faces,
        _local(obj['center_m'], obj['yaw_degrees'], lx, ly, lz),
        mats[mat],
        obj['yaw_degrees'],
    )
    CREATED.setdefault(obj['id'], []).append(created)
    return created


def _cone(obj, name, mats, mat, lx, ly, lz, radius1, radius2, depth,
          axis='Z', segments=20):
    verts, faces = _frustum_geom(radius1, radius2, depth, segments=segments, axis=axis)
    created = _link_mesh_object(
        f"{obj['id']}-{name}",
        verts,
        faces,
        _local(obj['center_m'], obj['yaw_degrees'], lx, ly, lz),
        mats[mat],
        obj['yaw_degrees'],
    )
    CREATED.setdefault(obj['id'], []).append(created)
    return created


def _sphere(obj, name, mats, mat, lx, ly, lz, radius, subdivisions=1):
    verts, faces = _icosphere_geom(radius, subdivisions=subdivisions)
    created = _link_mesh_object(
        f"{obj['id']}-{name}",
        verts,
        faces,
        _local(obj['center_m'], obj['yaw_degrees'], lx, ly, lz),
        mats[mat],
        obj['yaw_degrees'],
    )
    CREATED.setdefault(obj['id'], []).append(created)
    return created


def _frame_box(obj, name, mats, mat, lx, ly, lz, sx, sy, sz,
               border_x, border_z, bottom_border=None):
    """4-bar perimeter frame in the X-Z plane with clean stepped joints."""
    bx = min(sx * 0.42, max(0.008, border_x))
    bz_top = min(sz * 0.42, max(0.008, border_z))
    bz_bot = min(sz * 0.42, max(0.008, bottom_border if bottom_border is not None else border_z))
    inner_h = max(0.006, sz - bz_top - bz_bot)
    inner_z = lz + (bz_bot - bz_top) / 2
    _box(obj, f'{name}-top', mats, mat, lx, ly, lz + sz / 2 - bz_top / 2, sx, sy, bz_top)
    _box(obj, f'{name}-bot', mats, mat, lx, ly, lz - sz / 2 + bz_bot / 2, sx, sy, bz_bot)
    _box(obj, f'{name}-left', mats, mat, lx - sx / 2 + bx / 2, ly, inner_z, bx, sy, inner_h)
    _box(obj, f'{name}-right', mats, mat, lx + sx / 2 - bx / 2, ly, inner_z, bx, sy, inner_h)


def _table(obj, mats):
    sx, sy, sz = obj['size_m']
    top_t = min(sz * 0.14, max(0.025, sz * 0.065))
    _chamfer_box(obj, 'top', mats, 'base', 0, 0, sz / 2 - top_t / 2,
                 sx, sy, top_t, bevel=min(0.008, top_t * 0.25))

    # Small square cafe/bistro tables read cleaner with a pedestal & cross base
    if min(sx, sy) < 0.72 and abs(sx - sy) < 0.15 and sz > 0.45:
        base_h = max(0.018, sz * 0.04)
        col_h = max(0.04, sz - top_t - base_h)
        col_r = max(0.02, min(sx, sy) * 0.065)
        span = min(sx, sy) * 0.65
        _cyl(obj, 'pedestal', mats, 'dark', 0, 0, -sz / 2 + base_h + col_h / 2, col_r, col_h)
        _box(obj, 'foot-x', mats, 'dark', 0, 0, -sz / 2 + base_h / 2, span, col_r * 1.4, base_h)
        _box(obj, 'foot-y', mats, 'dark', 0, 0, -sz / 2 + base_h / 2, col_r * 1.4, span, base_h)
        return

    overhang = min(sx * 0.12, sy * 0.12, max(0.018, min(sx, sy) * 0.055))
    leg_top = max(0.026, min(sx, sy) * 0.058)
    leg_bot = leg_top * 0.65
    leg_h = max(0.04, sz - top_t)
    apron_h = min(leg_h * 0.26, max(0.028, sz * 0.09))
    apron_t = max(0.016, leg_top * 0.45)

    lx_off = max(0.01, sx / 2 - overhang - leg_top / 2)
    ly_off = max(0.01, sy / 2 - overhang - leg_top / 2)
    for dx in (-1, 1):
        for dy in (-1, 1):
            _prism(obj, f'leg-{dx}-{dy}', mats, 'dark',
                   dx * lx_off, dy * ly_off, -sz / 2 + leg_h / 2,
                   leg_bot, leg_bot, leg_top, leg_top, leg_h)

    apron_z = sz / 2 - top_t - apron_h / 2
    span_x = max(0.02, 2 * lx_off - leg_top)
    span_y = max(0.02, 2 * ly_off - leg_top)
    for dy in (-1, 1):
        _box(obj, f'apron-y-{dy}', mats, 'dark', 0, dy * ly_off, apron_z, span_x, apron_t, apron_h)
    for dx in (-1, 1):
        _box(obj, f'apron-x-{dx}', mats, 'dark', dx * lx_off, 0, apron_z, apron_t, span_y, apron_h)


def _chair(obj, mats):
    sx, sy, sz = obj['size_m']
    seat_top = -sz / 2 + sz * 0.45
    seat_t = max(0.028, sz * 0.06)
    seat_d = sy * 0.82
    seat_y = -sy * 0.04
    leg_top = max(0.022, min(sx, sy) * 0.06)
    leg_bot = leg_top * 0.72

    _chamfer_box(obj, 'seat', mats, 'base', 0, seat_y, seat_top - seat_t / 2,
                 sx * 0.94, seat_d, seat_t, bevel=min(0.01, seat_t * 0.28))

    x_leg = max(0.01, sx * 0.44 - leg_top / 2)
    y_front = seat_y - seat_d / 2 + leg_top * 0.65
    y_rear_bot = seat_y + seat_d / 2 - leg_top * 0.65
    front_h = max(0.04, sz * 0.45 - seat_t * 0.5)

    for dx in (-1, 1):
        _prism(obj, f'leg-f-{dx}', mats, 'dark',
               dx * x_leg, y_front, -sz / 2 + front_h / 2,
               leg_bot, leg_bot, leg_top, leg_top, front_h, shift_top_y=0.008)
        # Rear stile rises from floor and rakes backward to support the backrest
        rake = max(0.02, sy * 0.08)
        _prism(obj, f'stile-r-{dx}', mats, 'dark',
               dx * x_leg, y_rear_bot + rake / 2, 0,
               leg_bot, leg_bot, leg_top * 0.9, leg_top * 0.9, sz,
               shift_top_y=rake)
        # Side stretcher rung
        rung_y = (y_front + y_rear_bot) / 2
        rung_len = max(0.02, abs(y_rear_bot - y_front))
        _box(obj, f'stretcher-{dx}', mats, 'dark',
             dx * x_leg, rung_y, -sz / 2 + sz * 0.16, leg_bot * 0.7, rung_len, leg_bot * 0.7)

    # Reclined two-rail backrest with open lumbar gap
    back_w = max(0.04, sx * 0.92)
    back_t = max(0.022, sy * 0.065)
    upper_h = sz * 0.22
    lower_h = sz * 0.09
    _chamfer_box(obj, 'back-top', mats, 'base', 0, sy * 0.41, sz / 2 - upper_h / 2 - sz * 0.02,
                 back_w, back_t, upper_h, bevel=0.006, pitch_x=-9.0)
    _box(obj, 'back-lumbar', mats, 'light', 0, sy * 0.38, seat_top + sz * 0.16,
         back_w * 0.94, back_t * 0.85, lower_h, pitch_x=-9.0)


def _sofa(obj, mats):
    sx, sy, sz = obj['size_m']
    leg_h = max(0.03, sz * 0.10)
    base_h = max(0.05, sz * 0.16)
    arm_w = max(0.055, min(0.18, sx * 0.11))
    back_d = max(0.07, sy * 0.22)
    seat_d = max(0.08, sy - back_d)
    inner_w = max(0.08, sx - 2 * arm_w)

    foot_w = max(0.03, min(sx, sy) * 0.06)
    for dx in (-1, 1):
        for dy in (-1, 1):
            _prism(obj, f'foot-{dx}-{dy}', mats, 'dark',
                   dx * (sx * 0.46 - foot_w / 2), dy * (sy * 0.45 - foot_w / 2),
                   -sz / 2 + leg_h / 2,
                   foot_w * 0.65, foot_w * 0.65, foot_w, foot_w, leg_h)

    deck_z = -sz / 2 + leg_h + base_h / 2
    _box(obj, 'deck', mats, 'dark', 0, 0, deck_z, sx * 0.98, sy * 0.96, base_h)

    n_cush = max(2, min(4, round(inner_w / 0.62)))
    gap = 0.012
    cush_w = max(0.03, (inner_w - gap * (n_cush - 1)) / n_cush)
    cush_h = max(0.05, sz * 0.17)
    seat_top = -sz / 2 + leg_h + base_h + cush_h
    seat_y = -back_d / 2

    for i in range(n_cush):
        cx = -inner_w / 2 + cush_w / 2 + i * (cush_w + gap)
        _chamfer_box(obj, f'seat-{i}', mats, 'base', cx, seat_y, seat_top - cush_h / 2,
                     cush_w, seat_d * 0.96, cush_h, bevel=0.014)

    back_h = max(0.08, sz - leg_h - base_h)
    _prism(obj, 'back-frame', mats, 'dark',
           0, sy / 2 - back_d / 2, -sz / 2 + leg_h + base_h + back_h / 2,
           sx * 0.98, back_d, sx * 0.96, back_d * 0.78, back_h, shift_top_y=back_d * 0.08)

    pillow_h = max(0.06, sz - seat_top - 0.01)
    pillow_d = max(0.04, back_d * 0.65)
    for i in range(n_cush):
        cx = -inner_w / 2 + cush_w / 2 + i * (cush_w + gap)
        _chamfer_box(obj, f'pillow-{i}', mats, 'light',
                     cx, sy / 2 - back_d - pillow_d * 0.35, seat_top + pillow_h / 2,
                     cush_w * 0.96, pillow_d, pillow_h, bevel=0.016, pitch_x=-10.0)

    arm_h = max(0.06, min(sz - leg_h - base_h, cush_h + sz * 0.17))
    for dx in (-1, 1):
        _chamfer_box(obj, f'arm-{dx}', mats, 'base',
                     dx * (sx / 2 - arm_w / 2), -back_d * 0.12,
                     -sz / 2 + leg_h + base_h + arm_h / 2,
                     arm_w, sy - back_d * 0.35, arm_h, bevel=0.014)


def _bed(obj, mats):
    sx, sy, sz = obj['size_m']
    leg_h = max(0.025, sz * 0.08)
    rail_h = max(0.05, sz * 0.16)
    matt_h = max(0.07, sz * 0.21)
    hb_t = max(0.035, min(0.09, sy * 0.045))
    fb_t = max(0.028, min(0.06, sy * 0.03))
    post_w = max(0.035, min(sx, sy) * 0.04)

    for dx in (-1, 1):
        for dy in (-1, 1):
            _prism(obj, f'leg-{dx}-{dy}', mats, 'dark',
                   dx * (sx / 2 - post_w / 2), dy * (sy / 2 - post_w / 2),
                   -sz / 2 + leg_h / 2,
                   post_w * 0.7, post_w * 0.7, post_w, post_w, leg_h)

    frame_z = -sz / 2 + leg_h + rail_h / 2
    _box(obj, 'frame', mats, 'dark', 0, 0, frame_z, sx * 0.98, sy * 0.98, rail_h)

    # Headboard (+Y) with posts, cap rail, and recessed panel
    hb_h = max(0.10, sz - leg_h)
    hb_y = sy / 2 - hb_t / 2
    hb_z = -sz / 2 + leg_h + hb_h / 2
    _frame_box(obj, 'headboard-frame', mats, 'dark', 0, hb_y, hb_z,
               sx, hb_t, hb_h, post_w, max(0.03, sz * 0.05))
    _box(obj, 'headboard-panel', mats, 'base', 0, hb_y, hb_z,
         max(0.04, sx - 2 * post_w), hb_t * 0.55, max(0.04, hb_h - sz * 0.10))

    # Low footboard (-Y)
    fb_h = rail_h + matt_h * 0.55
    _box(obj, 'footboard', mats, 'dark', 0, -sy / 2 + fb_t / 2,
         -sz / 2 + leg_h + fb_h / 2, sx, fb_t, fb_h)

    # Mattress & folded duvet
    inner_len = max(0.1, sy - hb_t - fb_t)
    matt_y = (fb_t - hb_t) / 2
    matt_top = -sz / 2 + leg_h + rail_h + matt_h
    _chamfer_box(obj, 'mattress', mats, 'light', 0, matt_y, matt_top - matt_h / 2,
                 sx * 0.94, inner_len * 0.98, matt_h, bevel=0.015)

    duvet_len = inner_len * 0.62
    duvet_y = -sy / 2 + fb_t + duvet_len / 2 + 0.01
    duvet_h = max(0.025, matt_h * 0.22)
    _chamfer_box(obj, 'duvet', mats, 'base', 0, duvet_y, matt_top + duvet_h / 2 - 0.005,
                 sx * 0.96, duvet_len, duvet_h, bevel=0.01)
    # Folded turnover cuff
    cuff_len = max(0.06, inner_len * 0.11)
    _chamfer_box(obj, 'duvet-cuff', mats, 'light',
                 0, duvet_y + duvet_len / 2 - cuff_len / 2, matt_top + duvet_h * 0.85,
                 sx * 0.965, cuff_len, duvet_h * 0.7, bevel=0.008)

    # Pillows at headboard end
    n_pil = 1 if sx < 1.15 else 2
    pil_w = (sx * 0.84) / n_pil - (0.02 if n_pil == 2 else 0.0)
    pil_d = max(0.08, inner_len * 0.18)
    pil_h = max(0.04, matt_h * 0.35)
    pil_y = sy / 2 - hb_t - pil_d * 0.62
    for i in range(n_pil):
        px = 0.0 if n_pil == 1 else (-sx * 0.22 if i == 0 else sx * 0.22)
        _chamfer_box(obj, f'pillow-{i}', mats, 'light',
                     px, pil_y, matt_top + pil_h * 0.45,
                     pil_w, pil_d, pil_h, bevel=0.016, pitch_x=14.0)


def _cabinet(obj, mats):
    sx, sy, sz = obj['size_m']
    kick_h = min(0.10, max(0.025, sz * 0.07))
    top_t = min(0.04, max(0.015, sz * 0.03))
    body_h = max(0.04, sz - kick_h - top_t)
    body_d = sy * 0.92

    _box(obj, 'plinth', mats, 'dark', 0, sy * 0.02, -sz / 2 + kick_h / 2,
         sx * 0.92, body_d * 0.88, kick_h)
    _box(obj, 'carcass', mats, 'base', 0, sy * 0.02, -sz / 2 + kick_h + body_h / 2,
         sx * 0.96, body_d, body_h)
    _chamfer_box(obj, 'top', mats, 'dark', 0, 0, sz / 2 - top_t / 2,
                 sx, sy, top_t, bevel=0.006)

    front_y = -sy * 0.44 - max(0.008, sy * 0.025)
    front_t = max(0.014, sy * 0.045)
    has_drawer = sz >= 0.72
    drawer_h = body_h * 0.20 if has_drawer else 0.0
    doors_h = body_h - drawer_h - (0.014 if has_drawer else 0.0)
    doors_z = -sz / 2 + kick_h + doors_h / 2 + 0.004

    if has_drawer:
        dz = sz / 2 - top_t - drawer_h / 2 - 0.004
        dw = sx * 0.92
        _frame_box(obj, 'drawer-frame', mats, 'dark', 0, front_y, dz,
                   dw, front_t, drawer_h, max(0.02, dw * 0.05), max(0.018, drawer_h * 0.18))
        _box(obj, 'drawer-panel', mats, 'base', 0, front_y + front_t * 0.2, dz,
             dw * 0.90, front_t * 0.5, drawer_h * 0.65)
        _box(obj, 'drawer-pull', mats, 'accent', 0, front_y - front_t * 0.65, dz,
             min(0.16, dw * 0.28), max(0.012, sy * 0.03), max(0.012, drawer_h * 0.12))

    n_doors = 1 if sx < 0.52 else 2
    gap = max(0.012, sx * 0.018)
    door_w = max(0.04, (sx * 0.93 - gap * (n_doors - 1)) / n_doors)
    stile = max(0.022, door_w * 0.14)
    rail = max(0.022, doors_h * 0.07)

    for i in range(n_doors):
        dx = 0.0 if n_doors == 1 else (-1 if i == 0 else 1) * (door_w / 2 + gap / 2)
        _frame_box(obj, f'door-frame-{i}', mats, 'dark', dx, front_y, doors_z,
                   door_w, front_t, doors_h, stile, rail)
        _box(obj, f'door-panel-{i}', mats, 'base', dx, front_y + front_t * 0.2, doors_z,
             max(0.02, door_w - 2 * stile), front_t * 0.5, max(0.02, doors_h - 2 * rail))
        hx = dx + (door_w * 0.34 if n_doors == 1 else (1 if i == 0 else -1) * (door_w / 2 - stile * 0.65))
        _box(obj, f'handle-{i}', mats, 'accent', hx, front_y - front_t * 0.65,
             doors_z + doors_h * 0.12,
             max(0.012, sx * 0.018), max(0.014, sy * 0.035), min(0.18, doors_h * 0.22))


def _counter(obj, mats):
    sx, sy, sz = obj['size_m']
    kick_h = min(0.10, max(0.025, sz * 0.07))
    top_t = min(0.05, max(0.02, sz * 0.04))
    body_h = max(0.04, sz - kick_h - top_t)
    _box(obj, 'plinth', mats, 'dark', 0, 0, -sz / 2 + kick_h / 2, sx * 0.94, sy * 0.80, kick_h)
    _box(obj, 'body', mats, 'base', 0, 0, -sz / 2 + kick_h + body_h / 2, sx * 0.97, sy * 0.88, body_h)
    _chamfer_box(obj, 'top', mats, 'dark', 0, 0, sz / 2 - top_t / 2, sx, sy, top_t, bevel=0.008)


def _shelf(obj, mats):
    sx, sy, sz = obj['size_m']
    post = max(0.026, min(sx, sy) * 0.055)
    shelf_t = max(0.02, sz * 0.024)

    for dx in (-1, 1):
        for dy in (-1, 1):
            _box(obj, f'post-{dx}-{dy}', mats, 'dark',
                 dx * (sx / 2 - post / 2), dy * (sy / 2 - post / 2), 0, post, post, sz)

    # Thin open-friendly back panel
    _box(obj, 'back', mats, 'dark', 0, sy / 2 - 0.008, 0, sx * 0.98, 0.014, sz * 0.98)

    # Bottom plinth shelf, 3 middle shelves, and top cap shelf
    z_levels = [
        -sz / 2 + sz * 0.05,
        -sz / 2 + sz * 0.28,
        -sz / 2 + sz * 0.51,
        -sz / 2 + sz * 0.74,
        sz / 2 - shelf_t / 2,
    ]
    for idx, z in enumerate(z_levels):
        w = sx if idx == len(z_levels) - 1 else max(0.04, sx - post * 0.8)
        d = sy if idx == len(z_levels) - 1 else max(0.04, sy - post * 0.8)
        _box(obj, f'shelf-{idx}', mats, 'base', 0, 0, z, w, d, shelf_t)
        # Side ladder rails keep side profile articulated while remaining see-through
        for dx in (-1, 1):
            _box(obj, f'side-rail-{idx}-{dx}', mats, 'dark',
                 dx * (sx / 2 - post / 2), 0, z, post * 0.7, max(0.04, sy - post), shelf_t * 0.9)

    # Light book/box accents on two middle shelves so it reads immediately as a bookshelf
    if sx >= 0.45 and sz >= 0.8:
        book_h = sz * 0.15
        book_d = sy * 0.65
        for shelf_idx, x_sign in ((1, -1), (2, 1)):
            bz = z_levels[shelf_idx] + shelf_t / 2 + book_h / 2
            bx = x_sign * (sx * 0.24)
            _box(obj, f'books-a-{shelf_idx}', mats, 'light',
                 bx, -sy * 0.05, bz, sx * 0.14, book_d, book_h)
            _box(obj, f'books-b-{shelf_idx}', mats, 'accent',
                 bx + x_sign * (sx * 0.09), -sy * 0.03, bz - book_h * 0.06,
                 sx * 0.06, book_d * 0.92, book_h * 0.88)


def _monitor(obj, mats):
    sx, sy, sz = obj['size_m']
    base_h = max(0.012, sz * 0.04)
    screen_h = sz * 0.68
    screen_z = sz / 2 - screen_h / 2
    head_d = max(0.024, min(0.055, sy * 0.26))
    bezel = max(0.012, min(sx, screen_h) * 0.045)
    chin = bezel * 1.65

    front_y = -sy * 0.12
    _frame_box(obj, 'bezel', mats, 'dark', 0, front_y, screen_z,
               sx, head_d * 0.45, screen_h, bezel, bezel, bottom_border=chin)
    inner_w = max(0.04, sx - 2 * bezel)
    inner_h = max(0.04, screen_h - bezel - chin)
    inner_z = screen_z + (chin - bezel) / 2
    _box(obj, 'screen', mats, 'light', 0, front_y + head_d * 0.08, inner_z,
         inner_w, head_d * 0.25, inner_h)
    # Tapered rear housing
    _prism(obj, 'rear-housing', mats, 'dark',
           0, front_y + head_d * 0.55, screen_z,
           sx * 0.94, head_d * 0.7, sx * 0.72, head_d * 0.2, screen_h * 0.90,
           pitch_x=90.0)

    stand_h = max(0.04, sz - base_h - screen_h * 0.45)
    _prism(obj, 'stand', mats, 'base',
           0, sy * 0.12, -sz / 2 + base_h + stand_h / 2,
           sx * 0.13, sy * 0.22, sx * 0.10, sy * 0.16, stand_h, shift_top_y=-sy * 0.14)
    _chamfer_box(obj, 'base', mats, 'base', 0, 0, -sz / 2 + base_h / 2,
                 sx * 0.42, sy * 0.86, base_h, bevel=min(0.006, base_h * 0.35))


def _batten(obj, mats):
    sx, sy, sz = obj['size_m']
    cap_w = max(0.02, min(0.06, sx * 0.04))
    spine_h = max(0.012, sz * 0.35)
    tube_h = max(0.014, sz - spine_h)
    _box(obj, 'spine', mats, 'dark', 0, 0, sz / 2 - spine_h / 2,
         sx, max(0.025, sy * 0.42), spine_h)
    _box(obj, 'diffuser', mats, 'light', 0, 0, -sz / 2 + tube_h / 2,
         max(0.04, sx - 2 * cap_w), max(0.02, sy * 0.34), tube_h)
    for dx in (-1, 1):
        _box(obj, f'endcap-{dx}', mats, 'dark',
             dx * (sx / 2 - cap_w / 2), 0, -sz / 2 + tube_h / 2,
             cap_w, max(0.026, sy * 0.44), tube_h)


def _lamp(obj, mats):
    sx, sy, sz = obj['size_m']
    radius = min(sx, sy) / 2
    base_h = max(0.018, sz * 0.065)
    shade_h = sz * 0.34
    pole_h = max(0.04, sz - base_h - shade_h * 0.85)

    _cyl(obj, 'base-lower', mats, 'dark', 0, 0, -sz / 2 + base_h * 0.35,
         radius * 0.68, base_h * 0.7)
    _cyl(obj, 'base-upper', mats, 'base', 0, 0, -sz / 2 + base_h * 0.85,
         radius * 0.45, base_h * 0.3)
    _cyl(obj, 'pole', mats, 'base', 0, 0, -sz / 2 + base_h + pole_h / 2,
         max(0.008, radius * 0.09), pole_h)
    _cyl(obj, 'socket', mats, 'dark', 0, 0, -sz / 2 + base_h + pole_h,
         max(0.014, radius * 0.16), max(0.02, sz * 0.05))

    shade_z = sz / 2 - shade_h / 2
    r_bot = radius * 0.96
    r_top = radius * 0.50
    _cone(obj, 'shade', mats, 'light', 0, 0, shade_z, r_bot, r_top, shade_h)
    rim_h = max(0.008, shade_h * 0.06)
    _cyl(obj, 'rim-bot', mats, 'dark', 0, 0, shade_z - shade_h / 2 + rim_h / 2,
         r_bot * 1.01, rim_h)
    _cyl(obj, 'rim-top', mats, 'dark', 0, 0, shade_z + shade_h / 2 - rim_h / 2,
         r_top * 1.02, rim_h)


def _window(obj, mats):
    sx, sy, sz = obj['size_m']
    sill_h = max(0.022, sz * 0.045)
    frame = max(0.035, min(sx, sz) * 0.055)
    sash = max(0.022, frame * 0.65)
    win_h = max(0.06, sz - sill_h)
    win_z = -sz / 2 + sill_h + win_h / 2

    _chamfer_box(obj, 'sill', mats, 'dark', 0, 0, -sz / 2 + sill_h / 2,
                 sx, sy, sill_h, bevel=min(0.006, sill_h * 0.25))
    _frame_box(obj, 'casing', mats, 'dark', 0, 0, win_z,
               sx * 0.96, sy * 0.84, win_h, frame, frame)
    inner_w = max(0.04, sx * 0.96 - 2 * frame)
    inner_h = max(0.04, win_h - 2 * frame)
    _frame_box(obj, 'sash', mats, 'base', 0, 0, win_z,
               inner_w, sy * 0.55, inner_h, sash, sash)

    glass_w = max(0.02, inner_w - 2 * sash)
    glass_h = max(0.02, inner_h - 2 * sash)
    _box(obj, 'glass', mats, 'light', 0, 0, win_z,
         glass_w, max(0.008, sy * 0.16), glass_h)
    _box(obj, 'mullion-v', mats, 'dark', 0, 0, win_z,
         max(0.015, frame * 0.45), sy * 0.45, glass_h)
    _box(obj, 'mullion-h', mats, 'dark', 0, 0, win_z + glass_h * 0.12,
         glass_w, sy * 0.42, max(0.015, frame * 0.4))


DOOR_TURN = {'ajar': 30.0, 'open': 90.0, 'folded': 172.0}  # hinged leaf, degrees from closed
DOOR_SHOWN = {'ajar': 0.5, 'open': 0.0, 'folded': 0.0}       # pocket/roll-up: share of the opening still covered


def _door(obj, mats):
    """Frame plus the leaf its mechanism (`opens`) and `leaf_state` put there.

    Built along the wall (u, hinge_sign end = +/-) and into the room (v, `inward`); an open or missing
    leaf shows a dark void, so a doorway reads as an opening, not a closed door.
    """
    sx, sy, sz = obj['size_m']
    nx, ny = obj.get('inward') or ((0, 1) if sx >= sy else (1, 0))
    ux, uy = (1.0, 0.0) if ny else (0.0, 1.0)
    run, thick = (sx, sy) if ny else (sy, sx)
    s = -uy * nx + ux * ny                       # +1 when the frame's local +y points into the room
    cx, cy, cz = obj['center_m']
    frame_obj = {'id': obj['id'], 'center_m': obj['center_m'], 'yaw_degrees': math.degrees(math.atan2(uy, ux))}
    opens, state = obj.get('opens') or 'inward', obj.get('leaf_state') or 'closed'
    hs = obj.get('hinge_sign') or -1

    frame = max(0.045, min(run, sz) * 0.055)
    thresh_h = max(0.012, sz * 0.012)
    leaf_w, leaf_h = max(0.06, run - 2 * frame), max(0.08, sz - frame - thresh_h)
    leaf_z = -sz / 2 + thresh_h + leaf_h / 2
    leaf_d = max(0.024, min(0.06, thick * 0.48))
    top = sz / 2 - frame

    def part(name, mat, u, v, z, wu, wv, h, **kw):
        _box(frame_obj, name, mats, mat, u, s * v, z, wu, wv, h, **kw)

    def leaf(name, width, u0, free, turn=0.0, out=False, v0=0.0, start=None, hinges=True):
        """A leaf from (u0, v0) or world `start`, toward its free end `free` (+/-u), turned into the room (away if out)."""
        t = math.radians(turn)
        du, dv = free * math.cos(t), (-1 if out else 1) * math.sin(t)
        wx, wy = du * ux + dv * nx, du * uy + dv * ny
        bx, by = start or (cx + u0 * ux + v0 * nx, cy + u0 * uy + v0 * ny)
        lo = {'id': obj['id'], 'center_m': (bx + wx * width / 2, by + wy * width / 2, cz),
              'yaw_degrees': math.degrees(math.atan2(wy, wx))}
        _box(lo, f'{name}-panel', mats, 'base', 0, 0, leaf_z, width, leaf_d, leaf_h)
        _frame_box(lo, f'{name}-molding', mats, 'light', 0, 0, leaf_z + leaf_h * 0.05, width * 0.64,
                   leaf_d + 0.012, leaf_h * 0.7, max(0.018, width * 0.04), max(0.018, leaf_h * 0.02))
        lever_x = width / 2 - min(0.09, width * 0.2)
        _box(lo, f'{name}-lever', mats, 'accent', lever_x, 0, leaf_z - leaf_h * 0.04, min(0.11, width * 0.3),
             leaf_d + 0.05, 0.02)
        for i, fz in enumerate((0.38, 0.0, -0.38) if hinges else ()):
            _box(lo, f'{name}-hinge-{i}', mats, 'accent', -width / 2 + 0.02, 0, leaf_z + leaf_h * fz,
                 0.04, leaf_d + 0.04, max(0.1, leaf_h * 0.07))
        return bx + wx * width, by + wy * width

    part('threshold', 'dark', 0, 0, -sz / 2 + thresh_h / 2, run, thick, thresh_h)
    part('frame-top', 'dark', 0, 0, sz / 2 - frame / 2, run, thick, frame)
    for side in (-1, 1):
        part(f'frame-{side}', 'dark', side * (run / 2 - frame / 2), 0, 0, frame, thick, sz)

    turn = DOOR_TURN.get(state, 0.0)
    shown = DOOR_SHOWN.get(state, 1.0)
    if opens in ('none', 'revolving') or state != 'closed':
        part('void', 'accent', 0, -thick * 0.2, leaf_z, leaf_w, max(0.01, thick * 0.4), leaf_h)

    if opens in ('inward', 'outward'):
        leaf('leaf', leaf_w, hs * leaf_w / 2, -hs, turn, opens == 'outward')
    elif opens in ('double-inward', 'double-outward'):
        for side in (-1, 1):
            leaf(f'leaf-{side}', leaf_w / 2, side * leaf_w / 2, -side, turn, opens == 'double-outward')
    elif opens == 'bifold':
        fold = min(turn, 85.0)
        end = leaf('fold-a', leaf_w / 2, hs * leaf_w / 2, -hs, fold)
        leaf('fold-b', leaf_w / 2, 0, -hs, fold, out=True, start=end, hinges=False)
    elif opens == 'sliding':
        shift = hs * leaf_w * (1 - shown)
        face = thick / 2 + leaf_d / 2 + 0.01
        part('track', 'dark', hs * leaf_w / 2, face, top + frame / 2, 2 * leaf_w + 2 * frame, 0.05, 0.05)
        leaf('leaf', leaf_w, shift - leaf_w / 2, 1, v0=face, hinges=False)
    elif opens == 'pocket' and shown:
        leaf('leaf', leaf_w * shown, -hs * leaf_w / 2, hs, hinges=False)
    elif opens == 'roll-up':
        h = leaf_h * shown
        if h:
            part('curtain', 'base', 0, 0, top - h / 2, leaf_w, leaf_d, h)
            for i in range(1, int(h / 0.12)):
                part(f'slat-{i}', 'dark', 0, leaf_d / 2, top - i * 0.12, leaf_w, 0.01, 0.012)
        part('drum', 'dark', 0, thick / 2 + 0.14, sz / 2 + 0.12, run, 0.26, 0.26)
    elif opens == 'up-and-over':
        a = {'closed': 0.0, 'ajar': 45.0}.get(state, 90.0)
        r = math.radians(a)
        part('panel', 'base', 0, leaf_h / 2 * math.sin(r), top - leaf_h / 2 * math.cos(r), leaf_w, leaf_d, leaf_h,
             pitch_x=s * a)
    elif opens == 'revolving':
        radius = leaf_w / 2
        _cyl(frame_obj, 'canopy', mats, 'dark', 0, 0, top + frame / 2, radius, frame)
        for wing in (45.0, 135.0):
            wo = {**frame_obj, 'yaw_degrees': frame_obj['yaw_degrees'] + wing}
            _box(wo, f'wing-{int(wing)}', mats, 'base', 0, 0, leaf_z, 2 * radius - 0.04, leaf_d, leaf_h)


def _pipe(obj, mats):
    sx, sy, sz = obj['size_m']
    r = min(sx, sz) / 2
    _cyl(obj, 'pipe', mats, 'base', 0, 0, 0, r * 0.84, sy, axis='Y')
    flange_t = max(0.018, min(0.05, sy * 0.04))
    n_joints = max(2, min(8, round(sy / 1.4) + 1))
    for i in range(n_joints):
        fy = -sy / 2 + flange_t / 2 + i * (sy - flange_t) / (n_joints - 1)
        _cyl(obj, f'flange-{i}', mats, 'dark', 0, fy, 0, r, flange_t, axis='Y')


def _tray(obj, mats):
    sx, sy, sz = obj['size_m']
    rail_t = max(0.014, min(sx, sz) * 0.14)
    flange_w = max(0.022, min(sx * 0.14, sz * 0.45))
    rail_h = max(0.035, sz)

    # C-channel side rails (web + top & bottom inward flanges)
    for dx in (-1, 1):
        wx = dx * (sx / 2 - rail_t / 2)
        fx = dx * (sx / 2 - flange_w / 2)
        _box(obj, f'web-{dx}', mats, 'dark', wx, 0, 0, rail_t, sy, rail_h)
        _box(obj, f'flange-top-{dx}', mats, 'dark', fx, 0, rail_h / 2 - rail_t / 2,
             flange_w, sy, rail_t)
        _box(obj, f'flange-bot-{dx}', mats, 'dark', fx, 0, -rail_h / 2 + rail_t / 2,
             flange_w, sy, rail_t)

    span = max(0.04, sx - 2 * rail_t)
    count = max(2, min(24, round(sy / 0.32)))
    rung = max(0.018, span * 0.045)
    for index in range(count):
        y = -sy / 2 + sy * (index + 0.5) / count
        _box(obj, f'rung-{index}', mats, 'base', 0, y, -rail_h / 2 + rail_t * 1.4,
             span, rung, max(0.014, rail_h * 0.22))


def _column(obj, mats):
    sx, sy, sz = obj['size_m']
    r = min(sx, sy) / 2
    plinth_h = max(0.03, sz * 0.06)
    cap_h = max(0.03, sz * 0.05)
    collar_h = max(0.018, sz * 0.025)
    shaft_h = max(0.06, sz - plinth_h - cap_h - 2 * collar_h)

    _chamfer_box(obj, 'plinth', mats, 'dark', 0, 0, -sz / 2 + plinth_h / 2,
                 sx * 0.98, sy * 0.98, plinth_h, bevel=0.008)
    _cyl(obj, 'base-collar', mats, 'dark', 0, 0, -sz / 2 + plinth_h + collar_h / 2,
         r * 0.90, collar_h)
    _cyl(obj, 'shaft', mats, 'base', 0, 0, 0, r * 0.78, shaft_h)
    _cyl(obj, 'neck-collar', mats, 'dark', 0, 0, sz / 2 - cap_h - collar_h / 2,
         r * 0.88, collar_h)
    _chamfer_box(obj, 'capital', mats, 'dark', 0, 0, sz / 2 - cap_h / 2,
                 sx, sy, cap_h, bevel=0.008)


def _vehicle(obj, mats):
    sx, sy, sz = obj['size_m']
    wheel_r = max(0.05, min(sz * 0.21, sy * 0.11))
    clearance = wheel_r * 0.42
    body_h = max(0.08, (sz - clearance) * 0.52)
    cabin_h = max(0.06, sz - clearance - body_h)
    body_z = -sz / 2 + clearance + body_h / 2

    # Tapered lower chassis (slightly narrower at the front nose -Y)
    _prism(obj, 'body', mats, 'base', 0, 0, body_z,
           sx * 0.94, sy * 0.94, sx * 0.90, sy * 0.92, body_h)

    # Front & rear bumpers + headlights
    bumper_h = max(0.03, body_h * 0.24)
    bumper_z = -sz / 2 + clearance + bumper_h * 0.6
    _chamfer_box(obj, 'bumper-f', mats, 'dark', 0, -sy / 2 + sy * 0.03, bumper_z,
                 sx * 0.95, max(0.03, sy * 0.06), bumper_h, bevel=0.008)
    _chamfer_box(obj, 'bumper-r', mats, 'dark', 0, sy / 2 - sy * 0.03, bumper_z,
                 sx * 0.95, max(0.03, sy * 0.06), bumper_h, bevel=0.008)
    for dx in (-1, 1):
        _box(obj, f'headlight-{dx}', mats, 'light',
             dx * (sx * 0.32), -sy * 0.47, body_z + body_h * 0.12,
             sx * 0.16, max(0.015, sy * 0.02), body_h * 0.20)

    # Sloped trapezoidal cabin greenhouse (windshield at -Y, roof, rear window at +Y)
    cabin_z = -sz / 2 + clearance + body_h + cabin_h / 2
    _prism(obj, 'cabin', mats, 'light', 0, sy * 0.06, cabin_z,
           sx * 0.86, sy * 0.58, sx * 0.74, sy * 0.34, cabin_h, shift_top_y=sy * 0.05)

    # 4 Wheels with hubcaps
    tire_w = max(0.035, sx * 0.11)
    for dx in (-1, 1):
        for dy in (-1, 1):
            wx = dx * (sx / 2 - tire_w / 2)
            wy = dy * (sy * 0.31)
            wz = -sz / 2 + wheel_r
            _cyl(obj, f'wheel-{dx}-{dy}', mats, 'dark', wx, wy, wz, wheel_r, tire_w, axis='X')
            _cyl(obj, f'rim-{dx}-{dy}', mats, 'light',
                 wx + dx * (tire_w * 0.52), wy, wz, wheel_r * 0.55, 0.01, axis='X')


def _crate(obj, mats):
    sx, sy, sz = obj['size_m']
    batten = max(0.022, min(sx, sy, sz) * 0.08)
    relief = max(0.008, min(sx, sy) * 0.02)

    # Recessed core box
    _box(obj, 'core', mats, 'base', 0, 0, 0,
         max(0.02, sx - 2 * relief), max(0.02, sy - 2 * relief), max(0.02, sz - 2 * relief))

    # Top, bottom, and corner framing battens
    _frame_box(obj, 'face-f', mats, 'dark', 0, -sy / 2 + batten / 2, 0, sx, batten, sz, batten, batten)
    _frame_box(obj, 'face-b', mats, 'dark', 0, sy / 2 - batten / 2, 0, sx, batten, sz, batten, batten)
    for dx in (-1, 1):
        _box(obj, f'side-top-{dx}', mats, 'dark', dx * (sx / 2 - batten / 2), 0, sz / 2 - batten / 2,
             batten, sy, batten)
        _box(obj, f'side-bot-{dx}', mats, 'dark', dx * (sx / 2 - batten / 2), 0, -sz / 2 + batten / 2,
             batten, sy, batten)

    # Diagonal cross-brace slat on front & back faces
    diag_len = math.hypot(max(0.02, sx - 2 * batten), max(0.02, sz - 2 * batten)) * 0.92
    diag_ang = math.degrees(math.atan2(max(0.02, sx - 2 * batten), max(0.02, sz - 2 * batten)))
    for dy in (-1, 1):
        _box(obj, f'diag-{dy}', mats, 'dark',
             0, dy * (sy / 2 - batten * 0.45), 0,
             batten * 0.9, batten * 0.85, diag_len, roll_y=diag_ang)


def _extinguisher(obj, mats):
    sx, sy, sz = obj['size_m']
    radius = min(sx, sy) / 2
    skirt_h = max(0.015, sz * 0.05)
    cyl_h = sz * 0.62
    dome_h = sz * 0.13
    head_h = max(0.03, sz - skirt_h - cyl_h - dome_h)

    _cyl(obj, 'skirt', mats, 'dark', 0, 0, -sz / 2 + skirt_h / 2, radius * 0.88, skirt_h)
    _cyl(obj, 'tank', mats, 'base', 0, 0, -sz / 2 + skirt_h + cyl_h / 2, radius * 0.86, cyl_h)
    _cone(obj, 'shoulder', mats, 'base', 0, 0, -sz / 2 + skirt_h + cyl_h + dome_h / 2,
          radius * 0.86, radius * 0.28, dome_h)

    neck_z = -sz / 2 + skirt_h + cyl_h + dome_h + head_h * 0.4
    _cyl(obj, 'valve', mats, 'dark', 0, 0, neck_z, radius * 0.24, head_h * 0.8)
    _cyl(obj, 'gauge', mats, 'light', 0, -radius * 0.28, neck_z,
         max(0.01, radius * 0.16), 0.012, axis='Y')
    _box(obj, 'lever-top', mats, 'dark', radius * 0.28, 0, sz / 2 - head_h * 0.18,
         radius * 0.95, radius * 0.22, head_h * 0.18, roll_y=-14.0)
    _box(obj, 'lever-bot', mats, 'dark', radius * 0.25, 0, sz / 2 - head_h * 0.42,
         radius * 0.85, radius * 0.20, head_h * 0.16)

    # Vertical side discharge hose & flared horn nozzle
    hose_x = radius * 0.90
    hose_h = cyl_h * 0.72
    _cyl(obj, 'hose', mats, 'dark', hose_x, 0, -sz / 2 + skirt_h + cyl_h * 0.55,
         max(0.008, radius * 0.10), hose_h)
    _cone(obj, 'nozzle', mats, 'dark', hose_x, 0, -sz / 2 + skirt_h + cyl_h * 0.16,
          max(0.015, radius * 0.22), max(0.009, radius * 0.11), cyl_h * 0.18)


def _plant(obj, mats):
    sx, sy, sz = obj['size_m']
    radius = min(sx, sy) / 2
    pot_h = sz * 0.30
    rim_h = max(0.018, pot_h * 0.16)

    _cone(obj, 'pot', mats, 'base', 0, 0, -sz / 2 + pot_h / 2,
          radius * 0.44, radius * 0.62, pot_h)
    _cyl(obj, 'pot-rim', mats, 'dark', 0, 0, -sz / 2 + pot_h - rim_h / 2,
         radius * 0.66, rim_h)
    _cyl(obj, 'soil', mats, 'accent', 0, 0, -sz / 2 + pot_h - rim_h * 0.4,
         radius * 0.58, rim_h * 0.4)

    # Central woody stem + angled branches
    stem_h = sz * 0.38
    _cyl(obj, 'stem', mats, 'dark', 0, 0, -sz / 2 + pot_h + stem_h * 0.4,
         max(0.01, radius * 0.08), stem_h)

    # Multi-tuft organic foliage canopy
    crown_r = radius * 0.46
    _sphere(obj, 'foliage-crown', mats, 'light', 0, 0, sz / 2 - crown_r, crown_r, subdivisions=1)
    tufts = [
        (0.42, 0.22, 0.12, 0.38, 'base'),
        (-0.40, 0.26, 0.08, 0.36, 'light'),
        (0.18, -0.44, 0.10, 0.37, 'light'),
        (-0.32, -0.34, 0.04, 0.35, 'base'),
        (0.05, 0.44, 0.06, 0.34, 'light'),
    ]
    for idx, (ox, oy, oz, tr, mat_key) in enumerate(tufts):
        r_tuft = radius * tr
        z_tuft = min(sz / 2 - r_tuft, sz * oz)
        _sphere(obj, f'foliage-{idx}', mats, mat_key,
                radius * ox, radius * oy, z_tuft, r_tuft, subdivisions=1)


def _patch(obj, mats):
    sx, sy, sz = obj['size_m']
    _chamfer_box(obj, 'patch', mats, 'base', 0, 0, 0, sx, sy, max(0.015, sz), bevel=0.005)


def _artwork(obj, mats):
    sx, sy, sz = obj['size_m']
    frame = max(0.025, min(sx, sz) * 0.07)
    mat_b = max(0.02, min(sx, sz) * 0.06)
    _frame_box(obj, 'frame', mats, 'dark', 0, 0, 0, sx, sy, sz, frame, frame)
    inner_w = max(0.04, sx - 2 * frame)
    inner_h = max(0.04, sz - 2 * frame)
    _frame_box(obj, 'matboard', mats, 'light', 0, 0, 0,
               inner_w, sy * 0.65, inner_h, mat_b, mat_b)
    _box(obj, 'canvas', mats, 'base', 0, 0, 0,
         max(0.02, inner_w - 2 * mat_b), sy * 0.45, max(0.02, inner_h - 2 * mat_b))


def _panel(obj, mats):
    sx, sy, sz = obj['size_m']
    _box(obj, 'enclosure', mats, 'dark', 0, sy * 0.08, 0, sx * 0.96, sy * 0.84, sz * 0.98)
    _chamfer_box(obj, 'door', mats, 'base', 0, -sy * 0.35, 0,
                 sx, max(0.012, sy * 0.30), sz, bevel=0.005)
    _box(obj, 'latch', mats, 'accent', sx * 0.38, -sy * 0.48, 0,
         max(0.015, sx * 0.04), max(0.01, sy * 0.12), max(0.04, sz * 0.12))


def _generic(obj, mats):
    sx, sy, sz = obj['size_m']
    if min(sx, sy) < 0.08 or sz < 0.1:
        _chamfer_box(obj, 'plate', mats, 'base', 0, 0, 0,
                     sx, sy, max(0.015, sz), bevel=0.005)
    elif abs(sx - sy) < 0.05 and min(sx, sy) < 0.6:
        cap_h = max(0.015, sz * 0.08)
        _cyl(obj, 'cylinder', mats, 'base', 0, 0, 0, sx / 2 * 0.96, sz)
        _cyl(obj, 'cap-bot', mats, 'dark', 0, 0, -sz / 2 + cap_h / 2, sx / 2, cap_h)
        _cyl(obj, 'cap-top', mats, 'dark', 0, 0, sz / 2 - cap_h / 2, sx / 2, cap_h)
    else:
        _chamfer_box(obj, 'mass', mats, 'base', 0, 0, 0, sx, sy, sz, bevel=0.012)


BUILDERS = {
    'table': _table,
    'counter': _counter,
    'chair': _chair,
    'shelf': _shelf,
    'cabinet': _cabinet,
    'monitor': _monitor,
    'batten': _batten,
    'lamp': _lamp,
    'window': _window,
    'door': _door,
    'pipe': _pipe,
    'tray': _tray,
    'column': _column,
    'vehicle': _vehicle,
    'crate': _crate,
    'extinguisher': _extinguisher,
    'bed': _bed,
    'sofa': _sofa,
    'plant': _plant,
    'artwork': _artwork,
    'patch': _patch,
    'panel': _panel,
}


def _spool(obj, mats):
    sx, sy, sz = obj['size_m']
    radius = min(sy, sz) / 2
    flange_t = max(0.018, sx * 0.08)
    _cyl(obj, 'core', mats, 'light', 0, 0, 0, radius * 0.68, max(0.02, sx - 2 * flange_t), axis='X')
    for dx in (-1, 1):
        fx = dx * (sx / 2 - flange_t / 2)
        _cyl(obj, f'flange-{dx}', mats, 'dark', fx, 0, 0, radius, flange_t, axis='X')
        _cyl(obj, f'hub-{dx}', mats, 'accent',
             dx * (sx / 2 - flange_t * 0.4), 0, 0, radius * 0.24, flange_t * 1.2, axis='X')


BUILDERS['spool'] = _spool


def _offset(origin, yaw, pitch, lx, ly, lz):
    """origin + R_z(yaw)·R_x(pitch)·(lx, ly, lz), angles in degrees."""
    x, y, z = _rotate_xyz(lx, ly, lz, pitch_x=pitch)
    a = math.radians(yaw)
    return (origin[0] + x * math.cos(a) - y * math.sin(a),
            origin[1] + x * math.sin(a) + y * math.cos(a),
            origin[2] + z)


# Local mannequin parts per posture: (name, (lx, ly, lz), (sx, sy, sz), material, pitch); +y is forward.
def _seated(c):
    return [('pelvis', (0, -0.02, c + 0.08), (0.36, 0.30, 0.16), 'base', 0),
            ('torso', (0, -0.07, c + 0.40), (0.40, 0.22, 0.50), 'base', 12),
            *[part for s in (-1, 1) for part in (
                (f'thigh-{s}', (s * 0.1, 0.2, c + 0.07), (0.15, 0.46, 0.14), 'base', 0),
                (f'shin-{s}', (s * 0.1, 0.43, c / 2), (0.12, 0.12, c + 0.04), 'dark', 0),
                (f'upper-arm-{s}', (s * 0.24, -0.08, c + 0.42), (0.09, 0.10, 0.30), 'base', 10),
                (f'forearm-{s}', (s * 0.2, 0.1, c + 0.24), (0.08, 0.30, 0.08), 'dark', 0))]]


def _upright(hip):
    """Standing (hip 0.95 m) or kneeling/crouching (hip ~0.55 m); torso and arms scale with the hip height."""
    return [('pelvis', (0, 0, hip), (0.36, 0.24, 0.18), 'base', 0),
            ('torso', (0, 0, hip + 0.32), (0.40, 0.22, 0.52), 'base', 0),
            *[part for s in (-1, 1) for part in (
                (f'leg-{s}', (s * 0.1, 0, (hip - 0.09) / 2), (0.13, 0.14, hip - 0.09), 'dark', 0),
                (f'arm-{s}', (s * 0.25, 0, hip + 0.23), (0.09, 0.10, 0.62), 'base', 0))]]


def _lying(z):
    return [('torso', (0, -0.4, z), (0.40, 0.55, 0.22), 'base', 0),
            *[(f'leg-{s}', (s * 0.1, -1.05, z - 0.03), (0.14, 0.85, 0.14), 'dark', 0) for s in (-1, 1)]]


def build_mannequin(occ, seat_z=0.45):
    """Coloured stand-in for an actor; returns the created objects. occ: id/seat, color (linear rgb), hip [x, y],
    head [x, y, z], yaw_pitch (head; yaw 0 = +y), body_yaw, posture, hidden."""
    if occ.get('hidden'):
        return []
    key = occ.get('id') or occ['seat']
    rgb = tuple(occ['color'])
    mats = {'base': _make_material(f'm-{key}', rgb), 'dark': _make_material(f'm-{key}-dark', _shade(rgb, 0.45))}
    visor = _make_material(f'm-{key}-visor', (0.02, 0.02, 0.025))
    x, y = occ['hip']
    body_yaw = occ.get('body_yaw', 0.0)
    posture = occ.get('posture', 'seated')
    head = occ['head']
    parts = (_seated(seat_z) if posture == 'seated' else _lying(head[2]) if posture == 'lying'
             else _upright(0.95 if posture == 'standing' else 0.55))
    made = []
    for name, local, size, mat, pitch in parts:
        verts, faces = _chamfer_geom(*size, bevel=0.012, pitch_x=pitch)
        made.append(_link_mesh_object(f'{key}-{name}', verts, faces, _offset((x, y, 0), body_yaw, 0, *local),
                                      mats[mat], body_yaw))
    if posture != 'lying':
        verts, faces = _frustum_geom(0.05, 0.05, 0.10, segments=24)
        seated = posture == 'seated'
        neck = _offset((x, y, 0), body_yaw, 0, 0, -0.11 if seated else 0, seat_z + 0.60 if seated else head[2] - 0.12)
        made.append(_link_mesh_object(f'{key}-neck', verts, faces, neck, mats['base']))
    verts, faces = _icosphere_geom(0.105, subdivisions=2)
    made.append(_link_mesh_object(f'{key}-head', verts, faces, head, mats['base']))
    yaw, pitch = occ['yaw_pitch']
    for name, offset, size in (('visor', (0, 0.08, 0.015), (0.17, 0.06, 0.075)),
                               ('nose', (0, 0.11, -0.035), (0.04, 0.06, 0.06))):
        verts, faces = _chamfer_geom(*size, bevel=0.006, pitch_x=-pitch)
        made.append(_link_mesh_object(f'{key}-{name}', verts, faces, _offset(head, yaw, -pitch, *offset),
                                      visor if name == 'visor' else mats['dark'], yaw))
    return made


def _build_objects(spec):
    CREATED.clear()
    materials = {}
    for obj in spec['objects']:
        category = obj['category']
        if category not in materials:
            rgb = obj['color']
            materials[category] = {
                'base': _make_material(f'{category}-base', rgb),
                'dark': _make_material(f'{category}-dark', _shade(rgb, 0.56)),
                'light': _make_material(f'{category}-light', _shade(rgb, 1.32)),
                'accent': _make_material(f'{category}-accent', _shade(rgb, 0.36)),
            }
    for obj in spec['objects']:
        BUILDERS.get(obj['category'], _generic)(obj, materials[obj['category']])


def _build_room(spec):
    width, depth, height = spec['room_m']
    wall_mat = _make_material('room-wall', (0.64, 0.63, 0.60))
    floor_mat = _make_material('room-floor', (0.48, 0.47, 0.44))
    wall = 0.06
    if spec.get('outdoor'):
        _add_box('ground', (width / 2, depth / 2, -wall / 2), (width + 40, depth + 40, wall), floor_mat)
        return
    _add_box('floor', (width / 2, depth / 2, -wall / 2), (width, depth, wall), floor_mat)
    _add_box('ceiling', (width / 2, depth / 2, height + wall / 2),
             (width, depth, wall), wall_mat)
    _add_box('left-wall', (-wall / 2, depth / 2, height / 2),
             (wall, depth, height), wall_mat)
    _add_box('right-wall', (width + wall / 2, depth / 2, height / 2),
             (wall, depth, height), wall_mat)
    _add_box('far-wall', (width / 2, depth + wall / 2, height / 2),
             (width, wall, height), wall_mat)

    door_width = min(0.9, width * 0.6)
    door_height = min(2.1, height * 0.8)
    side_width = (width - door_width) / 2
    _add_box('entrance-wall-left', (side_width / 2, -wall / 2, height / 2),
             (side_width, wall, height), wall_mat)
    _add_box('entrance-wall-right', (width - side_width / 2, -wall / 2, height / 2),
             (side_width, wall, height), wall_mat)
    if height > door_height:
        _add_box('entrance-wall-lintel', (width / 2, -wall / 2, (door_height + height) / 2),
                 (door_width, wall, height - door_height), wall_mat)


def contains(obj, point, pad=0.02):
    """True when the camera sits inside this object's oriented box."""
    dx = point[0] - obj['center_m'][0]
    dy = point[1] - obj['center_m'][1]
    dz = point[2] - obj['center_m'][2]
    angle = math.radians(obj['yaw_degrees'])
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    local_x = dx * cos_a + dy * sin_a
    local_y = -dx * sin_a + dy * cos_a
    sx, sy, sz = obj['size_m']
    return (abs(local_x) <= sx / 2 + pad
            and abs(local_y) <= sy / 2 + pad
            and abs(dz) <= sz / 2 + pad)


GREYS = {
    'shell': 0.58, 'trim': 0.46, 'seat': 0.34, 'dash': 0.27, 'wheel': 0.12, 'ground': 0.80,
}


def _car_materials():
    return {name: (v, v, v) for name, v in GREYS.items()}


def _car_box(name, center, size, mat, pitch=0.0, yaw=0.0, bevel=0.012):
    verts, faces = _chamfer_geom(*size, bevel=bevel, pitch_x=pitch)
    return _link_mesh_object(name, verts, faces, center, mat, yaw)


def _car_slanted(name, bottom, top, x, width, depth, mat):
    (y0, z0), (y1, z1) = bottom, top
    length = math.hypot(y1 - y0, z1 - z0)
    pitch = math.degrees(math.atan2(y0 - y1, z1 - z0))  # +pitch leans the top toward −y
    return _car_box(name, (x, (y0 + y1) / 2, (z0 + z1) / 2), (width, depth, length), mat, pitch=pitch, bevel=0.006)


def _car_cylinder(name, center, radius, depth, axis, mat, pitch=0.0):
    verts, faces = _frustum_geom(radius, radius, depth, segments=24, axis=axis)
    if pitch:
        verts = [_rotate_xyz(*v, pitch_x=pitch) for v in verts]
    return _link_mesh_object(name, verts, faces, center, mat)


def _build_cabin(spec, mats):
    b = spec['body']
    hw = b['half_width'] + 0.06
    front = b['dash_y'] + 0.25           # windshield base / firewall
    ws_top = b['dash_y'] - 0.35          # windshield top edge on the roof
    rear = b['rear_wall_y']
    sedan = b['trunk_len'] > 0
    roof_end = rear + (0.45 if sedan else 0.05)
    belt, roof, c = b['belt_z'], b['roof_z'], b['cushion_z']

    _car_box('floor', (0, (front + rear) / 2, -0.03), (2 * hw, front - rear, 0.06), mats['trim'])
    for sign, side in ((-1, 'left'), (1, 'right')):
        x = sign * hw
        _car_box(f'door-{side}', (x, (front + rear) / 2, belt / 2), (0.06, front - rear, belt), mats['shell'])
        _car_slanted(f'a-pillar-{side}', (front, belt), (ws_top, roof), x - sign * 0.03, 0.07, 0.09, mats['shell'])
        pillars = [-0.45] + ([(b['rear_y'] + b['third_y']) / 2] if b['third_y'] is not None else [])
        for i, y in enumerate(pillars):
            _car_box(f'pillar-{i}-{side}', (x, y, (belt + roof) / 2), (0.07, 0.12, roof - belt), mats['shell'])
        if sedan:
            _car_slanted(f'c-pillar-{side}', (rear, belt), (roof_end, roof), x - sign * 0.03, 0.07, 0.22, mats['shell'])
        else:
            _car_box(f'd-pillar-{side}', (x - sign * 0.02, rear + 0.1, (belt + roof) / 2), (0.1, 0.2, roof - belt), mats['shell'])
    _car_box('roof', (0, (ws_top + roof_end) / 2, roof + 0.03), (2 * hw, ws_top - roof_end, 0.06), mats['shell'])
    _car_box('rear-wall', (0, rear, belt / 2), (2 * hw, 0.08, belt), mats['shell'])
    if not sedan:
        _car_box('tailgate-header', (0, rear, roof - 0.04), (2 * hw, 0.08, 0.08), mats['shell'])

    _car_box('dashboard', (0, b['dash_y'] + 0.13, (0.45 + belt + 0.12) / 2), (2 * b['half_width'], 0.26, belt + 0.12 - 0.45), mats['dash'])
    driver_x = spec['seats']['driver'][0]
    _car_box('instrument-hood', (driver_x, b['dash_y'] + 0.05, belt + 0.15), (0.42, 0.14, 0.08), mats['dash'])
    wheel_c = (driver_x, b['dash_y'] - 0.14, belt + 0.04)
    _car_cylinder('steering-wheel', wheel_c, 0.19, 0.035, 'Y', mats['wheel'], pitch=-25)
    _car_cylinder('steering-hub', wheel_c, 0.06, 0.07, 'Y', mats['dash'], pitch=-25)
    _car_box('console', (0, (b['dash_y'] - 0.25) / 2, 0.28), (0.24, b['dash_y'] + 0.25, 0.5), mats['dash'])

    for seat in ('driver', 'front-passenger'):
        x, y = spec['seats'][seat]
        _car_box(f'{seat}-pedestal', (x, y, (c - 0.12) / 2), (0.40, 0.42, c - 0.12), mats['trim'])
        _car_box(f'{seat}-cushion', (x, y + 0.02, c - 0.06), (0.52, 0.52, 0.12), mats['seat'])
        _car_box(f'{seat}-back', (x, y - 0.25, c + 0.30), (0.52, 0.13, 0.64), mats['seat'], pitch=14)
        _car_box(f'{seat}-headrest', (x, y - 0.35, c + 0.74), (0.27, 0.11, 0.20), mats['seat'], pitch=10)
    for row, y in (('rear', b['rear_y']), ('third', b['third_y'])):
        if y is None:
            continue
        width = 2 * b['rear_x'] + 0.52
        _car_box(f'{row}-base', (0, y, (c - 0.12) / 2), (width, 0.48, c - 0.12), mats['trim'])
        _car_box(f'{row}-cushion', (0, y + 0.02, c - 0.06), (width, 0.52, 0.12), mats['seat'])
        _car_box(f'{row}-back', (0, y - 0.27, c + 0.30), (width, 0.13, 0.64), mats['seat'], pitch=14)
        for lateral, x in (('left', -b['rear_x']), ('center', 0.0), ('right', b['rear_x'])):
            _car_box(f'{row}-{lateral}-headrest', (x, y - 0.37, c + 0.74), (0.25, 0.10, 0.18), mats['seat'], pitch=10)

    hood = b['hood_len']
    _car_box('hood', (0, front + hood / 2, (belt + 0.02 - 0.05) / 2), (2 * hw, hood, belt + 0.07), mats['shell'])
    if sedan:
        _car_box('trunk', (0, rear - b['trunk_len'] / 2, (belt - 0.05) / 2), (2 * hw, b['trunk_len'], belt + 0.05), mats['shell'])
    tail = rear - b['trunk_len']
    _car_box('skirt', (0, (front + hood + tail) / 2, -0.2), (2 * hw, front + hood - tail, 0.34), mats['shell'])
    for y in (front + hood * 0.45, b['rear_y'] - 0.35):
        for sign in (-1, 1):
            _car_cylinder(f'wheel-{y:.2f}-{sign}', (sign * (hw + 0.01), y, -0.28), 0.36, 0.26, 'X', mats['wheel'])
    _car_box('road', (0, 0, -0.66), (40, 60, 0.02), mats['ground'], bevel=0)


def _view(view: dict, clip: float | None) -> View:
    target = view.get('target_m') or [view['position_m'][0] + view['forward'][0],
                                      view['position_m'][1] + view['forward'][1], view['position_m'][2]]
    return View(tuple(view['position_m']), tuple(target), view['hfov_degrees'], view['width_px'], view['height_px'], clip)


def room_scenes(spec: dict) -> list[Scene]:
    """One scene per spec view: the room, its objects minus those culled for that camera, the view's mannequins."""
    with _collect() as base:
        _build_room(spec)
        _build_objects(spec)
        for oid, meshes in CREATED.items():  # CREATED is module state: read it under the same lock
            for mesh in meshes:
                mesh.group = oid
    scenes = []
    for view in spec['views']:
        hidden = set(view.get('culled_ids', ())) | {o['id'] for o in spec['objects'] if contains(o, view['position_m'])}
        with _collect() as actors:
            for occ in view.get('mannequins', []):
                build_mannequin(occ, occ.get('seat_z', 0.45))
        scenes.append(Scene([m for m in base if m.group not in hidden] + actors, _view(view, view.get('clip_start_m')),
                            bool(spec.get('outdoor'))))
    return scenes


def car_scene(job: dict) -> Scene:
    with _collect() as meshes:
        _build_cabin(job, _car_materials())
        for occ in job['occupants']:
            build_mannequin(occ, job['body']['cushion_z'])
    cam = job['camera']
    return Scene(meshes, View(tuple(cam['position']), tuple(cam['target']), cam['hfov'],
                              job['width_px'], job['height_px'], 0.04))
