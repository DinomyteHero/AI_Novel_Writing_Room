"""Unified quality metrics dashboard aggregating all quality checkers."""

from collections import Counter
from pathlib import Path

import yaml

from src.quality.dialogue_expectation import derive as derive_dialogue_expectation
from src.quality.pacing_analyzer import PacingAnalyzer
from src.quality.repetition_detector import RepetitionDetector
from src.quality.slop_detector import SlopDetector
from src.quality.voice_checker import VoiceChecker


class MetricsDashboard:
    """Aggregate quality metrics across all checkers for per-chapter reports."""

    def __init__(
        self,
        negative_constraints_path: str = "config/negative_constraints.yaml",
        embedding_function=None,
    ):
        constraints_path = Path(negative_constraints_path)
        if constraints_path.exists():
            with open(constraints_path, encoding="utf-8") as f:
                self.negative_constraints = yaml.safe_load(f)
        else:
            self.negative_constraints = {"banned_phrases": {}, "structural_rules": {}}

        self.repetition = RepetitionDetector(embedding_function=embedding_function)
        self.pacing = PacingAnalyzer()
        self.voice = VoiceChecker(self.negative_constraints)
        self.slop = SlopDetector(self.negative_constraints)

        # Cross-scene overused word tracking
        self._manuscript_word_freq: Counter = Counter()
        self._manuscript_scene_count: int = 0
        self._word_scene_appearances: Counter = Counter()  # tracks how many scenes each word was flagged in

    def analyze_chapter(
        self,
        prose: str,
        scene_card: dict,
        prior_chapters: list[str] | None = None,
        voice_notes: str = "",
    ) -> dict:
        """Run all quality metrics on a chapter.

        Returns:
            {
                "chapter_number": int,
                "scene_number": int,
                "word_count": int,
                "repetition": dict,
                "pacing": dict,
                "voice": dict,
                "slop": dict,
                "overall_score": float,
                "passed": bool,
                "flags": list[str],
                "per_scene": list[dict],  # single-item list wrapping this result
            }

        `per_scene` is present so downstream consumers that iterate
        `quality_metrics["per_scene"]` (orchestrator, scene_emotion,
        line_copy) receive a non-empty list without the orchestrator
        having to switch to `analyze_chapter_multi_scene`. The inner dict
        shares structure with the top-level fields; the same rep/pacing/
        voice/slop dicts are referenced from both places, so consumers
        that read flat fields and consumers that iterate per_scene see
        the same underlying data.
        """
        chapter_num = scene_card.get("chapter_number", 0)
        scene_num = scene_card.get("scene_number", 1)
        character_names = scene_card.get("characters_present", [])
        structural_phase = scene_card.get("structural_phase", "setup")
        pov_character = scene_card.get("pov_character", "")
        word_count = len(prose.split()) if prose else 0

        # Run all checkers
        rep_result = self.repetition.analyze(
            prose,
            character_names=character_names,
            prior_chapters=prior_chapters,
        )
        pacing_result = self.pacing.analyze(
            prose,
            structural_phase=structural_phase,
            characters_present=character_names,
            dialogue_expectation=derive_dialogue_expectation(scene_card),
        )
        voice_result = self.voice.analyze(
            prose,
            voice_notes=voice_notes,
            pov_character_name=pov_character,
        )
        slop_result = self.slop.analyze(prose)

        # Weighted average: 0.25 each
        overall_score = 0.25 * (
            rep_result["repetition_score"]
            + pacing_result["pacing_score"]
            + voice_result["voice_fidelity_score"]
            + slop_result["slop_score"]
        )
        overall_score = round(overall_score, 3)

        # Collect human-readable flags
        flags = self._collect_flags(rep_result, pacing_result, voice_result, slop_result)

        # Build the per-scene payload once and expose it both at the top
        # level (legacy flat access) and inside `per_scene` (list-iterating
        # consumers). Shared references — not deep-copied — so there's no
        # risk of the two views drifting.
        scene_payload = {
            "chapter_number": chapter_num,
            "scene_number": scene_num,
            "word_count": word_count,
            "repetition": rep_result,
            "pacing": pacing_result,
            "voice": voice_result,
            "slop": slop_result,
            "overall_score": overall_score,
            "passed": overall_score >= 0.6,
            "flags": flags,
        }
        return {
            **scene_payload,
            "per_scene": [scene_payload],
        }

    def analyze_manuscript(self, chapter_results: list[dict]) -> dict:
        """Aggregate metrics across all chapters.

        Args:
            chapter_results: list of results from analyze_chapter()

        Returns:
            {
                "manuscript_score": float,
                "chapter_scores": list[float],
                "trends": {...},
                "worst_chapters": list[int],
            }
        """
        if not chapter_results:
            return {
                "manuscript_score": 0.0,
                "chapter_scores": [],
                "trends": {
                    "repetition_trend": [],
                    "pacing_trend": [],
                    "voice_trend": [],
                    "slop_trend": [],
                },
                "worst_chapters": [],
            }

        chapter_scores = [r["overall_score"] for r in chapter_results]
        manuscript_score = round(
            sum(chapter_scores) / len(chapter_scores), 3
        )

        trends = {
            "repetition_trend": [
                r["repetition"]["repetition_score"] for r in chapter_results
            ],
            "pacing_trend": [
                r["pacing"]["pacing_score"] for r in chapter_results
            ],
            "voice_trend": [
                r["voice"]["voice_fidelity_score"] for r in chapter_results
            ],
            "slop_trend": [
                r["slop"]["slop_score"] for r in chapter_results
            ],
        }

        worst_chapters = [
            r["chapter_number"]
            for r in chapter_results
            if r["overall_score"] < 0.6
        ]

        return {
            "manuscript_score": manuscript_score,
            "chapter_scores": chapter_scores,
            "trends": trends,
            "worst_chapters": worst_chapters,
        }

    def analyze_chapter_multi_scene(self, scene_results: list[dict]) -> dict:
        """Aggregate per-scene analysis results into a chapter-level report.

        Args:
            scene_results: List of dicts from analyze_chapter(), one per scene.

        Returns:
            Chapter aggregate with min/max/avg scores, per-scene detail,
            pass/fail determination, and weakest scene identification.
        """
        if not scene_results:
            return {
                "chapter_number": 0,
                "scene_count": 0,
                "aggregate_score": 0.0,
                "min_score": 0.0,
                "max_score": 0.0,
                "avg_score": 0.0,
                "per_scene": [],
                "passed": False,
                "weakest_scene": 0,
            }

        scores = [r["overall_score"] for r in scene_results]
        ch = scene_results[0].get("chapter_number", 0)

        min_score = min(scores)
        max_score = max(scores)
        avg_score = sum(scores) / len(scores)

        # Chapter passes if avg >= 0.6 AND no single scene below 0.4
        passed = avg_score >= 0.6 and min_score >= 0.4

        weakest_idx = scores.index(min_score)
        weakest_scene = scene_results[weakest_idx].get("scene_number", 0)

        return {
            "chapter_number": ch,
            "scene_count": len(scene_results),
            "aggregate_score": round(avg_score, 3),
            "min_score": round(min_score, 3),
            "max_score": round(max_score, 3),
            "avg_score": round(avg_score, 3),
            "per_scene": scene_results,
            "passed": passed,
            "weakest_scene": weakest_scene,
        }

    def _collect_flags(
        self,
        rep: dict,
        pacing: dict,
        voice: dict,
        slop: dict,
    ) -> list[str]:
        """Collect human-readable flag summaries from all checkers."""
        flags = []

        # Repetition flags
        if rep["flagged_words"]:
            # Surface per-word paragraph indices when we have them so
            # Quality Polish can target the right paragraphs directly.
            word_summaries = []
            for f in rep["flagged_words"][:3]:
                paras = f.get("paragraph_indices") or []
                if paras:
                    paras_str = ", ".join(f"¶{i}" for i in paras)
                    word_summaries.append(f"{f['word']} ({paras_str})")
                else:
                    word_summaries.append(f["word"])
            flags.append(f"Overused words: {', '.join(word_summaries)}")
        if rep["repeated_ngrams"]:
            count = len(rep["repeated_ngrams"])
            flags.append(f"{count} repeated n-gram(s) detected")
        if rep["opener_violations"]:
            flags.append("Sentence opener repetition above 15% threshold")
        if rep["similar_paragraphs"]:
            flags.append(f"{len(rep['similar_paragraphs'])} semantically similar paragraph pair(s)")

        # Pacing flags
        if pacing["variance_flag"]:
            flags.append(
                f"Low sentence length variance ({pacing['sentence_length_variance']:.2f})"
            )
        if pacing["scene_type_flag"]:
            flags.append(f"Scene type imbalance: >{60}% {pacing['scene_type_flag']}")
        if pacing["density_flag"]:
            flags.append(
                f"Event density {pacing['event_density_per_1k']:.1f}/1k outside expected range"
            )

        # Voice flags
        if voice["banned_phrases_found"]:
            count = len(voice["banned_phrases_found"])
            flags.append(f"{count} banned phrase(s) detected")
        if voice["adverb_flag"]:
            flags.append(f"Adverb density {voice['adverb_density']:.3f} exceeds 0.02 threshold")
        if voice["metaphor_violations"]:
            flags.append(f"{len(voice['metaphor_violations'])} metaphor cooldown violation(s)")

        # Slop flags
        if slop["ai_tells_found"]:
            tells = ", ".join(
                set(h["word"] for h in slop["ai_tells_found"][:5])
            )
            flags.append(f"AI-tell words: {tells}")
        if slop["tell_not_show"]:
            count = len(slop["tell_not_show"])
            flags.append(f"{count} show-don't-tell violation(s)")
        if slop["filler_patterns"]:
            count = len(slop["filler_patterns"])
            flags.append(f"{count} filler pattern(s) detected")
        if slop["burstiness_score"] > 0.5:
            flags.append(f"High burstiness score ({slop['burstiness_score']:.2f})")

        # Cross-scene manuscript-level tracking
        self._manuscript_scene_count += 1
        if rep["flagged_words"]:
            for w in rep["flagged_words"]:
                self._manuscript_word_freq[w["word"]] += w["count"]
                self._word_scene_appearances[w["word"]] += 1

        # Flag words that appear in overused lists across 3+ scenes
        manuscript_flags = []
        for word, scene_count in self._word_scene_appearances.items():
            if scene_count >= 3:
                total = self._manuscript_word_freq[word]
                manuscript_flags.append(
                    f"Manuscript-level overused: '{word}' ({total}x across {scene_count} scenes)"
                )
        flags.extend(manuscript_flags)

        return flags
