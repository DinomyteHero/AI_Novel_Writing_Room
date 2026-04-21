"""Schema coverage for the additive scene_voice_permissions field."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

jsonschema = pytest.importorskip("jsonschema")


SCHEMA_PATH = Path("schemas") / "scene_card.json"


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_scene_card_schema_accepts_scene_voice_permissions():
    schema = _load_schema()
    good = {
        "chapter_number": 1,
        "scene_number": 1,
        "structural_phase": "setup",
        "pov_character": "A",
        "mission": "m",
        "conflict": "c",
        "turning_point": "tp",
        "scene_voice_permissions": {
            "notes": "Keep the prose close to the body.",
            "anti_patterns": ["No exposition dump"],
            "pov_arc_phase": "lie_questioned",
            "anchor_profile": {
                "primary": "Bujold",
                "supporting": ["Cherryh"],
            },
            "authorized_modes": ["heightened_interiority"],
        },
    }
    jsonschema.validate(instance=good, schema=schema)


def test_scene_card_schema_rejects_unknown_scene_voice_mode():
    schema = _load_schema()
    bad = {
        "chapter_number": 1,
        "scene_number": 1,
        "structural_phase": "setup",
        "pov_character": "A",
        "mission": "m",
        "conflict": "c",
        "turning_point": "tp",
        "scene_voice_permissions": {
            "authorized_modes": ["stover_style"],
        },
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad, schema=schema)
