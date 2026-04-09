"""Integration test: series workflow — create series seed, generate Book 1,
transition snapshot, and validate Book 2 setup."""

import json
import pytest
from pathlib import Path

from src.concept_workshop.series_manager import SeriesManager
from src.memory.story_state import StoryState


@pytest.fixture
def series_project(tmp_path):
    """Set up a complete series project structure."""
    project_dir = tmp_path / "void_chronicles"
    mgr = SeriesManager(project_dir)

    # Step 1: Create series seed
    series_seed = mgr.create_series_seed(
        series_title="The Void Chronicles",
        total_books=3,
        series_dramatic_question="Can unity survive the corruption of power?",
        series_antagonist_escalation="Personal rival -> faction leader -> cosmic threat",
        series_stakes_progression="Personal survival -> community -> existence of magic",
        series_theme={
            "thematic_premise": "Unity requires sacrifice",
            "per_book_thematic_focus": ["Trust", "Sacrifice", "Legacy"],
        },
        per_book_outline=[
            {"book_number": 1, "book_dramatic_question": "Can Kael learn to trust?",
             "book_role_in_series": "setup"},
            {"book_number": 2, "book_dramatic_question": "What must be sacrificed?",
             "book_role_in_series": "escalation"},
            {"book_number": 3, "book_dramatic_question": "What legacy endures?",
             "book_role_in_series": "resolution"},
        ],
        series_promises=[
            {"promise_id": "void_origin", "description": "Origin of the Void revealed",
             "planted_book": 1, "payoff_book": 3},
            {"promise_id": "mentor_truth", "description": "Morreth's true motivation",
             "planted_book": 1, "payoff_book": 2},
        ],
    )

    return mgr, series_seed, project_dir


class TestSeriesWorkflow:
    """End-to-end series workflow test."""

    def test_series_seed_creation(self, series_project):
        """Series seed is created and valid."""
        mgr, seed, project_dir = series_project
        assert seed["total_books"] == 3
        assert len(seed["series_promises"]) == 2
        assert (project_dir / "series_seed.json").exists()

    def test_series_seed_loads_correctly(self, series_project):
        """Series seed can be loaded back from disk."""
        mgr, _, _ = series_project
        loaded = mgr.load_series_seed()
        assert loaded is not None
        assert loaded["series_title"] == "The Void Chronicles"

    def test_book1_state_initialization(self, series_project, tmp_path):
        """Book 1 story state initializes with Phase 5 tables."""
        _, _, _ = series_project
        db_path = str(tmp_path / "book1.db")
        state = StoryState(db_path=db_path)

        # Simulate Book 1 concept seed initialization
        book1_seed = {
            "meta": {"project_scope": "planned_series", "book_number": 1},
            "ensemble_cast": [
                {
                    "name": "Kael",
                    "role": "Protagonist",
                    "weiland_arc": {
                        "lie_believed": "Trust is weakness",
                        "ghost": "Mentor betrayal",
                        "want": "Solo power",
                        "need": "Connection",
                        "arc_type": "positive_change",
                    },
                },
            ],
            "subplots": [
                {"subplot_id": "main", "name": "Seal the breach",
                 "line_type": "A", "chapters_active": [1, 25]},
            ],
            "hooks": [
                {"hook_id": "void_origin", "description": "What created the Void",
                 "hook_type": "hard", "planted_in": "Chapter 2",
                 "resolved_in": None},
            ],
            "terminology_registry": [
                {"term": "The Void", "definition": "Corrupting darkness", "category": "concept"},
            ],
        }
        state.init_from_concept_seed(book1_seed)

        # Verify all Phase 5 tables populated
        assert state.get_character_arc("kael") is not None
        assert len(state.get_all_subplots()) == 1
        assert len(state.get_all_hooks()) == 1
        assert state.find_term("The Void") is not None
        state.close()

    def test_book1_arc_progression(self, series_project, tmp_path):
        """Simulate arc progression through Book 1."""
        _, _, _ = series_project
        db_path = str(tmp_path / "progression.db")
        state = StoryState(db_path=db_path)
        state.add_character(id="kael", name="Kael")
        state.add_character_arc(
            character_id="kael", arc_type="positive_change",
            lie_believed="Trust is weakness", ghost="Betrayal",
            want="Solo power", need="Connection",
        )

        # Simulate progression through chapters
        assert state.advance_arc_phase("kael", "lie_questioned", chapter=5)
        assert state.advance_arc_phase("kael", "lie_cracking", chapter=13)
        assert state.advance_arc_phase("kael", "lie_confronted", chapter=20)
        assert state.advance_arc_phase("kael", "truth_accepted", chapter=24)

        arc = state.get_character_arc("kael")
        assert arc["current_phase"] == "truth_accepted"
        assert arc["phase_chapter"] == 24
        state.close()

    def test_transition_snapshot_generation(self, series_project, tmp_path):
        """Transition snapshot captures Book 1 end state."""
        mgr, _, _ = series_project
        db_path = str(tmp_path / "book1_end.db")
        state = StoryState(db_path=db_path)
        state.add_character(id="kael", name="Kael", emotional_state="hopeful",
                             current_location="The Sealed Breach")
        state.add_character_arc(
            character_id="kael", arc_type="positive_change",
            lie_believed="Trust is weakness", ghost="Betrayal",
            want="Solo power", need="Connection",
            current_phase="truth_accepted",
        )
        state.add_plot_thread(id="void_origin", description="Origin of the Void",
                               status="active")
        state.add_hook(hook_id="void_origin", description="What created the Void",
                       hook_type="mystery_question", planted_chapter=2, priority="hard")

        snapshot = mgr.generate_transition_snapshot(state, book_number=1)

        assert snapshot["book_number"] == 1
        assert len(snapshot["character_end_states"]) >= 1
        assert snapshot["character_end_states"][0]["emotional_state"] == "hopeful"
        assert len(snapshot["unresolved_threads"]) == 1
        assert len(snapshot["unresolved_hooks"]) == 1
        state.close()

    def test_transition_snapshot_import_for_book2(self, series_project, tmp_path):
        """Transition snapshot can be imported for Book 2 planning."""
        mgr, _, project_dir = series_project

        # Create a snapshot file
        snapshot_data = {
            "book_number": 1,
            "character_end_states": [
                {"id": "kael", "name": "Kael", "location": "The Sealed Breach",
                 "emotional_state": "hopeful", "arc_position": "truth_accepted"},
            ],
            "character_arc_states": [
                {"character_id": "kael", "current_phase": "truth_accepted",
                 "arc_type": "positive_change", "lie_believed": "Trust is weakness",
                 "need": "Connection"},
            ],
            "unresolved_threads": [
                {"id": "void_origin", "description": "Origin of the Void",
                 "status": "active", "urgency": "rising"},
            ],
            "unresolved_hooks": [
                {"hook_id": "void_origin", "description": "What created the Void",
                 "priority": "hard", "current_status": "advancing"},
            ],
            "unfired_chekhov_guns": [],
        }
        snapshot_path = project_dir / "book_1_transition.json"
        with open(snapshot_path, "w") as f:
            json.dump(snapshot_data, f)

        loaded = mgr.import_transition_snapshot(str(snapshot_path))
        assert loaded["book_number"] == 1
        assert len(loaded["unresolved_threads"]) == 1
        assert loaded["character_end_states"][0]["emotional_state"] == "hopeful"

    def test_series_consistency_validation(self, series_project):
        """Series consistency validation catches identical questions."""
        mgr, series_seed, _ = series_project

        # Book with different question — should pass
        good_book = {
            "meta": {"book_number": 1},
            "premise": {"central_dramatic_question": "Can Kael learn to trust?"},
        }
        warnings = mgr.validate_series_consistency(series_seed, good_book)
        assert len(warnings) == 0

        # Book with identical question to series — should warn
        bad_book = {
            "meta": {"book_number": 2},
            "premise": {
                "central_dramatic_question": "Can unity survive the corruption of power?",
            },
        }
        warnings = mgr.validate_series_consistency(series_seed, bad_book)
        assert len(warnings) > 0
        assert any("identical" in w.lower() for w in warnings)
