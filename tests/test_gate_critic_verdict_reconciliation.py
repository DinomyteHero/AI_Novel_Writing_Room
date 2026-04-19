"""Tests for GateCritic.run() verdict/failure_codes reconciliation.

The model's stated verdict is never trusted for routing — verdict, route, and
severity are always derived from `failure_codes`. These tests cover the
contract inconsistency where a model could return `verdict="pass"` alongside
a STRUCTURAL_CODES entry and cause the orchestrator to skip the rewrite loop.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.gate_critic import GateCritic


def _make_context() -> dict:
    """Minimal context for GateCritic.run() — the mock router ignores it."""
    return {
        "prose": "sample prose",
        "scene_card": {"chapter_number": 1, "scene_number": 1},
        "bible_summary": "",
    }


async def _run_with_model_result(model_result: dict) -> dict:
    router = MagicMock()
    router.complete_structured = AsyncMock(return_value=model_result)
    critic = GateCritic(router)
    return await critic.run(_make_context())


class TestVerdictReconciliation:
    async def test_model_pass_with_structural_code_overridden_to_fail_structural(self):
        """The core bug: `verdict="pass"` + structural code must route to full rewrite."""
        result = await _run_with_model_result({
            "verdict": "pass",
            "failure_codes": [
                {"code": "WEAK_TURNING_POINT", "location": "para 3",
                 "description": "turn lands in two beats", "fix_hint": "build resistance"},
            ],
            "structural_score": 0.75,
            "voice_score": 0.80,
            "polish_score": 0.80,
        })

        assert result["verdict"] == "fail_structural"
        assert result["route_to"] == "full_rewrite"
        assert result["severity"] == "blocking"
        assert len(result["failure_codes"]) == 1

    async def test_model_fail_polish_with_structural_code_overridden(self):
        """Fail_polish + structural code still escalates to fail_structural."""
        result = await _run_with_model_result({
            "verdict": "fail_polish",
            "failure_codes": [
                {"code": "HOOK_VIOLATION", "location": "end",
                 "description": "hook not planted", "fix_hint": "plant H01"},
                {"code": "PACING_FLATLINE", "location": "middle",
                 "description": "sentence lengths uniform", "fix_hint": "vary cadence"},
            ],
            "structural_score": 0.70,
            "voice_score": 0.85,
            "polish_score": 0.70,
        })

        assert result["verdict"] == "fail_structural"
        assert result["route_to"] == "full_rewrite"

    async def test_empty_codes_returns_pass_regardless_of_model_verdict(self):
        """No codes means no actionable issue — verdict must be pass."""
        result = await _run_with_model_result({
            "verdict": "fail_polish",
            "failure_codes": [],
            "structural_score": 0.90,
            "voice_score": 0.90,
            "polish_score": 0.90,
        })

        assert result["verdict"] == "pass"
        assert result["route_to"] is None
        assert result["severity"] == "non_blocking"

    async def test_unknown_failure_code_is_dropped(self, capsys):
        """Codes not in ALL_CODES are filtered out with a log message."""
        result = await _run_with_model_result({
            "verdict": "fail_polish",
            "failure_codes": [
                {"code": "MADE_UP_CODE", "location": "para 1",
                 "description": "bogus", "fix_hint": "n/a"},
                {"code": "PACING_FLATLINE", "location": "middle",
                 "description": "real issue", "fix_hint": "vary it"},
            ],
        })

        codes = [fc["code"] for fc in result["failure_codes"]]
        assert codes == ["PACING_FLATLINE"]
        assert result["verdict"] == "fail_polish"

        captured = capsys.readouterr()
        assert "MADE_UP_CODE" in captured.out
        assert "dropping unknown failure_code" in captured.out

    async def test_verdict_disagreement_is_logged(self, capsys):
        """Model verdict vs derived verdict disagreement is surfaced in output."""
        await _run_with_model_result({
            "verdict": "pass",
            "failure_codes": [{"code": "MOTIVATION_GAP", "location": "para 2",
                               "description": "x", "fix_hint": "y"}],
        })

        captured = capsys.readouterr()
        assert "overridden" in captured.out
        assert "pass" in captured.out
        assert "fail_structural" in captured.out


class TestBenignCases:
    """Sanity checks: when model and derived verdict agree, no spurious logs."""

    async def test_no_disagreement_log_when_verdicts_match(self, capsys):
        """When model verdict matches the derived verdict, no override log fires.

        Pre-v3 this used WORD_COUNT_VIOLATION (a polish code) to exercise the
        fail_polish verdict path. Post-Stage-1h that code is out of the
        taxonomy, so we use PROSE_CLICHE_BURST (still a polish code) instead.
        """
        await _run_with_model_result({
            "verdict": "fail_polish",
            "failure_codes": [{"code": "PROSE_CLICHE_BURST", "location": "all",
                               "description": "purple prose", "fix_hint": "tighten"}],
        })

        captured = capsys.readouterr()
        assert "overridden" not in captured.out

    async def test_model_omits_verdict_is_fine(self):
        """When model doesn't return a verdict, derivation still works and no log fires."""
        result = await _run_with_model_result({
            "failure_codes": [{"code": "TERMINOLOGY_DRIFT", "location": "para 1",
                               "description": "typo", "fix_hint": "fix"}],
        })

        assert result["verdict"] == "fail_voice"
        assert result["route_to"] == "targeted_revision"
