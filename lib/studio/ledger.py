"""Story state ledger: where each character is, panel to panel and scene to scene, checked in code.

The LLM decides what changes; this module flags what changed without a reason.
A place is an area (location ref without its view suffix), a vehicle seat and/or a [room-anchor].
"""
import math
import re
from dataclasses import dataclass

from lib.studio.vehicle_geometry import SEATS, infer_seat

_CABIN = (*SEATS, 'cargo', 'trunk', 'outside')

_VIEW_SUFFIX = re.compile(r'-(View-.*|Interior-.*|Exterior)$')
_ANCHOR = re.compile(r'\[([a-z0-9]+(?:-[a-z0-9]+)+)\]')
_MOVE = re.compile(
    r'\b(?:mov|walk|step|cross|climb|scrambl|slid|lung|enter|exit|crawl|jump|approach|retreat|return|leav|arriv|'
    r'switch|scoot|shift|yank|shov|dash|rush|kneel|duck|drag|pull|push|throw)\w*'
    r'|\b(?:get|gets|got|sit|sits|sat|stand|stands|stood|rise|rises|rose|run|runs|ran|fall|falls|fell|thrown|knelt)\b',
    re.I)
_WARDROBE = re.compile(r'\b(?:puts? on|takes? off|took off|remov\w*|chang\w*|dress\w*|undress\w*|wrap\w*|strip\w*)', re.I)


@dataclass(frozen=True)
class Place:
    area: str
    seat: str | None
    anchor: str | None
    look: str
    xy: tuple[float, float] | None = None   # metres, from a resolved pos


@dataclass(frozen=True)
class Issue:
    scene_id: object
    panel_index: object
    character: str
    message: str

    def __str__(self) -> str:
        where = f'P{self.panel_index}' if isinstance(self.panel_index, int) else self.panel_index
        return f'S{self.scene_id} {where} {self.character}: {self.message}'


def vehicle_names(character_info: dict) -> set[str]:
    return {area_of(name) for name, info in character_info.items() if info.get('type') == 'Vehicle'}


def area_of(location_ref: str) -> str:
    return _VIEW_SUFFIX.sub('', location_ref or '')


def places(panel: dict, scene: dict | None = None) -> dict[str, Place]:
    """Character name → place in this panel."""
    refs = panel.get('location_references') or [(scene or {}).get('location', '')]
    area = area_of(refs[0] if refs else '')
    out = {}
    for a in panel.get('state', {}).get('actors', []):
        explicit = a.get('vehicle_position')
        position = a.get('position') or ''
        anchor = _ANCHOR.search(position)
        seat = explicit if explicit in _CABIN else infer_seat(explicit if explicit else position)
        pos = a.get('pos') or {}
        xy = (pos['x_m'], pos['y_m']) if 'x_m' in pos else None
        out[a.get('name', '')] = Place(area, seat, anchor[1] if anchor else None, a.get('visual_ref') or '', xy)
    return out


def _actor_text(panel: dict, name: str) -> str:
    actor = next((a for a in panel.get('state', {}).get('actors', []) if a.get('name') == name), {})
    return f"{panel.get('motion_action', '')} {actor.get('motion_action', '')} {actor.get('pose', '')}"


MOVE_M = 0.6  # a resolved position shift beyond this is a move


def _moved(a: Place, b: Place) -> str | None:
    if a.seat and b.seat and a.seat != b.seat:
        return f'seat {a.seat} → {b.seat}'
    if a.area == b.area and a.xy and b.xy:
        dist = math.dist(a.xy, b.xy)
        return f'{dist:.1f} m' if dist > MOVE_M else None
    if a.area == b.area and a.anchor and b.anchor and a.anchor != b.anchor:
        return f'[{a.anchor}] → [{b.anchor}]'
    return None


def _changed_look(a: Place, b: Place) -> bool:
    return bool(a.look and b.look and a.look != b.look)


def panel_issues(panels: list[dict], scene: dict) -> list[Issue]:
    """Consecutive panels: a move or a wardrobe change needs a reason in motion_action/pose."""
    issues = []
    sid = scene.get('scene_id', scene.get('scene_local_id'))
    ordered = sorted(panels, key=lambda p: p.get('panel_index', 0))
    for prev, cur in zip(ordered, ordered[1:]):
        before, after = places(prev, scene), places(cur, scene)
        for name in before.keys() & after.keys():
            why = _actor_text(prev, name) + _actor_text(cur, name)
            move = _moved(before[name], after[name])
            if move and not _MOVE.search(why):
                issues.append(Issue(sid, cur.get('panel_index'), name, f'moves {move} with no move in motion_action'))
            if _changed_look(before[name], after[name]) and not _WARDROBE.search(why):
                issues.append(Issue(sid, cur.get('panel_index'), name,
                                    f'wardrobe {before[name].look} → {after[name].look} with no change in the action'))
    return issues


def _vehicle_in_play(panel: dict, scene: dict | None, vehicle: str) -> bool:
    text = ' '.join(a.get('position') or '' for a in panel.get('state', {}).get('actors', []))
    return vehicle.lower() in f"{area_of((panel.get('location_references') or [''])[0])} {text}".lower() or \
        any(p.seat in SEATS for p in places(panel, scene).values())


def boundary_issues(prev_last: dict, prev_scene: dict | None, first: dict, scene: dict,
                    vehicles: set[str] = frozenset()) -> list[Issue]:
    """Previous scene's last panel → this scene's first panel, unless the scene declares a cut in time or place."""
    if scene.get('transition_in', 'continuous') != 'continuous':
        return []
    sid, pid = scene.get('scene_id', scene.get('scene_local_id')), first.get('panel_index')
    before, after = places(prev_last, prev_scene), places(first, scene)
    issues = []
    for name, now in after.items():
        was = before.get(name)
        if was:
            if was.seat in SEATS and now.seat in SEATS and was.seat != now.seat:
                issues.append(Issue(sid, pid, name, f'previous scene ends in seat {was.seat}, this one starts in {now.seat}'))
            if _changed_look(was, now):
                issues.append(Issue(sid, pid, name, f'wardrobe {was.look} → {now.look} across a continuous cut'))
        elif now.seat in SEATS:
            position = next((a.get('position') or '' for a in first.get('state', {}).get('actors', [])
                             if a.get('name') == name), '')
            vehicle = next((v for v in vehicles if v.lower() in f'{now.area} {position}'.lower()), now.area)
            if _vehicle_in_play(prev_last, prev_scene, vehicle):
                issues.append(Issue(sid, pid, name, f'seated ({now.seat}) at scene start but absent when the '
                                                    f'previous scene ended with {vehicle} in play'))
    return issues


def check(scenes: list[dict], vehicles: set[str] = frozenset()) -> list[Issue]:
    issues = []
    prev = None
    for scene in scenes:
        panels = sorted(scene.get('panels', []), key=lambda p: p.get('panel_index', 0))
        if not panels:
            continue
        issues += panel_issues(panels, scene)
        if prev:
            issues += boundary_issues(prev[1], prev[0], panels[0], scene, vehicles)
        prev = (scene, panels[-1])
    return issues


def declared_issues(panels: list[dict], scene_spec: dict) -> list[Issue]:
    """Generated panels against the screenplay's entry_state (first panel) and exit_state (last panel)."""
    if not panels:
        return []
    ordered = sorted(panels, key=lambda p: p.get('panel_index', 0))
    sid = scene_spec.get('scene_local_id')
    issues = []
    for key, panel in (('entry_state', ordered[0]), ('exit_state', ordered[-1])):
        got = places(panel, scene_spec)
        for item in scene_spec.get(key) or []:
            want = item.get('vehicle_position')
            have = got.get(item.get('character', ''))
            if not have:
                continue
            if want in SEATS and have.seat and have.seat != want:
                issues.append(Issue(sid, panel.get('panel_index'), item['character'],
                                    f'{key} declares seat {want}, panel has {have.seat}'))
            if item.get('visual_ref') and have.look and have.look != item['visual_ref']:
                issues.append(Issue(sid, panel.get('panel_index'), item['character'],
                                    f"{key} declares wardrobe {item['visual_ref']}, panel has {have.look}"))
    return issues


def screenplay_issues(screenplay: dict) -> list[Issue]:
    """Declared exit_state of each scene → entry_state of the next continuous scene."""
    scenes = [(ep.get('episode_id'), s) for ep in screenplay.get('episodes', []) for s in ep.get('scenes', [])]
    issues = []
    for (_, prev), (ep_id, cur) in zip(scenes, scenes[1:]):
        if cur.get('transition_in', 'continuous') != 'continuous':
            continue
        exits = {i.get('character'): i for i in prev.get('exit_state') or []}
        anyone_seated = any(i.get('vehicle_position') in SEATS for i in exits.values())
        sid = f"{ep_id}.{cur.get('scene_local_id')}"
        for item in cur.get('entry_state') or []:
            name, seat = item.get('character', ''), item.get('vehicle_position')
            was = exits.get(name)
            if was is None:
                if seat in SEATS and anyone_seated:
                    issues.append(Issue(sid, 'entry', name, f'enters seated ({seat}) but is not in the previous exit_state'))
                continue
            if seat in SEATS and was.get('vehicle_position') in SEATS and seat != was['vehicle_position']:
                issues.append(Issue(sid, 'entry', name, f"seat {was['vehicle_position']} → {seat} across a continuous cut"))
            a, b = (was.get('place') or '').strip(), (item.get('place') or '').strip()
            if _ANCHOR.fullmatch(f'[{a}]') and _ANCHOR.fullmatch(f'[{b}]') and a != b:
                issues.append(Issue(sid, 'entry', name, f'place {a} → {b} across a continuous cut'))
    return issues


def issues_block(issues: list[Issue]) -> str:
    return ('CONTINUITY ERRORS in your previous answer — fix every one (a move needs a motion_action that '
            'performs it; a seat or place carried from the previous scene must not change silently):\n'
            + '\n'.join(f'- {i}' for i in issues))
