"""Tests for the SeedBuilder agent."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.seed_builder import SeedBuilder


def _make_valid_seed():
    """Create a minimal valid concept seed for testing."""
    return {
        "meta": {
            "project_title": "Test Novel",
            "project_scope": "standalone",
            "franchise": "Original",
            "canon_status": "original",
            "era": "Contemporary",
            "tone": "character_study",
            "target_word_count": 80000,
            "target_chapters": 25,
            "pov_structure": "Single POV",
        },
        "premise": {
            "what_if": "What if a retired detective discovered her own daughter was behind the cold case she never solved?",
            "central_dramatic_question": "Can she choose justice over family?",
            "logline": "A retired detective reopens a cold case and discovers her estranged daughter is the prime suspect.",
        },
        "conflict": {
            "primary_antagonistic_force": {
                "type": "External",
                "identity": "Maya Chen (daughter)",
                "motivation": "Maya believes the victim deserved what happened and has built a new life she'll do anything to protect.",
                "escalation": "From avoidance to manipulation to direct confrontation as the detective gets closer to the truth and Maya realizes her mother won't stop.",
            },
            "secondary_pressures": [
                "The detective's former partner who wants the case to stay cold",
                "The victim's family demanding answers after twenty years",
            ],
            "lock_in_mechanism": "DNA evidence links Maya to the scene — the detective can't un-see what she's found.",
        },
        "theme": {
            "thematic_premise": "Justice without mercy destroys; mercy without justice enables.",
            "thematic_argument": "The novel tests this through a mother forced to choose between institutional justice and personal loyalty, ultimately arguing that true justice requires understanding the full context of why people act, not just what they did.",
            "how_each_arc_tests_theme": {
                "Detective Lin": "Tests the theme by forcing her to apply her lifelong principles to her own family.",
                "Maya Chen": "Tests the theme from the other side — was her act justified by circumstances?",
            },
        },
        "protagonist_arc_type": "change",
        "ensemble_cast": [
            {
                "name": "Detective Lin",
                "role": "Protagonist",
                "age": "58",
                "three_dimensions": {
                    "surface": "Methodical, principled, quietly commanding. The detective everyone trusts to get it right.",
                    "backstory_inner_demons": "Failed her daughter by choosing the job over family for twenty years. The guilt drives her perfectionism.",
                    "action_under_pressure": "Retreats into procedure and evidence when emotions threaten to overwhelm her judgment.",
                },
                "weiland_arc": {
                    "lie_believed": "If I follow the evidence wherever it leads, justice will be served and that's all that matters.",
                    "ghost": "The night she chose a stakeout over her daughter's recital — the last time Maya asked for her presence.",
                    "want": "To solve the case and prove she's still the best detective.",
                    "need": "To accept that justice is not the same as truth, and that she owes her daughter more than procedure.",
                    "arc_type": "positive_change",
                    "arc_summary": "From rigid procedural justice to contextual understanding",
                    "arc_phase_map": {
                        "lie_established": "Chapter 1",
                        "lie_reinforced": "Chapter 5",
                        "lie_challenged": "Chapter 12",
                        "moment_of_truth": "Chapter 20",
                        "new_truth_demonstrated": "Chapter 23",
                        "arc_resolved": "Chapter 25",
                    },
                },
            },
            {
                "name": "Maya Chen",
                "role": "Antagonist",
                "age": "32",
                "three_dimensions": {
                    "surface": "Warm, successful, the person everyone wishes they could be. Built her life from scratch after a traumatic youth.",
                    "backstory_inner_demons": "Carries the weight of what she did and the rage at the mother who wasn't there when it mattered.",
                    "action_under_pressure": "Manipulates through charm first, then escalates to threats when cornered.",
                },
                "weiland_arc": {
                    "lie_believed": "I had no choice. Anyone in my position would have done the same.",
                    "ghost": "The night the victim attacked her and no one came to help.",
                    "want": "To keep her new life intact.",
                    "need": "To stop running from what happened.",
                    "arc_type": "negative",
                },
            },
        ],
        "canon_constraints": {
            "continuity": "Original universe",
            "canon_preserved": [],
            "canon_overridden": [],
            "style_constraints": ["American English"],
        },
        "voice_definition": {
            "pov_approach": "Close third person, locked to Detective Lin",
            "prose_register": "Literary crime fiction",
            "character_voices": {},
            "anti_slop_rules": [],
            "anti_patterns": [],
        },
        "subplots": [],
        "hooks": [],
        "revelation_schedule": [],
        "scene_cards": [],
        "terminology_registry": [],
        "stress_test_scores": {"overall": None},
    }


class TestSeedBuilderFormatting:
    """Test the SeedBuilder context formatting."""

    def test_format_context_includes_summary(self, mock_router):
        builder = SeedBuilder(mock_router)
        summary = "This is my novel about a detective."
        formatted = builder._format_context({"summary_text": summary})

        assert "This is my novel about a detective." in formatted
        assert "Planning Manuscript" in formatted
        assert "concept seed json" in formatted.lower()

    def test_format_fixup_includes_failures(self, mock_router):
        builder = SeedBuilder(mock_router)
        formatted = builder._format_fixup_context(
            summary="My novel summary",
            current_seed={"meta": {"project_title": "Test"}},
            failures=["meta: missing franchise", "premise: missing what_if"],
        )

        assert "missing franchise" in formatted
        assert "missing what_if" in formatted
        assert "Compliance Failures" in formatted
        assert '"project_title": "Test"' in formatted


class TestSeedBuilderBuild:
    """Test the build_seed workflow."""

    @pytest.mark.asyncio
    async def test_build_seed_extracts_structure(self):
        """LLM returns a structured seed with required fields populated."""
        valid_seed = _make_valid_seed()

        router = MagicMock()
        router.complete_structured = AsyncMock(return_value=valid_seed)

        builder = SeedBuilder(router)
        seed, report = await builder.build_seed("A detective novel about...", max_retries=0)

        assert isinstance(seed, dict)
        assert seed["meta"]["project_title"] == "Test Novel"
        assert seed["premise"]["what_if"].startswith("What if")
        assert len(seed["ensemble_cast"]) == 2
        assert seed["ensemble_cast"][0]["weiland_arc"]["arc_type"] == "positive_change"

    @pytest.mark.asyncio
    async def test_build_seed_retries_on_incomplete(self):
        """Incomplete seed triggers fix-up calls with failures."""
        incomplete = {"meta": {"project_title": "Test"}}
        better_seed = _make_valid_seed()

        router = MagicMock()
        # Initial call returns incomplete, all fix-up calls return better seed
        router.complete_structured = AsyncMock(
            side_effect=[incomplete, better_seed, better_seed]
        )

        builder = SeedBuilder(router)
        seed, report = await builder.build_seed("A detective novel about...", max_retries=2)

        # Should have retried (initial + up to 2 fix-ups)
        assert router.complete_structured.call_count >= 2
        assert seed["meta"]["project_title"] == "Test Novel"

    @pytest.mark.asyncio
    async def test_build_seed_returns_report_on_failure(self):
        """If all retries fail, return the best seed and failure report."""
        bad_seed = {"meta": {"project_title": "Test"}}

        router = MagicMock()
        router.complete_structured = AsyncMock(return_value=bad_seed)

        builder = SeedBuilder(router)
        seed, report = await builder.build_seed("A detective novel...", max_retries=1)

        assert not report.passed
        assert len(report.critical_failures) > 0

    @pytest.mark.asyncio
    async def test_build_seed_handles_non_dict_response(self):
        """If LLM returns non-dict, treat as empty seed."""
        router = MagicMock()
        router.complete_structured = AsyncMock(return_value="not a dict")

        builder = SeedBuilder(router)
        seed, report = await builder.build_seed("Some summary", max_retries=0)

        assert not report.passed
