"""Tests for scripts/enrich_scene_cards.py \u2014 pure-Python mapping layer.

The live-router path (``enrich_bundle``) requires a configured ModelRouter
and an actual PlotArchitect roundtrip; those are exercised by the operator
when running the migration. The tests here cover ``_apply_brief_to_card``
and ``_is_already_enriched`` which are the safety-critical parts.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).parent.parent / "scripts" / "enrich_scene_cards.py"
_spec = importlib.util.spec_from_file_location("enrich_scene_cards", SCRIPT_PATH)
enrich_scene_cards = importlib.util.module_from_spec(_spec)
sys.modules["enrich_scene_cards"] = enrich_scene_cards
_spec.loader.exec_module(enrich_scene_cards)

_apply = enrich_scene_cards._apply_brief_to_card
_is_enriched = enrich_scene_cards._is_already_enriched
_build_offline_brief = enrich_scene_cards._build_offline_brief


def _valid_brief() -> dict:
    return {
        "scene_objective": "obj",
        "turning_point": {
            "trigger": "Alex opens the sealed file",
            "shift": "private transgression becomes concrete",
            "cost": "breach of institutional trust",
        },
        "emotional_arc": {
            "start": "procedural boredom",
            "shift": "recognition",
            "end": "deliberate transgression",
        },
        "closing_beat": "a text arrives from an unknown number",
        "target_word_count": 3500,
        "opening_mode": "sensory_hook",
        "key_beats": [
            {
                "beat_description": "Alex scans the duty log",
                "state_change": "sees the sealed file flag",
                "pov_reaction": "pause in the scrolling pattern",
            },
            {
                "beat_description": "Alex opens the file",
                "state_change": "identity revealed",
                "pov_reaction": "balance registers a drop",
            },
            {
                "beat_description": "Alex locks it away",
                "state_change": "evidence privatised",
                "pov_reaction": "reflex to check the corridor",
            },
        ],
        "anti_patterns": ["no flashback", "avoid exposition dump"],
    }


def test_is_already_enriched_detects_full_card():
    card = {
        "turning_point_detail": {"trigger": "a", "shift": "b", "cost": "c"},
        "emotional_arc": {"start": "x", "shift": "y", "end": "z"},
        "key_beats": [{}, {}, {}],
    }
    assert _is_enriched(card) is True


def test_is_already_enriched_rejects_partial_card():
    assert _is_enriched({"turning_point_detail": {}}) is False
    assert _is_enriched({"emotional_arc": {}}) is False
    assert _is_enriched({}) is False


def test_apply_brief_promotes_turning_point_to_detail_field():
    card = {"chapter_number": 1, "scene_number": 1, "turning_point": "scalar legacy"}
    brief = _valid_brief()
    enriched = _apply(card, brief)
    # Legacy string stays untouched; new detail field is populated alongside.
    assert enriched["turning_point"] == "scalar legacy"
    assert enriched["turning_point_detail"] == brief["turning_point"]


def test_apply_brief_promotes_emotional_arc():
    card = {"chapter_number": 1, "scene_number": 1}
    enriched = _apply(card, _valid_brief())
    assert enriched["emotional_arc"]["start"] == "procedural boredom"
    assert enriched["emotional_arc"]["end"] == "deliberate transgression"


def test_apply_brief_promotes_key_beats():
    card = {"chapter_number": 1, "scene_number": 1}
    enriched = _apply(card, _valid_brief())
    assert len(enriched["key_beats"]) == 3
    assert enriched["key_beats"][0]["beat_description"].startswith("Alex")


def test_apply_brief_drops_invalid_opening_mode():
    card = {"chapter_number": 1, "scene_number": 1}
    brief = _valid_brief()
    brief["opening_mode"] = "not_an_enum"
    enriched = _apply(card, brief)
    assert "opening_mode" not in enriched


def test_apply_brief_merges_anti_patterns_with_existing():
    card = {
        "chapter_number": 1, "scene_number": 1,
        "anti_patterns": ["no purple prose"],
    }
    enriched = _apply(card, _valid_brief())
    # Original author anti-patterns are preserved; brief anti-patterns added.
    assert "no purple prose" in enriched["anti_patterns"]
    assert "no flashback" in enriched["anti_patterns"]
    assert "avoid exposition dump" in enriched["anti_patterns"]
    # Order: existing first, then brief additions.
    assert enriched["anti_patterns"][0] == "no purple prose"


def test_apply_brief_rejects_incomplete_turning_point():
    card = {"chapter_number": 1, "scene_number": 1}
    brief = _valid_brief()
    brief["turning_point"] = {"trigger": "only trigger"}  # missing shift, cost
    enriched = _apply(card, brief)
    assert "turning_point_detail" not in enriched


def test_apply_brief_rejects_short_key_beats():
    card = {"chapter_number": 1, "scene_number": 1}
    brief = _valid_brief()
    brief["key_beats"] = brief["key_beats"][:2]  # only 2 items
    enriched = _apply(card, brief)
    assert "key_beats" not in enriched


def test_apply_brief_caps_key_beats_at_five():
    card = {"chapter_number": 1, "scene_number": 1}
    brief = _valid_brief()
    beat_template = brief["key_beats"][0]
    brief["key_beats"] = [dict(beat_template) for _ in range(8)]
    enriched = _apply(card, brief)
    assert len(enriched["key_beats"]) == 5


def test_apply_brief_returns_new_dict_not_mutation():
    card = {"chapter_number": 1, "scene_number": 1}
    _apply(card, _valid_brief())
    assert "turning_point_detail" not in card, "input card must not be mutated"


def test_build_offline_brief_creates_complete_structured_fields():
    card = {
        "chapter_number": 1,
        "scene_number": 1,
        "structural_phase": "setup",
        "pov_character": "Ben Skywalker",
        "mission": "Ben loses a sparring exchange he should not have lost",
        "conflict": "Wrongness in the Force throws his timing off",
        "turning_point": (
            "Alone in the salle, Ben runs a form without igniting the blade. "
            "He stops pretending the problem is fatigue."
        ),
        "opening_hook": (
            "Ben's guard drops a half-second late and the training blade "
            "catches him across the shoulder"
        ),
        "closing_hook": "Luke appears in the doorway with a datapad",
        "emotional_trajectory": "Restless unease -> frustrated isolation -> reluctant hope",
        "target_word_count": 1250,
        "action_beats": [
            "Ben's guard drops and he takes the hit",
            "Ben waves off a rematch and stays behind",
            "Luke appears in the doorway with a datapad",
        ],
        "notes": (
            "Diagnostic-voice trap — he should not clinically articulate the wrongness yet. "
            "Anti-pattern: do not describe the wrongness in visual or color terms."
        ),
        "stakes": {
            "personal": "His confidence in his own Force perception",
            "interpersonal": "His distance from other Knights",
        },
    }

    brief = _build_offline_brief(card)

    assert brief["turning_point"]["trigger"].startswith("Alone in the salle")
    assert brief["turning_point"]["shift"]
    assert brief["turning_point"]["cost"]
    assert brief["emotional_arc"] == {
        "start": "Restless unease",
        "shift": "frustrated isolation",
        "end": "reluctant hope",
    }
    assert brief["opening_mode"] == "in_medias_res"
    assert len(brief["key_beats"]) == 3
    assert all(beat["state_change"] for beat in brief["key_beats"])
    assert all(beat["pov_reaction"] for beat in brief["key_beats"])


def test_build_offline_brief_extracts_anti_patterns_from_notes():
    card = {
        "chapter_number": 13,
        "scene_number": 1,
        "structural_phase": "midpoint",
        "pov_character": "Ben Skywalker",
        "mission": "Experience the unwoven zone at full scale",
        "conflict": "The Force stops answering in a known register",
        "turning_point": "Ben reaches for the Force and finds no structure.",
        "opening_hook": (
            "Ben watches the settlement world fill the viewport while scan "
            "data contradicts what the eye reports"
        ),
        "closing_hook": "Ben hears his own thoughts without the usual safety net",
        "emotional_trajectory": "Professional assessment -> escalating wrongness -> existential disorientation",
        "target_word_count": 1600,
        "action_beats": [
            "The ship breaks orbit over Kolven",
            "Ben steps onto the surface and reaches for the Force",
            "Desh watches his chrono skip seconds",
        ],
        "notes": (
            "Diagnostic-voice trap — Ben should not analyse the phenomenology as concept. "
            "Anti-pattern (chapter-level): absolutely no 'it was as if the Force had —' constructions."
        ),
        "stakes": {"external": "Veraine can weaponize the absence across the galaxy"},
    }

    brief = _build_offline_brief(card)

    assert brief["opening_mode"] == "contrast"
    assert "anti_patterns" in brief
    assert any("should not analyse the phenomenology as concept" in item for item in brief["anti_patterns"])
    assert any("absolutely no 'it was as if the Force had —' constructions" in item for item in brief["anti_patterns"])
