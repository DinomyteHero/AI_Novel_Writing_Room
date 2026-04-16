"""Tests for the QualityPolish agent.

QualityPolish is the single bounded polish pass that replaced the Craft Editor
and the 3-band revision pipeline. It produces polished prose (a string) from
gate-passed prose plus scene-card hard constraints and optional quality metrics.
The Final Gate validates the polish output — these tests only cover the agent's
own contract.
"""

from unittest.mock import AsyncMock, MagicMock

from src.agents.quality_polish import QualityPolish


def _make_context(
    prose: str = "Original prose. The protagonist stared into the middle distance.",
    target: int = 1000,
    characters: list[str] | None = None,
    closing_hook: str = "The door closed behind her.",
    quality_metrics: dict | None = None,
    negative_constraints: str = "",
    canon_notes: str = "",
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
        "quality_metrics": quality_metrics,
        "negative_constraints": negative_constraints,
        "canon_notes": canon_notes,
    }


async def _run_polish(context: dict, response: str = "Polished prose."):
    router = MagicMock()
    router.complete = AsyncMock(return_value=response)
    agent = QualityPolish(router)
    return await agent.run(context), router


class TestQualityPolishBasics:
    async def test_returns_polished_prose(self):
        result, _ = await _run_polish(_make_context(), response="Polished output.")
        assert result["prose"] == "Polished output."
        assert result["was_polished"] is True

    async def test_delegates_to_router_complete_once(self):
        _, router = await _run_polish(_make_context())
        router.complete.assert_awaited_once()

    async def test_scene_card_preserved_in_result(self):
        ctx = _make_context()
        result, _ = await _run_polish(ctx)
        assert result["scene_card"] is ctx["scene_card"]

    async def test_response_is_stripped(self):
        result, _ = await _run_polish(_make_context(), response="  polished with whitespace  \n")
        assert result["prose"] == "polished with whitespace"


class TestQualityPolishPromptContext:
    """Verify the user prompt carries the CAN/CANNOT contract inputs."""

    async def test_prompt_includes_hard_constraints(self):
        ctx = _make_context(
            characters=["Alex", "Jordan"],
            closing_hook="The door closed behind her.",
            target=1500,
        )
        _, router = await _run_polish(ctx)

        messages = router.complete.await_args.args[1]
        user_content = messages[-1]["content"]
        assert "Hard Constraints" in user_content
        assert "Alex" in user_content
        assert "Jordan" in user_content
        assert "The door closed behind her." in user_content
        assert "1500" in user_content

    async def test_prompt_includes_word_count_contract_with_floor(self):
        # 500-word prose -> floor is 400 (80%)
        prose = " ".join(["word"] * 500)
        ctx = _make_context(prose=prose)
        _, router = await _run_polish(ctx)

        content = router.complete.await_args.args[1][-1]["content"]
        assert "Word Count Contract" in content
        assert "500" in content  # pre-polish count
        assert "400" in content  # 80% floor

    async def test_prompt_includes_quality_metric_flags_when_provided(self):
        metrics = {
            "flags": ["show-don't-tell violations", "overused word: suddenly"],
            "per_scene": [{"repetition": {"flagged_words": [{"word": "eyes"}]}}],
        }
        ctx = _make_context(quality_metrics=metrics)
        _, router = await _run_polish(ctx)

        content = router.complete.await_args.args[1][-1]["content"]
        assert "show-don't-tell violations" in content
        assert "eyes" in content

    async def test_prompt_includes_negative_constraints(self):
        ctx = _make_context(negative_constraints="Avoid: delve, tapestry, testament.")
        _, router = await _run_polish(ctx)

        content = router.complete.await_args.args[1][-1]["content"]
        assert "delve" in content
        assert "Style Constraints" in content

    async def test_prompt_includes_canon_notes_as_hard_constraint(self):
        ctx = _make_context(canon_notes="- Use 'lightsaber' not 'laser sword'.")
        _, router = await _run_polish(ctx)

        content = router.complete.await_args.args[1][-1]["content"]
        assert "Canon Notes" in content
        assert "HARD CONSTRAINT" in content
        assert "lightsaber" in content

    async def test_prompt_enumerates_can_and_cannot(self):
        _, router = await _run_polish(_make_context())
        content = router.complete.await_args.args[1][-1]["content"]
        assert "You CAN:" in content
        assert "You CANNOT:" in content
        assert "Final Gate" in content or "80% word-count floor" in content


class TestQualityPolishNoCrashOnMissingOptionalFields:
    async def test_empty_quality_metrics_ok(self):
        ctx = _make_context(quality_metrics=None)
        result, _ = await _run_polish(ctx)
        assert result["prose"] == "Polished prose."

    async def test_no_canon_notes_ok(self):
        result, _ = await _run_polish(_make_context(canon_notes=""))
        assert result["prose"]

    async def test_no_target_word_count_does_not_crash(self):
        # Even with target=0, the agent should still work (floor becomes 0)
        prose = "Short prose."
        ctx = _make_context(prose=prose, target=0)
        result, router = await _run_polish(ctx)
        assert result["prose"]
        content = router.complete.await_args.args[1][-1]["content"]
        # Floor is computed from pre-polish wc, not target
        assert "Word Count Contract" in content
