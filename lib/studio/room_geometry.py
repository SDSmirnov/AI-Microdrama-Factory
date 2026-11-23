"""Shared room-dimension helpers.

Used by both the room-view prompt builder (``artist.py``) and the Blender
sketch spec builder (``room_sketch.py``) so both sides resolve the ceiling
height and the view aspect ratio the same way.
"""
import re

# web/index.js:1123 uses 3.0 m when a description gives no ceiling height.
FALLBACK_ROOM_HEIGHT_M = 3.0

WALL_NAMES = {'x0': 'image-left wall', 'x1': 'image-right wall', 'y0': 'entrance wall', 'y1': 'far wall'}

# Wall views cut the room 0.5 m inside the camera wall: the wall and everything
# before the cut are hidden (behind the camera). Shared by the sketch (cut plane
# and culling) and by the render/QA anchor block (hidden objects, depths).
WALL_INSET_M = 0.5

# Adult eye level; _VIEW_CAMERA has no height component.
CAMERA_HEIGHT_M = 1.55

# What each room view's camera cannot see. Descriptions written from the
# vocabulary routinely place these elements in frame; renders and QA must not.
BEHIND_CAMERA = {
    'View-From-Entrance': 'the entrance wall with its door, doorframe and threshold',
    'View-To-Entrance': 'the far wall with its windows and fixtures',
    'View-From-Left-Wall': 'the left wall (x=0) and everything mounted on it',
    'View-From-Right-Wall': 'the right wall (x=1) and everything mounted on it',
    'View-Center-To-Far': 'the entrance wall with its door, and the entrance half of the room',
    'View-Center-To-Entrance': 'the far wall with its windows, and the far half of the room',
    'View-By-Far-Wall': 'the entrance wall and all mid-room furniture',
    'View-By-Entrance': 'the far wall and all mid-room furniture',
    # Outdoor: four headings from one station; each turns its back on the opposite section.
    'View-Primary': 'everything the description places BEHIND the station',
    'View-Opposite': 'everything the description places AHEAD of the station',
    'View-Ortho-Primary': 'everything the description places on the LEFT of the station',
    'View-Ortho-Opposite': 'everything the description places on the RIGHT of the station',
}


def behind_camera_rule(view_suffix: str) -> str:
    hidden = BEHIND_CAMERA.get(view_suffix)
    return (
        f"BEHIND THE CAMERA, NOT VISIBLE: {hidden}. Never show or require it, "
        "even where a description places it in frame."
    ) if hidden else ''


_CEILING_PATTERNS = (
    re.compile(r'(\d+(?:\.\d+)?)\s*m(?:eters?)?\s+(?:ceiling|high|height)', re.I),
    re.compile(r'ceiling\s*(?:height)?\s*[:=]?\s*(\d+(?:\.\d+)?)\s*m(?:eters?)?', re.I),
    # "a double-height 6m ceiling", "The ceiling is a double-height 6m"
    re.compile(r'double[- ]height\s+(\d+(?:\.\d+)?)\s*m(?:eters?)?', re.I),
    re.compile(
        r'ceiling\s+is\s+(?:a\s+)?(?:double[- ]height\s+)?(\d+(?:\.\d+)?)\s*m(?:eters?)?',
        re.I,
    ),
)


def resolve_room_height_m(anchor_points: dict, visual_desc: str = '') -> tuple[float, str]:
    """Return (ceiling_height_m, source) from anchors or the room description."""
    explicit = anchor_points.get('room_height_m')
    if isinstance(explicit, (int, float)) and 1.5 <= explicit <= 10:
        return float(explicit), 'anchor_points.room_height_m'

    for pattern in _CEILING_PATTERNS:
        match = pattern.search(visual_desc or '')
        if match:
            value = float(match.group(1))
            if 1.5 <= value <= 10:
                return value, 'visual_desc ceiling phrase'
    return FALLBACK_ROOM_HEIGHT_M, '3.0 m fallback (web viewer constant)'
