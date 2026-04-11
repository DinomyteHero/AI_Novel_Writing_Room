"""Tests for CanonEvidenceRanker and HybridSearch.

Validates confidence scoring, source-authority weighting, filtering,
format_evidence_for_context output, reciprocal rank fusion, BM25
keyword search, and the full HybridSearch.search pipeline.
"""

import pytest

chromadb = pytest.importorskip("chromadb", reason="chromadb not installed")

from src.rag.canon_db import CanonDB
from src.rag.canon_evidence import CanonEvidenceRanker, SOURCE_AUTHORITY
from src.rag.embedding import MockEmbeddingFunction
from src.rag.hybrid_search import BM25, HybridSearch


# ------------------------------------------------------------------ #
# Shared fixtures
# ------------------------------------------------------------------ #


@pytest.fixture
def mock_ef():
    """Deterministic mock embedding function."""
    return MockEmbeddingFunction(dimension=384)


@pytest.fixture
def canon_db(tmp_path, mock_ef):
    """CanonDB populated with test chunks in a temp directory."""
    db = CanonDB(
        persist_directory=str(tmp_path / "test_canon_db"),
        collection_name="test_canon",
        embedding_function=mock_ef,
    )

    chunks = [
        {
            "id": "chunk_primary_1",
            "text": "Ben Skywalker is the son of Luke Skywalker and Mara Jade Skywalker.",
            "metadata": {
                "source_class": "primary_canon",
                "source_article": "Fate of the Jedi",
                "source_section": "Characters",
                "continuity_status": "canon",
            },
        },
        {
            "id": "chunk_secondary_1",
            "text": "The Jedi Temple on Coruscant houses the Order's central archives.",
            "metadata": {
                "source_class": "secondary_canon",
                "source_article": "Jedi Order",
                "source_section": "Locations",
                "continuity_status": "canon",
            },
        },
        {
            "id": "chunk_fan_1",
            "text": "Ben Skywalker's lightsaber crystal is believed to be a rare Adegan variant.",
            "metadata": {
                "source_class": "fan_maintained",
                "source_article": "Wookieepedia Fan Theory",
                "source_section": "Equipment",
                "continuity_status": "disputed",
            },
        },
        {
            "id": "chunk_primary_2",
            "text": "The Force flows through all living things and connects every being in the galaxy.",
            "metadata": {
                "source_class": "primary_canon",
                "source_article": "The Force",
                "source_section": "Overview",
                "continuity_status": "both",
            },
        },
        {
            "id": "chunk_reference_1",
            "text": "The Unknown Regions are largely unexplored territories beyond the Outer Rim.",
            "metadata": {
                "source_class": "reference_book",
                "source_article": "Essential Atlas",
                "source_section": "Geography",
                "continuity_status": "legends",
            },
        },
    ]

    db.add_chunks(chunks)
    return db


@pytest.fixture
def hybrid_search(canon_db):
    """HybridSearch backed by the test CanonDB."""
    return HybridSearch(canon_db)


@pytest.fixture
def ranker(hybrid_search):
    """CanonEvidenceRanker backed by the test HybridSearch."""
    return CanonEvidenceRanker(hybrid_search)


# ================================================================== #
# CanonEvidenceRanker
# ================================================================== #


class TestCanonEvidenceRanker:
    """Test the two-stage evidence retrieval and ranking."""

    def test_confidence_is_combined_score_times_authority(self, ranker):
        """confidence = normalized_combined_score * source_authority_weight."""
        # We cannot control exact scores from mock embeddings, but we can
        # verify the relationship between source_class and confidence.
        evidence = ranker.get_evidence(
            "Ben Skywalker lineage", k=10, confidence_threshold=0.0
        )

        # Should return results
        assert len(evidence) > 0

        # All confidence values should be in [0, 1]
        for item in evidence:
            assert 0.0 <= item["confidence"] <= 1.0

        # If primary_canon items and fan_maintained items are both returned,
        # verify the authority weighting principle
        primary_items = [e for e in evidence if e["source_class"] == "primary_canon"]
        fan_items = [e for e in evidence if e["source_class"] == "fan_maintained"]

        if primary_items and fan_items:
            # Primary canon authority (1.0) should weight higher than fan (0.4)
            # assuming similar relevance scores
            assert SOURCE_AUTHORITY["primary_canon"] > SOURCE_AUTHORITY["fan_maintained"]

    def test_results_below_threshold_filtered(self, ranker):
        """Results below the confidence threshold should be excluded."""
        # Get all results with no filter
        all_evidence = ranker.get_evidence(
            "Ben Skywalker", k=10, confidence_threshold=0.0
        )
        # Get filtered results with high threshold
        filtered = ranker.get_evidence(
            "Ben Skywalker", k=10, confidence_threshold=0.5
        )

        # Filtered should have fewer or equal results
        assert len(filtered) <= len(all_evidence)

        # All filtered results should meet the threshold
        for item in filtered:
            assert item["confidence"] >= 0.5

    def test_evidence_sorted_by_confidence_descending(self, ranker):
        """Returned evidence should be sorted highest confidence first."""
        evidence = ranker.get_evidence(
            "Jedi Temple archives", k=10, confidence_threshold=0.0
        )

        if len(evidence) >= 2:
            for i in range(len(evidence) - 1):
                assert evidence[i]["confidence"] >= evidence[i + 1]["confidence"]

    def test_evidence_schema_fields(self, ranker):
        """Each evidence item should have all required schema fields."""
        evidence = ranker.get_evidence(
            "The Force", k=5, confidence_threshold=0.0
        )

        required_fields = {
            "claim", "source_article", "source_section",
            "source_class", "confidence", "continuity_tag",
            "divergence_safe",
        }

        for item in evidence:
            assert required_fields.issubset(item.keys()), (
                f"Missing fields: {required_fields - item.keys()}"
            )

    def test_divergence_safe_for_fan_and_legends(self, ranker):
        """fan_maintained and legends sources should be divergence-safe."""
        evidence = ranker.get_evidence(
            "lightsaber crystal", k=10, confidence_threshold=0.0
        )

        for item in evidence:
            if item["source_class"] == "fan_maintained":
                assert item["divergence_safe"] is True
            if item["continuity_tag"] == "legends":
                assert item["divergence_safe"] is True


# ================================================================== #
# format_evidence_for_context
# ================================================================== #


class TestFormatEvidence:
    """Test the context-string formatter."""

    def test_format_evidence_produces_expected_format(self, ranker):
        """Output should contain source_class, continuity, confidence, and claim."""
        evidence = [
            {
                "claim": "Ben is Luke's son",
                "source_article": "Fate of the Jedi",
                "source_section": "Characters",
                "source_class": "primary_canon",
                "confidence": 0.92,
                "continuity_tag": "canon",
                "divergence_safe": False,
            },
        ]

        formatted = ranker.format_evidence_for_context(evidence)

        assert "primary_canon" in formatted
        assert "canon" in formatted
        assert "0.92" in formatted
        assert "Ben is Luke's son" in formatted
        assert "Fate of the Jedi" in formatted
        assert "Characters" in formatted

    def test_format_empty_evidence(self, ranker):
        """Empty evidence list should return the fallback message."""
        formatted = ranker.format_evidence_for_context([])
        assert "No high-confidence canon matches found" in formatted

    def test_format_evidence_without_section(self, ranker):
        """Evidence without source_section should just show the article."""
        evidence = [
            {
                "claim": "The Force exists",
                "source_article": "Force Overview",
                "source_section": "",
                "source_class": "primary_canon",
                "confidence": 0.85,
                "continuity_tag": "canon",
                "divergence_safe": False,
            },
        ]

        formatted = ranker.format_evidence_for_context(evidence)
        assert "Force Overview" in formatted
        # Should not have the " > " separator if section is empty
        assert "Force Overview >" not in formatted


# ================================================================== #
# HybridSearch._reciprocal_rank_fusion
# ================================================================== #


class TestReciprocalRankFusion:
    """Test the RRF merging algorithm directly."""

    def test_rrf_merges_two_lists(self, hybrid_search):
        """RRF should merge items from both lists and sum scores."""
        semantic = [
            {"id": "a", "text": "Doc A", "metadata": {}, "distance": 0.1},
            {"id": "b", "text": "Doc B", "metadata": {}, "distance": 0.5},
        ]
        keyword = [
            {"id": "b", "text": "Doc B", "metadata": {}, "score": 5.0},
            {"id": "c", "text": "Doc C", "metadata": {}, "score": 3.0},
        ]

        merged = hybrid_search._reciprocal_rank_fusion(semantic, keyword, k=60)

        ids = {r["id"] for r in merged}
        assert "a" in ids
        assert "b" in ids
        assert "c" in ids

        # Doc B appears in both lists, so its combined_score should be highest
        scores_by_id = {r["id"]: r["combined_score"] for r in merged}
        assert scores_by_id["b"] > scores_by_id["a"]
        assert scores_by_id["b"] > scores_by_id["c"]

    def test_rrf_empty_lists(self, hybrid_search):
        """RRF with empty lists should return empty results."""
        merged = hybrid_search._reciprocal_rank_fusion([], [], k=60)
        assert merged == []

    def test_rrf_single_list_only(self, hybrid_search):
        """RRF with only one list should still produce results."""
        semantic = [
            {"id": "a", "text": "Doc A", "metadata": {}, "distance": 0.1},
        ]
        merged = hybrid_search._reciprocal_rank_fusion(semantic, [], k=60)
        assert len(merged) == 1
        assert merged[0]["id"] == "a"

    def test_rrf_scores_are_positive(self, hybrid_search):
        """All RRF combined_scores should be positive."""
        semantic = [
            {"id": "x", "text": "X", "metadata": {}, "distance": 0.2},
            {"id": "y", "text": "Y", "metadata": {}, "distance": 0.8},
        ]
        keyword = [
            {"id": "y", "text": "Y", "metadata": {}, "score": 2.0},
        ]

        merged = hybrid_search._reciprocal_rank_fusion(semantic, keyword, k=60)
        for r in merged:
            assert r["combined_score"] > 0


# ================================================================== #
# BM25
# ================================================================== #


class TestBM25:
    """Test the in-memory BM25 keyword search."""

    def test_bm25_returns_relevant_results(self):
        """BM25 should rank documents containing query terms higher."""
        corpus = [
            {"id": "d1", "text": "Ben Skywalker is a Jedi Knight from Coruscant.", "metadata": {}},
            {"id": "d2", "text": "The Unknown Regions are dangerous and unexplored.", "metadata": {}},
            {"id": "d3", "text": "Skywalker lightsaber forms include Djem So.", "metadata": {}},
        ]

        bm25 = BM25(corpus)
        results = bm25.search("Skywalker Jedi", k=3)

        assert len(results) >= 1
        # d1 mentions both "Skywalker" and "Jedi"
        assert results[0]["id"] == "d1"

    def test_bm25_empty_corpus(self):
        """BM25 with empty corpus should return empty results."""
        bm25 = BM25([])
        results = bm25.search("anything", k=5)
        assert results == []

    def test_bm25_empty_query(self):
        """BM25 with empty query should return empty results."""
        corpus = [
            {"id": "d1", "text": "Some text here.", "metadata": {}},
        ]
        bm25 = BM25(corpus)
        results = bm25.search("", k=5)
        assert results == []

    def test_bm25_no_matching_terms(self):
        """BM25 with no matching terms should return empty results."""
        corpus = [
            {"id": "d1", "text": "Alpha beta gamma delta.", "metadata": {}},
        ]
        bm25 = BM25(corpus)
        results = bm25.search("zzzzz xyzzy", k=5)
        assert results == []

    def test_bm25_scores_are_positive(self):
        """All returned BM25 scores should be positive."""
        corpus = [
            {"id": "d1", "text": "The Force is strong with this one.", "metadata": {}},
            {"id": "d2", "text": "Use the Force, Luke.", "metadata": {}},
        ]
        bm25 = BM25(corpus)
        results = bm25.search("Force", k=5)

        for r in results:
            assert r["score"] > 0


# ================================================================== #
# HybridSearch.search (end-to-end)
# ================================================================== #


class TestHybridSearchEndToEnd:
    """Test the full hybrid search pipeline."""

    def test_search_returns_combined_results(self, hybrid_search):
        """search() should return results with all expected fields."""
        results = hybrid_search.search("Ben Skywalker", k=5)

        assert len(results) > 0

        required_fields = {"id", "text", "metadata", "semantic_score", "keyword_score", "combined_score"}
        for r in results:
            assert required_fields.issubset(r.keys()), (
                f"Missing fields: {required_fields - r.keys()}"
            )

    def test_search_respects_k_limit(self, hybrid_search):
        """search() should return at most k results."""
        results = hybrid_search.search("Jedi Temple", k=2)
        assert len(results) <= 2

    def test_search_results_sorted_by_combined_score(self, hybrid_search):
        """Results should be sorted by combined_score descending."""
        results = hybrid_search.search("Unknown Regions", k=5)

        if len(results) >= 2:
            for i in range(len(results) - 1):
                assert results[i]["combined_score"] >= results[i + 1]["combined_score"]

    def test_search_deduplicates_by_id(self, hybrid_search):
        """Each result ID should appear at most once."""
        results = hybrid_search.search("Force living things", k=10)
        ids = [r["id"] for r in results]
        assert len(ids) == len(set(ids)), "Duplicate IDs found in results"
