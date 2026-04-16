"""Shared helpers for locating prose features by paragraph index.

Quality Polish targets specific paragraphs when it edits — a paragraph
index is more actionable than "line 42" because the polish model doesn't
see raw line numbers. These helpers convert between line-based and
paragraph-based coordinates using a consistent definition of paragraph:
blocks separated by one or more blank lines.
"""

from __future__ import annotations

import re


_WORD_BOUNDARY_TEMPLATE = r"\b{}\b"


def split_paragraphs(prose: str) -> list[str]:
    """Split prose into paragraphs on blank lines.

    Returns a list of paragraph strings in order, with surrounding
    whitespace stripped. Empty paragraphs are omitted.
    """
    return [p.strip() for p in re.split(r"\n\s*\n", prose) if p.strip()]


def line_to_paragraph_index(prose: str, line_num: int) -> int:
    """Convert a 1-indexed line number to a 0-indexed paragraph index.

    A paragraph is the run of non-blank lines ended by a blank line (or
    the end of the prose). Lines that fall inside a blank separator are
    mapped to the paragraph immediately preceding them (the one that
    just ended), which keeps hit locations stable even when the telling
    word sits on a terminator line.

    Lines beyond the end of the prose clamp to the last paragraph.
    """
    if line_num < 1:
        return 0
    lines = prose.split("\n")
    clamped = min(line_num, len(lines))

    in_paragraph = False
    paragraph_index = -1
    for i, line in enumerate(lines, start=1):
        is_blank = not line.strip()
        if not is_blank and not in_paragraph:
            in_paragraph = True
            paragraph_index += 1
        elif is_blank:
            in_paragraph = False
        if i == clamped:
            return max(0, paragraph_index if paragraph_index >= 0 else 0)

    return max(0, paragraph_index)


def paragraph_indices_for_word(prose: str, word: str) -> list[int]:
    """Return the 0-indexed paragraph indices whose text contains ``word``.

    Matching is case-insensitive and respects word boundaries so that
    ``"silence"`` does not match ``"silenced"``. Multi-word phrases are
    matched as a literal substring (after regex-escaping).
    """
    if not word:
        return []

    if " " in word:
        pattern = re.compile(re.escape(word), re.IGNORECASE)
    else:
        pattern = re.compile(_WORD_BOUNDARY_TEMPLATE.format(re.escape(word)), re.IGNORECASE)

    hits: list[int] = []
    for idx, paragraph in enumerate(split_paragraphs(prose)):
        if pattern.search(paragraph):
            hits.append(idx)
    return hits
