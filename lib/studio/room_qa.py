"""Truth-aware room-view QA and correction loop.

The room chain has three levels of truth:

* ``View-From-Entrance`` (VFE) is the base truth. It is QA'd against its own
  description and locked once passed; framing mismatches are only reported.
* ``View-To-Entrance`` (VTE) is the second truth. It is rendered from VFE
  alone, then QA'd; targeted image edits correct it. Nothing downstream may
  treat an unverified VTE as truth.
* Every other room view is derived from ``sketch + VFE + VTE`` and QA'd against
  both truth views (the sketch is geometry-only advice).

QA actions are banded by the minimum of the style, architecture and geometry
scores. See :func:`lib.studio.critic.decide_room_view_action`.

Candidates are rendered/edited into a staging directory and only replace the
live PNG when they are valid and score better. An API error blocks the view and
leaves the live PNG untouched.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from lib.core.prompts import NO_LABEL_TEXT
from lib.core.utils import atomic_write, safe_name
from lib.llm.base import BaseLLM
from lib.studio import critic

logger = logging.getLogger(__name__)

VFE_SUFFIX = 'View-From-Entrance'
VTE_SUFFIX = 'View-To-Entrance'
DERIVED_SUFFIXES: tuple[str, ...] = tuple(
    suffix for suffix in critic._VIEW_TRUTH_SOURCES if suffix != VTE_SUFFIX
)
OUTDOOR_TRUTH = critic.OUTDOOR_TRUTH
OUTDOOR_DERIVED = tuple(critic._OUTDOOR_TRUTH_SOURCES)
QA_DIRNAME = '.room_qa'
QA_SUMMARY_NAME = 'room_view_qa.json'


# ---------------------------------------------------------------------------
# Naming and view metadata
# ---------------------------------------------------------------------------

def view_suffix_of(name: str) -> str | None:
    """Return the canonical room-view suffix for a ref name, if any."""
    for suffix, _ in _room_views():
        if name.endswith(f'-{suffix}'):
            return suffix
    return None


def base_name_of(name: str, suffix: str | None = None) -> str:
    suffix = suffix or view_suffix_of(name)
    if suffix and name.endswith(f'-{suffix}'):
        return name[: -(len(suffix) + 1)]
    return name


def _room_views() -> list[tuple[str, str]]:
    # Imported lazily: artist imports room_qa only inside functions.
    from lib.studio.artist import _OUTDOOR_VIEWS, _ROOM_VIEWS
    return list(_ROOM_VIEWS) + list(_OUTDOOR_VIEWS)


def truth_suffixes(view_suffix: str) -> list[str]:
    return list(critic._VIEW_TRUTH_SOURCES.get(view_suffix) or critic._OUTDOOR_TRUTH_SOURCES.get(view_suffix, []))


def truth_ref_paths(ref_dir: Path, view_name: str, view_suffix: str) -> list[tuple[str, Path]]:
    base = base_name_of(view_name, view_suffix)
    paths: list[tuple[str, Path]] = []
    for suffix in truth_suffixes(view_suffix):
        path = ref_dir / f"{safe_name(base + '-' + suffix)}.png"
        if path.exists():
            paths.append((suffix, path))
    return paths


def compose_render_desc(view_data: dict) -> str:
    """Compose the immutable description with persisted QA corrections."""
    desc = (view_data.get('visual_desc') or '').strip()
    corrections = [
        str(c).strip() for c in (view_data.get('qa_corrections') or []) if str(c).strip()
    ]
    if not corrections:
        return desc
    bullets = '\n'.join(f"- {correction}" for correction in corrections)
    return (
        f"{desc}\n\n"
        f"PERSISTED QA CORRECTIONS — these override the description where they conflict:\n"
        f"{bullets}"
    )


def _set_correction(view_data: dict, correction: str) -> None:
    """Keep only the latest fix: accumulated corrections go stale and contradict each other."""
    correction = (correction or '').strip()
    if correction:
        view_data['qa_corrections'] = [correction]


def _model_name(llm, project, model: str = '') -> str:
    """The judge that actually answered: the backend's model, else the backend itself ('ManualLLM' = scored
    by hand), never the configured judge it replaced. Test doubles fall back to the configured one."""
    backend = getattr(llm, 'text_model', None)
    if isinstance(backend, str) and backend:
        return backend
    if isinstance(llm, BaseLLM):
        return type(llm).__name__
    return model or getattr(project, 'qa_model', '') or getattr(project, 'text_model', '')


# ---------------------------------------------------------------------------
# Geometry / aspect helpers
# ---------------------------------------------------------------------------

def expected_aspect_for(
    project,
    config: dict,
    view_name: str,
    view_suffix: str,
    view_data: dict,
) -> str | None:
    from lib.studio.artist import (
        _load_entrance_anchor_points,
        _parse_room_dims,
        _view_aspect_ratio,
    )
    from lib.studio.room_geometry import resolve_room_height_m

    anchor_points = view_data.get('anchor_points') or _load_entrance_anchor_points(
        view_name, view_suffix, project
    )
    room_m = anchor_points.get('room_m') if isinstance(anchor_points, dict) else None
    if isinstance(room_m, (list, tuple)) and len(room_m) >= 2:
        dims = (float(room_m[0]), float(room_m[1]))
    else:
        dims = _parse_room_dims(view_data.get('visual_desc', ''))
    if not dims:
        return None
    room_h, _ = resolve_room_height_m(
        anchor_points if isinstance(anchor_points, dict) else {},
        view_data.get('visual_desc', ''),
    )
    return _view_aspect_ratio(view_suffix, dims, config, room_h)


def aspect_report(image_path: Path, expected_aspect: str | None) -> dict | None:
    """Return a mismatch report without changing anything on disk."""
    if not expected_aspect:
        return None
    try:
        exp_w, exp_h = (int(part) for part in expected_aspect.split(':'))
    except (ValueError, ZeroDivisionError):
        return None
    with Image.open(image_path) as img:
        actual = img.width / img.height
        size = (img.width, img.height)
    expected = exp_w / exp_h
    if abs(actual / expected - 1.0) <= 0.12:
        return None
    return {
        'expected': expected_aspect,
        'expected_ratio': round(expected, 3),
        'actual_size': list(size),
        'actual_ratio': round(actual, 3),
        'message': (
            f"{image_path.name} is {size[0]}x{size[1]} ({actual:.2f}:1); "
            f"physical room proportions require {expected_aspect} ({expected:.2f}:1)."
        ),
    }


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def evaluate_view(
    project,
    llm,
    view_name: str,
    view_data: dict,
    view_suffix: str,
    image_path: Path,
    config: dict,
    threshold: int = critic.ROOM_QA_PASS_THRESHOLD,
) -> dict:
    """Run the vision judge on one image, with the view's truth refs attached."""
    from lib.studio.artist import _load_entrance_anchor_points

    if view_suffix == VFE_SUFFIX:
        sketch, sketch_img = project.ref_dir / f"{safe_name(view_name)}.sketch.png", None
        if view_data.get('floor_plan') and sketch.exists():
            with Image.open(sketch) as s:
                sketch_img = s.copy()
        with Image.open(image_path) as img:
            return critic.analyze_room_description(
                llm, img.copy(), view_data.get('visual_desc', ''),
                view_data.get('room_vocabulary'), threshold, sketch_img=sketch_img,
            )
    if view_suffix == OUTDOOR_TRUTH:
        with Image.open(image_path) as img:
            return critic.analyze_outdoor_description(llm, img.copy(), view_data.get('visual_desc', ''), threshold)

    truth_paths = truth_ref_paths(project.ref_dir, view_name, view_suffix)
    if not truth_paths:
        return critic.normalize_room_view_qa({
            'api_error': True,
            'error': f'no truth PNGs for {view_name}',
            'issues': [{
                'category': 'architecture',
                'severity': 'high',
                'object': 'truth views',
                'expected': ', '.join(truth_suffixes(view_suffix)),
                'observed': 'missing PNGs',
            }],
        }, pass_threshold=threshold, api_error=True)

    source_views: list[tuple[str, Image.Image]] = []
    opened: list[Image.Image] = []
    try:
        for suffix, path in truth_paths:
            img = Image.open(path)
            opened.append(img)
            source_views.append((suffix, img.copy()))

        with Image.open(image_path) as img:
            view_img = img.copy()

        sketch_img = None
        if view_suffix != VTE_SUFFIX:
            sketch_path = project.ref_dir / f"{safe_name(view_name)}.sketch.png"
            if sketch_path.exists():
                sketch_img = Image.open(sketch_path)
                opened.append(sketch_img)

        anchor_points = view_data.get('anchor_points') or _load_entrance_anchor_points(
            view_name, view_suffix, project
        )
        result = critic.analyze_room_view(
            llm=llm,
            view_img=view_img,
            source_views=source_views,
            view_suffix=view_suffix,
            visual_desc=view_data.get('visual_desc', ''),
            threshold=threshold,
            anchor_points=anchor_points or None,
            expected_aspect=expected_aspect_for(
                project, config, view_name, view_suffix, view_data
            ),
            sketch_img=sketch_img,
        )
        return result
    finally:
        for img in opened:
            img.close()


# ---------------------------------------------------------------------------
# Candidate rendering / editing / commit
# ---------------------------------------------------------------------------

def _qa_dir(project) -> Path:
    path = project.ref_dir / QA_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _candidate_path(project, view_name: str) -> Path:
    return _qa_dir(project) / f"{safe_name(view_name)}.candidate.png"


def _valid_image(path: Path) -> bool:
    try:
        with Image.open(path) as img:
            img.verify()
        with Image.open(path) as img:
            return img.width > 0 and img.height > 0
    except Exception:
        return False


def _commit_candidate(project, candidate: Path, live: Path) -> bool:
    """Atomically replace the live PNG after keeping a backup."""
    if not candidate.exists() or not _valid_image(candidate):
        logger.warning(f"    ⚠️  Invalid QA candidate for {live.name}; keeping live image")
        return False
    backup_dir = _qa_dir(project) / 'previous'
    backup_dir.mkdir(parents=True, exist_ok=True)
    if live.exists():
        shutil.copy2(live, backup_dir / live.name)
    os.replace(candidate, live)
    logger.info(f"    💾 Committed QA candidate → {live.name}")
    return True


def _edit_instruction(result: dict) -> str:
    parts: list[str] = []
    prompt = (result.get('edit_prompt') or '').strip()
    if prompt:
        parts.append(prompt)
    for op in result.get('edit_instructions') or []:
        if not isinstance(op, dict):
            continue
        action = str(op.get('op') or '').strip()
        target = str(op.get('target') or '').strip()
        src = str(op.get('from') or '').strip()
        dst = str(op.get('to') or '').strip()
        details = str(op.get('details') or '').strip()
        text = f"{action} {target}".strip()
        if src:
            text += f" from {src}"
        if dst:
            text += f" to {dst}"
        if details:
            text += f" ({details})"
        if text:
            parts.append(text)
    if not parts:
        parts = list(result.get('issues') or [])
    return '; '.join(parts)


def apply_targeted_edits(
    project,
    llm,
    view_name: str,
    view_suffix: str,
    view_data: dict,
    result: dict,
    candidate: Path,
    config: dict,
) -> bool:
    """Ask the image backend for a targeted edit; write only to the candidate."""
    instruction = _edit_instruction(result)
    if not instruction:
        logger.warning(f"    ⚠️  No edit instruction for {view_name}")
        return False

    refs = [str(path) for _, path in truth_ref_paths(
        project.ref_dir, view_name, view_suffix
    )]
    if view_suffix != VTE_SUFFIX:
        sketch_path = project.ref_dir / f"{safe_name(view_name)}.sketch.png"
        if sketch_path.exists():
            refs.append(str(sketch_path))

    instruction = (
        "Edit the source image. Keep the camera position, framing, perspective, "
        "materials and lighting unchanged except where explicitly instructed. "
        f"{NO_LABEL_TEXT} "
        "Apply ONLY the following corrections: "
        f"{instruction}"
    )
    live = project.ref_dir / f"{safe_name(view_name)}.png"
    try:
        image_bytes = llm.edit_image(
            str(live),
            instruction,
            refs=refs,
            aspect_ratio=expected_aspect_for(
                project, config, view_name, view_suffix, view_data
            ),
            image_size='1K',
        )
    except NotImplementedError:
        logger.warning("    ⚠️  Backend does not support edit_image")
        return False
    except Exception as exc:
        logger.warning(f"    ⚠️  Targeted edit failed for {view_name}: {exc}")
        return False

    if not image_bytes:
        logger.warning(f"    ⚠️  Empty edit response for {view_name}")
        return False
    candidate.write_bytes(image_bytes)
    if not _valid_image(candidate):
        logger.warning(f"    ⚠️  Edit response is not a valid image for {view_name}")
        candidate.unlink(missing_ok=True)
        return False
    return True


def _render_candidate(
    project,
    llm,
    view_data: dict,
    view_name: str,
    config: dict,
    candidate: Path,
) -> bool:
    from lib.studio.artist import _render_single_ref

    try:
        _render_single_ref(
            view_data, config, project, llm, force=True, output_path=candidate
        )
    except Exception as exc:
        logger.warning(f"    ⚠️  Candidate render failed for {view_name}: {exc}")
        return False
    if not candidate.exists() or not _valid_image(candidate):
        logger.warning(f"    ⚠️  Candidate render produced no valid image for {view_name}")
        return False
    return True


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _history_entry(attempt: int, result: dict, action: str) -> dict:
    return {
        'attempt': attempt,
        'action': action,
        'scores': {
            'style': result.get('style_score'),
            'architecture': result.get('architecture_score'),
            'geometry': result.get('geometry_score'),
            'overall': result.get('overall_score'),
        },
        'issues': list(result.get('issues') or [])[:12],
        'severities': [i.get('severity') for i in result.get('issue_details') or []][:12],
        'api_error': bool(result.get('api_error')),
        'at': _now(),
    }


def _png_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def persist_view_qa(
    project,
    view_name: str,
    view_data: dict,
    *,
    status: str,
    result: dict | None,
    action: str,
    attempts: int,
    history: list[dict],
    threshold: int,
    model: str,
) -> None:
    block: dict[str, Any] = {
        'status': status,
        'model': model,
        'pass_threshold': threshold,
        'action': action,
        'attempts': attempts,
        'updated_at': _now(),
        'history': history[-10:],
    }
    if result:
        block['scores'] = {
            'style': result.get('style_score'),
            'architecture': result.get('architecture_score'),
            'geometry': result.get('geometry_score'),
            'overall': result.get('overall_score'),
        }
        block['issues'] = list(result.get('issues') or [])[:12]
    if result and result.get('api_error'):
        block['error'] = result.get('error', 'QA API error')
    if status == 'passed':
        block['png_sha256'] = _png_sha256(project.ref_dir / f"{safe_name(view_name)}.png")
    view_data['qa'] = block
    json_path = project.ref_dir / f"{safe_name(view_name)}.json"
    atomic_write(json_path, json.dumps(view_data, indent=2))


# ---------------------------------------------------------------------------
# QA loop
# ---------------------------------------------------------------------------

def run_view_qa_loop(
    project,
    llm,
    view_name: str,
    *,
    config: dict,
    threshold: int = critic.ROOM_QA_PASS_THRESHOLD,
    max_attempts: int = 3,
    edit_attempts: int = 1,
    model: str = '',
) -> dict:
    """QA one rendered view and correct it using the banded action policy.

    Returns ``{view, status, action, scores, attempts, threshold}``.
    ``status`` is one of ``passed``, ``failed``, ``blocked`` or ``missing``.
    """
    suffix = view_suffix_of(view_name)
    json_path = project.ref_dir / f"{safe_name(view_name)}.json"
    live = project.ref_dir / f"{safe_name(view_name)}.png"
    if not suffix or not json_path.exists() or not live.exists():
        return {
            'view': view_name,
            'status': 'missing',
            'action': 'blocked',
            'scores': {},
            'attempts': 0,
            'threshold': threshold,
        }

    view_data = json.loads(json_path.read_text(encoding='utf-8'))
    qa = view_data.get('qa') or {}
    if qa.get('status') == 'passed' and qa.get('png_sha256') == _png_sha256(live):
        logger.info(f"    ✅ {view_name}: passed earlier, image unchanged — QA skipped")
        return {'view': view_name, 'status': 'passed', 'action': 'accept',
                'scores': qa.get('scores', {}), 'attempts': 0, 'threshold': threshold}
    model = _model_name(llm, project, model)
    history: list[dict] = []
    attempts = 0
    status = 'failed'
    last_result: dict | None = None
    last_action = 'regenerate'
    edits_failed = False

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        result = evaluate_view(
            project, llm, view_name, view_data, suffix, live, config, threshold
        )
        last_result = result
        last_action = result['action']
        if last_action == 'targeted_edit' and edits_failed:
            # Edits already failed on this view: escalate to a re-render.
            last_action = 'regenerate_with_instructions'
        history.append(_history_entry(attempt, result, last_action))

        logger.info(
            f"    QA attempt {attempt}: overall={result['overall_score']}/10 "
            f"(style={result['style_score']}, architecture={result['architecture_score']}, "
            f"geometry={result['geometry_score']}) action={last_action}"
        )
        for issue in result.get('issues', []):
            logger.info(f"      ⚠️  {issue}")

        if result.get('api_error'):
            status = 'blocked'
            logger.warning(f"    ⛔ QA blocked for {view_name}; live PNG preserved")
            break

        if last_action == 'accept':
            status = 'passed'
            break

        candidate = _candidate_path(project, view_name)
        candidate.unlink(missing_ok=True)

        if last_action == 'targeted_edit':
            improved = False
            for edit_index in range(1, edit_attempts + 1):
                if not apply_targeted_edits(
                    project, llm, view_name, suffix, view_data, result, candidate, config
                ):
                    break
                candidate_result = evaluate_view(
                    project, llm, view_name, view_data, suffix, candidate, config, threshold
                )
                history.append(_history_entry(
                    attempt, candidate_result, f'targeted_edit_{edit_index}'
                ))
                logger.info(
                    f"      edit {edit_index}: overall={candidate_result['overall_score']}/10 "
                    f"action={candidate_result['action']}"
                )
                if candidate_result.get('api_error'):
                    break
                if candidate_result['overall_score'] > result['overall_score']:
                    if _commit_candidate(project, candidate, live):
                        improved = True
                        last_result = candidate_result
                        last_action = candidate_result['action']
                    if candidate_result['action'] == 'accept':
                        status = 'passed'
                        break
                else:
                    candidate.unlink(missing_ok=True)
                if status == 'passed':
                    break
            if status == 'passed':
                break
            if not improved:
                edits_failed = True
                _set_correction(view_data, _edit_instruction(result))
            continue

        if last_action == 'regenerate':
            # Full reset: the accumulated corrections are part of what failed.
            view_data['qa_corrections'] = []
        else:  # regenerate_with_instructions
            _set_correction(
                view_data, result.get('regeneration_prompt') or _edit_instruction(result)
            )

        if attempt >= max_attempts:
            break

        if not _render_candidate(project, llm, view_data, view_name, config, candidate):
            continue

        candidate_result = evaluate_view(
            project, llm, view_name, view_data, suffix, candidate, config, threshold
        )
        history.append(_history_entry(attempt + 1, candidate_result, candidate_result['action']))
        logger.info(
            f"      re-render: overall={candidate_result['overall_score']}/10 "
            f"action={candidate_result['action']}"
        )
        if candidate_result.get('api_error'):
            candidate.unlink(missing_ok=True)
            continue
        if candidate_result['overall_score'] > result['overall_score']:
            if _commit_candidate(project, candidate, live):
                last_result = candidate_result
                last_action = candidate_result['action']
                if candidate_result['action'] == 'accept':
                    status = 'passed'
                    break
        else:
            candidate.unlink(missing_ok=True)

    if status != 'passed':
        if last_result and last_result.get('api_error'):
            status = 'blocked'
        elif last_result and last_result.get('action') == 'accept':
            status = 'passed'
        else:
            status = 'failed'
        logger.warning(
            f"    ❌ {view_name} QA {status} after {attempts} attempt(s); "
            f"live PNG preserved"
        )

    persist_view_qa(
        project,
        view_name,
        view_data,
        status=status,
        result=last_result,
        action=last_action,
        attempts=attempts,
        history=history,
        threshold=threshold,
        model=model,
    )
    return {
        'view': view_name,
        'status': status,
        'action': last_action,
        'scores': {
            'style': (last_result or {}).get('style_score'),
            'architecture': (last_result or {}).get('architecture_score'),
            'geometry': (last_result or {}).get('geometry_score'),
            'overall': (last_result or {}).get('overall_score'),
        },
        'attempts': attempts,
        'threshold': threshold,
    }


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------

def invalidate_dependents(project, base: str, changed_suffix: str) -> list[str]:
    """Mark views that depend on a changed truth view for re-render.

    VFE → VTE and every derived view. VTE → every derived view. Outdoor View-Primary → its three station views.
    """
    if changed_suffix == VFE_SUFFIX:
        affected = [VTE_SUFFIX] + list(DERIVED_SUFFIXES)
    elif changed_suffix == VTE_SUFFIX:
        affected = list(DERIVED_SUFFIXES)
    elif changed_suffix == OUTDOOR_TRUTH:
        affected = list(OUTDOOR_DERIVED)
    else:
        return []

    invalidated: list[str] = []
    for suffix in affected:
        path = project.ref_dir / f"{safe_name(base + '-' + suffix)}.json"
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except Exception as e:
            logger.warning(f"⚠️  Unreadable {path.name}: {e}")
            continue
        data['needs_regenerate'] = True
        data['qa'] = {'status': 'pending'}
        data['qa_corrections'] = []
        atomic_write(path, json.dumps(data, indent=2))
        invalidated.append(f"{base}-{suffix}")
    if invalidated:
        logger.info(f"  ♻️  Invalidated {len(invalidated)} dependent view(s) of {changed_suffix}")
    return invalidated


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def _without_anchors(project, bases: Iterable[str], truth: str) -> list[str]:
    """Bases whose truth view still has no anchor_points: the screenplay cannot place actors there."""
    def has(base):
        path = project.ref_dir / f"{safe_name(base + '-' + truth)}.json"
        return path.exists() and json.loads(path.read_text(encoding='utf-8')).get('anchor_points')
    return [base for base in bases if not has(base)]


def places_without_anchors(project) -> list[str]:
    """Truth views (room VFE, outdoor View-Primary) with no anchor_points: actors there cannot be placed."""
    return [f'{base}-{truth}' for kind, truth in (('Room', VFE_SUFFIX), ('Outdoor', OUTDOOR_TRUTH))
            for base in _without_anchors(project, [b for b, _ in _room_targets(project, kind=kind, truth=truth)], truth)]


def _matches_room(base: str, full_name: str, rooms: Iterable[str] | None) -> bool:
    if not rooms:
        return True
    wanted = {r.strip().lower() for r in rooms if r.strip()}
    return base.lower() in wanted or full_name.lower() in wanted


def _room_targets(project, rooms: Iterable[str] | None = None,
                  kind: str = 'Room', truth: str = VFE_SUFFIX) -> list[tuple[str, dict]]:
    targets: list[tuple[str, dict]] = []
    for name, info in project.character_info.items():
        if info.get('type') != kind or not name.endswith(f'-{truth}'):
            continue
        base = base_name_of(name, truth)
        if _matches_room(base, name, rooms):
            targets.append((base, info))
    return sorted(targets, key=lambda item: item[0])


def _render_truth_view(project, llm, view_name: str, config: dict) -> bool:
    from lib.studio.artist import _render_single_ref

    json_path = project.ref_dir / f"{safe_name(view_name)}.json"
    png_path = project.ref_dir / f"{safe_name(view_name)}.png"
    if not json_path.exists():
        return False
    view_data = json.loads(json_path.read_text(encoding='utf-8'))
    before = png_path.exists()
    try:
        _render_single_ref(view_data, config, project, llm, force=True)
    except Exception as exc:
        logger.warning(f"  ⚠️  Failed to render {view_name}: {exc}")
        return False
    if not png_path.exists():
        return False
    view_data.pop('needs_regenerate', None)
    atomic_write(json_path, json.dumps(view_data, indent=2))
    project.character_images[view_name] = str(png_path)
    suffix = view_suffix_of(view_name)
    if before and suffix in (VFE_SUFFIX, VTE_SUFFIX, OUTDOOR_TRUTH):
        invalidate_dependents(project, base_name_of(view_name, suffix), suffix)
    return True


def _vfe_changed(project, base: str, vfe_json: Path, suffix: str = VFE_SUFFIX) -> None:
    """A new truth image: its anchors describe the old one, and every view built from it is stale."""
    data = json.loads(vfe_json.read_text(encoding='utf-8'))
    if not data.get('floor_plan'):  # a plan is the image's source, not read from it
        data.pop('anchor_points', None)
    atomic_write(vfe_json, json.dumps(data, indent=2))
    project.character_info[data['name']] = data
    invalidate_dependents(project, base, suffix)


def _view_is_stale(view_data: dict, png_path: Path, force: bool) -> bool:
    return force or not png_path.exists() or bool(view_data.get('needs_regenerate'))


def run_room_views(
    project,
    llm,
    config: dict,
    *,
    rooms: Iterable[str] | None = None,
    use_sketches: bool = True,
    pass_threshold: int = critic.ROOM_QA_PASS_THRESHOLD,
    max_attempts: int = 3,
    edit_attempts: int = 1,
    allow_unverified_vte: bool = False,
    allow_unverified_vfe: bool = False,
    force: bool = False,
    blender_cmd: str = 'blender',
    model: str = '',
    anchor_llm=None,
) -> dict:
    """Run the full VFE → VTE → anchors/sketch → derived chain.

    VTE is gated on a passed VFE and derived views on a passed VTE. The
    ``allow_unverified_*`` flags render past a failed gate (the summary records
    the views as unverified).
    """
    from lib.studio.artist import (
        load_character_refs,
        remake_room_refs,
        run_room_anchors,
    )
    from lib.studio.room_sketch import render_sketches

    # 1. Make sure every room has its per-view JSONs.
    remake_room_refs(config, llm, project, create_only=True)
    load_character_refs(project)

    targets = _room_targets(project, rooms)
    if not targets:
        logger.info("  No room View-From-Entrance refs found.")

    summary: dict[str, Any] = {
        'generated_at': _now(),
        'threshold': pass_threshold,
        'model': _model_name(llm, project, model),
        'rooms': {},
        'failed_vfe': [],
        'passed_vte': [],
        'failed_vte': [],
    }
    passed_bases: list[str] = []
    failed_bases: list[str] = []

    planned = {base for base, info in targets if info.get('floor_plan')}
    if planned and use_sketches:
        try:
            render_sketches(project, config, blender_cmd=blender_cmd, room_filter=planned)
        except Exception as exc:
            logger.warning(f"  ⚠️  Plan sketch rendering failed ({exc}); VFE renders from text and anchors")
        targets = [(base, project.character_info.get(f'{base}-{VFE_SUFFIX}', info)) for base, info in targets]

    # 2. Base truth: render VFE when missing/stale. Never QA it into a regen.
    for base, info in targets:
        vfe_name = f'{base}-{VFE_SUFFIX}'
        vfe_png = project.ref_dir / f"{safe_name(vfe_name)}.png"
        vfe_json = project.ref_dir / f"{safe_name(vfe_name)}.json"
        room_summary: dict[str, Any] = {'views': {}}
        summary['rooms'][base] = room_summary

        if _view_is_stale(info, vfe_png, force):
            logger.info(f"  🎬 Base truth: rendering {vfe_name}")
            if not _render_truth_view(project, llm, vfe_name, config):
                room_summary['error'] = 'VFE render failed'
                failed_bases.append(base)
                continue
            _vfe_changed(project, base, vfe_json)
            info = json.loads(vfe_json.read_text(encoding='utf-8'))
        else:
            project.character_images[vfe_name] = str(vfe_png)

        report = aspect_report(
            vfe_png,
            expected_aspect_for(project, config, vfe_name, VFE_SUFFIX, info),
        )
        if report:
            room_summary['vfe_aspect'] = report
            logger.warning(f"  ⚠️  VFE framing: {report['message']} (reported, not re-rendered)")

        before = vfe_png.read_bytes()
        result = run_view_qa_loop(
            project, llm, vfe_name, config=config, threshold=pass_threshold,
            max_attempts=max_attempts, edit_attempts=edit_attempts, model=model,
        )
        room_summary['views'][VFE_SUFFIX] = result
        if vfe_png.read_bytes() != before:
            _vfe_changed(project, base, vfe_json)
        if result['status'] != 'passed':
            if allow_unverified_vfe:
                logger.warning(f"  ⚠️  {vfe_name} unverified; continuing (--allow-unverified-vfe)")
            else:
                room_summary['error'] = f"VFE QA {result['status']}"
                summary['failed_vfe'].append(base)

    # 3. Second truth: VTE from a verified VFE alone, then QA/edit loop.
    for base, _info in targets:
        if base in failed_bases or base in summary['failed_vfe']:
            continue
        vte_name = f'{base}-{VTE_SUFFIX}'
        vte_json = project.ref_dir / f"{safe_name(vte_name)}.json"
        vte_png = project.ref_dir / f"{safe_name(vte_name)}.png"
        if not vte_json.exists():
            logger.warning(f"  ⚠️  Missing VTE JSON for {base}")
            failed_bases.append(base)
            summary['rooms'][base]['error'] = 'VTE JSON missing'
            continue
        vte_data = json.loads(vte_json.read_text(encoding='utf-8'))

        if _view_is_stale(vte_data, vte_png, force):
            logger.info(f"  🎬 Second truth: rendering {vte_name} from VFE")
            if not _render_truth_view(project, llm, vte_name, config):
                failed_bases.append(base)
                summary['rooms'][base]['error'] = 'VTE render failed'
                continue
            vte_data = json.loads(vte_json.read_text(encoding='utf-8'))
        else:
            project.character_images[vte_name] = str(vte_png)

        result = run_view_qa_loop(
            project,
            llm,
            vte_name,
            config=config,
            threshold=pass_threshold,
            max_attempts=max_attempts,
            edit_attempts=edit_attempts,
            model=model,
        )
        summary['rooms'][base]['views'][VTE_SUFFIX] = result
        if result['status'] == 'passed':
            passed_bases.append(base)
            summary['passed_vte'].append(base)
        else:
            failed_bases.append(base)
            summary['failed_vte'].append(base)

    # 4. Anchors and sketches only for rooms with verified VTE truth.
    anchor_bases = list(passed_bases)
    if failed_bases and allow_unverified_vte:
        anchor_bases.extend(failed_bases)
        logger.warning(
            "  ⚠️  Rendering derived views for unverified VTE rooms: "
            + ', '.join(failed_bases)
        )

    if anchor_bases:
        try:
            run_room_anchors(project, anchor_llm or llm, room_filter=set(anchor_bases))
        except Exception as exc:
            logger.warning(f"  ⚠️  Anchor generation failed: {exc}")
        for base in _without_anchors(project, anchor_bases, VFE_SUFFIX):
            summary['rooms'][base]['error'] = 'anchors missing'

        if use_sketches:
            try:
                render_sketches(project, config, blender_cmd=blender_cmd,
                                room_filter=set(anchor_bases))
            except Exception as exc:
                logger.warning(f"  ⚠️  Sketch rendering failed ({exc}); "
                               "derived views will use VFE + VTE only")

    # 5. Derived views from sketch + VFE + VTE, then QA/edit loop.
    for base in anchor_bases:
        if base in failed_bases and not allow_unverified_vte:
            continue
        summary['rooms'][base]['views'].update(_derived_views(
            project, llm, config, base, DERIVED_SUFFIXES, force=force, threshold=pass_threshold,
            max_attempts=max_attempts, edit_attempts=edit_attempts, model=model))

    summary['outdoor'] = run_outdoor_views(
        project, llm, config, locations=rooms, use_sketches=use_sketches, pass_threshold=pass_threshold,
        max_attempts=max_attempts, edit_attempts=edit_attempts, allow_unverified=allow_unverified_vfe,
        force=force, blender_cmd=blender_cmd, model=model, anchor_llm=anchor_llm)

    summary_path = project.ref_dir / QA_SUMMARY_NAME
    atomic_write(summary_path, json.dumps(summary, indent=2))
    logger.info(f"  📄 Room-view QA summary: {summary_path}")
    return summary


def _derived_views(project, llm, config: dict, base: str, suffixes, *, force: bool, threshold: int,
                   max_attempts: int, edit_attempts: int, model: str) -> dict:
    """Render stale views built from verified truth, then run each through the QA/edit loop."""
    from lib.studio.artist import _render_single_ref

    results: dict[str, dict] = {}
    for suffix in suffixes:
        view_name = f'{base}-{suffix}'
        json_path = project.ref_dir / f"{safe_name(view_name)}.json"
        png_path = project.ref_dir / f"{safe_name(view_name)}.png"
        if not json_path.exists():
            continue
        data = json.loads(json_path.read_text(encoding='utf-8'))
        if _view_is_stale(data, png_path, force):
            logger.info(f"  🎬 Derived view: rendering {view_name}")
            try:
                rendered = _render_single_ref(data, config, project, llm, force=True)
            except Exception as exc:
                logger.warning(f"  ⚠️  Render failed for {view_name}: {exc}")
                rendered = None
            if not rendered:
                results[suffix] = {'view': view_name, 'status': 'render_failed', 'action': 'blocked', 'attempts': 0}
                continue
            data.pop('needs_regenerate', None)
            atomic_write(json_path, json.dumps(data, indent=2))
        project.character_images[view_name] = str(png_path)
        results[suffix] = run_view_qa_loop(
            project, llm, view_name, config=config, threshold=threshold,
            max_attempts=max_attempts, edit_attempts=edit_attempts, model=model,
        )
    return results


def run_outdoor_views(
    project,
    llm,
    config: dict,
    *,
    locations: Iterable[str] | None = None,
    use_sketches: bool = True,
    pass_threshold: int = critic.ROOM_QA_PASS_THRESHOLD,
    max_attempts: int = 3,
    edit_attempts: int = 1,
    allow_unverified: bool = False,
    force: bool = False,
    blender_cmd: str = 'blender',
    model: str = '',
    anchor_llm=None,
) -> dict:
    """Outdoor chain: View-Primary (description QA) → anchors + station sketches → the three station views.

    A Primary that fails QA blocks its other views unless ``allow_unverified``. Returns
    ``{'locations': {base: {'views': {...}, 'error'?}}, 'failed': [base, ...]}``.
    """
    from lib.studio.artist import run_room_anchors
    from lib.studio.room_sketch import render_sketches

    out: dict[str, Any] = {'locations': {}, 'failed': []}
    verified: list[str] = []
    for base, info in _room_targets(project, locations, kind='Outdoor', truth=OUTDOOR_TRUTH):
        name = f'{base}-{OUTDOOR_TRUTH}'
        png = project.ref_dir / f"{safe_name(name)}.png"
        json_path = project.ref_dir / f"{safe_name(name)}.json"
        entry: dict[str, Any] = {'views': {}}
        out['locations'][base] = entry
        if _view_is_stale(info, png, force):
            logger.info(f"  🎬 Outdoor truth: rendering {name}")
            if not _render_truth_view(project, llm, name, config):
                entry['error'] = 'View-Primary render failed'
                out['failed'].append(base)
                continue
            _vfe_changed(project, base, json_path, OUTDOOR_TRUTH)
        else:
            project.character_images[name] = str(png)
        before = png.read_bytes()
        result = run_view_qa_loop(project, llm, name, config=config, threshold=pass_threshold,
                                  max_attempts=max_attempts, edit_attempts=edit_attempts, model=model)
        entry['views'][OUTDOOR_TRUTH] = result
        if png.read_bytes() != before:
            _vfe_changed(project, base, json_path, OUTDOOR_TRUTH)
        if result['status'] == 'passed' or allow_unverified:
            verified.append(base)
        else:
            entry['error'] = f"View-Primary QA {result['status']}"
            out['failed'].append(base)

    if not verified:
        return out
    try:
        run_room_anchors(project, anchor_llm or llm, room_filter=set(verified))
    except Exception as exc:
        logger.warning(f"  ⚠️  Outdoor anchor generation failed: {exc}")
    for base in _without_anchors(project, verified, OUTDOOR_TRUTH):
        out['locations'][base]['error'] = 'anchors missing'
        out['failed'].append(base)
    if use_sketches:
        try:
            render_sketches(project, config, blender_cmd=blender_cmd, room_filter=set(verified))
        except Exception as exc:
            logger.warning(f"  ⚠️  Outdoor sketch rendering failed ({exc}); station views render from View-Primary only")
    for base in verified:
        out['locations'][base]['views'].update(_derived_views(
            project, llm, config, base, OUTDOOR_DERIVED, force=force, threshold=pass_threshold,
            max_attempts=max_attempts, edit_attempts=edit_attempts, model=model))
    return out
