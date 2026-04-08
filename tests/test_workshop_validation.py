"""Tests for Phase 5 workshop validation gates."""

import pytest

from src.concept_workshop.workshop_state import ConceptWorkshopState


class TestWorkshopStatePhase5Fields:
    """Tests for new Phase 5 fields in ConceptWorkshopState."""

    def test_new_fields_exist_with_defaults(self):
        """New Phase 5 fields are present with correct defaults."""
        state = ConceptWorkshopState()
        assert state.voice_definition == {}
        assert state.subplot_board == []
        assert state.hook_map == []
        assert state.revelation_schedule == []
        assert state.author_only_secrets is None
        assert state.terminology_registry == []
        assert state.stress_test_results == {}

    def test_to_dict_round_trip_with_phase5_fields(self):
        """Phase 5 fields survive to_dict → from_dict round-trip."""
        state = ConceptWorkshopState()
        state.voice_definition = {"pov_approach": "close third", "prose_register": "commercial"}
        state.subplot_board = [{"subplot_id": "trust_arc", "line_type": "B"}]
        state.hook_map = [{"hook_id": "seal", "priority": "hard"}]
        state.revelation_schedule = [{"info_id": "r1", "content": "The truth"}]
        state.terminology_registry = [{"term": "Voidsteel", "definition": "Dark metal"}]
        state.stress_test_results = {"scores": {"premise_strength": 8.0}}
        state.author_only_secrets = "The mentor is the true villain"

        d = state.to_dict()
        restored = ConceptWorkshopState.from_dict(d)

        assert restored.voice_definition["pov_approach"] == "close third"
        assert len(restored.subplot_board) == 1
        assert len(restored.hook_map) == 1
        assert len(restored.revelation_schedule) == 1
        assert len(restored.terminology_registry) == 1
        assert restored.stress_test_results["scores"]["premise_strength"] == 8.0
        assert restored.author_only_secrets == "The mentor is the true villain"

    def test_to_dict_omits_empty_phase5_fields(self):
        """Empty Phase 5 fields are not included in to_dict output."""
        state = ConceptWorkshopState()
        d = state.to_dict()
        assert "voice_definition" not in d
        assert "subplot_board" not in d
        assert "hook_map" not in d
        assert "terminology_registry" not in d
        assert "stress_test_results" not in d

    def test_from_dict_backward_compatible(self):
        """from_dict works with Phase 4 data (no Phase 5 fields)."""
        phase4_data = {
            "meta": {"project_title": "Test"},
            "premise": {},
            "conflict": {},
            "theme": {},
            "ensemble_cast": [],
            "confirmed_fields": ["meta.project_title"],
        }
        state = ConceptWorkshopState.from_dict(phase4_data)
        assert state.meta["project_title"] == "Test"
        assert state.voice_definition == {}
        assert state.subplot_board == []

    def test_seed_fields_includes_phase5_entries(self):
        """_SEED_FIELDS dict includes Phase 5 field paths."""
        from src.concept_workshop.workshop_state import _SEED_FIELDS
        phase5_fields = [
            "meta.project_scope",
            "voice_definition.pov_approach",
            "voice_definition.prose_register",
            "subplot_board",
            "hook_map",
            "terminology_registry",
            "stress_test_results",
        ]
        for field in phase5_fields:
            assert field in _SEED_FIELDS, f"Missing Phase 5 field: {field}"

    def test_set_field_voice_definition(self):
        """set_field works for voice_definition nested paths."""
        state = ConceptWorkshopState()
        state.set_field("voice_definition.pov_approach", "deep POV")
        assert state.voice_definition["pov_approach"] == "deep POV"

    def test_confirm_phase5_field(self):
        """confirm works for Phase 5 field paths."""
        state = ConceptWorkshopState()
        state.confirm("voice_definition.pov_approach")
        assert "voice_definition.pov_approach" in state.confirmed_fields
