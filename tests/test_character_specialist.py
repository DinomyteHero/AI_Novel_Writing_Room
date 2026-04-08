"""Tests for CharacterSpecialist agent."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.agents.character_specialist import CharacterSpecialist


@pytest.fixture
def character_specialist(mock_router):
    """CharacterSpecialist with mock router."""
    return CharacterSpecialist(mock_router)


@pytest.fixture
def char_context(sample_scene_card, sample_prose):
    """Context dict for the character specialist."""
    return {
        "prose": sample_prose,
        "scene_card": sample_scene_card,
        "character_voices": "### Ben Skywalker\nInformal but precise. Uses humor as deflection.",
        "character_knowledge": "### Ben Skywalker\n- Knows about the mission briefing.",
        "character_profiles": [
            {
                "name": "Ben Skywalker",
                "three_dimensions": {
                    "surface": "Competent, dry humor.",
                    "backstory_inner_demons": "Carries guilt and trust issues.",
                    "action_under_pressure": "Leads with instinct. Protects people.",
                },
                "voice_notes": "Informal but precise. Uses humor as deflection.",
            }
        ],
    }


class TestCharacterSpecialist:
    @pytest.mark.asyncio
    async def test_run_pass(self, character_specialist, char_context, mock_router):
        mock_router.complete_structured = AsyncMock(return_value={
            "verdict": "pass",
            "character_analyses": [
                {
                    "character_name": "Ben Skywalker",
                    "voice_consistent": True,
                    "actions_consistent": True,
                    "knowledge_respected": True,
                    "emotional_arc_match": True,
                    "notes": "Voice matches profile.",
                }
            ],
            "overall_voice_score": 0.92,
            "overall_notes": "All characters consistent.",
        })

        result = await character_specialist.run(char_context)
        assert result["verdict"] == "pass"
        assert len(result["character_analyses"]) == 1
        assert result["overall_voice_score"] == 0.92

    @pytest.mark.asyncio
    async def test_run_fail_voice(self, character_specialist, char_context, mock_router):
        mock_router.complete_structured = AsyncMock(return_value={
            "verdict": "fail_voice",
            "character_analyses": [
                {
                    "character_name": "Ben Skywalker",
                    "voice_consistent": False,
                    "actions_consistent": True,
                    "knowledge_respected": True,
                    "emotional_arc_match": True,
                    "notes": "Dialogue too formal for Ben's profile.",
                }
            ],
            "overall_voice_score": 0.45,
            "overall_notes": "Voice inconsistency detected.",
        })

        result = await character_specialist.run(char_context)
        assert result["verdict"] == "fail_voice"

    @pytest.mark.asyncio
    async def test_run_fail_action(self, character_specialist, char_context, mock_router):
        mock_router.complete_structured = AsyncMock(return_value={
            "verdict": "fail_action",
            "character_analyses": [
                {
                    "character_name": "Ben Skywalker",
                    "voice_consistent": True,
                    "actions_consistent": False,
                    "knowledge_respected": True,
                    "emotional_arc_match": False,
                    "notes": "Ben abandons crew — contradicts action_under_pressure.",
                }
            ],
            "overall_voice_score": 0.30,
            "overall_notes": "OOC action detected.",
        })

        result = await character_specialist.run(char_context)
        assert result["verdict"] == "fail_action"

    @pytest.mark.asyncio
    async def test_verdict_derived_from_analyses(self, character_specialist, char_context, mock_router):
        """If LLM returns pass but analyses show issues, derive correct verdict."""
        mock_router.complete_structured = AsyncMock(return_value={
            "verdict": "pass",
            "character_analyses": [
                {
                    "character_name": "Ben Skywalker",
                    "voice_consistent": False,
                    "actions_consistent": True,
                    "knowledge_respected": True,
                    "notes": "Voice mismatch.",
                }
            ],
            "overall_voice_score": 0.50,
            "overall_notes": "",
        })

        result = await character_specialist.run(char_context)
        # Should override "pass" because voice_consistent is False
        assert result["verdict"] == "fail_voice"

    @pytest.mark.asyncio
    async def test_action_overrides_voice(self, character_specialist, char_context, mock_router):
        """fail_action is more severe and should override fail_voice."""
        mock_router.complete_structured = AsyncMock(return_value={
            "verdict": "pass",
            "character_analyses": [
                {
                    "character_name": "Ben Skywalker",
                    "voice_consistent": False,
                    "actions_consistent": False,
                    "knowledge_respected": True,
                    "notes": "Both voice and action issues.",
                }
            ],
            "overall_voice_score": 0.20,
            "overall_notes": "",
        })

        result = await character_specialist.run(char_context)
        assert result["verdict"] == "fail_action"

    @pytest.mark.asyncio
    async def test_context_formatting(self, character_specialist, char_context):
        """Verify context includes character profiles and voices."""
        formatted = character_specialist._format_context(char_context)
        assert "Character Profiles" in formatted
        assert "Ben Skywalker" in formatted
        assert "Voice Sheets" in formatted or "character_voices" in formatted.lower()
        assert "Prose to Evaluate" in formatted

    @pytest.mark.asyncio
    async def test_result_structure(self, character_specialist, char_context, mock_router):
        mock_router.complete_structured = AsyncMock(return_value={
            "verdict": "pass",
            "character_analyses": [],
            "overall_voice_score": 1.0,
            "overall_notes": "",
        })
        result = await character_specialist.run(char_context)
        assert "verdict" in result
        assert "character_analyses" in result
        assert "overall_voice_score" in result
        assert "overall_notes" in result

    def test_role_is_character_specialist(self, character_specialist):
        assert character_specialist.role == "character_specialist"
