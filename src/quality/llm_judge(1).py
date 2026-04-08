"""LLM-as-Judge evaluation for holistic quality assessment.

Uses a cloud model (Claude Sonnet via OpenRouter) to provide
structured rubric-based scoring beyond heuristic metrics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from src.agents.base_agent import BaseAgent

if TYPE_CHECKING:
    from src.model_router import ModelRouter


# Default rubric used when config file is not found
_DEFAULT_RUBRIC = {
    "narrative_engagement": {
        "description": "Does the prose pull the reader forward?",
        "scoring": "1-3: flat, 4-6: adequate, 7-8: compelling, 9-10: unputdownable",
    },
    "character_authenticity": {
        "description": "Do characters feel real and distinct?",
        "scoring": "1-3: cardboard, 4-6: adequate, 7-8: vivid, 9-10: unforgettable",
    },
    "prose_craftsmanship": {
        "description": "Quality of sentence construction, word choice, rhythm",
        "scoring": "1-3: clumsy, 4-6: adequate, 7-8: polished, 9-10: masterful",
    },
    "thematic_resonance": {
        "description": "Does the scene advance or illuminate the theme?",
        "scoring": "1-3: absent, 4-6: present, 7-8: resonant, 9-10: profound",
    },
    "structural_contribution": {
        "description": "Does the scene earn its place in the manuscript?",
        "scoring": "1-3: filler, 4-6: functional, 7-8: essential, 9-10: irreplaceable",
    },
}


class JudgeEvaluator(BaseAgent):
    """LLM-powered evaluation agent with structured rubric scoring.

    Sends prose + rubric to a cloud model for holistic quality assessment.
    Each chapter is scored on 5 dimensions (1-10 each).
    """

    def __init__(
        self,
        router: "ModelRouter",
        role: str = "judge_evaluator",
        rubric_path: str = "config/eval_rubric.yaml",
    ):
        super().__init__(router, role)
        self.rubric = self._load_rubric(rubric_path)

    def _load_rubric(self, rubric_path: str) -> dict:
        """Load evaluation rubric from YAML config."""
        path = Path(rubric_path)
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data.get("rubric", _DEFAULT_RUBRIC)
        return _DEFAULT_RUBRIC

    def _format_context(self, context: dict) -> str:
        """Format prose and rubric into evaluation prompt."""
        prose = context.get("prose", "")
        scene_card = context.get("scene_card", {})

        parts = []

        # Scene context
        if scene_card:
            parts.append("## Scene Context")
            parts.append(f"Chapter: {scene_card.get('chapter_number', '?')}")
            parts.append(f"Structural phase: {scene_card.get('structural_phase', '?')}")
            parts.append(f"POV: {scene_card.get('pov_character', '?')}")
            parts.append(f"Mission: {scene_card.get('mission', '?')}")
            parts.append("")

        # Rubric
        parts.append("## Evaluation Rubric")
        parts.append("Score each dimension from 1-10:\n")
        for dim, info in self.rubric.items():
            parts.append(f"### {dim}")
            parts.append(f"  {info['description']}")
            parts.append(f"  Scale: {info['scoring']}")
            parts.append("")

        # Prose
        parts.append(f"## Prose to Evaluate\n{prose}")

        # Task
        parts.append(
            "## Task\n"
            "Evaluate the prose above using the rubric. Return a JSON object with:\n"
            "- scores: {dimension_name: score (1-10)} for each rubric dimension\n"
            "- feedback: A 2-3 sentence summary of strengths and weaknesses\n"
            "- recommendation: One of 'publish_ready', 'minor_revision', "
            "'major_revision', 'rewrite'\n\n"
            "Return ONLY the JSON object."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        """Parse judge evaluation response."""
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3].strip()

        try:
            result = json.loads(text)
            return self._normalize_result(result, context)
        except json.JSONDecodeError:
            return {
                "scores": {},
                "overall_score": 0.0,
                "feedback": text,
                "recommendation": "major_revision",
            }

    def _normalize_result(self, result: dict, context: dict) -> dict:
        """Ensure consistent output structure."""
        scores = result.get("scores", {})

        # Compute overall score as average of all dimensions
        if scores:
            overall = sum(scores.values()) / len(scores)
        else:
            overall = 0.0

        scene_card = context.get("scene_card", {})

        return {
            "chapter_number": scene_card.get("chapter_number"),
            "scene_number": scene_card.get("scene_number", 1),
            "scores": scores,
            "overall_score": round(overall, 2),
            "feedback": result.get("feedback", ""),
            "recommendation": result.get("recommendation", "major_revision"),
        }

    async def evaluate_chapter(self, context: dict) -> dict:
        """Evaluate a single chapter.

        Args:
            context: {prose: str, scene_card: dict}

        Returns:
            {chapter_number, scores, overall_score, feedback, recommendation}
        """
        result = await self.run_structured(context)

        # If structured parse succeeded, normalize
        if isinstance(result, dict) and "scores" in result:
            return self._normalize_result(result, context)

        # Fallback to non-structured
        return await self.run(context)

    async def evaluate_manuscript(self, chapters: list[dict]) -> dict:
        """Evaluate an entire manuscript chapter by chapter.

        Args:
            chapters: List of {prose, scene_card} dicts.

        Returns:
            {manuscript_score, chapter_scores, dimension_averages, feedback_summary}
        """
        chapter_results = []
        for chapter in chapters:
            result = await self.evaluate_chapter(chapter)
            chapter_results.append(result)

        # Compute aggregates
        if chapter_results:
            scores_list = [r["overall_score"] for r in chapter_results if r.get("overall_score")]
            manuscript_score = sum(scores_list) / len(scores_list) if scores_list else 0.0

            # Per-dimension averages
            dim_totals: dict[str, list[float]] = {}
            for r in chapter_results:
                for dim, score in r.get("scores", {}).items():
                    dim_totals.setdefault(dim, []).append(score)
            dimension_averages = {
                dim: round(sum(vals) / len(vals), 2)
                for dim, vals in dim_totals.items()
            }
        else:
            manuscript_score = 0.0
            dimension_averages = {}

        return {
            "manuscript_score": round(manuscript_score, 2),
            "chapter_scores": [r.get("overall_score", 0) for r in chapter_results],
            "dimension_averages": dimension_averages,
            "chapter_results": chapter_results,
            "feedback_summary": f"Evaluated {len(chapter_results)} chapters. "
            f"Manuscript score: {manuscript_score:.1f}/10.",
        }
