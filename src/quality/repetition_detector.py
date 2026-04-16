"""Detect repetitive patterns at multiple levels in prose."""

import re
from collections import Counter
from statistics import mean, stdev

import numpy as np

from src.quality._para_util import paragraph_indices_for_word


# Common English stop words to exclude from frequency analysis
STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "was", "are", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "need", "must",
    "that", "this", "these", "those", "it", "its", "i", "me", "my", "we",
    "us", "our", "you", "your", "he", "him", "his", "she", "her", "they",
    "them", "their", "what", "which", "who", "whom", "when", "where",
    "how", "not", "no", "nor", "if", "then", "than", "so", "as", "up",
    "out", "about", "into", "through", "during", "before", "after",
    "above", "below", "between", "under", "again", "further", "once",
    "here", "there", "all", "each", "every", "both", "few", "more",
    "most", "other", "some", "such", "only", "own", "same", "also",
    "just", "over", "very", "too", "quite", "still", "even", "back",
    "now", "then", "down", "off", "said", "like",
})

_WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a, dtype=np.float32)
    b_arr = np.array(b, dtype=np.float32)
    dot = np.dot(a_arr, b_arr)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


class RepetitionDetector:
    """Detect repetitive patterns at word, n-gram, opener, and semantic levels."""

    def __init__(
        self,
        embedding_function=None,
        stop_words: set[str] | None = None,
        word_frequency_allowlist: list[str] | None = None,
        semantic_similarity_threshold: float = 0.85,
        adjacency_window: int | None = None,
    ):
        self.embedding_function = embedding_function
        self.stop_words = stop_words if stop_words is not None else STOP_WORDS
        # Case-insensitive allowlist of words that should not be flagged as overused
        self.word_frequency_allowlist: set[str] = set()
        if word_frequency_allowlist:
            self.word_frequency_allowlist = {w.lower() for w in word_frequency_allowlist}
        self.semantic_similarity_threshold = semantic_similarity_threshold
        # If set, only flag paragraph pairs within N paragraphs of each other
        self.adjacency_window = adjacency_window

    def analyze(
        self,
        prose: str,
        character_names: list[str] | None = None,
        prior_chapters: list[str] | None = None,
    ) -> dict:
        """Run all repetition analyses.

        Returns:
            {
                "repetition_score": float,  # 0.0 (severe) to 1.0 (clean)
                "flagged_words": [...],
                "repeated_ngrams": [...],
                "opener_violations": [...],
                "similar_paragraphs": [...],
            }
        """
        if not prose or not prose.strip():
            return {
                "repetition_score": 1.0,
                "flagged_words": [],
                "repeated_ngrams": [],
                "opener_violations": [],
                "similar_paragraphs": [],
            }

        # Build exclusion set from character names
        name_words = set()
        if character_names:
            for name in character_names:
                for w in name.lower().split():
                    name_words.add(w)

        tokens = _WORD_RE.findall(prose.lower())
        paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]

        flagged_words = self._check_word_frequency(tokens, name_words)
        # Annotate flagged words with the paragraph indices they appear in
        # so Quality Polish can target specific paragraphs instead of
        # re-reading the whole scene to find them.
        for flag in flagged_words:
            flag["paragraph_indices"] = paragraph_indices_for_word(prose, flag["word"])
        repeated_ngrams = self._check_ngrams(prose, prior_chapters)
        opener_violations = self._check_openers(paragraphs)
        similar_paragraphs = self._check_paragraph_similarity(paragraphs)

        score = self._compute_score(
            flagged_words, repeated_ngrams, opener_violations, similar_paragraphs
        )

        return {
            "repetition_score": score,
            "flagged_words": flagged_words,
            "repeated_ngrams": repeated_ngrams,
            "opener_violations": opener_violations,
            "similar_paragraphs": similar_paragraphs,
        }

    def _check_word_frequency(
        self, tokens: list[str], name_words: set[str]
    ) -> list[dict]:
        """Flag words appearing >3 std devs above expected frequency."""
        # Filter out stop words, character names, and allowlisted words
        content_words = [
            t for t in tokens
            if t not in self.stop_words
            and t not in name_words
            and t not in self.word_frequency_allowlist
            and len(t) > 2
        ]
        if len(content_words) < 10:
            return []

        counts = Counter(content_words)
        freqs = list(counts.values())

        if len(freqs) < 3:
            return []

        avg = mean(freqs)
        sd = stdev(freqs)
        if sd == 0:
            return []

        threshold = avg + 3 * sd
        flags = []
        for word, count in counts.most_common():
            if count > threshold:
                flags.append({
                    "word": word,
                    "count": count,
                    "expected_max": round(threshold, 1),
                    "zscore": round((count - avg) / sd, 2),
                })
        return flags

    def _check_ngrams(
        self,
        prose: str,
        prior_chapters: list[str] | None,
        n_values: tuple[int, ...] = (3, 4),
    ) -> list[dict]:
        """Check n-gram repetition within chapter and across prior chapters."""
        flags = []
        tokens = _WORD_RE.findall(prose.lower())

        for n in n_values:
            if len(tokens) < n:
                continue

            # Within-chapter n-grams
            chapter_ngrams = Counter()
            for i in range(len(tokens) - n + 1):
                ngram = " ".join(tokens[i:i + n])
                chapter_ngrams[ngram] += 1

            for ngram, count in chapter_ngrams.items():
                if count > 2:
                    flags.append({
                        "ngram": ngram,
                        "count": count,
                        "scope": "chapter",
                    })

            # Cross-chapter n-grams (last 3 chapters)
            if prior_chapters:
                all_texts = list(prior_chapters[-3:]) + [prose]
                cross_ngrams = Counter()
                for text in all_texts:
                    text_tokens = _WORD_RE.findall(text.lower())
                    seen_in_text = set()
                    for i in range(len(text_tokens) - n + 1):
                        ngram = " ".join(text_tokens[i:i + n])
                        if ngram not in seen_in_text:
                            cross_ngrams[ngram] += 1
                            seen_in_text.add(ngram)

                for ngram, doc_count in cross_ngrams.items():
                    if doc_count > 3:
                        # Avoid duplicating flags already caught in chapter scope
                        already_flagged = any(
                            f["ngram"] == ngram for f in flags
                        )
                        if not already_flagged:
                            flags.append({
                                "ngram": ngram,
                                "count": doc_count,
                                "scope": "cross_chapter",
                            })

        return flags

    def _check_openers(self, paragraphs: list[str]) -> list[dict]:
        """Flag when >15% of sentences share the same opening pattern."""
        # Extract sentences from all paragraphs
        sentences = []
        for para in paragraphs:
            # Split on sentence-ending punctuation
            sents = re.split(r'(?<=[.!?])\s+', para)
            sentences.extend(s.strip() for s in sents if s.strip())

        if len(sentences) < 5:
            return []

        # Extract first 3 words of each sentence
        openers = []
        for sent in sentences:
            words = sent.split()[:3]
            if words:
                opener = " ".join(w.lower() for w in words)
                openers.append(opener)

        if not openers:
            return []

        opener_counts = Counter(openers)
        total = len(openers)
        max_pct = 0.15  # from negative_constraints.yaml

        flags = []
        for opener, count in opener_counts.items():
            pct = count / total
            if pct > max_pct and count > 1:
                flags.append({
                    "opener": opener,
                    "percentage": round(pct, 3),
                    "count": count,
                })

        return flags

    def _check_paragraph_similarity(self, paragraphs: list[str]) -> list[dict]:
        """Flag paragraph pairs with cosine similarity above threshold."""
        if self.embedding_function is None or len(paragraphs) < 2:
            return []

        # Embed all paragraphs
        try:
            embeddings = self.embedding_function(paragraphs)
        except Exception:
            return []

        flags = []
        threshold = self.semantic_similarity_threshold
        for i in range(len(embeddings)):
            for j in range(i + 1, len(embeddings)):
                # Adjacency filtering: only compare paragraphs within window
                if self.adjacency_window is not None and (j - i) > self.adjacency_window:
                    continue
                sim = _cosine_similarity(embeddings[i], embeddings[j])
                if sim > threshold:
                    flags.append({
                        "para_a": i,
                        "para_b": j,
                        "similarity": round(sim, 3),
                    })

        return flags

    def _compute_score(
        self,
        flagged_words: list[dict],
        repeated_ngrams: list[dict],
        opener_violations: list[dict],
        similar_paragraphs: list[dict],
    ) -> float:
        """Compute repetition score from 0.0 (severe) to 1.0 (clean)."""
        score = 1.0
        # Cap deductions per category to avoid one category dominating
        score -= min(0.20, 0.02 * len(flagged_words))
        score -= min(0.25, 0.03 * len(repeated_ngrams))
        score -= min(0.15, 0.05 * len(opener_violations))
        score -= min(0.15, 0.05 * len(similar_paragraphs))
        return max(0.0, round(score, 3))
