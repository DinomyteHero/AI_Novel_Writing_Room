"""Tests for MetricsDashboard."""
import pytest
from src.quality.metrics_dashboard import MetricsDashboard


class TestMetricsDashboard:
    def test_analyze_chapter_structure(self, metrics_dashboard, sample_prose, sample_scene_card):
        result = metrics_dashboard.analyze_chapter(sample_prose, sample_scene_card)
        assert "overall_score" in result
        assert "passed" in result
        assert "repetition" in result
        assert "pacing" in result
        assert "voice" in result
        assert "slop" in result
        assert "chapter_number" in result
        assert "word_count" in result
        assert "flags" in result
        assert isinstance(result["flags"], list)

    def test_analyze_chapter_includes_per_scene(self, metrics_dashboard, sample_prose, sample_scene_card):
        # Consumers (orchestrator, scene_emotion, line_copy) iterate
        # `quality_metrics["per_scene"]`. The key must be present as a
        # single-item list wrapping this scene's result, so those loops
        # actually fire instead of silently no-opping.
        result = metrics_dashboard.analyze_chapter(sample_prose, sample_scene_card)
        assert "per_scene" in result
        assert isinstance(result["per_scene"], list)
        assert len(result["per_scene"]) == 1
        scene = result["per_scene"][0]
        # Inner scene payload must carry the fields consumers actually read.
        assert "pacing" in scene
        assert "repetition" in scene
        assert scene["pacing"] is result["pacing"]  # shared reference, not a copy

    def test_clean_prose_passes(self, metrics_dashboard, sample_prose, sample_scene_card):
        result = metrics_dashboard.analyze_chapter(sample_prose, sample_scene_card)
        assert result["overall_score"] >= 0.5
        assert isinstance(result["passed"], bool)

    def test_sloppy_prose_scores_lower(self, metrics_dashboard, sloppy_prose, sample_scene_card):
        result = metrics_dashboard.analyze_chapter(sloppy_prose, sample_scene_card)
        # Sloppy prose should score significantly lower
        assert result["overall_score"] < 0.8

    def test_overall_score_is_weighted_average(self, metrics_dashboard, sample_prose, sample_scene_card):
        result = metrics_dashboard.analyze_chapter(sample_prose, sample_scene_card)
        expected = 0.25 * (
            result["repetition"]["repetition_score"]
            + result["pacing"]["pacing_score"]
            + result["voice"]["voice_fidelity_score"]
            + result["slop"]["slop_score"]
        )
        assert abs(result["overall_score"] - expected) < 0.01

    def test_pass_threshold(self, metrics_dashboard, sample_prose, sample_scene_card):
        result = metrics_dashboard.analyze_chapter(sample_prose, sample_scene_card)
        if result["overall_score"] >= 0.6:
            assert result["passed"] is True
        else:
            assert result["passed"] is False

    def test_chapter_number_from_scene_card(self, metrics_dashboard, sample_prose, sample_scene_card):
        result = metrics_dashboard.analyze_chapter(sample_prose, sample_scene_card)
        assert result["chapter_number"] == sample_scene_card["chapter_number"]

    def test_analyze_manuscript(self, metrics_dashboard, sample_prose, sample_scene_card):
        ch1 = metrics_dashboard.analyze_chapter(sample_prose, sample_scene_card)
        ch2 = metrics_dashboard.analyze_chapter(sample_prose, sample_scene_card)
        manuscript = metrics_dashboard.analyze_manuscript([ch1, ch2])
        assert "manuscript_score" in manuscript
        assert "chapter_scores" in manuscript
        assert "trends" in manuscript
        assert "worst_chapters" in manuscript
        assert len(manuscript["chapter_scores"]) == 2

    def test_analyze_manuscript_empty(self, metrics_dashboard):
        manuscript = metrics_dashboard.analyze_manuscript([])
        assert manuscript["manuscript_score"] == 0.0
        assert manuscript["chapter_scores"] == []

    def test_empty_prose(self, metrics_dashboard, sample_scene_card):
        result = metrics_dashboard.analyze_chapter("", sample_scene_card)
        assert result["overall_score"] == 1.0
        assert result["word_count"] == 0

    def test_prior_chapters_passed_through(self, metrics_dashboard, sample_prose, sample_scene_card):
        # Should not crash when prior chapters provided
        result = metrics_dashboard.analyze_chapter(
            sample_prose, sample_scene_card,
            prior_chapters=["Some prior chapter text goes here."]
        )
        assert "overall_score" in result

    def test_voice_notes_passed_through(self, metrics_dashboard, sample_prose, sample_scene_card):
        result = metrics_dashboard.analyze_chapter(
            sample_prose, sample_scene_card,
            voice_notes="Short, terse sentences."
        )
        assert "overall_score" in result
