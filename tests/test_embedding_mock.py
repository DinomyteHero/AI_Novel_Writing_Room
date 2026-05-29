"""Regression: the mock embedding must never emit NaN/Infinity.

Raw SHA-256 bytes reinterpreted as float32 can form NaN/Inf bit patterns, which
newer ChromaDB rejects ("Embeddings must not contain NaN or Infinity values").
The `norm == 0` guard does not catch NaN (NaN == 0 is False).
"""

import math

from src.rag.embedding import MockEmbeddingFunction


def test_mock_embedding_is_always_finite():
    m = MockEmbeddingFunction()
    # ~3% of inputs hit a NaN/Inf bit pattern before the fix; 3000 reliably
    # covers several.
    texts = [f"scene summary {i}" for i in range(3000)] + ["", " ", "\n", "x" * 2000]
    for text, vec in zip(texts, m(texts)):
        assert len(vec) == m.dimension
        assert all(math.isfinite(x) for x in vec), f"non-finite vector for {text!r}"


def test_mock_embedding_is_deterministic():
    m = MockEmbeddingFunction()
    assert m(["the wrongness has a direction"]) == m(["the wrongness has a direction"])
