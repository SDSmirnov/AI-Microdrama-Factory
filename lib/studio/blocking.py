"""Pinhole camera shared by car and room blocking: framing, projection, frame side, facing. Units: metres."""
import math
import os
from dataclasses import dataclass

def blocking_mode() -> str:
    """AI_BLOCKING (AI_CAR_BLOCKING still read): sketch (block + Blender sketch, default) | text (block only) | off."""
    mode = (os.getenv('AI_BLOCKING') or os.getenv('AI_CAR_BLOCKING') or 'sketch').strip().lower()
    return mode if mode in ('sketch', 'text', 'off') else 'sketch'


# Subject width (m) a tight scale fits across the frame's short side.
SCALE_FRAME_M = {'ECU': 0.14, 'CU': 0.32, 'MCU': 0.5, 'MS': 0.8}


@dataclass(frozen=True)
class Camera:
    position: tuple[float, float, float]
    target: tuple[float, float, float]
    hfov: float          # horizontal, degrees
    vfov: float
    hidden_seat: str | None = None   # POV owner: the camera sits in their head


def _scale_fov(fov: float, ratio: float) -> float:
    return math.degrees(2 * math.atan(math.tan(math.radians(fov) / 2) * ratio))


def frame_fovs(fov: float, aspect: tuple[int, int], axis: str) -> tuple[float, float]:
    """(hfov, vfov) with `fov` on axis 'h' (wide shots: people run across both 9:16 and 16:9)
    or 'short' (tight scales: a CU fills the short side)."""
    w, h = aspect
    if axis == 'short' and w > h:
        return _scale_fov(fov, w / h), fov
    return fov, _scale_fov(fov, h / w)


def parse_aspect(aspect: str) -> tuple[int, int]:
    try:
        w, h = (int(p) for p in aspect.split(':'))
        return (w, h) if w > 0 and h > 0 else (9, 16)
    except (ValueError, AttributeError):
        return 9, 16


def scale_of(panel: dict) -> str:
    raw = (panel.get('scale') or (panel.get('drama_requirements') or {}).get('shot_scale') or '').upper()
    return next((k for k in ('ECU', 'MCU', 'CU', 'MS') if raw.startswith(k) or f'({k})' in raw), 'WS')


def tight_fov(fov: float, aspect: tuple[int, int], scale: str, distance: float) -> tuple[float, float]:
    """(hfov, vfov) narrowed so the scale's subject width fills the short side, never wider than `fov`."""
    mount_short = min(frame_fovs(fov, aspect, 'h'))
    tight = math.degrees(2 * math.atan(SCALE_FRAME_M[scale] / 2 / max(0.2, distance)))
    return frame_fovs(max(8.0, min(mount_short, tight)), aspect, 'short')


def basis(cam: Camera):
    f = [t - p for t, p in zip(cam.target, cam.position)]
    n = math.sqrt(sum(c * c for c in f)) or 1.0
    f = [c / n for c in f]
    r = [f[1], -f[0], 0.0]  # f × z_up
    rn = math.hypot(r[0], r[1])
    r = [c / rn for c in r] if rn > 1e-6 else [1.0, 0.0, 0.0]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    return f, r, u


def project(cam: Camera, point) -> tuple[float, float, float]:
    """(img_x, img_y, depth): img in [0,1] when on frame, img_y = 0 at the top. Matches Blender's camera."""
    f, r, u = basis(cam)
    d = [p - c for p, c in zip(point, cam.position)]
    z = sum(a * b for a, b in zip(d, f))
    if z <= 1e-6:
        return math.nan, math.nan, z
    x = sum(a * b for a, b in zip(d, r)) / z
    y = sum(a * b for a, b in zip(d, u)) / z
    tx, ty = math.tan(math.radians(cam.hfov) / 2), math.tan(math.radians(cam.vfov) / 2)
    return 0.5 + x / (2 * tx), 0.5 - y / (2 * ty), z


def lateral(cam: Camera, point) -> str | None:
    """frame-left/right, on or off frame; None behind the camera."""
    f, r, _ = basis(cam)
    d = [p - c for p, c in zip(point, cam.position)]
    if sum(a * b for a, b in zip(d, f)) <= 0:
        return None
    return 'frame-right' if sum(a * b for a, b in zip(d, r)) > 0 else 'frame-left'


def facing(cam: Camera, head, face_xy) -> str:
    """How a head turned along face_xy reads in this camera."""
    to_cam = [c - h for c, h in zip(cam.position, head)]
    n = math.hypot(to_cam[0], to_cam[1]) or 1.0
    fn = math.hypot(*face_xy) or 1.0
    cos_a = (face_xy[0] * to_cam[0] + face_xy[1] * to_cam[1]) / n / fn
    _, r, _ = basis(cam)
    side = 'frame-right' if face_xy[0] * r[0] + face_xy[1] * r[1] > 0 else 'frame-left'
    if cos_a > 0.87:
        return 'face toward the camera'
    if cos_a > 0.34:
        return f'three-quarter toward the camera, turned to {side}'
    if cos_a > -0.34:
        return f'in profile, facing {side}'
    if cos_a > -0.87:
        return f'three-quarter from behind, turned to {side}'
    return 'back of the head to the camera'


def placement(cam: Camera, head, chest, bands=(0.75, 1.6)) -> tuple[str, bool, bool]:
    """(text, visible, head in frame); bands = foreground / mid-ground depth limits in metres."""
    h, c = project(cam, head), project(cam, chest)
    on = lambda p: p[2] > 0 and -0.02 <= p[0] <= 1.02 and -0.02 <= p[1] <= 1.02  # noqa: E731
    if not on(h) and not on(c):
        return f"out of frame{' (beside or behind the camera)' if h[2] <= 0 else ''}", False, False
    p = h if on(h) else c
    side = 'frame-left' if p[0] < 0.38 else 'frame-right' if p[0] > 0.62 else 'frame-center'
    depth = 'foreground' if p[2] < bands[0] else 'mid-ground' if p[2] < bands[1] else 'background'
    part = '' if on(h) else ' (body only, head cut by the frame)'
    return f'{side}, {depth}, {p[2]:.1f} m from the lens{part}', True, on(h)


def equivalent_focal_mm(cam: Camera) -> int:
    """Full-frame equivalent focal length for the frame's short side (24 mm)."""
    return round(12 / math.tan(math.radians(min(cam.hfov, cam.vfov)) / 2))
