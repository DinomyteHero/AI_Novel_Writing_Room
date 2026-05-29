"""Build an outline-planner artifact from a hand-written markdown file."""

from __future__ import annotations

import re
from pathlib import Path

from workflows._shared.markdown_parser import (
    parse_kv_block,
    parse_sections,
    read_text,
)

_CHAPTER_TITLE = re.compile(r"^chapter_(\d+)(?:_(.+))?$")


def import_from_markdown(path: str | Path) -> dict:
    """Return an outline-planner artifact dict from a markdown file."""
    text = read_text(path)
    sections = parse_sections(text)

    structural_kv = parse_kv_block(sections.get("brooks_alignment", []))
    structural_notes = (
        {"brooks_alignment": structural_kv} if structural_kv else None
    )

    outline: list[dict] = []
    for title, lines in sections.items():
        match = _CHAPTER_TITLE.match(title)
        if not match:
            continue
        chapter_no = int(match.group(1))
        kv = parse_kv_block(lines)
        entry: dict = {"chapter_number": chapter_no}
        for k in ("chapter_title", "synopsis", "pov_character", "structural_phase"):
            if k in kv:
                entry[k] = kv[k]
        if "estimated_word_count" in kv:
            try:
                entry["estimated_word_count"] = int(kv["estimated_word_count"])
            except ValueError:
                pass
        # Bullet lists for arc_phases_active and subplot_ids in nested level-3.
        outline.append(entry)
    outline.sort(key=lambda e: e["chapter_number"])

    artifact: dict = {
        "surface": "outline-planner",
        "schema_version": "1.0",
        "outline": outline,
    }
    if structural_notes:
        artifact["structural_notes"] = structural_notes

    subplots = _parse_id_list(sections.get("subplots", []), "subplot_id")
    if subplots:
        artifact["subplots"] = subplots
    hooks = _parse_id_list(sections.get("hooks", []), "hook_id")
    if hooks:
        artifact["hooks"] = hooks
    revelations = _parse_id_list(
        sections.get("revelation_schedule", []), "revelation_id",
    )
    if revelations:
        artifact["revelation_schedule"] = revelations
    promises = _parse_id_list(
        sections.get("promise_payoff_ledger", []), "promise_id",
    )
    if promises:
        artifact["promise_payoff_ledger"] = promises

    return artifact


def _parse_id_list(lines: list[str], id_field: str) -> list[dict]:
    """Parse a section like:

        - id: SUB_01
          name: Royal politics
          function: subplot

    Returns a list of dicts; the first non-bullet, non-`key: value` line
    starts a new entry. This is a deliberately simple shape — for richer
    content, use legacy_seed importer or hand-author the JSON.
    """
    items: list[dict] = []
    current: dict | None = None
    for line in lines:
        bullet = re.match(r"^\s*[-*+]\s+([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        kv = re.match(r"^\s+([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if bullet:
            if current is not None:
                items.append(current)
            current = {bullet.group(1): bullet.group(2).strip()}
        elif kv and current is not None:
            current[kv.group(1)] = kv.group(2).strip()
    if current is not None:
        items.append(current)
    # Promote the first key to id_field if not already keyed that way.
    out: list[dict] = []
    for item in items:
        if id_field not in item:
            # First key is treated as the id.
            for k in list(item.keys()):
                item[id_field] = item.pop(k)
                break
        out.append(item)
    return out
