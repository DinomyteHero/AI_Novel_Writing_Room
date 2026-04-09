"""Tests for Phase 5 workshop validation gates."""

import pytest

from src.concept_workshop.workshop_state import ConceptWorkshopState


class TestWorkshopStatePhase5Fields:
    """Tests for new Phase 5 fields in ConceptWorkshopState."""

    def test_new_fields_exist_with_defaults(self):
        """New Phase 5 fields are present with correct defaults."""
        state = ConceptWorkshopState()
        assert state.voice_definition == {}
        assert state.subplots == []
        assert state.hooks == []
        assert state.revelation_schedule == []
        assert state.author_only_secrets is None
        assert state.terminology_registry == []
        assert state.stress_test_scores == {}
        # Post-Phase-5 fields (Ruusan Atonement revision)
        assert state.promise_payoff_ledger == []
        assert state.extended_metadata == {}

    def test_to_dict_round_trip_with_phase5_fields(self):
        """Phase 5 fields survive to_dict → from_dict round-trip."""
        state = ConceptWorkshopState()
        state.voice_definition = {"pov_approach": "close third", "prose_register": "commercial"}
        state.subplots = [{"subplot_id": "trust_arc", "line_type": "B"}]
        state.hooks = [{"hook_id": "seal", "hook_type": "hard"}]
        state.revelation_schedule = [{"info_id": "r1", "content": "The truth"}]
        state.terminology_registry = [{"term": "Voidsteel", "definition": "Dark metal"}]
        state.stress_test_scores = {"structural_integrity": 8.0, "overall": 8.0}
        state.author_only_secrets = "The mentor is the true villain"

        d = state.to_dict()
        restored = ConceptWorkshopState.from_dict(d)

        assert restored.voice_definition["pov_approach"] == "close third"
        assert len(restored.subplots) == 1
        assert len(restored.hooks) == 1
        assert len(restored.revelation_schedule) == 1
        assert len(restored.terminology_registry) == 1
        assert restored.stress_test_scores["structural_integrity"] == 8.0
        assert restored.author_only_secrets == "The mentor is the true villain"

    def test_round_trip_with_post_phase5_fields(self):
        """promise_payoff_ledger and extended_metadata round-trip correctly."""
        state = ConceptWorkshopState()
        state.promise_payoff_ledger = [
            {
                "promise_id": "PP01",
                "promise": "The wound has a source",
                "planted_in": "Chapter 1",
                "payoff_in": "Chapter 3",
                "type": "plot",
            }
        ]
        state.extended_metadata = {
            "technique_lineage": {"description": "Ancient chain of Force experiments"},
            "workshop_origin": {"source": "claude_ai_simulation"},
        }

        d = state.to_dict()
        restored = ConceptWorkshopState.from_dict(d)

        assert len(restored.promise_payoff_ledger) == 1
        assert restored.promise_payoff_ledger[0]["promise_id"] == "PP01"
        assert restored.extended_metadata["technique_lineage"]["description"].startswith("Ancient")
        assert restored.extended_metadata["workshop_origin"]["source"] == "claude_ai_simulation"

    def test_to_dict_omits_empty_phase5_fields(self):
        """Empty Phase 5 and post-Phase-5 fields are not included in to_dict output."""
        state = ConceptWorkshopState()
        d = state.to_dict()
        assert "voice_definition" not in d
        assert "subplots" not in d
        assert "hooks" not in d
        assert "terminology_registry" not in d
        assert "stress_test_scores" not in d
        # Post-Phase-5 fields should also be omitted when empty
        assert "promise_payoff_ledger" not in d
        assert "extended_metadata" not in d

    def test_from_dict_backward_compatible(self):
        """from_dict works with minimal data missing optional fields."""
        minimal_data = {
            "meta": {"project_title": "Test"},
            "premise": {},
            "conflict": {},
            "theme": {},
            "ensemble_cast": [],
            "confirmed_fields": ["meta.project_title"],
        }
        state = ConceptWorkshopState.from_dict(minimal_data)
        assert state.meta["project_title"] == "Test"
        assert state.voice_definition == {}
        assert state.subplots == []
        # Post-Phase-5 fields default correctly
        assert state.promise_payoff_ledger == []
        assert state.extended_metadata == {}

    def test_from_dict_without_post_phase5_fields(self):
        """Data with voice_definition etc. but no promise_payoff_ledger loads cleanly."""
        data = {
            "meta": {"project_title": "A book"},
            "premise": {},
            "conflict": {},
            "theme": {},
            "ensemble_cast": [],
            "voice_definition": {"pov_approach": "deep POV"},
            "subplots": [{"subplot_id": "sp1"}],
            "confirmed_fields": ["meta.project_title", "voice_definition.pov_approach"],
        }
        state = ConceptWorkshopState.from_dict(data)
        assert state.voice_definition == {"pov_approach": "deep POV"}
        assert len(state.subplots) == 1
        assert state.promise_payoff_ledger == []
        assert state.extended_metadata == {}

    def test_seed_fields_includes_phase5_entries(self):
        """_SEED_FIELDS dict includes the canonical top-level entries."""
        from src.concept_workshop.workshop_state import _SEED_FIELDS
        canonical_fields = [
            "meta.project_scope",
            "voice_definition.pov_approach",
            "voice_definition.prose_register",
            "subplots",
            "hooks",
            "terminology_registry",
            "stress_test_scores",
        ]
        for field in canonical_fields:
            assert field in _SEED_FIELDS, f"Missing canonical field: {field}"

    def test_seed_fields_includes_post_phase5_entries(self):
        """_SEED_FIELDS dict includes the richer voice_definition fields and new top-level entries."""
        from src.concept_workshop.workshop_state import _SEED_FIELDS
        post_phase5_fields = [
            "voice_definition.reference_authors",
            "voice_definition.character_voices",
            "voice_definition.anti_slop_rules",
            "voice_definition.force_description_guidelines",
            "promise_payoff_ledger",
            "extended_metadata",
        ]
        for field in post_phase5_fields:
            assert field in _SEED_FIELDS, f"Missing post-Phase-5 field: {field}"

    def test_legacy_anti_slop_label_removed(self):
        """The legacy `voice_definition.anti_slop` label key is renamed to anti_slop_rules."""
        from src.concept_workshop.workshop_state import _SEED_FIELDS
        # The old key should no longer be in _SEED_FIELDS; the new one must be.
        assert "voice_definition.anti_slop" not in _SEED_FIELDS
        assert "voice_definition.anti_slop_rules" in _SEED_FIELDS

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
