"""Tests for SeriesManager — series seed creation, transition snapshots,
and retroactive series promotion."""

import json
import pytest
from pathlib import Path

from src.concept_workshop.series_manager import SeriesManager
from src.memory.story_state import StoryState


@pytest.fixture
def series_mgr(tmp_path):
    """Create a SeriesManager with a temp project directory."""
    return SeriesManager(tmp_path / "test_project")


@pytest.fixture
def sample_series_seed_data():
    """Minimal valid series seed data."""
    return {
        "series_title": "The Void Chronicles",
        "total_books": 3,
        "series_dramatic_question": "Can unity survive the corruption of power?",
        "series_antagonist_escalation": "Personal rival -> faction leader -> world threat",
        "series_stakes_progression": "Personal survival -> community safety -> existence of magic",
        "series_theme": {
            "thematic_premise": "Unity requires individual sacrifice",
            "per_book_thematic_focus": ["Trust", "Sacrifice", "Legacy"],
        },
        "per_book_outline": [
            {
                "book_number": 1,
                "book_dramatic_question": "Can Kael learn to trust again?",
                "book_role_in_series": "setup",
            },
            {
                "book_number": 2,
                "book_dramatic_question": "What must Kael sacrifice for the greater good?",
                "book_role_in_series": "escalation",
            },
            {
                "book_number": 3,
                "book_dramatic_question": "Can Kael's legacy outlast the corruption?",
                "book_role_in_series": "resolution",
            },
        ],
        "series_promises": [
            {
                "promise_id": "void_origin",
                "description": "The true origin of the Void is revealed",
                "planted_book": 1,
                "payoff_book": 3,
            },
        ],
    }


class TestSeriesSeedCreation:
    """Tests for creating series seeds."""

    def test_create_series_seed(self, series_mgr, sample_series_seed_data):
        """create_series_seed produces valid seed and persists it."""
        seed = series_mgr.create_series_seed(**sample_series_seed_data)
        assert seed["series_title"] == "The Void Chronicles"
        assert seed["total_books"] == 3
        assert len(seed["per_book_outline"]) == 3
        assert len(seed["series_promises"]) == 1
        assert (series_mgr.project_dir / "series_seed.json").exists()

    def test_load_series_seed(self, series_mgr, sample_series_seed_data):
        """load_series_seed round-trips correctly."""
        series_mgr.create_series_seed(**sample_series_seed_data)
        loaded = series_mgr.load_series_seed()
        assert loaded is not None
        assert loaded["series_title"] == "The Void Chronicles"

    def test_load_missing_seed_returns_none(self, series_mgr):
        """load_series_seed returns None when no seed exists."""
        assert series_mgr.load_series_seed() is None


class TestSeriesSeedValidation:
    """Tests for series seed validation."""

    def test_valid_seed_no_errors(self, series_mgr, sample_series_seed_data):
        """A well-formed seed passes validation."""
        seed = series_mgr.create_series_seed(**sample_series_seed_data)
        errors = series_mgr.validate_series_seed(seed)
        assert errors == []

    def test_too_few_books(self, series_mgr):
        """Series with fewer than 2 books is flagged."""
        errors = series_mgr.validate_series_seed({"total_books": 1, "series_promises": [{"x": 1}]})
        assert any("at least 2" in e for e in errors)

    def test_no_cross_book_promises(self, series_mgr):
        """Series with no promises is flagged."""
        errors = series_mgr.validate_series_seed({"total_books": 3, "series_promises": []})
        assert any("promise" in e.lower() for e in errors)

    def test_duplicate_questions_flagged(self, series_mgr):
        """Book question identical to series question is flagged."""
        seed = {
            "total_books": 2,
            "series_dramatic_question": "Can love survive?",
            "per_book_outline": [
                {"book_number": 1, "book_dramatic_question": "Can love survive?"},
            ],
            "series_promises": [{"x": 1}],
        }
        errors = series_mgr.validate_series_seed(seed)
        assert any("identical" in e.lower() for e in errors)


class TestTransitionSnapshot:
    """Tests for transition snapshot generation and import."""

    def test_generate_snapshot(self, series_mgr, tmp_path):
        """generate_transition_snapshot produces valid snapshot."""
        db_path = str(tmp_path / "state.db")
        state = StoryState(db_path=db_path)
        state.add_character(id="kael", name="Kael", emotional_state="determined",
                             current_location="The Citadel")
        state.add_plot_thread(id="void_mystery", description="Origin of the Void",
                               status="active")
        state.add_chekhov_gun(id="broken_seal", item_description="The broken seal",
                                planted_chapter=3)

        snapshot = series_mgr.generate_transition_snapshot(state, book_number=1)
        assert snapshot["book_number"] == 1
        assert len(snapshot["character_end_states"]) >= 1
        assert len(snapshot["unresolved_threads"]) == 1
        assert len(snapshot["unfired_chekhov_guns"]) == 1
        assert (series_mgr.project_dir / "book_1_transition.json").exists()
        state.close()

    def test_import_snapshot(self, series_mgr, tmp_path):
        """import_transition_snapshot loads and validates."""
        snapshot_data = {
            "book_number": 1,
            "character_end_states": [{"id": "kael", "name": "Kael"}],
        }
        path = tmp_path / "snapshot.json"
        with open(path, "w") as f:
            json.dump(snapshot_data, f)

        loaded = series_mgr.import_transition_snapshot(str(path))
        assert loaded["book_number"] == 1

    def test_import_missing_snapshot_raises(self, series_mgr):
        """import_transition_snapshot raises for nonexistent file."""
        with pytest.raises(FileNotFoundError):
            series_mgr.import_transition_snapshot("/nonexistent/path.json")

    def test_import_invalid_snapshot_raises(self, series_mgr, tmp_path):
        """import_transition_snapshot raises for invalid format."""
        path = tmp_path / "bad.json"
        with open(path, "w") as f:
            json.dump({"some_field": "no required fields"}, f)
        with pytest.raises(ValueError, match="missing required field"):
            series_mgr.import_transition_snapshot(str(path))


class TestRetroactivePromotion:
    """Tests for promoting a standalone seed to series."""

    def test_promote_to_series(self, series_mgr):
        """promote_to_series creates a valid series seed from standalone."""
        concept_seed = {
            "premise": {"central_dramatic_question": "Can Kael overcome betrayal?"},
            "theme": {"thematic_premise": "Trust requires vulnerability"},
        }
        seed = series_mgr.promote_to_series(
            concept_seed=concept_seed,
            series_title="The Kael Saga",
            total_books=3,
            series_dramatic_question="Can trust endure across generations?",
            series_stakes_progression="Personal -> communal -> existential",
        )
        assert seed["series_title"] == "The Kael Saga"
        assert seed["total_books"] == 3
        assert seed["per_book_outline"][0]["book_role_in_series"] == "setup"
        assert seed["per_book_outline"][0]["book_dramatic_question"] == "Can Kael overcome betrayal?"
        assert len(seed["series_promises"]) >= 1


class TestSeriesConsistency:
    """Tests for validate_series_consistency."""

    def test_consistent_book_no_warnings(self, series_mgr, sample_series_seed_data):
        """Consistent book seed produces no warnings."""
        series_seed = series_mgr.create_series_seed(**sample_series_seed_data)
        book_seed = {
            "meta": {"book_number": 1},
            "premise": {"central_dramatic_question": "Can Kael learn to trust again?"},
        }
        warnings = series_mgr.validate_series_consistency(series_seed, book_seed)
        assert warnings == []

    def test_duplicate_question_warned(self, series_mgr, sample_series_seed_data):
        """Book question identical to series question triggers warning."""
        series_seed = series_mgr.create_series_seed(**sample_series_seed_data)
        book_seed = {
            "meta": {"book_number": 1},
            "premise": {
                "central_dramatic_question": "Can unity survive the corruption of power?",
            },
        }
        warnings = series_mgr.validate_series_consistency(series_seed, book_seed)
        assert any("identical" in w.lower() for w in warnings)
