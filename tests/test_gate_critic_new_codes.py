"""Tests for the 5 new failure codes in gate_critic."""

import pytest

from src.agents.gate_critic import (
    STRUCTURAL_CODES, VOICE_CODES, POLISH_CODES, ALL_CODES,
    determine_verdict, determine_route,
)


class TestNewFailureCodeSets:
    """Tests that new codes are in the correct sets."""

    def test_character_arc_stall_is_structural(self):
        assert "CHARACTER_ARC_STALL" in STRUCTURAL_CODES

    def test_hook_violation_is_structural(self):
        assert "HOOK_VIOLATION" in STRUCTURAL_CODES

    def test_subplot_drift_is_structural(self):
        assert "SUBPLOT_DRIFT" in STRUCTURAL_CODES

    def test_terminology_drift_is_voice(self):
        assert "TERMINOLOGY_DRIFT" in VOICE_CODES

    def test_voice_definition_violation_is_voice(self):
        assert "VOICE_DEFINITION_VIOLATION" in VOICE_CODES

    def test_all_codes_includes_new(self):
        new_codes = {
            "CHARACTER_ARC_STALL", "HOOK_VIOLATION", "SUBPLOT_DRIFT",
            "TERMINOLOGY_DRIFT", "VOICE_DEFINITION_VIOLATION",
        }
        assert new_codes.issubset(ALL_CODES)

    def test_total_code_count(self):
        """Total should be 19 (14 original + 5 new)."""
        assert len(ALL_CODES) == 19


class TestNewCodeVerdicts:
    """Tests that new codes produce correct verdicts."""

    def test_character_arc_stall_verdict(self):
        codes = [{"code": "CHARACTER_ARC_STALL"}]
        assert determine_verdict(codes) == "fail_structural"

    def test_hook_violation_verdict(self):
        codes = [{"code": "HOOK_VIOLATION"}]
        assert determine_verdict(codes) == "fail_structural"

    def test_subplot_drift_verdict(self):
        codes = [{"code": "SUBPLOT_DRIFT"}]
        assert determine_verdict(codes) == "fail_structural"

    def test_terminology_drift_verdict(self):
        codes = [{"code": "TERMINOLOGY_DRIFT"}]
        assert determine_verdict(codes) == "fail_voice"

    def test_voice_definition_violation_verdict(self):
        codes = [{"code": "VOICE_DEFINITION_VIOLATION"}]
        assert determine_verdict(codes) == "fail_voice"


class TestNewCodeRouting:
    """Tests that new code verdicts route correctly."""

    def test_structural_new_codes_route_to_full_rewrite(self):
        codes = [{"code": "CHARACTER_ARC_STALL"}]
        verdict = determine_verdict(codes)
        assert determine_route(verdict) == "full_rewrite"

    def test_voice_new_codes_route_to_targeted_revision(self):
        codes = [{"code": "TERMINOLOGY_DRIFT"}]
        verdict = determine_verdict(codes)
        assert determine_route(verdict) == "targeted_revision"

    def test_structural_takes_priority_over_voice(self):
        """Structural codes take priority over voice codes."""
        codes = [
            {"code": "HOOK_VIOLATION"},
            {"code": "TERMINOLOGY_DRIFT"},
        ]
        assert determine_verdict(codes) == "fail_structural"
