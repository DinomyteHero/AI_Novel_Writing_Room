"""Tests for PacingAnalyzer."""
import pytest
from src.quality.pacing_analyzer import PacingAnalyzer


class TestPacingAnalyzer:
    def setup_method(self):
        self.analyzer = PacingAnalyzer()

    def test_clean_prose_scores_well(self, sample_prose):
        result = self.analyzer.analyze(sample_prose)
        assert result["pacing_score"] >= 0.6
        assert isinstance(result["sentence_length_variance"], float)

    def test_empty_prose(self):
        result = self.analyzer.analyze("")
        assert result["pacing_score"] == 1.0

    def test_monotonous_prose_flags_low_variance(self):
        # All sentences same length
        prose = ". ".join(["The man walked down the road slowly"] * 20) + "."
        result = self.analyzer.analyze(prose)
        # Low variance = bad
        assert result["variance_flag"] is True or result["sentence_length_variance"] < 0.3

    def test_varied_prose_no_variance_flag(self):
        prose = (
            "Run. The explosion shattered the viewport into a thousand fragments "
            "that caught the emergency lighting like scattered diamonds. He dove. "
            "Glass everywhere. The alarms screamed their warning to an empty corridor "
            "while smoke billowed through the ventilation system in thick gray coils."
        )
        result = self.analyzer.analyze(prose)
        # Should have good variance
        assert result["sentence_length_variance"] > 0.2

    def test_dialogue_ratio(self):
        # Mostly dialogue
        prose = (
            '"Hello there," she said.\n\n'
            '"General Kenobi," he replied.\n\n'
            '"You are a bold one," she observed.\n\n'
            '"I have the high ground," he warned.\n\n'
            'The room fell silent for a moment.'
        )
        result = self.analyzer.analyze(prose)
        assert result["dialogue_ratio"] > 0.3

    def test_scene_type_distribution(self, sample_prose):
        result = self.analyzer.analyze(sample_prose)
        dist = result["scene_type_distribution"]
        assert "action" in dist
        assert "dialogue" in dist
        assert "introspection" in dist
        assert "description" in dist
        # All should sum to approximately 1.0
        total = sum(dist.values())
        assert 0.9 <= total <= 1.1

    def test_event_density(self, sample_prose):
        result = self.analyzer.analyze(sample_prose, structural_phase="setup")
        assert result["event_density_per_1k"] >= 0
        assert len(result["expected_density_range"]) == 2

    def test_structural_phase_affects_density_range(self):
        prose = "Action happened. They ran. Explosions. Fighting. More action."
        setup = self.analyzer.analyze(prose, structural_phase="setup")
        climax = self.analyzer.analyze(prose, structural_phase="climax")
        # Different phases should have different expected ranges
        assert setup["expected_density_range"] != climax["expected_density_range"]

    def test_result_structure(self, sample_prose):
        result = self.analyzer.analyze(sample_prose)
        assert "pacing_score" in result
        assert "sentence_length_variance" in result
        assert "variance_flag" in result
        assert "dialogue_ratio" in result
        assert "scene_type_distribution" in result
        assert "event_density_per_1k" in result
        assert 0.0 <= result["pacing_score"] <= 1.0
