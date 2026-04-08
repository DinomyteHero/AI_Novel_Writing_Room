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

    def test_generation_brief_requests_new_sections(self, architect):
        """The task prompt includes Hook/Subplot/Arc directives."""
        context = {
            "scene_card": {"chapter_number": 1, "pov_character": "Hero",
                           "mission": "Test", "conflict": "X", "turning_point": "Y"},
        }
        formatted = architect._format_context(context)
        assert "Hook directives" in formatted
        assert "Subplot directives" in formatted
        assert "Arc phase directive" in formatted

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
