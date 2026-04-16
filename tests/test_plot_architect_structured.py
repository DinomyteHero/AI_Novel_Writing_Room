"""Tests for PlotArchitect emitting a typed generation brief.

Phase 2 hard cutover: Plot Architect now uses `complete_structured` and
returns a dict matching schemas/generation_brief.json. These tests cover the
agent's contract — what it calls, what it returns, and how missing required
fields surface as a warning.
"""

from unittest.mock import AsyncMock, MagicMock

from src.agents.plot_architect import PlotArchitect, REQUIRED_BRIEF_FIELDS


def _well_formed_brief() -> dict:
    """A minimal brief that satisfies every required field."""
    return {
        "scene_objective": "Establish Alex's solitary working style.",
        "turning_point": {
            "trigger": "Alex opens the sealed file.",
            "shift": "Private case becomes personal.",
            "cost": "Alex chooses transgression over protocol.",
        },
        "closing_beat": "The locked drawer; an unknown text arrives.",
        "emotional_arc": {
            "start": "procedural boredom",
            "shift": "unexpected recognition",
            "end": "deliberate transgression",
        },
        "target_word_count": 3000,
    }


def _make_context(scene_card: dict | None = None) -> dict:
    return {
        "scene_card": scene_card or {
            "chapter_number": 1,
            "scene_number": 1,
            "target_word_count": 3000,
            "mission": "mock mission",
            "notes": "",
        },
        "bible_summary": "Test bible",
    }


async def _run(brief_response: dict, context: dict | None = None) -> tuple[dict, MagicMock]:
    router = MagicMock()
    router.complete_structured = AsyncMock(return_value=brief_response)
    agent = PlotArchitect(router)
    result = await agent.run(context or _make_context())
    return result, router


class TestStructuredOutput:
    async def test_uses_complete_structured(self):
        _, router = await _run(_well_formed_brief())
        router.complete_structured.assert_awaited_once()

    async def test_returns_brief_and_scene_card(self):
        context = _make_context()
        result, _ = await _run(_well_formed_brief(), context)
        assert result["generation_brief"] == _well_formed_brief()
        assert result["scene_card"] is context["scene_card"]

    async def test_role_passed_to_router(self):
        _, router = await _run(_well_formed_brief())
        call_args = router.complete_structured.await_args
        assert call_args.args[0] == "plot_architect"


class TestRequiredFieldsContract:
    def test_required_fields_constant_matches_schema(self):
        """REQUIRED_BRIEF_FIELDS must stay in sync with the schema's required list."""
        assert set(REQUIRED_BRIEF_FIELDS) == {
            "scene_objective",
            "turning_point",
            "closing_beat",
            "emotional_arc",
            "target_word_count",
        }

    async def test_warning_logged_when_required_field_missing(self, capsys):
        """Missing required fields log a warning but do not raise."""
        partial = _well_formed_brief()
        del partial["emotional_arc"]

        result, _ = await _run(partial)
        # Agent still returns the partial brief — missing fields propagate
        assert result["generation_brief"] == partial

        captured = capsys.readouterr()
        assert "missing required fields" in captured.out
        assert "emotional_arc" in captured.out

    async def test_no_warning_when_all_required_fields_present(self, capsys):
        await _run(_well_formed_brief())
        captured = capsys.readouterr()
        assert "missing required fields" not in captured.out


class TestPromptContext:
    """The user prompt sent to the LLM should instruct it to produce typed JSON."""

    async def test_prompt_requests_json_output(self):
        _, router = await _run(_well_formed_brief())
        messages = router.complete_structured.await_args.args[1]
        user_content = messages[-1]["content"]
        assert "JSON" in user_content
        assert "GenerationBrief" in user_content or "generation brief" in user_content.lower()

    async def test_prompt_names_all_required_fields(self):
        _, router = await _run(_well_formed_brief())
        user_content = router.complete_structured.await_args.args[1][-1]["content"]
        for field in REQUIRED_BRIEF_FIELDS:
            assert field in user_content, f"required field {field!r} not in prompt"

    async def test_prompt_includes_anti_pattern_extraction_instruction(self):
        _, router = await _run(_well_formed_brief())
        user_content = router.complete_structured.await_args.args[1][-1]["content"]
        assert "anti_pattern" in user_content.lower()
        assert "notes" in user_content.lower()

    async def test_prompt_includes_scene_card_json(self):
        scene_card = {
            "chapter_number": 1,
            "scene_number": 1,
            "target_word_count": 1250,
            "mission": "Specific mission text",
            "notes": "do not open with a flashback",
        }
        _, router = await _run(_well_formed_brief(), _make_context(scene_card))
        user_content = router.complete_structured.await_args.args[1][-1]["content"]
        assert "Specific mission text" in user_content
        assert "do not open with a flashback" in user_content
