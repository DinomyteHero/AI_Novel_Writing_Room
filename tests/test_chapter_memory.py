"""Tests for ChromaDB-backed chapter memory."""

import pytest

chromadb = pytest.importorskip("chromadb", reason="chromadb not installed")

from src.memory.chapter_memory import ChapterMemory


class TestAddAndGetSummary:
    """Tests for add_summary and get_summary round trip."""

    def test_add_and_get_summary(self, chapter_memory):
        """add_summary followed by get_summary returns the stored text."""
        chapter_memory.add_summary(
            chapter_number=1,
            summary_text="The crew assembles at the Jedi Temple for a mission briefing.",
        )
        result = chapter_memory.get_summary(1)
        assert result is not None
        assert "crew assembles" in result

    def test_get_summary_returns_none_for_missing(self, chapter_memory):
        """get_summary returns None for a chapter that has not been stored."""
        assert chapter_memory.get_summary(999) is None

    def test_add_summary_with_metadata(self, chapter_memory):
        """add_summary stores additional metadata alongside the summary."""
        chapter_memory.add_summary(
            chapter_number=1,
            summary_text="Mission briefing.",
            metadata={"pov_character": "Ben Skywalker", "word_count": 3500},
        )
        result = chapter_memory.get_summary(1)
        assert result is not None

    def test_upsert_overwrites_existing(self, chapter_memory):
        """Adding a summary for an existing chapter overwrites it."""
        chapter_memory.add_summary(chapter_number=1, summary_text="Original summary")
        chapter_memory.add_summary(chapter_number=1, summary_text="Updated summary")
        result = chapter_memory.get_summary(1)
        assert result == "Updated summary"


class TestGetRecentSummaries:
    """Tests for get_recent_summaries."""

    def test_returns_last_n_in_order(self, chapter_memory):
        """get_recent_summaries returns the last N summaries ordered by chapter."""
        for i in range(1, 6):
            chapter_memory.add_summary(
                chapter_number=i,
                summary_text=f"Summary for chapter {i}.",
            )

        result = chapter_memory.get_recent_summaries(n=3)
        assert "Chapter 3" in result
        assert "Chapter 4" in result
        assert "Chapter 5" in result
        # Chapters 1 and 2 should not be in the last 3
        assert "Chapter 1" not in result
        assert "Chapter 2" not in result

    def test_returns_all_when_fewer_than_n(self, chapter_memory):
        """get_recent_summaries returns all when fewer than N summaries exist."""
        chapter_memory.add_summary(chapter_number=1, summary_text="Only chapter.")
        result = chapter_memory.get_recent_summaries(n=5)
        assert "Chapter 1" in result
        assert "Only chapter." in result

    def test_returns_default_when_empty(self, chapter_memory):
        """get_recent_summaries returns a default message when no summaries exist."""
        result = chapter_memory.get_recent_summaries()
        assert result == "No previous chapter summaries available."


class TestSearchSummaries:
    """Tests for search_summaries."""

    def test_returns_relevant_results(self, chapter_memory):
        """search_summaries returns results relevant to the query."""
        chapter_memory.add_summary(
            chapter_number=1,
            summary_text="The crew assembles at the Jedi Temple and receives the mission briefing.",
        )
        chapter_memory.add_summary(
            chapter_number=2,
            summary_text="The ship enters the Unknown Regions and encounters a navigation hazard.",
        )
        chapter_memory.add_summary(
            chapter_number=3,
            summary_text="Ben discovers the Force operates differently in the wound regions.",
        )

        results = chapter_memory.search_summaries("Force wound regions", k=2)
        assert len(results) >= 1
        # Each result should have the expected structure
        first = results[0]
        assert "id" in first
        assert "summary" in first
        assert "metadata" in first
        assert "distance" in first

    def test_search_empty_collection(self, chapter_memory):
        """search_summaries returns empty list when no summaries exist."""
        results = chapter_memory.search_summaries("anything")
        assert results == []

    def test_search_respects_k_limit(self, chapter_memory):
        """search_summaries returns at most k results."""
        for i in range(1, 6):
            chapter_memory.add_summary(
                chapter_number=i, summary_text=f"Summary {i}"
            )
        results = chapter_memory.search_summaries("Summary", k=2)
        assert len(results) == 2


class TestCount:
    """Tests for the count method."""

    def test_count_returns_correct_number(self, chapter_memory):
        """count returns the number of stored summaries."""
        assert chapter_memory.count() == 0
        chapter_memory.add_summary(chapter_number=1, summary_text="First")
        assert chapter_memory.count() == 1
        chapter_memory.add_summary(chapter_number=2, summary_text="Second")
        assert chapter_memory.count() == 2

    def test_count_on_empty_collection(self, chapter_memory):
        """count returns 0 on an empty collection."""
        assert chapter_memory.count() == 0
