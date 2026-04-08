"""Style fingerprinting: extract, compare, and store prose style metrics."""

import re
import statistics

# Abbreviations that should not trigger a sentence split on their trailing period.
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "ave",
    "gen", "gov", "sgt", "cpl", "pvt", "capt", "lt", "col",
    "etc", "vs", "vol", "dept", "est", "approx",
    "inc", "ltd", "co", "corp",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug",
    "sep", "oct", "nov", "dec",
})

# Words ending in -ly that are not adverbs.
_LY_FALSE_POSITIVES = frozenset({
    "only", "family", "truly", "really", "holy", "early", "daily",
    "lonely", "likely", "rally", "belly", "ally", "supply", "reply",
    "apply", "fly", "july", "rely", "comply", "multiply", "imply",
    "sly", "ugly", "italy", "friendly", "lovely", "deadly", "lively",
    "costly", "ghostly", "elderly", "orderly", "scholarly", "homely",
    "bully", "jelly", "jolly", "silly", "hilly", "folly", "fully",
    "tally", "assembly", "butterfly", "anomaly", "curly",
})

# Regex that splits on sentence-ending punctuation (.!?) followed by whitespace
# or end-of-string, but avoids splitting after known abbreviations.
# We use a two-pass approach: first split naively, then re-join fragments
# that were incorrectly broken on abbreviation periods.
_SENTENCE_SPLIT_RE = re.compile(r'(?<=[.!?])(?:\s+|$)')

# Pattern for quoted dialogue (double or single quotes wrapping content).
_DIALOGUE_RE = re.compile(r'["\u201c].+?["\u201d]|[\u2018\'].+?[\u2019\']')

# Em-dash variants: actual em-dash, or double-hyphen used as em-dash.
_EM_DASH_RE = re.compile(r'\u2014|--')


class StyleFingerprinter:
    """Extract, compare, and store prose-level style metrics."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(self, prose: str) -> dict:
        """Compute style metrics from a block of prose text.

        Returns a dict with the following keys:
            avg_sentence_length        - average words per sentence
            sentence_length_std        - standard deviation of sentence lengths
            dialogue_to_narration_ratio - proportion of lines containing dialogue
            avg_paragraph_length       - average sentences per paragraph
            adverb_frequency           - proportion of words ending in -ly (excl. false positives)
            question_frequency         - proportion of sentences ending with ?
            exclamation_frequency      - proportion of sentences ending with !
            semicolon_frequency        - semicolons per 1000 words
            em_dash_frequency          - em-dashes per 1000 words
        """
        if not prose or not prose.strip():
            return self._empty_fingerprint()

        sentences = self._split_sentences(prose)
        words = prose.split()
        word_count = len(words)
        paragraphs = [p.strip() for p in prose.split("\n\n") if p.strip()]

        # Sentence lengths (in words)
        sentence_lengths = [len(s.split()) for s in sentences if s.strip()]
        if not sentence_lengths:
            return self._empty_fingerprint()

        avg_sentence_length = statistics.mean(sentence_lengths)
        sentence_length_std = (
            statistics.pstdev(sentence_lengths) if len(sentence_lengths) > 1 else 0.0
        )

        # Dialogue ratio: proportion of non-empty lines that contain quoted text.
        lines = [ln for ln in prose.split("\n") if ln.strip()]
        dialogue_lines = sum(1 for ln in lines if _DIALOGUE_RE.search(ln))
        dialogue_to_narration_ratio = dialogue_lines / max(len(lines), 1)

        # Average paragraph length in sentences.
        para_sentence_counts = []
        for para in paragraphs:
            para_sentences = self._split_sentences(para)
            para_sentence_counts.append(
                len([s for s in para_sentences if s.strip()])
            )
        avg_paragraph_length = (
            statistics.mean(para_sentence_counts) if para_sentence_counts else 0.0
        )

        # Adverb frequency.
        adverb_count = 0
        for w in words:
            clean = re.sub(r'[^a-zA-Z]', '', w).lower()
            if (
                clean.endswith("ly")
                and len(clean) > 3
                and clean not in _LY_FALSE_POSITIVES
            ):
                adverb_count += 1
        adverb_frequency = adverb_count / max(word_count, 1)

        # Question and exclamation frequency.
        question_count = sum(1 for s in sentences if s.strip().endswith("?"))
        exclamation_count = sum(1 for s in sentences if s.strip().endswith("!"))
        sent_total = max(len(sentences), 1)
        question_frequency = question_count / sent_total
        exclamation_frequency = exclamation_count / sent_total

        # Semicolon and em-dash frequency (per 1000 words).
        semicolon_count = prose.count(";")
        em_dash_count = len(_EM_DASH_RE.findall(prose))

        per_k = 1000 / max(word_count, 1)
        semicolon_frequency = semicolon_count * per_k
        em_dash_frequency = em_dash_count * per_k

        return {
            "avg_sentence_length": round(avg_sentence_length, 2),
            "sentence_length_std": round(sentence_length_std, 2),
            "dialogue_to_narration_ratio": round(dialogue_to_narration_ratio, 4),
            "avg_paragraph_length": round(avg_paragraph_length, 2),
            "adverb_frequency": round(adverb_frequency, 4),
            "question_frequency": round(question_frequency, 4),
            "exclamation_frequency": round(exclamation_frequency, 4),
            "semicolon_frequency": round(semicolon_frequency, 2),
            "em_dash_frequency": round(em_dash_frequency, 2),
        }

    def compare(self, current: dict, target: dict) -> dict:
        """Compare two fingerprints and return per-metric deviations.

        Returns a dict keyed by metric name, each value being:
            {
                "current": <float>,
                "target": <float>,
                "deviation_pct": <float>,  # percentage deviation from target
            }
        Only metrics present in *both* fingerprints are compared.
        """
        result = {}
        for metric_name in target:
            if metric_name not in current:
                continue
            cur_val = current[metric_name]
            tgt_val = target[metric_name]
            if tgt_val == 0:
                deviation_pct = 0.0 if cur_val == 0 else 100.0
            else:
                deviation_pct = abs(cur_val - tgt_val) / abs(tgt_val) * 100
            result[metric_name] = {
                "current": cur_val,
                "target": tgt_val,
                "deviation_pct": round(deviation_pct, 2),
            }
        return result

    def store(self, story_state, source: str, metrics: dict) -> None:
        """Persist every metric in *metrics* to the story_state style_fingerprint table.

        Uses ``story_state.add_style_metric(source, metric_name, metric_value)``
        for each key/value pair.
        """
        for metric_name, metric_value in metrics.items():
            story_state.add_style_metric(source, metric_name, metric_value)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_fingerprint() -> dict:
        """Return a zeroed-out fingerprint dict."""
        return {
            "avg_sentence_length": 0.0,
            "sentence_length_std": 0.0,
            "dialogue_to_narration_ratio": 0.0,
            "avg_paragraph_length": 0.0,
            "adverb_frequency": 0.0,
            "question_frequency": 0.0,
            "exclamation_frequency": 0.0,
            "semicolon_frequency": 0.0,
            "em_dash_frequency": 0.0,
        }

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split *text* into sentences.

        Uses a simple regex approach that splits on sentence-ending
        punctuation (.!?) followed by whitespace or end-of-string, but
        avoids splitting after common abbreviations like "Mr.", "Dr.", "etc.".
        """
        # Normalise whitespace for splitting.
        text = text.replace("\n", " ").strip()
        if not text:
            return []

        raw_parts = _SENTENCE_SPLIT_RE.split(text)
        # Filter out empty fragments produced by the split.
        raw_parts = [p for p in raw_parts if p.strip()]
        if not raw_parts:
            return []

        # Re-join fragments that were incorrectly broken after abbreviations.
        merged: list[str] = []
        for part in raw_parts:
            if merged and _ends_with_abbreviation(merged[-1]):
                merged[-1] = merged[-1] + " " + part
            else:
                merged.append(part)

        return merged


def _ends_with_abbreviation(fragment: str) -> bool:
    """Return True if *fragment* ends with a known abbreviation period."""
    fragment = fragment.rstrip()
    if not fragment.endswith("."):
        return False
    # Grab the last whitespace-delimited token before the period.
    last_token = fragment.rstrip(".").rsplit(None, 1)[-1].lower()
    # Strip any leading punctuation (e.g. opening quotes or parens).
    last_token = re.sub(r'^[^a-zA-Z]+', '', last_token)
    return last_token in _ABBREVIATIONS
