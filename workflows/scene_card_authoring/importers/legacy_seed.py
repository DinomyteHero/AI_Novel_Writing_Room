"""Extract a scene-card-authoring artifact from a legacy concept_seed.json.

A legacy seed has scene cards in one of two states:

1. **Post-extraction**: ``seed["scene_cards"]`` is empty and the canonical
   per-scene files live at ``data/franchises/<fr>/books/<bk>/scene_cards/
   chapter_NN_scene_NN.json``. The committed Ruusan seed is in this state.

2. **Pre-extraction (workshop form)**: ``seed["scene_cards"]`` carries the
   compressed workshop format (one card per chapter with ``scene_goal``,
   ``scene_conflict``, ``location`` etc.) that the translator must
   normalise.

This importer accepts both: when ``extracted_scene_cards_dir`` is supplied
and contains files, those win; otherwise the embedded list is used.
"""

from __future__ import annotations

import copy
from pathlib import Path

from workflows._shared.legacy_seed_loader import load_extracted_scene_cards


def import_from_seed(
    seed: dict,
    *,
    extracted_scene_cards_dir: str | Path | None = None,
    structural_overrides: dict | None = None,
) -> dict:
    """Return a scene-card-authoring artifact dict extracted from ``seed``."""
    cards: list[dict] = []
    if extracted_scene_cards_dir is not None:
        cards = load_extracted_scene_cards(extracted_scene_cards_dir)
    if not cards:
        cards = [copy.deepcopy(c) for c in seed.get("scene_cards") or []]

    artifact: dict = {
        "surface": "scene-card-authoring",
        "schema_version": "1.0",
        "scene_cards": cards,
    }
    if structural_overrides:
        artifact["structural_overrides"] = copy.deepcopy(structural_overrides)
    return artifact
