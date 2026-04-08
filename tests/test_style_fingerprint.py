"""Tests for style_fingerprint table."""

import pytest

from src.memory.story_state import StoryState


class TestStyleFingerprintCRUD:
    """Tests for basic CRUD on style_fingerprint."""

    def test_add_and_get_style_metric(self, story_state):
        """add_style_metric followed by get_style_metrics round-trips."""
        mid = story_state.add_style_metric(
            source="reference_author",
            metric_name="avg_sentence_length",
            metric_value=14.5,
        )
        assert mid is not None
        metrics = story_state.get_style_metrics("reference_author")
        assert len(metrics) == 1
        assert metrics[0]["metric_name"] == "avg_sentence_length"
        assert metrics[0]["metric_value"] == 14.5

    def test_multiple_metrics_per_source(self, story_state):
        """Multiple metrics can be stored for the same source."""
        story_state.add_style_metric("voice", "avg_sentence_length", 12.0)
        story_state.add_style_metric("voice", "dialogue_ratio", 0.35)
        story_state.add_style_metric("voice", "adverb_frequency", 0.018)
        metrics = story_state.get_style_metrics("voice")
        assert len(metrics) == 3
        names = {m["metric_name"] for m in metrics}
        assert names == {"avg_sentence_length", "dialogue_ratio", "adverb_frequency"}

    def test_get_all_metrics(self, story_state):
        """get_style_metrics with no source returns everything."""
        story_state.add_style_metric("ref", "metric1", 1.0)
        story_state.add_style_metric("discovered", "metric2", 2.0)
        all_metrics = story_state.get_style_metrics()
        assert len(all_metrics) == 2

    def test_get_style_fingerprint_dict(self, story_state):
        """get_style_fingerprint_dict returns metric_name -> metric_value dict."""
        story_state.add_style_metric("test_source", "avg_sentence_length", 15.0)
        story_state.add_style_metric("test_source", "dialogue_ratio", 0.4)
        fp = story_state.get_style_fingerprint_dict("test_source")
        assert fp == {"avg_sentence_length": 15.0, "dialogue_ratio": 0.4}

    def test_complex_metric_value(self, story_state):
        """Metric values can be complex JSON (lists, dicts)."""
        story_state.add_style_metric(
            "ref", "top_words",
            ["the", "and", "was", "her", "she"],
        )
        story_state.add_style_metric(
            "ref", "sentence_length_distribution",
            {"mean": 14.5, "std": 6.2, "min": 3, "max": 42},
        )
        metrics = story_state.get_style_metrics("ref")
        words_metric = next(m for m in metrics if m["metric_name"] == "top_words")
        dist_metric = next(m for m in metrics if m["metric_name"] == "sentence_length_distribution")
        assert words_metric["metric_value"] == ["the", "and", "was", "her", "she"]
        assert dist_metric["metric_value"]["mean"] == 14.5
