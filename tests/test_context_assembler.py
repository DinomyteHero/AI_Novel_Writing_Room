"""Tests for the Phase 1 ContextAssembler."""

import json
from pathlib import Path

import pytest

from src.memory.context_assembler import ContextAssembler


class TestContextAssembler:
    """Test basic context assembly functionality."""

    @pytest.fixture
    def assembler(self):
        concept_path = (
            Path(__file__).parent.parent
            / "data" / "story_bibles" / "beyond_the_veil" / "concept_seed.json"
        )
        return ContextAssembler(
            concept_seed_path=str(concept_path),
            manuscripts_dir=str(Path(__file__).parent.parent / "data" / "manuscripts"),
        )

    def test_loads_concept_seed(self, assembler):
        assert assembler.concept_seed is not None
        assert assembler.concept_seed["meta"]["project_title"] == "Beyond the Veil"

    def test_bible_summary_contains_key_elements(self, assembler):
        summary = assembler.get_bible_summary()
        assert "Beyond the Veil" in summary
        assert "Star Wars" in summary
        assert "Ben Skywalker" in summary
        assert "collective willpower" in summary.lower() or "collective" in summary.lower()

    def test_bible_summary_includes_cast(self, assembler):
        summary = assembler.get_bible_summary()
        assert "Ben Skywalker" in summary
        assert "Jedi Scholar" in summary

    def test_bible_summary_includes_style_constraints(self, assembler):
        summary = assembler.get_bible_summary()
        assert "Human" in summary  # Star Wars capitalize rule

    def test_character_voices_returns_matching(self, assembler):
        voices = assembler.get_character_voices(["Ben Skywalker"])
        assert "Ben Skywalker" in voices
        assert "humor" in voices.lower() or "deflection" in voices.lower()

    def test_character_voices_partial_name_match(self, assembler):
        voices = assembler.get_character_voices(["Ben"])
        assert "Ben Skywalker" in voices

    def test_negative_constraints_loaded(self, assembler):
        constraints = assembler.get_negative_constraints()
        assert "delve" in constraints.lower()
        assert "tapestry" in constraints.lower()

    def test_assemble_includes_all_components(self, assembler, sample_scene_card):
        context = assembler.assemble(sample_scene_card)
        # Should contain bible summary
        assert "Beyond the Veil" in context
        # Should contain scene card
        assert "Scene Card" in context
        # Should contain constraints
        assert "Writing Constraints" in context

    def test_assemble_includes_character_voices(self, assembler, sample_scene_card):
        context = assembler.assemble(sample_scene_card)
        assert "Character Voices" in context
        assert "Ben Skywalker" in context

    def test_no_previous_chapter_for_chapter_1(self, assembler, sample_scene_card):
        prev = assembler.get_previous_chapter(1)
        assert prev is None
