"""Embedding model wrapper for ChromaDB integration.

Provides a unified interface for embedding text using sentence-transformers
or other backends. Includes a mock implementation for testing.
"""

import hashlib
import struct
from typing import Protocol


class EmbeddingFunction(Protocol):
    """Protocol for ChromaDB-compatible embedding functions."""

    def __call__(self, input: list[str]) -> list[list[float]]:
        ...


class SentenceTransformerEmbedding:
    """Embedding function using sentence-transformers."""

    def __init__(self, model_name: str = "nomic-ai/nomic-embed-text-v1.5"):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_name, trust_remote_code=True)
        self.dimension = self.model.get_sentence_embedding_dimension()
        self._model_name = model_name

    def name(self) -> str:
        return self._model_name

    def __call__(self, input: list[str]) -> list[list[float]]:
        embeddings = self.model.encode(input, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_query(self, input: list[str]) -> list[list[float]]:
        return self(input)


class MockEmbeddingFunction:
    """Deterministic mock embedding for testing. Returns consistent
    fixed-dimension vectors based on input text hash.

    Implements the ChromaDB 1.5+ EmbeddingFunction interface where both
    __call__ and embed_query take list[str] and return list[vector].
    """

    def __init__(self, dimension: int = 384):
        self.dimension = dimension

    def name(self) -> str:
        return "mock_embedding"

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._hash_to_vector(text) for text in input]

    def embed_query(self, input: list[str]) -> list[list[float]]:
        """ChromaDB 1.5+ calls embed_query with a list of strings."""
        return self(input)

    def embed_documents(self, input: list[str]) -> list[list[float]]:
        return self(input)

    def _hash_to_vector(self, text: str) -> list[float]:
        """Generate a deterministic vector from text via SHA-256 hash."""
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # Repeat hash bytes to fill the dimension
        repeated = h * ((self.dimension * 4 // len(h)) + 1)
        floats = struct.unpack(f"<{self.dimension}f", repeated[: self.dimension * 4])
        # Normalize to unit vector
        norm = sum(x * x for x in floats) ** 0.5
        if norm == 0:
            return [0.0] * self.dimension
        return [x / norm for x in floats]


def get_embedding_function(
    model_name: str = "nomic-ai/nomic-embed-text-v1.5",
    use_mock: bool = False,
    dimension: int = 384,
) -> EmbeddingFunction:
    """Get a ChromaDB-compatible embedding function.

    Args:
        model_name: Model name for sentence-transformers.
        use_mock: If True, return a deterministic mock (for testing).
        dimension: Vector dimension for mock embedding.
    """
    if use_mock:
        return MockEmbeddingFunction(dimension=dimension)
    return SentenceTransformerEmbedding(model_name=model_name)
