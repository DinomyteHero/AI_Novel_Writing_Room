"""Helpers for the per-surface ``importers/legacy_seed.py`` modules.

A "legacy seed" is a pre-Phase-4 ``concept_seed.json`` that was authored
either by hand or by the monolithic concept workshop. The legacy_seed
importers split such a seed into the six surface artifacts so a Ruusan-style
project can roll forward into the workflow kit without rewriting content.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


def load_seed(path: str | Path) -> dict:
    """Load a concept_seed.json from disk."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_extracted_scene_cards(scene_cards_dir: str | Path) -> list[dict]:
    """Load all extracted scene card JSON files from a directory.

    Returns cards sorted by (chapter_number, scene_number). Returns an
    empty list when the directory does not exist or contains no matching
    files.
    """
    p = Path(scene_cards_dir)
    if not p.exists():
        return []
    cards: list[dict] = []
    for path in p.glob("chapter_*_scene_*.json"):
        cards.append(json.loads(path.read_text(encoding="utf-8")))
    cards.sort(
        key=lambda c: (c.get("chapter_number", 0), c.get("scene_number", 0))
    )
    return cards


def pick(seed: dict, key: str, default: Any = None) -> Any:
    """Return a deep copy of ``seed[key]`` or ``default`` when missing/falsy.

    Returns ``default`` (not a deepcopy of it) when the key is absent or
    its value is empty/None — this matches importer semantics where an
    omitted slice should be omitted from the output rather than carried
    as an empty container.
    """
    if key not in seed:
        return default
    value = seed[key]
    if value in (None, "", [], {}):
        return default
    return copy.deepcopy(value)
