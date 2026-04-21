"""JSON-schema validation tests for Slice 5 artifacts.

Checks ``schemas/sociogram_edge.json`` and the ``relationship_deltas``
addition to ``schemas/scene_card.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from src.memory.sociogram import Sociogram


SCHEMA_DIR = Path("schemas")


def _load_schema(name: str) -> dict:
    with (SCHEMA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _edge_to_schema_shape(row: dict) -> dict:
    """Translate store row into the canonical schema shape (current_state
    nesting + history list).
    """
    return {
        "edge_id": row["edge_id"],
        "subject": row["subject"],
        "object": row["object"],
        "arc_type": row["arc_type"],
        "current_state": {
            "trust": row["trust"],
            "warmth": row["warmth"],
            "power_balance": row["power_balance"],
            "updated_at_scene": row["updated_at_scene"],
        },
        "history": row["history"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def test_sociogram_edge_schema_validates_real_row():
    schema = _load_schema("sociogram_edge.json")
    graph = Sociogram(db_path=":memory:")
    try:
        graph.initialize_from_planning(concept_seed={
            "relationship_arcs": [
                {"dyad": "A/B", "arc_type": "stable_alliance"},
            ],
        })
        graph.apply_delta(
            subject="A", obj="B", scene_id="ch01_sc01",
            trust_delta=0.1, source="scene_card",
        )
        row = graph.get_edge("A", "B")
    finally:
        graph.close()
    jsonschema.validate(instance=_edge_to_schema_shape(row), schema=schema)


def test_sociogram_edge_schema_rejects_trust_out_of_range():
    schema = _load_schema("sociogram_edge.json")
    bad = {
        "edge_id": "rel_x", "subject": "A", "object": "B",
        "arc_type": "stable_alliance",
        "current_state": {
            "trust": 1.5, "warmth": 0.0, "power_balance": 0.0,
            "updated_at_scene": "ch01_sc01",
        },
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_sociogram_edge_schema_rejects_unknown_arc_type():
    schema = _load_schema("sociogram_edge.json")
    bad = {
        "edge_id": "rel_x", "subject": "A", "object": "B",
        "arc_type": "summer_fling",
        "current_state": {
            "trust": 0.0, "warmth": 0.0, "power_balance": 0.0,
            "updated_at_scene": "ch01_sc01",
        },
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_scene_card_accepts_relationship_deltas():
    schema = _load_schema("scene_card.json")
    good = {
        "chapter_number": 1, "scene_number": 1,
        "structural_phase": "setup",
        "pov_character": "A", "mission": "m", "conflict": "c", "turning_point": "tp",
        "relationship_deltas": [
            {"subject": "A", "object": "B", "trust_delta": 0.2, "warmth_delta": 0.1},
        ],
    }
    jsonschema.validate(instance=good, schema=schema)


def test_scene_card_rejects_relationship_delta_over_cap():
    schema = _load_schema("scene_card.json")
    bad = {
        "chapter_number": 1, "scene_number": 1,
        "structural_phase": "setup",
        "pov_character": "A", "mission": "m", "conflict": "c", "turning_point": "tp",
        "relationship_deltas": [
            {"subject": "A", "object": "B", "trust_delta": 0.75},
        ],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)
