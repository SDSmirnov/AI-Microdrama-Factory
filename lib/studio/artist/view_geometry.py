"""View geometry: room dimensions, aspect ratios, camera rigs, projection."""
import math
import re

from lib.studio.artist.view_catalog import _OUTDOOR_VIEW_SUFFIXES, _X_AXIS_VIEWS, _Y_AXIS_VIEWS
from lib.studio.room_geometry import (
    CAMERA_HEIGHT_M, FALLBACK_ROOM_HEIGHT_M, WALL_INSET_M,
)


def _parse_room_dims(visual_desc: str) -> tuple[float, float] | None:
    """Extract (width_m, depth_m) from visual_desc text.

    Prefers explicitly labelled phrases ('4m wide', '7m deep') because unlabelled
    'NxM' patterns give no hint about which axis is width vs depth.
    Returns None when dimensions cannot be reliably parsed.
    """
    desc = visual_desc.lower()
    mw = re.search(r'(\d+(?:\.\d+)?)\s*m(?:eters?)?\s+(?:wide|width|across)', desc)
    md = re.search(r'(\d+(?:\.\d+)?)\s*m(?:eters?)?\s+(?:deep|depth|long|length)', desc)
    if mw and md:
        return float(mw.group(1)), float(md.group(1))
    # Unlabelled NxM — treat first as width, second as depth only as last resort
    m = re.search(r'(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*m', desc)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


# Ratios the image backends accept (Gemini ImageConfig). Room views are not
# framed to the film's 9:16/16:9 target: each view targets the physical
# cross-section of the wall it faces and snaps to the nearest supported value.
_SUPPORTED_IMAGE_ASPECTS: tuple[tuple[str, float], ...] = (
    ('1:1', 1.0),
    ('3:2', 3.0 / 2.0),
    ('4:3', 4.0 / 3.0),
    ('16:9', 16.0 / 9.0),
    ('21:9', 21.0 / 9.0),
    ('2:3', 2.0 / 3.0),
    ('3:4', 3.0 / 4.0),
    ('9:16', 9.0 / 16.0),
)


def _nearest_supported_aspect(target: float) -> str:
    """Snap a physical aspect ratio to the closest backend-supported one."""
    if not math.isfinite(target) or target <= 0:
        return '1:1'
    return min(
        _SUPPORTED_IMAGE_ASPECTS,
        key=lambda item: abs(math.log(target / item[1])),
    )[0]


def _room_view_aspect_ratio(view_suffix: str, dims: tuple[float, float] | None,
                            room_height: float) -> float | None:
    """Physical horizontal:vertical ratio of the wall this view faces.

    Y-axis views see the room width across the frame; X-axis views see the
    room depth. The ceiling height is the vertical extent. Returns None when
    the view or dimensions are unknown.
    """
    if dims is None or room_height <= 0:
        return None
    width, depth = dims
    if view_suffix in _Y_AXIS_VIEWS:
        horizontal = width
    elif view_suffix in _X_AXIS_VIEWS:
        horizontal = depth
    else:
        return None
    return horizontal / room_height


def _view_aspect_ratio(view_suffix: str, dims: tuple[float, float] | None, config: dict,
                       room_height: float | None = None) -> str:
    """Choose image aspect ratio for a room view from physical room dimensions.

    Y-axis views (entrance/far-wall cameras): horizontal span = room width.
    X-axis views (left/right-wall cameras): horizontal span = room depth.
    Vertical span = ceiling height. The result is snapped to the nearest ratio
    the image backend supports, so room views are never forced to the film's
    9:16 or 16:9 target. Falls back to config ref_aspect_ratio only when the
    room dimensions are unavailable.
    """
    fallback = config.get('reference_characters', {}).get('ref_aspect_ratio', '3:4')
    if view_suffix in _OUTDOOR_VIEW_SUFFIXES:  # no ceiling to shape the frame: a landscape plate like a location scout's
        return OUTDOOR_ASPECT
    target = _room_view_aspect_ratio(
        view_suffix,
        dims,
        room_height if room_height is not None else FALLBACK_ROOM_HEIGHT_M,
    )
    if target is None:
        return fallback
    return _nearest_supported_aspect(target)


# Camera position (cx, cy) and forward direction (fdx, fdy) per view, in normalised room coords.
_VIEW_CAMERA: dict[str, tuple[float, float, float, float]] = {
    'View-From-Entrance':      (0.5, 0.02,  0.0, +1.0),
    'View-To-Entrance':        (0.5, 0.98,  0.0, -1.0),
    'View-From-Left-Wall':     (0.02, 0.5, +1.0,  0.0),
    'View-From-Right-Wall':    (0.98, 0.5, -1.0,  0.0),
    'View-Center-To-Far':      (0.5, 0.5,   0.0, +1.0),
    'View-Center-To-Entrance': (0.5, 0.5,   0.0, -1.0),
    'View-By-Far-Wall':        (0.5, 0.85,  0.0, +1.0),
    'View-By-Entrance':        (0.5, 0.15,  0.0, -1.0),
    'View-Primary':            (0.5, 0.5,   0.0, +1.0),   # outdoor: one station, four headings
    'View-Opposite':           (0.5, 0.5,   0.0, -1.0),
    'View-Ortho-Primary':      (0.5, 0.5,  +1.0,  0.0),
    'View-Ortho-Opposite':     (0.5, 0.5,  -1.0,  0.0),
}


def view_camera(view_suffix: str, anchor_points: dict | None = None) -> tuple[float, float, float, float]:
    """(x, y, forward_x, forward_y) of a view's camera, normalized; outdoor views stand at the anchors' station."""
    cx, cy, fdx, fdy = _VIEW_CAMERA[view_suffix]
    station = (anchor_points or {}).get('station')
    if (view_suffix in _OUTDOOR_VIEW_SUFFIXES and isinstance(station, (list, tuple)) and len(station) == 2
            and all(isinstance(v, (int, float)) and 0 <= v <= 1 for v in station)):
        cx, cy = map(float, station)
    return cx, cy, fdx, fdy


def _is_wall_camera(cx: float, cy: float) -> bool:
    """True when a canonical view camera stands on a wall plane.

    Only these cameras get the 0.5 m inset. Center and By-* cameras are
    already defined by their distance from a wall; shifting them would move
    the shot instead of clearing wall-mounted furniture.
    """
    return min(cx, cy, 1.0 - cx, 1.0 - cy) <= 0.025


def _project_image_x(obj_x: float, obj_y: float, view_suffix: str) -> float:
    """Return normalised image-x [0=image-left, 1=image-right] for an object at (obj_x, obj_y)."""
    if view_suffix in ('View-To-Entrance', 'View-Center-To-Entrance', 'View-By-Entrance', 'View-Opposite'):
        return 1.0 - obj_x
    if view_suffix in ('View-From-Left-Wall', 'View-Ortho-Primary'):
        # entrance-side (low Y) → image-right; far-side (high Y) → image-left
        return 1.0 - obj_y
    if view_suffix in ('View-From-Right-Wall', 'View-Ortho-Opposite'):
        # entrance-side (low Y) → image-left; far-side (high Y) → image-right
        return obj_y
    return obj_x  # View-From-Entrance, View-Center-To-Far, View-By-Far-Wall — no mirror


_VIEW_POSITION_LABEL: dict[str, str] = {
    'View-From-Entrance':      'standing at entrance doorway (y=0)',
    'View-To-Entrance':        'standing at far wall (y=1), facing entrance',
    'View-From-Left-Wall':     'at image-left wall (x=0), looking across room',
    'View-From-Right-Wall':    'at image-right wall (x=1), looking across room',
    'View-Center-To-Far':      'at room center, facing far wall',
    'View-Center-To-Entrance': 'at room center, facing entrance',
    'View-By-Far-Wall':        '1m from far wall (y≈0.85), facing far wall — close-up',
    'View-By-Entrance':        '1m from entrance (y≈0.15), facing entrance — close-up',
    'View-Primary':            'at the station, facing the primary direction (toward y=1)',
    'View-Opposite':           'at the station, facing back (toward y=0)',
    'View-Ortho-Primary':      'at the station, turned 90° right of the primary direction (toward x=1)',
    'View-Ortho-Opposite':     'at the station, turned 90° left of the primary direction (toward x=0)',
}


_VIEW_FACING_WALL: dict[str, str] = {
    'View-From-Entrance':      'far wall  (looking toward y=1)',
    'View-To-Entrance':        'entrance wall  (looking toward y=0)',
    'View-From-Left-Wall':     'image-right wall  (looking toward x=1)',
    'View-From-Right-Wall':    'image-left wall  (looking toward x=0)',
    'View-Center-To-Far':      'far wall  (looking toward y=1)',
    'View-Center-To-Entrance': 'entrance wall  (looking toward y=0)',
    'View-By-Far-Wall':        'far wall  (looking toward y=1)',
    'View-By-Entrance':        'entrance wall  (looking toward y=0)',
    'View-Primary':            'far end  (looking toward y=1)',
    'View-Opposite':           'near end  (looking toward y=0)',
    'View-Ortho-Primary':      'right side  (looking toward x=1)',
    'View-Ortho-Opposite':     'left side  (looking toward x=0)',
}


# Horizontal FOV in degrees; wide-angle for by-wall close shots.
# Outdoor lenses on the 16:9 plate: along the street a 28 mm (65°) shows both sidewalks receding;
# across it a 40 mm (48°) holds the facade square without wide-angle stretch.
OUTDOOR_ASPECT = '16:9'
_OUTDOOR_HFOV = {'View-Primary': 65, 'View-Opposite': 65, 'View-Ortho-Primary': 48, 'View-Ortho-Opposite': 48}

_VIEW_HFOV: dict[str, int] = {
    'View-From-Entrance':      90,
    'View-To-Entrance':        90,
    'View-From-Left-Wall':     90,
    'View-From-Right-Wall':    90,
    'View-Center-To-Far':      75,
    'View-Center-To-Entrance': 75,
    'View-By-Far-Wall':        110,
    'View-By-Entrance':        110,
}


# Wall-facing room views size the lens to frame the opposite wall, like the
# physical aspect ratio does: 90° (18 mm full-frame) down a narrow room forced
# the perspective and blew up near furniture; under 60° (31 mm) the room's
# sides drop out. By-* close shots keep their fixed wide lens. The margin keeps
# the wall's corners and floor line in frame: the camera stands at 1.55 m, above
# the wall's mid-height, so an exact fit cuts the floor off.
_FIT_HFOV_RANGE = (60.0, 90.0)


_FIT_MARGIN = 1.15


# Wall views: the cut WALL_INSET_M into the room fixes what is hidden; the
# camera stands behind that cut as far as a natural lens needs to frame the
# opposite wall. Narrow rooms put it outside the room, as on a film set with the
# fourth wall removed, instead of forcing a wide lens close to the far wall.
NATURAL_HFOV = 55.0   # ≈35 mm full-frame


MAX_SETBACK_M = 3.0   # behind the wall; past it the lens widens instead


def _view_rig(view_suffix: str, room_m=None, room_h: float | None = None) -> tuple[float, float]:
    """(hfov_degrees, back_m) for a room view; back_m = camera distance behind the cut plane.

    Non-wall views (center, By-*, outdoor) keep their lens and stand at their
    canonical position (back_m = 0).
    """
    camera = _VIEW_CAMERA.get(view_suffix)
    if (view_suffix not in _VIEW_HFOV or not camera or not _is_wall_camera(*camera[:2])
            or not isinstance(room_m, (list, tuple)) or len(room_m) < 2):
        return _view_hfov(view_suffix, room_m), 0.0
    if view_suffix == 'View-From-Entrance':  # the inventory master: whole room from the doorway, as VFE renders look
        return _FIT_HFOV_RANGE[1], WALL_INSET_M
    width, depth = float(room_m[0]), float(room_m[1])
    room_h = room_h or FALLBACK_ROOM_HEIGHT_M
    cx, cy, fdx, fdy = camera
    span, extent, near = ((width, depth, cy if fdy > 0 else 1 - cy) if fdy
                          else (depth, width, cx if fdx > 0 else 1 - cx))
    available = extent * (1 - near) - WALL_INSET_M  # cut plane → opposite wall
    if span <= 0 or available <= 0:
        return _view_hfov(view_suffix, room_m, WALL_INSET_M), 0.0
    aw, ah = (int(part) for part in _view_aspect_ratio(view_suffix, (width, depth), {}, room_h).split(':'))
    # tan(hfov/2) × distance the frame must cover: the wall's width, and its
    # height around the eye (converted to the horizontal through the aspect).
    reach = max(span / 2, max(CAMERA_HEIGHT_M, room_h - CAMERA_HEIGHT_M) * aw / ah) * _FIT_MARGIN

    def lens(back: float) -> float:
        fit = math.degrees(2 * math.atan(reach / (available + back)))
        return min(_FIT_HFOV_RANGE[1], max(NATURAL_HFOV, fit))

    back = min(max(0.0, reach / math.tan(math.radians(NATURAL_HFOV) / 2) - available),
               MAX_SETBACK_M + WALL_INSET_M)
    # The floor before the cut is cut away too: the lowest ray must land past it.
    while back > 0 and CAMERA_HEIGHT_M * aw / ah / math.tan(math.radians(lens(back)) / 2) < back:
        back = max(0.0, back - 0.1)
    return round(lens(back), 1), round(back, 2)


def _view_hfov(view_suffix: str, room_m=None, inset_m: float = 0.0) -> float:
    """Horizontal FOV for a room view; the _VIEW_HFOV value without room dimensions."""
    if view_suffix in _OUTDOOR_HFOV:
        return _OUTDOOR_HFOV[view_suffix]
    fixed = _VIEW_HFOV.get(view_suffix, 90)
    camera = _VIEW_CAMERA.get(view_suffix)
    if (view_suffix not in _VIEW_HFOV or view_suffix.startswith('View-By-') or not camera
            or not isinstance(room_m, (list, tuple)) or len(room_m) < 2):
        return fixed
    width, depth = float(room_m[0]), float(room_m[1])
    cx, cy, fdx, fdy = camera
    span, distance = ((width, depth * (1 - cy if fdy > 0 else cy)) if fdy
                      else (depth, width * (1 - cx if fdx > 0 else cx)))
    if _is_wall_camera(cx, cy):
        distance -= inset_m
    if span <= 0 or distance <= 0:
        return fixed
    low, high = _FIT_HFOV_RANGE
    return round(min(high, max(low, math.degrees(2 * math.atan(span * _FIT_MARGIN / 2 / distance)))), 1)

