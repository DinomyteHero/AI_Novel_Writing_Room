"""Tests for the ChapterGateCritic agent and orchestrator chapter detection."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.chapter_gate_critic import ChapterGateCritic
from src.orchestrator import Orchestrator


class TestIsLastSceneInChapter:
    """Test the static _is_last_scene_in_chapter helper."""

    def test_last_scene_in_multi_scene_chapter(self):
        cards = [
            {"chapter_number": 1, "scene_number": 1},
            {"chapter_number": 1, "scene_number": 2},
            {"chapter_number": 2, "scene_number": 1},
        ]
        assert not Orchestrator._is_last_scene_in_chapter(0, cards)
        assert Orchestrator._is_last_scene_in_chapter(1, cards)
        assert Orchestrator._is_last_scene_in_chapter(2, cards)

    def test_single_scene_chapter(self):
        cards = [
            {"chapter_number": 1, "scene_number": 1},
            {"chapter_number": 2, "scene_number": 1},
        ]
        assert Orchestrator._is_last_scene_in_chapter(0, cards)
        assert Orchestrator._is_last_scene_in_chapter(1, cards)

    def test_single_card(self):
        cards = [{"chapter_number": 1, "scene_number": 1}]
        assert Orchestrator._is_last_scene_in_chapter(0, cards)


class TestChapterGateCriticFormatting:
    """Test the ChapterGateCritic context formatting."""

    def test_format_includes_all_scenes(self, multi_scene_chapter_cards, mock_router):
        critic = ChapterGateCritic(mock_router)

        context = {
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": [
                "Scene 1 prose here.",
                "Scene 2 prose here.",
                "Scene 3 prose here.",
            ],
            "chapter_number": 5,
        }

        formatted = critic._format_context(context)
        assert "Chapter 5" in formatted
        assert "Scene 1 — Card" in formatted
        assert "Scene 2 — Card" in formatted
        assert "Scene 3 — Card" in formatted
        assert "Scene 1 prose here." in formatted
        assert "Scene 3 prose here." in formatted

    @pytest.mark.asyncio
    async def test_run_parses_pass_response(self, multi_scene_chapter_cards):
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "chapter_passed": True,
            "chapter_level_failures": [],
            "scene_level_flags": [],
            "metrics": {
                "scene_variety_index": 0.7,
                "conflict_density": 0.5,
                "chapter_hook_strength": 0.8,
                "arc_pressure_progression": "ascending",
            },
        })

        critic = ChapterGateCritic(router)
        result = await critic.run({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["prose 1", "prose 2", "prose 3"],
            "chapter_number": 5,
        })

        assert result["chapter_passed"] is True
        assert result["chapter_level_failures"] == []

    @pytest.mark.asyncio
    async def test_run_handles_non_dict_response(self, multi_scene_chapter_cards):
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value={
            "content": "not valid json at all"
        })

        critic = ChapterGateCritic(router)
        result = await critic.run({
            "scene_cards": multi_scene_chapter_cards,
            "scene_prose": ["prose 1", "prose 2", "prose 3"],
            "chapter_number": 5,
        })

        assert result["chapter_passed"] is False
        assert len(result["chapter_level_failures"]) > 0
        assert result["chapter_level_failures"][0]["check"] == "parse_error"
