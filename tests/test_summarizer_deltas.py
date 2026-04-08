"""Tests for Summarizer validated delta format (Phase 5 change types)."""

import pytest

from src.agents.summarizer import Summarizer


class TestSummarizerNormalization:
    """Tests that _normalize_result includes Phase 5 change types."""

    @pytest.fixture
    def summarizer(self, mock_router):
        return Summarizer(mock_router)

    def test_normalize_adds_phase5_defaults(self, summarizer):
        """Phase 5 change types get empty list defaults."""
        result = {
            "summary": "Test summary",
            "state_diff": {
                "chapter_number": 1,
                "changes": {
                    "character_updates": [],
                    "plot_thread_updates": [],
                    "new_knowledge": [],
                },
            },
        }
        normalized = summarizer._normalize_result(result)
        changes = normalized["state_diff"]["changes"]
        assert "subplot_updates" in changes
        assert "hook_updates" in changes
        assert "arc_phase_updates" in changes
        assert "terminology_updates" in changes
        assert changes["subplot_updates"] == []
        assert changes["hook_updates"] == []

    def test_normalize_preserves_existing_phase5_data(self, summarizer):
        """Phase 5 data already present is not overwritten."""
        result = {
            "summary": "Test",
            "state_diff": {
                "chapter_number": 5,
                "changes": {
                    "character_updates": [],
                    "plot_thread_updates": [],
                    "new_knowledge": [],
                    "arc_phase_updates": [
                        {"character_id": "hero", "old_phase": "lie_reinforced",
                         "new_phase": "lie_questioned", "evidence": "Doubted the lie"},
                    ],
                    "hook_updates": [
                        {"hook_id": "seal", "field": "current_status", "new_value": "advancing"},
                    ],
                },
            },
        }
        normalized = summarizer._normalize_result(result)
        changes = normalized["state_diff"]["changes"]
        assert len(changes["arc_phase_updates"]) == 1
        assert len(changes["hook_updates"]) == 1

    def test_format_context_mentions_phase5_types(self, summarizer):
        """The prompt includes Phase 5 change type descriptions."""
        context = {
            "prose": "Test prose",
            "scene_card": {"chapter_number": 1},
        }
        formatted = summarizer._format_context(context)
        assert "subplot_updates" in formatted
        assert "hook_updates" in formatted
        assert "arc_phase_updates" in formatted
        assert "terminology_updates" in formatted
        assert "False positives are worse than false negatives" in formatted
