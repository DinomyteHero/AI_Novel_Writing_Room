"""Tests for WorkshopSummarizer."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.concept_workshop.workshop_summarizer import (
    WorkshopSessionSummary,
    WorkshopSummarizer,
)
from src.concept_workshop.workshop_state import ConceptWorkshopState


@pytest.fixture
def mock_router():
    router = MagicMock()
    router.complete = AsyncMock(return_value="A summary of the session so far.")
    router.complete_structured = AsyncMock(return_value={
        "decisions_confirmed": {"meta": {"franchise": "Star Wars (Legends)"}},
        "open_questions": ["Theme not yet confirmed"],
        "current_step": "Step 3 — Conflict Stress Test",
        "key_decisions_reasoning": ["Franchise chosen for depth of lore"],
    })
    return router


@pytest.fixture
def state_with_decisions():
    state = ConceptWorkshopState()
    state.set_field("meta.franchise", "Star Wars (Legends)")
    state.set_field("meta.era", "47 ABY")
    state.confirm("meta.franchise")
    state.confirm("meta.era")
    return state


def _make_history(n_turns: int, chars_per_turn: int = 200) -> list[dict]:
    """Generate a conversation history of *n_turns* turns."""
    history = []
    for i in range(n_turns):
        role = "human" if i % 2 == 0 else "assistant"
        content = f"Turn {i}: " + "x" * chars_per_turn
        history.append({"role": role, "content": content})
    return history


class TestShouldSummarize:
    """should_summarize triggers at the correct token threshold."""

    def test_below_threshold(self, tmp_path, mock_router):
        summarizer = WorkshopSummarizer(mock_router, tmp_path)
        # 10 turns * 200 chars = 2000 chars = ~500 tokens (well under 24K).
        history = _make_history(10, chars_per_turn=200)
        assert summarizer.should_summarize(history) is False

    def test_above_threshold(self, tmp_path, mock_router):
        summarizer = WorkshopSummarizer(mock_router, tmp_path)
        # 500 turns * 200 chars = 100_000 chars = ~25K tokens.
        history = _make_history(500, chars_per_turn=200)
        assert summarizer.should_summarize(history) is True

    def test_custom_threshold(self, tmp_path, mock_router):
        summarizer = WorkshopSummarizer(mock_router, tmp_path)
        history = _make_history(10, chars_per_turn=200)
        # 2000 chars = ~500 tokens.  Threshold of 100 should trigger.
        assert summarizer.should_summarize(history, token_threshold=100) is True


class TestRebuildContext:
    """rebuild_context preserves recent turns and injects summary."""

    def test_preserves_recent_turns(self, tmp_path, mock_router, state_with_decisions):
        summarizer = WorkshopSummarizer(mock_router, tmp_path)
        summary = WorkshopSessionSummary(
            session_id="session_001",
            narrative_summary="The team decided on Star Wars Legends.",
            key_decisions_reasoning=["Franchise chosen for depth of lore"],
        )
        recent = _make_history(8)

        rebuilt = summarizer.rebuild_context(summary, recent, state_with_decisions)

        # First message is the compressed system context.
        assert rebuilt[0]["role"] == "system"
        assert "Star Wars (Legends)" in rebuilt[0]["content"]
        # Remaining messages are the 8 recent turns, preserved exactly.
        assert len(rebuilt) == 9  # 1 system + 8 turns
        for i, original in enumerate(recent):
            assert rebuilt[i + 1]["content"] == original["content"]
            assert rebuilt[i + 1]["role"] == original["role"]

    def test_rebuilt_context_under_threshold(self, tmp_path, mock_router, state_with_decisions):
        summarizer = WorkshopSummarizer(mock_router, tmp_path)
        summary = WorkshopSessionSummary(
            session_id="session_001",
            narrative_summary="Short summary.",
            key_decisions_reasoning=["One reason."],
        )
        recent = _make_history(8, chars_per_turn=200)

        rebuilt = summarizer.rebuild_context(summary, recent, state_with_decisions)
        total_tokens = WorkshopSummarizer.estimate_tokens(rebuilt)
        # Should be well under the default 24K threshold.
        assert total_tokens < 24_000


class TestSummaryDataclass:
    """WorkshopSessionSummary serialization round-trip."""

    def test_round_trip(self):
        summary = WorkshopSessionSummary(
            session_id="session_001",
            summary_timestamp="2026-04-07T14:32:00+00:00",
            tokens_compressed=18420,
            decisions_confirmed={"meta": {"franchise": "Star Wars"}},
            open_questions=["Theme not confirmed"],
            current_step="Step 3",
            narrative_summary="The team chose Star Wars Legends.",
            key_decisions_reasoning=["Depth of lore"],
        )

        d = summary.to_dict()
        restored = WorkshopSessionSummary.from_dict(d)

        assert restored.session_id == "session_001"
        assert restored.tokens_compressed == 18420
        assert restored.decisions_confirmed == {"meta": {"franchise": "Star Wars"}}
        assert restored.narrative_summary == "The team chose Star Wars Legends."


class TestSummarize:
    """summarize() calls the router and produces a summary."""

    @pytest.mark.asyncio
    async def test_summarize_produces_summary(self, tmp_path, mock_router, state_with_decisions):
        summarizer = WorkshopSummarizer(mock_router, tmp_path)
        history = _make_history(20, chars_per_turn=200)

        summary = await summarizer.summarize(history, state_with_decisions, session_id="session_001")

        assert summary.session_id == "session_001"
        assert summary.tokens_compressed > 0
        assert summary.narrative_summary == "A summary of the session so far."
        assert summary.current_step == "Step 3 — Conflict Stress Test"

        # Summary file should have been persisted.
        summary_path = tmp_path / "workshop_sessions" / "session_001_summary.json"
        assert summary_path.exists()
