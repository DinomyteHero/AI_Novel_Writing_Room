"""Check prose against character voice profiles and anti-slop constraints."""

import re

# False positives for adverb detection (words ending in -ly that aren't adverbs)
_LY_FALSE_POSITIVES = frozenset({
    "only", "really", "family", "holy", "early", "daily", "lonely",
    "likely", "rally", "belly", "ally", "supply", "reply", "apply",
    "fly", "july", "rely", "comply", "multiply", "imply", "sly",
    "ugly", "italy", "friendly", "lovely", "deadly", "lively",
    "costly", "ghostly", "elderly", "orderly", "scholarly", "homely",
    "bully", "jelly", "jolly", "silly", "hilly", "folly", "fully",
    "tally", "assembly", "butterfly", "anomaly", "curly",
})

_METAPHOR_PATTERNS = [
    re.compile(r'\blike\s+a\b', re.IGNORECASE),
    re.compile(r'\bas\s+if\b', re.IGNORECASE),
    re.compile(r'\bas\s+though\b', re.IGNORECASE),
]


class VoiceChecker:
    """Check prose against voice profiles and anti-slop constraints."""

    def __init__(self, negative_constraints: dict):
        self.banned_phrases = negative_constraints.get("banned_phrases", {})
        self.structural_rules = negative_constraints.get("structural_rules", {})
        self.max_adverb_density = self.structural_rules.get("max_adverb_density", 0.02)
        self.metaphor_cooldown = self.structural_rules.get("metaphor_cooldown_paragraphs", 8)

    def analyze(
        self,
        prose: str,
        voice_notes: str = "",
        pov_character_name: str = "",
    ) -> dict:
        """Run all voice consistency checks.

        Returns:
            {
                "voice_fidelity_score": float,  # 0.0 to 1.0
                "banned_phrases_found": [...],
                "adverb_density": float,
                "adverb_flag": bool,
                "metaphor_violations": [...],
                "voice_notes": str,
            }
        """
        if not prose or not prose.strip():
            return {
                "voice_fidelity_score": 1.0,
                "banned_phrases_found": [],
                "adverb_density": 0.0,
                "adverb_flag": False,
                "metaphor_violations": [],
                "voice_notes": "",
            }

        banned = self._scan_banned_phrases(prose)
        adverb_density, adverb_flag = self._compute_adverb_density(prose)
        metaphor_violations = self._check_metaphor_cooldown(prose)
        voice_fidelity, voice_feedback = self._check_voice_fidelity(prose, voice_notes)

        score = self._compute_score(
            banned, adverb_flag, metaphor_violations, voice_fidelity
        )

        return {
            "voice_fidelity_score": score,
            "banned_phrases_found": banned,
            "adverb_density": round(adverb_density, 4),
            "adverb_flag": adverb_flag,
            "metaphor_violations": metaphor_violations,
            "voice_notes": voice_feedback,
        }

    def _scan_banned_phrases(self, prose: str) -> list[dict]:
        """Scan prose against all banned phrase categories."""
        hits = []
        prose_lower = prose.lower()
        lines = prose.split("\n")

        for category, phrases in self.banned_phrases.items():
            for phrase in phrases:
                phrase_lower = phrase.lower()
                # Search for the phrase in the text
                idx = 0
                while True:
                    pos = prose_lower.find(phrase_lower, idx)
                    if pos == -1:
                        break
                    # Find line number
                    line_num = prose[:pos].count("\n") + 1
                    # Get surrounding context
                    start = max(0, pos - 20)
                    end = min(len(prose), pos + len(phrase) + 20)
                    context = prose[start:end].replace("\n", " ")
                    hits.append({
                        "phrase": phrase,
                        "category": category,
                        "location": f"line {line_num}",
                        "context": f"...{context}...",
                    })
                    idx = pos + 1

        return hits

    def _compute_adverb_density(self, prose: str) -> tuple[float, bool]:
        """Count adverb density (words ending in -ly / total words)."""
        words = prose.lower().split()
        if not words:
            return (0.0, False)

        adverb_count = 0
        for word in words:
            # Strip punctuation from word
            clean = re.sub(r'[^a-z]', '', word)
            if clean.endswith("ly") and len(clean) > 3 and clean not in _LY_FALSE_POSITIVES:
                adverb_count += 1

        density = adverb_count / len(words)
        return (density, density > self.max_adverb_density)

    def _check_metaphor_cooldown(self, prose: str) -> list[dict]:
        """Flag metaphors/similes appearing within cooldown distance."""
        paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]
        if not paragraphs:
            return []

        # Find all metaphor locations (paragraph index)
        metaphor_locations = []
        for para_idx, para in enumerate(paragraphs):
            for pattern in _METAPHOR_PATTERNS:
                if pattern.search(para):
                    metaphor_locations.append(para_idx)
                    break  # One match per paragraph is enough

        # Check distances between consecutive metaphors
        violations = []
        for i in range(1, len(metaphor_locations)):
            distance = metaphor_locations[i] - metaphor_locations[i - 1]
            if distance < self.metaphor_cooldown:
                violations.append({
                    "location_a": metaphor_locations[i - 1],
                    "location_b": metaphor_locations[i],
                    "distance_paragraphs": distance,
                })

        return violations

    def _check_voice_fidelity(
        self, prose: str, voice_notes: str
    ) -> tuple[float, str]:
        """Coarse heuristic check of voice against voice_notes."""
        if not voice_notes:
            return (1.0, "")

        notes_lower = voice_notes.lower()
        feedback_parts = []
        penalties = 0.0

        # Split into sentences for analysis
        sentences = re.split(r'(?<=[.!?])\s+', prose)
        if not sentences:
            return (1.0, "")

        avg_sent_len = sum(len(s.split()) for s in sentences) / len(sentences)

        # Check for short/terse voice expectations
        if any(w in notes_lower for w in ("short", "terse", "laconic", "clipped", "brief")):
            if avg_sent_len > 18:
                feedback_parts.append(
                    f"Voice notes indicate short sentences, but avg is {avg_sent_len:.0f} words"
                )
                penalties += 0.15

        # Check for informal voice
        contraction_count = len(re.findall(r"\b\w+'(?:t|s|re|ve|ll|d|m)\b", prose))
        words = prose.split()
        contraction_ratio = contraction_count / max(len(words), 1)

        if any(w in notes_lower for w in ("informal", "casual", "humor", "irreverent")):
            if contraction_ratio < 0.01:
                feedback_parts.append("Voice notes indicate informal tone, but few contractions found")
                penalties += 0.10

        # Check for formal/academic voice
        if any(w in notes_lower for w in ("formal", "academic", "precise", "scholarly")):
            if contraction_ratio > 0.03:
                feedback_parts.append("Voice notes indicate formal tone, but many contractions found")
                penalties += 0.10

        fidelity = max(0.0, 1.0 - penalties)
        return (fidelity, "; ".join(feedback_parts))

    def _compute_score(
        self,
        banned: list[dict],
        adverb_flag: bool,
        metaphor_violations: list[dict],
        voice_fidelity: float,
    ) -> float:
        """Compute overall voice consistency score."""
        score = 1.0
        score -= 0.03 * len(banned)
        if adverb_flag:
            score -= 0.10
        score -= 0.05 * len(metaphor_violations)
        score -= (1.0 - voice_fidelity) * 0.5  # Scale voice fidelity impact
        return max(0.0, round(score, 3))
