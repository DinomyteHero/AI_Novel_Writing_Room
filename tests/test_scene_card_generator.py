"""Tests for the SceneCardGenerator and OutlinePlanner."""

import json
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

import pytest

from src.planning.scene_card_generator import OutlinePlanner, SceneCardGenerator


@pytest.fixture
def seed():
    return {
        "meta": {
            "project_title": "Test Novel",
            "franchise": "Star Wars",
            "target_chapters": 3,
            "target_word_count": 9000,
            "pov_structure": "rotating",
        },
        "premise": {
            "what_if": "What if Force wounds required collective healing?",
            "central_dramatic_question": "Can they trust each other?",
            "logline": "A crew ventures into Force wounds.",
        },
        "conflict": {
            "primary_antagonistic_force": {
                "type": "environmental",
                "identity": "Force wounds",
                "motivation": "Spreading chaos",
                "escalation": "Wounds grow larger over time.",
            },
        },
        "theme": {
            "thematic_premise": "Trust",
            "thematic_argument": "Collective trust overcomes individual doubt.",
        },
        "ensemble_cast": [
            {"name": "Ben", "role": "protagonist", "three_dimensions": {"surface": "brave", "backstory_inner_demons": "doubt"}},
            {"name": "Kira", "role": "deuteragonist", "three_dimensions": {"surface": "calm", "backstory_inner_demons": "guilt"}},
        ],
        "structural_notes": {
            "setup": "Establish crew and mission.",
            "first_plot_point": "Crew enters the wound.",
        },
    }


@pytest.fixture
def mock_outline_response():
    """Mock response with valid scene cards."""
    return [
        {
            "chapter_number": 1,
            "scene_number": 1,
            "structural_phase": "setup",
            "pov_character": "Ben",
            "mission": "Establish the mission",
            "why_now": "Opening scene sets up the crew",
            "conflict": "Internal doubt",
            "conflict_type": "internal",
            "turning_point": "Ben accepts the mission",
            "emotional_trajectory": "Doubt to acceptance",
            "characters_present": ["Ben", "Kira"],
            "plot_threads_advanced": ["mission"],
            "promises_planted": ["trust_issue"],
            "promises_paid": [],
            "canon_elements_needed": ["Jedi Temple"],
            "target_word_count": 3000,
        },
        {
            "chapter_number": 2,
            "scene_number": 1,
            "structural_phase": "response",
            "pov_character": "Kira",
            "mission": "Enter the wound",
            "why_now": "Mission begins after briefing",
            "conflict": "Environmental danger",
            "conflict_type": "environmental",
            "turning_point": "First encounter with the wound",
            "emotional_trajectory": "Calm to fear",
            "characters_present": ["Ben", "Kira"],
            "plot_threads_advanced": ["wound_exploration"],
            "promises_planted": [],
            "promises_paid": [],
            "canon_elements_needed": [],
            "target_word_count": 3000,
        },
    ]


class TestOutlinePlanner:

    def test_outline_planner_role(self, mock_router):
        planner = OutlinePlanner(mock_router)
        assert planner.role == "outline_planner"

    def test_format_context_includes_seed(self, mock_router, seed):
        planner = OutlinePlanner(mock_router)
        context = planner._format_context({"concept_seed": seed})

        assert "Test Novel" in context
        assert "Star Wars" in context
        assert "3" in context  # target_chapters
        assert "Ben" in context
        assert "Kira" in context

    def test_parse_response_json_array(self, mock_router, mock_outline_response):
        planner = OutlinePlanner(mock_router)
        response = json.dumps(mock_outline_response)
        result = planner._parse_response(response, {})

        assert "scene_cards" in result
        assert len(result["scene_cards"]) == 2

    def test_parse_response_markdown_fenced(self, mock_router, mock_outline_response):
        planner = OutlinePlanner(mock_router)
        response = f"```json\n{json.dumps(mock_outline_response)}\n```"
        result = planner._parse_response(response, {})

        assert len(result["scene_cards"]) == 2


class TestSceneCardGenerator:

    @pytest.mark.asyncio
    async def test_generate_returns_cards(self, mock_router, seed, mock_outline_response):
        mock_router.complete_structured = AsyncMock(return_value={
            "scene_cards": mock_outline_response,
        })

        generator = SceneCardGenerator(mock_router)
        cards = await generator.generate(seed)

        assert len(cards) == 2
        assert cards[0]["chapter_number"] == 1

    @pytest.mark.asyncio
    async def test_generate_fills_defaults(self, mock_router, seed):
        """A minimal card gets defaults filled.  Since critical fields are
        empty the generator retries — the second call returns the same
        minimal card, so after max_retries it returns with defaults applied."""
        minimal = {"chapter_number": 1}
        mock_router.complete_structured = AsyncMock(return_value={
            "scene_cards": [minimal],
        })

        generator = SceneCardGenerator(mock_router)
        cards = await generator.generate(seed, max_retries=1)

        assert cards[0]["scene_number"] == 1
        assert cards[0]["structural_phase"] == "setup"
        assert cards[0]["target_word_count"] == 1000  # (9000 / 3) / 3 = per-scene

    @pytest.mark.asyncio
    async def test_generate_no_physics(self, mock_router, seed, mock_outline_response):
        mock_router.complete_structured = AsyncMock(return_value={
            "scene_cards": mock_outline_response,
        })

        generator = SceneCardGenerator(mock_router, physics_enforcer=None)
        cards = await generator.generate(seed)

        assert len(cards) == 2

    def test_save_scene_cards(self, mock_router, temp_dir, mock_outline_response):
        generator = SceneCardGenerator(mock_router)
        output_dir = str(Path(temp_dir) / "scene_cards")

        paths = generator.save_scene_cards(mock_outline_response, output_dir)

        assert len(paths) == 2
        assert all(p.exists() for p in paths)
        assert paths[0].name == "chapter_01_scene_01.json"
        assert paths[1].name == "chapter_02_scene_01.json"

        # Verify content
        data = json.loads(paths[0].read_text())
        assert data["chapter_number"] == 1

    def test_semantic_completeness_detects_empty_fields(self, mock_router):
        """Cards with empty critical fields are flagged by semantic check."""
        empty_card = {
            "chapter_number": 1, "scene_number": 1,
            "structural_phase": "setup",
            "pov_character": "", "mission": "",
            "conflict": "", "turning_point": "",
            "characters_present": [],
        }
        warnings = SceneCardGenerator._check_semantic_completeness(empty_card)
        assert len(warnings) == 5  # 4 string fields + characters_present

    def test_semantic_completeness_passes_complete_card(self, mock_router, mock_outline_response):
        """A fully populated card passes semantic check."""
        warnings = SceneCardGenerator._check_semantic_completeness(mock_outline_response[0])
        assert warnings == []

    @pytest.mark.asyncio
    async def test_generate_retries_on_empty_fields(self, mock_router, seed, mock_outline_response):
        """Incomplete cards trigger retry; complete cards are accepted."""
        empty_card = {"chapter_number": 1, "scene_number": 1}

        mock_router.complete_structured = AsyncMock(side_effect=[
            {"scene_cards": [empty_card]},
            {"scene_cards": mock_outline_response[:1]},  # complete card on retry
        ])

        generator = SceneCardGenerator(mock_router)
        cards = await generator.generate(seed, max_retries=2)

        # Should have called LLM twice (initial + 1 retry)
        assert mock_router.complete_structured.call_count == 2
        # Final card should have content
        assert cards[0]["mission"] != ""

    @pytest.mark.asyncio
    async def test_generate_with_physics_retry(self, mock_router, seed):
        """PhysicsEnforcer rejects first attempt, generator retries."""
        # Card that passes semantic check but fails physics (no why_now)
        sem_ok_card = {
            "chapter_number": 1, "scene_number": 1,
            "structural_phase": "setup",
            "pov_character": "Ben", "mission": "Test",
            "conflict": "Test conflict", "turning_point": "Test turn",
            "characters_present": ["Ben"],
        }
        # Card that passes both
        good_card = {**sem_ok_card, "why_now": "Good reason"}

        # First call returns physics-failing card, second returns good card
        mock_router.complete_structured = AsyncMock(side_effect=[
            {"scene_cards": [sem_ok_card]},
            {"scene_cards": [good_card]},
        ])

        mock_physics = MagicMock()
        mock_physics.validate_pre_chapter = MagicMock(side_effect=[
            {"passed": False, "issues": [{"issue_type": "missing_why_now"}], "recommendations": []},
            {"passed": True, "issues": [], "recommendations": []},
        ])

        generator = SceneCardGenerator(mock_router, physics_enforcer=mock_physics)
        cards = await generator.generate(seed, max_retries=2)

        assert len(cards) >= 1
        assert mock_physics.validate_pre_chapter.call_count == 2
