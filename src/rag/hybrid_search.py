"""Hybrid search combining semantic (ChromaDB) and BM25 keyword search.

Retrieves canon knowledge using reciprocal rank fusion to merge results
from both vector similarity and term-frequency matching, providing
robust retrieval even when queries use different terminology than the
stored canon text.
"""

import math
import re
from collections import Counter
from typing import Optional

from src.rag.canon_db import CanonDB


def _tokenize(text: str) -> list[str]:
    """Lowercase tokenization with basic punctuation stripping."""
    return re.findall(r"[a-z0-9]+", text.lower())


class BM25:
    """Simple in-memory BM25 implementation for keyword search.

    Operates on a static corpus of document chunks. Suitable for
    the relatively small corpus sizes typical of franchise canon DBs
    (thousands to tens of thousands of chunks).
    """

    def __init__(self, corpus: list[dict], k1: float = 1.5, b: float = 0.75):
        """Build BM25 index from a corpus of document chunks.

        Args:
            corpus: List of dicts with keys: id, text, metadata.
            k1: Term frequency saturation parameter.
            b: Document length normalization parameter.
        """
        self.k1 = k1
        self.b = b
        self.corpus = corpus
        self.n_docs = len(corpus)

        # Tokenize all documents
        self._doc_tokens: list[list[str]] = []
        self._doc_lengths: list[int] = []
        self._tf: list[Counter] = []

        for doc in corpus:
            tokens = _tokenize(doc["text"])
            self._doc_tokens.append(tokens)
            self._doc_lengths.append(len(tokens))
            self._tf.append(Counter(tokens))

        # Average document length
        self._avg_dl = (
            sum(self._doc_lengths) / self.n_docs if self.n_docs > 0 else 0.0
        )

        # Document frequency: number of docs containing each term
        self._df: Counter = Counter()
        for tf in self._tf:
            for term in tf:
                self._df[term] += 1

    def search(self, query: str, k: int = 10) -> list[dict]:
        """Return top-k documents ranked by BM25 score.

        Args:
            query: Search query string.
            k: Number of results to return.

        Returns:
            List of dicts with keys: id, text, metadata, score.
        """
        if self.n_docs == 0:
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scores: list[float] = []

        for i in range(self.n_docs):
            score = 0.0
            dl = self._doc_lengths[i]

            for term in query_tokens:
                if term not in self._tf[i]:
                    continue

                tf = self._tf[i][term]
                df = self._df[term]

                # IDF component: log((N - df + 0.5) / (df + 0.5) + 1)
                idf = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)

                # TF component with length normalization
                tf_norm = (tf * (self.k1 + 1.0)) / (
                    tf + self.k1 * (1.0 - self.b + self.b * dl / self._avg_dl)
                )

                score += idf * tf_norm

            scores.append(score)

        # Get top-k indices by score
        ranked = sorted(range(self.n_docs), key=lambda i: scores[i], reverse=True)
        top_k = ranked[:k]

        results = []
        for idx in top_k:
            if scores[idx] <= 0.0:
                break
            results.append({
                "id": self.corpus[idx]["id"],
                "text": self.corpus[idx]["text"],
                "metadata": self.corpus[idx]["metadata"],
                "score": scores[idx],
            })

        return results


class HybridSearch:
    """Combines ChromaDB semantic search with BM25 keyword search.

    Uses reciprocal rank fusion (RRF) to merge rankings from both
    retrieval methods, producing robust results that capture both
    semantic meaning and exact keyword matches.
    """

    def __init__(self, canon_db: CanonDB):
        self.canon_db = canon_db
        self._bm25_index: Optional[BM25] = None
        self._bm25_doc_count: int = 0

    def search(self, query: str, k: int = 10) -> list[dict]:
        """Hybrid search combining semantic and keyword retrieval.

        Args:
            query: Search query string.
            k: Number of results to return.

        Returns:
            List of dicts with keys: id, text, metadata,
            semantic_score, keyword_score, combined_score.
        """
        candidate_k = k * 2

        # Stage 1: Semantic search via ChromaDB
        semantic_results = self.canon_db.search(query, k=candidate_k)

        # Stage 2: BM25 keyword search
        bm25 = self._get_bm25_index()
        keyword_results = bm25.search(query, k=candidate_k) if bm25.n_docs > 0 else []

        # Stage 3: Reciprocal rank fusion
        merged = self._reciprocal_rank_fusion(
            semantic_results, keyword_results, k=60,
        )

        # Stage 4: Deduplicate by chunk ID and keep highest score
        seen: dict[str, dict] = {}
        for result in merged:
            rid = result["id"]
            if rid not in seen or result["combined_score"] > seen[rid]["combined_score"]:
                seen[rid] = result

        # Stage 5: Sort and return top-k
        deduped = sorted(
            seen.values(), key=lambda r: r["combined_score"], reverse=True,
        )
        return deduped[:k]

    def _get_bm25_index(self) -> BM25:
        """Lazy-build the BM25 index, rebuilding if canon DB has changed."""
        current_count = self.canon_db.get_chunk_count()

        if self._bm25_index is None or current_count != self._bm25_doc_count:
            all_chunks = self.canon_db.get_all_chunks()
            self._bm25_index = BM25(all_chunks)
            self._bm25_doc_count = current_count

        return self._bm25_index

    def _reciprocal_rank_fusion(
        self,
        semantic_results: list[dict],
        keyword_results: list[dict],
        k: int = 60,
    ) -> list[dict]:
        """Merge result lists using reciprocal rank fusion.

        RRF score for each document = sum(1 / (k + rank)) across all
        lists in which the document appears. Rank is 1-based.

        Also normalizes and tracks per-retriever scores for transparency.

        Args:
            semantic_results: Results from ChromaDB semantic search.
            keyword_results: Results from BM25 keyword search.
            k: RRF constant (default 60).

        Returns:
            Merged results sorted by RRF score descending.
        """
        # Build lookup by ID for metadata and text
        doc_map: dict[str, dict] = {}
        semantic_scores: dict[str, float] = {}
        keyword_scores: dict[str, float] = {}
        rrf_scores: dict[str, float] = {}

        # Process semantic results
        # Normalize semantic scores: ChromaDB returns distances (lower = better)
        # Convert to similarity scores in [0, 1]
        if semantic_results:
            max_dist = max(r.get("distance", 0.0) for r in semantic_results) or 1.0
            for rank, result in enumerate(semantic_results, start=1):
                rid = result["id"]
                doc_map[rid] = {
                    "id": rid,
                    "text": result["text"],
                    "metadata": result["metadata"],
                }
                # Convert distance to similarity (1.0 = identical, 0.0 = most distant)
                distance = result.get("distance", 0.0)
                semantic_scores[rid] = max(0.0, 1.0 - (distance / max_dist)) if max_dist > 0 else 1.0
                rrf_scores[rid] = rrf_scores.get(rid, 0.0) + 1.0 / (k + rank)

        # Process keyword results
        # Normalize BM25 scores to [0, 1]
        if keyword_results:
            max_bm25 = max(r.get("score", 0.0) for r in keyword_results) or 1.0
            for rank, result in enumerate(keyword_results, start=1):
                rid = result["id"]
                if rid not in doc_map:
                    doc_map[rid] = {
                        "id": rid,
                        "text": result["text"],
                        "metadata": result["metadata"],
                    }
                keyword_scores[rid] = result.get("score", 0.0) / max_bm25 if max_bm25 > 0 else 0.0
                rrf_scores[rid] = rrf_scores.get(rid, 0.0) + 1.0 / (k + rank)

        # Build final result list
        results = []
        for rid, rrf_score in rrf_scores.items():
            doc = doc_map[rid]
            results.append({
                "id": doc["id"],
                "text": doc["text"],
                "metadata": doc["metadata"],
                "semantic_score": semantic_scores.get(rid, 0.0),
                "keyword_score": keyword_scores.get(rid, 0.0),
                "combined_score": rrf_score,
            })

        results.sort(key=lambda r: r["combined_score"], reverse=True)
        return results
