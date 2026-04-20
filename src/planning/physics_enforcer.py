"""Story physics enforcement layer for the generation pipeline.

Wraps the standalone validators (CausalityChainValidator, RevelationMap,
PromisePayoffLedger, PressureMatrix, SceneEconomics) and provides
pre-chapter, post-chapter, and milestone validation hooks.
"""

from __future__ import annotations

from src.planning.pressure_matrix import PressureMatrix
from src.planning.scene_economics import SceneEconomics
from src.planning.story_physics import (
    CausalityChainValidator,
    PromisePayoffLedger,
    RevelationMap,
)


class PhysicsViolationError(Exception):
    """Raised when strict_mode is enabled and critical physics violations are found."""

    def __init__(self, message: str, violations: list[dict] | None = None):
        super().__init__(message)
        self.violations = violations or []


class PhysicsEnforcer:
    """Validates story physics at key pipeline moments.

    By default advisory-only — produces warnings and recommendations but
    does not block generation. When ``strict_mode=True``, raises
    ``PhysicsViolationError`` for critical issues (missing ``why_now``,
    overdue hard promises).
    """

    # Issue types that indicate a structurally broken plan. These fail the
    # compile-time gate in ``scripts/compile_bundle.py`` under ``--strict``.
    # Non-critical issues surface as warnings only.
    CRITICAL_ISSUE_TYPES: frozenset[str] = frozenset({
        "missing_why_now",
        "generic_why_now",
        "overdue",
        "too_early",
    })

    def __init__(
        self,
        concept_seed: dict,
        scene_cards: list[dict] = None,
        strict_mode: bool = False,
    ):
        physics = concept_seed.get("story_physics", {})
        meta = concept_seed.get("meta", {})

        self.total_chapters = meta.get("target_chapters", 20)
        self.scene_cards = scene_cards or []
        self.strict_mode = strict_mode

        # Initialize validators from story physics data
        self.scene_economics = SceneEconomics()
        self.pressure_matrix = PressureMatrix(
            physics.get("pressure_matrix", {})
        )
        self.promise_ledger = PromisePayoffLedger(
            physics.get("promise_payoff_ledger", [])
        )
        self.causality_validator = CausalityChainValidator(
            physics.get("causality_chains", [])
        )
        self.revelation_map = RevelationMap(
            physics.get("revelation_map", [])
        )

    def validate_pre_chapter(self, scene_card: dict) -> dict:
        """Run before chapter generation.

        Checks:
        - SceneEconomics: does this scene card have a valid why_now?
        - PressureMatrix: is character pressure appropriate?
        - PromisePayoffLedger: are overdue promises being addressed?

        Returns:
            {passed: bool, issues: list[dict], recommendations: list[str]}
        """
        issues = []
        recommendations = []

        # Scene economics — validate why_now
        econ_issues = self.scene_economics.validate_scene_cards([scene_card])
        issues.extend(econ_issues)
        for issue in econ_issues:
            recommendations.append(
                f"Scene {issue['scene_number']} in chapter "
                f"{issue['chapter_number']}: {issue['description']}"
            )

        # Pressure matrix — check POV character pressure
        chapter_num = scene_card.get("chapter_number", 1)
        pov = scene_card.get("pov_character", "")
        if pov:
            pressure = self.pressure_matrix.get_pressure_for_chapter(
                pov, chapter_num
            )
            if pressure and pressure.get("pressure_level", 5) <= 2:
                issues.append({
                    "issue_type": "low_pressure",
                    "character": pov,
                    "chapter": chapter_num,
                    "description": (
                        f"POV character '{pov}' has low pressure "
                        f"(level {pressure['pressure_level']}) at chapter "
                        f"{chapter_num}. Consider raising stakes."
                    ),
                })
                recommendations.append(
                    f"Raise pressure on {pov} — current level is only "
                    f"{pressure['pressure_level']}/10."
                )

        # Promise ledger — check for overdue promises
        promise_issues = self.promise_ledger.check_at_milestone(
            chapter_num, self.total_chapters
        )
        issues.extend(promise_issues)
        for issue in promise_issues:
            recommendations.append(
                f"Consider addressing promise '{issue['promise_id']}': "
                f"{issue['description']}"
            )

        # Strict mode: raise on critical violations
        if self.strict_mode and issues:
            _CRITICAL_TYPES = {"missing_why_now", "generic_why_now", "overdue"}
            critical = [
                i for i in issues if i.get("issue_type") in _CRITICAL_TYPES
            ]
            if critical:
                raise PhysicsViolationError(
                    f"{len(critical)} critical physics violation(s) in "
                    f"chapter {chapter_num}",
                    violations=critical,
                )

        return {
            "passed": len(issues) == 0,
            "issues": issues,
            "recommendations": recommendations,
        }

    def validate_post_chapter(
        self, scene_card: dict, prose: str, chapter_num: int
    ) -> dict:
        """Run after chapter generation.

        Checks:
        - CausalityChain: do events have causes and consequences?
        - RevelationMap: are reveals ordered correctly?

        Returns:
            {passed: bool, issues: list[dict]}
        """
        issues = []

        # Causality validation
        causality_issues = self.causality_validator.validate()
        issues.extend(causality_issues)

        # Revelation ordering
        revelation_issues = self.revelation_map.validate_ordering()
        issues.extend(revelation_issues)

        return {
            "passed": len(issues) == 0,
            "issues": issues,
        }

    def validate_milestone(
        self, milestone_phase: str, chapter_results: list[dict]
    ) -> dict:
        """Run at milestone gates (first_plot_point, midpoint, second_plot_point).

        Combines all validators for a comprehensive phase-specific check.

        Returns:
            {passed: bool, issues: list[dict], summary: str}
        """
        issues = []

        # Run all validators
        causality_issues = self.causality_validator.validate()
        revelation_issues = self.revelation_map.validate_ordering()
        pressure_issues = self.pressure_matrix.validate_escalation()

        current_chapter = len(chapter_results)
        promise_issues = self.promise_ledger.check_at_milestone(
            current_chapter, self.total_chapters
        )

        issues.extend(causality_issues)
        issues.extend(revelation_issues)
        issues.extend(pressure_issues)
        issues.extend(promise_issues)

        summary_parts = []
        if causality_issues:
            summary_parts.append(
                f"{len(causality_issues)} causality issue(s)"
            )
        if revelation_issues:
            summary_parts.append(
                f"{len(revelation_issues)} revelation timing issue(s)"
            )
        if pressure_issues:
            summary_parts.append(
                f"{len(pressure_issues)} pressure escalation issue(s)"
            )
        if promise_issues:
            summary_parts.append(
                f"{len(promise_issues)} overdue promise(s)"
            )

        summary = (
            f"Milestone '{milestone_phase}' at chapter {current_chapter}: "
            + (", ".join(summary_parts) if summary_parts else "all checks passed")
        )

        return {
            "passed": len(issues) == 0,
            "issues": issues,
            "summary": summary,
        }

    @staticmethod
    def validate_chapter_pressure_progression(scene_cards: list[dict]) -> list[dict]:
        """Validate pressure progression within a single chapter's scenes.

        Args:
            scene_cards: All scene cards for ONE chapter, sorted by scene_number.

        Returns:
            List of issue dicts.
        """
        issues: list[dict] = []
        if len(scene_cards) < 2:
            return issues

        ch = scene_cards[0].get("chapter_number", "?")

        # Heuristic pressure scores
        pressure_scores = []
        for card in scene_cards:
            score = PhysicsEnforcer._estimate_scene_pressure(card)
            pressure_scores.append((card.get("scene_number", 0), score))

        # Final scene should not be lowest-pressure
        final_scene, final_pressure = pressure_scores[-1]
        min_pressure = min(p for _, p in pressure_scores)
        max_pressure = max(p for _, p in pressure_scores)
        if final_pressure == min_pressure and final_pressure < max_pressure:
            issues.append({
                "issue_type": "weak_chapter_ending",
                "chapter": ch,
                "description": (
                    f"Chapter {ch}: final scene (scene {final_scene}) has the lowest "
                    f"pressure score ({final_pressure}). The chapter ending should not be "
                    f"the lowest-pressure moment."
                ),
            })

        # All same conflict_type with 3+ scenes
        conflict_types = [c.get("conflict_type") for c in scene_cards]
        if len(set(conflict_types)) == 1 and len(scene_cards) >= 3:
            issues.append({
                "issue_type": "monotone_conflict",
                "chapter": ch,
                "description": (
                    f"Chapter {ch}: all {len(scene_cards)} scenes have conflict_type "
                    f"'{conflict_types[0]}'. Vary conflict types for richer chapters."
                ),
            })

        # Flat pressure (all identical scores)
        scores_only = [p for _, p in pressure_scores]
        if len(set(scores_only)) == 1 and len(scene_cards) >= 3:
            issues.append({
                "issue_type": "flat_pressure",
                "chapter": ch,
                "description": (
                    f"Chapter {ch}: all scenes have identical estimated pressure "
                    f"({scores_only[0]}). Vary intensity across scenes."
                ),
            })

        return issues

    def validate_plan(
        self, scene_cards: list[dict] | None = None
    ) -> dict:
        """Corpus-level plan validation.

        Runs every structural check against the full scene-card set plus
        the story-physics artifacts from the concept seed. Intended to be
        invoked at compile time, before any drafting, so structural
        problems fail the plan rather than the pipeline.

        Returns:
            {
                "passed": bool,              # True iff zero critical issues
                "critical_count": int,
                "warn_count": int,
                "issues": list[dict],        # every issue, flat
                "recommendations": list[str],
                "by_category": {
                    "economics":           [...],
                    "causality":           [...],
                    "revelations":         [...],
                    "promises":            [...],
                    "pressure":            [...],
                    "chapter_progression": [...],
                },
            }
        """
        cards = scene_cards if scene_cards is not None else self.scene_cards

        # Per-card economics (why_now).
        economics_issues = self.scene_economics.validate_scene_cards(cards)

        # Causality graph.
        causality_issues = self.causality_validator.validate()

        # Revelation timing.
        revelation_issues = self.revelation_map.validate_ordering()

        # Promise ledger — plan-time semantics. The milestone check assumes a
        # running book where "unfulfilled" means the draft hasn't paid off
        # yet; at plan time every promise is unfulfilled by definition, so
        # that check would flag all of them. Instead, we check structural
        # completeness: every promise needs a scheduled payoff, and the
        # payoff must land inside the story.
        promise_issues: list[dict] = []
        for p in self.promise_ledger._promises.values():
            pid = p.get("promise_id", "?")
            payoff = p.get("payoff_chapter")
            planted = p.get("planted_chapter")
            if payoff is None:
                if p.get("type") == "chekhov":
                    promise_issues.append({
                        "promise_id": pid,
                        "issue_type": "no_payoff_planned",
                        "description": (
                            f"Chekhov promise '{pid}' has no planned "
                            f"payoff_chapter."
                        ),
                    })
                continue
            if isinstance(payoff, int) and payoff > self.total_chapters:
                promise_issues.append({
                    "promise_id": pid,
                    "issue_type": "overdue",
                    "description": (
                        f"Promise '{pid}' has payoff_chapter {payoff} which "
                        f"exceeds the planned story length "
                        f"({self.total_chapters} chapters)."
                    ),
                })
            if (
                isinstance(payoff, int)
                and isinstance(planted, int)
                and payoff < planted
            ):
                promise_issues.append({
                    "promise_id": pid,
                    "issue_type": "overdue",
                    "description": (
                        f"Promise '{pid}' has payoff_chapter {payoff} "
                        f"scheduled before planted_chapter {planted}."
                    ),
                })

        # Pressure escalation across chapters.
        pressure_issues = self.pressure_matrix.validate_escalation()

        # Per-chapter pressure progression across scenes.
        chapter_progression_issues: list[dict] = []
        by_chapter: dict[int, list[dict]] = {}
        for card in cards:
            ch = card.get("chapter_number")
            if isinstance(ch, int):
                by_chapter.setdefault(ch, []).append(card)
        for ch in sorted(by_chapter):
            scenes_sorted = sorted(
                by_chapter[ch], key=lambda c: c.get("scene_number", 0)
            )
            chapter_progression_issues.extend(
                PhysicsEnforcer.validate_chapter_pressure_progression(
                    scenes_sorted
                )
            )

        by_category = {
            "economics": economics_issues,
            "causality": causality_issues,
            "revelations": revelation_issues,
            "promises": promise_issues,
            "pressure": pressure_issues,
            "chapter_progression": chapter_progression_issues,
        }

        issues: list[dict] = []
        for bucket in by_category.values():
            issues.extend(bucket)

        critical_count = sum(
            1 for i in issues
            if i.get("issue_type") in PhysicsEnforcer.CRITICAL_ISSUE_TYPES
        )
        warn_count = len(issues) - critical_count

        recommendations: list[str] = [
            i["description"] for i in issues if "description" in i
        ]

        return {
            "passed": critical_count == 0,
            "critical_count": critical_count,
            "warn_count": warn_count,
            "issues": issues,
            "recommendations": recommendations,
            "by_category": by_category,
        }

    @staticmethod
    def _estimate_scene_pressure(card: dict) -> int:
        """Heuristic pressure score (1-10) for a scene card."""
        score = 3  # baseline
        ct = card.get("conflict_type", "")
        if ct == "external":
            score += 2
        elif ct == "interpersonal":
            score += 1

        stakes = card.get("stakes", {})
        if stakes.get("external", "").strip():
            score += 2
        if stakes.get("interpersonal", "").strip():
            score += 1
        if stakes.get("personal", "").strip():
            score += 1

        return min(score, 10)
