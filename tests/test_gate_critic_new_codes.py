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
        """Forward Relay v4: CHARACTER_PRESENCE_VIOLATION left the GateCritic
        taxonomy — PresenceChecker is the sole authority at save time.

        Cumulative adjustments from the original taxonomy:
        - Relay v3 (Stage 1h): -1 for WORD_COUNT_VIOLATION
        - Forward Relay v4: -1 for CHARACTER_PRESENCE_VIOLATION

        14 original + 5 Phase 5 + 4 scene card compliance - 1 (WC) - 1 (CPV)
        = 21.
        """
        assert len(ALL_CODES) == 21

    def test_word_count_violation_not_in_all_codes(self):
        """Relay v3 (Stage 1h): word-count enforcement no longer lives in the gate."""
        assert "WORD_COUNT_VIOLATION" not in ALL_CODES

    def test_character_presence_violation_not_in_all_codes(self):
        """Forward Relay v4: GateCritic no longer emits CHARACTER_PRESENCE_VIOLATION.
        PresenceChecker at save time is the sole authority."""
        assert "CHARACTER_PRESENCE_VIOLATION" not in ALL_CODES
        assert "CHARACTER_PRESENCE_VIOLATION" not in STRUCTURAL_CODES


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
