"""JSON-schema validation tests for Slice 6 manuscript patch schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")


SCHEMA_DIR = Path("schemas")


def _load_schema(name: str) -> dict:
    with (SCHEMA_DIR / name).open(encoding="utf-8") as fh:
        return json.load(fh)


def test_manuscript_patch_schema_accepts_valid_entry():
    schema = _load_schema("manuscript_patch.json")
    good = {
        "version": "2026-04-21",
        "source_pass": "line",
        "entries": [
            {"action": "accept-isolated", "scene_id": "ch01_sc02"},
            {"action": "replace", "scene_id": "ch03_sc05", "prose_path": "x.md",
             "gap_id": "gap_01", "notes": "line-pass fix"},
            {"action": "overrule", "gap_id": "gap_02"},
        ],
    }
    jsonschema.validate(instance=good, schema=schema)


def test_manuscript_patch_rejects_bad_action():
    schema = _load_schema("manuscript_patch.json")
    bad = {
        "version": "2026-04-21",
        "entries": [
            {"action": "rewrite_scene", "scene_id": "ch01_sc01"},
        ],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_manuscript_patch_rejects_bad_source_pass():
    schema = _load_schema("manuscript_patch.json")
    bad = {
        "version": "2026-04-21",
        "source_pass": "structural",
        "entries": [],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)


def test_manuscript_patch_rejects_bad_scene_id_pattern():
    schema = _load_schema("manuscript_patch.json")
    bad = {
        "version": "2026-04-21",
        "entries": [
            {"action": "accept-isolated", "scene_id": "Chapter 1"},
        ],
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)
