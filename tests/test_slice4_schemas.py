"""JSON-schema validation tests for Slice 4 artifacts.

Checks:
- ``schemas/continuity_event.json`` validates real rows from the store.
- ``oneOf`` discriminator rejects events whose ``details`` don't match the
  event_type.
- Unknown event_type / bad scene_id / out-of-range confidence all fail.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")

from src.memory.continuity_log import ContinuityLog


SCHEMA_DIR = Path("schemas")


def _load_schema(name: str) -> dict:
    with (SCHEMA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def _clean(row: dict) -> dict:
    return {k: v for k, v in row.items() if v is not None}


def test_continuity_event_schema_validates_location_change():
    schema = _load_schema("continuity_event.json")
    log = ContinuityLog(db_path=":memory:")
    try:
        event_id = log.append({
            "event_type": "location_change",
            "scene_id": "ch01_sc01",
            "subject": "Hunter",
            "details": {"from_location": "a", "to_location": "b"},
            "confidence": 0.95,
            "extractor_version": "v0.1",
        })
        row = log.get(event_id)
    finally:
        log.close()
    jsonschema.validate(instance=_clean(row), schema=schema)


def test_continuity_event_schema_validates_injury_state():
    schema = _load_schema("continuity_event.json")
    log = ContinuityLog(db_path=":memory:")
    try:
        event_id = log.append({
            "event_type": "injury_state",
            "scene_id": "ch01_sc01",
            "subject": "Ben",
            "details": {"severity": "severe", "body_part": "arm", "mechanism": "blade"},
            "confidence": 0.9,
            "extractor_version": "v0.1",
        })
        row = log.get(event_id)
    finally:
        log.close()
    jsonschema.validate(instance=_clean(row), schema=schema)


def test_continuity_event_schema_rejects_details_mismatch():
    """Spec \u00a78.1 oneOf discriminator: location_change event_type with
    injury_state details must fail validation at schema level."""
    schema = _load_schema("continuity_event.json")
    bad = {
        "event_id": "evt_x",
        "event_type": "location_change",
        "scene_id": "ch01_sc01",
        "subject": "Hunter",
        "details": {"severity": "minor", "body_part": "arm", "mechanism": "fall"},
        "confidence": 0.9,
        "extractor_version": "v0.1",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_continuity_event_schema_rejects_unknown_type():
    schema = _load_schema("continuity_event.json")
    bad = {
        "event_id": "evt_x",
        "event_type": "mood_shift",
        "scene_id": "ch01_sc01",
        "subject": "Ben",
        "details": {"from": "calm", "to": "angry"},
        "confidence": 0.9,
        "extractor_version": "v0.1",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_continuity_event_schema_rejects_out_of_range_confidence():
    schema = _load_schema("continuity_event.json")
    bad = {
        "event_id": "evt_x",
        "event_type": "location_change",
        "scene_id": "ch01_sc01",
        "subject": "Hunter",
        "details": {"from_location": "a", "to_location": "b"},
        "confidence": 1.5,
        "extractor_version": "v0.1",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_continuity_event_schema_rejects_bad_scene_id():
    schema = _load_schema("continuity_event.json")
    bad = {
        "event_id": "evt_x",
        "event_type": "location_change",
        "scene_id": "Chapter 1 Scene 1",
        "subject": "Hunter",
        "details": {"from_location": "a", "to_location": "b"},
        "confidence": 0.9,
        "extractor_version": "v0.1",
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)
