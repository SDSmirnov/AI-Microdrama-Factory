"""fixer.py — Logic/physics/space bug fixer + scene prerequisites appendix generator.

Two-pass per chapter:
  1. Зануда-логик pass: fixes physical / spatial / temporal / causal errors in prose.
  2. Appendix pass: generates "Place Setup and Decorations Master" from fixed text.
"""
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from lib.core.utils import CYR_TO_LAT
from lib.llm.base import BaseLLM, accepted
from lib.studio.archivist import Progress, _cached, _hash, _locate

logger = logging.getLogger(__name__)

_CHAPTER_RE = re.compile(r'(?m)^(?=## )')

_ZANUDA_SYSTEM = """Ты — "ЗАНУДА-ЛОГИК", строгий редактор по логике, физике и пространству.

Обязательные проверки:

1. ФИЗИЧЕСКАЯ ЛОГИКА:
   - Каждое описание звука, движения, ощущения — возможно ли это физически?
   - Соответствуют ли глаголы свойствам взаимодействующих объектов?
   - Пример ошибки: "морось стучала" (морось не стучит — она моросит)
   - Пример ошибки: "керамика царапнула ворс" (керамика скребёт или шуршит, но не царапает мягкий ворс)
   - Взаимодействие с предметами, движения, падения, прыжки, бег - нет ли нарушений физики и биомеханики?

2. ПРОСТРАНСТВЕННАЯ ЛОГИКА:
   - Не телепортируются ли персонажи? Соответствуют ли расстояния времени перемещения?
   - Видит / слышит ли персонаж то, что физически возможно с его позиции?
   - Помещаются ли все объекты и персонажи в описанном пространстве?
   - Не противоречат ли детали окружения (тип пола, расположение мебели) друг другу в разных частях текста?

3. ВРЕМЕННАЯ ЛОГИКА:
   - Нет ли скачков или необъяснённых дыр во времени?
   - Может ли персонаж успеть сделать всё описанное за указанное время?
   - Логично ли время суток / освещение / погода для хода событий?
   - Не происходят ли одновременно действия, требующие последовательности?
   - Тайминг слов (речь 130-150 слов в минуту) и действий?
   - Скорость движений и перемещений?

4. ЛОГИКА ПОСЛЕДСТВИЙ:
   - Если персонаж получил травму, удар или физическое воздействие — есть ли последствия?
   - Соответствует ли реакция тела описанному воздействию (боль, кровь, потеря равновесия)?
   - Правоваые и нормативные ограничения мира?

6. КИНЕМАТОГРАФИЧЕСКАЯ ДОСТОВЕРНОСТЬ (текст будут снимать живые актёры, без супергеройских эффектов):
   - Прыжки, рывки, удары, отбрасывания, падения — в пределах возможностей обычного человека.
   - Пример ошибки: "прыгнул на пять метров прямо в Джека и отбросил его на три метра в дверь" — это комикс.
     Исправление: "в два шага сократил дистанцию и всем весом впечатал Джека спиной в дверь".
   - Сохраняй драматический эффект, меняй масштаб.

5. ПРИЧИННО-СЛЕДСТВЕННЫЕ СВЯЗИ:
   - Логично ли следуют события друг за другом? Нет ли пропущенных промежуточных этапов?
   - Откуда персонаж знает то, о чём говорит? Не использует ли он знания, которые ещё не получал?

ПРАВИЛА РЕДАКТУРЫ:
- Исправляй только найденные ошибки. Не трогать стиль, метафоры, ритм, авторский голос.
- Не добавлять новые сцены, персонажей, сюжетные повороты.
- Обсценная лексика и сцены насилия допустимы.
- Выдать исправленный текст и все претензии."""

_APPENDIX_SYSTEM = """Ты — технический консультант по локациям и реквизиту для кино и театра.
По готовому тексту главы ты составляешь техническое приложение "Мастер сеттинга и декораций" —
список физических и пространственных предусловий, необходимых для того, чтобы все описанные
в тексте действия были физически возможны.

Для каждой локации, упомянутой в главе, укажи:

1. **Локация**: название / тип пространства; размеры: ширина × глубина × высота в метрах
   (оценка по типу помещения и действиям, если текст их не даёт — пометь "оценка")
2. **Обязательные объекты**: что должно находиться в сцене и где (примерное расположение)
3. **Пространственные требования**: минимальные расстояния, проходы, свободное пространство,
   необходимые для описанных действий
4. **Состояние объектов до начала сцены**: в каком виде должны быть предметы
   (пример: "на столе лежат бумаги", "дверь приоткрыта", "стул стоит у окна")
5. **Физические условия**: освещение, погода, время суток — если это влияет на возможность
   описанных действий

Пример рассуждения: герой спотыкается и падает на стол, сметая бумаги, поэтому:
- нужен предмет для спотыкания (порог, ковёр, брошенная вещь, чья-то нога)
- от точки спотыкания до стола — 1–2 м, стол в направлении падения
- на столе до начала сцены лежат бумаги
- свободное пространство для падения тела — не менее 1,5 м

Пиши по-русски. Будь конкретен. Это технический документ для постановщика, а не критика текста."""


_TEXT_MARK, _CLAIMS_MARK = '=== ТЕКСТ ===', '=== ПРЕТЕНЗИИ ==='
LOGIC_REPLY_TOKENS = 32_000     # an episode and its claims are ~12k; a looping model stops here, not at 100k
LOGIC_REASONING_TOKENS = 8_000  # thinking cap on top of the reply: uncapped, nemotron-3.5 spent up to 38k (2026-11-26)
_WORD_RATIO = (0.85, 1.3)  # fixed/original words outside this: the fix dropped or rewrote prose — rejected
_OUTPUT_RULES = (
    f"ФОРМАТ ОТВЕТА — ровно два раздела:\n{_TEXT_MARK}\n<полный исправленный текст, без комментариев>\n"
    f"{_CLAIMS_MARK}\n<претензии списком: цитата → проблема → исправление; пусто, если правок нет>"
)


def _split_reply(reply: str) -> tuple[str, str] | None:
    """(text, claims) from a marked reply; None when the text section is missing."""
    if _TEXT_MARK not in (reply or ''):
        return None
    body = reply.split(_TEXT_MARK, 1)[1]
    text, _, claims = body.partition(_CLAIMS_MARK)
    return (text.strip(), claims.strip()) if text.strip() else None


def _words_ok(original: str, fixed: str) -> bool:
    ratio = len(fixed.split()) / max(1, len(original.split()))
    return _WORD_RATIO[0] <= ratio <= _WORD_RATIO[1]


_MIXED = re.compile(r'\w*(?:[a-zA-Z][а-яёА-ЯЁ]|[а-яёА-ЯЁ][a-zA-Z])\w*')


def _unmixed(original: str, fixed: str, label: str) -> str:
    """fixed with every word written in two scripts that the original lacks ("amerики", a decoding slip) put back
    as the original word it romanizes to; one with no such word is kept and reported."""
    known = set(_MIXED.findall(original))
    by_latin = {w.lower().translate(CYR_TO_LAT): w for w in re.findall(r'\w+', original)}

    def restore(m: re.Match) -> str:
        word = m.group()
        if word in known:
            return word
        if found := by_latin.get(word.lower().translate(CYR_TO_LAT)):
            logger.warning(f"  ⚠️  {label}: {word!r} → {found!r} (mixed scripts)")
            return found
        logger.warning(f"  ⚠️  {label}: {word!r} mixes Latin and Cyrillic letters — check it")
        return word

    return _MIXED.sub(restore, fixed)


def _split_chapters(text: str) -> list[str]:
    parts = _CHAPTER_RE.split(text)
    return [p.strip() for p in parts if p.strip()]


def _fix_chapter(chapter_text: str, chapter_num: int, llm: BaseLLM, setting: str = "") -> tuple[str, str]:
    """Run both passes on one chapter. Returns (fixed_text, appendix)."""
    zanuda_system = _ZANUDA_SYSTEM
    if setting and setting.strip():
        zanuda_system = (
            f"КОНТЕКСТ МИРА И СЕТТИНГА (используй как эталон достоверности):\n\n"
            f"{setting.strip()}\n\n"
            f"---\n\n"
            f"{_ZANUDA_SYSTEM}"
        )

    logger.info(f"  [ch.{chapter_num}] logic fix pass...")
    try:
        fixed = _text(
            llm,
            prompt=(
                f"Используй роль ЗАНУДА-ЛОГИК.\n\n"
                f"Задача (по шагам):\n"
                f"1) Проанализируй главу по критериям: ФИЗИЧЕСКАЯ ЛОГИКА, ПРОСТРАНСТВЕННАЯ "
                f"ЛОГИКА, ВРЕМЕННАЯ ЛОГИКА, ЛОГИКА ПОСЛЕДСТВИЙ, ПРИЧИННО-СЛЕДСТВЕННЫЕ СВЯЗИ.\n"
                f"2) Внеси ВСЕ исправления непосредственно в текст.\n"
                f"3) Выдай исправленный полный текст главы {chapter_num} "
                f"Текст главы {chapter_num}:\n\n{chapter_text}"
            ),
            system_prompt=zanuda_system,
        )
        if not fixed or not fixed.strip():
            logger.warning(f"  [ch.{chapter_num}] empty fix response, using original")
            fixed = chapter_text
        fixed = _unmixed(chapter_text, fixed, f"ch.{chapter_num}")
    except Exception as e:
        logger.error(f"  [ch.{chapter_num}] fix pass failed: {e}")
        fixed = chapter_text

    logger.info(f"  [ch.{chapter_num}] appendix pass...")
    try:
        appendix = _text(
            llm,
            prompt=(
                f"По тексту главы {chapter_num} составь техническое приложение "
                f"\"Мастер сеттинга и декораций\".\n\n"
                f"Текст главы:\n\n{fixed}"
            ),
            system_prompt=_APPENDIX_SYSTEM,
        )
        if not appendix or not appendix.strip():
            appendix = "_нет данных_"
    except Exception as e:
        logger.error(f"  [ch.{chapter_num}] appendix pass failed: {e}")
        appendix = "_ошибка генерации_"

    return fixed, appendix


def fix_novel(text: str, llm: BaseLLM, max_workers: int = 5, setting: str = "") -> str:
    """Fix all chapters in parallel. Returns combined fixed text with per-chapter appendixes."""
    chapters = _split_chapters(text)
    if not chapters:
        logger.warning("No '## ' chapter headers found — treating entire text as one chapter")
        chapters = [text.strip()]

    logger.info(f"Fixing {len(chapters)} chapter(s) with up to {max_workers} workers...")

    results: dict[int, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_fix_chapter, ch, i + 1, llm, setting): i
            for i, ch in enumerate(chapters)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results[idx] = future.result()
                logger.info(f"  [ch.{idx + 1}] done")
            except Exception as e:
                logger.error(f"  [ch.{idx + 1}] failed: {e}")
                results[idx] = (chapters[idx], "_ошибка_")

    parts = []
    for i in range(len(chapters)):
        fixed, appendix = results[i]
        parts.append(fixed)
        parts.append(
            f"\n\n---\n"
            f"### ПРИЛОЖЕНИЕ: Мастер сеттинга и декораций — Глава {i + 1}\n\n"
            f"{appendix}\n\n"
            f"---"
        )

    return "\n\n".join(parts)


# ── book mode: episode files in, prose and setup appendix out ─────────────────

def _system(setting: str) -> str:
    return (f"КОНТЕКСТ МИРА И СЕТТИНГА (используй как эталон достоверности):\n\n{setting.strip()}\n\n---\n\n"
            if setting and setting.strip() else '') + _ZANUDA_SYSTEM


def fix_episode(text: str, label: str, llm: BaseLLM, setting: str = '') -> dict | None:
    """Logic fix + setup appendix for one episode → {text, claims, appendix}; None when the fix is unusable
    (no marked text, or the word count drifted outside _WORD_RATIO)."""
    reply = _text(
            llm,
        prompt=(f"Используй роль ЗАНУДА-ЛОГИК. Проанализируй эпизод {label} по всем шести критериям, внеси ВСЕ "
                f"исправления прямо в текст и выдай его полностью.\n\n{_OUTPUT_RULES}\n\nТекст эпизода:\n\n{text}"),
        system_prompt=_system(setting))
    parsed = _split_reply(reply)
    if not parsed:
        logger.error(f"  ❌ {label}: fix reply has no {_TEXT_MARK} section")
        return None
    fixed, claims = parsed
    if not _words_ok(text, fixed):
        logger.error(f"  ❌ {label}: fix changed the length {len(text.split())} → {len(fixed.split())} words — rejected")
        return None
    fixed = _unmixed(text, fixed, label)
    appendix = _text(
            llm,
        prompt=f"По тексту эпизода {label} составь техническое приложение \"Мастер сеттинга и декораций\".\n\n"
               f"Текст эпизода:\n\n{fixed}",
        system_prompt=_APPENDIX_SYSTEM)
    if not (appendix or '').strip():
        logger.error(f"  ❌ {label}: empty appendix")
        return None
    return {'text': fixed, 'claims': claims, 'appendix': appendix.strip()}


def _conflict_prompt(label: str, items: list[dict], text: str) -> str:
    def refs(rs):
        return "\n".join(f"    [{r['chapter']}] «{r['quote']}» — {r['fact']}" for r in rs) or "    (нет)"
    blocks = "\n\n".join(f"{i + 1}. {c['entity']}: {c['description']}\n  КАНОН (другие эпизоды, не меняется):\n"
                          f"{refs(c['canon'])}\n  ИСПРАВИТЬ В ЭТОМ ЭПИЗОДЕ:\n{refs(c['fix'])}"
                          for i, c in enumerate(items))
    return (f"Используй роль ЗАНУДА-ЛОГИК. Библия всей книги нашла противоречия между эпизодом {label} и "
            f"другими эпизодами.\n\n{blocks}\n\nПРАВИЛА:\n"
            "- Исправь ТОЛЬКО эти противоречия, приведя эпизод к КАНОНУ.\n"
            "- Меняй только предложения с цитатами из раздела ИСПРАВИТЬ; весь остальной текст — дословно.\n"
            "- Если это не настоящее противоречие (мимолётное состояние, разные моменты, план и то, что случилось на "
            "самом деле), верни текст без изменений и напиши об этом в правках.\n"
            "- Не добавляй сцен-подготовок и новых описаний: то, что появится позже, покажет визуал.\n\n"
            f"{_OUTPUT_RULES}\n\nТекст эпизода:\n\n{text}")


def _text(llm: BaseLLM, prompt: str, system_prompt: str) -> str:
    return llm.make_text(prompt=prompt, system_prompt=system_prompt, **accepted(
        llm.make_text, max_tokens=LOGIC_REPLY_TOKENS, reasoning_tokens=LOGIC_REASONING_TOKENS))


_SENTENCE = re.compile(r'.*?(?:[.!?…]+[»"”)]*\s+|\n+|$)', re.S)


def _cited_only(text: str, fixed: str, quotes: list[str]) -> tuple[str, int]:
    """fixed with every changed run of sentences that holds none of the quotes put back as in text: a conflict
    fix may touch only the sentences it cites. → (text, runs put back)."""
    old, new = [u for u in _SENTENCE.findall(text) if u], [u for u in _SENTENCE.findall(fixed) if u]
    out, reverted = [], 0
    for op, i1, i2, j1, j2 in SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        span = ''.join(old[i1:i2])
        cited = span.strip() and any(_locate(span, q) is not None or _locate(q, span) is not None for q in quotes)
        if op == 'equal' or cited:
            out += new[j1:j2]
        else:
            out += old[i1:i2]
            reverted += span.split() != ''.join(new[j1:j2]).split()  # whitespace alone is no change
    return ''.join(out), reverted


def fix_conflicts(text: str, label: str, items: list[dict], llm: BaseLLM, setting: str = '') -> dict | None:
    """Targeted fix of the bible's cross-episode conflicts → {text, claims}; None when unusable or when
    more than the cited sentences changed (word similarity below 0.9). Changes outside the cited sentences
    are put back."""
    parsed = _split_reply(_text(llm, prompt=_conflict_prompt(label, items, text), system_prompt=_system(setting)))
    if not parsed:
        logger.error(f"  ❌ {label}: conflict reply has no {_TEXT_MARK} section")
        return None
    fixed, claims = parsed
    similarity = SequenceMatcher(None, text.split(), fixed.split(), autojunk=False).ratio()
    if similarity < 0.9:
        logger.error(f"  ❌ {label}: conflict fix rewrote too much (word similarity {similarity:.2f}) — rejected")
        return None
    fixed, reverted = _cited_only(text, _unmixed(text, fixed, label), [r['quote'] for c in items for r in c['fix']])
    if reverted:
        logger.warning(f"  ⚠️  {label}: {reverted} change(s) outside the cited sentences put back")
    return {'text': fixed, 'claims': claims}


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + '\n', encoding='utf-8')


def fix_book(raw_dir: Path, out_dir: Path, llm: BaseLLM, workers: int, setting: str = '',
             force: bool = False) -> list[str]:
    """raw_dir/*.txt → out_dir/<same>.txt (fixed prose only) + out_dir/appendix/<same>.md (setup for the bible)
    + <same>.claims.md (review). Cached by raw text and prompts; the prose is rewritten only when its raw text or
    prompts changed, so a later conflict fix survives re-runs. → failed episode ids."""
    paths = sorted(raw_dir.glob('*.txt'))
    if not paths:
        raise FileNotFoundError(f"no episode files in {raw_dir}")
    state = out_dir / '.logic'
    logger.info(f"🧐 Logic: {len(paths)} episode(s) {raw_dir} → {out_dir}")
    progress = Progress('logic', len(paths))

    def one(p: Path) -> tuple[str, dict | None]:
        text = p.read_text(encoding='utf-8')
        key = _hash('fix', _ZANUDA_SYSTEM, _APPENDIX_SYSTEM, _OUTPUT_RULES, setting, text)
        result = _cached(state / f'{p.stem}.json', key, lambda: fix_episode(text, p.stem, llm, setting), force)
        base = state / f'{p.stem}.base'  # key of the fix the prose file was written from
        if result and (force or not (out_dir / p.name).exists() or not base.exists()
                       or base.read_text() != key):
            _write(out_dir / p.name, result['text'])
            _write(out_dir / 'appendix' / f'{p.stem}.md', result['appendix'])
            _write(out_dir / 'appendix' / f'{p.stem}.claims.md', result['claims'] or '_нет правок_')
            base.write_text(key)
        return p.stem, result

    def describe(r):
        stem, result = r
        if result is None:
            return f"{stem}: ❌ no usable fix — re-run to retry"
        claims = sum(1 for line in result['claims'].splitlines() if line.strip())
        return f"{stem}: {len(result['text'].split()):,} words, {claims} claim line(s)"

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda p: progress.run(lambda: one(p), describe), paths))
    return [stem for stem, r in results if r is None]


def fix_book_conflicts(out_dir: Path, bible: dict, llm: BaseLLM, workers: int, setting: str = '',
                       force: bool = False) -> tuple[list[str], list[str]]:
    """Apply the bible's cross-episode conflicts to out_dir/<episode>.txt, once per conflict set and prose version
    (keyed by the conflicts and the fix the prose was written from, not the text, so a re-run never applies them
    twice, and prose rewritten by `logic` gets them again). → (fixed ids, failed ids)."""
    todo = bible.get('conflicts_by_chapter') or {}
    if not todo:
        logger.info("🧐 Logic: the bible reports no cross-episode conflicts")
        return [], []
    logger.info(f"🧐 Logic: {sum(map(len, todo.values()))} conflict(s) in {len(todo)} episode(s)")
    state = out_dir / '.logic'
    progress = Progress('conflicts', len(todo))

    def one(stem: str) -> tuple[str, str]:
        path = out_dir / f'{stem}.txt'
        if not path.exists():
            logger.error(f"  ❌ {path}: missing")
            return stem, 'failed'
        items = todo[stem]
        base = state / f'{stem}.base'
        key = _hash('conflicts', _OUTPUT_RULES, setting, items, base.read_text() if base.exists() else '')
        marker = state / f'{stem}.conflicts.applied'
        if not force and marker.exists() and marker.read_text() == key:
            return stem, 'applied before'
        text = path.read_text(encoding='utf-8')
        result = _cached(state / f'{stem}.conflicts.json', key,
                         lambda: fix_conflicts(text, stem, items, llm, setting), force)
        if result is None:
            return stem, 'failed'
        _write(path, result['text'])
        claims = out_dir / 'appendix' / f'{stem}.claims.md'
        _write(claims, (claims.read_text(encoding='utf-8') if claims.exists() else '')
               + '\n\n## Противоречия с другими эпизодами\n\n' + (result['claims'] or '_нет правок_'))
        marker.write_text(key)
        return stem, 'fixed'

    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda s: progress.run(
            lambda: one(s), lambda r: f"{r[0]}: {len(todo[r[0]])} conflict(s) — {r[1]}"), sorted(todo)))
    return [s for s, r in results if r == 'fixed'], [s for s, r in results if r == 'failed']
