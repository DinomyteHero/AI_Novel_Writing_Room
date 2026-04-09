"""Concept seed compliance validator.

Checks a concept seed JSON for post-workshop protocol compliance. This is
distinct from JSON schema validation (which enforces structural shape) —
the compliance validator checks semantic completeness: has every eleven-
step protocol output been formally addressed, are hooks planted AND
resolved in scene cards, are word counts within target range, etc.

The validator checks the **workshop-native seed format** (with top-level
``subplots``, ``hooks``, ``stress_test_scores``, ``scene_cards``) as
specified in the Ruusan Atonement revision task. Legacy canonical field
names (``subplot_board``, ``hook_map``, ``stress_test_results``) are also
accepted as fallbacks.

Run from the repo root:
    python -m src.concept_workshop.compliance_validator --seed PATH
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Report types
# ---------------------------------------------------------------------------


class CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass
class CheckResult:
    field_path: str
    status: CheckStatus
    message: str


@dataclass
class ValidationReport:
    passed: bool = True
    critical_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, path: str, status: CheckStatus, message: str) -> None:
        self.checks.append(CheckResult(path, status, message))
        if status == CheckStatus.FAIL:
            self.critical_failures.append(f"{path}: {message}")
            self.passed = False
        elif status == CheckStatus.WARN:
            self.warnings.append(f"{path}: {message}")

    def format(self) -> str:
        lines: list[str] = []
        header = "PASS" if self.passed else "FAIL"
        lines.append(f"=== Compliance report: {header} ===")
        lines.append(f"Critical failures: {len(self.critical_failures)}")
        lines.append(f"Warnings:          {len(self.warnings)}")
        lines.append(f"Total checks:      {len(self.checks)}")
        lines.append("")
        if self.critical_failures:
            lines.append("--- Critical failures ---")
            for msg in self.critical_failures:
                lines.append(f"  FAIL  {msg}")
            lines.append("")
        if self.warnings:
            lines.append("--- Warnings ---")
            for msg in self.warnings:
                lines.append(f"  WARN  {msg}")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_CHAPTER_REF_RE = re.compile(r"(?:chapter\s*)?(\d+)", re.IGNORECASE)


def _parse_chapter_ref(ref: Any) -> int | None:
    """Parse a chapter reference into an integer, accepting int or string form."""
    if ref is None:
        return None
    if isinstance(ref, int):
        return ref
    if isinstance(ref, str):
        match = _CHAPTER_REF_RE.search(ref)
        if match:
            return int(match.group(1))
    return None


def _get_subplots(seed: dict) -> list[dict]:
    """Return the seed's subplot list from either naming convention."""
    return seed.get("subplots") or seed.get("subplot_board") or []


def _get_hooks(seed: dict) -> list[dict]:
    """Return the seed's hook list from either naming convention."""
    return seed.get("hooks") or seed.get("hook_map") or []


def _get_stress_scores(seed: dict) -> dict:
    """Return the seed's stress test scores from either naming convention."""
    scores = seed.get("stress_test_scores")
    if scores:
        return scores
    legacy = seed.get("stress_test_results") or {}
    return legacy.get("scores", {})


def _is_supporting_character(char: dict) -> bool:
    """Heuristic: a character is 'supporting' if their role or arc_type flags it."""
    role = (char.get("role") or "").lower()
    arc_type = (char.get("weiland_arc", {}).get("arc_type") or "").lower()
    return (
        "supporting" in role
        or "minor" in arc_type
        or "minor" in role
    )


# ---------------------------------------------------------------------------
# Section checks
# ---------------------------------------------------------------------------


REQUIRED_TOP_LEVEL_FIELDS = [
    "meta",
    "premise",
    "conflict",
    "theme",
    "ensemble_cast",
    "voice_definition",
    "subplots",  # accepts subplot_board fallback
    "hooks",  # accepts hook_map fallback
    "revelation_schedule",
    "scene_cards",
    "terminology_registry",
    "stress_test_scores",  # accepts stress_test_results fallback
]


def _check_top_level_fields(seed: dict, report: ValidationReport) -> None:
    """Every top-level field in the canonical list must be present (accepting fallbacks)."""
    for field_name in REQUIRED_TOP_LEVEL_FIELDS:
        if field_name == "subplots":
            if _get_subplots(seed):
                report.add("subplots", CheckStatus.PASS, "present (or via subplot_board)")
            else:
                report.add("subplots", CheckStatus.FAIL, "missing (no subplots or subplot_board)")
        elif field_name == "hooks":
            if _get_hooks(seed):
                report.add("hooks", CheckStatus.PASS, "present (or via hook_map)")
            else:
                report.add("hooks", CheckStatus.FAIL, "missing (no hooks or hook_map)")
        elif field_name == "stress_test_scores":
            if _get_stress_scores(seed):
                report.add("stress_test_scores", CheckStatus.PASS, "present (or via stress_test_results.scores)")
            else:
                report.add("stress_test_scores", CheckStatus.FAIL, "missing (no stress_test_scores or stress_test_results.scores)")
        else:
            if seed.get(field_name):
                report.add(field_name, CheckStatus.PASS, "present")
            else:
                report.add(field_name, CheckStatus.FAIL, "missing top-level field")


META_REQUIRED = [
    "project_title",
    "project_scope",
    "franchise",
    "canon_status",
    "era",
    "tone",
    "target_word_count",
    "target_chapters",
    "pov_structure",
]


def _check_meta(seed: dict, report: ValidationReport) -> None:
    meta = seed.get("meta") or {}
    for key in META_REQUIRED:
        if not meta.get(key) and meta.get(key) != 0:
            report.add(f"meta.{key}", CheckStatus.FAIL, "missing required meta field")
        else:
            report.add(f"meta.{key}", CheckStatus.PASS, f"value={meta.get(key)!r}")


def _check_premise(seed: dict, report: ValidationReport) -> None:
    premise = seed.get("premise") or {}
    what_if = premise.get("what_if", "")
    if len(what_if) < 50:
        report.add("premise.what_if", CheckStatus.FAIL, f"what_if too short ({len(what_if)} chars, need ≥50)")
    else:
        report.add("premise.what_if", CheckStatus.PASS, f"{len(what_if)} chars")
    if not premise.get("central_dramatic_question"):
        report.add("premise.central_dramatic_question", CheckStatus.FAIL, "missing")
    else:
        report.add("premise.central_dramatic_question", CheckStatus.PASS, "present")
    logline = premise.get("logline", "")
    if not logline:
        report.add("premise.logline", CheckStatus.FAIL, "missing")
    elif len(logline) > 500:
        report.add("premise.logline", CheckStatus.WARN, f"logline is {len(logline)} chars (recommended ≤500)")
    else:
        report.add("premise.logline", CheckStatus.PASS, f"{len(logline)} chars")
    if not premise.get("hook_classification"):
        report.add("premise.hook_classification", CheckStatus.WARN, "missing hook_classification")
    else:
        report.add("premise.hook_classification", CheckStatus.PASS, f"{premise['hook_classification']}")


def _check_conflict(seed: dict, report: ValidationReport) -> None:
    conflict = seed.get("conflict") or {}
    paf = conflict.get("primary_antagonistic_force") or {}
    for key in ("type", "motivation", "escalation"):
        if not paf.get(key):
            report.add(
                f"conflict.primary_antagonistic_force.{key}",
                CheckStatus.FAIL,
                "missing",
            )
        else:
            report.add(
                f"conflict.primary_antagonistic_force.{key}",
                CheckStatus.PASS,
                "present",
            )
    if not paf.get("identity"):
        report.add(
            "conflict.primary_antagonistic_force.identity",
            CheckStatus.WARN,
            "missing identity (allowed for abstract antagonists)",
        )
    secondary = conflict.get("secondary_pressures") or []
    if not secondary:
        report.add("conflict.secondary_pressures", CheckStatus.FAIL, "empty — at least one secondary pressure required")
    else:
        report.add("conflict.secondary_pressures", CheckStatus.PASS, f"{len(secondary)} pressures")
    if not conflict.get("lock_in_mechanism"):
        report.add("conflict.lock_in_mechanism", CheckStatus.FAIL, "missing")
    else:
        report.add("conflict.lock_in_mechanism", CheckStatus.PASS, "present")


def _check_theme(seed: dict, report: ValidationReport) -> None:
    theme = seed.get("theme") or {}
    if not theme.get("thematic_premise"):
        report.add("theme.thematic_premise", CheckStatus.FAIL, "missing")
    else:
        report.add("theme.thematic_premise", CheckStatus.PASS, "present")
    argument = theme.get("thematic_argument", "")
    if len(argument) < 100:
        report.add("theme.thematic_argument", CheckStatus.FAIL, f"too short ({len(argument)} chars, need ≥100)")
    else:
        report.add("theme.thematic_argument", CheckStatus.PASS, f"{len(argument)} chars")
    arc_tests = theme.get("how_each_arc_tests_theme") or {}
    cast = seed.get("ensemble_cast") or []
    if not arc_tests:
        report.add("theme.how_each_arc_tests_theme", CheckStatus.FAIL, "missing entries for each cast member")
    else:
        # Warn if any cast member's name has no entry (allow fuzzy match by substring).
        missing = []
        for char in cast:
            name = char.get("name", "")
            if not any(
                name.lower() in k.lower() or k.lower() in name.lower()
                for k in arc_tests.keys()
            ):
                missing.append(name)
        if missing:
            report.add(
                "theme.how_each_arc_tests_theme",
                CheckStatus.WARN,
                f"no arc-theme entry for: {', '.join(missing)}",
            )
        else:
            report.add(
                "theme.how_each_arc_tests_theme",
                CheckStatus.PASS,
                f"{len(arc_tests)} entries",
            )


def _check_ensemble_cast(seed: dict, report: ValidationReport) -> None:
    cast = seed.get("ensemble_cast") or []
    if not cast:
        report.add("ensemble_cast", CheckStatus.FAIL, "empty")
        return
    for i, char in enumerate(cast):
        name = char.get("name", f"(char #{i})")
        path_prefix = f"ensemble_cast[{i}]"
        # Required sub-fields
        for key in ("name", "role", "age"):
            if not char.get(key):
                report.add(f"{path_prefix}.{key}", CheckStatus.FAIL, f"missing for {name}")
        three_dims = char.get("three_dimensions") or {}
        for key in ("surface", "backstory_inner_demons", "action_under_pressure"):
            if not three_dims.get(key):
                report.add(
                    f"{path_prefix}.three_dimensions.{key}",
                    CheckStatus.FAIL,
                    f"missing for {name}",
                )
        weiland = char.get("weiland_arc") or {}
        for key in ("lie_believed", "ghost", "want", "need", "arc_type"):
            if not weiland.get(key):
                report.add(
                    f"{path_prefix}.weiland_arc.{key}",
                    CheckStatus.FAIL,
                    f"missing for {name}",
                )
        # arc_phase_map is optional — warn (not fail) if a non-supporting
        # character is missing it.
        arc_phase_map = weiland.get("arc_phase_map")
        if not arc_phase_map and not _is_supporting_character(char):
            report.add(
                f"{path_prefix}.weiland_arc.arc_phase_map",
                CheckStatus.WARN,
                f"missing arc_phase_map for main character {name}",
            )
        elif arc_phase_map:
            report.add(
                f"{path_prefix}.weiland_arc.arc_phase_map",
                CheckStatus.PASS,
                f"{len(arc_phase_map)} phases for {name}",
            )


def _check_voice_definition(seed: dict, report: ValidationReport) -> None:
    voice = seed.get("voice_definition") or {}
    if not voice:
        report.add("voice_definition", CheckStatus.FAIL, "missing voice_definition (Step 5)")
        return
    required = ["pov_approach", "prose_register", "reference_authors", "character_voices", "anti_slop_rules", "anti_patterns"]
    for key in required:
        if not voice.get(key):
            report.add(f"voice_definition.{key}", CheckStatus.FAIL, "missing")
        else:
            report.add(
                f"voice_definition.{key}",
                CheckStatus.PASS,
                f"{len(voice[key]) if hasattr(voice[key], '__len__') else 'present'}",
            )
    if voice.get("force_description_guidelines"):
        report.add(
            "voice_definition.force_description_guidelines",
            CheckStatus.PASS,
            "present (optional)",
        )


def _check_hooks_and_scene_cards(seed: dict, report: ValidationReport) -> None:
    """Every hard hook must be planted AND resolved in at least one scene card.
    Every revelation must appear in at least one scene card."""
    hooks = _get_hooks(seed)
    scene_cards = seed.get("scene_cards") or []
    revelations = seed.get("revelation_schedule") or []

    # Collect hook actions across all scene cards
    hook_plants: set[str] = set()
    hook_resolves: set[str] = set()
    scene_revelations: set[str] = set()
    for card in scene_cards:
        for action_entry in card.get("hook_references", []) or []:
            hook_id = action_entry.get("hook_id")
            action = action_entry.get("action")
            if not hook_id:
                continue
            if action == "plant":
                hook_plants.add(hook_id)
            elif action == "resolve":
                hook_resolves.add(hook_id)
        for rev_id in card.get("revelation_references", []) or []:
            scene_revelations.add(rev_id)

    # Check hard hooks — some workshop formats put priority in hook_type
    def _is_hard(hook: dict) -> bool:
        return (
            hook.get("hook_type") == "hard"
            or hook.get("priority") == "hard"
        )

    hard_hook_ids = [h.get("hook_id") for h in hooks if _is_hard(h) and h.get("hook_id")]
    orphaned_plants = [hid for hid in hard_hook_ids if hid not in hook_plants]
    orphaned_resolves = [hid for hid in hard_hook_ids if hid not in hook_resolves]
    if orphaned_plants:
        report.add(
            "hooks",
            CheckStatus.WARN,
            f"hard hooks never planted in any scene card: {', '.join(orphaned_plants)}",
        )
    if orphaned_resolves:
        report.add(
            "hooks",
            CheckStatus.WARN,
            f"hard hooks never resolved in any scene card: {', '.join(orphaned_resolves)}",
        )
    if not orphaned_plants and not orphaned_resolves and hard_hook_ids:
        report.add(
            "hooks",
            CheckStatus.PASS,
            f"all {len(hard_hook_ids)} hard hooks planted and resolved in scene cards",
        )

    # Check revelations
    revelation_ids = [r.get("revelation_id") or r.get("info_id") for r in revelations]
    revelation_ids = [rid for rid in revelation_ids if rid]
    orphaned_rev = [rid for rid in revelation_ids if rid not in scene_revelations]
    if orphaned_rev:
        report.add(
            "revelation_schedule",
            CheckStatus.WARN,
            f"revelations not tied to any scene card: {', '.join(orphaned_rev)}",
        )
    elif revelation_ids:
        report.add(
            "revelation_schedule",
            CheckStatus.PASS,
            f"all {len(revelation_ids)} revelations appear in scene cards",
        )


def _check_scene_cards_coverage(seed: dict, report: ValidationReport) -> None:
    """Scene cards should cover every chapter from 1 to target_chapters."""
    meta = seed.get("meta") or {}
    target_chapters = meta.get("target_chapters")
    scene_cards = seed.get("scene_cards") or []
    if not target_chapters:
        report.add("scene_cards.coverage", CheckStatus.WARN, "no target_chapters set; skipping coverage check")
        return
    chapters_with_cards: set[int] = set()
    for card in scene_cards:
        ch = card.get("chapter_number")
        if isinstance(ch, int):
            chapters_with_cards.add(ch)
    missing = [ch for ch in range(1, target_chapters + 1) if ch not in chapters_with_cards]
    if missing:
        report.add(
            "scene_cards.coverage",
            CheckStatus.FAIL,
            f"chapters missing scene cards: {missing}",
        )
    else:
        report.add(
            "scene_cards.coverage",
            CheckStatus.PASS,
            f"all {target_chapters} chapters covered",
        )

    # Word count check: total scene card word count should be within ±20% of target
    target_word_count = meta.get("target_word_count")
    if target_word_count:
        total = sum(card.get("estimated_word_count", 0) for card in scene_cards)
        deviation = abs(total - target_word_count) / target_word_count
        if deviation > 0.20:
            report.add(
                "scene_cards.word_count",
                CheckStatus.WARN,
                f"total {total} vs target {target_word_count} ({deviation:.1%} deviation, max 20%)",
            )
        else:
            report.add(
                "scene_cards.word_count",
                CheckStatus.PASS,
                f"total {total} vs target {target_word_count} ({deviation:.1%} deviation)",
            )


def _check_terminology(seed: dict, report: ValidationReport) -> None:
    terms = seed.get("terminology_registry") or []
    cast = seed.get("ensemble_cast") or []
    if not terms:
        report.add("terminology_registry", CheckStatus.FAIL, "empty")
        return
    # Accept both term names — canonical_form (workshop) or term (schema)
    term_names = set()
    for entry in terms:
        name = entry.get("canonical_form") or entry.get("term")
        if name:
            term_names.add(name.lower())
    missing = []
    for char in cast:
        char_name = (char.get("name") or "").lower()
        if char_name and char_name not in term_names:
            missing.append(char.get("name"))
    if missing:
        report.add(
            "terminology_registry",
            CheckStatus.WARN,
            f"no terminology entry for characters: {', '.join(missing)}",
        )
    else:
        report.add(
            "terminology_registry",
            CheckStatus.PASS,
            f"{len(terms)} entries, all cast members present",
        )


def _check_stress_test(seed: dict, report: ValidationReport) -> None:
    scores = _get_stress_scores(seed)
    if not scores:
        report.add("stress_test_scores", CheckStatus.FAIL, "missing")
        return
    overall = scores.get("overall")
    if overall is None:
        report.add("stress_test_scores.overall", CheckStatus.FAIL, "missing overall score")
        return
    if overall < 7.0:
        report.add(
            "stress_test_scores.overall",
            CheckStatus.FAIL,
            f"overall score {overall} below 7.0 (pipeline-ready threshold)",
        )
    else:
        report.add(
            "stress_test_scores.overall",
            CheckStatus.PASS,
            f"overall={overall}",
        )
    # Detect legacy 5-dim format and warn
    legacy_keys = {"premise_strength", "hook_coherence", "series_viability"}
    canonical_keys = {"hook_discipline", "thematic_resonance", "conflict_architecture"}
    has_legacy = any(k in scores for k in legacy_keys)
    has_canonical = any(k in scores for k in canonical_keys)
    if has_legacy and not has_canonical:
        report.add(
            "stress_test_scores.format",
            CheckStatus.WARN,
            "legacy 5-dimension stress test format detected — recommend re-scoring under 9-dimension rubric",
        )


# ---------------------------------------------------------------------------
# Main entrypoint
# ---------------------------------------------------------------------------


def validate_concept_seed(seed: dict) -> ValidationReport:
    """Run the full compliance validation suite against a concept seed dict."""
    report = ValidationReport()
    _check_top_level_fields(seed, report)
    _check_meta(seed, report)
    _check_premise(seed, report)
    _check_conflict(seed, report)
    _check_theme(seed, report)
    _check_ensemble_cast(seed, report)
    _check_voice_definition(seed, report)
    _check_hooks_and_scene_cards(seed, report)
    _check_scene_cards_coverage(seed, report)
    _check_terminology(seed, report)
    _check_stress_test(seed, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run concept seed compliance validation.",
    )
    parser.add_argument(
        "--seed",
        type=Path,
        required=True,
        help="Path to the concept seed JSON file",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print all check results (pass and fail); by default only failures and warnings are shown",
    )
    args = parser.parse_args()

    if not args.seed.exists():
        print(f"ERROR: seed file not found: {args.seed}", file=sys.stderr)
        return 1

    seed = json.loads(args.seed.read_text(encoding="utf-8"))
    report = validate_concept_seed(seed)

    print(report.format())
    if args.verbose:
        print("--- All checks ---")
        for check in report.checks:
            marker = {
                CheckStatus.PASS: " OK ",
                CheckStatus.WARN: "WARN",
                CheckStatus.FAIL: "FAIL",
            }[check.status]
            print(f"  [{marker}] {check.field_path}: {check.message}")

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
