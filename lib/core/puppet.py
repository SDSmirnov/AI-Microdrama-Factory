"""
3D Puppet Theater Engine — coordinate-geometry layer for spatial disposition.

Coordinate system (per ANCHOR_SCHEMA):
  Origin (0,0) = entrance door center at floor level.
  X+ = East (right when entering).
  Y+ = into room (away from entrance).
  Z+ = up.
  View-To-Entrance mirrors all X coordinates (left↔right swap).

Replaces LLM-guessed spatial heuristics with deterministic 3D geometry for:
  - Screen-side derivation (left/right from camera right vector)
  - Depth/occlusion ordering (nearest-first by camera distance)
  - 180-degree rule validation (consecutive camera axis flip detection)
  - State continuity (movement budget enforcement across panels)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CameraRig:
    x: float
    y: float
    z: float
    look_at_x: float
    look_at_y: float
    look_at_z: float
    focal_mm: int = 50


@dataclass
class CharacterPose:
    name: str
    x: float
    y: float
    z: float = 0.0           # foot level = 0
    facing_deg: float = 0.0  # 0 = toward entrance, 180 = away from entrance
    pose: str = 'standing'   # seated / standing / crouching / prone
    visible: bool = True     # False if behind camera (POV/OTS source)


@dataclass
class PuppetFrame:
    panel_index: int
    camera: CameraRig
    characters: dict[str, CharacterPose]   # name -> pose
    view_type: str   # "From-Entrance" | "To-Entrance"
    duration: int = 6  # panel duration in seconds (movement budget denominator)


@dataclass
class SceneState:
    frames: list[PuppetFrame] = field(default_factory=list)

    def validate_transitions(self) -> list[dict]:
        """Check consecutive frames for physically impossible position jumps.

        Budget = panel duration * 1.2 m/s walking speed. Flags characters
        whose XY displacement exceeds the budget without a motion_prompt.
        Returns: [{panel_a, panel_b, character, distance_m, budget_m}]
        """
        violations = []
        for a, b in zip(self.frames, self.frames[1:]):
            budget_m = max(a.duration, 1) * 1.2
            for name in set(a.characters) & set(b.characters):
                pa, pb = a.characters[name], b.characters[name]
                if not pa.visible or not pb.visible:
                    continue
                dist = math.hypot(pb.x - pa.x, pb.y - pa.y)
                if dist > budget_m:
                    violations.append({
                        'panel_a': a.panel_index,
                        'panel_b': b.panel_index,
                        'character': name,
                        'distance_m': round(dist, 2),
                        'budget_m': round(budget_m, 2),
                    })
        return violations


# ---------------------------------------------------------------------------
# Core geometry functions
# ---------------------------------------------------------------------------

def resolve_screen_side(camera: CameraRig, subject_x: float, subject_y: float) -> str:
    """Return 'left' or 'right' for subject position relative to camera viewing direction.

    Computes the dot product of the camera's right vector (perpendicular to look_dir
    in XY, pointing clockwise) with the unit vector from camera to subject.
    Positive dot → screen-right; negative → screen-left.

    Replaces LLM-guessed swap_view with deterministic camera geometry.
    """
    dx = camera.look_at_x - camera.x
    dy = camera.look_at_y - camera.y
    norm = math.hypot(dx, dy)
    if norm < 1e-9:
        return 'left'  # degenerate: camera has no look direction
    dx /= norm
    dy /= norm
    # Right vector: rotate look_dir 90° clockwise → (dy, -dx)
    right_x = dy
    right_y = -dx
    sx = subject_x - camera.x
    sy = subject_y - camera.y
    sn = math.hypot(sx, sy)
    if sn < 1e-9:
        return 'left'  # subject coincides with camera
    sx /= sn
    sy /= sn
    return 'right' if (right_x * sx + right_y * sy) > 0 else 'left'


def resolve_depth_order(
    camera: CameraRig,
    objects: list[tuple[str, float, float]],
) -> list[str]:
    """Return object/character names sorted nearest-to-farthest from camera (Euclidean XY)."""
    return [
        name
        for name, _, _ in sorted(
            objects,
            key=lambda item: math.hypot(item[1] - camera.x, item[2] - camera.y),
        )
    ]


def is_occluded_by(
    camera: CameraRig,
    subject: CharacterPose,
    obj_x: float,
    obj_y: float,
    obj_height: float,
) -> bool:
    """Return True if obj lies between camera and subject on the camera-to-subject ray.

    Projects obj onto the camera→subject ray via dot product. The object is considered
    occluding when:
      - Projection parameter t ∈ (0, 1)  (object is between camera and subject)
      - Perpendicular distance < 0.5 m   (object is on the ray, not beside it)
      - obj_height > subject.z           (object is tall enough to block view)
    """
    rx = subject.x - camera.x
    ry = subject.y - camera.y
    rlen_sq = rx * rx + ry * ry
    if rlen_sq < 1e-9:
        return False
    ox = obj_x - camera.x
    oy = obj_y - camera.y
    t = (ox * rx + oy * ry) / rlen_sq
    if not (0.0 < t < 1.0):
        return False
    # Perpendicular distance from obj to camera→subject line
    # |cross product| / |ray| = |ox*ry - oy*rx| / sqrt(rlen_sq)
    perp = abs(ox * ry - oy * rx) / math.sqrt(rlen_sq)
    if perp > 0.5:  # 0.5 m = half typical furniture width
        return False
    return obj_height > subject.z


def validate_180_rule(frames: list[PuppetFrame]) -> list[dict]:
    """Detect camera axis flips between consecutive panels.

    Flags any pair where the dot product of look_at direction vectors < 0,
    indicating the camera crossed the 180-degree axis. Violations are
    warnings only — intentional coverage cuts trigger false positives here.
    Returns: [{panel_a, panel_b, reason}]
    """
    violations = []
    for a, b in zip(frames, frames[1:]):
        da_x = a.camera.look_at_x - a.camera.x
        da_y = a.camera.look_at_y - a.camera.y
        db_x = b.camera.look_at_x - b.camera.x
        db_y = b.camera.look_at_y - b.camera.y
        na = math.hypot(da_x, da_y)
        nb = math.hypot(db_x, db_y)
        if na < 1e-9 or nb < 1e-9:
            continue
        dot = (da_x * db_x + da_y * db_y) / (na * nb)
        if dot < 0:
            violations.append({
                'panel_a': a.panel_index,
                'panel_b': b.panel_index,
                'reason': (
                    f"camera axis flipped {a.view_type}→{b.view_type} "
                    f"(look_dir dot={dot:.2f})"
                ),
            })
    return violations


# ---------------------------------------------------------------------------
# POV / OTS camera-source character detection
# ---------------------------------------------------------------------------

_POV_NAMED = re.compile(
    r"""
    (?:
        (?P<name_poss>[\w][\w\s'-]*?)\s*'s\s+POV
      | POV\s+from\s+(?P<name_from>[\w][\w\s'-]*)
      | over[- ]the[- ]shoulder\s+of\s+(?P<name_ots>[\w][\w\s'-]*)
      | OTS\s+(?P<name_ots2>[\w][\w\s'-]*)
      | camera\s+behind\s+(?P<name_behind>[\w][\w\s'-]*)
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)

_POV_GENERIC = re.compile(
    r'\b(point[- ]of[- ]view|subjective\s+camera|first[- ]person\s+view)\b',
    re.IGNORECASE,
)


def detect_pov_character(lights_and_camera: str, visual_start: str) -> Optional[str]:
    """Return the camera-source character name for POV/OTS shots, or None.

    Searches lights_and_camera and visual_start for POV/OTS signals and returns
    the character whose perspective the camera represents (i.e. behind the lens).
    Returns None when the shot is not POV/OTS or the source character is unnamed.
    """
    combined = f"{lights_and_camera} {visual_start}"
    m = _POV_NAMED.search(combined)
    if m:
        name = (
            m.group('name_poss')
            or m.group('name_from')
            or m.group('name_ots')
            or m.group('name_ots2')
            or m.group('name_behind')
        )
        if name:
            return name.strip()
    return None  # generic POV or no signal found


# ---------------------------------------------------------------------------
# Deterministic visual_disposition compiler
# ---------------------------------------------------------------------------

# Max character-distance between a character name and zone label in disposition text
# to count as a zone assignment. 200 chars ≈ one sentence buffer.
_ZONE_PROX_CHARS = 200


def _nearest_zone(x: float, y: float, zones: list[dict]) -> Optional[dict]:
    """Return the zone whose (x, y) is closest to the given coordinates."""
    if not zones:
        return None
    return min(zones, key=lambda z: math.hypot(z.get('x', 0.0) - x, z.get('y', 0.0) - y))


def extract_zone_for_character(
    visual_disposition: str,
    char_name: str,
    zones: list[dict],
) -> Optional[dict]:
    """Identify which anchor zone a character is assigned to in a disposition text.

    Finds the character name's position in the text, then returns the zone whose
    label appears closest (within _ZONE_PROX_CHARS characters). Falls back to None
    when no zone label is found within the proximity window.
    """
    if not visual_disposition or not zones:
        return None
    text_lower = visual_disposition.lower()
    char_pos = text_lower.find(char_name.lower())
    if char_pos < 0:
        return None
    best_zone: Optional[dict] = None
    best_dist = float('inf')
    for zone in zones:
        label = zone.get('label', '')
        if not label:
            continue
        label_pos = text_lower.find(label.lower())
        if label_pos < 0:
            continue
        dist = abs(char_pos - label_pos)
        if dist < best_dist:
            best_dist = dist
            best_zone = zone
    return best_zone if best_dist < _ZONE_PROX_CHARS else None


def compile_visual_disposition(frame: PuppetFrame, anchor_points: dict) -> str:
    """Deterministically generate visual_disposition text from a PuppetFrame.

    Algorithm:
      1. Invisible characters → "[Name] — behind camera, not in frame"
      2. Visible characters → nearest zone hint (view_type selects hint variant)
      3. Compute depth order of visible characters + furniture objects
      4. Append "DEPTH: [near] → [mid] → [background]" line
      5. Trim to 120 words

    Returns '' when no characters are present.
    """
    zones = anchor_points.get('zones', [])
    objects_data = anchor_points.get('objects', [])
    cam = frame.camera
    parts: list[str] = []

    for c in frame.characters.values():
        if not c.visible:
            parts.append(f"{c.name} — behind camera, not in frame")

    visible = [c for c in frame.characters.values() if c.visible]
    for c in visible:
        zone = _nearest_zone(c.x, c.y, zones)
        if zone is None:
            continue
        hint_key = (
            'visual_disposition_hint_to_entrance'
            if frame.view_type == 'To-Entrance'
            else 'visual_disposition_hint'
        )
        hint = (zone.get(hint_key) or zone.get('visual_disposition_hint', '')).strip()
        # Strip embedded DEPTH lines — we build one unified DEPTH line below
        hint_body = re.sub(
            r'\s*DEPTH:.*', '', hint, flags=re.IGNORECASE | re.DOTALL,
        ).strip()
        # Keep first two semicolon/period-separated clauses for conciseness
        clauses = [s.strip() for s in re.split(r'(?<=[.;])\s+', hint_body) if s.strip()]
        brief = '; '.join(clauses[:2])
        parts.append(f"{c.name}: {brief}")

    if not parts and not visible:
        return ''

    # Depth order: visible characters + furniture objects, nearest-to-farthest
    depth_items: list[tuple[str, float, float]] = [
        (c.name, c.x, c.y) for c in visible
    ] + [
        (obj.get('label') or obj.get('id', ''), obj.get('x', 0.0), obj.get('y', 0.0))
        for obj in objects_data
        if obj.get('label') or obj.get('id')
    ]
    if depth_items:
        ordered = resolve_depth_order(cam, depth_items)
        parts.append(f"DEPTH: {' → '.join(ordered)}")

    text = ' '.join(parts)
    words = text.split()
    if len(words) > 120:
        text = ' '.join(words[:120])
    return text


# ---------------------------------------------------------------------------
# Integration helper — build PuppetFrames from panel dicts + anchor_points
# ---------------------------------------------------------------------------

_TO_ENTRANCE_SUFFIXES = ('-View-To-Entrance', '-Interior-To-Entrance', '-View-Opposite')


def _infer_view_type(panel: dict) -> str:
    """Infer 'To-Entrance' or 'From-Entrance' from panel location_references."""
    for ref in panel.get('location_references', []):
        if any(ref.endswith(s) for s in _TO_ENTRANCE_SUFFIXES):
            return 'To-Entrance'
    return 'From-Entrance'


def camera_from_view_type(view_type: str, anchor_points: dict) -> CameraRig:
    """Construct a CameraRig centered on room width and offset just outside the boundary.

    Camera is positioned so the look_dir is unambiguously into room (+Y) for
    From-Entrance or toward entrance (-Y) for To-Entrance. X is centered for
    resolve_screen_side correctness when camera is not laterally offset.
    """
    room_m = anchor_points.get('room_m', [6.0, 8.0])
    cx = room_m[0] / 2
    depth = room_m[1] if len(room_m) > 1 else 8.0
    if view_type == 'To-Entrance':
        return CameraRig(
            x=cx, y=depth + 0.3, z=1.6,
            look_at_x=cx, look_at_y=0.0, look_at_z=1.0,
        )
    return CameraRig(
        x=cx, y=-0.3, z=1.6,
        look_at_x=cx, look_at_y=depth, look_at_z=1.0,
    )


def build_scene_frames(panels: list[dict], anchor_points: dict) -> list[PuppetFrame]:
    """Build PuppetFrame list from panel dicts using the LLM-generated visual_disposition.

    Parses each panel's visual_disposition to extract character-to-zone assignments.
    POV/OTS characters are detected via detect_pov_character and marked visible=False.
    Panels with no parseable character assignments still produce a PuppetFrame
    (characters dict will be empty) so 180-rule validation can still run.
    """
    zones = anchor_points.get('zones', [])
    frames: list[PuppetFrame] = []
    for panel in panels:
        idx = panel.get('panel_index', 0)
        view_type = _infer_view_type(panel)
        cam = camera_from_view_type(view_type, anchor_points)
        pov_char = detect_pov_character(
            panel.get('lights_and_camera', ''),
            panel.get('visual_start', ''),
        )
        disp_text = panel.get('visual_disposition', '')
        characters: dict[str, CharacterPose] = {}
        for cname in panel.get('references', []):
            if pov_char and cname.lower() == pov_char.lower():
                characters[cname] = CharacterPose(
                    name=cname, x=cam.x, y=cam.y, visible=False,
                )
            else:
                zone = extract_zone_for_character(disp_text, cname, zones)
                if zone:
                    characters[cname] = CharacterPose(
                        name=cname,
                        x=zone.get('x', 0.0),
                        y=zone.get('y', 0.0),
                    )
        frames.append(PuppetFrame(
            panel_index=idx,
            camera=cam,
            characters=characters,
            view_type=view_type,
            duration=panel.get('duration', 6),
        ))
    return frames
