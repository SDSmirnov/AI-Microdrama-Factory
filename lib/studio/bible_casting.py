"""Bible-driven casting: the story bible decides which refs exist and how they are named; the model
only writes their content, one entity per call, from the bible entry and its source excerpts.

Slots come from code: a character's base look plus one variation per variant in the chapter's story
time, a room's six views, a vehicle's three, an outdoor place's four, a recurring object. Every ref
carries bible_key / bible_variant / bible_view (its slot) and bible_hash. A ref whose hash is not its
entity's — the bible changed, or a pre-bible ref matched by name — is rewritten unless update=False;
a rewrite drops what was derived from the old text (room vocabulary, anchors, floor plan, QA) and
marks an existing PNG for re-render.
"""
import hashlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

from lib.core.project import Project
from lib.core.prompts import DOOR_HANDEDNESS
from lib.core.schemas import CHARACTER_SCHEMA
from lib.core.utils import safe_name
from lib.llm.base import BaseLLM
from lib.studio.archivist import (
    ENRICH_BUDGET, EXCERPT_RADIUS, Progress, _excerpts, chapter_texts, chapter_window, entity_block, find_entity,
    mentions, needs_ref, ref_key,
)
from lib.studio.artist.catalog import load_character_refs
from lib.studio.artist.view_catalog import _OUTDOOR_VIEWS, _ROOM_VIEWS, _VEHICLE_VIEWS
from lib.studio.ledger import area_of
from lib.studio.room_geometry import behind_camera_rule

logger = logging.getLogger(__name__)

VIEWS = {'Room': _ROOM_VIEWS, 'Vehicle': _VEHICLE_VIEWS, 'Outdoor': _OUTDOOR_VIEWS}
STYLE_VIEW = {'Room': 'View-From-Entrance', 'Vehicle': 'Exterior', 'Outdoor': 'View-Primary'}
# Derived from a ref's old text: stale once the text is rewritten.
DERIVED = ('details_applied', 'room_vocabulary', 'anchor_points', 'floor_plan', 'qa', 'qa_corrections')
_CONTENT = ('logline_subject_info', 'visual_desc', 'video_visual_desc', 'behavioral_signature', 'physical_vocabulary')


@dataclass(frozen=True)
class Slot:
    key: str           # bible entity key
    variant: str       # '' = the base look
    view: str          # '' for characters and objects
    name: str          # ref name (an adopted pre-bible ref keeps its own)
    camera: str = ''   # view instruction
    context: str = ''  # when a variation applies


def entity_hash(entity: dict) -> str:
    content = {k: entity.get(k) for k in ('ref_name', 'type', 'role', 'aliases', 'visual_desc', 'features', 'variants')}
    return hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def _title(label: str) -> str:
    return '-'.join(w.capitalize() for w in label.split('-'))


def plan(bible: dict, entity: dict, window: tuple[int, int] | None) -> list[Slot]:
    """The refs one entity needs: views for places, base + in-window variants for characters."""
    base, etype, key = entity['ref_name'], entity['type'], entity['key']
    if etype in VIEWS:
        return [Slot(key, '', view, f'{base}-{view}', camera) for view, camera in VIEWS[etype]]
    slots = [Slot(key, '', '', base)]
    if etype == 'Character':
        rank = {p['id']: i for i, p in enumerate(bible['periods'])}
        label = {p['id']: p['label'] for p in bible['periods']}
        for v in entity.get('variants') or []:
            lo, hi = v['time_context']['from'], v['time_context']['to']
            if window is None or (rank[lo] <= window[1] and rank[hi] >= window[0]):
                slots.append(Slot(key, v['label'], '', f"{base}-{_title(v['label'])}",
                                  context=f"{v['context']} ({label[lo]} – {label[hi]})"))
    return slots


def index_refs(bible: dict, character_info: dict) -> tuple[dict, list[str]]:
    """(key, variant, view) → existing ref name, and orphans (linked to a key the bible no longer has).
    A pre-bible ref is adopted by name/alias: a base character, or a place view by its suffix."""
    slots, orphans = {}, []
    for name, info in character_info.items():
        if key := info.get('bible_key'):
            if key in bible['entities']:
                slots[(key, info.get('bible_variant', ''), info.get('bible_view', ''))] = name
            else:
                orphans.append(name)
    for name, info in character_info.items():
        if info.get('bible_key') or info.get('character_ref') or not (e := find_entity(bible, name)):
            continue
        view = name[len(area_of(name)):].lstrip('-')
        slots.setdefault((e['key'], '', view), name)
    return slots, orphans


def _excerpt_lines(entity: dict, texts: dict[str, str]) -> list[str]:
    """Source excerpts around the entity's references, in story order, within half the enrich budget."""
    picked, cost = [], 0
    for r in entity['refs']:
        if r['offset'] is None or r['chapter'] not in texts:
            continue
        cost += 2 * EXCERPT_RADIUS + len(r['quote'])
        if cost > ENRICH_BUDGET // 2:
            break
        picked.append(r)
    return _excerpts(picked, texts)


def _slot_line(entity: dict, s: Slot) -> str:
    if s.view:
        rule = f" {behind_camera_rule(s.view)}" if entity['type'] in ('Room', 'Outdoor') else ''
        return f"- {s.name} — {entity['type']} view {s.view}. Camera: {s.camera}{rule}"
    if s.variant:
        v = next(v for v in entity['variants'] if v['label'] == s.variant)
        return (f"- {s.name} — variation of {entity['ref_name']}: {v['variance']}. Context: {s.context}. "
                f"Look: {v['description']}")
    return f"- {s.name} — {entity['type']}, base look at first appearance"


def _cast_names(bible: dict, entity: dict) -> str:
    """The spelling every ref uses for the characters around this entity: code romanizes names, a model respells
    them ("Нарсизо" is Narsizo, not Narziso), and a respelled name reads as another person."""
    chapters = set(entity['chapters'])
    return ', '.join(sorted(e['ref_name'].replace('-', ' ') for e in bible['entities'].values()
                            if e['type'] == 'Character' and chapters & set(e['chapters'])))


def entry_prompt(bible: dict, entity: dict, todo: list[Slot], prompts: dict, excerpts: list[str]) -> str:
    excerpt_block = "\n".join(excerpts) or "(none)"
    names = _cast_names(bible, entity)
    return f"""{prompts.get('casting', '')}

{prompts.get('setting', '')}

You are writing reference entries for ONE entity of the story bible. The bible was built from the whole book: it is the truth for what this entity is and what is in it. The setting's real-world anchor, when given, is the truth for how it looks in its era: a thing the bible gives it that the anchor lists as not in this world, and that no source excerpt names, is a bible error — leave it out and draw the era's own counterpart.

## ENTITY (story bible)
Role: {entity['role']}
{entity_block(bible, entity)}

## SOURCE EXCERPTS (what the novel says around this entity)
{excerpt_block}

## RETURN EXACTLY THESE ENTRIES — names verbatim, no others:
{chr(10).join(_slot_line(entity, s) for s in todo)}

RULES
1. visual_desc: detailed, for image generation. Every bible feature visible in the entry is drawn, including those first named later in the book — they are already there.
2. A view entry describes ONE camera angle (its Camera line), with image-left/right for that camera; what is behind the camera is not in frame. No multi-panel layouts.
3. A variation copies the base look's physical traits verbatim (face, hair, build, age, skin, eyes) and describes only what changes.
4. video_visual_desc: concise; for characters keep build, clothing, face and what is worn or carried on the body with its placement. A prop taken out and used in one scene has its own ref: not part of a look.
5. behavioral_signature and physical_vocabulary: characters only, from the excerpts (observable behaviour, together within 60 words); empty for everything else.
6. logline_subject_info: one sentence, who/what this is in the story.
7. DOORS: {DOOR_HANDEDNESS}
8. Nothing that contradicts the bible.
9. Names: write characters exactly as {names or 'the bible names them'} — never respelled or translated.
10. No aspect ratio or frame format in any description: the renderer sets the frame."""


def _entries(reply) -> list[dict]:
    """The entry list from a reply: the array itself, a bare entry, or an object wrapping the array."""
    if isinstance(reply, dict) and 'name' not in reply:
        reply = next((v for v in reply.values() if isinstance(v, list)), [])
    if isinstance(reply, dict):
        reply = [reply]
    return [e for e in reply if isinstance(e, dict)] if isinstance(reply, list) else []


def _match(reply, todo: list[Slot]) -> dict[str, dict]:
    """Slot name → returned entry, by the same key; a lone slot takes a lone entry whatever its name."""
    entries = _entries(reply)
    by_key = {ref_key(e.get('name') or ''): e for e in entries}
    got = {s.name: by_key[ref_key(s.name)] for s in todo if ref_key(s.name) in by_key}
    if not got and len(todo) == 1 and len(entries) == 1:
        got = {todo[0].name: entries[0]}
    if missing := [s.name for s in todo if s.name not in got]:
        logger.warning(f"  ⚠️  reply lacks {', '.join(missing)}; got {type(reply).__name__} with names "
                       f"{[e.get('name') for e in entries]}")
    return got


def _forced(entity: dict, s: Slot, slots: list[Slot], entry: dict, old: dict, h: str, refs: dict) -> dict:
    """Fields code owns: name, type, links between refs, provenance. A base keeps the hand-made
    variations it lists that still exist; bible variations come from the slots only."""
    style_view = STYLE_VIEW.get(entity['type'])
    base = next((x.name for x in slots if not x.variant and not x.view), '')
    if s.view:  # every view takes the truth view as its style reference
        style = '' if s.view == style_view else next((x.name for x in slots if x.view == style_view), '')
    else:       # a variation takes the base look
        style = base if s.variant else ''
    manual = [v for v in old.get('variations') or [] if v in refs and not refs[v].get('bible_key')]
    variations = manual + [x.name for x in slots if x.variant]
    return {
        **{k: entry.get(k, '') for k in _CONTENT},
        'logline_subject_info': entry.get('logline_subject_info') or entity['role'],
        'name': s.name,
        'type': entity['type'],
        'style_reference': style,
        'character_ref': base if s.variant else '',
        'context': s.context,
        'variations': [] if s.variant or s.view else list(dict.fromkeys(variations)),
        'bible_key': s.key, 'bible_variant': s.variant, 'bible_view': s.view, 'bible_hash': h,
    }


def _save(project: Project, data: dict, rewritten: bool = True) -> None:
    """A rewritten ref drops what was derived from its old text and re-renders an existing PNG."""
    name = data['name']
    old = project.character_info.get(name) or {}
    merged = ({k: v for k, v in old.items() if k not in DERIVED} if rewritten else old) | data
    if rewritten and old and (project.ref_dir / f"{safe_name(name)}.png").exists():
        merged['needs_regenerate'] = True
    (project.ref_dir / f"{safe_name(name)}.json").write_text(json.dumps(merged, indent=2, ensure_ascii=False),
                                                             encoding='utf-8')
    project.character_info[name] = merged


def _cast_entity(bible: dict, entity: dict, slots: list[Slot], todo: list[Slot], h: str, prompts: dict,
                 texts: dict, llm: BaseLLM, project: Project) -> dict:
    """One call for the entity's stale/new slots, one retry for any it left out. → {written, failed}."""
    excerpts = _excerpt_lines(entity, texts)
    got = _match(llm.make_json(entry_prompt(bible, entity, todo, prompts, excerpts), CHARACTER_SCHEMA), todo)
    if missing := [s for s in todo if s.name not in got]:
        got |= _match(llm.make_json(entry_prompt(bible, entity, missing, prompts, excerpts), CHARACTER_SCHEMA),
                      missing)
    for s in todo:
        if s.name in got:
            _save(project, _forced(entity, s, slots, got[s.name], project.character_info.get(s.name) or {}, h,
                                   project.character_info))
    return {'entity': entity['ref_name'], 'written': [s.name for s in todo if s.name in got],
            'failed': [s.name for s in todo if s.name not in got]}


def cast_from_bible(bible: dict, chapter: str | None, prompts: dict, llm: BaseLLM, project: Project,
                    update: bool = True) -> dict:
    """Refs for the chapter's bible entities (all entities when chapter is None).
    → {written, failed, linked, current, orphans}."""
    load_character_refs(project)
    window = None if chapter is None else chapter_window(bible, chapter)
    texts = chapter_texts(bible)
    scoped = [e for e in bible['entities'].values() if chapter is None or chapter in e['chapters']]
    entities = [e for e in scoped if needs_ref(e, texts)]
    if skipped := [f"{e['ref_name']} ({len(e['refs'])} refs, {mentions(e, texts)} mentions)"
                   for e in scoped if e['type'] == 'Character' and not needs_ref(e, texts)]:
        logger.info(f"  ⏭️  no ref, background only: {', '.join(skipped)}")
    existing, orphans = index_refs(bible, project.character_info)

    jobs, linked, conflicts, current = [], [], [], 0
    for e in entities:
        h = entity_hash(e)
        slots = [replace(s, name=existing.get((s.key, s.variant, s.view), s.name)) for s in plan(bible, e, window)]
        todo = []
        for s in slots:
            info = project.character_info.get(s.name)
            if info and info.get('bible_key') not in (None, s.key):  # the name belongs to another entity
                logger.error(f"  ❌ {s.name}: already a ref of {info['bible_key']!r}, not {s.key!r} — not written")
                conflicts.append(s.name)
            elif info and info.get('bible_hash') == h:
                current += 1
            elif info and not update:
                if not info.get('bible_key'):  # link only: content kept as it is
                    _save(project, {'name': s.name, 'bible_key': s.key, 'bible_variant': s.variant,
                                    'bible_view': s.view}, rewritten=False)
                    linked.append(s.name)
            else:
                todo.append(s)
        if todo:
            jobs.append((e, slots, todo, h))

    scope = f"chapter {chapter}" if chapter else "the whole book"
    logger.info(f"🎭 Bible casting for {scope}: {len(entities)} entit(ies), {current} ref(s) current, "
                f"{sum(len(j[2]) for j in jobs)} to write in {len(jobs)} call(s)")
    progress = Progress('cast', len(jobs))

    def describe(r: dict) -> str:
        failed = f" · ❌ missing: {', '.join(r['failed'])}" if r['failed'] else ''
        return f"{r['entity']}: {len(r['written'])} ref(s){failed}"

    with ThreadPoolExecutor(max_workers=project.max_workers) as ex:
        results = list(ex.map(lambda j: progress.run(
            lambda: _cast_entity(bible, *j, prompts, texts, llm, project), describe), jobs))
    for name in orphans:
        logger.warning(f"  ⚠️  {name}: linked to a bible entity that no longer exists — left as is")
    return {'written': [n for r in results for n in r['written']],
            'failed': [n for r in results for n in r['failed']] + conflicts,
            'linked': linked, 'current': current, 'orphans': orphans}
