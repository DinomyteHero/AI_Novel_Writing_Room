"""JSON-schema validation tests for Slice 3 artifacts.

Checks:
- ``schemas/promise_ledger_entry.json`` validates a real ledger row.
- ``schemas/scene_card.json`` accepts the new ``promises_progressed`` field.
- Known-bad examples fail (bad scene-id pattern, unknown status, unknown type).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from src.memory.promise_ledger import PromiseLedger


SCHEMA_DIR = Path("schemas")


def _load_schema(name: str) -> dict:
    with (SCHEMA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _clean_row(row: dict) -> dict:
    """Drop None-valued optional fields so the schema's type unions (which
    allow null) are not double-gated by omitting them entirely."""
    return {k: v for k, v in row.items() if v is not None}


def test_promise_ledger_schema_validates_real_row():
    schema = _load_schema("promise_ledger_entry.json")
    ledger = PromiseLedger(db_path=":memory:")
    try:
        ledger.initialize_from_planning(
            concept_seed={
                "story_physics": {
                    "promise_payoff_ledger": [
                        {
                            "promise_id": "PP01",
                            "description": "An ordinary story obligation",
                            "planted_chapter": 1,
                            "payoff_chapter": 5,
                            "type": "plot",
                            "status": "unfulfilled",
                        },
                    ],
                },
            },
            scene_cards=[],
        )
        ledger.record_progression(
            promise_id="PP01", scene_id="ch02_sc03", source="scene_card",
        )
        row = ledger.get("PP01")
    finally:
        ledger.close()
    jsonschema.validate(instance=_clean_row(row), schema=schema)


def test_promise_ledger_schema_rejects_bad_scene_id():
    schema = _load_schema("promise_ledger_entry.json")
    bad = {
        "promise_id": "P1",
        "description": "",
        "setup_scene": "chapter_one",
        "status": "planted",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_promise_ledger_schema_rejects_unknown_status():
    schema = _load_schema("promise_ledger_entry.json")
    bad = {
        "promise_id": "P1",
        "description": "",
        "setup_scene": "ch01_sc01",
        "status": "half-baked",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_promise_ledger_schema_rejects_unknown_type():
    schema = _load_schema("promise_ledger_entry.json")
    bad = {
        "promise_id": "P1",
        "description": "",
        "setup_scene": "ch01_sc01",
        "status": "planted",
        "promise_type": "metafiction",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_scene_card_schema_accepts_promises_progressed():
    schema = _load_schema("scene_card.json")
    good = {
        "chapter_number": 3,
        "scene_number": 4,
        "structural_phase": "midpoint",
        "pov_character": "Ben",
        "mission": "m",
        "conflict": "c",
        "turning_point": "tp",
        "promises_progressed": ["PP01", "PP04"],
    }
    jsonschema.validate(instance=good, schema=schema)


def test_scene_card_rejects_non_array_promises_progressed():
    schema = _load_schema("scene_card.json")
    bad = {
        "chapter_number": 3,
        "scene_number": 4,
        "structural_phase": "midpoint",
        "pov_character": "Ben",
        "mission": "m",
        "conflict": "c",
        "turning_point": "tp",
        "promises_progressed": "PP01",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)
