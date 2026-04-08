"""Tests for ConceptWorkshopStateWriter."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.concept_workshop.state_writer import ConceptWorkshopStateWriter
from src.concept_workshop.workshop_state import ConceptWorkshopState


@pytest.fixture
def mock_router():
    router = MagicMock()
    router.complete_structured = AsyncMock()
    return router


class TestStateWriterProcessTurn:
    """process_turn correctly writes confirmed decisions to state."""

    @pytest.mark.asyncio
    async def test_confirmed_decision_written(self, tmp_path, mock_router):
        mock_router.complete_structured.return_value = {
            "contains_decision": True,
            "field_path": "meta.franchise",
            "decision_value": "Star Wars (Legends)",
            "confidence": 0.92,
        }

        writer = ConceptWorkshopStateWriter("test_proj", tmp_path, mock_router)
        await writer.process_turn("human", "Star Wars Legends it is.")

        assert writer.state.meta["franchise"] == "Star Wars (Legends)"
        assert "meta.franchise" in writer.state.confirmed_fields

        # State was persisted to disk.
        state_file = tmp_path / "workshop_state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["meta"]["franchise"] == "Star Wars (Legends)"

    @pytest.mark.asyncio
    async def test_exploratory_turn_not_written(self, tmp_path, mock_router):
        mock_router.complete_structured.return_value = {
            "contains_decision": False,
            "field_path": None,
            "decision_value": None,
            "confidence": 0.3,
        }

        writer = ConceptWorkshopStateWriter("test_proj", tmp_path, mock_router)
        await writer.process_turn("assistant", "Here are some options to consider...")

        assert writer.state.meta == {}
        assert writer.state.confirmed_fields == set()

    @pytest.mark.asyncio
    async def test_mixed_sequence(self, tmp_path, mock_router):
        """Process a mix of confirmed decisions and exploratory discussion."""
        responses = [
            # Exploratory
            {"contains_decision": False, "field_path": None, "decision_value": None, "confidence": 0.2},
            # Confirmed franchise
            {"contains_decision": True, "field_path": "meta.franchise", "decision_value": "Star Wars (Legends)", "confidence": 0.95},
            # Exploratory
            {"contains_decision": False, "field_path": None, "decision_value": None, "confidence": 0.1},
            # Confirmed era
            {"contains_decision": True, "field_path": "meta.era", "decision_value": "47 ABY", "confidence": 0.90},
            # Low-confidence (filtered out)
            {"contains_decision": True, "field_path": "meta.tone", "decision_value": "dark_gritty", "confidence": 0.5},
        ]
        mock_router.complete_structured.side_effect = responses

        writer = ConceptWorkshopStateWriter("test_proj", tmp_path, mock_router)
        turns = [
            ("assistant", "Here are franchise options..."),
            ("human", "Star Wars Legends."),
            ("assistant", "Great! What era?"),
            ("human", "Post-FOTJ, 47 ABY."),
            ("human", "Maybe dark? Not sure yet."),
        ]

        for role, content in turns:
            await writer.process_turn(role, content)

        # Only two decisions should be confirmed.
        assert writer.state.meta["franchise"] == "Star Wars (Legends)"
        assert writer.state.meta["era"] == "47 ABY"
        assert "meta.franchise" in writer.state.confirmed_fields
        assert "meta.era" in writer.state.confirmed_fields
        # Low-confidence tone should NOT be written.
        assert "tone" not in writer.state.meta
        assert "meta.tone" not in writer.state.confirmed_fields

    @pytest.mark.asyncio
    async def test_state_persists_atomically(self, tmp_path, mock_router):
        """The state file is written atomically — no partial writes."""
        mock_router.complete_structured.return_value = {
            "contains_decision": True,
            "field_path": "meta.franchise",
            "decision_value": "Star Wars",
            "confidence": 0.9,
        }

        writer = ConceptWorkshopStateWriter("test_proj", tmp_path, mock_router)
        await writer.process_turn("human", "Star Wars.")

        # No temp files should linger.
        files = [f.name for f in tmp_path.iterdir()]
        assert "workshop_state.json" in files
        temp_files = [f for f in files if f.startswith(".ws_") or f.endswith(".tmp")]
        assert temp_files == []


class TestStateWriterFinalize:
    """finalize() produces valid concept seed JSON."""

    def test_finalize_full_state(self, tmp_path, mock_router):
        writer = ConceptWorkshopStateWriter("test_proj", tmp_path, mock_router)
        writer.state.set_field("meta.project_title", "Test Novel")
        writer.state.set_field("meta.franchise", "Star Wars")
        writer.state.set_field("meta.era", "47 ABY")
        writer.state.set_field("meta.tone", "dark_gritty")
        writer.state.set_field("meta.canon_status", "AU")
        writer.state.set_field("meta.target_word_count", 75000)
        writer.state.set_field("premise.what_if", "What if the Force only responds to collective will?")
        writer.state.set_field("premise.central_dramatic_question", "Can trust exist without certainty?")
        writer.state.set_field("premise.logline", "A crew discovers collective Force mechanics.")

        output_path = str(tmp_path / "book_1_seed.json")
        writer.finalize(output_path)

        data = json.loads(Path(output_path).read_text())
        assert data["meta"]["franchise"] == "Star Wars"
        assert data["premise"]["what_if"].startswith("What if")
        # confirmed_fields should not appear in the finalized output.
        assert "confirmed_fields" not in data

    def test_finalize_partial_state_warns(self, tmp_path, mock_router, caplog):
        import logging
        writer = ConceptWorkshopStateWriter("test_proj", tmp_path, mock_router)
        writer.state.set_field("meta.franchise", "Star Wars")
        writer.state.confirm("meta.franchise")

        output_path = str(tmp_path / "book_1_seed.json")
        with caplog.at_level(logging.WARNING):
            writer.finalize(output_path)

        assert "incomplete fields" in caplog.text.lower()
        # File should still be written.
        assert Path(output_path).exists()


class TestStateWriterSessionContext:
    """get_session_context() produces a formatted summary."""

    def test_session_context_output(self, tmp_path, mock_router):
        writer = ConceptWorkshopStateWriter("test_proj", tmp_path, mock_router)
        writer.state.set_field("meta.franchise", "Star Wars (Legends)")
        writer.state.confirm("meta.franchise")
        writer.state.set_field("meta.era", "47 ABY")
        writer.state.confirm("meta.era")

        ctx = writer.get_session_context()
        assert "Decisions confirmed" in ctx
        assert "Star Wars (Legends)" in ctx
        assert "Fields still requiring confirmation" in ctx

    def test_session_context_empty_state(self, tmp_path, mock_router):
        writer = ConceptWorkshopStateWriter("test_proj", tmp_path, mock_router)
        ctx = writer.get_session_context()
        assert "No decisions confirmed yet" in ctx


class TestStateWriterResume:
    """Writer loads existing state on init."""

    def test_loads_existing_state(self, tmp_path, mock_router):
        # Pre-populate a workshop_state.json.
        state = ConceptWorkshopState()
        state.set_field("meta.franchise", "Star Wars (Legends)")
        state.confirm("meta.franchise")
        state.save(tmp_path / "workshop_state.json")

        writer = ConceptWorkshopStateWriter("test_proj", tmp_path, mock_router)
        assert writer.state.meta["franchise"] == "Star Wars (Legends)"
        assert "meta.franchise" in writer.state.confirmed_fields
