"""Tests for multi-scene chapter aggregation in MetricsDashboard and PacingAnalyzer."""

import pytest

from src.quality.metrics_dashboard import MetricsDashboard
from src.quality.pacing_analyzer import PacingAnalyzer
from src.planning.physics_enforcer import PhysicsEnforcer


class TestMetricsChapterAggregate:
    """Test MetricsDashboard.analyze_chapter_multi_scene()."""

    def _make_scene_result(self, chapter: int, scene: int, score: float) -> dict:
        return {
            "chapter_number": chapter,
            "scene_number": scene,
            "overall_score": score,
            "word_count": 1200,
            "repetition": {"repetition_score": score},
            "pacing": {"pacing_score": score},
            "voice": {"voice_fidelity_score": score},
            "slop": {"slop_score": score},
            "passed": score >= 0.6,
            "flags": [],
        }

    def test_aggregate_scoring(self):
        dashboard = MetricsDashboard.__new__(MetricsDashboard)
        results = [
            self._make_scene_result(5, 1, 0.8),
            self._make_scene_result(5, 2, 0.7),
            self._make_scene_result(5, 3, 0.9),
        ]
        agg = dashboard.analyze_chapter_multi_scene(results)

        assert agg["chapter_number"] == 5
        assert agg["scene_count"] == 3
        assert agg["min_score"] == 0.7
        assert agg["max_score"] == 0.9
        assert 0.79 < agg["avg_score"] < 0.81
        assert agg["passed"] is True

    def test_weakest_scene_identified(self):
        dashboard = MetricsDashboard.__new__(MetricsDashboard)
        results = [
            self._make_scene_result(5, 1, 0.9),
            self._make_scene_result(5, 2, 0.3),
            self._make_scene_result(5, 3, 0.8),
        ]
        agg = dashboard.analyze_chapter_multi_scene(results)

        assert agg["weakest_scene"] == 2
        assert agg["passed"] is False  # min 0.3 < 0.4

    def test_empty_results(self):
        dashboard = MetricsDashboard.__new__(MetricsDashboard)
        agg = dashboard.analyze_chapter_multi_scene([])
        assert agg["scene_count"] == 0
        assert agg["passed"] is False


class TestPacingChapterAggregate:
    """Test PacingAnalyzer.analyze_chapter_pacing()."""

    def test_diverse_scenes_high_variety(self):
        analyzer = PacingAnalyzer.__new__(PacingAnalyzer)
        scenes = [
            {"sentence_length_variance": 0.3, "scene_type_distribution": {"action": 0.6, "dialogue": 0.3, "introspection": 0.1}},
            {"sentence_length_variance": 0.5, "scene_type_distribution": {"dialogue": 0.5, "introspection": 0.3, "description": 0.2}},
            {"sentence_length_variance": 0.4, "scene_type_distribution": {"introspection": 0.4, "action": 0.3, "description": 0.3}},
        ]
        result = analyzer.analyze_chapter_pacing(scenes)

        assert result["variety_index"] > 0.2  # diverse
        assert len(result["flags"]) == 0

    def test_uniform_scenes_low_variety(self):
        analyzer = PacingAnalyzer.__new__(PacingAnalyzer)
        scenes = [
            {"sentence_length_variance": 0.3, "scene_type_distribution": {"action": 0.9, "dialogue": 0.1}},
            {"sentence_length_variance": 0.3, "scene_type_distribution": {"action": 0.85, "dialogue": 0.15}},
            {"sentence_length_variance": 0.3, "scene_type_distribution": {"action": 0.95, "dialogue": 0.05}},
        ]
        result = analyzer.analyze_chapter_pacing(scenes)

        assert result["variety_index"] < 0.2  # uniform
        assert len(result["flags"]) > 0
        assert "action" in result["flags"][0].lower()

    def test_empty_input(self):
        analyzer = PacingAnalyzer.__new__(PacingAnalyzer)
        result = analyzer.analyze_chapter_pacing([])
        assert result["variety_index"] == 0.0


class TestPressureProgression:
    """Test PhysicsEnforcer.validate_chapter_pressure_progression()."""

    def test_ascending_pressure_passes(self):
        cards = [
            {"scene_number": 1, "conflict_type": "internal", "stakes": {"personal": "x", "interpersonal": "", "external": ""}},
            {"scene_number": 2, "conflict_type": "interpersonal", "stakes": {"personal": "x", "interpersonal": "y", "external": ""}},
            {"scene_number": 3, "conflict_type": "external", "stakes": {"personal": "x", "interpersonal": "y", "external": "z"}},
        ]
        issues = PhysicsEnforcer.validate_chapter_pressure_progression(cards)
        assert len(issues) == 0

    def test_final_scene_lowest_pressure_flagged(self):
        cards = [
            {"chapter_number": 5, "scene_number": 1, "conflict_type": "external", "stakes": {"personal": "x", "interpersonal": "y", "external": "z"}},
            {"chapter_number": 5, "scene_number": 2, "conflict_type": "interpersonal", "stakes": {"personal": "x", "interpersonal": "y", "external": "z"}},
            {"chapter_number": 5, "scene_number": 3, "conflict_type": "internal", "stakes": {"personal": "x", "interpersonal": "", "external": ""}},
        ]
        issues = PhysicsEnforcer.validate_chapter_pressure_progression(cards)
        assert any(i["issue_type"] == "weak_chapter_ending" for i in issues)

    def test_single_scene_no_issues(self):
        cards = [{"scene_number": 1, "conflict_type": "internal", "stakes": {"personal": "x"}}]
        issues = PhysicsEnforcer.validate_chapter_pressure_progression(cards)
        assert len(issues) == 0
