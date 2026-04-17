"""Extract an outline-planner artifact from a legacy concept_seed.json.

Pulls structural_notes plus the planner-level skeletons (subplots, hooks,
revelation_schedule, promise_payoff_ledger) and per-character arc_phase_maps.
The chapter outline list is derived from extracted scene cards when
available, since legacy seeds don't carry an outline-only field.
"""

from __future__ import annotations

import copy
from pathlib import Path

from workflows._shared.legacy_seed_loader import (
    load_extracted_scene_cards,
    pick,
)
from workflows.outline_planner.api import OutlinePlannerSurface


def import_from_seed(
    seed: dict,
    *,
    extracted_scene_cards_dir: str | Path | None = None,
) -> dict:
    """Return an outline-planner artifact dict extracted from ``seed``.

    When ``extracted_scene_cards_dir`` is supplied, the chapter outline is
    derived from the extracted scene cards via
    ``OutlinePlannerSurface.project_to_outline``. Otherwise the outline is
    derived from the seed's embedded ``scene_cards`` array (which may be
    empty in post-extraction seeds, in which case the outline list will be
    empty and the surface validator will report it).
    """
    artifact: dict = {
        "surface": "outline-planner",
        "schema_version": "1.0",
    }

    structural_notes = pick(seed, "structural_notes")
    if structural_notes is not None:
        artifact["structural_notes"] = structural_notes

    for key in ("subplots", "hooks", "revelation_schedule", "promise_payoff_ledger"):
        value = pick(seed, key)
        if value is not None:
            artifact[key] = value

    # arc_phase_maps reside under each character's weiland_arc; collect them
    # by name so the bundle compiler can reapply via apply_arc_phase_maps.
    arc_phase_maps: dict = {}
    for char in seed.get("ensemble_cast") or []:
        weiland = char.get("weiland_arc") or {}
        phase_map = weiland.get("arc_phase_map")
        if phase_map:
            arc_phase_maps[char.get("name", "")] = copy.deepcopy(phase_map)
    if arc_phase_maps:
        artifact["arc_phase_maps"] = arc_phase_maps

    # Outline list: prefer extracted cards (canonical post-installer state),
    # fall back to embedded seed.scene_cards (workshop-form pre-installer).
    cards: list[dict] = []
    if extracted_scene_cards_dir is not None:
        cards = load_extracted_scene_cards(extracted_scene_cards_dir)
    if not cards:
        cards = list(seed.get("scene_cards") or [])
    artifact["outline"] = OutlinePlannerSurface.project_to_outline(cards)

    return artifact
