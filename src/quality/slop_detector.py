"""Detect AI-typical writing artifacts and LLM slop patterns."""

import re
from collections import Counter
from statistics import mean, variance

from src.quality._para_util import line_to_paragraph_index

# Show-don't-tell words to flag outside dialogue
_TELLING_WORDS = [
    "felt", "knew", "realized", "understood", "noticed", "wondered",
    "seemed", "appeared", "was aware", "could tell", "could sense",
    "the distinction mattered", "explanation required",
    "he'd been waiting to be sure", "she'd been waiting to be sure",
]

# Generic filler patterns typical of LLM output
_FILLER_PATTERNS = [
    "in that moment",
    "without hesitation",
    "for a long moment",
    "despite everything",
    "something shifted",
    "with a sense of",
    "it was as if",
    "there was something about",
    "for some reason",
    "in the end",
    "at the end of the day",
    "a mixture of",
    "couldn't help but",
    "found himself",
    "found herself",
    "the kind of pain that",
    "the kind of silence that",
    "the kind of weight that",
    "like a skip in",
    "bodies keep score",
    "the body keeps the score",
    "something about the way",
]

# Additional AI-tell phrases beyond what's in negative_constraints
_EXTRA_AI_TELLS = [
    "a testament to",
    "in the realm of",
    "crucial",
    "vital",
    "pivotal",
]


class SlopDetector:
    """Detect AI-typical writing artifacts in prose."""

    def __init__(self, negative_constraints: dict):
        self.ai_tells = list(
            negative_constraints.get("banned_phrases", {}).get("ai_tells", [])
        )
        # Merge extras, avoiding duplicates
        existing_lower = {t.lower() for t in self.ai_tells}
        for tell in _EXTRA_AI_TELLS:
            if tell.lower() not in existing_lower:
                self.ai_tells.append(tell)

    def analyze(self, prose: str) -> dict:
        """Run all slop detection analyses.

        Returns:
            {
                "slop_score": float,  # 0.0 (AI-saturated) to 1.0 (clean)
                "ai_tells_found": [...],
                "burstiness_score": float,
                "tell_not_show": [...],
                "filler_patterns": [...],
            }
        """
        if not prose or not prose.strip():
            return {
                "slop_score": 1.0,
                "ai_tells_found": [],
                "burstiness_score": 0.0,
                "tell_not_show": [],
                "filler_patterns": [],
            }

        ai_tells = self._scan_ai_tells(prose)
        burstiness = self._compute_burstiness(prose)
        tell_not_show = self._scan_show_dont_tell(prose)
        fillers = self._scan_filler_patterns(prose)

        score = self._compute_score(ai_tells, burstiness, tell_not_show, fillers)

        return {
            "slop_score": score,
            "ai_tells_found": ai_tells,
            "burstiness_score": round(burstiness, 3),
            "tell_not_show": tell_not_show,
            "filler_patterns": fillers,
        }

    def _scan_ai_tells(self, prose: str) -> list[dict]:
        """Scan for known AI-tell words and phrases."""
        hits = []
        prose_lower = prose.lower()
        lines = prose.split("\n")

        for tell in self.ai_tells:
            tell_lower = tell.lower()
            # Use word boundary for single words, substring for phrases
            if " " in tell_lower:
                pattern = re.escape(tell_lower)
            else:
                pattern = r'\b' + re.escape(tell_lower) + r'\b'

            for match in re.finditer(pattern, prose_lower):
                pos = match.start()
                line_num = prose[:pos].count("\n") + 1
                hits.append({
                    "word": tell,
                    "location": f"line {line_num}",
                })

        return hits

    def _compute_burstiness(self, prose: str) -> float:
        """Measure burstiness of word repetition.

        Uses index of dispersion: (variance - mean) / (variance + mean)
        for inter-occurrence distances of common content words.
        Values near 1.0 indicate bursty (AI-like) patterns.
        """
        words = re.findall(r'[a-z]+', prose.lower())
        if len(words) < 50:
            return 0.0

        # Get top-50 content words (excluding very common words)
        common_stops = frozenset({
            "the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
            "for", "of", "with", "by", "from", "is", "was", "are", "were",
            "be", "been", "have", "has", "had", "that", "this", "it", "he",
            "she", "they", "his", "her", "its", "not", "said",
        })

        counts = Counter(w for w in words if w not in common_stops and len(w) > 2)
        top_words = [w for w, _ in counts.most_common(50) if counts[w] >= 3]

        if not top_words:
            return 0.0

        burstiness_scores = []
        for word in top_words:
            # Find all positions of this word
            positions = [i for i, w in enumerate(words) if w == word]
            if len(positions) < 3:
                continue

            # Compute inter-occurrence distances
            distances = [
                positions[i + 1] - positions[i]
                for i in range(len(positions) - 1)
            ]
            if len(distances) < 2:
                continue

            m = mean(distances)
            v = variance(distances)
            if (v + m) == 0:
                continue

            # Index of dispersion
            b = (v - m) / (v + m)
            burstiness_scores.append(b)

        if not burstiness_scores:
            return 0.0

        # Average burstiness, clamped to [0, 1]
        avg_b = mean(burstiness_scores)
        return max(0.0, min(1.0, avg_b))

    def _scan_show_dont_tell(self, prose: str) -> list[dict]:
        """Flag telling emotion words appearing outside dialogue."""
        hits = []
        lines = prose.split("\n")

        for line_idx, line in enumerate(lines):
            line_num = line_idx + 1
            # Remove dialogue (text inside quotes) from the line
            no_dialogue = re.sub(r'"[^"]*"', '', line)

            for telling_word in _TELLING_WORDS:
                # Word boundary match for single words, plain match for phrases
                if " " in telling_word:
                    pattern = re.escape(telling_word)
                else:
                    pattern = r'\b' + re.escape(telling_word) + r'\b'

                for match in re.finditer(pattern, no_dialogue, re.IGNORECASE):
                    # Get context snippet
                    start = max(0, match.start() - 15)
                    end = min(len(no_dialogue), match.end() + 15)
                    context = no_dialogue[start:end].strip()
                    hits.append({
                        "phrase": telling_word,
                        "location": f"line {line_num}",
                        "paragraph": line_to_paragraph_index(prose, line_num),
                        "context": context,
                    })

        return hits

    def _scan_filler_patterns(self, prose: str) -> list[dict]:
        """Flag generic transitional/filler phrases."""
        hits = []
        prose_lower = prose.lower()

        for filler in _FILLER_PATTERNS:
            filler_lower = filler.lower()
            idx = 0
            while True:
                pos = prose_lower.find(filler_lower, idx)
                if pos == -1:
                    break
                line_num = prose[:pos].count("\n") + 1
                hits.append({
                    "phrase": filler,
                    "location": f"line {line_num}",
                    "paragraph": line_to_paragraph_index(prose, line_num),
                })
                idx = pos + 1

        return hits

    def _compute_score(
        self,
        ai_tells: list[dict],
        burstiness: float,
        tell_not_show: list[dict],
        fillers: list[dict],
    ) -> float:
        """Compute slop score from 0.0 (saturated) to 1.0 (clean)."""
        score = 1.0
        score -= min(0.40, 0.08 * len(ai_tells))
        score -= min(0.25, 0.05 * len(fillers))
        # Show-don't-tell is less severe — occasional use is fine in fiction
        score -= min(0.15, 0.02 * len(tell_not_show))
        # Burstiness penalty for scores > 0.5
        score -= max(0, burstiness - 0.5) * 0.3
        return max(0.0, round(score, 3))
