"""Shared render task runner and scene loading."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor

from lib.core.project import Project
from lib.studio.archivist import match_ref

logger = logging.getLogger(__name__)


def _run_render_tasks(render, tasks: list, describe, workers: int) -> None:
    """Run render(task) for every task in a thread pool and report the ones that raised.

    A bare executor.map() whose result is never read drops worker exceptions: the
    image is simply missing and nothing is logged.
    """
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [(task, executor.submit(render, task)) for task in tasks]
    failed = 0
    for task, future in futures:
        if future.exception() is not None:
            failed += 1
            logger.error(f"  ❌ Render crashed for {describe(task)}", exc_info=future.exception())
    if failed:
        logger.error(f"  ❌ {failed}/{len(tasks)} render task(s) crashed — see tracebacks above")


def _load_scenes(project: Project) -> list:
    """
    Load scenes from animation_metadata.json (single source of truth).
    Falls back to per-episode *_refined.json files if metadata doesn't exist yet.
    """
    meta_path = project.output_dir / "animation_metadata.json"
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding='utf-8'))
            scenes = data.get('scenes', [])
            logger.info(f"  📋 Loaded {len(scenes)} scene(s) from animation_metadata.json")
            return scenes
        except Exception as e:
            logger.warning(f"  ⚠️  Could not read animation_metadata.json: {e}")

    # Fallback: collect from per-episode refined files
    logger.warning("  ⚠️  animation_metadata.json not found, falling back to per-episode refined JSONs")
    scenes = []
    for json_path in sorted(project.output_dir.glob("animation_episode_scenes_*_refined.json")):
        try:
            data = json.loads(json_path.read_text(encoding='utf-8'))
            scenes.extend(data.get('scenes', []))
        except Exception as e:
            logger.warning(f"  ⚠️  Could not read {json_path}: {e}")
    return scenes


def known_refs(names: list[str], images: dict) -> list[str]:
    """Ref names for `names` in order, deduped, spelling variants resolved by match_ref ('Kennō' → 'Kenno');
    names with no ref (props never cast) are logged and dropped."""
    found = {n: match_ref(n, images) for n in dict.fromkeys(names)}
    if missing := [n for n, ref in found.items() if not ref]:
        logger.warning(f"  ⚠️  No ref for {missing}")
    return list(dict.fromkeys(ref for ref in found.values() if ref))


def _ref_label(name: str, ref_type: str, info: str) -> str:
    """Return a type-aware annotation label that follows its reference image."""
    if ref_type in ('Location', 'Room', 'Outdoor'):
        return f"↑ SCENE ENVIRONMENT: \"{name}\" — match this background/location.\n{info}\n"
    if ref_type == 'Vehicle' and '-Interior-' in name:
        # An interior view has its own camera; copying it would override the panel's shot.
        return (f"↑ VEHICLE INTERIOR: \"{name}\" — match materials, trim, colours and tint only; "
                f"camera position and seat layout come from the panel description.\n{info}\n")
    if ref_type in ('Object', 'Vehicle', 'Interface'):
        return f"↑ PROP: \"{name}\" — match this object's appearance exactly.\n{info}\n"
    return f"↑ CHARACTER: \"{name}\" — match face, hair, clothing exactly.\n{info}\n"

