"""fixer.py — Logic/physics/space bug fixer + scene prerequisites appendix generator.

Two-pass per chapter:
  1. Зануда-логик pass: fixes physical / spatial / temporal / causal errors in prose.
  2. Appendix pass: generates "Place Setup and Decorations Master" from fixed text.
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from lib.llm.base import BaseLLM

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

1. **Локация**: название / тип пространства
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
        fixed = llm.make_text(
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
    except Exception as e:
        logger.error(f"  [ch.{chapter_num}] fix pass failed: {e}")
        fixed = chapter_text

    logger.info(f"  [ch.{chapter_num}] appendix pass...")
    try:
        appendix = llm.make_text(
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
