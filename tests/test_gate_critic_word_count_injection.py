"""Tests for programmatic WORD_COUNT_VIOLATION injection in GateCritic.run().

Word-count enforcement must not depend on the LLM remembering to emit the code.
If prose is outside +/- 20% of target_word_count, the orchestrator injects the
failure code deterministically before verdict derivation.
"""

from unittest.mock import AsyncMock, MagicMock

from src.agents.gate_critic import GateCritic


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


class TestWordCountInjection:
    async def test_injected_when_below_tolerance_and_llm_silent(self):
        """Prose at 70% of target + no model code -> WORD_COUNT_VIOLATION injected."""
        # 700 words / 1000 target = 70%, outside -20% tolerance
        result = await _run(_make_prose(700), model_codes=[])

        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" in codes
        assert result["verdict"] == "fail_polish"

    async def test_injected_when_above_tolerance_and_llm_silent(self):
        """Prose at 130% of target + no model code -> WORD_COUNT_VIOLATION injected."""
        result = await _run(_make_prose(1300), model_codes=[])

        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" in codes

    async def test_not_injected_when_within_tolerance(self):
        """Prose at 90% of target (within +/- 20%) -> no injection."""
        result = await _run(_make_prose(900), model_codes=[])

        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" not in codes
        assert result["verdict"] == "pass"

    async def test_not_injected_at_exact_boundary(self):
        """Prose at exactly 80% (1000 - 200) or 120% should not trigger; uses strict >20%."""
        # 800 words / 1000 = 80%, delta = 20%, boundary case (strict >)
        result_low = await _run(_make_prose(800), model_codes=[])
        codes_low = [fc["code"] for fc in result_low["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" not in codes_low

        # 1200 / 1000 = 120%, delta = 20%, boundary case (strict >)
        result_high = await _run(_make_prose(1200), model_codes=[])
        codes_high = [fc["code"] for fc in result_high["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" not in codes_high

    async def test_not_duplicated_when_llm_already_emitted(self):
        """If the LLM already emitted WORD_COUNT_VIOLATION, we don't append a duplicate."""
        existing_code = {
            "code": "WORD_COUNT_VIOLATION",
            "location": "whole scene",
            "description": "too short per LLM check",
            "fix_hint": "expand",
        }
        result = await _run(_make_prose(700), model_codes=[existing_code])

        wc_codes = [fc for fc in result["failure_codes"] if fc["code"] == "WORD_COUNT_VIOLATION"]
        assert len(wc_codes) == 1
        # The LLM-provided description is preserved (we don't overwrite)
        assert wc_codes[0]["description"] == "too short per LLM check"

    async def test_no_target_word_count_means_no_injection(self):
        """If scene card lacks target_word_count, never inject."""
        result = await _run(_make_prose(500), model_codes=[], target=None)

        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" not in codes

    async def test_zero_target_word_count_does_not_divide_by_zero(self):
        """target_word_count == 0 is treated as 'no target', not an error."""
        result = await _run(_make_prose(500), model_codes=[], target=0)

        codes = [fc["code"] for fc in result["failure_codes"]]
        assert "WORD_COUNT_VIOLATION" not in codes

    async def test_injected_code_coexists_with_structural_code(self):
        """A structural failure still dominates verdict even if word count also fires."""
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
        assert "WORD_COUNT_VIOLATION" in codes
        # Structural dominates polish
        assert result["verdict"] == "fail_structural"

    async def test_injection_is_logged(self, capsys):
        """A line is printed so the rejection is visible in orchestrator output."""
        await _run(_make_prose(500), model_codes=[])

        captured = capsys.readouterr()
        assert "WORD_COUNT_VIOLATION" in captured.out
        assert "500/1000" in captured.out
