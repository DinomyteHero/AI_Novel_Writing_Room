"""Canon Evidence Ranker for two-stage canon validation.

Retrieves candidate chunks via hybrid search, then produces ranked
evidence with confidence scores weighted by source authority. Output
conforms to schemas/canon_evidence.json.
"""

from src.rag.hybrid_search import HybridSearch

SOURCE_AUTHORITY: dict[str, float] = {
    "primary_canon": 1.0,
    "secondary_canon": 0.85,
    "reference_book": 0.7,
    "fan_maintained": 0.4,
    "ambiguous": 0.3,
}


class CanonEvidenceRanker:
    """Two-stage canon evidence retrieval and ranking.

    Stage 1: Retrieve candidate chunks via hybrid search (semantic + BM25).
    Stage 2: Rank candidates by confidence = combined_score * source_authority.

    Output conforms to the canon_evidence.json schema for downstream
    consumption by the Canon Expert agent.
    """

    def __init__(self, hybrid_search: HybridSearch):
        self.search = hybrid_search

    def get_evidence(
        self,
        claim: str,
        k: int = 5,
        confidence_threshold: float = 0.5,
    ) -> list[dict]:
        """Retrieve and rank canon evidence for a given claim.

        Args:
            claim: The canon claim or element to verify.
            k: Maximum number of evidence items to return.
            confidence_threshold: Minimum confidence to include.

        Returns:
            List of evidence dicts conforming to canon_evidence.json:
                - claim: The original claim text.
                - source_article: Article the evidence came from.
                - source_section: Section within the article.
                - source_class: Source authority classification.
                - confidence: Weighted confidence score (0-1).
                - continuity_tag: Canon/legends/both/disputed.
                - divergence_safe: Whether divergence is safe for AU.
        """
        # Stage 1: Hybrid search for candidates
        # Retrieve more than k to allow for filtering
        candidates = self.search.search(claim, k=k * 3)

        # Stage 2: Score and rank by source-weighted confidence
        evidence = []
        for candidate in candidates:
            metadata = candidate.get("metadata", {})
            source_class = metadata.get("source_class", "ambiguous")
            authority = SOURCE_AUTHORITY.get(source_class, SOURCE_AUTHORITY["ambiguous"])
            combined_score = candidate.get("combined_score", 0.0)

            # Confidence = retrieval relevance * source authority
            # Normalize combined_score to approximate [0, 1] range
            # RRF scores are typically small (e.g., 0.01-0.03), so scale them
            # For a single list contribution: 1/(60+1) = ~0.016
            # For two lists at rank 1: 2 * 1/61 = ~0.033
            # Scale so max plausible RRF score maps to ~1.0
            max_rrf = 2.0 / 61.0  # Best possible: rank 1 in both lists
            normalized_score = min(combined_score / max_rrf, 1.0) if max_rrf > 0 else 0.0

            confidence = normalized_score * authority
            confidence = min(confidence, 1.0)

            if confidence < confidence_threshold:
                continue

            continuity_status = metadata.get("continuity_status", "canon")
            continuity_tag = self._map_continuity_tag(continuity_status)

            evidence.append({
                "claim": claim,
                "source_article": metadata.get("source_article", "Unknown"),
                "source_section": metadata.get("source_section", ""),
                "source_class": source_class,
                "confidence": round(confidence, 4),
                "continuity_tag": continuity_tag,
                "divergence_safe": self._is_divergence_safe(source_class, continuity_tag),
            })

        # Sort by confidence descending, return top-k
        evidence.sort(key=lambda e: e["confidence"], reverse=True)
        return evidence[:k]

    def format_evidence_for_context(self, evidence: list[dict]) -> str:
        """Format evidence list into a readable context string.

        Produces a summary suitable for injection into an LLM prompt,
        with source classification and confidence annotations.

        Args:
            evidence: List of evidence dicts from get_evidence().

        Returns:
            Formatted string with one line per evidence item, or a
            fallback message if no evidence is available.
        """
        if not evidence:
            return "No high-confidence canon matches found."

        lines = []
        for item in evidence:
            source_class = item.get("source_class", "unknown")
            continuity = item.get("continuity_tag", "unknown")
            confidence = item.get("confidence", 0.0)
            claim = item.get("claim", "")
            article = item.get("source_article", "")
            section = item.get("source_section", "")

            location = article
            if section:
                location = f"{article} > {section}"

            line = (
                f"[{source_class}/{continuity} conf={confidence:.2f}] "
                f"{claim} (from: {location})"
            )
            lines.append(line)

        return "\n".join(lines)

    def _map_continuity_tag(self, continuity_status: str) -> str:
        """Map raw continuity status to schema-valid tag.

        Args:
            continuity_status: Raw status from chunk metadata.

        Returns:
            One of: canon, legends, both, disputed.
        """
        mapping = {
            "canon": "canon",
            "legends": "legends",
            "both": "both",
            "disputed": "disputed",
            "eu": "legends",
            "expanded_universe": "legends",
        }
        return mapping.get(continuity_status.lower(), "canon")

    def _is_divergence_safe(self, source_class: str, continuity_tag: str) -> bool:
        """Determine if diverging from this evidence is safe for AU stories.

        Lower-authority sources and non-canon continuity are safer to
        diverge from in alternate universe stories.

        Args:
            source_class: The source authority class.
            continuity_tag: The continuity classification.

        Returns:
            True if divergence is relatively safe.
        """
        # Safe to diverge from non-primary sources
        if source_class in ("fan_maintained", "ambiguous"):
            return True

        # Safe to diverge from legends/disputed material
        if continuity_tag in ("legends", "disputed"):
            return True

        # Reference books are generally safe for AU
        if source_class == "reference_book":
            return True

        return False
