"""Tests for src/pipeline/brief_assembler.py \u2014 the pure-Python
replacement for PlotArchitect. Covers both the fully-enriched happy path
and the legacy-card fallback behavior."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from src.pipeline.brief_assembler import AssembledBrief, BriefAssembler


REPO_ROOT = Path(__file__).resolve().parent.parent
_BRIEF_SCHEMA = json.loads(
    (REPO_ROOT / "schemas" / "generation_brief.json").read_text(encoding="utf-8")
)


def _enriched_card() -> dict:
    return {
        "chapter_number": 1,
        "scene_number": 1,
        "structural_phase": "setup",
        "pov_character": "Alex Reyes",
        "mission": "Establish Alex's solitary working style",
        "conflict": "Alex vs institution",
        "turning_point": "Alex decides not to report the sealed file",
        "turning_point_detail": {
            "trigger": "Alex opens a sealed file",
            "shift": "private transgression becomes concrete",
            "cost": "breach of institutional trust",
        },
        "emotional_trajectory": "procedural boredom -> recognition -> deliberate transgression",
        "emotional_arc": {
            "start": "procedural boredom",
            "shift": "recognition",
            "end": "deliberate transgression",
        },
        "closing_hook": "a text message arrives from an unknown number",
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
        "opening_mode": "sensory_hook",
        "anti_patterns": ["no flashback", "no exposition dump"],
        "target_word_count": 3500,
        "active_subplots": ["sub_alex_personal_stakes"],
        "revelations": ["rev_alex_knows_target"],
        "hook_actions": [
            {"hook_id": "hook_dark_hooded_enemy", "action": "plant"},
        ],
    }


def _legacy_card() -> dict:
    """Pre-enrichment scene card shape \u2014 only the scalar legacy fields."""
    return {
        "chapter_number": 1,
        "scene_number": 1,
        "structural_phase": "setup",
        "pov_character": "Alex Reyes",
        "mission": "Establish Alex's solitary working style",
        "conflict": "Alex vs institution",
        "turning_point": "Alex decides not to report the sealed file",
        "emotional_trajectory": "procedural boredom -> recognition -> deliberate transgression",
        "closing_hook": "a text message arrives from an unknown number",
        "target_word_count": 3500,
    }


class TestEnrichedCard:
    def test_produces_clean_brief_for_enriched_card(self):
        result = BriefAssembler().assemble(_enriched_card())
        assert isinstance(result, AssembledBrief)
        assert result.warnings == []

    def test_brief_validates_against_schema(self):
        result = BriefAssembler().assemble(_enriched_card())
        jsonschema.validate(instance=result.brief, schema=_BRIEF_SCHEMA)

    def test_turning_point_from_enriched_detail(self):
        result = BriefAssembler().assemble(_enriched_card())
        tp = result.brief["turning_point"]
        assert tp["trigger"].startswith("Alex opens")
        assert tp["shift"].startswith("private")
        assert tp["cost"].startswith("breach")

    def test_emotional_arc_from_enriched_field(self):
        result = BriefAssembler().assemble(_enriched_card())
        arc = result.brief["emotional_arc"]
        assert arc["start"] == "procedural boredom"
        assert arc["shift"] == "recognition"
        assert arc["end"] == "deliberate transgression"

    def test_key_beats_pass_through(self):
        result = BriefAssembler().assemble(_enriched_card())
        assert len(result.brief["key_beats"]) == 3
        assert (
            result.brief["key_beats"][0]["beat_description"]
            == "Alex scans the duty log"
        )

    def test_opening_mode_preserved_when_valid_enum(self):
        result = BriefAssembler().assemble(_enriched_card())
        assert result.brief["opening_mode"] == "sensory_hook"

    def test_invalid_opening_mode_dropped(self):
        card = _enriched_card()
        card["opening_mode"] = "not_an_enum"
        result = BriefAssembler().assemble(card)
        assert "opening_mode" not in result.brief

    def test_hook_subplot_revelation_ids_echoed(self):
        result = BriefAssembler().assemble(_enriched_card())
        assert result.brief["required_hooks"] == ["hook_dark_hooded_enemy"]
        assert result.brief["required_subplots"] == ["sub_alex_personal_stakes"]
        assert result.brief["required_revelations"] == ["rev_alex_knows_target"]

    def test_target_word_count_echoed(self):
        result = BriefAssembler().assemble(_enriched_card())
        assert result.brief["target_word_count"] == 3500

    def test_scene_objective_combines_mission_and_phase(self):
        result = BriefAssembler().assemble(_enriched_card())
        assert "Alex's solitary" in result.brief["scene_objective"]
        assert "setup" in result.brief["scene_objective"]

    def test_closing_beat_rewrites_present_tense_verbs(self):
        result = BriefAssembler().assemble(_enriched_card())
        beat = result.brief["closing_beat"]
        # "arrives" in the closing_hook becomes "arrived".
        assert "arrived" in beat
        assert "arrives" not in beat


class TestLegacyFallback:
    def test_legacy_card_produces_brief_with_warnings(self):
        result = BriefAssembler().assemble(_legacy_card())
        # Brief still validates against schema (turning_point has required
        # trigger/shift/cost keys even when shift/cost are empty strings).
        # Required minLength means trigger must be non-empty; legacy card
        # has a turning_point string, so trigger gets populated.
        assert result.brief["turning_point"]["trigger"]
        # Warnings surface the migration gap.
        assert any("turning_point_detail" in w for w in result.warnings)
        assert any("emotional_arc" in w for w in result.warnings)
        assert any("key_beats" in w for w in result.warnings)

    def test_legacy_turning_point_lands_in_trigger(self):
        result = BriefAssembler().assemble(_legacy_card())
        assert result.brief["turning_point"]["trigger"].startswith(
            "Alex decides"
        )
        # Shift and cost stay empty under legacy fallback.
        assert result.brief["turning_point"]["shift"] == ""
        assert result.brief["turning_point"]["cost"] == ""

    def test_legacy_emotional_trajectory_splits_when_arrowed(self):
        """'start -> shift -> end' legacy strings split cleanly."""
        result = BriefAssembler().assemble(_legacy_card())
        arc = result.brief["emotional_arc"]
        assert arc["start"] == "procedural boredom"
        assert arc["shift"] == "recognition"
        assert arc["end"] == "deliberate transgression"

    def test_legacy_emotional_trajectory_dumps_to_shift_when_unparseable(self):
        card = _legacy_card()
        card["emotional_trajectory"] = "just one string, no arrows"
        result = BriefAssembler().assemble(card)
        arc = result.brief["emotional_arc"]
        assert arc["shift"] == "just one string, no arrows"
        assert arc["start"] == ""
        assert arc["end"] == ""

    def test_legacy_card_omits_key_beats(self):
        result = BriefAssembler().assemble(_legacy_card())
        assert "key_beats" not in result.brief

    def test_missing_both_turning_point_fields_warns_loudly(self):
        card = _legacy_card()
        card.pop("turning_point")
        result = BriefAssembler().assemble(card)
        assert any(
            "no turning_point_detail AND no legacy turning_point" in w
            for w in result.warnings
        )

    def test_missing_closing_hook_warns(self):
        card = _legacy_card()
        card.pop("closing_hook")
        result = BriefAssembler().assemble(card)
        assert any("closing_hook" in w for w in result.warnings)


class TestVoiceGuidance:
    def test_voice_guidance_from_anchor_profile(self):
        card = _enriched_card()
        card["scene_voice_permissions"] = {
            "anchor_profile": {
                "primary": "Bujold",
                "supporting": ["Le Guin", "Cherryh"],
            },
        }
        result = BriefAssembler().assemble(card)
        assert "Bujold" in result.brief.get("voice_guidance", "")
        assert "Le Guin" in result.brief.get("voice_guidance", "")

    def test_voice_guidance_falls_back_to_legacy_anchors(self):
        card = _enriched_card()
        card["primary_anchor"] = "Zahn"
        card["supporting_anchor"] = "Luceno, Bujold"
        result = BriefAssembler().assemble(card)
        vg = result.brief.get("voice_guidance", "")
        assert "Zahn" in vg
        assert "Luceno" in vg

    def test_voice_guidance_absent_when_no_voice_context(self):
        card = _enriched_card()
        result = BriefAssembler().assemble(card)
        # Bare card with no voice data \u2014 no voice_guidance expected.
        assert "voice_guidance" not in result.brief

    def test_pov_approach_injected_when_provided(self):
        result = BriefAssembler(
            pov_approach="Close third-person, present-tense interiority",
        ).assemble(_enriched_card())
        assert "present-tense" in result.brief["voice_guidance"]


class TestAntiPatternMerging:
    def test_top_level_anti_patterns_included(self):
        result = BriefAssembler().assemble(_enriched_card())
        assert "no flashback" in result.brief["anti_patterns"]

    def test_voice_level_anti_patterns_merged(self):
        card = _enriched_card()
        card["scene_voice_permissions"] = {
            "anti_patterns": ["no clinical voice"],
        }
        result = BriefAssembler().assemble(card)
        assert "no flashback" in result.brief["anti_patterns"]
        assert "no clinical voice" in result.brief["anti_patterns"]

    def test_duplicates_deduplicated(self):
        card = _enriched_card()
        card["anti_patterns"] = ["no flashback", "no flashback"]
        card["scene_voice_permissions"] = {
            "anti_patterns": ["no flashback", "no clinical voice"],
        }
        result = BriefAssembler().assemble(card)
        assert result.brief["anti_patterns"].count("no flashback") == 1
        assert "no clinical voice" in result.brief["anti_patterns"]


@pytest.mark.parametrize("missing_field", [
    "mission", "structural_phase",
])
def test_empty_scene_objective_warns(missing_field: str):
    card = _enriched_card()
    card.pop(missing_field)
    result = BriefAssembler().assemble(card)
    # One missing field \u2014 objective still renders (from the other). Two
    # missing fields would produce an empty objective + warning, exercised
    # elsewhere.
    assert result.brief["scene_objective"]


def test_no_mission_and_no_phase_warns_and_empty_objective():
    card = _enriched_card()
    card.pop("mission")
    card.pop("structural_phase")
    result = BriefAssembler().assemble(card)
    assert result.brief["scene_objective"] == ""
    assert any("scene_objective" in w for w in result.warnings)
