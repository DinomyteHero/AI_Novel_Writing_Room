"""ChromaDB-backed vector database for franchise canon knowledge.

Stores and retrieves canon chunks with metadata for source authority,
continuity status, and entity classification. Supports semantic search
with optional metadata filtering.
"""

from pathlib import Path
from typing import Optional

import chromadb

from src.rag.embedding import MockEmbeddingFunction


class CanonDB:
    """ChromaDB-backed vector store for franchise canon knowledge.

    Each document chunk carries metadata describing its source authority,
    continuity status, and entity type, enabling filtered retrieval for
    canon validation tasks.
    """

    def __init__(
        self,
        persist_directory: str = "output/_fallback/canon_dbs",
        collection_name: str = "canon",
        embedding_function: Optional[object] = None,
    ):
        persist_path = Path(persist_directory)
        persist_path.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=str(persist_path))

        if embedding_function is None:
            embedding_function = MockEmbeddingFunction()

        self._embedding_fn = embedding_function
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=self._embedding_fn,
        )

    def add_chunks(self, chunks: list[dict]) -> None:
        """Batch upsert document chunks with metadata.

        Args:
            chunks: List of dicts, each containing:
                - id (str): Unique chunk identifier.
                - text (str): The chunk text content.
                - metadata (dict): Keys include source_article, source_section,
                  entity_type, canon_era, continuity_status, source_class.
        """
        if not chunks:
            return

        ids = [chunk["id"] for chunk in chunks]
        documents = [chunk["text"] for chunk in chunks]
        metadatas = [chunk.get("metadata", {}) for chunk in chunks]

        # ChromaDB handles batching internally; upsert to allow re-ingestion
        self._collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
        )

    def search(
        self,
        query: str,
        k: int = 5,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """Semantic search with optional metadata filtering.

        Args:
            query: The search query text.
            k: Number of results to return.
            where: Optional ChromaDB metadata filter dict.

        Returns:
            List of dicts with keys: id, text, metadata, distance.
        """
        if self._collection.count() == 0:
            return []

        query_params: dict = {
            "query_texts": [query],
            "n_results": min(k, self._collection.count()),
        }
        if where:
            query_params["where"] = where

        results = self._collection.query(**query_params)

        output = []
        for i in range(len(results["ids"][0])):
            output.append({
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0.0,
            })

        return output

    def get_chunk_count(self) -> int:
        """Return the total number of chunks in the collection."""
        return self._collection.count()

    def get_all_chunks(self) -> list[dict]:
        """Retrieve all chunks from the collection.

        Used by the BM25 index builder in HybridSearch.

        Returns:
            List of dicts with keys: id, text, metadata.
        """
        if self._collection.count() == 0:
            return []

        results = self._collection.get()
        output = []
        for i in range(len(results["ids"])):
            output.append({
                "id": results["ids"][i],
                "text": results["documents"][i],
                "metadata": results["metadatas"][i] if results["metadatas"] else {},
            })
        return output

    def close(self) -> None:
        """Release ChromaDB client resources."""
        # PersistentClient doesn't expose a close() method, but we can
        # delete our reference so the GC can reclaim file handles.
        self._collection = None
        self._client = None
