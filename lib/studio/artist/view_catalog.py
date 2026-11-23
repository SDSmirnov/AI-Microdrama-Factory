"""View catalog: suffixes, per-view instructions, and metadata helpers."""

_MULTIPANEL_MARKERS = ('top:', 'bottom:', 'top panel', 'bottom panel', '2-panel', 'two-panel',
                       'panel stacked', 'panels stacked', 'left panel', 'right panel')


# Y-axis views look along the room depth (entrance → far wall).
# X-axis views look across the room width (left wall → right wall).
_Y_AXIS_VIEWS = frozenset({
    'View-From-Entrance', 'View-To-Entrance',
    'View-Center-To-Far', 'View-Center-To-Entrance',
    'View-By-Far-Wall', 'View-By-Entrance',
})


_X_AXIS_VIEWS = frozenset({'View-From-Left-Wall', 'View-From-Right-Wall', 'View-Ortho-Primary', 'View-Ortho-Opposite'})


# Outdoor: four headings turned in place at one station, street-view style:
# Primary +y, Ortho-Primary +x (90° right), Opposite -y, Ortho-Opposite -x.
_OUTDOOR_VIEW_SUFFIXES = frozenset({'View-Primary', 'View-Opposite', 'View-Ortho-Primary', 'View-Ortho-Opposite'})


# Per-view spatial consistency note injected into the render prompt alongside the style reference.
# Tells the model HOW the reference is spatially related to this view — critical for
# lateral/rotated views where a generic "180-degree turn" rule is simply wrong.
_VIEW_RENDER_CONSISTENCY: dict[str, str] = {
    'View-To-Entrance': (
        "MATERIAL MATCH: ALL wall surfaces, floor, ceiling, fixtures, and furniture must be "
        "IDENTICAL to the style reference in material, color, and texture. "
        "SPATIAL RULE: this is a 180-degree turn — left and right are SWAPPED. "
        "Every object on the LEFT in the reference must appear on the RIGHT here, and vice versa."
    ),
    'View-Center-To-Entrance': (
        "MATERIAL MATCH: ALL materials must match the style reference exactly. "
        "SPATIAL RULE: 180-degree turn toward entrance — left/right SWAPPED vs reference. "
        "Entrance door is in the mid-background. No far wall visible."
    ),
    'View-By-Entrance': (
        "MATERIAL MATCH: entrance-wall materials and door frame must match the style reference exactly. "
        "SPATIAL RULE: left/right SWAPPED vs reference — same mirroring as View-To-Entrance."
    ),
    'View-From-Left-Wall': (
        "MATERIAL MATCH: ALL materials must match the style reference exactly. "
        "SPATIAL RULE: camera rotated 90° — now on the image-left wall looking across. "
        "The reference's image-right wall (x=1) is now the FAR WALL straight ahead. "
        "Entrance-side furniture (low Y in reference) appears image-right; "
        "far-side furniture (high Y in reference) appears image-left."
    ),
    'View-From-Right-Wall': (
        "MATERIAL MATCH: ALL materials must match the style reference exactly. "
        "SPATIAL RULE: camera rotated 90° — now on the image-right wall looking across. "
        "The reference's image-left wall (x=0) is now the FAR WALL straight ahead. "
        "Entrance-side furniture (low Y in reference) appears image-left; "
        "far-side furniture (high Y in reference) appears image-right."
    ),
    'View-Ortho-Primary': (
        "MATERIAL MATCH: ALL materials must match the style reference exactly. "
        "SPATIAL RULE: same camera spot as the reference, turned 90° right. What lined the reference's image-right "
        "side is now straight ahead, seen head-on; the reference's distance runs off to the image-left."
    ),
    'View-Ortho-Opposite': (
        "MATERIAL MATCH: ALL materials must match the style reference exactly. "
        "SPATIAL RULE: same camera spot as the reference, turned 90° left. What lined the reference's image-left "
        "side is now straight ahead, seen head-on; the reference's distance runs off to the image-right."
    ),
    'View-Center-To-Far': (
        "MATERIAL MATCH: ALL materials must match the style reference exactly. "
        "SPATIAL RULE: SAME left/right orientation as reference — no mirroring. "
        "Camera at room center; far wall appears closer and dominates the frame."
    ),
    'View-By-Far-Wall': (
        "MATERIAL MATCH: far-wall materials, window frames, and surface details must match the style reference exactly. "
        "SPATIAL RULE: SAME left/right orientation as reference — no mirroring. "
        "Far wall fills ~80% of frame; mid-room furniture is behind the camera and NOT visible."
    ),
}


_VIEW_CAMERA_PHRASES = {
    'View-From-Entrance':      'viewed from the entrance, looking into the room',
    'View-To-Entrance':        'viewed from the far end, looking back toward the entrance',
    'View-From-Left-Wall':     'viewed from the image-left wall, looking across the room',
    'View-From-Right-Wall':    'viewed from the image-right wall, looking across the room',
    'View-Center-To-Far':      'viewed from room center, looking toward the far wall',
    'View-Center-To-Entrance': 'viewed from room center, looking toward the entrance',
    'View-By-Far-Wall':        'viewed from 1m of the far wall/window, looking at the far wall (silhouette position)',
    'View-By-Entrance':        'viewed from 1m of the entrance, looking at the entrance door (threshold position)',
    'Interior-From-Entrance':  'interior viewed from the entrance',
    'Interior-To-Entrance':    'interior viewed looking toward the entrance',
    'Exterior':                'exterior view',
    'View-Primary':            'primary direction view',
    'View-Opposite':           'opposite direction view',
    'View-Ortho-Primary':      'cross view, 90° right of the primary direction',
    'View-Ortho-Opposite':     'cross view, 90° left of the primary direction',
}


def _view_logline(base_logline: str, view_suffix: str) -> str:
    """Build a view-specific logline_subject_info without inheriting camera-position language.

    Strips the part after the first view-position clause (', viewed', ' — ', '. ') from
    the base logline and appends the correct per-view camera phrase.
    """
    # Strip any existing view-position suffix from base
    for marker in (', viewed', ' — ', '. '):
        idx = base_logline.find(marker)
        if idx != -1:
            base_logline = base_logline[:idx]
    base_logline = base_logline.strip().rstrip('.')
    camera_phrase = _VIEW_CAMERA_PHRASES.get(view_suffix, view_suffix.replace('-', ' ').lower())
    return f"{base_logline} — {camera_phrase}"


_ROOM_VIEWS = [
    (
        'View-From-Entrance',
        'Wide shot standing at the entrance doorway, camera looking INTO the room toward the opposite wall. '
        'Use the wall layout from visual_desc: show the opposite wall, left wall, right wall, center floor. '
        'All furniture and decor visible from this angle must match that layout exactly. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-To-Entrance',
        'Wide shot standing at the far end of the room, camera looking BACK toward the entrance wall and door. '
        'CRITICAL SPATIAL RULE — 180-degree turn: left and right walls are SWAPPED relative to View-From-Entrance. '
        'What was on the LEFT when entering is now on the RIGHT. What was on the RIGHT when entering is now on the LEFT. '
        'Example: if the bar was on the IMAGE-LEFT wall in View-From-Entrance, it must appear on the IMAGE-RIGHT side of this image. '
        'Use the room layout from visual_desc to determine the correct left/right placement for each wall. '
        'Show the entrance wall with its door at the far end. '
        'All furniture and materials must be identical to the View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-From-Left-Wall',
        'Wide shot camera on the IMAGE-LEFT wall (x=0 as seen in View-From-Entrance), looking across the room toward the IMAGE-RIGHT wall. '
        'SPATIAL RE-MAPPING relative to View-From-Entrance: '
        'IMAGE-RIGHT wall (x=1) is now the FAR WALL straight ahead. '
        'Far wall (straight ahead in View-From-Entrance) is now image-LEFT. '
        'Entrance wall (behind camera in View-From-Entrance) is now image-RIGHT. '
        'Re-position all furniture using the room layout from visual_desc: '
        'entrance-side objects (low Y) appear image-right, far-wall objects (high Y) appear image-left. '
        'All materials and lighting identical to View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-From-Right-Wall',
        'Wide shot camera on the IMAGE-RIGHT wall (x=1 as seen in View-From-Entrance), looking across the room toward the IMAGE-LEFT wall. '
        'SPATIAL RE-MAPPING relative to View-From-Entrance: '
        'IMAGE-LEFT wall (x=0) is now the FAR WALL straight ahead. '
        'Entrance wall (behind camera in View-From-Entrance) is now image-LEFT. '
        'Far wall (straight ahead in View-From-Entrance) is now image-RIGHT. '
        'Re-position all furniture using the room layout from visual_desc: '
        'entrance-side objects (low Y) appear image-left, far-wall objects (high Y) appear image-right. '
        'All materials and lighting identical to View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-Center-To-Far',
        'Wide shot camera at the CENTER of the room, looking toward the FAR wall (high Y, straight ahead in View-From-Entrance). '
        'Left/right orientation SAME as View-From-Entrance: image-left wall (x=0) stays image-left, image-right wall (x=1) stays image-right. '
        'Camera is mid-room: far wall fills the mid-background; center-floor furniture dominates the foreground. '
        'Entrance wall is behind the camera and NOT visible. '
        'All materials and lighting identical to View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-Center-To-Entrance',
        'Wide shot camera at the CENTER of the room, looking toward the ENTRANCE wall (low Y, behind camera in View-From-Entrance). '
        'CRITICAL: left/right SWAPPED vs View-From-Entrance — image-left wall (x=0) is now image-RIGHT, image-right wall (x=1) is now image-LEFT. '
        'Camera is mid-room: entrance wall and door fill the mid-background; center-floor furniture dominates the foreground. '
        'Far wall is behind the camera and NOT visible. '
        'All materials and lighting identical to View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-By-Far-Wall',
        'Intimate close shot camera 1m from the FAR WALL / WINDOW side, looking toward the far wall (same axis direction as View-From-Entrance). '
        'Left/right orientation UNCHANGED vs View-From-Entrance — NO mirroring. '
        'The far wall fills ~80% of the frame: window panes, far-wall texture, any objects on the far wall dominate. '
        'CRITICAL: mid-room furniture is behind the camera — NOT visible. Only objects immediately beside the far wall appear. '
        'A small strip of floor is visible near the base of the far wall. '
        'Characters placed at this position will appear silhouetted against window light. '
        'All materials and lighting identical to View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
    (
        'View-By-Entrance',
        'Intimate close shot camera 1m from the ENTRANCE WALL, looking toward the entrance door (same axis direction as View-To-Entrance). '
        'CRITICAL: left/right SWAPPED vs View-From-Entrance — same mirroring as View-To-Entrance. '
        'The entrance door and its frame fill ~80% of the frame. '
        'CRITICAL: mid-room furniture is behind the camera — NOT visible. Only entrance-wall objects appear. '
        'A small strip of floor is visible near the base of the entrance wall. '
        'All materials and lighting identical to View-From-Entrance style reference. '
        'Empty room, no people, architectural photography.',
    ),
]


_VEHICLE_VIEWS = [
    (
        'Exterior',
        'Full exterior, three-quarter front angle, studio lighting, '
        'entire vehicle in frame, no people.',
    ),
    (
        'Interior-From-Entrance',
        'Interior cabin view looking IN from the driver/main door. '
        'Dashboard, steering wheel, front seats, controls, '
        'cabin materials. No people.',
    ),
    (
        'Interior-To-Entrance',
        'Interior cabin view looking TOWARD the entrance door from '
        'the back seat. Rear cabin, headrests, door panels, '
        'details not visible from entrance side. No people.',
    ),
]


_OUTDOOR_VIEWS = [
    (
        'View-Primary',
        'Wide establishing shot facing the primary direction as defined in the visual_desc layout. '
        'Show all foreground, midground, and background landmarks visible from this angle. '
        '28 mm wide lens, eye height, both sides of the location receding. '
        'Empty location, no people, landscape/architectural photography.',
    ),
    (
        'View-Opposite',
        'Wide establishing shot facing the OPPOSITE direction (180-degree turn from View-Primary). '
        'CRITICAL SPATIAL RULE — 180-degree turn: left and right sides are SWAPPED relative to View-Primary. '
        'What was on the LEFT in View-Primary is now on the RIGHT, and vice versa. '
        'Use the layout from visual_desc to determine the correct left/right placement of each landmark. '
        'All materials, lighting, and atmosphere must match View-Primary style reference. '
        '28 mm wide lens, eye height, both sides of the location receding. '
        'Empty location, no people, landscape/architectural photography.',
    ),
    (
        'View-Ortho-Primary',
        'Establishing shot from the SAME camera spot as View-Primary, turned 90 degrees RIGHT. What lined the '
        'RIGHT side of View-Primary (e.g. the near facade) is now straight ahead, seen head-on; the View-Primary '
        'distance runs off to the image-LEFT. Follow the RIGHT section of visual_desc. '
        'All materials, lighting, and atmosphere must match View-Primary style reference. '
        '40 mm lens, eye height, the facing side square to the frame, verticals upright and parallel. '
        'Empty location, no people, landscape/architectural photography.',
    ),
    (
        'View-Ortho-Opposite',
        'Establishing shot from the SAME camera spot as View-Primary, turned 90 degrees LEFT. What lined the '
        'LEFT side of View-Primary (e.g. the far side of the street) is now straight ahead, seen head-on; the '
        'View-Primary distance runs off to the image-RIGHT. Follow the LEFT section of visual_desc. '
        'All materials, lighting, and atmosphere must match View-Primary style reference. '
        '40 mm lens, eye height, the facing side square to the frame, verticals upright and parallel. '
        'Empty location, no people, landscape/architectural photography.',
    ),
]


def _truth_ref_suffixes(view_suffix: str) -> list[str]:
    """Truth views a room view is built from and QA'd against."""
    if view_suffix == 'View-From-Entrance':
        return []
    if view_suffix == 'View-To-Entrance':
        return ['View-From-Entrance']
    return ['View-From-Entrance', 'View-To-Entrance']


def _ensure_view_metadata(data: dict) -> bool:
    """Backfill truth/QA metadata on an existing room-view JSON."""
    if data.get('type') != 'Room':
        return False
    suffix = next((s for s, _ in _ROOM_VIEWS if data.get('name', '').endswith(f'-{s}')), None)
    if not suffix:
        return False
    changed = False
    truth = _truth_ref_suffixes(suffix)
    if data.get('truth_refs') != truth:
        data['truth_refs'] = truth
        changed = True
    if 'qa_corrections' not in data:
        data['qa_corrections'] = []
        changed = True
    if suffix != 'View-From-Entrance' and 'qa' not in data:
        data['qa'] = {'status': 'pending'}
        changed = True
    return changed
