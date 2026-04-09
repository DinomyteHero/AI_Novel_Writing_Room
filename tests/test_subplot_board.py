"""Tests for the subplots table and lifecycle tracking."""

import pytest

from src.memory.story_state import StoryState


class TestSubplotCRUD:
    """Tests for basic CRUD on the subplots table."""

    def test_add_and_get_subplot(self, story_state):
        """add_subplot followed by get_subplot round-trips."""
        story_state.add_subplot(
            subplot_id="trust_arc",
            subplot_name="Ben and Lyra's trust arc",
            line_type="B",
            characters_involved=["ben", "lyra"],
            start_chapter=2,
            resolution_chapter=18,
            structural_purpose="Tests the theme of vulnerability",
            interweave_points=[5, 9, 14],
        )
        sub = story_state.get_subplot("trust_arc")
        assert sub is not None
        assert sub["subplot_name"] == "Ben and Lyra's trust arc"
        assert sub["line_type"] == "B"
        assert sub["characters_involved"] == ["ben", "lyra"]
        assert sub["interweave_points"] == [5, 9, 14]
        assert sub["current_status"] == "planned"

    def test_get_missing_subplot_returns_none(self, story_state):
        """get_subplot returns None for nonexistent subplot."""
        assert story_state.get_subplot("nonexistent") is None

    def test_update_subplot(self, story_state):
        """update_subplot modifies specific fields."""
        story_state.add_subplot(subplot_id="s1", subplot_name="Test", line_type="C")
        story_state.update_subplot("s1", current_status="active", start_chapter=3)
        sub = story_state.get_subplot("s1")
        assert sub["current_status"] == "active"
        assert sub["start_chapter"] == 3

    def test_get_active_subplots(self, story_state):
        """get_active_subplots excludes resolved and abandoned."""
        story_state.add_subplot(subplot_id="active1", subplot_name="Active", line_type="A",
                                 current_status="active")
        story_state.add_subplot(subplot_id="resolved1", subplot_name="Resolved", line_type="B",
                                 current_status="resolved")
        story_state.add_subplot(subplot_id="abandoned1", subplot_name="Abandoned", line_type="C",
                                 current_status="abandoned")
        story_state.add_subplot(subplot_id="planned1", subplot_name="Planned", line_type="D",
                                 current_status="planned")
        active = story_state.get_active_subplots()
        ids = {s["subplot_id"] for s in active}
        assert "active1" in ids
        assert "planned1" in ids
        assert "resolved1" not in ids
        assert "abandoned1" not in ids

    def test_get_all_subplots(self, story_state):
        """get_all_subplots returns everything."""
        story_state.add_subplot(subplot_id="x", subplot_name="X", line_type="A")
        story_state.add_subplot(subplot_id="y", subplot_name="Y", line_type="B")
        assert len(story_state.get_all_subplots()) == 2

    def test_get_all_subplots_filtered_by_book(self, story_state):
        """get_all_subplots filters by book_number."""
        story_state.add_subplot(subplot_id="b1s", subplot_name="Book 1", line_type="A",
                                 book_number=1)
        story_state.add_subplot(subplot_id="b2s", subplot_name="Book 2", line_type="A",
                                 book_number=2)
        assert len(story_state.get_all_subplots(book_number=1)) == 1
        assert len(story_state.get_all_subplots(book_number=2)) == 1

    def test_json_round_trip_for_list_fields(self, story_state):
        """JSON-serialized list fields deserialize correctly."""
        story_state.add_subplot(
            subplot_id="json_test",
            subplot_name="JSON Test",
            line_type="B",
            characters_involved=["a", "b", "c"],
            interweave_points=[1, 5, 10, 15],
        )
        sub = story_state.get_subplot("json_test")
        assert sub["characters_involved"] == ["a", "b", "c"]
        assert sub["interweave_points"] == [1, 5, 10, 15]
