"""ChromaDB-backed chapter summary storage for Tier 3 context.

Stores chapter summaries as embedded vectors for semantic retrieval.
Used by the ContextAssembler to provide recent chapter context.
"""

from pathlib import Path

import chromadb

from src.rag.embedding import MockEmbeddingFunction


class ChapterMemory:
    """Vector-based chapter summary storage using ChromaDB."""

    def __init__(
        self,
        persist_directory: str = "data/chapter_memory",
        embedding_function=None,
        collection_name: str = "chapter_summaries",
    ):
        persist_path = Path(persist_directory)
        persist_path.mkdir(parents=True, exist_ok=True)

        self.client = chromadb.PersistentClient(path=str(persist_path))

        # Use provided embedding function or fall back to mock
        self._ef = embedding_function or MockEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self._ef,
        )

    def add_summary(
        self,
        chapter_number: int,
        summary_text: str,
        metadata: dict | None = None,
    ) -> None:
        """Embed and store a chapter summary."""
        doc_id = f"chapter_{chapter_number:03d}"
        meta = {"chapter_number": chapter_number}
        if metadata:
            meta.update(metadata)

        self.collection.upsert(
            ids=[doc_id],
            documents=[summary_text],
            metadatas=[meta],
        )

    def get_recent_summaries(self, n: int = 3) -> str:
        """Retrieve the last N summaries ordered by chapter number.

        Returns formatted text suitable for context injection.
        """
        # Get all summaries and sort by chapter number
        result = self.collection.get(
            include=["documents", "metadatas"],
        )

        if not result["ids"]:
            return "No previous chapter summaries available."

        # Pair up and sort by chapter number
        entries = []
        for doc_id, doc, meta in zip(
            result["ids"], result["documents"], result["metadatas"]
        ):
            chapter_num = meta.get("chapter_number", 0)
            entries.append((chapter_num, doc))

        entries.sort(key=lambda x: x[0])

        # Take the last N
        recent = entries[-n:]

        lines = []
        for chapter_num, summary in recent:
            lines.append(f"### Chapter {chapter_num}")
            lines.append(summary)
            lines.append("")

        return "\n".join(lines).strip()

    def search_summaries(self, query: str, k: int = 5) -> list[dict]:
        """Semantic search across all chapter summaries."""
        count = self.collection.count()
        if count == 0:
            return []

        # Don't request more results than we have documents
        n_results = min(k, count)

        result = self.collection.query(
            query_texts=[query],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        matches = []
        for i in range(len(result["ids"][0])):
            matches.append(
                {
                    "id": result["ids"][0][i],
                    "summary": result["documents"][0][i],
                    "metadata": result["metadatas"][0][i],
                    "distance": result["distances"][0][i],
                }
            )

        return matches

    def get_summary(self, chapter_number: int) -> str | None:
        """Get the summary for a specific chapter."""
        doc_id = f"chapter_{chapter_number:03d}"
        result = self.collection.get(
            ids=[doc_id],
            include=["documents"],
        )
        if result["ids"]:
            return result["documents"][0]
        return None

    def count(self) -> int:
        """Return the number of stored summaries."""
        return self.collection.count()
