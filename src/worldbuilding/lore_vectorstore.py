"""ChromaDB-backed vector store for worldbuilding lore entries.

One collection per universe (named ``worldbuilding_{universe_id}``).
Follows the same ChromaDB patterns as CanonDB: PersistentClient,
upsert/query/get, MockEmbeddingFunction for tests.
"""

import logging
from pathlib import Path
from typing import Optional

import chromadb

from src.rag.embedding import MockEmbeddingFunction

logger = logging.getLogger(__name__)


class LoreVectorStore:
    """ChromaDB vector store for worldbuilding lore.

    Each universe gets its own collection so searches stay scoped.
    Inheritance chain queries search multiple collections sequentially.
    """

    def __init__(
        self,
        persist_directory: str = "data/worldbuilding_vectors",
        embedding_function: Optional[object] = None,
    ):
        persist_path = Path(persist_directory)
        persist_path.mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=str(persist_path))

        if embedding_function is None:
            embedding_function = MockEmbeddingFunction()

        self._embedding_fn = embedding_function
        self._collections: dict = {}

    def _collection_name(self, universe_id: str) -> str:
        """Sanitized collection name for a universe."""
        # ChromaDB requires 3-63 chars, alphanumeric + underscores/hyphens
        name = f"wb_{universe_id}"
        # Replace any invalid chars
        name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in name)
        return name[:63].ljust(3, "_")

    def _get_collection(self, universe_id: str):
        """Get or create the ChromaDB collection for a universe."""
        if universe_id not in self._collections:
            col_name = self._collection_name(universe_id)
            self._collections[universe_id] = self._client.get_or_create_collection(
                name=col_name,
                embedding_function=self._embedding_fn,
            )
        return self._collections[universe_id]

    def upsert_entry(
        self,
        universe_id: str,
        entry_id: str,
        text: str,
        metadata: dict,
    ) -> None:
        """Upsert a lore entry into the universe's collection."""
        collection = self._get_collection(universe_id)
        # ChromaDB metadata values must be str, int, float, or bool
        clean_meta = {}
        for k, v in metadata.items():
            if v is None:
                clean_meta[k] = ""
            elif isinstance(v, bool):
                clean_meta[k] = v
            elif isinstance(v, (int, float)):
                clean_meta[k] = v
            elif isinstance(v, list):
                clean_meta[k] = ", ".join(str(x) for x in v)
            else:
                clean_meta[k] = str(v)

        collection.upsert(
            ids=[entry_id],
            documents=[text],
            metadatas=[clean_meta],
        )

    def remove_entry(self, universe_id: str, entry_id: str) -> None:
        """Remove a lore entry from the universe's collection."""
        collection = self._get_collection(universe_id)
        try:
            collection.delete(ids=[entry_id])
        except Exception:
            logger.warning("Failed to delete entry %s from ChromaDB", entry_id)

    def search(
        self,
        universe_id: str,
        query: str,
        k: int = 5,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """Semantic search within a single universe's collection."""
        collection = self._get_collection(universe_id)
        if collection.count() == 0:
            return []

        query_params: dict = {
            "query_texts": [query],
            "n_results": min(k, collection.count()),
        }
        if where:
            query_params["where"] = where

        results = collection.query(**query_params)

        output = []
        for i in range(len(results["ids"][0])):
            output.append({
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0.0,
            })
        return output

    def search_chain(
        self,
        universe_ids: list[str],
        query: str,
        k: int = 5,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """Search across an inheritance chain of universes.

        Queries each universe sequentially (child first), deduplicates
        by entry ID (child overrides parent), and returns top-k by distance.
        """
        all_results = []
        seen_ids: set[str] = set()

        for uid in universe_ids:
            results = self.search(uid, query, k=k, where=where)
            for r in results:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    all_results.append(r)

        # Sort by distance (lower = more similar) and take top-k
        all_results.sort(key=lambda x: x.get("distance", float("inf")))
        return all_results[:k]

    def get_all_entry_ids(self, universe_id: str) -> set[str]:
        """Get all entry IDs in a universe's collection (for reconciliation)."""
        collection = self._get_collection(universe_id)
        if collection.count() == 0:
            return set()
        results = collection.get()
        return set(results["ids"])

    def delete_collection(self, universe_id: str) -> None:
        """Delete an entire universe's collection."""
        col_name = self._collection_name(universe_id)
        try:
            self._client.delete_collection(name=col_name)
        except Exception:
            logger.warning("Failed to delete collection %s", col_name)
        self._collections.pop(universe_id, None)

    def close(self) -> None:
        """Release ChromaDB client resources."""
        self._collections.clear()
        self._client = None
