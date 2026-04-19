"""Tests for the v3 relay refactor: WORD_COUNT_VIOLATION leaves the gate.

Under Stage 1h, scene-level word count is no longer enforced at the gate.
The constant ``WORD_COUNT_VIOLATION`` still exists for historical ledger
compatibility but is NOT in ``ALL_CODES``, so:

- GateCritic never injects WORD_COUNT_VIOLATION programmatically.
- Any WORD_COUNT_VIOLATION the LLM emits is dropped by the
  unknown-code filter, same as any hallucinated or typo'd code.

Chapter-level drift is tracked in src/pipeline/word_count_telemetry.py
and emitted as info/warn/error events that never block a save.
"""

from unittest.mock import AsyncMock, MagicMock

from src.agents.gate_critic import GateCritic, WORD_COUNT_VIOLATION


def _make_prose(word_count: int) -> str:
    return " ".join(["word"] * word_count)


def _make_context(prose: str, target: int | None = 1000) -> dict:
    scene_card: dict = {"chapter_number": 1, "scene_number": 1}
    if target is not None:
        scene_card["target_word_count"] = target
    return {"prose": prose, "scene_card": scene_card, "bible_summary": ""}


async def _run(prose: str, model_codes: list[dict], target: int | None = 1000) -> dict:
    router = MagicMock()
    router.complete_structured = AsyncMock(return_value={
        "verdict": "pass",
        "failure_codes": model_codes,
        "structural_score": 0.85,
        "voice_score": 0.85,
        "polish_score": 0.85,
    })
    critic = GateCritic(router)
    return await critic.run(_make_context(prose, target))


class TestWordCountNotInjected:
    async def test_constant_still_importable(self):
        """Historical-compat: the name is still exported."""
        assert WORD_COUNT_VIOLATION == "WORD_COUNT_VIOLATION"

    async def test_not_injected_when_below_tolerance(self):
        """Prose at 70% of target no longer triggers injection."""
        result = await _run(_make_prose(700), model_codes=[])
        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" not in codes
        assert result["verdict"] == "pass"

    async def test_not_injected_when_above_tolerance(self):
        """Prose at 130% of target no longer triggers injection."""
        result = await _run(_make_prose(1300), model_codes=[])
        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" not in codes

    async def test_not_injected_when_within_tolerance(self):
        """Prose at 90% of target — no injection (same as before)."""
        result = await _run(_make_prose(900), model_codes=[])
        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" not in codes

    async def test_llm_emitted_code_is_dropped(self, capsys):
        """If the LLM emits WORD_COUNT_VIOLATION it's dropped by the
        unknown-code filter, because the code is no longer in ALL_CODES."""
        existing_code = {
            "code": "WORD_COUNT_VIOLATION",
            "location": "whole scene",
            "description": "LLM thinks it's short",
            "fix_hint": "expand",
        }
        result = await _run(_make_prose(700), model_codes=[existing_code])
        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" not in codes

        captured = capsys.readouterr()
        assert "dropping unknown failure_code" in captured.out
        assert "WORD_COUNT_VIOLATION" in captured.out

    async def test_other_codes_still_work(self):
        """Removing word-count injection does not affect other codes."""
        result = await _run(
            _make_prose(500),
            model_codes=[{
                "code": "WEAK_TURNING_POINT",
                "location": "para 3",
                "description": "turn lands in two beats",
                "fix_hint": "build resistance",
            }],
        )
        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WEAK_TURNING_POINT" in codes
        assert result["verdict"] == "fail_structural"
