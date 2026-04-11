"""Tests for the Phase 1 ContextAssembler."""

from pathlib import Path

import pytest

from src.memory.context_assembler import ContextAssembler


class TestContextAssembler:
    """Test basic context assembly functionality.

    Uses the synthetic `sample_seed.json` fixture from `tests/fixtures/`.
    The lead character is "Alex Reyes" (slugified: `alex_reyes`); the
    supporting cast is Morgan Kade, Sam Okafor, and Dr. Elena Voss.
    """

    @pytest.fixture
    def assembler(self):
        concept_path = (
            Path(__file__).parent / "fixtures" / "sample_seed.json"
        )
        return ContextAssembler(
            concept_seed_path=str(concept_path),
            manuscripts_dir=str(Path(__file__).parent.parent / "data" / "manuscripts"),
        )

    def test_loads_concept_seed(self, assembler):
        assert assembler.concept_seed is not None
        assert assembler.concept_seed["meta"]["project_title"] == "Test Story"

    def test_bible_summary_contains_key_elements(self, assembler):
        summary = assembler.get_bible_summary()
        assert "Test Story" in summary
        assert "Original" in summary
        assert "Alex Reyes" in summary
        # The synthetic fixture's thematic premise mentions trust.
        assert "trust" in summary.lower()

    def test_bible_summary_includes_cast(self, assembler):
        summary = assembler.get_bible_summary()
        assert "Alex Reyes" in summary
        assert "Morgan Kade" in summary

    def test_bible_summary_includes_style_constraints(self, assembler):
        summary = assembler.get_bible_summary()
        # The synthetic fixture's style constraints mention American English.
        assert "American English" in summary

    def test_character_voices_returns_matching(self, assembler):
        voices = assembler.get_character_voices(["Alex Reyes"])
        assert "Alex Reyes" in voices
        # Alex's voice notes mention dry humor and deflection.
        assert "dry" in voices.lower() or "humor" in voices.lower()

    def test_character_voices_partial_name_match(self, assembler):
        voices = assembler.get_character_voices(["Alex"])
        assert "Alex Reyes" in voices

    def test_negative_constraints_loaded(self, assembler):
        constraints = assembler.get_negative_constraints()
        # These come from the global config/negative_constraints.yaml, not
        # the project seed — they are stable across projects.
        assert "delve" in constraints.lower()
        assert "tapestry" in constraints.lower()

    def test_assemble_includes_all_components(self, assembler, sample_scene_card):
        context = assembler.assemble(sample_scene_card)
        # Should contain bible summary
        assert "Test Story" in context
        # Should contain scene card
        assert "Scene Card" in context
        # Should contain constraints
        assert "Writing Constraints" in context

    def test_assemble_includes_character_voices(self, assembler, sample_scene_card):
        context = assembler.assemble(sample_scene_card)
        assert "Character Voices" in context
        # The synthetic scene card's POV character is Alex Reyes.
        assert "Alex Reyes" in context

    def test_no_previous_chapter_for_chapter_1(self, assembler, sample_scene_card):
        prev = assembler.get_previous_chapter(1)
        assert prev is None

    def test_phase1_includes_voice_rules(self, assembler, sample_scene_card):
        """Phase 1 assembly must inject voice_definition from the concept seed."""
        context = assembler._assemble_phase1(sample_scene_card)
        assert "Voice Rules (MANDATORY)" in context
        # Anti-slop rules from the sample seed
        assert "a sense of" in context.lower()
        # Character voice guidance
        assert "Alex Reyes" in context
        # Anti-patterns
        assert "prophecy" in context.lower() or "destiny" in context.lower()
