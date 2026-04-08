"""Tests for ConceptWorkshopState."""

import json
from pathlib import Path

import pytest

from src.concept_workshop.workshop_state import ConceptWorkshopState


class TestConceptWorkshopStateBasic:
    """Core creation, field-setting, and confirmation."""

    def test_empty_state(self):
        state = ConceptWorkshopState()
        assert state.meta == {}
        assert state.confirmed_fields == set()
        assert state.protagonist_arc_type is None

    def test_set_field_simple(self):
        state = ConceptWorkshopState()
        state.set_field("meta.franchise", "Star Wars (Legends)")
        assert state.meta["franchise"] == "Star Wars (Legends)"

    def test_set_field_nested(self):
        state = ConceptWorkshopState()
        state.set_field("conflict.primary_antagonistic_force.type", "Internal betrayal")
        assert state.conflict["primary_antagonistic_force"]["type"] == "Internal betrayal"

    def test_set_field_top_level(self):
        state = ConceptWorkshopState()
        state.set_field("protagonist_arc_type", "steadfast")
        assert state.protagonist_arc_type == "steadfast"

    def test_set_field_ensemble_cast(self):
        state = ConceptWorkshopState()
        state.set_field("ensemble_cast.0.name", "Ben Skywalker")
        assert state.ensemble_cast[0]["name"] == "Ben Skywalker"

    def test_confirm(self):
        state = ConceptWorkshopState()
        state.set_field("meta.franchise", "Star Wars (Legends)")
        state.confirm("meta.franchise")
        assert "meta.franchise" in state.confirmed_fields


class TestConceptWorkshopStateSerialization:
    """Round-trip JSON fidelity."""

    def test_round_trip(self):
        state = ConceptWorkshopState()
        state.set_field("meta.franchise", "Star Wars (Legends)")
        state.set_field("meta.era", "Post-FOTJ, ~47 ABY")
        state.set_field("meta.tone", "adventurous_hopeful")
        state.set_field("premise.what_if", "What if the Force only responds to collective will?")
        state.set_field("protagonist_arc_type", "steadfast")
        state.set_field("ensemble_cast.0.name", "Ben Skywalker")
        state.set_field("ensemble_cast.0.role", "Mission lead")
        state.confirm("meta.franchise")
        state.confirm("meta.era")
        state.confirm("premise.what_if")

        d = state.to_dict()
        restored = ConceptWorkshopState.from_dict(d)

        assert restored.meta["franchise"] == "Star Wars (Legends)"
        assert restored.meta["era"] == "Post-FOTJ, ~47 ABY"
        assert restored.premise["what_if"] == "What if the Force only responds to collective will?"
        assert restored.protagonist_arc_type == "steadfast"
        assert restored.ensemble_cast[0]["name"] == "Ben Skywalker"
        assert restored.confirmed_fields == {"meta.franchise", "meta.era", "premise.what_if"}

    def test_json_serializable(self):
        state = ConceptWorkshopState()
        state.set_field("meta.franchise", "Star Wars")
        state.confirm("meta.franchise")
        # Should not raise.
        json_str = json.dumps(state.to_dict())
        assert "Star Wars" in json_str


class TestConceptWorkshopStatePersistence:
    """Save / load from disk."""

    def test_save_and_load(self, tmp_path):
        path = tmp_path / "workshop_state.json"

        state = ConceptWorkshopState()
        state.set_field("meta.franchise", "Star Wars (Legends)")
        state.set_field("meta.era", "47 ABY")
        state.confirm("meta.franchise")
        state.confirm("meta.era")
        state.save(path)

        loaded = ConceptWorkshopState.load(path)
        assert loaded.meta["franchise"] == "Star Wars (Legends)"
        assert loaded.meta["era"] == "47 ABY"
        assert loaded.confirmed_fields == {"meta.franchise", "meta.era"}

    def test_load_nonexistent_returns_empty(self, tmp_path):
        path = tmp_path / "does_not_exist.json"
        state = ConceptWorkshopState.load(path)
        assert state.meta == {}
        assert state.confirmed_fields == set()

    def test_atomic_write_leaves_no_temp(self, tmp_path):
        path = tmp_path / "ws.json"
        state = ConceptWorkshopState()
        state.set_field("meta.franchise", "Test")
        state.save(path)

        # Only the target file should remain — no .tmp leftover.
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "ws.json"


class TestConceptWorkshopStateOpenQuestions:
    """get_open_questions reports unconfirmed fields."""

    def test_all_open_when_empty(self):
        state = ConceptWorkshopState()
        questions = state.get_open_questions()
        # Should list all seed fields.
        assert len(questions) > 10
        assert any("Franchise" in q for q in questions)

    def test_confirmed_fields_excluded(self):
        state = ConceptWorkshopState()
        state.set_field("meta.franchise", "Star Wars")
        state.confirm("meta.franchise")
        state.set_field("meta.era", "47 ABY")
        state.confirm("meta.era")

        questions = state.get_open_questions()
        assert not any("meta.franchise" in q for q in questions)
        assert not any("meta.era" in q for q in questions)
        # Other fields still open.
        assert any("Tone" in q for q in questions)

    def test_confirmed_summary(self):
        state = ConceptWorkshopState()
        state.set_field("meta.franchise", "Star Wars (Legends)")
        state.confirm("meta.franchise")

        summary = state.get_confirmed_summary()
        assert "Star Wars (Legends)" in summary
        assert "Franchise" in summary
