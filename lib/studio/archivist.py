"""Story bible: a multi-pass collector of every character, place, vehicle and object of a book,
versioned by story time — reverse-engineering versioned API docs from every call site.

One call over a long text misses things (casting finds 10 items, the next run 12 more), and a look
in week 1 need not hold in week 2. So:

  1  map      chunk by chunk (paragraph-aligned, ~chunk_chars): entities with facts and verbatim
              quotes (the call sites), then up to `gleanings` re-reads of the same chunk that ask only
              for what was missed, stopping when nothing new comes back. Quotes are located in code;
              a quote that is not in the text demotes its fact to deduced.
  1b time     a sequential pass over every chunk's time cues: story periods (new day, stated jump,
              flashback) in story order, one per chunk.
  2  resolve  per type, in batches: names of one entity merged; each reference lands on one entity. Code keeps
              only names the fragment contains, joins a factless entity to the one entity holding all its names,
              and drops an alias two entities share.
  3  enrich   per entity: its references + the source excerpts around them → base description, features
              (from which period), variants (item, variance, time_context, context, description),
              conflicts; every claim cites reference ids, checked in code. Entities that fit one call are
              described up to ENRICH_BATCH per call (grouped by chapter, within ENRICH_BUDGET), each answer
              cached as that entity's own; a bigger one goes alone, in budget-sized parts merged hierarchically.

Every call is cached by content hash under <bible_dir>/.cache. Output: story_bible.json + .md.
"""
import hashlib
import json
import logging
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from dataclasses import dataclass, field, replace
from pathlib import Path

from lib.core.schemas import (
    BIBLE_CHUNK_SCHEMA, BIBLE_ENRICH_BATCH_SCHEMA, BIBLE_ENRICH_SCHEMA, BIBLE_GLEAN_SCHEMA, BIBLE_RESOLVE_SCHEMA,
    BIBLE_SETUP_BATCH_SCHEMA, BIBLE_TIMELINE_SCHEMA,
)
from lib.core.utils import CYR_TO_LAT
from lib.llm.base import BaseLLM, accepted
from lib.studio.ledger import area_of

logger = logging.getLogger(__name__)

VERSION = 4             # bump on any prompt/schema change: invalidates every cached call
CHUNK_CHARS = 20_000    # ~6k tokens of Russian prose: a split-book chapter is one call
GLEANINGS = 2           # "what did you miss" re-reads per chunk; stop early when nothing new
TIMELINE_WINDOW = 60    # chunks per timeline call; the periods found so far are carried over
RESOLVE_BATCH = 150     # candidate rows per resolve call
EXCERPT_RADIUS = 400    # source chars on each side of a reference shown to the enrich pass
ENRICH_BUDGET = 40_000  # prompt chars of references + excerpts per enrich call; bigger → hierarchical
ENRICH_BATCH = 8        # entities described per call when each fits ENRICH_BUDGET together
SETUP_BATCH = 4         # setup notes read per call, together within chunk_chars
GROUNDED = 0.5          # a story chunk's reply with fewer of its quotes in the text is a loop or copied examples
GROUNDED_MIN = 30       # ... judged only from this many facts: a short reply may paraphrase
MENTIONS = 5            # a character named this often gets a ref even when the text barely describes them


def _unaccent(text: str) -> str:
    """Latin diacritics dropped: 'Kennō' → 'Kenno'. Run after CYR_TO_LAT, or 'й'/'ё' lose their marks too."""
    return ''.join(c for c in unicodedata.normalize('NFKD', text) if not unicodedata.combining(c))


def ref_key(name: str) -> str:
    """Name → ASCII kebab key; 'Detective-Office', 'detective office' and 'Detective-Officé' meet."""
    return re.sub(r'[^a-z0-9]+', '-', _unaccent(name.lower().translate(CYR_TO_LAT))).strip('-')


def match_ref(name: str, names) -> str | None:
    """The name in `names` that `name` means, or None: exact, else by ref_key, also without a group index
    ('Bodyguard-2' → 'Bodyguard') and with or without a plural s ('Blind-Musician-1' → 'Blind-Musicians')."""
    if not name or name in names:
        return name or None
    keys = {ref_key(n): n for n in names}
    key = ref_key(name)
    for k in dict.fromkeys((key, re.sub(r'-\d+$', '', key))):
        for v in (k, f'{k}s', k.removesuffix('s')):
            if v in keys:
                return keys[v]
    return None


def latin_name(name: str) -> str:
    """Display name: Cyrillic words romanized by the same table as ref_key, Latin words kept without accents.
    'Торюмон-House-Garden' → 'Toryumon-House-Garden'; ref_key(latin_name(n)) == ref_key(n)."""
    roman = re.sub(r'[а-яё]+', lambda m: m[0].lower().translate(CYR_TO_LAT).capitalize(), name, flags=re.I)
    return re.sub(r'[^A-Za-z0-9]+', '-', _unaccent(roman)).strip('-')


def _hash(*parts) -> str:
    return hashlib.sha256(json.dumps([VERSION, *parts], ensure_ascii=False, sort_keys=True,
                                     default=str).encode()).hexdigest()


_local = threading.local()


def _fresh_calls() -> int:
    """Cache misses so far in this thread: a unit whose count did not move came from the cache."""
    return getattr(_local, 'misses', 0)


def _dur(seconds: float) -> str:
    return f"{int(seconds // 3600)}h{int(seconds % 3600 // 60):02d}m" if seconds >= 3600 else \
        f"{int(seconds // 60)}m{int(seconds % 60):02d}s"


def _names(names: list[str], limit: int = 6) -> str:
    return ', '.join(names[:limit]) + (f" +{len(names) - limit}" if len(names) > limit else '')


class Progress:
    """Logs `[stage done/total · elapsed · ETA]` as units finish; the ETA rate counts only units that
    called the model (cache hits are instant and marked 💾)."""

    def __init__(self, stage: str, total: int):
        self.stage, self.total, self.done, self.fresh = stage, total, 0, 0
        self.start, self.lock = time.monotonic(), threading.Lock()

    def run(self, fn, describe):
        """Run fn() in this thread, log describe(result) (under the lock: it may update shared state)."""
        before = _fresh_calls()
        result = fn()
        cached = _fresh_calls() == before
        with self.lock:
            self.done += 1
            self.fresh += not cached
            elapsed = time.monotonic() - self.start
            eta = _dur(elapsed / self.fresh * (self.total - self.done)) if self.fresh else '?'
            logger.info(f"  [{self.stage} {self.done}/{self.total} · {_dur(elapsed)} · ETA {eta}] "
                        f"{'💾 ' if cached else ''}{describe(result)}")
        return result


_MISS = object()


def _cache_get(path: Path, key: str):
    """The result cached at path for key, else _MISS."""
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('key') == key:
                return data['result']
        except (ValueError, KeyError) as e:
            logger.warning(f"  ⚠️  {path}: unreadable cache ({e}) — recomputing")
    return _MISS


def _cache_put(path: Path, key: str, result) -> None:
    """Store result for key; a None or partial result is not stored."""
    if result is not None and not (isinstance(result, dict) and result.get('partial')):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'key': key, 'result': result}, ensure_ascii=False, indent=1), encoding='utf-8')


def _cached(path: Path, key: str, compute, force: bool):
    """Return the cached result for key, else compute and store it (a None or partial result is not stored)."""
    if not force and (hit := _cache_get(path, key)) is not _MISS:
        return hit
    _local.misses = _fresh_calls() + 1
    result = compute()
    _cache_put(path, key, result)
    return result


SYSTEM_PROMPT = ("You read a novel for its continuity bible: what every character, place and object looks like, "
                 "by story time. Report what the text gives, nothing more. Reply with the JSON the schema asks for.")
MAX_REPLY_TOKENS = 32_000  # a whole chapter or a batch replies in ~12k; a looping model stops here, not at 100k
SETUP_REPLY_TOKENS = 12_000  # per setup note: they reply in ≤7.5k (2026-11-26); a loop on one cost 36k and 4 min
# Thinking cap on top of the reply budget. Measured 2026-11-25, nemotron-3.5-super-vl:free: uncapped it spent all
# 16k tokens thinking (empty or cut-off replies, half the chunks lost); 3-4k gave whole, correct replies.
REASONING_TOKENS = 4_000


ASK_ATTEMPTS = 2  # an unusable reply is a bad sample more often than a bad prompt: one more draw


def _ask(llm: BaseLLM, prompt: str, schema: dict, max_tokens: int = MAX_REPLY_TOKENS) -> dict | None:
    """One structured call, drawn again once when the reply is unparseable (truncated, or a model looping on one
    line); still unusable → None, logged: this unit fails, not the whole build. HTTP errors still propagate."""
    kwargs = accepted(llm.make_json, max_tokens=max_tokens, reasoning_tokens=REASONING_TOKENS)
    for attempt in range(1, ASK_ATTEMPTS + 1):
        try:
            return llm.make_json(prompt, schema, **kwargs)
        except (ValueError, RuntimeError) as e:  # json.JSONDecodeError is a ValueError
            logger.error(f"  ❌ unusable reply {attempt}/{ASK_ATTEMPTS} ({type(e).__name__}): {str(e)[:120]}")
    return None


def _words(s: str) -> str:
    return ' '.join(re.findall(r'\w+', s.casefold().replace('ё', 'е')))


def _locate(text: str, quote: str) -> int | None:
    """Start of the quote in text, ignoring punctuation, spacing, case and ё/е; a quote shortened with
    "..." matches when its pieces occur in order."""
    start, pos = None, 0
    for piece in re.split(r'\.{3}|…', quote):
        words = re.findall(r'\w+', piece)
        if not words:
            continue
        pattern = re.sub('[еёЕЁ]', '[еёЕЁ]', r'\W+'.join(map(re.escape, words)))
        m = re.compile(pattern, re.I).search(text, pos)
        if not m:
            return None
        start, pos = m.start() if start is None else start, m.end()
    return start


# ── chunks ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Chunk:
    id: str
    chapter: str
    start: int   # offset in the chapter text
    text: str
    setup: bool = False  # the logic step's setup appendix for the chapter, not story text
    known: tuple[str, ...] = ()  # setup only: the chapter's story entities, the only ones its facts may attach to
    world: str = ''  # setting.md's real-world anchor: the era and material culture facts are read in


def _pieces(text: str, size: int):
    """Paragraph spans; a paragraph longer than size is cut on whitespace."""
    for m in re.finditer(r'[^\n]*\S[^\n]*(?:\n[^\n]*\S[^\n]*)*', text):  # runs of non-blank lines
        s, e = m.span()
        while e - s > size:
            cut = text.rfind(' ', s + 1, s + size)
            cut = cut if cut > s else s + size
            yield s, cut
            s = cut
        if text[s:e].strip():
            yield s, e


def chunk_chapter(chapter: str, text: str, size: int = CHUNK_CHARS) -> list[Chunk]:
    """Paragraph-aligned chunks of about `size` chars; a short last paragraph is repeated as overlap."""
    groups, cur, fresh = [], [], 0  # fresh: pieces after the repeated one; a chunk never holds only the overlap
    for piece in _pieces(text, size):
        if fresh and piece[1] - cur[0][0] > size:
            groups.append(cur)
            cur = [cur[-1]] if cur[-1][1] - cur[-1][0] <= size // 4 else []
            fresh = 0
        cur.append(piece)
        fresh += 1
    if cur:
        groups.append(cur)
    return [Chunk(f'{chapter}#{i + 1:03d}', chapter, g[0][0], text[g[0][0]:g[-1][1]]) for i, g in enumerate(groups)]


# ── pass 1: map + gleaning ──────────────────────────────────────────────────────

_RULES = """RULES
1. A fact is visual and physical: face, build, hair, clothing, carried items, built-in fixtures, furniture and where it stands, props, materials, colours, damage, light sources.
2. Facts hidden in actions count: "he took X from the Y in the wall" gives the room a Y set in the wall (fixture) and the man X (carried); "he sat on the Z by the W" gives the room a Z standing by a W, and the W.
3. A fact that compares entities belongs to each: "an A the colour of his B" gives the A that colour and the man a B of that colour.
X, Y, Z, W, A, B stand for whatever the fragment names: rules 2-3 show the form of a fact, never a fact of this text.
4. quote: the shortest verbatim span of the fragment, in its original language, that the fact rests on. Copy it once and move on: code locates every quote, do not re-check them. explicit=false when the fact is deduced rather than read.
5. A place is the room or area where action happens, named by function and owner (Detective-Office, Mansion-Living-Room, Mansion-Driveway); a house the text walks through gives one entity per room. Never a camera view.
6. ref_name: Title-Case-Kebab, letters, digits, hyphens. Proper names (people, families, temples, towns, ships) are copied in the text's own script and spelling, in the nominative, never transliterated or translated; code romanizes them. Everything else is English: Торюмон-Рэйден, Хонган-дзи-Ruins, Торюмон-House-Garden. A character by the name the text uses most; a named first-person narrator by that name, never Narrator. A place a named person or family owns starts with that name. Minor figures count (a waiter, a guard), and so does every object a character handles.
7. Only what a camera could film in this fragment's scenes. Not an entity: a place only named (a province, a far-off city), a being only mentioned, prayed to or remembered outside a flashback scene, the sky or weather, an abstraction, an illustration marker such as [Картинка: …].
8. No fact the text neither states nor implies.
9. Report only what is there: leave out any kind the fragment says nothing about. Never write a fact such as "none", "not described" or "no details given", and never repeat a fact. Each thing once: never list synonyms, alternatives or numbered variants of one item. An entity with nothing visual still gets its names and role, with an empty facts list."""


_SETUP_NOTE = """This fragment is NOT story text: it is the production consultant's setup note for chapter {chapter} — room sizes, distances, required objects and their places, the state of things before a scene. Extract its facts the same way (explicit=false: they are planned, not narrated); leave every time field empty. Its staging (who stands, sits, walks or does what) is no fact: only things, sizes, places and what someone wears or carries."""


_SETUP_CAST = """Attach every fact to one of the chapter's story entities below, under its exact ref_name; a role word (the hero, the son, the father, the teacher) means the named character it stands for. Leave out whatever is none of them: the note may fill in the story, never add to it.
STORY ENTITIES:
{known}"""


def _world_block(world: str, rule: str) -> str:
    return f"\nSTORY WORLD — the real place and time this novel builds on:\n{world}\n{rule}\n" if world else ''


_WORLD_READ = ("Read every fact in this world's material culture. A thing it lists as not in this world is a "
               "misreading unless the fragment names it verbatim: then it is the novel's own departure, keep it.")
_WORLD_DESCRIBE = ("Describe everything in this world's material culture. A reference to a thing it lists as not in "
                   "this world, with no verbatim quote in the excerpts, is a misreading: leave it out.")


def _chunk_prompt(c: Chunk) -> str:
    setup = f"\n{_SETUP_NOTE.format(chapter=c.chapter)}\n{_SETUP_CAST.format(known=chr(10).join(c.known))}\n" \
        if c.setup else ''
    return f"""You are a script supervisor building a novel's continuity bible before any frame is drawn.
List every character, room, vehicle, outdoor place and object fragment {c.id} shows, with every visual fact.
{setup}{_world_block(c.world, _WORLD_READ)}
{_RULES}

TIME: cues = verbatim phrases that place the fragment in story time ("на следующее утро", "через неделю", "двадцать лет назад", a date, a weekday); label = when this is relative to the story so far ("same evening", "a week later", "flashback: childhood"); season, month, time_of_day, weather as stated or clearly implied, else empty; flashback = true when the fragment narrates a time earlier than the story's present.

<FRAGMENT id="{c.id}">
{c.text}
</FRAGMENT>"""


def _found_list(entities: list[dict]) -> str:
    return "\n".join(f"- {e['ref_name']} ({e.get('type')}): " + "; ".join(f['fact'] for f in e.get('facts') or [])
                     for e in entities) or "(nothing)"


def _glean_prompt(c: Chunk, found: list[dict]) -> str:
    return f"""You are re-reading fragment {c.id} for a novel's continuity bible. The reads so far found:
{_found_list(found)}

First reads often miss minor characters, furniture, fixtures, carried items, clothing details, colours, objects handled in actions, things only implied by what people do. Re-read sentence by sentence and return ONLY what is missing and on screen — new entities, or new facts for listed ones under the same ref_name. An empty list is a good answer when nothing is missing.
{_world_block(c.world, _WORLD_READ)}
{_RULES}

<FRAGMENT id="{c.id}">
{c.text}
</FRAGMENT>"""


def _merge_entities(entities: list[dict]) -> list[dict]:
    """Same ref_name → one entity; same fact (by words) once."""
    out: dict[str, dict] = {}
    for e in entities:
        k = ref_key(e.get('ref_name', ''))
        if not k:
            if re.search(r'\w', e.get('ref_name') or ''):
                logger.warning(f"  ⚠️  {e['ref_name']!r}: no Latin or Cyrillic letters to key — dropped")
            continue
        m = out.setdefault(k, {**e, 'names': [], 'facts': []})
        m['names'] = list(dict.fromkeys(m['names'] + (e.get('names') or [])))
        seen = {_words(f['fact']) for f in m['facts']}
        for f in e.get('facts') or []:
            if f.get('fact') and _words(f['fact']) not in seen:
                seen.add(_words(f['fact']))
                m['facts'].append(f)
    return list(out.values())


def _size(entities: list[dict]) -> int:
    return len(entities) + sum(len(e['facts']) for e in entities)


def _ungrounded(c: Chunk, reply) -> str:
    """Why a story chunk's reply is not the text's (most of its many quotes are not in it: the model looped on
    a list or copied the prompt's examples), else ''. Setup notes are paraphrased, never judged."""
    if c.setup or not isinstance(reply, dict):
        return ''
    quotes = [f.get('quote') or '' for e in reply.get('entities') or [] if isinstance(e, dict)
              for f in e.get('facts') or [] if isinstance(f, dict)]
    found = sum(_locate(c.text, q) is not None for q in quotes)
    return f"{found}/{len(quotes)} quotes in the text" if len(quotes) >= GROUNDED_MIN and found < GROUNDED * len(
        quotes) else ''


def _ask_grounded(llm: BaseLLM, prompt: str, schema: dict, c: Chunk) -> dict | None:
    """_ask, drawn again when the reply is not grounded in the chunk; still ungrounded → None, logged."""
    for attempt in range(1, ASK_ATTEMPTS + 1):
        reply = _ask(llm, prompt, schema, SETUP_REPLY_TOKENS if c.setup else MAX_REPLY_TOKENS)
        if not (why := _ungrounded(c, reply)):
            return reply
        logger.error(f"  ❌ {c.id}: ungrounded reply {attempt}/{ASK_ATTEMPTS} ({why}) — a loop or copied examples")
    return None


def _chunk_entry(c: Chunk, gleanings: int, cache: Path) -> tuple[Path, str]:
    """The chunk's cache path and key; a setup note's are the same whether it is read alone or in a batch."""
    blank = replace(c, text='')
    return (cache / 'chunks' / f'{c.id.replace("#", "_").replace("@", "_")}.json',
            _hash(c.text, gleanings, c.setup, _RULES, _chunk_prompt(blank), _glean_prompt(blank, [])))


def _setup_batch_prompt(notes: list[Chunk]) -> str:
    blocks = "\n\n".join(f"""{_SETUP_NOTE.format(chapter=c.chapter)}
{_SETUP_CAST.format(known=chr(10).join(c.known))}
<FRAGMENT id="{c.id}">
{c.text}
</FRAGMENT>""" for c in notes)
    return f"""You are a script supervisor building a novel's continuity bible before any frame is drawn.
Read each of the {len(notes)} setup notes below on its own: list the entities it shows, with every visual fact, under its fragment id. A fact of one note never goes to another.
{_world_block(notes[0].world, _WORLD_READ)}
{_RULES}

{blocks}"""


def _extract_setup_batches(notes: list[Chunk], llm: BaseLLM, cache: Path, force: bool, workers: int) -> set[str]:
    """Setup notes not yet cached, read SETUP_BATCH per call within CHUNK_CHARS (a note is a short list, a call
    each is mostly prompt). Each answer is stored as that note's own chunk entry, where the solo read finds it;
    a note the reply drops stays uncached and is read alone. → chunk ids stored."""
    todo = [c for c in notes if force or _cache_get(*_chunk_entry(c, 0, cache)) is _MISS]
    packs, cur = [], []
    for c in todo:
        if cur and (len(cur) >= SETUP_BATCH or sum(len(n.text) for n in cur) + len(c.text) > CHUNK_CHARS):
            packs.append(cur)
            cur = []
        cur.append(c)
    packs = [p for p in packs + [cur] if len(p) > 1]
    if not packs:
        return set()
    logger.info(f"📖 Pass 1a: {sum(map(len, packs))} setup note(s) in {len(packs)} batch(es)...")

    def run(pack: list[Chunk]) -> list[str]:
        _local.misses = _fresh_calls() + 1
        reply = _ask(llm, _setup_batch_prompt(pack), BIBLE_SETUP_BATCH_SCHEMA,
                     min(MAX_REPLY_TOKENS, SETUP_REPLY_TOKENS * len(pack)))
        notes_by_id = {}
        for n in (reply or {}).get('notes') or []:
            if isinstance(n, dict) and isinstance(n.get('entities'), list):
                notes_by_id.setdefault(str(n.get('id') or ''), n)
        stored = []
        for c in pack:
            if (n := notes_by_id.get(c.id)) is not None:
                _cache_put(*_chunk_entry(c, 0, cache), {'time': {}, 'entities': _merge_entities(n['entities']),
                                                        'gleaned': []})
                stored.append(c.id)
        return stored

    progress, stored = Progress('setup batches', len(packs)), set()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for done in ex.map(lambda pack: progress.run(lambda: run(pack), lambda r: f"{len(r)}/{len(pack)} read"
                                                     + ('' if len(r) == len(pack) else '; the rest alone next')),
                           packs):
            stored.update(done)
    return stored


def _extract(c: Chunk, llm: BaseLLM, gleanings: int, cache: Path, force: bool) -> dict | None:
    def run():
        first = _ask_grounded(llm, _chunk_prompt(c), BIBLE_CHUNK_SCHEMA, c)
        if not isinstance(first, dict):
            return None
        found, gleaned = _merge_entities(first.get('entities') or []), []
        for i in range(gleanings):
            more = _ask_grounded(llm, _glean_prompt(c, found), BIBLE_GLEAN_SCHEMA, c)
            if more is None:  # a failed re-read is not "nothing missing": use what we have, cache nothing
                return {'time': first.get('time') or {}, 'entities': found, 'gleaned': gleaned, 'partial': True}
            merged = _merge_entities(found + (more.get('entities') or []))
            gained = _size(merged) - _size(found)
            logger.debug(f"  🔍 {c.id}: re-read {i + 1} +{gained}")
            gleaned.append(max(gained, 0))
            if gained <= 0:
                break
            found = merged
        return {'time': first.get('time') or {}, 'entities': found, 'gleaned': gleaned}

    return _cached(*_chunk_entry(c, gleanings, cache), run, force)


def _chunk_status(c: Chunk, seen: set[str]):
    """Status line of a finished chunk; names entities no earlier chunk had."""
    def describe(r):
        if r is None:
            return f"{c.id}: ❌ extraction failed"
        ents = r['entities']
        new = [e['ref_name'] for e in ents if ref_key(e['ref_name']) not in seen]
        seen.update(ref_key(e['ref_name']) for e in ents)
        reads = ' '.join(f'+{g}' for g in r.get('gleaned') or []) + (' ❌' if r.get('partial') else '') or '-'
        when = (r.get('time') or {}).get('label', '')
        return (f"{c.id}: {len(ents)} entities, {sum(len(e['facts']) for e in ents)} facts (re-reads {reads})"
                + (f" · {when}" if when else '') + (f" · new: {_names(new)}" if new else ''))
    return describe


# ── pass 1b: timeline ───────────────────────────────────────────────────────────

_PERIOD_FIELDS = ('label', 'season', 'month', 'weather')


def _timeline_prompt(known: dict[str, dict], rows: list[str]) -> str:
    known_rows = "\n".join(f"  {p['id']} | {p['order']:g} | " + " | ".join(p.get(k, '') for k in _PERIOD_FIELDS)
                           + (" | flashback" if p.get('flashback') else '') for p in known.values()) or "  (none)"
    return f"""You are a script supervisor building the story timeline of a novel. Fragments are listed in reading order with their time cues.
A period is a stretch of story time with one continuous look: a new day, any stated time jump, the start or end of a flashback, or a change of season starts a new one. A flashback period gets the story-time order of WHEN IT HAPPENS, not when it is read. A fragment that continues a known period (also when the story returns from a flashback) reuses its id.

KNOWN PERIODS (id | order | label | season | month | weather):
{known_rows}

FRAGMENTS (id | cues | label | season | month | time of day | weather | flashback):
{chr(10).join(rows)}

Return periods: every NEW period and known ones you refine — ids continue the numbering (T01, T02, …), order is the story-time position as a number (fractional to fall between known ones, e.g. 2.5), label like "Day 3, evening", "Week 2, Tuesday", "Flashback: summer 1975". Return chunks: every fragment id above with its period id."""


def _timeline(chunks: list[Chunk], extracted: dict, llm: BaseLLM, cache: Path, force: bool,
              seed: list[dict] = ()):
    """→ (periods in story order, chunk id → period id). Gaps inherit the previous chunk's period.
    seed: the previous bible's periods, shown as known so a recomputed timeline keeps their ids (every reference,
    and so every description cache key, carries one). A hint, not a cache-key input: an unchanged book stays cached;
    a seed period a reply reuses is stored with it, so the cache never needs the old bible."""
    seeds = {p['id']: p for p in seed if p.get('id')}
    def row(c):
        t = (extracted.get(c.id) or {}).get('time') or {}
        return (f"  {c.id} | {' / '.join(t.get('cues') or [])} | " + " | ".join(
            t.get(k, '') for k in ('label', 'season', 'month', 'time_of_day', 'weather'))
            + (" | flashback" if t.get('flashback') else ''))

    periods: dict[str, dict] = {}
    assign: dict[str, str] = {}
    progress = Progress('time', -(-len(chunks) // TIMELINE_WINDOW))
    for w in range(0, len(chunks), TIMELINE_WINDOW):
        window = chunks[w:w + TIMELINE_WINDOW]
        rows, known = [row(c) for c in window], dict(periods)

        def describe(r):
            if r is None:
                return f"{window[0].id}…{window[-1].id}: ❌ failed"
            new = [f"{p.get('id')} {p.get('label', '')}" for p in r.get('periods') or []
                   if p.get('id') not in known and p.get('id') not in seeds]
            return f"{window[0].id}…{window[-1].id}: {len(new)} new period(s)" + (f": {_names(new, 4)}" if new else '')

        def ask():
            r = _ask(llm, _timeline_prompt({**seeds, **known}, rows), BIBLE_TIMELINE_SCHEMA)
            if isinstance(r, dict):
                returned = {p.get('id') for p in r.get('periods') or [] if isinstance(p, dict)}
                reused = {a.get('period') for a in r.get('chunks') or [] if isinstance(a, dict)} - returned
                r['periods'] = (r.get('periods') or []) + [seeds[i] for i in sorted(reused) if i in seeds]
            return r

        result = progress.run(lambda: _cached(
            cache / 'timeline' / f'{w // TIMELINE_WINDOW:03d}.json', _hash(rows, known), ask, force), describe)
        if result is None:
            logger.error(f"  ❌ timeline window {w // TIMELINE_WINDOW}: failed — chunks inherit the previous period")
        for p in (result or {}).get('periods') or []:
            pid = (p.get('id') or '').strip()
            if not pid:
                continue
            try:
                order = float(p.get('order'))
            except (TypeError, ValueError):
                order = float(len(periods) + 1)
            periods[pid] = {**periods.get(pid, {}), **{k: p.get(k, '') for k in _PERIOD_FIELDS},
                            'id': pid, 'order': order, 'flashback': bool(p.get('flashback'))}
        ids = {c.id for c in window}
        assign.update({a['chunk']: a['period'] for a in (result or {}).get('chunks') or []
                       if a.get('chunk') in ids and a.get('period') in periods})

    prev, gaps = None, 0
    for c in chunks:
        if c.id not in assign:
            gaps += 1
            if prev is None:
                periods.setdefault('T00', {'id': 'T00', 'order': -1.0, 'label': 'unknown time', 'season': '',
                                           'month': '', 'weather': '', 'flashback': False})
                prev = 'T00'
            assign[c.id] = prev
        prev = assign[c.id]
    if gaps:
        logger.warning(f"  ⚠️  timeline: {gaps} chunk(s) without a period → previous chunk's period")
    first_read = {}
    for i, c in enumerate(chunks):
        first_read.setdefault(assign[c.id], i)
    used = sorted((p for p in periods.values() if p['id'] in first_read),
                  key=lambda p: (p['order'], first_read[p['id']]))
    return used, assign


# ── pass 2: references + resolve ────────────────────────────────────────────────

_NULL_FACT = re.compile(r"\s*((none|n/?a|nothing|unknown)\b|not (described|given|mentioned|specified|stated)\b"
                        r"|no\b.*\b(given|described|mentioned|specified|stated)\b)", re.I)
_PLACEHOLDERS = {'', 'none', 'null', 'n-a', 'na', 'unknown', 'unnamed', 'nobody', 'nothing', 'no-one'}


def _references(chunks: list[Chunk], extracted: dict, assign: dict) -> tuple[list[dict], dict[str, dict]]:
    """Every fact becomes a reference (a call site) with a stable id <chunk>/<n>, so an edit in one chunk
    leaves every other reference id — and the enrich caches keyed by them — unchanged.
    → (references in reading order, key → candidate)."""
    refs, cands = [], {}
    story_keys = {ref_key(e.get('ref_name', '')) for c in chunks if not c.setup
                  for e in (extracted.get(c.id) or {}).get('entities') or []}
    for c in chunks:
        demoted, n, said = 0, 0, f" {_stem(c.text)} "
        for e in (extracted.get(c.id) or {}).get('entities') or []:
            key = ref_key(e.get('ref_name', ''))
            if key in _PLACEHOLDERS:
                logger.debug(f"  {c.id}: placeholder entity {e.get('ref_name')!r} dropped")
                continue
            if c.setup and key not in story_keys:  # "the hero", "the son": a setup note never adds an entity
                logger.debug(f"  {c.id}: setup-only entity {e.get('ref_name')!r} dropped")
                continue
            cand = cands.setdefault(key, {'ref_name': e['ref_name'], 'types': {}, 'names': set(), 'roles': [],
                                          'refs': []})
            cand['types'][e.get('type')] = cand['types'].get(e.get('type'), 0) + 1
            # a name the fragment does not contain is made up: 'Ivamoto-Mother', 'Фудзимото +3'
            cand['names'].update(nm for nm in e.get('names') or [] if (s := _stem(nm)) and f" {s} " in said)
            if e.get('role') and e['role'] not in cand['roles']:
                cand['roles'].append(e['role'])
            for f in e.get('facts') or []:
                if _NULL_FACT.match(f.get('fact', '')) and not f.get('quote', '').strip():
                    continue  # "none", "no details given": a placeholder, not a fact
                pos = None if c.setup else _locate(c.text, f.get('quote', ''))
                explicit = bool(f.get('explicit')) and pos is not None
                demoted += bool(f.get('explicit')) and pos is None and not c.setup
                n += 1
                ref = {'id': f'{c.id}/{n}', 'key': key, 'chunk': c.id, 'chapter': c.chapter,
                       'period': assign[c.id], 'kind': f.get('kind', ''), 'fact': f.get('fact', ''),
                       'quote': f.get('quote', ''), 'explicit': explicit,
                       'origin': 'setup' if c.setup else 'story',
                       'offset': None if pos is None else c.start + pos}
                refs.append(ref)
                cand['refs'].append(ref['id'])
        if demoted:
            logger.warning(f"  ⚠️  {c.id}: {demoted} quote(s) not found in the text → deduced")
    return refs, cands


def _type_of(cand: dict) -> str:
    return max(cand['types'], key=cand['types'].get)


_ENDING = re.compile(r'(ами|ями|ого|его|ому|ему|ой|ей|ий|ый|ая|яя|ое|ее|ам|ям|ах|ях|ом|ем|ов|ев|[аяуюеоыиьй])$')


def _stem(name: str) -> str:
    """A name without Russian case endings: «дознавателя» and «Дознаватель» meet."""
    return ' '.join(_ENDING.sub('', w) if len(w) > 4 else w for w in re.findall(r'\w+', name.casefold().replace('ё', 'е')))


def _shared_names(keys: list[str], cands: dict[str, dict]) -> dict[str, list[str]]:
    """key → the other keys that use one of its names, inflection aside."""
    by_stem: dict[str, set[str]] = {}
    for k in keys:
        for n in cands[k]['names']:
            by_stem.setdefault(_stem(n), set()).add(k)
    return {k: sorted({o for n in cands[k]['names'] for o in by_stem[_stem(n)]} - {k}) for k in keys}


_PLACES = ('Room', 'Outdoor')  # a yard or porch is a room in one chapter, outdoors in the next: resolved together


def _resolve_type(cand: dict) -> str:
    return 'place (room or outdoor area)' if _type_of(cand) in _PLACES else _type_of(cand)


def _spelling_variants(keys: list[str]) -> dict[str, list[str]]:
    """key → the other keys that differ from it only in how a word is spelled (toryumon / toryomon)."""
    canon: dict[str, str] = {}
    for t in sorted({t for k in keys for t in k.split('-')}):
        canon[t] = next((c for c in dict.fromkeys(canon.values()) if min(len(t), len(c)) >= 5 and t[0] == c[0]
                         and SequenceMatcher(None, t, c).ratio() >= 0.8), t)
    form = {k: '-'.join(canon[t] for t in k.split('-')) for k in keys}
    return {k: [o for o in keys if o != k and form[o] == form[k]] for k in keys}


def _production_name(name) -> bool:
    """A Title-Case name, not a bare lowercase key ('sad') or an empty one."""
    return isinstance(name, str) and bool(re.search(r'\w', name)) and name.strip()[0].isupper()


def _resolve_prompt(rows: list[str], etype: str, previous: list[list[str]] = ()) -> str:
    before = ("\nThe previous build merged (keep a group unless these rows show it is wrong):\n"
              + "\n".join(f"  {' + '.join(g)}" for g in previous) + "\n") if previous else ''
    return f"""You are a script supervisor merging a novel's {etype} list after a fragment-by-fragment read.
Each row: key | name | names used in the text | role | references | other keys using one of its names or spelling it differently (a hint, not proof: different rooms share a word like "hall").

{chr(10).join(rows)}
{before}
Return merges: groups of keys that denote the SAME entity — one person under first name, surname, nickname, title or rank; one room or car under different names. Different rooms of one house, a person and their outfit stay separate. List only groups of two or more keys, each key at most once; ref_name is the canonical Title-Case-Kebab name: proper names copied from the members' names in the text's own script, in the nominative; everything else English.

Return names: each key whose name is not a production name yet — a common noun in Russian or another language, a bare lowercase key, a vague word — with its production name: Title-Case-Kebab; a place by owner and function (<Owner>-House-Garden, <Owner>-Office); common words in English; proper names exactly as the text writes them. Leave out keys whose name is already right."""


def _resolve(cands: dict[str, dict], llm: BaseLLM, cache: Path, force: bool,
             previous: list[list[str]] = ()) -> dict[str, dict]:
    """canonical key → {ref_name, keys}; per type (rooms and outdoor places together), in batches. Every key
    lands in exactly one group. The same call names each group: a common noun or a bare key the reads left
    becomes a production name, unless it would take another group's name; keys never change.
    previous: the last build's merge groups, shown as a hint (not a cache-key input) so merges stay stable."""
    groups: dict[str, dict] = {}
    taken: set[str] = set()
    renames: dict[str, str] = {}
    by_type: dict[str, list[str]] = {}
    for k, cand in sorted(cands.items()):
        by_type.setdefault(_resolve_type(cand), []).append(k)
    progress = Progress('resolve', sum(-(-len(keys) // RESOLVE_BATCH) for keys in by_type.values() if len(keys) > 1))
    for etype, keys in by_type.items():
        for b in range(0, len(keys), RESOLVE_BATCH):
            batch = keys[b:b + RESOLVE_BATCH]
            if len(batch) < 2:
                continue
            shared, variants = _shared_names(batch, cands), _spelling_variants(batch)
            before = [m for g in previous if len(m := [k for k in g if k in batch]) > 1]
            rows = [f"  {k} | {cands[k]['ref_name']} | {', '.join(sorted(cands[k]['names']))} | "
                    f"{' / '.join(cands[k]['roles'][:2])} | {len(cands[k]['refs'])} | "
                    f"{', '.join(sorted({*shared[k], *variants[k]}))}" for k in batch]
            result = progress.run(lambda: _cached(
                cache / 'resolve' / f'{ref_key(etype)}-{b // RESOLVE_BATCH:03d}.json',
                _hash(rows, _resolve_prompt([], etype)),
                lambda: _ask(llm, _resolve_prompt(rows, etype, before), BIBLE_RESOLVE_SCHEMA), force),
                lambda r: f"{etype}: {len(batch)} name(s), "
                          + ("❌ failed" if r is None else f"{len(r.get('merges') or [])} merge group(s), "
                                                           f"{len(r.get('names') or [])} renamed"))
            if result is None:
                logger.warning(f"  ⚠️  resolve {etype} batch {b // RESOLVE_BATCH}: failed — names stay separate")
            for n in (result or {}).get('names') or []:
                if isinstance(n, dict) and n.get('key') in batch and _production_name(n.get('ref_name')):
                    renames[n['key']] = n['ref_name'].strip()
            for g in (result or {}).get('merges') or []:
                if unknown := set(g.get('keys') or []) - set(batch):
                    logger.warning(f"  ⚠️  resolve: keys outside the batch ignored: {sorted(unknown)}")
                members = [k for k in dict.fromkeys(g.get('keys') or []) if k in batch and k not in taken]
                if len(members) < 2:
                    continue
                canon = ref_key(g.get('ref_name', ''))
                # A canonical key must not steal another entity's key or an earlier group's.
                if not canon or (canon in cands and canon not in members) or canon in groups:
                    canon = members[0]
                groups[canon] = {'ref_name': g.get('ref_name') or cands[members[0]]['ref_name'], 'keys': members}
                taken.update(members)
                logger.info(f"  🔗 {groups[canon]['ref_name']} ← {', '.join(members)}")
    groups.update({k: {'ref_name': c['ref_name'], 'keys': [k]} for k, c in cands.items() if k not in taken})
    _name_groups(groups, cands, renames)
    _absorb_bare(groups, cands)  # after naming: an absorbed spelling never names its owner
    return groups


def _absorb_bare(groups: dict[str, dict], cands: dict[str, dict]) -> None:
    """A group with no facts whose every name is part of a name of exactly one other group of its kind, one with
    facts, is that entity under another spelling the resolve call left apart ('toriiomon-hideo' with
    'Торюмон Хидео', 'Хидео-сан' → 'hideo'): its keys join that group. An unmatched or ambiguous one stays."""
    words = {k: [set(_stem(n).split()) for c in g['keys'] for n in cands[c]['names']] for k, g in groups.items()}
    facts = {k: any(cands[c]['refs'] for c in g['keys']) for k, g in groups.items()}
    kind = {k: _resolve_type(cands[g['keys'][0]]) for k, g in groups.items()}
    for k in [k for k in groups if not facts[k] and words[k]]:
        owners = [o for o in groups if o != k and facts[o] and kind[o] == kind[k]
                  and all(any(w <= m for m in words[o]) for w in words[k])]
        if len(owners) == 1:
            bare = groups.pop(k)
            groups[owners[0]]['keys'] += bare['keys']
            logger.debug(f"  {bare['ref_name']} (no facts) → {groups[owners[0]]['ref_name']}")


def _name_groups(groups: dict[str, dict], cands: dict[str, dict], renames: dict[str, str]) -> None:
    """Each group's production name: a member's rename, else its merge name, else the best-read member's own
    name — the first that is a production name (a rename is the model's explicit fix of a name). Biggest groups choose first; a name another group already took
    falls back to the group's read name, so ref names stay unique."""
    taken: set[str] = set()
    for g in sorted(groups.values(), key=lambda g: -sum(len(cands[k]['refs']) for k in g['keys'])):
        read = max((cands[k]['ref_name'] for k in g['keys']), key=lambda n: (_production_name(n), len(n)))
        options = [*(renames.get(k, '') for k in g['keys']), g['ref_name'] if len(g['keys']) > 1 else '', read]
        name = next((n for n in options if _production_name(n) and ref_key(n) not in taken), g['ref_name'])
        if name != g['ref_name']:
            logger.debug(f"  ✏️  {g['ref_name']} → {name}")
        g['ref_name'] = name
        taken.add(ref_key(name))


# ── pass 3: enrich ──────────────────────────────────────────────────────────────

def _excerpts(refs: list[dict], texts: dict[str, str]) -> list[str]:
    """Source windows around located references; overlapping windows of one chapter are merged."""
    spans: dict[str, list[list]] = {}
    for r in sorted((r for r in refs if r['offset'] is not None), key=lambda r: (r['chapter'], r['offset'])):
        s = max(0, r['offset'] - EXCERPT_RADIUS)
        e = min(len(texts[r['chapter']]), r['offset'] + len(r['quote']) + EXCERPT_RADIUS)
        cur = spans.setdefault(r['chapter'], [])
        if cur and s <= cur[-1][1]:
            cur[-1][1] = max(cur[-1][1], e)
            cur[-1][2].append(r['id'])
        else:
            cur.append([s, e, [r['id']]])
    return [f"[{' '.join(ids)}] {chapter}: «{' '.join(texts[chapter][s:e].split())}»"
            for chapter, cur in spans.items() for s, e, ids in cur]


def _ref_row(r: dict) -> str:
    source = 'setup' if r.get('origin') == 'setup' else 'stated' if r['explicit'] else 'deduced'
    return (f"  {r['id']} | {r['period']} | {r['kind']} | {source} | "
            f"{r['fact']} | «{r['quote']}»")


def _cost(r: dict) -> int:
    """Prompt chars a reference brings: its row and, when located, its source excerpt."""
    return len(_ref_row(r)) + (2 * EXCERPT_RADIUS + len(r['quote']) if r['offset'] is not None else 0)


def _batches(refs: list[dict]) -> list[list[dict]]:
    """Consecutive references (story order) packed so references + excerpts fit ENRICH_BUDGET."""
    out, cur, cost = [], [], 0
    for r in refs:
        c = _cost(r)
        if cur and cost + c > ENRICH_BUDGET:
            out.append(cur)
            cur, cost = [], 0
        cur.append(r)
        cost += c
    return out + [cur] if cur else out


_ENRICH_RULES = """RULES
1. features: one per permanent physical thing — architecture, fixtures, built-in and heavy furniture, a car's body and paint, a face, scars, build — merged across references, with material, colour and where it is (which wall, side, next to what). Not a feature: the place as a whole, its size, light or atmosphere (they go in visual_desc), or something the text says is absent. It is drawn from the entity's FIRST period ({first}) unless a reference says it was added, built, bought or damaged later: applies_from = that first period, even when the text first names it much later. until = the period from which it is gone, empty when never. Ids kebab-case.
2. variants: a look is what an image model must draw differently and what stays that way across shots — an outfit, a hairstyle or makeup, a wound or bandage, dirt, blood or soaked clothes, age; a room redecorated or after a fire; a car after a crash. NOT a look: expression, emotion, mood, pose, gesture, action, where the entity is or who watches it, lighting or time of day, a door or window open or closed, a hand-held item picked up, put down or thrown, how a movable object is mounted or used. The first look is the base (visual_desc), never a variant; an entity that keeps one look has NO variants. One variant per later or alternate look: label (kebab-case), variance (what differs from the base description), time_context (from/to period ids), context (when/where it applies), description (full standalone description for an image model). Clothing and movable things persist until a reference changes them; a colour or detail stated later applies back to the nearest earlier period where the item is worn with no change stated in between (source of the matching feature = inferred, reason names the references).
3. conflicts: references that cannot both be true (blue eyes in one period, brown in another). Keep the earlier in features, list the clash with both ids, never average. Only a permanent feature or a look can conflict: a passing state (expression, pallor, tears, fatigue, a limp, mood, what a hand holds at one moment) never does, nor does a thing replaced or changed later (that is a variant). Two references to one scene, or two spellings or names of one thing, are not a conflict; no clash, no conflicts entry.
4. visual_desc: the full English base description at the first period: every permanent feature, and for a character the clothing of the first look and what is worn or carried on the body throughout it (a watch, a bag, a holstered gun). A thing taken out, used and put away is a prop, not part of the look. Only what is known: never write that something is not described, not specified or none — leave it out.
5. refs: cite the reference ids (s01e002#003/7) each item rests on; only ids listed here. Nothing beyond these references and what follows from them.
6. "setup" references come from the production consultant's notes, not the novel: they fill what the story leaves open (room sizes, distances, where things stand). A stated or deduced story reference wins over a setup one; a clash with a setup reference is never a conflict — drop the setup fact."""


def _enrich_prompt(name: str, etype: str, role: str, periods: str, first: str, refs: list[dict],
                   excerpts: list[str], part: str, world: str = '') -> str:
    return f"""You are a production designer writing the versioned reference for {name} ({etype}): the one description used to draw it in every period of the story.
Role: {role}
Story periods (id | label), in story order:
{periods}
{part}
REFERENCES (id | period | kind | stated/deduced | fact | quote):
{chr(10).join(_ref_row(r) for r in refs)}

SOURCE EXCERPTS around the references (read them: they hold details the reference list dropped):
{chr(10).join(excerpts) or '(none)'}
{_world_block(world, _WORLD_DESCRIBE)}
{_ENRICH_RULES.format(first=first)}"""


def _merge_prompt(name: str, etype: str, periods: str, first: str, parts: list[dict], world: str = '') -> str:
    body = "\n\n".join(f"PART {i + 1}:\n{json.dumps(p, ensure_ascii=False)}" for i, p in enumerate(parts))
    return f"""You are a production designer merging partial versioned references of {name} ({etype}), each written from consecutive story periods.
Story periods (id | label), in story order:
{periods}

{body}

Merge into one: a physical thing described in several parts is one feature (earliest applies_from, union of refs); a look that continues across parts is one variant with the widened time_context; a part that contradicts another is a conflict. Keep every ref id.
{_world_block(world, _WORLD_DESCRIBE)}
{_ENRICH_RULES.format(first=first)}"""


_UNSAID = re.compile(r"\b(?:not|never) (?:described|specified|given|mentioned|stated|provided)\b|:\s*none\b"
                     r"|^\W*no\b[^.;]*\b(?:described|specified|given|mentioned|stated|provided)\b", re.I)
_CLAUSE = re.compile(r'((?<=[.!?])\s+|;\s+|,\s+and\s+(?=(?:its|their|his|her|the|it|they)\b))')  # ". ", "; ", ", and its"


def _said(text: str) -> str:
    """Clauses that say what is NOT in the text ("Clothing is not described.", "…; its colour is not stated") dropped:
    an image prompt would draw them. The rest keeps its punctuation; a cut across a sentence starts a new one."""
    parts = _CLAUSE.split(text.strip())
    out, sep = '', ''
    for i in range(0, len(parts), 2):
        clause = parts[i]
        sep = sep or (parts[i - 1] if i else '')  # after a dropped clause: the separator before it, if not a full stop
        if not clause or _UNSAID.search(clause):
            if not (parts[i - 1] if i else ' ').strip() or clause[-1:] in '.!?':
                sep = ' '                         # the dropped run crossed a sentence end
            continue
        if out and not sep.strip():
            out += '' if out[-1] in '.!?' else '.'
            clause = clause[0].upper() + clause[1:]
        out += (sep if out else '') + clause + ')' * (clause.count('(') - clause.count(')'))
        sep = ''
    return out + ('.' if out and out[-1] not in '.!?' and text.rstrip()[-1:] in '.!?' else '')


def _check_enrich(name: str, result: dict, refs: list[dict], rank: dict[str, int], first: str, last: str) -> dict:
    """Period ids must exist and reference ids must belong to the entity; first_stated comes from the refs."""
    by_id = {r['id']: r for r in refs}
    result['visual_desc'] = _said(result.get('visual_desc') or '')

    def period(value: str, fallback: str) -> str:
        if value in rank:
            return value
        if value:
            logger.warning(f"  ⚠️  {name}: period {value!r} unknown → {fallback}")
        return fallback

    def cited(item: dict) -> list[str]:
        return [i for i in item.get('refs') or [] if i in by_id]

    for f in result.get('features') or []:
        f['id'] = ref_key(f.get('id', '')) or 'feature'
        f['refs'] = cited(f)
        f['applies_from'] = period(f.get('applies_from', ''), first)
        f['until'] = period(f.get('until', ''), '') if f.get('until') else ''
        f['first_stated'] = min((by_id[i]['period'] for i in f['refs']), key=rank.get, default=f['applies_from'])
        if not any(by_id[i]['explicit'] for i in f['refs']):  # setup notes and deductions are not the text's word
            f['source'] = 'inferred'
    for v in result.get('variants') or []:
        v['label'] = ref_key(v.get('label', '')) or 'variant'
        v['refs'] = cited(v)
        v['description'] = _said(v.get('description') or '')
        tc = v.get('time_context') or {}
        lo, hi = period(tc.get('from', ''), first), period(tc.get('to', ''), last)
        v['time_context'] = {'from': lo, 'to': hi} if rank[lo] <= rank[hi] else {'from': hi, 'to': lo}
    def clash(c: dict) -> bool:
        """Story references only, with two different facts from two different quotes. "None identified", a lone
        ref, one sentence cited twice, or any setup ref (it fills gaps, never contradicts) is no clash."""
        cited = [by_id[i] for i in c['refs']]
        if not cited or any(r.get('origin', 'story') != 'story' for r in cited):
            return False
        return (len({_words(r['fact']) for r in cited}) >= 2 and len({_words(r.get('quote', '')) for r in cited}) >= 2
                and bool(c['description']) and not _NULL_FACT.match(c['description']))

    conflicts = [{'description': c.get('description', ''), 'refs': cited(c)} for c in result.get('conflicts') or []]
    if dropped := [c['description'] for c in conflicts if not clash(c)]:
        logger.debug(f"  {name}: non-conflicts dropped: {dropped}")
    result['conflicts'] = [c for c in conflicts if clash(c)]
    return result


def _fallback(refs: list[dict]) -> dict:
    """Enrich failed: keep the raw references so nothing the text said is lost."""
    return {
        'visual_desc': '. '.join(r['fact'] for r in refs if r['kind'] in ('appearance', 'fixture', 'furniture')),
        'features': [{'id': ref_key(r['fact'])[:40] or 'feature', 'description': r['fact'],
                      'applies_from': refs[0]['period'], 'until': '', 'first_stated': r['period'],
                      'source': 'stated' if r['explicit'] else 'inferred', 'reason': '', 'refs': [r['id']]}
                     for r in refs],
        'variants': [], 'conflicts': [], 'consolidated': False,
    }


def _concat(parts: list[dict]) -> dict:
    """Merge failed: the parts side by side, base description from the earliest — finished work is not dropped."""
    return {'visual_desc': next((p['visual_desc'] for p in parts if p.get('visual_desc')), ''),
            **{k: [x for p in parts for x in p.get(k) or []] for k in ('features', 'variants', 'conflicts')},
            'consolidated': False}


@dataclass
class Subject:
    """One entity ready to enrich: what its prompts and cache keys are built from."""
    key: str
    name: str
    etype: str
    role: str
    base: dict                # the entity's bible entry without the description
    refs: list[dict]          # story order
    first: str = ''
    last: str = ''
    legend: str = ''          # its periods first..last, "id | label" rows
    span: tuple = ()          # those period ids: cache keys follow ids, not the model's wording of the labels
    parts: list[list[dict]] = field(default_factory=list)  # budget-sized reference batches; one = fits one call
    world: str = ''           # setting.md's real-world anchor


def _subject(key: str, group: dict, cands: dict, all_refs: list[dict], periods: list[dict]) -> Subject:
    cs = [cands[k] for k in group['keys']]
    rank = {p['id']: i for i, p in enumerate(periods)}
    read = [r for r in all_refs if r['key'] in group['keys']]   # reading order
    refs = sorted(read, key=lambda r: rank[r['period']])         # story order, stable within a period
    types: dict[str, int] = {}
    for c in cs:
        for t, n in c['types'].items():
            types[t] = types.get(t, 0) + n
    etype, name = max(types, key=types.get), latin_name(group['ref_name'])
    roles = [r for c in cs for r in c['roles']]
    base = {'key': key, 'ref_name': name, 'type': etype, 'aliases': sorted({n for c in cs for n in c['names']}),
            'role': roles[0] if roles else '', 'chapters': list(dict.fromkeys(r['chapter'] for r in read)),
            'periods': list(dict.fromkeys(r['period'] for r in refs)), 'refs': refs}
    s = Subject(key, name, etype, ' / '.join(roles[:3]), base, refs)
    if refs:
        s.first, s.last = refs[0]['period'], refs[-1]['period']
        span = periods[rank[s.first]:rank[s.last] + 1]
        s.legend = "\n".join(f"  {p['id']} | {p['label']}" for p in span)
        s.span = tuple(p['id'] for p in span)
        s.parts = _batches(refs)
    return s


def _part(s: Subject, i: int, texts: dict, cache: Path) -> tuple[Path, str, str]:
    """Part i's cache path, cache key and prompt. A one-part entity has the same path and key whether it is
    described alone or in a batch, so either answer serves the other."""
    refs = s.parts[i]
    excerpts = _excerpts(refs, texts)
    part = '' if len(s.parts) == 1 else (
        f"PART {i + 1} of {len(s.parts)}: periods {refs[0]['period']}–{refs[-1]['period']}; "
        "describe only what these references show.\n")
    return (cache / 'entities' / s.key / f'part-{i:03d}.json',
            _hash(_ENRICH_RULES, s.name, s.etype, s.span, refs, excerpts, part, s.world),
            _enrich_prompt(s.name, s.etype, s.role, s.legend, s.first, refs, excerpts, part, s.world))


def _batch_prompt(pack: list[Subject], periods: list[dict], texts: dict) -> str:
    rank = {p['id']: i for i, p in enumerate(periods)}
    lo, hi = min(rank[s.first] for s in pack), max(rank[s.last] for s in pack)
    blocks = "\n\n".join(
        f"ENTITY {s.key}: {s.name} ({s.etype}); role: {s.role}; FIRST period: {s.first}\n"
        f"REFERENCES (id | period | kind | stated/deduced | fact | quote):\n"
        + "\n".join(_ref_row(r) for r in s.refs) for s in pack)
    excerpts = _excerpts([r for s in pack for r in s.refs], texts)
    return f"""You are a production designer writing the versioned references for the {len(pack)} entities below: for each, the one description used to draw it in every period of the story.
Story periods (id | label), in story order:
{chr(10).join(f"  {p['id']} | {p['label']}" for p in periods[lo:hi + 1])}

{blocks}

SOURCE EXCERPTS around the references (read them: they hold details the reference lists dropped):
{chr(10).join(excerpts) or '(none)'}
{_world_block(pack[0].world, _WORLD_DESCRIBE)}
{_ENRICH_RULES.format(first='on its ENTITY line')}
7. entities: one entry per ENTITY above, key = its key. An entry rests only on its own entity's references: a fact about another entity never moves to this one."""


def _well_formed(entry) -> bool:
    return (isinstance(entry, dict) and isinstance(entry.get('visual_desc'), str)
            and all(isinstance(entry.get(k, []), list) for k in ('features', 'variants', 'conflicts')))


def _drop_foreign(result: dict, key: str, owner: dict[str, str]) -> int:
    """Items whose every cited reference of the batch belongs to another entity: a fact moved across entities.
    → how many were dropped. Items citing ids outside the batch are left to _check_enrich, as alone."""
    dropped = 0
    for k in ('features', 'variants', 'conflicts'):
        kept = []
        for item in result.get(k) or []:
            ids = [i for i in (item.get('refs') or []) if i in owner] if isinstance(item, dict) else []
            if ids and all(owner[i] != key for i in ids):
                dropped += 1
            else:
                kept.append(item)
        result[k] = kept
    return dropped


def _enrich_batches(subjects: list[Subject], periods: list[dict], order: list[str], texts: dict, llm: BaseLLM,
                    cache: Path, force: bool, workers: int) -> set[str]:
    """Pass 3a: one-part entities not yet cached, described ENRICH_BATCH per call — grouped by first chapter,
    references + excerpts within ENRICH_BUDGET. Each answer is stored as that entity's own part-000, where the
    solo pass reads it; an entity the reply drops or garbles stays uncached and is described alone.
    → keys stored by this pass."""
    chapter = {c: i for i, c in enumerate(order)}
    todo = sorted((s for s in subjects if len(s.parts) == 1
                   and (force or _cache_get(*_part(s, 0, texts, cache)[:2]) is _MISS)),
                  key=lambda s: (chapter[s.base['chapters'][0]], s.key))
    packs, cur, cost = [], [], 0
    for s in todo:
        c = sum(_cost(r) for r in s.refs)
        if cur and (len(cur) >= ENRICH_BATCH or cost + c > ENRICH_BUDGET):
            packs.append(cur)
            cur, cost = [], 0
        cur.append(s)
        cost += c
    packs = [p for p in packs + [cur] if len(p) > 1]  # a lone entity is described alone, by the solo pass
    if not packs:
        return set()
    logger.info(f"📖 Pass 3a: {sum(map(len, packs))} entit(ies) in {len(packs)} batch(es)...")

    def run(pack: list[Subject]) -> list[str]:
        _local.misses = _fresh_calls() + 1
        reply = _ask(llm, _batch_prompt(pack, periods, texts), BIBLE_ENRICH_BATCH_SCHEMA)
        entries: dict[str, dict] = {}
        for e in (reply or {}).get('entities') or []:
            if _well_formed(e):
                entries.setdefault(ref_key(str(e.get('key') or '')), e)
        owner = {r['id']: s.key for s in pack for r in s.refs}
        stored = []
        for s in pack:
            if (e := entries.get(s.key)) is None:
                continue
            result = {k: v for k, v in e.items() if k != 'key'}
            if n := _drop_foreign(result, s.key, owner):
                logger.warning(f"  ⚠️  {s.name}: {n} item(s) resting on another entity's references dropped")
            path, key, _ = _part(s, 0, texts, cache)
            _cache_put(path, key, result)
            stored.append(s.key)
        return stored

    def status(pack: list[Subject], stored: list[str]) -> str:
        alone = [s.name for s in pack if s.key not in stored]
        return f"{len(stored)}/{len(pack)} described" + (f"; alone next: {_names(alone)}" if alone else '')

    progress, stored = Progress('enrich batches', len(packs)), set()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for done in ex.map(lambda pack: progress.run(lambda: run(pack), lambda r: status(pack, r)), packs):
            stored.update(done)
    return stored


def _enrich(s: Subject, periods: list[dict], texts: dict, llm: BaseLLM, cache: Path, force: bool) -> dict:
    if not s.refs:
        return {**s.base, 'visual_desc': '', 'features': [], 'variants': [], 'conflicts': []}
    rank = {p['id']: i for i, p in enumerate(periods)}

    def call(path: Path, key: str, prompt: str):
        return _cached(path, key, lambda: _ask(llm, prompt, BIBLE_ENRICH_SCHEMA), force)

    if len(s.parts) > 1:
        logger.info(f"  📚 {s.name}: {len(s.refs)} references → {len(s.parts)} parts + merge")
    parts = [call(*_part(s, i, texts, cache)) for i in range(len(s.parts))]
    if any(p is None for p in parts):
        logger.error(f"  ❌ {s.name}: enrich failed — raw references kept")
        return {**s.base, **_fallback(s.refs)}
    level = 0
    while len(parts) > 1:  # hierarchical merge: packs of parts that fit the budget, at least two each
        packs, cur = [], []
        for p in parts:
            if len(cur) >= 2 and len(json.dumps(cur + [p], ensure_ascii=False)) > ENRICH_BUDGET:
                packs.append(cur)
                cur = []
            cur.append(p)
        packs.append(cur)
        level += 1
        merged = [pack[0] if len(pack) == 1 else
                  call(cache / 'entities' / s.key / f'merge-{level}-{j:03d}.json',
                       _hash(_ENRICH_RULES, s.name, s.span, pack, s.world),
                       _merge_prompt(s.name, s.etype, s.legend, s.first, pack, s.world))
                  for j, pack in enumerate(packs)]
        if any(m is None for m in merged):
            logger.error(f"  ❌ {s.name}: merge failed — its parts are kept unmerged")
        parts = [_concat(pack) if m is None else m for m, pack in zip(merged, packs)]
    return {**s.base, **_check_enrich(s.name, parts[0], s.refs, rank, s.first, s.last), 'parts': len(s.parts)}


def _entity_status(e: dict, rank: dict[str, int]) -> str:
    raw = ' ❌ not consolidated' if e.get('consolidated') is False else ''
    parts = f" · {e['parts']} parts" if e.get('parts', 1) > 1 else ''
    return (f"{e['ref_name']} ({e['type']}): {len(e['refs'])} refs → {len(e['features'])} features "
            f"({len(foreshadowed(e, rank))} ⏪), {len(e['variants'])} variants, {len(e['conflicts'])} conflicts"
            f"{parts}{raw}")


# ── build ───────────────────────────────────────────────────────────────────────

def _previous_build(bible_dir: Path) -> dict:
    """The last build's periods and merge groups (member keys of each entity), as hints that keep ids and merges
    stable across rebuilds; none when there is no readable bible."""
    try:
        bible = json.loads((bible_dir / 'story_bible.json').read_text(encoding='utf-8'))
        merges = [sorted({r['key'] for r in e.get('refs') or []}) for e in bible['entities'].values()]
        return {'periods': [p for p in bible.get('periods') or [] if isinstance(p, dict) and p.get('id')],
                'merges': [m for m in merges if len(m) > 1]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {'periods': [], 'merges': []}


def _drop_shared_aliases(entities: dict[str, dict]) -> None:
    """An alias two entities hold ('я', 'мать', a misread merge) names neither: find_entity would pick by dict
    order and mentions() would count it for both."""
    holders: dict[str, set[str]] = {}
    for k, e in entities.items():
        for a in e['aliases']:
            holders.setdefault(_stem(a), set()).add(k)
    for e in entities.values():
        e['aliases'] = [a for a in e['aliases'] if len(holders[_stem(a)]) == 1]


def build_bible(chapter_paths: list[Path], llm: BaseLLM, bible_dir: Path, workers: int, force: bool = False,
                chunk_chars: int = CHUNK_CHARS, gleanings: int = GLEANINGS, world: str = '') -> tuple[dict, list[str]]:
    """Map → timeline → resolve → enrich. Returns (bible, failed story chunk ids; a setup note that fails only
    warns: not cached, the next run reads it again). Writes story_bible.json/.md.
    world: setting.md's real-world anchor; extraction and descriptions read the book in its era (part of the keys).
    A chapter's setup appendix (<dir>/appendix/<id>.md, written by `logic`) is read as setup references:
    no time cues, the chapter's first period, outranked by story references."""
    order = [p.stem for p in chapter_paths]
    if len(set(order)) != len(order):
        raise ValueError(f"duplicate chapter ids: {sorted({c for c in order if order.count(c) > 1})}")
    texts = {p.stem: p.read_text(encoding='utf-8') for p in chapter_paths}
    story = [replace(c, world=world) for ch in order for c in chunk_chapter(ch, texts[ch], chunk_chars)]
    setup = [replace(c, chapter=p.stem, setup=True, world=world) for p in chapter_paths
             if (a := p.parent / 'appendix' / f'{p.stem}.md').is_file()
             for c in chunk_chapter(f'{p.stem}@setup', a.read_text(encoding='utf-8'), chunk_chars)]
    if not story:
        raise ValueError("the chapter files hold no text")
    cache = bible_dir / '.cache'
    previous = _previous_build(bible_dir)

    logger.info(f"📖 Pass 1: {len(story)} story + {len(setup)} setup chunk(s) of {len(order)} chapter(s), "
                f"up to {gleanings} re-read(s) each story chunk...")
    progress, seen = Progress('chunks', len(story) + len(setup)), set()

    def read(batch: list[Chunk], rereads: int, stored: set[str] = frozenset()) -> dict:
        with ThreadPoolExecutor(max_workers=workers) as ex:  # a batch answer stored this run is read back, even forced
            return dict(zip((c.id for c in batch), ex.map(lambda c: progress.run(
                lambda: _extract(c, llm, rereads, cache, force and c.id not in stored), _chunk_status(c, seen)),
                batch)))

    results = read(story, gleanings)
    cast: dict[str, dict[str, str]] = {}  # chapter → its story entities, what its setup note may attach to
    for c in story:
        for e in (results[c.id] or {}).get('entities') or []:
            if (k := ref_key(e.get('ref_name', ''))) not in _PLACEHOLDERS:
                cast.setdefault(c.chapter, {}).setdefault(
                    k, f"- {e['ref_name']} ({e.get('type')}): {', '.join(e.get('names') or [])}")
    if skipped := sorted({c.chapter for c in setup if c.chapter not in cast}):
        logger.warning(f"  ⚠️  setup notes of {', '.join(skipped)} wait for their story chunks — re-run")
    setup = [replace(c, known=tuple(cast[c.chapter].values())) for c in setup if c.chapter in cast]
    progress.total = len(story) + len(setup)
    notes_batched = _extract_setup_batches(setup, llm, cache, force, workers)
    results |= read(setup, 0, notes_batched)  # a note is a list: one read; re-reads only made up entities
    chunks = story + setup
    notes = {c.id for c in setup}
    unread = [cid for cid, r in results.items() if r is None or r.get('partial')]
    for cid in unread:
        if cid in notes:  # a setup note only fills gaps: the bible is whole without it, the chain goes on
            logger.warning(f"  ⚠️  {cid}: setup note not read — the chapter's planned sizes and objects are missing; "
                           f"not cached, the next run reads it again")
        else:
            logger.error(f"  ❌ {cid}: " + ("a re-read failed — its first-read facts are used, not cached" if results[cid]
                                           else "extraction failed — its facts are missing from the bible"))
    failed = [cid for cid in unread if cid not in notes]
    extracted = {cid: r for cid, r in results.items() if r is not None}

    logger.info("📖 Pass 1b: story timeline...")
    periods, assign = _timeline(story, extracted, llm, cache, force, previous['periods'])
    first = {}
    for c in story:
        first.setdefault(c.chapter, assign[c.id])
    assign |= {c.id: first.get(c.chapter, periods[0]['id']) for c in setup}  # setup notes are timeless
    refs, cands = _references(chunks, extracted, assign)

    logger.info(f"📖 Pass 1 found {len(cands)} name(s), {len(refs)} reference(s) over {len(periods)} period(s). "
                f"Pass 2: resolving names...")
    groups = _resolve(cands, llm, cache, force, previous['merges'])

    subjects = {k: replace(_subject(k, g, cands, refs, periods), world=world) for k, g in groups.items()}
    batched = _enrich_batches(list(subjects.values()), periods, order, texts, llm, cache, force, workers)
    logger.info(f"📖 Pass 3: enriching {len(groups)} entit(ies), biggest first...")
    rank = {p['id']: i for i, p in enumerate(periods)}
    progress = Progress('enrich', len(groups))
    # stored by a batch first (instant, so the ETA rate sees only real calls), then the rest biggest first
    biggest = sorted(groups, key=lambda k: (k not in batched, -len(subjects[k].refs)))
    with ThreadPoolExecutor(max_workers=workers) as ex:  # a batch answer stored this run is read back, even forced
        entities = dict(zip(biggest, ex.map(
            lambda k: progress.run(lambda: _enrich(subjects[k], periods, texts, llm, cache, force and k not in batched),
                                   lambda e: _entity_status(e, rank)), biggest)))
    _drop_shared_aliases(entities)

    bible = {
        'version': VERSION,
        'periods': periods,
        'chapters': [{'id': ch, 'path': str(path), 'sha': hashlib.sha256(texts[ch].encode()).hexdigest(),
                      'chunks': [c.id for c in story if c.chapter == ch],
                      'periods': list(dict.fromkeys(assign[c.id] for c in story if c.chapter == ch))}
                     for ch, path in zip(order, chapter_paths)],
        'entities': dict(sorted(entities.items(), key=lambda kv: (kv[1]['type'], kv[0]))),
        'conflicts_by_chapter': conflicts_by_chapter(entities, order),
    }
    bible_dir.mkdir(parents=True, exist_ok=True)
    (bible_dir / 'story_bible.json').write_text(json.dumps(bible, ensure_ascii=False, indent=1), encoding='utf-8')
    (bible_dir / 'story_bible.md').write_text(render_markdown(bible), encoding='utf-8')
    return bible, failed


def conflicts_by_chapter(entities: dict, order: list[str]) -> dict[str, list[dict]]:
    """Each conflict goes to the chapters that must change: every cited story chapter but the earliest, which
    is canon. A conflict inside one chapter has no canon to align with: it stays in the entity's conflicts for a
    human, never goes to the fixer. Setup references never count."""
    rank, out = {c: i for i, c in enumerate(order)}, {}
    for e in entities.values():
        by_id = {r['id']: r for r in e['refs'] if r.get('origin', 'story') == 'story'}
        for c in e.get('conflicts') or []:
            cited = [by_id[i] for i in c['refs'] if i in by_id]
            chapters = sorted({r['chapter'] for r in cited}, key=rank.get)
            for ch in chapters[1:]:
                out.setdefault(ch, []).append({
                    'entity': e['ref_name'], 'description': c['description'],
                    'canon': [{k: r[k] for k in ('chapter', 'quote', 'fact')} for r in cited if r['chapter'] != ch],
                    'fix': [{k: r[k] for k in ('chapter', 'quote', 'fact')} for r in cited if r['chapter'] == ch]})
    return dict(sorted(out.items(), key=lambda kv: rank[kv[0]]))


# ── consumers ───────────────────────────────────────────────────────────────────

def _rank(bible: dict) -> dict[str, int]:
    return {p['id']: i for i, p in enumerate(bible['periods'])}


def foreshadowed(entity: dict, rank: dict[str, int]) -> list[dict]:
    """Features drawn before the text names them: the reason this tool exists."""
    return [f for f in entity.get('features') or []
            if rank.get(f['applies_from'], 0) < rank.get(f['first_stated'], 0)]


def render_markdown(bible: dict) -> str:
    rank = _rank(bible)
    chapters_of = {}
    for ch in bible['chapters']:
        for p in ch['periods']:
            chapters_of.setdefault(p, []).append(ch['id'])
    out = ["# Story bible", "", "| period | label | season | month | weather | chapters |", "|---|---|---|---|---|---|"]
    out += [f"| {p['id']}{' ↩' if p.get('flashback') else ''} | {p['label']} | {p['season']} | {p['month']} | "
            f"{p['weather']} | {', '.join(chapters_of.get(p['id'], []))} |" for p in bible['periods']]
    for e in bible['entities'].values():
        early = {f['id'] for f in foreshadowed(e, rank)}
        out += ["", f"## {e['ref_name']} ({e['type']})", "",
                f"key `{e['key']}` · {len(e['refs'])} reference(s) · periods {', '.join(e['periods'])} · "
                f"aliases: {', '.join(e['aliases'])}", "", e['role'], "", e['visual_desc']]
        if e.get('features'):
            out += ["", "| feature | from | until | first named | source | description | refs |",
                    "|---|---|---|---|---|---|---|"]
            out += [f"| {'⏪ ' if f['id'] in early else ''}`{f['id']}` | {f['applies_from']} | {f['until']} | "
                    f"{f['first_stated']} | {f['source']} | {f['description']}"
                    f"{' — ' + f['reason'] if f.get('reason') else ''} | {' '.join(f['refs'])} |"
                    for f in e['features']]
        if e.get('variants'):
            out += ["", "| variant | time | context | variance | refs |", "|---|---|---|---|---|"]
            out += [f"| `{v['label']}` | {v['time_context']['from']}–{v['time_context']['to']} | {v['context']} | "
                    f"{v['variance']} | {' '.join(v['refs'])} |" for v in e['variants']]
        out += [f"- ⚠️ {c['description']} ({' '.join(c['refs'])})" for c in e.get('conflicts') or []]
    return "\n".join(out) + "\n"


def load_bible(bible_dir: Path) -> dict | None:
    path = bible_dir / 'story_bible.json'
    if not path.exists():
        return None
    bible = json.loads(path.read_text(encoding='utf-8'))
    if bible.get('version') != VERSION:
        logger.warning(f"  ⚠️  {path}: version {bible.get('version')} ≠ {VERSION} — ignored; re-run `make bible`")
        return None
    return bible


def find_entity(bible: dict | None, name: str) -> dict | None:
    """By key, ref_name or any alias the text used; a ref's view suffix is ignored."""
    if not bible:
        return None
    k = ref_key(area_of(name))
    return bible['entities'].get(k) or next(
        (e for e in bible['entities'].values() if k in {ref_key(a) for a in e['aliases']} | {ref_key(e['ref_name'])}),
        None)


def entity_block(bible: dict, entity: dict, window: tuple[int, int] | None = None) -> str:
    """Features and variants in force over a period-rank window (all when None)."""
    rank, label = _rank(bible), {p['id']: p['label'] for p in bible['periods']}
    lo, hi = window or (0, len(rank))
    lines = [f"- {entity['ref_name']} ({entity['type']}): {entity['visual_desc']}"]
    for f in entity.get('features') or []:
        if rank[f['applies_from']] > hi or (f['until'] and rank[f['until']] <= lo):
            continue
        early = f" — first named later ({label[f['first_stated']]}), must already be visible" \
            if rank[f['first_stated']] > rank[f['applies_from']] else ''
        gone = f" — gone from {label[f['until']]}" if f['until'] else ''
        lines.append(f"    [{f['id']}] {f['description']}{early}{gone}")
    for v in entity.get('variants') or []:
        a, b = rank[v['time_context']['from']], rank[v['time_context']['to']]
        if a <= hi and b >= lo:
            lines.append(f"    variant {v['label']} ({label[v['time_context']['from']]} – "
                         f"{label[v['time_context']['to']]}; {v['context']}): {v['description']}")
    return "\n".join(lines)


def chapter_window(bible: dict, chapter: str) -> tuple[int, int] | None:
    """Period-rank range a chapter covers; None when the bible does not have it."""
    ch = next((c for c in bible['chapters'] if c['id'] == chapter), None)
    if not ch:
        return None
    ranks = [_rank(bible)[p] for p in ch['periods']] or [0]
    return min(ranks), max(ranks)


def chapter_texts(bible: dict) -> dict[str, str]:
    """Chapter id → text for chapters whose file is unchanged since the bible was built (offsets hold)."""
    out = {}
    for ch in bible['chapters']:
        path = Path(ch.get('path') or '')
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8')
        if hashlib.sha256(text.encode()).hexdigest() == ch.get('sha'):
            out[ch['id']] = text
        else:
            logger.warning(f"  ⚠️  {path} changed since the bible was built — its excerpts are skipped; re-run `make bible`")
    return out


def mentions(entity: dict, texts: dict[str, str]) -> int:
    """Whole-word occurrences of the entity's aliases (inflected forms included) in its chapters' texts."""
    if not entity['aliases']:
        return 0
    names = '|'.join(map(re.escape, sorted(entity['aliases'], key=len, reverse=True)))
    pattern = re.compile(rf'(?<!\w)(?:{names})(?!\w)', re.IGNORECASE)
    return sum(len(pattern.findall(texts.get(ch, ''))) for ch in entity['chapters'])


def needs_ref(entity: dict, texts: dict[str, str] | None = None) -> bool:
    """Anything the book shows more than in passing: 3+ references or 2+ chapters, or a character named
    MENTIONS+ times (a lead the text barely describes still needs a face). A one-off extra (a messenger,
    a corridor) gets no ref; the screenplay stages it as background."""
    return (len(entity['refs']) >= 3 or len(entity['chapters']) >= 2
            or entity['type'] == 'Character' and mentions(entity, texts or {}) >= MENTIONS)


def place_block(bible: dict | None, base: str) -> str:
    """detail-rooms context: the place's whole-book features."""
    entity = find_entity(bible, base)
    if not entity:
        if bible:
            logger.warning(f"  ⚠️  {base}: not in the story bible")
        return ''
    return ("## STORY BIBLE — every feature the whole book uses in this place (each needs an entry; "
            "variants are later states, not extra objects):\n" + entity_block(bible, entity))
