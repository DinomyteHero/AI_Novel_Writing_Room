"""Tests for the concept seed compliance validator."""

import copy
import json
from pathlib import Path

import pytest

from src.concept_workshop.compliance_validator import (
    CheckStatus,
    ValidationReport,
    _iter_extracted_scene_cards,
    derive_slugs_from_path,
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


# ---------------------------------------------------------------------------
# Phase 3 source-of-truth cleanup: extracted scene cards are canonical
# ---------------------------------------------------------------------------


def _minimal_seed_for_extracted_tests() -> dict:
    """Skeleton seed populated only with fields required to exercise the
    hook/coverage checks. Other section checks will fail, but the
    assertions in these tests only inspect the specific checks we care
    about."""
    return {
        "meta": {
            "project_title": "Test Book",
            "project_scope": "single novel",
            "franchise": "Test Franchise",
            "canon_status": "original",
            "era": "present day",
            "tone": "noir",
            "target_word_count": 3000,
            "target_chapters": 2,
            "pov_structure": "third_limited",
        },
        "hooks": [
            {"hook_id": "H01", "hook_type": "hard"},
            {"hook_id": "H02", "hook_type": "hard"},
        ],
        "revelation_schedule": [{"revelation_id": "R01"}],
        "scene_cards": [
            # Embedded workshop card — must be ignored when extracted are found
            {
                "chapter_number": 1,
                "scene_number": 1,
                "pov_character": "Protagonist",
                "hook_references": [{"hook_id": "EMBEDDED_ONLY", "action": "plant"}],
                "estimated_word_count": 1500,
            },
        ],
    }


def _write_extracted_card(dir_path: Path, chapter: int, scene: int, card: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"chapter_{chapter:02d}_scene_{scene:02d}.json").write_text(
        json.dumps(card), encoding="utf-8"
    )


class TestIterExtractedSceneCards:
    """Unit tests for the extracted-cards iterator."""

    def test_returns_empty_when_directory_absent(self, tmp_path):
        assert _iter_extracted_scene_cards("sw", "rb", str(tmp_path)) == []

    def test_loads_every_card_in_sorted_order(self, tmp_path):
        cards_dir = (
            tmp_path / "data" / "franchises" / "sw" / "books" / "rb" / "scene_cards"
        )
        _write_extracted_card(cards_dir, 2, 1, {"chapter_number": 2, "scene_number": 1})
        _write_extracted_card(cards_dir, 1, 1, {"chapter_number": 1, "scene_number": 1})
        _write_extracted_card(cards_dir, 1, 2, {"chapter_number": 1, "scene_number": 2})

        cards = _iter_extracted_scene_cards("sw", "rb", str(tmp_path))
        assert [(c["chapter_number"], c["scene_number"]) for c in cards] == [
            (1, 1),
            (1, 2),
            (2, 1),
        ]

    def test_skips_unparseable_file(self, tmp_path):
        cards_dir = (
            tmp_path / "data" / "franchises" / "sw" / "books" / "rb" / "scene_cards"
        )
        cards_dir.mkdir(parents=True)
        (cards_dir / "good.json").write_text(
            json.dumps({"chapter_number": 1, "scene_number": 1}), encoding="utf-8"
        )
        (cards_dir / "bad.json").write_text("{ not valid", encoding="utf-8")

        cards = _iter_extracted_scene_cards("sw", "rb", str(tmp_path))
        assert len(cards) == 1
        assert cards[0]["chapter_number"] == 1


class TestValidateUsesExtractedCards:
    """End-to-end: validate_concept_seed prefers extracted cards over embedded."""

    def _setup_extracted_cards(self, tmp_path: Path) -> None:
        """Write extracted canonical cards: H01 planted in ch1/sc1 and
        resolved in ch2/sc1; H02 planted in ch2/sc1 but never resolved
        (so the orphan-resolve branch still fires)."""
        cards_dir = (
            tmp_path / "data" / "franchises" / "sw" / "books" / "rb" / "scene_cards"
        )
        _write_extracted_card(
            cards_dir, 1, 1,
            {
                "chapter_number": 1,
                "scene_number": 1,
                "hook_actions": [{"hook_id": "H01", "action": "plant"}],
                "revelations": ["R01"],
                "target_word_count": 1500,
            },
        )
        _write_extracted_card(
            cards_dir, 2, 1,
            {
                "chapter_number": 2,
                "scene_number": 1,
                "hook_actions": [
                    {"hook_id": "H01", "action": "resolve"},
                    {"hook_id": "H02", "action": "plant"},
                ],
                "target_word_count": 1500,
            },
        )

    def test_marks_source_as_extracted_when_directory_present(self, tmp_path):
        self._setup_extracted_cards(tmp_path)
        seed = _minimal_seed_for_extracted_tests()
        report = validate_concept_seed(seed, "sw", "rb", base_dir=str(tmp_path))

        source_checks = [c for c in report.checks if c.field_path == "scene_cards.source"]
        assert len(source_checks) == 1
        assert source_checks[0].status == CheckStatus.PASS
        assert "extracted" in source_checks[0].message

    def test_extracted_hook_plants_are_credited(self, tmp_path):
        """H01 is planted in extracted cards. The validator must not flag
        H01 as an unplanted hook just because the embedded cards list
        a different hook (EMBEDDED_ONLY)."""
        self._setup_extracted_cards(tmp_path)
        seed = _minimal_seed_for_extracted_tests()
        report = validate_concept_seed(seed, "sw", "rb", base_dir=str(tmp_path))

        # H01 is planted in extracted cards → no "never planted" warning for H01
        plant_warnings = [w for w in report.warnings if "never planted" in w]
        assert not any("H01" in w for w in plant_warnings)
        # EMBEDDED_ONLY (from the embedded cards) must NOT be canonical
        assert not any("EMBEDDED_ONLY" in w for w in plant_warnings)

    def test_extracted_coverage_honoured(self, tmp_path):
        """Two extracted cards covering chapters 1 and 2 satisfy target_chapters=2."""
        self._setup_extracted_cards(tmp_path)
        seed = _minimal_seed_for_extracted_tests()
        report = validate_concept_seed(seed, "sw", "rb", base_dir=str(tmp_path))

        coverage = [c for c in report.checks if c.field_path == "scene_cards.coverage"]
        assert coverage and coverage[0].status == CheckStatus.PASS

    def test_extracted_target_word_count_used(self, tmp_path):
        """Extracted cards carry ``target_word_count``; embedded cards carry
        ``estimated_word_count``. Coverage should sum the extracted field."""
        self._setup_extracted_cards(tmp_path)
        seed = _minimal_seed_for_extracted_tests()
        report = validate_concept_seed(seed, "sw", "rb", base_dir=str(tmp_path))

        wc_checks = [c for c in report.checks if c.field_path == "scene_cards.word_count"]
        # 2 extracted cards * 1500 = 3000 target; deviation = 0% → PASS
        assert wc_checks and wc_checks[0].status == CheckStatus.PASS


class TestValidateFallsBackToEmbedded:
    """When extracted cards are unavailable, fall back to embedded with a WARN."""

    def test_warns_when_franchise_path_missing(self, tmp_path):
        seed = _minimal_seed_for_extracted_tests()
        report = validate_concept_seed(seed, "sw", "rb", base_dir=str(tmp_path))

        source_checks = [c for c in report.checks if c.field_path == "scene_cards.source"]
        assert source_checks[0].status == CheckStatus.WARN
        assert "falling back" in source_checks[0].message

    def test_embedded_hook_still_credited_in_fallback(self, tmp_path):
        """In fallback mode, embedded EMBEDDED_ONLY hook is treated as planted."""
        seed = _minimal_seed_for_extracted_tests()
        # Register a hard hook that matches the embedded card so the
        # plant/resolve bookkeeping has something to correlate.
        seed["hooks"].append({"hook_id": "EMBEDDED_ONLY", "hook_type": "hard"})
        report = validate_concept_seed(seed, "sw", "rb", base_dir=str(tmp_path))

        plant_warnings = [w for w in report.warnings if "never planted" in w]
        assert not any("EMBEDDED_ONLY" in w for w in plant_warnings)

    def test_no_identifiers_keeps_legacy_embedded_behaviour(self):
        """Legacy API (no franchise/book) still works and reads embedded cards."""
        seed = _minimal_seed_for_extracted_tests()
        seed["hooks"].append({"hook_id": "EMBEDDED_ONLY", "hook_type": "hard"})
        report = validate_concept_seed(seed)

        # No scene_cards.source annotation is produced in the legacy path
        source_checks = [c for c in report.checks if c.field_path == "scene_cards.source"]
        assert source_checks == []


class TestExtractedSchemaFieldAliases:
    """Extracted cards use `hook_actions` / `revelations`; embedded use
    `hook_references` / `revelation_references`. The validator must accept both."""

    def test_extracted_hook_actions_recognised(self, tmp_path):
        cards_dir = (
            tmp_path / "data" / "franchises" / "sw" / "books" / "rb" / "scene_cards"
        )
        _write_extracted_card(
            cards_dir, 1, 1,
            {
                "chapter_number": 1,
                "scene_number": 1,
                "hook_actions": [{"hook_id": "H01", "action": "plant"}],
                "target_word_count": 1500,
            },
        )
        _write_extracted_card(
            cards_dir, 2, 1,
            {
                "chapter_number": 2,
                "scene_number": 1,
                "hook_actions": [{"hook_id": "H01", "action": "resolve"}],
                "target_word_count": 1500,
            },
        )
        seed = _minimal_seed_for_extracted_tests()
        seed["hooks"] = [{"hook_id": "H01", "hook_type": "hard"}]
        report = validate_concept_seed(seed, "sw", "rb", base_dir=str(tmp_path))

        hook_passes = [
            c for c in report.checks
            if c.field_path == "hooks" and c.status == CheckStatus.PASS
        ]
        assert hook_passes

    def test_extracted_revelations_recognised(self, tmp_path):
        cards_dir = (
            tmp_path / "data" / "franchises" / "sw" / "books" / "rb" / "scene_cards"
        )
        _write_extracted_card(
            cards_dir, 1, 1,
            {
                "chapter_number": 1,
                "scene_number": 1,
                "revelations": ["R01"],
                "target_word_count": 1500,
            },
        )
        _write_extracted_card(
            cards_dir, 2, 1,
            {
                "chapter_number": 2,
                "scene_number": 1,
                "target_word_count": 1500,
            },
        )
        seed = _minimal_seed_for_extracted_tests()
        report = validate_concept_seed(seed, "sw", "rb", base_dir=str(tmp_path))

        rev_passes = [
            c for c in report.checks
            if c.field_path == "revelation_schedule" and c.status == CheckStatus.PASS
        ]
        assert rev_passes


class TestCosmologyIdOptionalField:
    """Phase 2: meta.cosmology_id is optional and additive. Seeds with or
    without it must validate identically (compliance validator treats it as
    an optional metadata field — like series_id)."""

    def test_ruusan_seed_without_cosmology_still_passes(self, ruusan_seed):
        """Back-compat: existing seed has no cosmology_id, validation unchanged."""
        seed = copy.deepcopy(ruusan_seed)
        assert "cosmology_id" not in seed.get("meta", {})
        report = validate_concept_seed(seed)
        assert report.passed is True
        assert report.critical_failures == []

    def test_seed_with_cosmology_id_still_passes(self, ruusan_seed):
        """Adding optional meta.cosmology_id does not introduce new failures."""
        seed = copy.deepcopy(ruusan_seed)
        seed["meta"]["cosmology_id"] = "the-cosmere"
        report = validate_concept_seed(seed)
        assert report.passed is True
        assert report.critical_failures == []


class TestDeriveSlugsFromPath:
    """Phase 0: the shared path-to-slugs helper used by both the standalone
    compliance validator CLI and ``src/main.py --validate-seed``."""

    def test_franchise_layout_returns_both_slugs(self, tmp_path):
        seed_path = (
            tmp_path / "data" / "franchises" / "sw-legends" / "books"
            / "ruusan" / "concept_seed.json"
        )
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text("{}", encoding="utf-8")

        assert derive_slugs_from_path(seed_path) == ("sw-legends", "ruusan")

    def test_flat_project_layout_returns_nones(self, tmp_path):
        seed_path = tmp_path / "data" / "projects" / "solo-project" / "concept_seed.json"
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text("{}", encoding="utf-8")

        assert derive_slugs_from_path(seed_path) == (None, None)

    def test_unrelated_path_returns_nones(self, tmp_path):
        seed_path = tmp_path / "some" / "other" / "place" / "seed.json"
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text("{}", encoding="utf-8")

        assert derive_slugs_from_path(seed_path) == (None, None)

    def test_missing_segment_after_franchises_returns_nones(self, tmp_path):
        # A path with "franchises" but no "books" marker must not misinfer.
        seed_path = tmp_path / "data" / "franchises" / "sw-legends" / "concept_seed.json"
        seed_path.parent.mkdir(parents=True, exist_ok=True)
        seed_path.write_text("{}", encoding="utf-8")

        assert derive_slugs_from_path(seed_path) == (None, None)
