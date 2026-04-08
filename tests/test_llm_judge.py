"""Tests for the JudgeEvaluator (LLM-as-judge)."""

from unittest.mock import AsyncMock

import pytest

from src.quality.llm_judge import JudgeEvaluator, _DEFAULT_RUBRIC


@pytest.fixture
def judge(mock_router):
    return JudgeEvaluator(mock_router)


@pytest.fixture
def chapter_context():
    return {
        "prose": "Ben walked through the temple. The Force hummed around him.",
        "scene_card": {
            "chapter_number": 1,
            "scene_number": 1,
            "structural_phase": "setup",
            "pov_character": "Ben",
            "mission": "Establish the protagonist",
        },
    }


@pytest.fixture
def mock_judge_response():
    return {
        "scores": {
            "narrative_engagement": 7,
            "character_authenticity": 8,
            "prose_craftsmanship": 6,
            "thematic_resonance": 5,
            "structural_contribution": 7,
        },
        "feedback": "Solid setup chapter with good character work.",
        "recommendation": "minor_revision",
    }


class TestJudgeEvaluator:

    def test_role(self, judge):
        assert judge.role == "judge_evaluator"

    def test_rubric_loaded(self, judge):
        assert "narrative_engagement" in judge.rubric
        assert "character_authenticity" in judge.rubric
        assert "prose_craftsmanship" in judge.rubric
        assert "thematic_resonance" in judge.rubric
        assert "structural_contribution" in judge.rubric

    def test_default_rubric(self):
        assert "narrative_engagement" in _DEFAULT_RUBRIC
        assert len(_DEFAULT_RUBRIC) == 5

    def test_format_context_includes_rubric(self, judge, chapter_context):
        context = judge._format_context(chapter_context)

        assert "narrative_engagement" in context
        assert "character_authenticity" in context
        assert "Ben walked through the temple" in context

    def test_format_context_includes_scene_card(self, judge, chapter_context):
        context = judge._format_context(chapter_context)

        assert "Chapter: 1" in context
        assert "setup" in context
        assert "Ben" in context

    @pytest.mark.asyncio
    async def test_evaluate_chapter_scores(self, judge, chapter_context, mock_judge_response):
        judge.router.complete_structured = AsyncMock(return_value=mock_judge_response)

        result = await judge.evaluate_chapter(chapter_context)

        assert "scores" in result
        assert result["scores"]["narrative_engagement"] == 7
        assert result["scores"]["character_authenticity"] == 8

    @pytest.mark.asyncio
    async def test_evaluate_chapter_overall_score(self, judge, chapter_context, mock_judge_response):
        judge.router.complete_structured = AsyncMock(return_value=mock_judge_response)

        result = await judge.evaluate_chapter(chapter_context)

        # Overall should be average: (7+8+6+5+7) / 5 = 6.6
        assert result["overall_score"] == 6.6

    @pytest.mark.asyncio
    async def test_evaluate_chapter_chapter_number(self, judge, chapter_context, mock_judge_response):
        judge.router.complete_structured = AsyncMock(return_value=mock_judge_response)

        result = await judge.evaluate_chapter(chapter_context)

        assert result["chapter_number"] == 1
        assert result["scene_number"] == 1

    @pytest.mark.asyncio
    async def test_evaluate_manuscript(self, judge, mock_judge_response):
        judge.router.complete_structured = AsyncMock(return_value=mock_judge_response)

        chapters = [
            {
                "prose": "Chapter 1 prose here.",
                "scene_card": {"chapter_number": 1, "scene_number": 1},
            },
            {
                "prose": "Chapter 2 prose here.",
                "scene_card": {"chapter_number": 2, "scene_number": 1},
            },
        ]

        result = await judge.evaluate_manuscript(chapters)

        assert "manuscript_score" in result
        assert "chapter_scores" in result
        assert "dimension_averages" in result
        assert len(result["chapter_scores"]) == 2
        assert result["manuscript_score"] == 6.6  # same response for both

    @pytest.mark.asyncio
    async def test_evaluate_manuscript_feedback_summary(self, judge, mock_judge_response):
        judge.router.complete_structured = AsyncMock(return_value=mock_judge_response)

        chapters = [
            {"prose": "Ch1.", "scene_card": {"chapter_number": 1, "scene_number": 1}},
        ]

        result = await judge.evaluate_manuscript(chapters)

        assert "feedback_summary" in result
        assert "1 chapters" in result["feedback_summary"]

    def test_parse_response_valid_json(self, judge, mock_judge_response):
        import json
        response = json.dumps(mock_judge_response)
        result = judge._parse_response(response, {
            "scene_card": {"chapter_number": 1, "scene_number": 1}
        })

        assert "scores" in result
        assert result["overall_score"] == 6.6

    def test_parse_response_invalid_json(self, judge):
        result = judge._parse_response("Not valid JSON", {"scene_card": {}})

        assert result["overall_score"] == 0.0
        assert result["recommendation"] == "major_revision"
