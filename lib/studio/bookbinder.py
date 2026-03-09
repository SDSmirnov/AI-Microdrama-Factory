"""
bookbinder.py — Split a novel into filmable episode chunks for vertical microdrama.

Strategy: sliding windows of [_TAIL_CHAPTERS context] + [_BATCH_SIZE chapters to split].
The LLM returns a short verbatim text anchor (first ~15 words of the last paragraph
before each cut). The host resolves that anchor to a paragraph index and slices
the original prose byte-for-byte — no rewriting, no numbering errors.
"""
import inspect
import logging
import re
from pathlib import Path

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

_BATCH_SIZE = 2    # chapters per window (content to split)
_TAIL_CHAPTERS = 1 # chapters of narrative overlap (context only)
_WORDS_WARN = 45_000
_ANCHOR_MATCH_LEN = 40  # chars used for paragraph matching


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


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


def _find_split_paragraph(paragraphs: list[str], anchor: str, search_from: int) -> int:
    """
    Find the paragraph index whose text best matches `anchor`.
    Uses first _ANCHOR_MATCH_LEN chars; falls back to a shorter 20-char match.
    Returns -1 if not found.
    """
    needle_long = anchor.strip()[:_ANCHOR_MATCH_LEN].lower()
    needle_short = anchor.strip()[:20].lower()
    if not needle_short:
        return -1
    for i in range(search_from, len(paragraphs)):
        if paragraphs[i].lower().startswith(needle_long):
            return i
    for i in range(search_from, len(paragraphs)):
        if needle_short in paragraphs[i].lower():
            return i
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
    kwargs: dict = {"schema": _WINDOW_SCHEMA}
    if "max_tokens" in inspect.signature(llm.make_json).parameters:
        kwargs["max_tokens"] = 16_000

    data = llm.make_json(prompt, **kwargs)
    raw_splits = data.get("splits") or []

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
      1. Detect chapter boundaries.
      2. For each window of _BATCH_SIZE chapters (+ _TAIL_CHAPTERS context):
         - Send raw prose text (no numbering).
         - LLM returns verbatim 15-word anchors marking split points.
         - Host resolves anchors to paragraph indices.
      3. Write original prose slices verbatim to output_dir/s<SS>eNNN.txt.

    Raises RuntimeError if all windows return no splits.
    """
    paragraphs = _split_paragraphs(text)
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

    for batch_idx in range(0, n_chapters, _BATCH_SIZE):
        batch_end = min(batch_idx + _BATCH_SIZE, n_chapters)
        content_start = chapter_starts[batch_idx]
        content_end = chapter_starts[batch_end]

        tail_chapter_idx = max(0, batch_idx - _TAIL_CHAPTERS)
        tail_start = chapter_starts[tail_chapter_idx]
        tail_end = content_start

        logger.info(
            f"  → Window {batch_idx // _BATCH_SIZE + 1}: "
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
