"""Tests for the FinalGate agent.

FinalGate runs on the Quality Polish output before save. It enforces the
contract the Scene Gate could not (since the Scene Gate saw a different
artifact): character presence, closing-hook boundary, word-count floor,
structural regression. Its verdict is derived from failure codes using the
same machinery as GateCritic.
"""

from unittest.mock import AsyncMock, MagicMock

from src.agents.final_gate import FinalGate


def _make_prose(word_count: int) -> str:
    return " ".join(["word"] * word_count)


def _make_context(
    prose: str = "Polished prose.",
    gate_passed_word_count: int = 100,
    characters: list[str] | None = None,
    closing_hook: str = "The door closed.",
    target: int = 100,
) -> dict:
    return {
        "prose": prose,
        "scene_card": {
            "chapter_number": 1,
            "scene_number": 1,
            "target_word_count": target,
            "characters_present": characters or ["Alex"],
            "closing_hook": closing_hook,
            "mission": "Mock mission.",
        },
        "gate_passed_word_count": gate_passed_word_count,
    }


async def _run_gate(context: dict, model_result: dict) -> tuple[dict, MagicMock]:
    router = MagicMock()
    router.complete_structured = AsyncMock(return_value=model_result)
    agent = FinalGate(router)
    return await agent.run(context), router


class TestFinalGatePass:
    async def test_clean_polish_passes(self):
        """No failures -> verdict 'pass', no route."""
        result, _ = await _run_gate(
            _make_context(prose=_make_prose(100), gate_passed_word_count=100),
            {"verdict": "pass", "failure_codes": []},
        )
        assert result["verdict"] == "pass"
        assert result["route_to"] is None
        assert result["severity"] == "non_blocking"


class TestFinalGateFailures:
    async def test_character_presence_violation_fails_structural(self):
        """Polish introduces a character not in characters_present."""
        result, _ = await _run_gate(
            _make_context(),
            {
                "verdict": "fail_structural",
                "failure_codes": [{
                    "code": "CHARACTER_PRESENCE_VIOLATION",
                    "location": "paragraph 4",
                    "description": "Jordan speaks but is not in characters_present",
                    "fix_hint": "Remove Jordan's dialogue",
                }],
            },
        )
        assert result["verdict"] == "fail_structural"
        assert result["route_to"] == "full_rewrite"
        assert any(fc["code"] == "CHARACTER_PRESENCE_VIOLATION" for fc in result["failure_codes"])

    async def test_closing_hook_violation_fails_structural(self):
        """Polish extends past the closing hook."""
        result, _ = await _run_gate(
            _make_context(),
            {
                "verdict": "fail_structural",
                "failure_codes": [{
                    "code": "CLOSING_HOOK_VIOLATION",
                    "location": "end",
                    "description": "Three paragraphs after closing hook",
                    "fix_hint": "Trim trailing content",
                }],
            },
        )
        assert result["verdict"] == "fail_structural"

    async def test_llm_emitted_word_count_violation_is_dropped(self, capsys):
        """Relay v3 (Stage 1h): WORD_COUNT_VIOLATION left FINAL_GATE_CODES, so
        any instance the LLM emits is dropped by the out-of-scope filter."""
        result, _ = await _run_gate(
            _make_context(prose=_make_prose(100), gate_passed_word_count=100),
            {
                "verdict": "fail_polish",
                "failure_codes": [{
                    "code": "WORD_COUNT_VIOLATION",
                    "location": "whole scene",
                    "description": "LLM flagged word count drift",
                    "fix_hint": "Expand",
                }],
            },
        )
        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" not in codes
        # With no in-scope failure codes, the derived verdict is pass.
        assert result["verdict"] == "pass"
        captured = capsys.readouterr()
        assert "dropping out-of-scope failure_code" in captured.out


class TestFinalGateWordCountNotEnforced:
    """Relay v3 (Stage 1h): the 80% word-count floor is no longer enforced
    at FinalGate. Chapter-level drift is telemetry in
    src/pipeline/word_count_telemetry.py."""

    async def test_no_injection_below_old_floor(self):
        """Polished 60% of gate-passed — no code is injected."""
        result, _ = await _run_gate(
            _make_context(prose=_make_prose(60), gate_passed_word_count=100),
            {"verdict": "pass", "failure_codes": []},
        )
        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" not in codes
        assert result["verdict"] == "pass"

    async def test_no_injection_at_any_ratio(self):
        """Even at 10% of gate-passed, there is no injection."""
        result, _ = await _run_gate(
            _make_context(prose=_make_prose(10), gate_passed_word_count=100),
            {"verdict": "pass", "failure_codes": []},
        )
        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" not in codes


class TestFinalGateVerdictReconciliation:
    """The same contract as GateCritic: derived verdict always wins."""

    async def test_llm_pass_with_structural_code_overridden(self):
        """Model says pass but emits structural code -> verdict fail_structural."""
        result, _ = await _run_gate(
            _make_context(),
            {
                "verdict": "pass",
                "failure_codes": [{
                    "code": "MISSING_TURNING_POINT",
                    "location": "whole scene",
                    "description": "turning point flattened by polish",
                    "fix_hint": "restore it",
                }],
            },
        )
        assert result["verdict"] == "fail_structural"

    async def test_unknown_code_is_dropped(self, capsys):
        """Codes outside ALL_CODES are filtered out with a log."""
        result, _ = await _run_gate(
            _make_context(),
            {
                "verdict": "fail_polish",
                "failure_codes": [
                    {"code": "MADE_UP_CODE", "location": "x", "description": "y", "fix_hint": "z"},
                    {"code": "WEAK_TURNING_POINT", "location": "end", "description": "flat",
                     "fix_hint": "build"},
                ],
            },
        )
        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "MADE_UP_CODE" not in codes
        assert "WEAK_TURNING_POINT" in codes
        assert result["verdict"] == "fail_structural"
        captured = capsys.readouterr()
        assert "MADE_UP_CODE" in captured.out
