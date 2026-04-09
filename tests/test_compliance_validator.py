"""Tests for the concept seed compliance validator."""

import copy

import pytest

from src.concept_workshop.compliance_validator import (
    CheckStatus,
    ValidationReport,
    validate_concept_seed,
)


class TestHappyPath:
    """The installed Ruusan seed should pass validation cleanly."""

    def test_complete_seed_passes_validation(self, ruusan_seed):
        """A complete, properly enriched concept seed passes with no critical failures."""
        report = validate_concept_seed(ruusan_seed)
        assert report.passed is True, (
            f"Expected Ruusan seed to pass; got failures: {report.critical_failures}"
        )
        assert report.critical_failures == []

    def test_validation_produces_check_results(self, ruusan_seed):
        """The report lists individual check results, not just a bool."""
        report = validate_concept_seed(ruusan_seed)
        assert len(report.checks) > 20
        # Confirm at least one PASS exists for each major section
        paths = {c.field_path for c in report.checks if c.status == CheckStatus.PASS}
        assert any(p.startswith("meta.") for p in paths)
        assert any(p.startswith("premise.") for p in paths)
        assert any(p.startswith("theme.") for p in paths)
        assert any(p.startswith("voice_definition.") for p in paths)


class TestMissingTopLevelFields:
    """Missing required top-level fields must be flagged as critical."""

    def test_missing_top_level_field_flagged(self, ruusan_seed):
        """Removing any required top-level field produces a critical failure."""
        seed = copy.deepcopy(ruusan_seed)
        del seed["voice_definition"]
        report = validate_concept_seed(seed)
        assert report.passed is False
        assert any("voice_definition" in f for f in report.critical_failures)

    def test_missing_voice_definition_is_critical(self, ruusan_seed):
        """The lesson of the Ruusan workshop: a missing voice_definition is a hard fail."""
        seed = copy.deepcopy(ruusan_seed)
        del seed["voice_definition"]
        report = validate_concept_seed(seed)
        assert report.passed is False
        voice_fails = [f for f in report.critical_failures if "voice_definition" in f]
        assert len(voice_fails) >= 1

    def test_missing_subplots_is_critical(self, ruusan_seed):
        """Missing 'subplots' top-level field is a critical failure."""
        seed = copy.deepcopy(ruusan_seed)
        del seed["subplots"]
        report = validate_concept_seed(seed)
        assert report.passed is False
        assert any("subplots" in f for f in report.critical_failures)


class TestHookAndRevelationResolution:
    """Orphaned hooks and revelations are warnings, not critical failures."""

    def test_orphaned_hard_hook_is_warning(self, ruusan_seed):
        """A hard hook with no 'resolve' action in any scene card is a warning."""
        seed = copy.deepcopy(ruusan_seed)
        # Strip all hook_actions from scene cards so every hard hook becomes orphaned
        for card in seed["scene_cards"]:
            card["hook_references"] = []
        report = validate_concept_seed(seed)
        # Should still PASS overall (orphaned hooks are warnings)
        assert report.passed is True
        assert any("hard hooks never" in w for w in report.warnings)


class TestWordCount:
    """Scene card word count must be within ±20% of meta.target_word_count."""

    def test_word_count_out_of_range_flagged_as_warning(self, ruusan_seed):
        """A target word count 10× larger than scene card totals triggers a warning."""
        seed = copy.deepcopy(ruusan_seed)
        # Current target is 100000. Bump it so scene card total is ~50% off.
        seed["meta"]["target_word_count"] = 200000
        report = validate_concept_seed(seed)
        wc_warnings = [w for w in report.warnings if "word_count" in w]
        assert len(wc_warnings) >= 1, (
            f"Expected a word count warning; got warnings: {report.warnings}"
        )


class TestStressTestThreshold:
    """Stress test overall score <7.0 is a critical failure."""

    def test_stress_test_below_7_is_critical(self, ruusan_seed):
        """Setting overall=6.5 causes validation to fail."""
        seed = copy.deepcopy(ruusan_seed)
        seed["stress_test_scores"]["overall"] = 6.5
        report = validate_concept_seed(seed)
        assert report.passed is False
        assert any("overall score 6.5 below 7.0" in f for f in report.critical_failures)

    def test_stress_test_at_exactly_7_passes(self, ruusan_seed):
        """Overall=7.0 (the threshold) passes."""
        seed = copy.deepcopy(ruusan_seed)
        seed["stress_test_scores"]["overall"] = 7.0
        report = validate_concept_seed(seed)
        # Other checks must still pass too, but the stress test specifically is PASS
        stress_checks = [c for c in report.checks if c.field_path == "stress_test_scores.overall"]
        assert any(c.status == CheckStatus.PASS for c in stress_checks)

class TestArcPhaseMap:
    """arc_phase_map absence on main characters is a warning; on supporting it's a pass."""

    def test_arc_phase_map_missing_for_main_character_is_warning(self, ruusan_seed):
        """Removing Ben's arc_phase_map produces a warning (not a failure)."""
        seed = copy.deepcopy(ruusan_seed)
        for char in seed["ensemble_cast"]:
            if char["name"] == "Ben Skywalker":
                char["weiland_arc"].pop("arc_phase_map", None)
                break
        report = validate_concept_seed(seed)
        # Overall still passes
        assert report.passed is True
        assert any(
            "arc_phase_map" in w and "Ben Skywalker" in w
            for w in report.warnings
        )

    def test_arc_phase_map_missing_for_supporting_character_is_pass(self, ruusan_seed):
        """Desh Rolan has a 'minor positive' arc — missing arc_phase_map is fine."""
        # Confirm Desh lacks arc_phase_map in the fixture
        desh = next(
            c for c in ruusan_seed["ensemble_cast"]
            if c["name"] == "Desh Rolan"
        )
        assert "arc_phase_map" not in desh.get("weiland_arc", {})
        # The validation should NOT warn about Desh's missing arc_phase_map
        report = validate_concept_seed(ruusan_seed)
        desh_arc_warnings = [
            w for w in report.warnings
            if "Desh Rolan" in w and "arc_phase_map" in w
        ]
        assert desh_arc_warnings == []


class TestReportFormat:
    """The ValidationReport.format() method produces a human-readable string."""

    def test_format_reports_pass_or_fail_header(self, ruusan_seed):
        """Formatted report starts with a PASS or FAIL header."""
        report = validate_concept_seed(ruusan_seed)
        formatted = report.format()
        assert formatted.startswith("=== Compliance report:")
        assert "PASS" in formatted or "FAIL" in formatted

    def test_format_lists_warnings_when_present(self, ruusan_seed):
        """Warnings section appears when there are any warnings."""
        seed = copy.deepcopy(ruusan_seed)
        seed["meta"]["target_word_count"] = 200000  # triggers a word count warning
        report = validate_concept_seed(seed)
        formatted = report.format()
        assert "Warnings" in formatted
