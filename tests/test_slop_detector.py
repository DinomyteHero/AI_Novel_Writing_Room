"""Tests for SlopDetector."""
import pytest
from src.quality.slop_detector import SlopDetector


class TestSlopDetector:
    def test_clean_prose_scores_high(self, negative_constraints, sample_prose):
        detector = SlopDetector(negative_constraints)
        result = detector.analyze(sample_prose)
        assert result["slop_score"] >= 0.7
        assert len(result["ai_tells_found"]) == 0

    def test_empty_prose(self, negative_constraints):
        detector = SlopDetector(negative_constraints)
        result = detector.analyze("")
        assert result["slop_score"] == 1.0

    def test_ai_tell_detection(self, negative_constraints):
        prose = "He delved into the nuanced tapestry of the situation."
        detector = SlopDetector(negative_constraints)
        result = detector.analyze(prose)
        tells = [h["word"] for h in result["ai_tells_found"]]
        assert "delve" in [t.lower() for t in tells] or "delved" in prose.lower()
        assert len(result["ai_tells_found"]) >= 2  # delve + nuanced + tapestry

    def test_show_dont_tell_flagging(self, negative_constraints):
        prose = 'He felt angry. She knew the truth. He realized it was over.'
        detector = SlopDetector(negative_constraints)
        result = detector.analyze(prose)
        assert len(result["tell_not_show"]) >= 2
        words_found = [h["phrase"] for h in result["tell_not_show"]]
        assert "felt" in words_found

    def test_show_dont_tell_ignores_dialogue(self, negative_constraints):
        prose = '"I felt that was wrong," she said.'
        detector = SlopDetector(negative_constraints)
        result = detector.analyze(prose)
        # "felt" is inside dialogue, should NOT be flagged
        assert len(result["tell_not_show"]) == 0

    def test_filler_pattern_detection(self, negative_constraints):
        prose = "In that moment, he understood. Without hesitation, she moved."
        detector = SlopDetector(negative_constraints)
        result = detector.analyze(prose)
        assert len(result["filler_patterns"]) >= 2

    def test_burstiness_score_range(self, negative_constraints, sample_prose):
        detector = SlopDetector(negative_constraints)
        result = detector.analyze(sample_prose)
        assert 0.0 <= result["burstiness_score"] <= 1.0

    def test_sloppy_prose_scores_low(self, negative_constraints, sloppy_prose):
        detector = SlopDetector(negative_constraints)
        result = detector.analyze(sloppy_prose)
        assert result["slop_score"] < 0.5
        assert len(result["ai_tells_found"]) > 3
        assert len(result["filler_patterns"]) > 0

    def test_result_structure(self, negative_constraints, sample_prose):
        detector = SlopDetector(negative_constraints)
        result = detector.analyze(sample_prose)
        assert "slop_score" in result
        assert "ai_tells_found" in result
        assert "burstiness_score" in result
        assert "tell_not_show" in result
        assert "filler_patterns" in result
        assert 0.0 <= result["slop_score"] <= 1.0
