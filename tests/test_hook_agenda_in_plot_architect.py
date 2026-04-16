"""Tests for hook/subplot/arc context injection in PlotArchitect."""

import pytest

from src.agents.plot_architect import PlotArchitect


class TestPlotArchitectPhase5Context:
    """Tests that PlotArchitect includes Phase 5 context in formatted output."""

    @pytest.fixture
    def architect(self, mock_router):
        return PlotArchitect(mock_router)

    def test_hook_agenda_included(self, architect):
        """Hook agenda appears in formatted context when provided."""
        context = {
            "scene_card": {"chapter_number": 5, "pov_character": "Hero",
                           "mission": "Test", "conflict": "X", "turning_point": "Y"},
            "hook_agenda": "## Hook Agenda\n- Plant: broken_seal\n- Advance: mentor_secret",
        }
        formatted = architect._format_context(context)
        assert "Hook Agenda" in formatted
        assert "broken_seal" in formatted
        assert "mentor_secret" in formatted

    def test_arc_context_included(self, architect):
        """Arc context appears in formatted context when provided."""
        context = {
            "scene_card": {"chapter_number": 5, "pov_character": "Hero",
                           "mission": "Test", "conflict": "X", "turning_point": "Y"},
            "arc_context": "Lie: Trust is weakness\nPhase: lie_questioned",
        }
        formatted = architect._format_context(context)
        assert "POV Character Arc" in formatted
        assert "Trust is weakness" in formatted

    def test_subplot_context_included(self, architect):
        """Subplot context appears in formatted context when provided."""
        context = {
            "scene_card": {"chapter_number": 5, "pov_character": "Hero",
                           "mission": "Test", "conflict": "X", "turning_point": "Y"},
            "subplot_context": "B-line: Trust Arc (active)\nC-line: Scholar's secret (planned)",
        }
        formatted = architect._format_context(context)
        assert "Active Subplots" in formatted
        assert "Trust Arc" in formatted

    def test_generation_brief_requests_hook_subplot_revelation_fields(self, architect):
        """The task prompt names the typed brief fields for hooks/subplots/revelations."""
        context = {
            "scene_card": {"chapter_number": 1, "pov_character": "Hero",
                           "mission": "Test", "conflict": "X", "turning_point": "Y"},
        }
        formatted = architect._format_context(context)
        # The Phase 2 typed brief surfaces these as dedicated array fields
        # instead of prose "directive" sections.
        assert "required_hooks" in formatted
        assert "required_subplots" in formatted
        assert "required_revelations" in formatted

    def test_no_phase5_context_still_works(self, architect):
        """Without Phase 5 context, formatting still works (backward compat)."""
        context = {
            "scene_card": {"chapter_number": 1, "pov_character": "Hero",
                           "mission": "Test", "conflict": "X", "turning_point": "Y"},
            "bible_summary": "Story bible here",
        }
        formatted = architect._format_context(context)
        assert "Story Bible Summary" in formatted
        assert "Task" in formatted
