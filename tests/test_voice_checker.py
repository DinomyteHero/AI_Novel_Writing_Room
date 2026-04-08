"""Tests for VoiceChecker."""
import pytest
from src.quality.voice_checker import VoiceChecker


class TestVoiceChecker:
    def test_clean_prose_scores_high(self, negative_constraints, sample_prose):
        checker = VoiceChecker(negative_constraints)
        result = checker.analyze(sample_prose)
        assert result["voice_fidelity_score"] >= 0.7
        assert len(result["banned_phrases_found"]) == 0

    def test_empty_prose(self, negative_constraints):
        checker = VoiceChecker(negative_constraints)
        result = checker.analyze("")
        assert result["voice_fidelity_score"] == 1.0

    def test_banned_phrase_detection(self, negative_constraints):
        prose = "It wasn't just a mission, it was a testament to their resolve. A tapestry of emotions."
        checker = VoiceChecker(negative_constraints)
        result = checker.analyze(prose)
        assert len(result["banned_phrases_found"]) > 0
        categories = {h["category"] for h in result["banned_phrases_found"]}
        assert "faux_profundity" in categories

    def test_adverb_density_clean(self, negative_constraints):
        prose = "He walked to the door. She opened it. They left together."
        checker = VoiceChecker(negative_constraints)
        result = checker.analyze(prose)
        assert result["adverb_flag"] is False
        assert result["adverb_density"] < 0.02

    def test_adverb_density_excessive(self, negative_constraints):
        prose = (
            "He quickly ran remarkably fast. She quietly whispered softly. "
            "They gently carefully slowly moved gracefully forward. "
            "He nervously anxiously desperately looked around wildly."
        )
        checker = VoiceChecker(negative_constraints)
        result = checker.analyze(prose)
        assert result["adverb_density"] > 0.02
        assert result["adverb_flag"] is True

    def test_adverb_false_positives_excluded(self, negative_constraints):
        prose = "The only family that really mattered was the early morning daily routine."
        checker = VoiceChecker(negative_constraints)
        result = checker.analyze(prose)
        # "only", "really", "family", "early", "daily" should NOT count as adverbs
        assert result["adverb_density"] == 0.0

    def test_metaphor_cooldown_violation(self, negative_constraints):
        prose = (
            "She moved like a ghost.\n\n"
            "He spoke as if the world might end.\n\n"
            "Normal paragraph.\n\n"
            "Another normal paragraph."
        )
        checker = VoiceChecker(negative_constraints)
        result = checker.analyze(prose)
        # Two metaphors within 8 paragraphs
        assert len(result["metaphor_violations"]) > 0

    def test_metaphor_cooldown_no_violation(self, negative_constraints):
        paras = ["Normal paragraph."] * 10
        paras[0] = "She moved like a ghost."
        paras[9] = "He spoke as if the world might end."
        prose = "\n\n".join(paras)
        checker = VoiceChecker(negative_constraints)
        result = checker.analyze(prose)
        # 9 paragraphs apart > 8 cooldown
        assert len(result["metaphor_violations"]) == 0

    def test_voice_fidelity_short_sentence_character(self, negative_constraints):
        checker = VoiceChecker(negative_constraints)
        # Voice notes say short/terse, but prose has long sentences
        long_prose = (
            "He contemplated the vast and overwhelming complexity of the situation "
            "that lay before him with great deliberation and careful consideration "
            "of all the many possible outcomes and their various ramifications."
        )
        result = checker.analyze(long_prose, voice_notes="Short, terse sentences. Laconic.")
        assert "voice_notes" in result
        # Should penalize for mismatch
        assert result["voice_fidelity_score"] < 1.0

    def test_sloppy_prose_scores_low(self, negative_constraints, sloppy_prose):
        checker = VoiceChecker(negative_constraints)
        result = checker.analyze(sloppy_prose)
        assert result["voice_fidelity_score"] < 0.6
        assert len(result["banned_phrases_found"]) > 3

    def test_result_structure(self, negative_constraints, sample_prose):
        checker = VoiceChecker(negative_constraints)
        result = checker.analyze(sample_prose)
        assert "voice_fidelity_score" in result
        assert "banned_phrases_found" in result
        assert "adverb_density" in result
        assert "adverb_flag" in result
        assert "metaphor_violations" in result
        assert 0.0 <= result["voice_fidelity_score"] <= 1.0
