"""
bookbinder.py — Split a novel into filmable episode chunks for vertical microdrama.

Strategy: sliding windows of [_TAIL_CHAPTERS context] + [chapters to split, ~_WINDOW_WORDS words].
The LLM returns a short verbatim text anchor (first ~15 words of the last paragraph
before each cut). The host resolves that anchor to a paragraph index and slices
the original prose byte-for-byte — no rewriting, no numbering errors.
"""
import logging
import re
import textwrap
from pathlib import Path

from lib.llm.base import accepted

logger = logging.getLogger(__name__)

_WINDOW_SCHEMA = {
    "type": "object",
    "properties": {
        "splits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "split_after_text": {
                        "type": "string",
                        "description": "Exact first 15 words of the last paragraph before the cut, copied verbatim from the text.",
                    },
                    "cliffhanger_reason": {"type": "string"},
                },
                "required": ["split_after_text", "cliffhanger_reason"],
            },
        }
    },
    "required": ["splits"],
}

# Chapter-boundary patterns — Russian and English prose
_CHAPTER_RES = [
    re.compile(r"^(Глава|ГЛАВА|Часть|ЧАСТЬ|Эпилог|ЭПИЛОГ|Пролог|ПРОЛОГ)\b", re.UNICODE),
    re.compile(r"^(Chapter|CHAPTER|Part|PART|Epilogue|Prologue)\b"),
    re.compile(r"^\*{3}$|^\*\s+\*\s+\*$"),
    re.compile(r"^#{1,3}\s+\S"),
    re.compile(r"^—\s*\d+\s*—$"),
    re.compile(r"^\d+\s*$"),
]

_WINDOW_WORDS = 6000  # content words per window, rounded up to a chapter boundary: room for 2–4 episodes
_TAIL_CHAPTERS = 1    # chapters of narrative overlap (context only)
# Back matter (notes, comments): its numbered entries look like chapter numbers and are not story.
_BACK_MATTER_RE = re.compile(
    r"^(Примечания|Комментарии|Сноски|Notes|Endnotes|Footnotes|Glossary|Глоссарий)\.?$", re.IGNORECASE)
_WORDS_WARN = 45_000
_ANCHOR_MATCH_LEN = 40  # chars used for paragraph matching


_LONG_LINE = 150  # hard-wrapped prose never has lines this long; when 5%+ of lines do, a line is a paragraph
_FALLBACK_WORDS = 2500  # episode size when a window gets no usable reply
SPLIT_REASONING_TOKENS = 8_000  # thinking cap on top of the reply: uncapped, nemotron-3.5 spent ~20k per window
_MIN_EPISODE_WORDS = 800  # a shorter episode is merged into its neighbour


_ILLUSTRATION = re.compile(r'[ \t]*\[(?:Картинка|Рисунок|Иллюстрация|Image|Picture|Illustration):[^\]\n]*\]', re.I)
_INDENTED = re.compile(r'^(?: {2,}|\t)\S', re.M)  # lib.ru-style prose: hard-wrapped lines, each paragraph opens indented
_LIBRU_FOOTER = re.compile(r'^Last-modified: .*(?:\n.*){0,5}\Z', re.M)  # lib.ru's tail: a timestamp, counter ids


def _split_paragraphs(text: str) -> list[str]:
    """Blank-line blocks for hard-wrapped text; one paragraph per line when lines are whole paragraphs
    (blank lines then only separate sections, and a block would be a whole section); an indented line opens
    a paragraph when 5%+ of lines are indented (beyond the indent all lines share)."""
    text = textwrap.dedent(text)
    lines = [line for line in text.splitlines() if line.strip()]
    if lines and sum(len(line) > _LONG_LINE for line in lines) >= 0.05 * len(lines):
        return [line.strip() for line in lines]
    if lines and len(_INDENTED.findall(text)) >= 0.05 * len(lines):
        text = _INDENTED.sub(lambda m: '\n' + m.group(), text)
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _even_ends(paragraphs: list[str], start: int, end: int) -> list[int]:
    """Even paragraph-boundary cuts, the episode count nearest to _FALLBACK_WORDS each, for a window the
    model did not split."""
    counts = [len(p.split()) for p in paragraphs[start:end]]
    n = max(1, round(sum(counts) / _FALLBACK_WORDS))
    ends, words, k = [], 0, 1
    for i, c in enumerate(counts[:-1]):
        words += c
        if k < n and words >= k * sum(counts) / n:
            ends.append(start + i + 1)
            k += 1
    return ends + [end]


def _merge_short(paragraphs: list[str], ends: list[int]) -> list[int]:
    """Drop cuts that leave an episode under _MIN_EPISODE_WORDS: it joins the next one (the last joins the
    previous)."""
    out, start = [], 0
    for e in ends:
        if sum(len(p.split()) for p in paragraphs[start:e]) >= _MIN_EPISODE_WORDS or e == ends[-1]:
            out.append(e)
            start = e
    if len(out) > 1 and sum(len(p.split()) for p in paragraphs[out[-2]:out[-1]]) < _MIN_EPISODE_WORDS:
        del out[-2]
    return out


def _strip_back_matter(paragraphs: list[str]) -> list[str]:
    """Drop everything from a back-matter heading on; only in the second half by words (notes are many short
    paragraphs), so story text never triggers it."""
    half, words = sum(len(p.split()) for p in paragraphs) / 2, 0
    for i, p in enumerate(paragraphs):
        if words >= half and _BACK_MATTER_RE.match(p.strip()):
            logger.info(f"✂️  Back matter from §{i + 1} ({paragraphs[i].strip()!r}, "
                        f"{len(paragraphs) - i} paragraph(s)) is not story — dropped")
            return paragraphs[:i]
        words += len(p.split())
    return paragraphs


def _windows(paragraphs: list[str], chapter_starts: list[int]) -> list[tuple[int, int]]:
    """Chapter-index ranges [a, b) whose content reaches _WINDOW_WORDS (the last takes the rest)."""
    out, a, words = [], 0, 0
    for c in range(len(chapter_starts) - 1):
        words += sum(len(p.split()) for p in paragraphs[chapter_starts[c]:chapter_starts[c + 1]])
        if words >= _WINDOW_WORDS:
            out.append((a, c + 1))
            a, words = c + 1, 0
    if a < len(chapter_starts) - 1:
        out.append((a, len(chapter_starts) - 1))
    return out


def _detect_chapter_starts(paragraphs: list[str]) -> list[int]:
    """Return sorted paragraph indices that open a new chapter/section."""
    starts = [0]
    for i, p in enumerate(paragraphs[1:], start=1):
        first_line = p.splitlines()[0].strip()
        for pat in _CHAPTER_RES:
            if pat.match(first_line):
                starts.append(i)
                break
    return starts


def _words(text: str) -> str:
    """Lowercase words joined by single spaces: punctuation, dash and space variants (NBSP after a dialogue
    dash, «» vs "") and ё/е do not break a verbatim anchor match."""
    return " ".join(re.findall(r"\w+", text.lower().replace("ё", "е")))


def _find_split_paragraph(paragraphs: list[str], anchor: str, search_from: int) -> int:
    """
    Index of the first paragraph from `search_from` that starts with `anchor`'s first _ANCHOR_MATCH_LEN
    chars (compared as words, see _words); else the first containing its first 20. -1 if none.
    """
    needle = _words(anchor)
    if not needle:
        return -1
    texts = [_words(p) for p in paragraphs[search_from:]]
    for prefix, test in ((needle[:_ANCHOR_MATCH_LEN], str.startswith), (needle[:20], str.__contains__)):
        for i, t in enumerate(texts):
            if test(t, prefix):
                return search_from + i
    return -1


def _build_window_prompt(
    paragraphs: list[str],
    tail_range: tuple[int, int],
    content_range: tuple[int, int],
    shrinker_prompt: str,
) -> str:
    tail_start, tail_end = tail_range
    content_start, content_end = content_range

    parts = [shrinker_prompt, "\n\n---\n"]

    if tail_start < tail_end:
        parts.append(
            "## CONTEXT (read for story continuity — do NOT split here)\n\n"
        )
        parts.append("\n\n".join(paragraphs[tail_start:tail_end]))
        parts.append("\n\n")

    parts.append("## TEXT TO SPLIT\n\n")
    parts.append("\n\n".join(paragraphs[content_start:content_end]))

    content_words = sum(len(p.split()) for p in paragraphs[content_start:content_end])

    parts.append(
        "\n\n---\n"
        "## YOUR TASK\n\n"
        "Identify episode split points within the **TEXT TO SPLIT** section above.\n\n"
        "For each split point return:\n"
        "- `split_after_text`: the **exact first 15 words** of the LAST paragraph "
        "before the cut, copied verbatim from the TEXT TO SPLIT. "
        "Do NOT paraphrase, do NOT translate, do NOT alter punctuation.\n"
        "- `cliffhanger_reason`: ≤ 20 words in English describing the dramatic hook.\n\n"
        f"The TEXT TO SPLIT contains ~{content_words:,} words. "
        "Target chunk size: 1 500–3 000 words. Avoid < 1 000 or > 4 500.\n"
        "The LAST split point must cover the final paragraph of the TEXT TO SPLIT "
        "(i.e. `split_after_text` starts with the first words of that last paragraph).\n"
        "Return JSON: {\"splits\": [{\"split_after_text\": \"...\", \"cliffhanger_reason\": \"...\"}]}\n"
    )
    return "".join(parts)


def _call_window(
    llm,
    prompt: str,
    paragraphs: list[str],
    content_start: int,
    content_end: int,
    prev_split_end: int,
) -> list[int]:
    """
    Call LLM for one window. Resolve text anchors to paragraph indices.
    Returns sorted list of end-paragraph indices (exclusive: slice [:idx+1]).
    Always includes content_end as the final boundary.
    """
    kwargs = {"schema": _WINDOW_SCHEMA, **accepted(llm.make_json, max_tokens=33_000,
                                                    reasoning_tokens=SPLIT_REASONING_TOKENS)}

    data = None
    for attempt in (1, 2):  # an empty or unparseable reply gets one retry
        try:
            data = llm.make_json(prompt, **kwargs)
        except (ValueError, RuntimeError) as e:
            logger.warning(f"  ⚠️  Window §{content_start + 1}–§{content_end}: bad reply (attempt {attempt}): {e}")
            continue
        if isinstance(data, dict) and data.get("splits"):
            break
        logger.warning(f"  ⚠️  Window §{content_start + 1}–§{content_end}: no splits (attempt {attempt})")
    if not isinstance(data, dict) or not data.get("splits"):
        ends = _even_ends(paragraphs, content_start, content_end)
        logger.error(f"  ❌ Window §{content_start + 1}–§{content_end}: no usable reply — cut at paragraph "
                     f"boundaries into {len(ends)} episode(s) of ~{_FALLBACK_WORDS} words, no cliffhanger choice")
        return ends
    raw_splits = data["splits"]

    resolved: list[int] = []
    search_from = content_start

    for s in raw_splits:
        anchor = s.get("split_after_text", "").strip()
        reason = s.get("cliffhanger_reason", "")
        if not anchor:
            continue
        idx = _find_split_paragraph(paragraphs, anchor, search_from)
        if idx == -1:
            logger.warning(f"  ⚠️  Anchor not found: {anchor[:50]!r} — skipped")
            continue
        if not (content_start <= idx < content_end):
            logger.warning(
                f"  ⚠️  Anchor resolved to §{idx + 1} outside window "
                f"[{content_start + 1}–{content_end}] — skipped"
            )
            continue
        end_idx = idx + 1  # exclusive end: paragraphs[prev:end_idx]
        resolved.append(end_idx)
        logger.debug(f"    §{idx + 1} — {reason}")
        search_from = idx + 1

    # Guarantee window end is always a boundary
    if not resolved or resolved[-1] != content_end:
        if resolved:
            logger.warning(f"  ⚠️  No split at window end §{content_end}; appending")
        resolved.append(content_end)

    return sorted(set(resolved))


def split_book(
    text: str,
    llm,
    shrinker_prompt: str,
    output_dir: Path,
    season: int = 1,
) -> list[Path]:
    """
    Split `text` into filmable episode chunks using sliding chapter windows.

    Processing:
      1. Drop back matter (notes); detect chapter boundaries.
      2. For each window of whole chapters reaching _WINDOW_WORDS (+ _TAIL_CHAPTERS context):
         - Send raw prose text (no numbering).
         - LLM returns verbatim 15-word anchors marking split points.
         - Host resolves anchors to paragraph indices.
      3. Write original prose slices verbatim to output_dir/s<SS>eNNN.txt.

    Raises RuntimeError if all windows return no splits.
    """
    paragraphs = _strip_back_matter(_split_paragraphs(_LIBRU_FOOTER.sub('', _ILLUSTRATION.sub('', text))))  # e-book "[Картинка: _01.jpg]"
    n_para = len(paragraphs)
    n_words = len(text.split())
    logger.info(f"📖 Book: {n_words:,} words, {n_para} paragraphs")
    if n_words > _WORDS_WARN:
        logger.warning(f"⚠️  Large book ({n_words:,} words) — windowed processing active.")

    chapter_starts = _detect_chapter_starts(paragraphs)
    chapter_starts.append(n_para)  # sentinel
    n_chapters = len(chapter_starts) - 1
    logger.info(f"📑 {n_chapters} chapter(s) detected at §§: {chapter_starts[:-1]}")

    all_ends: list[int] = []
    prev_split_end = 0
    windows = _windows(paragraphs, chapter_starts)

    for window_idx, (batch_idx, batch_end) in enumerate(windows):
        content_start = chapter_starts[batch_idx]
        content_end = chapter_starts[batch_end]

        tail_chapter_idx = max(0, batch_idx - _TAIL_CHAPTERS)
        tail_start = chapter_starts[tail_chapter_idx]
        tail_end = content_start

        logger.info(
            f"  → Window {window_idx + 1}/{len(windows)}: "
            f"context §{tail_start + 1}–§{tail_end} | "
            f"split §{content_start + 1}–§{content_end}"
        )

        prompt = _build_window_prompt(
            paragraphs,
            (tail_start, tail_end),
            (content_start, content_end),
            shrinker_prompt,
        )
        ends = _call_window(llm, prompt, paragraphs, content_start, content_end, prev_split_end)
        all_ends.extend(ends)
        if ends:
            prev_split_end = ends[-1]

    if not all_ends:
        raise RuntimeError("LLM returned no split points across all windows.")

    # Deduplicate, sort, guarantee book end
    unique_ends = sorted(set(all_ends))
    if unique_ends[-1] != n_para:
        unique_ends.append(n_para)
    if (merged := _merge_short(paragraphs, unique_ends)) != unique_ends:
        logger.info(f"  🔗 {len(unique_ends) - len(merged)} episode(s) under {_MIN_EPISODE_WORDS} words merged "
                    "into a neighbour")
        unique_ends = merged

    # Write output files
    ep_prefix = f"s{season:02d}e"
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    prev_end = 0

    for ep_num, end_idx in enumerate(unique_ends, start=1):
        chunk_text = "\n\n".join(paragraphs[prev_end:end_idx])
        out_path = output_dir / f"{ep_prefix}{ep_num:03d}.txt"
        out_path.write_text(chunk_text, encoding="utf-8")
        words = len(chunk_text.split())
        logger.info(f"  ✓ {out_path.name}: §{prev_end + 1}–§{end_idx} ({words:,} words)")
        written.append(out_path)
        prev_end = end_idx

    return written
