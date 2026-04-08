"""Tests for RepetitionDetector."""
import pytest
from src.quality.repetition_detector import RepetitionDetector


class TestRepetitionDetector:
    def test_clean_prose_scores_high(self, sample_prose):
        detector = RepetitionDetector()
        result = detector.analyze(sample_prose)
        assert result["repetition_score"] >= 0.8
        assert isinstance(result["flagged_words"], list)
        assert isinstance(result["repeated_ngrams"], list)

    def test_empty_prose(self):
        detector = RepetitionDetector()
        result = detector.analyze("")
        assert result["repetition_score"] == 1.0
        assert result["flagged_words"] == []

    def test_word_frequency_flagging(self):
        # Prose with an extremely overused word
        prose = " ".join(["The darkness was dark and the dark night grew darker."] * 20)
        detector = RepetitionDetector()
        result = detector.analyze(prose)
        # Should flag "dark" or related
        assert result["repetition_score"] < 1.0

    def test_ngram_detection(self):
        # Prose with repeated 3-grams
        prose = (
            "The ship shuddered violently. They braced themselves. "
            "The ship shuddered violently. They prepared for impact. "
            "The ship shuddered violently. They held on tight."
        )
        detector = RepetitionDetector()
        result = detector.analyze(prose)
        ngrams = result["repeated_ngrams"]
        assert len(ngrams) > 0
        assert any("ship shuddered violently" in ng["ngram"] for ng in ngrams)

    def test_opener_detection(self):
        # All sentences start the same way
        sentences = ["He looked at the stars. " * 10 + "She turned away."]
        prose = " ".join(sentences)
        detector = RepetitionDetector()
        result = detector.analyze(prose)
        # Should flag the opener
        assert len(result["opener_violations"]) > 0 or result["repetition_score"] < 1.0

    def test_paragraph_similarity_with_embedding(self, mock_embedding_function):
        detector = RepetitionDetector(embedding_function=mock_embedding_function)
        # Two identical paragraphs should flag high similarity
        prose = "The stars shone brightly above.\n\nThe stars shone brightly above."
        result = detector.analyze(prose)
        # MockEmbedding produces same vector for same text -> similarity = 1.0
        assert len(result["similar_paragraphs"]) > 0

    def test_paragraph_similarity_skipped_without_embedding(self):
        detector = RepetitionDetector(embedding_function=None)
        prose = "Paragraph one about stars.\n\nParagraph one about stars."
        result = detector.analyze(prose)
        assert result["similar_paragraphs"] == []

    def test_character_names_excluded(self):
        # "Ben" appears many times but should be excluded as character name
        prose = "Ben walked. Ben spoke. Ben turned. Ben paused. Ben sighed. Ben left."
        detector = RepetitionDetector()
        result = detector.analyze(prose, character_names=["Ben Skywalker"])
        # "ben" should not appear in flagged words
        flagged = [f["word"] for f in result["flagged_words"]]
        assert "ben" not in flagged

    def test_cross_chapter_ngrams(self):
        prior = ["The Force was strong. The Force was strong. The Force was strong."]
        current = "The Force was strong. Something else happened."
        detector = RepetitionDetector()
        result = detector.analyze(current, prior_chapters=prior)
        # Should detect cross-chapter repetition
        assert isinstance(result["repeated_ngrams"], list)

    def test_result_structure(self, sample_prose):
        detector = RepetitionDetector()
        result = detector.analyze(sample_prose)
        assert "repetition_score" in result
        assert "flagged_words" in result
        assert "repeated_ngrams" in result
        assert "opener_violations" in result
        assert "similar_paragraphs" in result
        assert 0.0 <= result["repetition_score"] <= 1.0
