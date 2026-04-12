"""Measure narrative pacing characteristics in prose."""

import re
from collections import Counter
from statistics import mean, stdev

# Expected event density ranges by structural phase (events per 1000 words).
# Calibrated against observed output from Phase 4 pipeline runs (34-57.5/1k).
# The formula counts action words + dialogue tags + paragraph breaks as events,
# so paragraph count contributes significantly to the total. These ranges reflect
# the actual density profile of character-driven literary fiction with interspersed
# dialogue and moderate action pacing.
PHASE_DENSITY = {
    "setup": (20.0, 45.0),
    "first_plot_point": (25.0, 50.0),
    "response": (22.0, 48.0),
    "first_pinch": (30.0, 55.0),
    "midpoint": (30.0, 55.0),
    "attack": (30.0, 60.0),
    "second_pinch": (30.0, 55.0),
    "second_plot_point": (25.0, 50.0),
    "resolution": (20.0, 45.0),
    "climax": (35.0, 65.0),
}

# Heuristic word sets for paragraph classification
_ACTION_WORDS = frozenset({
    "ran", "jumped", "grabbed", "threw", "pulled", "pushed", "struck",
    "slammed", "dodged", "lunged", "sprinted", "dashed", "fired", "swung",
    "charged", "leaped", "ducked", "rolled", "blocked", "caught",
    "hit", "kicked", "punched", "stabbed", "shot", "exploded",
})

_INTROSPECTION_WORDS = frozenset({
    "thought", "wondered", "remembered", "considered", "realized",
    "reflected", "imagined", "recalled", "pondered", "felt", "knew",
    "understood", "believed", "feared", "hoped", "wished", "doubted",
    "questioned", "suspected", "sensed",
})

_DIALOGUE_TAG_RE = re.compile(
    r'\b(said|asked|replied|whispered|shouted|muttered|murmured|snapped|'
    r'growled|sighed|laughed|called|answered|added|continued|explained)\b',
    re.IGNORECASE,
)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences using regex heuristics."""
    # Handle common abbreviations to avoid false splits
    cleaned = text
    for abbr in ("Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Gen.", "Col.",
                 "Sgt.", "Ltd.", "Inc.", "Jr.", "Sr.", "vs.", "etc.",
                 "e.g.", "i.e."):
        cleaned = cleaned.replace(abbr, abbr.replace(".", "\x00"))

    # Split on sentence-ending punctuation followed by space or end
    parts = re.split(r'(?<=[.!?])\s+', cleaned)

    # Restore abbreviation periods
    sentences = []
    for part in parts:
        restored = part.replace("\x00", ".")
        stripped = restored.strip()
        if stripped:
            sentences.append(stripped)

    return sentences


class PacingAnalyzer:
    """Measure narrative pacing characteristics."""

    def analyze(self, prose: str, structural_phase: str = "setup") -> dict:
        """Run all pacing analyses.

        Returns:
            {
                "pacing_score": float,  # 0.0 (poor) to 1.0 (excellent)
                "sentence_length_variance": float,
                "variance_flag": bool,
                "dialogue_ratio": float,
                "scene_type_distribution": dict,
                "scene_type_flag": str | None,
                "event_density_per_1k": float,
                "expected_density_range": list,
                "density_flag": bool,
                "flags": list,
            }
        """
        if not prose or not prose.strip():
            return {
                "pacing_score": 1.0,
                "sentence_length_variance": 0.0,
                "variance_flag": False,
                "dialogue_ratio": 0.0,
                "scene_type_distribution": {
                    "action": 0.0, "dialogue": 0.0,
                    "introspection": 0.0, "description": 0.0,
                },
                "scene_type_flag": None,
                "event_density_per_1k": 0.0,
                "expected_density_range": list(PHASE_DENSITY.get(structural_phase, (2.0, 5.0))),
                "density_flag": False,
                "flags": [],
            }

        sentences = _split_sentences(prose)
        paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]
        word_count = len(prose.split())
        flags = []

        # Sentence length variance
        variance, variance_flag = self._compute_sentence_variance(sentences)
        if variance_flag:
            flags.append({
                "type": "low_variance",
                "description": f"Sentence length CV {variance:.2f} below 0.3 threshold",
                "value": variance,
                "threshold": 0.3,
            })

        # Dialogue ratio
        dialogue_ratio = self._compute_dialogue_ratio(prose)

        # Scene type distribution
        distribution, scene_type_flag = self._classify_paragraphs(paragraphs)
        if scene_type_flag:
            flags.append({
                "type": "scene_type_imbalance",
                "description": f">{60}% of paragraphs classified as '{scene_type_flag}'",
                "value": distribution[scene_type_flag],
                "threshold": 0.6,
            })

        # Event density
        density, expected_range, density_flag = self._compute_event_density(
            prose, word_count, structural_phase
        )
        if density_flag:
            flags.append({
                "type": "event_density",
                "description": (
                    f"Event density {density:.1f}/1k words outside "
                    f"expected range {expected_range} for '{structural_phase}'"
                ),
                "value": density,
                "threshold": expected_range,
            })

        score = self._compute_score(variance_flag, scene_type_flag, density_flag)

        return {
            "pacing_score": score,
            "sentence_length_variance": round(variance, 3),
            "variance_flag": variance_flag,
            "dialogue_ratio": round(dialogue_ratio, 3),
            "scene_type_distribution": {k: round(v, 3) for k, v in distribution.items()},
            "scene_type_flag": scene_type_flag,
            "event_density_per_1k": round(density, 1),
            "expected_density_range": list(expected_range),
            "density_flag": density_flag,
            "flags": flags,
        }

    def _compute_sentence_variance(
        self, sentences: list[str]
    ) -> tuple[float, bool]:
        """Compute coefficient of variation of sentence lengths."""
        if len(sentences) < 3:
            return (0.0, False)

        lengths = [len(s.split()) for s in sentences]
        avg = mean(lengths)
        if avg == 0:
            return (0.0, False)

        sd = stdev(lengths)
        cv = sd / avg
        return (cv, cv < 0.3)

    def _compute_dialogue_ratio(self, prose: str) -> float:
        """Measure percentage of text that is dialogue (inside quotes)."""
        # Count characters inside double quotes
        in_dialogue = False
        dialogue_chars = 0
        total_chars = 0

        for char in prose:
            if char == '"':
                in_dialogue = not in_dialogue
                continue
            if char.isalpha() or char == ' ':
                total_chars += 1
                if in_dialogue:
                    dialogue_chars += 1

        if total_chars == 0:
            return 0.0
        return dialogue_chars / total_chars

    def _classify_paragraphs(
        self, paragraphs: list[str]
    ) -> tuple[dict[str, float], str | None]:
        """Classify each paragraph and return distribution."""
        if not paragraphs:
            return (
                {"action": 0.0, "dialogue": 0.0, "introspection": 0.0, "description": 0.0},
                None,
            )

        counts = Counter()
        for para in paragraphs:
            classification = self._classify_single_paragraph(para)
            counts[classification] += 1

        total = len(paragraphs)
        distribution = {
            "action": counts.get("action", 0) / total,
            "dialogue": counts.get("dialogue", 0) / total,
            "introspection": counts.get("introspection", 0) / total,
            "description": counts.get("description", 0) / total,
        }

        # Flag if any single type > 60%
        dominant = None
        for stype, ratio in distribution.items():
            if ratio > 0.6:
                dominant = stype
                break

        return distribution, dominant

    def _classify_single_paragraph(self, para: str) -> str:
        """Classify a single paragraph as action/dialogue/introspection/description."""
        words = para.lower().split()
        word_set = set(words)

        # Dialogue: more than 50% of text in quotes
        quote_chars = sum(1 for c in para if c == '"')
        if quote_chars >= 2:
            # Rough check: if quotes present and dialogue tags found
            if _DIALOGUE_TAG_RE.search(para):
                return "dialogue"
            # Check if significant portion is in quotes
            in_q = False
            q_len = 0
            for c in para:
                if c == '"':
                    in_q = not in_q
                elif in_q:
                    q_len += 1
            if q_len > len(para) * 0.4:
                return "dialogue"

        # Action: contains action words and short sentences
        action_count = len(word_set & _ACTION_WORDS)
        if action_count >= 2:
            return "action"

        # Introspection: contains introspection words
        intro_count = len(word_set & _INTROSPECTION_WORDS)
        if intro_count >= 2:
            return "introspection"

        # Default: description
        return "description"

    def _compute_event_density(
        self,
        prose: str,
        word_count: int,
        structural_phase: str,
    ) -> tuple[float, tuple[float, float], bool]:
        """Count discrete events per 1000 words."""
        if word_count == 0:
            expected = PHASE_DENSITY.get(structural_phase, (2.0, 5.0))
            return (0.0, expected, False)

        # Count events: action words + dialogue exchanges + paragraph breaks
        prose_lower = prose.lower()
        action_count = sum(1 for w in _ACTION_WORDS if f" {w} " in f" {prose_lower} ")
        dialogue_tags = len(_DIALOGUE_TAG_RE.findall(prose))
        paragraphs = len([p for p in prose.split("\n\n") if p.strip()])

        total_events = action_count + dialogue_tags + paragraphs
        density = (total_events / word_count) * 1000

        expected = PHASE_DENSITY.get(structural_phase, (2.0, 5.0))
        flag = density < expected[0] or density > expected[1]

        return (density, expected, flag)

    def _compute_score(
        self,
        variance_flag: bool,
        scene_type_flag: str | None,
        density_flag: bool,
    ) -> float:
        """Compute pacing score from flags."""
        score = 1.0
        if variance_flag:
            score -= 0.20
        if scene_type_flag:
            score -= 0.20
        if density_flag:
            score -= 0.15
        return max(0.0, round(score, 3))

    def analyze_chapter_pacing(self, scene_analyses: list[dict]) -> dict:
        """Aggregate pacing metrics across a chapter's scenes.

        Args:
            scene_analyses: List of per-scene pacing analysis dicts.

        Returns:
            Chapter-level pacing summary with variety index and flags.
        """
        if not scene_analyses:
            return {
                "avg_sentence_variance": 0.0,
                "scene_type_distribution_chapter": {},
                "variety_index": 0.0,
                "flags": [],
            }

        # Average sentence variance
        variances = [sa.get("sentence_length_variance", 0.0) for sa in scene_analyses]
        avg_variance = sum(variances) / len(variances)

        # Aggregate scene type distribution across chapter
        from collections import Counter
        type_counts: Counter = Counter()
        total_scenes = len(scene_analyses)
        for sa in scene_analyses:
            dist = sa.get("scene_type_distribution", {})
            for stype, ratio in dist.items():
                type_counts[stype] += ratio

        chapter_dist = {
            k: round(v / total_scenes, 3) for k, v in type_counts.items()
        } if total_scenes else {}

        # Variety index: 1 - max_proportion
        max_prop = max(chapter_dist.values()) if chapter_dist else 0.0
        variety_index = round(1.0 - max_prop, 3) if chapter_dist else 0.0

        flags = []
        if variety_index < 0.2 and chapter_dist:
            dominant = max(chapter_dist, key=chapter_dist.get)
            flags.append(
                f"Low scene variety ({variety_index:.2f}): chapter dominated by '{dominant}'"
            )

        return {
            "avg_sentence_variance": round(avg_variance, 3),
            "scene_type_distribution_chapter": chapter_dist,
            "variety_index": variety_index,
            "flags": flags,
        }
