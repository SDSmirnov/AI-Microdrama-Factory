"""Panel blocking for cars and anchored rooms/outdoor locations, and its 3D sketches.

Sketches are cached in <ref_dir>/.blocking_sketches/ by spec hash and rendered through render3d.
"""
import functools
import hashlib
import json
import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path

from lib.core.utils import safe_name
from lib.studio import room_blocking, vehicle_geometry
from lib.studio.blocking import scale_of
from lib.studio.render3d.factory import get_engine
from lib.studio.render3d.shapes import car_scene, room_scenes
from lib.studio.room_blocking import RoomBlocking

logger = logging.getLogger(__name__)

SKETCH_VERSION = 1  # bump when the sketch geometry or engine output changes for the same spec
_RENDER_LOCK = threading.Lock()  # panel workers share cache files; one render batch at a time


def panel_blocking(panel: dict, scene: dict | None, lookup, aspect: str = '9:16'):
    """Car blocking for vehicle interiors, else room/outdoor blocking from anchors, else None."""
    return (vehicle_geometry.panel_blocking(panel, scene, lookup, aspect)
            or room_blocking.panel_blocking(panel, scene, lookup, aspect))


def sketch_worthy(panel: dict) -> bool:
    """An ECU sketch is one head filling the frame: no geometry worth copying, the text block suffices."""
    return scale_of(panel) != 'ECU'


def block_text(b, with_sketch: bool = False) -> str:
    if isinstance(b, RoomBlocking):
        return room_blocking.blocking_block(b, with_sketch, b.colors())
    return vehicle_geometry.blocking_block(b, with_sketch)


def label(b) -> str:
    return f'{b.location} {b.suffix}' if isinstance(b, RoomBlocking) else f'{b.vehicle} {b.shot}'


def _spec(b) -> dict:
    return room_blocking.sketch_spec(b) if isinstance(b, RoomBlocking) else vehicle_geometry.sketch_spec(b)


def sketch_dir(ref_dir: Path) -> Path:
    return Path(ref_dir) / '.blocking_sketches'


def sketch_path(ref_dir: Path, b) -> Path:
    engine = get_engine().name  # engines draw differently: never serve one engine's sketch to the other
    digest = hashlib.sha1(json.dumps([SKETCH_VERSION, engine, _spec(b)], sort_keys=True).encode()).hexdigest()[:12]
    kind = b.suffix if isinstance(b, RoomBlocking) else b.shot.replace(':', '-').replace('>', '-to-')
    name = b.location if isinstance(b, RoomBlocking) else b.vehicle
    return sketch_dir(ref_dir) / f'{safe_name(name)}--{kind}--{digest}.png'


def render_blockings(blockings: list, ref_dir: Path, blender_cmd: str = 'blender', force: bool = False) -> dict:
    """Render every missing sketch in one engine batch; PNGs land only when the batch succeeds. Returns blocking → path."""
    with _RENDER_LOCK:
        targets = {b: sketch_path(ref_dir, b) for b in blockings}
        todo = {path: b for b, path in targets.items() if force or not path.exists()}
        if not todo:
            return targets
        engine = get_engine(blender_cmd=blender_cmd)
        if not engine.available():
            raise RuntimeError(f'render engine {engine.name!r} is not available; blocking sketches need it')
        with tempfile.TemporaryDirectory(prefix='blocking-sketches-') as tmp:
            tmp_dir = Path(tmp)
            engine.render([(room_scenes(_spec(b))[0] if isinstance(b, RoomBlocking) else car_scene(_spec(b)),
                            tmp_dir / path.name) for path, b in todo.items()])
            sketch_dir(ref_dir).mkdir(parents=True, exist_ok=True)
            for path in todo:
                staged = tmp_dir / path.name
                tmp_target = path.with_name(f'{path.name}.{os.getpid()}.tmp')
                shutil.copyfile(staged, tmp_target)
                tmp_target.replace(path)
        logger.info(f'  🎭 Rendered {len(todo)} blocking sketch(es) into {sketch_dir(ref_dir)}')
        return targets


@functools.cache
def _warn_no_engine(name: str) -> None:
    logger.warning(f'  ⚠️  Render engine {name!r} unavailable: no blocking sketches (AI_RENDER3D=auto uses pyvista)')


def panel_sketch(b, ref_dir: Path, blender_cmd: str = 'blender') -> Path | None:
    """Cached sketch, rendered on demand; None without Blender or on failure (the text block still applies)."""
    if b is None:
        return None
    path = sketch_path(ref_dir, b)
    if path.exists():
        return path
    engine = get_engine(blender_cmd=blender_cmd)
    if not engine.available():
        _warn_no_engine(engine.name)
        return None
    try:
        return render_blockings([b], ref_dir, blender_cmd)[b]
    except RuntimeError as exc:
        logger.warning(f'  ⚠️  Blocking sketch failed ({label(b)}): {exc}')
        return None


def scene_blockings(scenes: list[dict], lookup, aspect: str, scene_filter: int | None = None) -> list[tuple]:
    out = []
    for scene in scenes:
        if scene_filter is not None and scene.get('scene_id') != scene_filter:
            continue
        for panel in scene.get('panels', []):
            b = panel_blocking(panel, scene, lookup, aspect)
            if b:
                out.append((scene['scene_id'], panel['panel_index'], b))
    return out


def write_index(path: Path, found: list[tuple], paths: dict, root: Path) -> None:
    """Panel → sketch map for viewers; derived, regenerated by blocking-sketches."""
    index = {f'S{sid:03d}_P{pid:02d}': os.path.relpath(paths[b], root) for sid, pid, b in found if b in paths}
    path.write_text(json.dumps(index, indent=2, sort_keys=True), encoding='utf-8')
