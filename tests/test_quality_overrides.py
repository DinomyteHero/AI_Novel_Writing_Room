"""Tests for quality metric overrides — allowlist, threshold, adjacency filtering."""

import pytest
import numpy as np

from src.quality.repetition_detector import RepetitionDetector


def _mock_embeddings(paragraphs):
    """Return semi-random embeddings where adjacent paragraphs are similar."""
    rng = np.random.RandomState(42)
    base = rng.randn(128).astype(np.float32)
    embeddings = []
    for i, _ in enumerate(paragraphs):
        noise = rng.randn(128).astype(np.float32) * 0.1
        embeddings.append((base + noise).tolist())
    return embeddings


class TestWordFrequencyAllowlist:
    def test_allowlisted_word_not_flagged(self):
        """Words on the allowlist should not appear in flagged_words."""
        # Repeat 'force' many times — should be flagged without allowlist
        prose = "The force is strong. Use the force. Feel the force. " * 10
        detector_default = RepetitionDetector()
        result_default = detector_default.analyze(prose)
        force_flagged = [f for f in result_default["flagged_words"] if f["word"] == "force"]

        # With allowlist, 'force' should not be flagged
        detector_allow = RepetitionDetector(word_frequency_allowlist=["Force"])
        result_allow = detector_allow.analyze(prose)
        force_flagged_allow = [f for f in result_allow["flagged_words"] if f["word"] == "force"]

        # If force was flagged without allowlist, it should not be flagged with it
        if force_flagged:
            assert len(force_flagged_allow) == 0

    def test_allowlist_case_insensitive(self):
        """Allowlist matching should be case-insensitive."""
        detector = RepetitionDetector(word_frequency_allowlist=["Jedi", "SITH"])
        assert "jedi" in detector.word_frequency_allowlist
        assert "sith" in detector.word_frequency_allowlist

    def test_non_allowlisted_word_still_flagged(self):
        """Words NOT on the allowlist should still be flagged if overused."""
        # Need varied prose so 'remarkable' stands out statistically
        prose = (
            "The knight walked through the forest and saw a bird. "
            "A castle stood on the hill near the river. "
            "The wizard cast spells while reading ancient books. "
            "remarkable remarkable remarkable remarkable remarkable "
            "remarkable remarkable remarkable remarkable remarkable "
            "remarkable remarkable remarkable remarkable remarkable. "
        )
        detector = RepetitionDetector(word_frequency_allowlist=["force"])
        result = detector.analyze(prose)
        remarkable_flagged = [f for f in result["flagged_words"] if f["word"] == "remarkable"]
        assert len(remarkable_flagged) > 0


class TestSemanticSimilarityThreshold:
    def test_higher_threshold_fewer_flags(self):
        """Raising the threshold should produce fewer or equal similar pairs."""
        paragraphs = [
            "The warrior drew his blade and advanced.",
            "The soldier pulled out his sword and moved forward.",
            "The merchant counted gold coins carefully.",
        ]
        # Low threshold — more flags
        det_low = RepetitionDetector(
            embedding_function=_mock_embeddings,
            semantic_similarity_threshold=0.5,
        )
        result_low = det_low.analyze("\n\n".join(paragraphs))

        # High threshold — fewer flags
        det_high = RepetitionDetector(
            embedding_function=_mock_embeddings,
            semantic_similarity_threshold=0.99,
        )
        result_high = det_high.analyze("\n\n".join(paragraphs))

        assert len(result_high["similar_paragraphs"]) <= len(result_low["similar_paragraphs"])


class TestAdjacencyWindow:
    def test_adjacency_window_limits_comparisons(self):
        """With adjacency_window=1, only consecutive paragraphs should be compared."""
        paragraphs = [f"Paragraph {i} with some common words here." for i in range(5)]
        prose = "\n\n".join(paragraphs)

        det_unlimited = RepetitionDetector(
            embedding_function=_mock_embeddings,
            semantic_similarity_threshold=0.5,
        )
        result_unlimited = det_unlimited.analyze(prose)

        det_window = RepetitionDetector(
            embedding_function=_mock_embeddings,
            semantic_similarity_threshold=0.5,
            adjacency_window=1,
        )
        result_window = det_window.analyze(prose)

        # Window-limited should produce fewer or equal flags
        assert len(result_window["similar_paragraphs"]) <= len(result_unlimited["similar_paragraphs"])
        # All flagged pairs should be adjacent (distance <= 1)
        for pair in result_window["similar_paragraphs"]:
            assert abs(pair["para_b"] - pair["para_a"]) <= 1


class TestDefaultBehavior:
    def test_no_overrides_works(self):
        """RepetitionDetector without overrides should work as before."""
        detector = RepetitionDetector()
        result = detector.analyze("A simple paragraph with some words.")
        assert "repetition_score" in result
        assert result["repetition_score"] == 1.0
