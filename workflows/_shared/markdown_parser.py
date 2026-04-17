"""Shared header/section parser for plain_markdown importers.

The plain_markdown ingress mode is the lowest-common-denominator way to
hand-write a workflow surface artifact. Each surface's importer pairs
with a tiny markdown schema (documented in importers/README.md):

    # Surface Title (h1, single, treated as document title)

    ## Section Name
    free-text content...

    ## Another Section
    - bullet
    - bullet

    ## Key/Value Section
    key1: value1
    key2: value2

This module exposes ``parse_sections`` returning ``{section: lines}``,
plus ``parse_bullets`` and ``parse_kv_block`` for the common content
shapes within a section.
"""

from __future__ import annotations

import re
from pathlib import Path

_HEADER = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
_BULLET = re.compile(r"^\s*[-*+]\s+(.*?)\s*$")
_KV = re.compile(r"^\s*([A-Za-z0-9_][A-Za-z0-9_ -]*?)\s*:\s+(.*?)\s*$")


def parse_sections(text: str, *, level: int = 2) -> dict[str, list[str]]:
    """Split markdown text into ``{section_title: [content_lines]}`` at the
    given header ``level``. Content above the first matching header is
    discarded. Section titles are stripped and lower-cased into snake_case
    so callers don't have to remember capitalisation.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in text.splitlines():
        match = _HEADER.match(raw)
        if match and len(match.group(1)) == level:
            title = _slugify(match.group(2))
            sections[title] = []
            current = title
            continue
        if current is None:
            continue
        sections[current].append(raw.rstrip())
    # Strip trailing blank lines per section.
    for key, lines in sections.items():
        while lines and not lines[-1].strip():
            lines.pop()
    return sections


def parse_bullets(lines: list[str]) -> list[str]:
    """Return the bullet contents from a block of lines.

    Lines that don't match the bullet pattern are ignored — this lets a
    section freely mix prose and bullet lists.
    """
    out: list[str] = []
    for line in lines:
        match = _BULLET.match(line)
        if match:
            out.append(match.group(1).strip())
    return out


def parse_kv_block(lines: list[str]) -> dict[str, str]:
    """Parse ``key: value`` pairs from a block of lines.

    Multi-line values are NOT supported — keep keys on their own line.
    Lines that don't match the kv pattern are skipped.
    """
    out: dict[str, str] = {}
    for line in lines:
        match = _KV.match(line)
        if match:
            key = _slugify(match.group(1))
            out[key] = match.group(2).strip()
    return out


def join_prose(lines: list[str]) -> str:
    """Collapse a block of lines into a single trimmed prose string.

    Blank lines become paragraph breaks (\\n\\n); single newlines become
    spaces. Bullets are dropped (use ``parse_bullets`` for those).
    """
    paragraphs: list[list[str]] = [[]]
    for line in lines:
        if _BULLET.match(line):
            continue
        if not line.strip():
            paragraphs.append([])
            continue
        paragraphs[-1].append(line.strip())
    return "\n\n".join(" ".join(p) for p in paragraphs if p).strip()


def _slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")
