"""Tests for propagation_debts table."""

import pytest

from src.memory.story_state import StoryState


class TestPropagationDebtsCRUD:
    """Tests for basic CRUD on propagation_debts."""

    def test_add_and_get_debt(self, story_state):
        """add_propagation_debt followed by get_propagation_debt round-trips."""
        debt_id = story_state.add_propagation_debt(
            source_layer="characters",
            change_description="Updated Kael backstory to include training arc",
            affected_chapters=[3, 5, 8],
        )
        assert debt_id is not None
        debt = story_state.get_propagation_debt(debt_id)
        assert debt is not None
        assert debt["source_layer"] == "characters"
        assert debt["affected_chapters"] == [3, 5, 8]
        assert debt["resolved_at"] is None

    def test_get_missing_debt_returns_none(self, story_state):
        """get_propagation_debt returns None for nonexistent ID."""
        assert story_state.get_propagation_debt(9999) is None

    def test_get_pending_debts(self, story_state):
        """get_pending_debts returns only unresolved debts."""
        id1 = story_state.add_propagation_debt(
            source_layer="world", change_description="Added new faction",
            affected_chapters=[1, 2],
        )
        id2 = story_state.add_propagation_debt(
            source_layer="canon", change_description="Corrected timeline",
            affected_chapters=[4, 6],
        )
        story_state.resolve_propagation_debt(id1, resolution_method="manual_review")
        pending = story_state.get_pending_debts()
        assert len(pending) == 1
        assert pending[0]["id"] == id2

    def test_resolve_debt(self, story_state):
        """resolve_propagation_debt marks debt as resolved."""
        debt_id = story_state.add_propagation_debt(
            source_layer="outline", change_description="Changed midpoint",
            affected_chapters=[10, 11, 12],
        )
        story_state.resolve_propagation_debt(debt_id, "auto_revision")
        debt = story_state.get_propagation_debt(debt_id)
        assert debt["resolved_at"] is not None
        assert debt["resolution_method"] == "auto_revision"

    def test_affected_chapters_json_round_trip(self, story_state):
        """affected_chapters list serializes and deserializes through JSON."""
        debt_id = story_state.add_propagation_debt(
            source_layer="characters",
            change_description="Test",
            affected_chapters=[1, 3, 5, 7, 9],
        )
        debt = story_state.get_propagation_debt(debt_id)
        assert debt["affected_chapters"] == [1, 3, 5, 7, 9]
