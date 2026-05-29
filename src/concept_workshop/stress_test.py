"""StressTestRunner — adversarial stress test for concept seeds.

Step 10 of the expanded concept workshop. Runs structural, character,
hook, and series stress tests against a concept seed, returning scored
results with flagged issues.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class StressTestRunner:
    """Runs adversarial stress tests against a concept seed."""

    # 9-dimension stress test keyset (workshop-native format).
    # Two dimensions are nullable: lore_and_continuity (franchise fiction only)
    # and series_coherence (series books only).
    DIMENSIONS = [
        "structural_integrity",
        "character_depth",
        "hook_discipline",
        "thematic_resonance",
        "conflict_architecture",
        "pacing_and_proportion",
        "lore_and_continuity",
        "world_building_coherence",
        "series_coherence",
    ]

    def __init__(self, router=None):
        """Initialize with optional model router for LLM-based testing."""
        self.router = router

    async def run(self, concept_seed: dict) -> dict:
        """Run the full adversarial stress test.

        If a router is available, uses LLM for deeper analysis.
        Otherwise, runs rule-based checks only.

        Returns structured stress test results.
        """
        issues = []

        # Rule-based structural checks
        issues.extend(self._check_structural(concept_seed))
        issues.extend(self._check_characters(concept_seed))
        issues.extend(self._check_hooks(concept_seed))
        issues.extend(self._check_series(concept_seed))

        # LLM-based stress test (if router available)
        llm_scores = None
        llm_issues = []
        if self.router:
            llm_result = await self._run_llm_stress_test(concept_seed)
            if llm_result:
                llm_scores = llm_result.get("scores")
                llm_issues = llm_result.get("flagged_issues", [])
                issues.extend(llm_issues)

        # Compute scores
        scores = llm_scores or self._compute_rule_scores(concept_seed, issues)

        return self.format_results(scores, issues)

    def _check_structural(self, seed: dict) -> list[str]:
        """Rule-based structural stress tests."""
        issues = []
        structure = seed.get("structural_notes", {}).get("brooks_alignment", {})

        if not structure:
            issues.append("No Brooks alignment defined — structure may be undefined")
        else:
            if not structure.get("midpoint"):
                issues.append("Midpoint is undefined — the story may lack a pivot")
            if not structure.get("second_plot_point"):
                issues.append("Second plot point is undefined — transition to resolution unclear")

        conflict = seed.get("conflict", {})
        antagonist = conflict.get("primary_antagonistic_force", {})
        if not antagonist.get("escalation"):
            issues.append("Antagonist escalation is missing — conflict may be flat")

        return issues

    def _check_characters(self, seed: dict) -> list[str]:
        """Rule-based character stress tests."""
        issues = []
        cast = seed.get("ensemble_cast", [])

        if len(cast) < 2:
            issues.append("Cast has fewer than 2 characters — limited perspective")

        # Check for Weiland arcs on POV characters
        pov_chars_without_arc = []
        lies_seen = []
        for char in cast:
            arc = char.get("weiland_arc")
            if arc:
                lie = arc.get("lie_believed", "").strip().lower()
                if lie and lie in lies_seen:
                    issues.append(
                        f"Characters share the same Lie: '{arc.get('lie_believed')}' — "
                        f"their arcs should test this belief differently"
                    )
                elif lie:
                    lies_seen.append(lie)

                # Verify lie and need are logically opposed
                need = arc.get("need", "").strip().lower()
                if lie and need and lie == need:
                    issues.append(
                        f"Character '{char['name']}': lie_believed and need are identical — "
                        f"they must be logically opposed"
                    )
            else:
                pov_chars_without_arc.append(char.get("name", "unnamed"))

        if pov_chars_without_arc:
            issues.append(
                f"Characters without Weiland arc: {', '.join(pov_chars_without_arc)}"
            )

        return issues

    def _check_hooks(self, seed: dict) -> list[str]:
        """Rule-based hook stress tests.

        Uses the workshop-native 'hooks' format. The 'hook_type' field carries
        the priority (hard/soft/series).
        """
        issues = []
        hooks = seed.get("hooks") or []

        if not hooks:
            return issues  # No hooks defined yet — not necessarily an error

        hard_hooks = [h for h in hooks if h.get("hook_type") == "hard"]
        target_chapters = seed.get("meta", {}).get("target_chapters", 25)
        budget = max(1, target_chapters // 3)

        if len(hard_hooks) > budget:
            issues.append(
                f"Too many hard hooks ({len(hard_hooks)}) for {target_chapters} chapters "
                f"(budget: {budget}). Reader may lose track."
            )

        # Check hard hooks have payoff chapters
        for hook in hard_hooks:
            if not hook.get("resolved_in"):
                issues.append(
                    f"Hard hook '{hook.get('hook_id')}' has no planned payoff chapter"
                )

        return issues

    def _check_series(self, seed: dict) -> list[str]:
        """Rule-based series stress tests (only if series scope)."""
        issues = []
        scope = seed.get("meta", {}).get("project_scope")
        if scope != "planned_series":
            return issues

        # These checks apply when series data is embedded in concept seed
        series = seed.get("meta", {}).get("series", {})
        if not series:
            issues.append("Project scope is planned_series but no series metadata found")

        return issues

    def _compute_rule_scores(
        self, seed: dict, issues: list[str]
    ) -> dict[str, float | None]:
        """Compute heuristic scores across all 9 canonical dimensions.

        Inapplicable dimensions return None:
        - lore_and_continuity: None for original-setting projects
        - series_coherence: None for standalone projects
        """
        base = 8.0  # Start optimistic
        penalty_per_issue = 0.5

        def _count(keywords: list[str]) -> int:
            return sum(
                1 for i in issues
                if any(k in i.lower() for k in keywords)
            )

        structural_issues = _count(["structure", "midpoint", "plot point", "escalation"])
        character_issues = _count(["character", "cast", "lie", "arc", "need"])
        hook_issues = _count(["hook", "payoff", "budget"])
        thematic_issues = _count(["theme", "thematic"])
        conflict_issues = _count(["antagonist", "conflict", "stakes", "lock"])
        pacing_issues = _count(["pacing", "proportion", "rhythm"])
        lore_issues = _count(["lore", "canon", "continuity", "timeline"])
        world_issues = _count(["world", "setting", "geography", "logistic"])
        series_issues = _count(["series", "book"])

        # Dimension applicability heuristics
        meta = seed.get("meta", {}) or {}
        canon_status = (meta.get("canon_status") or "").lower()
        is_franchise = bool(meta.get("franchise")) and "original" not in canon_status
        scope = meta.get("project_scope", "standalone")
        is_series = scope in ("planned_series", "continuation")

        def _score(n: int) -> float:
            return max(1.0, base - n * penalty_per_issue)

        return {
            "structural_integrity": _score(structural_issues),
            "character_depth": _score(character_issues),
            "hook_discipline": _score(hook_issues),
            "thematic_resonance": _score(thematic_issues),
            "conflict_architecture": _score(conflict_issues),
            "pacing_and_proportion": _score(pacing_issues),
            "lore_and_continuity": _score(lore_issues) if is_franchise else None,
            "world_building_coherence": _score(world_issues),
            "series_coherence": _score(series_issues) if is_series else None,
        }

    async def _run_llm_stress_test(self, concept_seed: dict) -> dict | None:
        """Run LLM-based stress test using the model router."""
        try:
            prompt_path = Path("prompts/stress_test_prompt.md")
            if prompt_path.exists():
                system_prompt = prompt_path.read_text(encoding="utf-8")
            else:
                system_prompt = "You are an adversarial concept evaluator."

            dim_list = ", ".join(self.DIMENSIONS)
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Evaluate this concept seed. Return JSON with 'scores' "
                        f"(9 dimensions: {dim_list}, plus 'overall' — each 1-10, "
                        f"or null for inapplicable dimensions) and 'flagged_issues' "
                        f"(array of strings).\n\n"
                        f"```json\n{json.dumps(concept_seed, indent=2)}\n```"
                    ),
                },
            ]
            result = await self.router.complete_structured("stress_test", messages)
            return result
        except Exception as e:
            logger.warning("LLM stress test failed: %s", e)
            return None

    def format_results(
        self,
        scores: dict[str, float | None],
        issues: list[str],
    ) -> dict:
        """Format stress test results for inclusion in concept seed.

        Automatically computes the 'overall' score as the mean of non-null
        dimension values (excluding the 'overall' key itself if present).
        """
        # Compute overall if not already supplied by the LLM.
        if "overall" not in scores or scores.get("overall") is None:
            values = [
                v for k, v in scores.items()
                if k != "overall" and isinstance(v, (int, float))
            ]
            overall = sum(values) / len(values) if values else 0.0
            scores = {**scores, "overall": round(overall, 2)}
        return {
            "scores": scores,
            "flagged_issues": issues,
            "human_approved": False,
            "approval_timestamp": None,
        }

    def score(self, results: dict) -> float:
        """Compute overall score (average of non-null dimension scores).

        Excludes the 'overall' key itself to avoid double-counting when the
        scores dict has been pre-populated by format_results.
        """
        scores = results.get("scores", {})
        if not scores:
            return 0.0
        values = [
            v for k, v in scores.items()
            if k != "overall" and isinstance(v, (int, float))
        ]
        return sum(values) / len(values) if values else 0.0
