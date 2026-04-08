"""Tests for StressTestRunner — adversarial concept stress testing."""

import pytest

from src.concept_workshop.stress_test import StressTestRunner


@pytest.fixture
def runner():
    """Create a StressTestRunner without a model router (rule-based only)."""
    return StressTestRunner(router=None)


@pytest.fixture
def good_seed():
    """A well-formed concept seed that should score well."""
    return {
        "meta": {
            "project_title": "The Void Chronicles: Book 1",
            "target_chapters": 25,
        },
        "premise": {
            "central_dramatic_question": "Can Kael learn to trust?",
        },
        "conflict": {
            "primary_antagonistic_force": {
                "type": "internal + external",
                "escalation": "Starts as personal rivalry, escalates to faction war, "
                              "culminates in existential threat to the world."
            },
        },
        "structural_notes": {
            "brooks_alignment": {
                "part_1_setup": "Kael arrives at the Academy",
                "first_plot_point": "Discovers the Void breach",
                "midpoint": "Realizes the mentor is compromised",
                "second_plot_point": "Must choose between safety and saving others",
                "part_4_resolution": "Confronts the Void with allies",
            },
        },
        "ensemble_cast": [
            {
                "name": "Kael",
                "weiland_arc": {
                    "lie_believed": "Showing vulnerability will get you killed",
                    "ghost": "Parents were killed when they trusted the wrong person",
                    "want": "To become powerful enough to never be hurt again",
                    "need": "To accept that strength comes from connection",
                    "arc_type": "positive_change",
                },
            },
            {
                "name": "Lyra",
                "weiland_arc": {
                    "lie_believed": "Rules exist to protect the powerful, not the weak",
                    "ghost": "Grew up in a system that punished her for speaking out",
                    "want": "To dismantle the Academy's hierarchy",
                    "need": "To build new systems rather than just tear down old ones",
                    "arc_type": "positive_change",
                },
            },
        ],
        "hook_map": [
            {"hook_id": "void_origin", "priority": "hard", "payoff_chapter": 20},
            {"hook_id": "mentor_secret", "priority": "hard", "payoff_chapter": 18},
            {"hook_id": "lyra_past", "priority": "soft"},
        ],
        "theme": {
            "thematic_premise": "True strength requires vulnerability",
        },
    }


@pytest.fixture
def weak_seed():
    """A concept seed with known weaknesses."""
    return {
        "meta": {"target_chapters": 6},
        "conflict": {"primary_antagonistic_force": {}},
        "structural_notes": {},
        "ensemble_cast": [
            {"name": "Hero"},  # No Weiland arc
        ],
        "hook_map": [
            {"hook_id": "h1", "priority": "hard"},  # No payoff chapter
            {"hook_id": "h2", "priority": "hard"},
            {"hook_id": "h3", "priority": "hard"},  # Exceeds budget (6/3=2)
        ],
    }


class TestStressTestScoring:
    """Tests for stress test scoring logic."""

    @pytest.mark.asyncio
    async def test_good_seed_scores_well(self, runner, good_seed):
        """A well-formed seed scores >= 7.0 overall."""
        results = await runner.run(good_seed)
        overall = runner.score(results)
        assert overall >= 7.0, f"Good seed scored {overall}, expected >= 7.0"

    @pytest.mark.asyncio
    async def test_weak_seed_has_issues(self, runner, weak_seed):
        """A weak seed has flagged issues."""
        results = await runner.run(weak_seed)
        assert len(results["flagged_issues"]) > 0

    @pytest.mark.asyncio
    async def test_weak_seed_scores_lower(self, runner, good_seed, weak_seed):
        """A weak seed scores lower than a good seed."""
        good_results = await runner.run(good_seed)
        weak_results = await runner.run(weak_seed)
        assert runner.score(weak_results) < runner.score(good_results)


class TestStructuralChecks:
    """Tests for rule-based structural checks."""

    def test_missing_structure_flagged(self, runner):
        """Missing Brooks alignment is flagged."""
        issues = runner._check_structural({"structural_notes": {}})
        assert any("structure" in i.lower() or "brooks" in i.lower() for i in issues)

    def test_missing_midpoint_flagged(self, runner):
        """Missing midpoint is flagged."""
        issues = runner._check_structural({
            "structural_notes": {"brooks_alignment": {"part_1_setup": "yes"}},
        })
        assert any("midpoint" in i.lower() for i in issues)

    def test_missing_escalation_flagged(self, runner):
        """Missing antagonist escalation is flagged."""
        issues = runner._check_structural({
            "conflict": {"primary_antagonistic_force": {}},
            "structural_notes": {"brooks_alignment": {"midpoint": "yes", "second_plot_point": "yes"}},
        })
        assert any("escalation" in i.lower() for i in issues)


class TestCharacterChecks:
    """Tests for rule-based character checks."""

    def test_missing_weiland_arc_flagged(self, runner):
        """Characters without Weiland arcs are listed."""
        issues = runner._check_characters({
            "ensemble_cast": [{"name": "Kael"}, {"name": "Lyra"}],
        })
        assert any("weiland" in i.lower() or "without" in i.lower() for i in issues)

    def test_duplicate_lies_flagged(self, runner):
        """Two characters with identical Lie are flagged."""
        issues = runner._check_characters({
            "ensemble_cast": [
                {"name": "A", "weiland_arc": {"lie_believed": "Trust is weakness",
                                                "need": "Trust", "want": "Power"}},
                {"name": "B", "weiland_arc": {"lie_believed": "Trust is weakness",
                                                "need": "Trust", "want": "Control"}},
            ],
        })
        assert any("same lie" in i.lower() or "share" in i.lower() for i in issues)

    def test_small_cast_flagged(self, runner):
        """Cast with fewer than 2 characters is flagged."""
        issues = runner._check_characters({"ensemble_cast": [{"name": "Solo"}]})
        assert any("fewer than 2" in i for i in issues)


class TestHookChecks:
    """Tests for rule-based hook checks."""

    def test_over_budget_flagged(self, runner):
        """Too many hard hooks for the chapter count is flagged."""
        issues = runner._check_hooks({
            "meta": {"target_chapters": 6},
            "hook_map": [
                {"hook_id": "h1", "priority": "hard", "payoff_chapter": 5},
                {"hook_id": "h2", "priority": "hard", "payoff_chapter": 6},
                {"hook_id": "h3", "priority": "hard", "payoff_chapter": 6},
            ],
        })
        assert any("budget" in i.lower() or "too many" in i.lower() for i in issues)

    def test_missing_payoff_flagged(self, runner):
        """Hard hook without payoff chapter is flagged."""
        issues = runner._check_hooks({
            "meta": {"target_chapters": 30},
            "hook_map": [
                {"hook_id": "h1", "priority": "hard"},  # No payoff_chapter
            ],
        })
        assert any("payoff" in i.lower() for i in issues)


class TestFormatAndScore:
    """Tests for result formatting and scoring."""

    def test_format_results_structure(self, runner):
        """format_results produces expected structure."""
        results = runner.format_results(
            {"premise_strength": 8.0, "character_depth": 7.5},
            ["Issue 1", "Issue 2"],
        )
        assert "scores" in results
        assert "flagged_issues" in results
        assert results["human_approved"] is False
        assert results["approval_timestamp"] is None

    def test_score_average(self, runner):
        """score computes the average of dimension scores."""
        results = {
            "scores": {
                "premise_strength": 8.0,
                "character_depth": 6.0,
                "structural_integrity": 7.0,
                "hook_coherence": 9.0,
                "series_viability": 5.0,
            },
        }
        assert runner.score(results) == 7.0

    def test_score_empty(self, runner):
        """score returns 0.0 for empty results."""
        assert runner.score({}) == 0.0
        assert runner.score({"scores": {}}) == 0.0
