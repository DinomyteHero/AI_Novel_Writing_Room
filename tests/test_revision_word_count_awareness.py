"""Tests for the Word Count Status block in Bands 2 and 3.

Context: run16's ledger showed Band 3 compressing scene 1 from 1153 (92% of
target) to 943 (75%), and Band 2 trimming scene 2 by 32 words while already
under-length. Neither band received target_word_count information, so they
cut for rhythm/variety even when the scene was already short.

The fix passes a `Word Count Status` note into each band's user message —
same pattern as craft_editor but gated at ratio >= 1.0 (not 0.85), so
revision bands do not undo craft editor's expansion work. These tests
exercise the status-generation logic, not the LLM's response to it.
"""

from unittest.mock import MagicMock

import pytest

from src.revision.line_copy import LineCopyEditor
from src.revision.scene_emotion import SceneEmotionReviewer


@pytest.fixture
def mock_router():
    return MagicMock()


def _prose_of_n_words(n: int) -> str:
    return " ".join(["word"] * n)


class TestLineCopyWordCountStatus:
    def test_emits_preserve_status_well_below_target(self, mock_router):
        """Scene at 64% of target — the classic under-length case."""
        band = LineCopyEditor(mock_router)
        ctx = band._format_context({
            "prose": _prose_of_n_words(800),
            "scene_card": {"target_word_count": 1250},
        })

        assert "## Word Count Status" in ctx
        assert "Current: 800 words / Target: 1250" in ctx
        assert "under target" in ctx
        assert "Do not reduce word count further" in ctx

    def test_emits_preserve_status_just_below_target(self, mock_router):
        """Scene at 92% of target — the run16 scene 1 case that was cut to 75%.

        Under the old 0.85 threshold this would have been "standard cutting
        behavior applies" and the LLM could have kept compressing. The new
        1.0 threshold prevents that.
        """
        band = LineCopyEditor(mock_router)
        ctx = band._format_context({
            "prose": _prose_of_n_words(1153),
            "scene_card": {"target_word_count": 1250},
        })

        assert "## Word Count Status" in ctx
        assert "under target" in ctx
        assert "Do not reduce word count further" in ctx

    def test_emits_standard_status_at_target(self, mock_router):
        """Exactly at target — boundary case (ratio == 1.0 is inclusive)."""
        band = LineCopyEditor(mock_router)
        ctx = band._format_context({
            "prose": _prose_of_n_words(1250),
            "scene_card": {"target_word_count": 1250},
        })

        assert "## Word Count Status" in ctx
        assert "at or above target" in ctx
        assert "standard cutting behavior applies" in ctx
        assert "under target" not in ctx

    def test_emits_standard_status_above_target(self, mock_router):
        band = LineCopyEditor(mock_router)
        ctx = band._format_context({
            "prose": _prose_of_n_words(1400),
            "scene_card": {"target_word_count": 1250},
        })

        assert "at or above target" in ctx
        assert "standard cutting behavior applies" in ctx

    def test_omits_status_when_target_missing(self, mock_router):
        band = LineCopyEditor(mock_router)
        ctx = band._format_context({
            "prose": _prose_of_n_words(500),
            "scene_card": {},
        })

        assert "## Word Count Status" not in ctx

    def test_omits_status_when_scene_card_absent(self, mock_router):
        band = LineCopyEditor(mock_router)
        ctx = band._format_context({
            "prose": _prose_of_n_words(500),
        })

        assert "## Word Count Status" not in ctx


class TestSceneEmotionWordCountStatus:
    def _min_card(self, target: int | None = 1250) -> dict:
        card = {
            "chapter_number": 1,
            "scene_number": 2,
            "characters_present": ["Ben", "Luke"],
        }
        if target is not None:
            card["target_word_count"] = target
        return card

    def test_emits_preserve_status_well_below_target(self, mock_router):
        """Scene at 69% of target — matches run16 scene 2's post-rewrite state."""
        band = SceneEmotionReviewer(mock_router)
        ctx = band._format_context({
            "prose": _prose_of_n_words(865),
            "scene_card": self._min_card(1250),
        })

        assert "## Word Count Status" in ctx
        assert "Current: 865 words / Target: 1250" in ctx
        assert "under target" in ctx
        assert "without reducing word count" in ctx

    def test_emits_preserve_status_just_below_target(self, mock_router):
        """Scene at 96% of target — close to target but still under.

        Under the old 0.85 threshold this would be 'standard' and cuts would
        be allowed. Under 1.0 threshold, preserve."""
        band = SceneEmotionReviewer(mock_router)
        ctx = band._format_context({
            "prose": _prose_of_n_words(1200),
            "scene_card": self._min_card(1250),
        })

        assert "## Word Count Status" in ctx
        assert "under target" in ctx

    def test_emits_standard_status_at_target(self, mock_router):
        band = SceneEmotionReviewer(mock_router)
        ctx = band._format_context({
            "prose": _prose_of_n_words(1250),
            "scene_card": self._min_card(1250),
        })

        assert "## Word Count Status" in ctx
        assert "at or above target" in ctx
        assert "under target" not in ctx

    def test_omits_status_when_target_missing(self, mock_router):
        band = SceneEmotionReviewer(mock_router)
        ctx = band._format_context({
            "prose": _prose_of_n_words(500),
            "scene_card": self._min_card(target=None),
        })

        assert "## Word Count Status" not in ctx
