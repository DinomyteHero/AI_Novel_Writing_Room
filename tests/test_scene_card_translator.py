"""Unit tests for src/concept_workshop/scene_card_translator.py.

The translator output is a *partial* scene card — it populates fields
present in the workshop format (chapter/scene numbers, pov, mission,
conflict, notes, references) and leaves ``why_now`` / ``turning_point`` /
``opening_hook`` / ``closing_hook`` as empty strings for downstream
enrichment. Those fields carry a ``minLength: 1`` constraint in the full
scene_card schema, so the raw translator output is not schema-valid by
itself. Tests validate the translator's own contract, not the final
post-enrichment card shape.
"""

from __future__ import annotations

from workflows._shared.scene_card_translator import (
    ARC_PHASE_PREFIX,
    UPPERCASE_MARKERS,
    build_scene_card_notes,
    derive_structural_phase,
    translate_scene_card,
)


class TestDeriveStructuralPhase:
    def test_override_wins(self):
        card = {"chapter_number": 26, "arc_phase": "Resolution: denouement"}
        result = derive_structural_phase(card, structural_overrides={26: "climax"})
        assert result == "climax"

    def test_override_with_string_key(self):
        card = {"chapter_number": 26, "arc_phase": "Resolution: denouement"}
        # workshop_patch.json stores keys as strings — translator must coerce.
        result = derive_structural_phase(card, structural_overrides={"26": "climax"})
        assert result == "climax"

    def test_uppercase_marker_in_scene_goal(self):
        card = {
            "chapter_number": 5,
            "scene_goal": "FIRST PLOT POINT — launch the mission",
        }
        assert derive_structural_phase(card) == "first_plot_point"

    def test_midpoint_marker(self):
        card = {"chapter_number": 14, "scene_goal": "MIDPOINT — the breach"}
        assert derive_structural_phase(card) == "midpoint"

    def test_second_plot_point_marker(self):
        card = {
            "chapter_number": 21,
            "scene_goal": "SECOND PLOT POINT — Torin turns",
        }
        assert derive_structural_phase(card) == "second_plot_point"

    def test_arc_phase_prefix(self):
        card = {"chapter_number": 3, "arc_phase": "Setup: establish the wrongness"}
        assert derive_structural_phase(card) == "setup"

    def test_response_prefix(self):
        card = {"chapter_number": 8, "arc_phase": "Response: investigate"}
        assert derive_structural_phase(card) == "response"

    def test_fallback_to_setup(self):
        card = {"chapter_number": 1, "arc_phase": ""}
        assert derive_structural_phase(card) == "setup"

    def test_precedence_override_beats_marker(self):
        """Override must beat uppercase-marker detection."""
        card = {
            "chapter_number": 26,
            "scene_goal": "FIRST PLOT POINT — should not apply",
        }
        result = derive_structural_phase(
            card, structural_overrides={26: "climax"}
        )
        assert result == "climax"

    def test_precedence_marker_beats_arc_phase(self):
        """Uppercase-marker detection must beat arc_phase prefix matching."""
        card = {
            "chapter_number": 5,
            "scene_goal": "FIRST PLOT POINT — launch",
            "arc_phase": "Setup: preliminary",
        }
        assert derive_structural_phase(card) == "first_plot_point"

    def test_malformed_override_key_skipped(self):
        card = {"chapter_number": 5, "arc_phase": "Setup: preliminary"}
        # A non-int-coercible key should be silently ignored; the translator
        # must still return a deterministic answer via arc_phase fallback.
        result = derive_structural_phase(
            card, structural_overrides={"not-a-number": "climax"}
        )
        assert result == "setup"

    def test_uppercase_markers_constant_covers_expected_set(self):
        assert set(UPPERCASE_MARKERS.keys()) == {
            "FIRST PLOT POINT",
            "SECOND PLOT POINT",
            "MIDPOINT",
        }

    def test_arc_phase_prefix_constant_covers_expected_set(self):
        assert "Setup" in ARC_PHASE_PREFIX
        assert "Response" in ARC_PHASE_PREFIX
        assert "Attack" in ARC_PHASE_PREFIX
        assert "Resolution" in ARC_PHASE_PREFIX


class TestBuildSceneCardNotes:
    def test_all_three_fields(self):
        card = {
            "time": "dawn",
            "thematic_beat": "awakening",
            "scene_outcome": "Ben departs",
        }
        notes = build_scene_card_notes(card)
        assert "Time: dawn" in notes
        assert "Thematic beat: awakening" in notes
        assert "Original scene_outcome: Ben departs" in notes

    def test_subset_of_fields(self):
        card = {"time": "dawn"}
        assert build_scene_card_notes(card) == "Time: dawn"

    def test_empty_card(self):
        assert build_scene_card_notes({}) == ""

    def test_empty_string_fields_are_skipped(self):
        card = {"time": "", "thematic_beat": "awakening", "scene_outcome": ""}
        assert build_scene_card_notes(card) == "Thematic beat: awakening"


class TestTranslateSceneCard:
    def _base_seed_card(self) -> dict:
        return {
            "chapter_number": 1,
            "scene_number": 2,
            "pov_character": "Ben Skywalker",
            "scene_goal": "Establish the wrongness",
            "scene_conflict": "Ben cannot parse the Force texture",
            "location": "Jedi Temple training ring",
            "arc_phase": "Setup: wrongness surfaces",
            "estimated_word_count": 1200,
            "time": "dawn",
            "thematic_beat": "dislocation",
            "scene_outcome": "Ben departs the ring",
            "scene_type": "action",
            "subplot_references": ["SP-A"],
            "hook_references": ["H01"],
            "revelation_references": ["R01"],
        }

    def test_required_fields_populated(self):
        card = translate_scene_card(self._base_seed_card())
        assert card["chapter_number"] == 1
        assert card["scene_number"] == 2
        assert card["structural_phase"] == "setup"
        assert card["pov_character"] == "Ben Skywalker"
        assert card["mission"] == "Establish the wrongness"
        assert card["conflict"] == "Ben cannot parse the Force texture"

    def test_defaults_apply(self):
        card = translate_scene_card(self._base_seed_card())
        assert card["conflict_type"] == "internal"
        assert card["target_word_count"] == 1200  # from workshop value

    def test_target_word_count_falls_back_to_default(self):
        seed = self._base_seed_card()
        del seed["estimated_word_count"]
        card = translate_scene_card(seed)
        assert card["target_word_count"] == 3500

    def test_default_conflict_type_override(self):
        seed = self._base_seed_card()
        card = translate_scene_card(seed, default_conflict_type="interpersonal")
        assert card["conflict_type"] == "interpersonal"

    def test_default_target_word_count_override(self):
        seed = self._base_seed_card()
        del seed["estimated_word_count"]
        card = translate_scene_card(seed, default_target_word_count=2500)
        assert card["target_word_count"] == 2500

    def test_scene_type_passthrough_for_valid_enum(self):
        for scene_type in ("action", "sequel"):
            seed = self._base_seed_card()
            seed["scene_type"] = scene_type
            card = translate_scene_card(seed)
            assert card["scene_type"] == scene_type

    def test_scene_type_omitted_for_invalid_value(self):
        seed = self._base_seed_card()
        seed["scene_type"] = "bogus"
        card = translate_scene_card(seed)
        assert "scene_type" not in card

    def test_scene_type_omitted_when_missing(self):
        seed = self._base_seed_card()
        del seed["scene_type"]
        card = translate_scene_card(seed)
        assert "scene_type" not in card

    def test_structural_override_applied(self):
        seed = self._base_seed_card()
        seed["chapter_number"] = 26
        seed["arc_phase"] = "Resolution: denouement"
        card = translate_scene_card(seed, structural_overrides={26: "climax"})
        assert card["structural_phase"] == "climax"

    def test_output_uses_valid_enums(self):
        """The translator's own contract: any enum it populates must be
        a valid schema enum member."""
        card = translate_scene_card(self._base_seed_card())
        assert card["structural_phase"] in {
            "setup", "first_plot_point", "response", "first_pinch",
            "midpoint", "attack", "second_pinch", "second_plot_point",
            "resolution", "climax",
        }
        assert card["conflict_type"] in {
            "internal", "interpersonal", "external", "environmental",
        }

    def test_empty_fields_left_for_post_enrichment(self):
        """``why_now`` / ``turning_point`` / ``opening_hook`` / ``closing_hook``
        are not present in the workshop format, so the translator leaves
        them empty for later enrichment (hand-authoring or a later workshop
        surface). Do not silently fill them — downstream tooling expects
        them to be detectable-empty."""
        card = translate_scene_card(self._base_seed_card())
        for field in ("why_now", "turning_point", "opening_hook", "closing_hook"):
            assert card[field] == ""

    def test_notes_combined(self):
        card = translate_scene_card(self._base_seed_card())
        assert "Time: dawn" in card["notes"]
        assert "Thematic beat: dislocation" in card["notes"]

    def test_references_preserved(self):
        card = translate_scene_card(self._base_seed_card())
        assert card["active_subplots"] == ["SP-A"]
        assert card["hook_actions"] == ["H01"]
        assert card["revelations"] == ["R01"]
        assert card["pov_arc_phase"] == "Setup: wrongness surfaces"

    def test_empty_references_default_to_empty_list(self):
        seed = self._base_seed_card()
        del seed["subplot_references"]
        del seed["hook_references"]
        del seed["revelation_references"]
        card = translate_scene_card(seed)
        assert card["active_subplots"] == []
        assert card["hook_actions"] == []
        assert card["revelations"] == []
