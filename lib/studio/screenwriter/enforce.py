"""Continuity enforcers: retry a pass once when the ledger, panel lint or placement finds issues; keep the better answer."""
import logging

from lib.studio import ledger, panel_lint, room_blocking
from lib.studio.archivist import match_ref

logger = logging.getLogger(__name__)


def _ledger_issues(p1a: dict | None, scene_spec: dict, prev_exit: dict | None, vehicles: set[str]) -> list:
    panels = (p1a or {}).get('panels', [])
    issues = ledger.panel_issues(panels, scene_spec) + ledger.declared_issues(panels, scene_spec)
    if panels and (prev_exit or {}).get('panel'):
        first = min(panels, key=lambda p: p.get('panel_index', 0))
        issues += ledger.boundary_issues(prev_exit['panel'], prev_exit.get('scene'), first, scene_spec, vehicles)
    return issues


def _enforce_ledger(p1a: dict | None, rerun, scene_spec: dict, prev_exit: dict | None, vehicles: set[str]) -> dict | None:
    """One corrective Pass 1A retry when the ledger finds unexplained changes; keeps the better answer."""
    issues = _ledger_issues(p1a, scene_spec, prev_exit, vehicles)
    if not issues:
        return p1a
    for issue in issues:
        logger.warning(f"      ⚠️  Continuity: {issue}")
    retry = rerun(ledger.issues_block(issues))
    left = _ledger_issues(retry, scene_spec, prev_exit, vehicles) if retry else issues
    if retry and len(left) < len(issues):
        logger.info(f"      🔁 Pass 1A retry: {len(issues)} → {len(left)} continuity issue(s)")
        return retry
    logger.warning(f"      ⚠️  Pass 1A retry did not reduce continuity issues ({len(issues)}); keeping the first answer")
    return p1a


def _enforce_lint(result: dict | None, rerun, lint, label: str) -> dict | None:
    """One corrective retry when panel_lint finds HARD-FAILURE rule violations; keeps the answer with fewer."""
    issues = lint(result)
    if not issues:
        return result
    for issue in issues:
        logger.warning(f"      ⚠️  {label}: {issue}")
    retry = rerun(panel_lint.issues_block(issues))
    left = lint(retry) if retry else issues
    if retry and len(left) < len(issues):
        logger.info(f"      🔁 {label} retry: {len(issues)} → {len(left)} rule violation(s)")
        return retry
    logger.warning(f"      ⚠️  {label} retry did not reduce rule violations ({len(issues)}); keeping the first answer")
    return result


def canonical_refs(p1a: dict | None, refs: dict) -> dict | None:
    """Each actor's visual_ref (or, when empty, name) rewritten to the ref it spells: renders find refs by
    exact name, so 'Kennō' or 'Bodyguard-2' would silently lose the 'Kenno' / 'Bodyguard' card."""
    for panel in (p1a or {}).get('panels', []):
        for actor in panel.get('state', {}).get('actors', []):
            actor['visual_ref'] = match_ref(actor.get('visual_ref') or actor.get('name', ''), refs) \
                or actor.get('visual_ref', '')
    return p1a


def unknown_ref_issues(p1a: dict | None, refs: dict) -> list[str]:
    """visual_refs naming no ref (after canonical_refs); '' is an extra without a ref and passes."""
    panels: dict[str, list] = {}
    for panel in (p1a or {}).get('panels', []):
        for actor in panel.get('state', {}).get('actors', []):
            if (v := actor.get('visual_ref')) and v not in refs:
                panels.setdefault(v, []).append(panel.get('panel_index'))
    return [f"visual_ref '{v}' (panels {', '.join(map(str, idx))}) names no ref: use a name from CAST IN SCENE "
            f"exactly as written, or '' for an extra who has no ref" for v, idx in panels.items()]


def canonical_contract(scene_spec: dict, refs: dict) -> None:
    """The scene contract's visual_refs rewritten like canonical_refs, so the ledger compares like with like."""
    for key in ('entry_state', 'exit_state'):
        for item in scene_spec.get(key) or []:
            item['visual_ref'] = match_ref(item.get('visual_ref', ''), refs) or item.get('visual_ref', '')


def canonical_panel_refs(merged: dict, refs: dict) -> None:
    """Each panel's references rewritten to ref names; names of props without a ref are kept."""
    for panel in merged.get('panels', []):
        for key in ('references', 'location_references'):
            panel[key] = list(dict.fromkeys(match_ref(n, refs) or n for n in panel.get(key) or []))


def _apply_placements(p1a: dict | None, p1b: dict | None) -> None:
    placements = {p.get('panel_index'): {pl.get('character'): pl for pl in p.get('placements') or []}
                  for p in (p1b or {}).get('panels', [])}
    for panel in (p1a or {}).get('panels', []):
        for actor in panel.get('state', {}).get('actors', []):
            pl = placements.get(panel.get('panel_index'), {}).get(actor.get('name'))
            actor.pop('placement', None)
            if pl:
                actor['placement'] = {k: pl[k] for k in ('anchor', 'relation', 'target', 'distance_m', 'posture') if k in pl}


def _position_issues(p1a: dict | None, p1b: dict | None, scene_spec: dict, character_info: dict, aspect: str) -> list:
    """Placements that resolve to nothing, and moves (now in metres) with no motion_action."""
    _apply_placements(p1a, p1b)
    cams = {p.get('panel_index'): p for p in (p1b or {}).get('panels', [])}
    scene = {'scene_local_id': scene_spec.get('scene_local_id'), 'location': scene_spec.get('location', ''),
             'panels': [{**p, **cams.get(p.get('panel_index'), {})} for p in (p1a or {}).get('panels', [])]}
    room_blocking.annotate([scene], character_info.get, aspect)
    issues = [ledger.Issue(scene['scene_local_id'], p.get('panel_index'), a.get('name'),
                           f"placement {a['placement'].get('anchor') or a['placement'].get('target')!r} matches no "
                           'ROOM ANCHOR id and no actor')
              for p in scene['panels'] for a in p.get('state', {}).get('actors', [])
              if a.get('in_frame') and a.get('placement') and not a.get('pos')]
    return issues + ledger.panel_issues(scene['panels'], scene)


def _enforce_positions(p1a: dict | None, p1b: dict | None, rerun, scene_spec: dict, character_info: dict,
                       aspect: str) -> dict | None:
    """One corrective Pass 1B retry for unresolvable placements or unexplained moves; keeps the better answer."""
    if not p1b:
        return p1b
    issues = _position_issues(p1a, p1b, scene_spec, character_info, aspect)
    if not issues:
        return p1b
    for issue in issues:
        logger.warning(f"      ⚠️  Positions: {issue}")
    retry = rerun(ledger.issues_block(issues))
    left = _position_issues(p1a, retry, scene_spec, character_info, aspect) if retry else issues
    if retry and len(left) < len(issues):
        logger.info(f"      🔁 Pass 1B retry: {len(issues)} → {len(left)} position issue(s)")
        return retry
    _position_issues(p1a, p1b, scene_spec, character_info, aspect)  # re-apply the kept answer's placements
    return p1b
