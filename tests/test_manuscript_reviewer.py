"""Tests for ManuscriptReviewer agent."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.agents.manuscript_reviewer import ManuscriptReviewer


class TestManuscriptReviewerFormat:
    """Tests for _format_context."""

    @pytest.fixture
    def reviewer(self, mock_router):
        return ManuscriptReviewer(mock_router)

    def test_format_includes_prose(self, reviewer):
        """Prose text appears in formatted context."""
        context = {
            "prose": "Chapter 1: The hero walked into the darkness...",
        }
        formatted = reviewer._format_context(context)
        assert "hero walked into the darkness" in formatted

    def test_format_includes_chapter_summaries(self, reviewer):
        """Chapter summaries appear when provided."""
        context = {
            "prose": "Test prose",
            "chapter_summaries": [
                {"title": "Chapter 1", "summary": "Setup complete"},
                {"title": "Chapter 2", "summary": "Conflict introduced"},
            ],
        }
        formatted = reviewer._format_context(context)
        assert "Setup complete" in formatted

    def test_format_includes_hooks(self, reviewer):
        """Hooks appear when provided."""
        context = {
            "prose": "Test prose",
            "hooks": "[{\"hook_id\": \"seal\", \"status\": \"planted\"}]",
        }
        formatted = reviewer._format_context(context)
        assert "seal" in formatted

    def test_format_minimal_context(self, reviewer):
        """Works with just prose (all other fields optional)."""
        context = {"prose": "Test prose only"}
        formatted = reviewer._format_context(context)
        assert "Test prose only" in formatted
        assert "Task" in formatted


class TestManuscriptReviewerOutput:
    """Tests for output structure."""

    @pytest.fixture
    def reviewer_with_mock(self):
        """Create reviewer with a mock router that returns valid JSON."""
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "review_persona": "literary_critic",
            "issues": [
                {
                    "severity": "major",
                    "category": "pacing",
                    "description": "Chapters 3-5 have identical tension levels",
                    "affected_chapters": [3, 4, 5],
                    "suggested_fix": "Increase stakes in chapter 4",
                }
            ],
            "overall_assessment": "Strong premise but pacing issues in act 2",
            "recommendation": "revise_specific_chapters",
        })
        return ManuscriptReviewer(router)

    @pytest.mark.asyncio
    async def test_run_returns_expected_structure(self, reviewer_with_mock):
        """run() returns dict with required keys."""
        result = await reviewer_with_mock.run({
            "prose": "Full manuscript text here...",
        })
        assert "issues" in result
        assert "overall_assessment" in result
        assert "recommendation" in result
        assert isinstance(result["issues"], list)

    @pytest.mark.asyncio
    async def test_run_normalizes_issues(self, reviewer_with_mock):
        """Issues have required fields."""
        result = await reviewer_with_mock.run({"prose": "Test"})
        for issue in result["issues"]:
            assert "severity" in issue
            assert "category" in issue
            assert "description" in issue
