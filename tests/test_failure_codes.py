"""Tests for failure code routing logic."""

import pytest

from src.agents.gate_critic import (
    ALL_CODES,
    POLISH_CODES,
    STRUCTURAL_CODES,
    VOICE_CODES,
    determine_route,
    determine_verdict,
)


class TestFailureCodeClassification:
    """Test that failure codes are correctly classified."""

    def test_structural_codes_exist(self):
        assert "CONTINUITY_CONTRADICTION" in STRUCTURAL_CODES
        assert "WEAK_TURNING_POINT" in STRUCTURAL_CODES
        assert "MISSING_TURNING_POINT" in STRUCTURAL_CODES
        assert "UNEARNED_RESOLUTION" in STRUCTURAL_CODES
        assert "STRUCTURAL_PHASE_VIOLATION" in STRUCTURAL_CODES
        assert "PROMISE_BROKEN" in STRUCTURAL_CODES
        assert "MOTIVATION_GAP" in STRUCTURAL_CODES

    def test_voice_codes_exist(self):
        assert "OOC_DIALOGUE" in VOICE_CODES
        assert "OOC_ACTION" in VOICE_CODES
        assert "TELLING_NOT_SHOWING" in VOICE_CODES

    def test_polish_codes_exist(self):
        assert "EXPOSITION_LEAK" in POLISH_CODES
        assert "PACING_FLATLINE" in POLISH_CODES
        assert "PROSE_CLICHE_BURST" in POLISH_CODES

    def test_canon_violation_is_structural(self):
        """CANON_VIOLATION was promoted from polish to structural."""
        assert "CANON_VIOLATION" in STRUCTURAL_CODES
        assert "CANON_VIOLATION" not in POLISH_CODES

    def test_no_overlap_between_categories(self):
        assert not (STRUCTURAL_CODES & VOICE_CODES)
        assert not (STRUCTURAL_CODES & POLISH_CODES)
        assert not (VOICE_CODES & POLISH_CODES)

    def test_all_codes_is_union(self):
        assert ALL_CODES == STRUCTURAL_CODES | VOICE_CODES | POLISH_CODES


class TestVerdictDetermination:
    """Test verdict logic from failure codes."""

    def test_no_failures_is_pass(self):
        assert determine_verdict([]) == "pass"

    def test_structural_failure_overrides_all(self):
        failures = [
            {"code": "CONTINUITY_CONTRADICTION"},
            {"code": "OOC_DIALOGUE"},
            {"code": "PACING_FLATLINE"},
        ]
        assert determine_verdict(failures) == "fail_structural"

    def test_voice_failure_overrides_polish(self):
        failures = [
            {"code": "OOC_DIALOGUE"},
            {"code": "PACING_FLATLINE"},
        ]
        assert determine_verdict(failures) == "fail_voice"

    def test_polish_only(self):
        failures = [
            {"code": "PACING_FLATLINE"},
            {"code": "PROSE_CLICHE_BURST"},
        ]
        assert determine_verdict(failures) == "fail_polish"

    def test_single_structural_code(self):
        failures = [{"code": "WEAK_TURNING_POINT"}]
        assert determine_verdict(failures) == "fail_structural"

    def test_single_voice_code(self):
        failures = [{"code": "TELLING_NOT_SHOWING"}]
        assert determine_verdict(failures) == "fail_voice"


class TestRouteMapping:
    """Test verdict-to-route mapping."""

    def test_pass_routes_nowhere(self):
        assert determine_route("pass") is None

    def test_structural_routes_to_full_rewrite(self):
        assert determine_route("fail_structural") == "full_rewrite"

    def test_voice_routes_to_targeted_revision(self):
        assert determine_route("fail_voice") == "targeted_revision"

    def test_polish_routes_nowhere(self):
        """Post-Phase 1 pipeline redesign: fail_polish does NOT trigger a rewrite.
        Polish issues are caught by the compression guard and Final Gate, which
        reject the polish and keep the gate-passed draft."""
        assert determine_route("fail_polish") is None
