"""Tests for DecisionDetector."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.concept_workshop.decision_detector import DecisionDetector, DecisionResult


@pytest.fixture
def mock_router():
    router = MagicMock()
    router.complete_structured = AsyncMock()
    return router


class TestDecisionDetector:
    """Decision classification using mocked ModelRouter responses."""

    @pytest.mark.asyncio
    async def test_character_name_confirmation(self, mock_router):
        mock_router.complete_structured.return_value = {
            "contains_decision": True,
            "field_path": "ensemble_cast.0.name",
            "decision_value": "Caden Arenthal",
            "confidence": 0.95,
        }

        detector = DecisionDetector(mock_router)
        result = await detector.detect(
            "human",
            "Caden Arenthal works for me — let's go with that name.",
        )

        assert result.contains_decision is True
        assert result.field_path == "ensemble_cast.0.name"
        assert result.decision_value == "Caden Arenthal"
        assert result.confidence == 0.95

    @pytest.mark.asyncio
    async def test_exploratory_options_not_flagged(self, mock_router):
        mock_router.complete_structured.return_value = {
            "contains_decision": False,
            "field_path": None,
            "decision_value": None,
            "confidence": 0.2,
        }

        detector = DecisionDetector(mock_router)
        result = await detector.detect(
            "assistant",
            "Here are five name options for the Jedi scholar: "
            "A) Voss Parlan, B) Erris Saan, C) Torvan Ryl, "
            "D) Caden Arenthal, E) Myra Dalish.",
        )

        assert result.contains_decision is False

    @pytest.mark.asyncio
    async def test_franchise_confirmation(self, mock_router):
        mock_router.complete_structured.return_value = {
            "contains_decision": True,
            "field_path": "meta.franchise",
            "decision_value": "Star Wars (Legends)",
            "confidence": 0.92,
        }

        detector = DecisionDetector(mock_router)
        result = await detector.detect(
            "human",
            "Star Wars Legends, definitely. I want to play in the old EU.",
        )

        assert result.contains_decision is True
        assert result.field_path == "meta.franchise"
        assert result.decision_value == "Star Wars (Legends)"

    @pytest.mark.asyncio
    async def test_confidence_threshold_filters_low(self, mock_router):
        mock_router.complete_structured.return_value = {
            "contains_decision": True,
            "field_path": "meta.tone",
            "decision_value": "dark_gritty",
            "confidence": 0.6,  # Below 0.8 threshold
        }

        detector = DecisionDetector(mock_router)
        result = await detector.detect(
            "human",
            "I'm leaning toward something darker, maybe...",
        )

        assert result.contains_decision is False
        assert result.confidence == 0.6

    @pytest.mark.asyncio
    async def test_model_failure_returns_no_decision(self, mock_router):
        mock_router.complete_structured.side_effect = RuntimeError("Model offline")

        detector = DecisionDetector(mock_router)
        result = await detector.detect("human", "Let's go with Star Wars.")

        assert result.contains_decision is False
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_theme_confirmation(self, mock_router):
        mock_router.complete_structured.return_value = {
            "contains_decision": True,
            "field_path": "theme.thematic_premise",
            "decision_value": "Trust is action in the presence of doubt.",
            "confidence": 0.88,
        }

        detector = DecisionDetector(mock_router)
        result = await detector.detect(
            "human",
            "Yes, that's the theme — trust as action in the presence of doubt.",
        )

        assert result.contains_decision is True
        assert result.field_path == "theme.thematic_premise"
