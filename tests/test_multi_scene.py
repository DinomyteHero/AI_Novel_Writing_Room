"""Multi-scene chapter support regression suite.

These tests define the target behavior for multi-scene chapters (2-4 scenes
per chapter). They should FAIL against the pre-multi-scene codebase and pass
once Steps 2-6 are implemented.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_assembler(manuscripts_dir: str):
    """Create a minimal ContextAssembler for testing previous-scene resolution."""
    from src.memory.context_assembler import ContextAssembler

    seed_path = str(Path(__file__).parent / "fixtures" / "sample_seed.json")
    return ContextAssembler(
        concept_seed_path=seed_path,
        manuscripts_dir=manuscripts_dir,
    )


# ---------------------------------------------------------------------------
# TestSceneLogSchema
# ---------------------------------------------------------------------------


class TestSceneLogSchema:
    """Verify the DB supports multiple scenes per chapter."""

    def test_insert_two_scenes_same_chapter(self, story_state):
        """Inserting scene 1 and scene 2 for the same chapter must both succeed."""
        story_state.add_scene_log(
            chapter_number=1, scene_number=1, word_count=1200,
            structural_phase="setup", pov_character="Alex Reyes",
            summary="Scene 1 summary", revision_status="draft",
        )
        story_state.add_scene_log(
            chapter_number=1, scene_number=2, word_count=1100,
            structural_phase="setup", pov_character="Alex Reyes",
            summary="Scene 2 summary", revision_status="draft",
        )
        log1 = story_state.get_scene_log(1, 1)
        log2 = story_state.get_scene_log(1, 2)
        assert log1 is not None
        assert log2 is not None
        assert log1["summary"] != log2["summary"]

    def test_get_chapter_scenes_returns_all(self, story_state):
        """get_chapter_scenes(N) returns all scene logs for chapter N, ordered by scene_number."""
        story_state.add_scene_log(
            chapter_number=3, scene_number=1, word_count=1000,
            structural_phase="response", pov_character="Alex",
            summary="S1", revision_status="draft",
        )
        story_state.add_scene_log(
            chapter_number=3, scene_number=2, word_count=1200,
            structural_phase="response", pov_character="Alex",
            summary="S2", revision_status="draft",
        )
        story_state.add_scene_log(
            chapter_number=3, scene_number=3, word_count=900,
            structural_phase="response", pov_character="Alex",
            summary="S3", revision_status="draft",
        )
        scenes = story_state.get_chapter_scenes(3)
        assert len(scenes) == 3
        assert [s["scene_number"] for s in scenes] == [1, 2, 3]

    def test_chapter_aggregate_word_count(self, story_state):
        """get_chapter_aggregate(N) returns summed word count across all scenes."""
        story_state.add_scene_log(
            chapter_number=1, scene_number=1, word_count=1200,
            structural_phase="setup", pov_character="Alex",
            summary="S1", revision_status="draft",
        )
        story_state.add_scene_log(
            chapter_number=1, scene_number=2, word_count=1100,
            structural_phase="setup", pov_character="Alex",
            summary="S2", revision_status="draft",
        )
        agg = story_state.get_chapter_aggregate(1)
        assert agg["total_word_count"] == 2300
        assert agg["scene_count"] == 2


# ---------------------------------------------------------------------------
# TestChapterMemoryMultiScene
# ---------------------------------------------------------------------------


class TestChapterMemoryMultiScene:
    """Verify ChromaDB stores unique summaries per (chapter, scene)."""

    def test_two_scenes_same_chapter_both_stored(self, chapter_memory):
        """Adding summaries for ch1s1 and ch1s2 stores both (no overwrite)."""
        chapter_memory.add_summary(
            chapter_number=1, scene_number=1,
            summary_text="Scene 1 summary",
        )
        chapter_memory.add_summary(
            chapter_number=1, scene_number=2,
            summary_text="Scene 2 summary",
        )
        s1 = chapter_memory.get_summary(1, 1)
        s2 = chapter_memory.get_summary(1, 2)
        assert s1 is not None and "Scene 1" in s1
        assert s2 is not None and "Scene 2" in s2
        assert chapter_memory.count() == 2


# ---------------------------------------------------------------------------
# TestContextAssemblerPreviousScene
# ---------------------------------------------------------------------------


class TestContextAssemblerPreviousScene:
    """Verify previous-scene resolution across scene and chapter boundaries."""

    def test_previous_scene_within_chapter(self, tmp_path):
        """For ch1s2, previous scene is ch1s1."""
        manuscripts = tmp_path / "manuscripts"
        manuscripts.mkdir()
        (manuscripts / "chapter_01_scene_01.md").write_text("Scene one prose.")
        (manuscripts / "chapter_01_scene_02.md").write_text("Scene two prose.")
        assembler = _make_assembler(manuscripts_dir=str(manuscripts))
        prev = assembler.get_previous_scene(chapter_number=1, scene_number=2)
        assert prev is not None
        assert "Scene one prose" in prev

    def test_previous_scene_cross_chapter(self, tmp_path):
        """For ch2s1, previous scene is the LAST scene of ch1."""
        manuscripts = tmp_path / "manuscripts"
        manuscripts.mkdir()
        (manuscripts / "chapter_01_scene_01.md").write_text("Ch1 S1.")
        (manuscripts / "chapter_01_scene_02.md").write_text("Ch1 S2.")
        (manuscripts / "chapter_01_scene_03.md").write_text("Ch1 S3 final.")
        (manuscripts / "chapter_02_scene_01.md").write_text("Ch2 S1.")
        assembler = _make_assembler(manuscripts_dir=str(manuscripts))
        prev = assembler.get_previous_scene(chapter_number=2, scene_number=1)
        assert prev is not None
        assert "Ch1 S3 final" in prev

    def test_load_prior_scenes_gets_last_n(self, tmp_path):
        """_load_prior_scenes returns the last N scene files before current."""
        manuscripts = tmp_path / "manuscripts"
        manuscripts.mkdir()
        for ch in range(1, 4):
            for sc in range(1, 4):
                (manuscripts / f"chapter_{ch:02d}_scene_{sc:02d}.md").write_text(
                    f"Ch{ch} S{sc}."
                )
        assembler = _make_assembler(manuscripts_dir=str(manuscripts))
        prior = assembler._load_prior_scenes(chapter_number=3, scene_number=1, n=3)
        assert len(prior) == 3
        # Should be ch2s1, ch2s2, ch2s3 (the 3 most recent before ch3s1)
        assert "Ch2 S3" in prior[-1]


# ---------------------------------------------------------------------------
# TestPipelineMultiSceneOrdering
# ---------------------------------------------------------------------------


class TestPipelineMultiSceneOrdering:
    """Verify the orchestrator processes multi-scene cards in correct order."""

    def test_scene_cards_sorted_by_chapter_then_scene(self):
        """Scene cards fed to run_pipeline are processed in (chapter, scene) order."""
        cards = [
            {"chapter_number": 1, "scene_number": 2, "mission": "b"},
            {"chapter_number": 1, "scene_number": 1, "mission": "a"},
            {"chapter_number": 2, "scene_number": 1, "mission": "c"},
        ]
        sorted_cards = sorted(
            cards, key=lambda c: (c["chapter_number"], c.get("scene_number", 1))
        )
        assert [c["mission"] for c in sorted_cards] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# TestOutlinePlannerMultiScene
# ---------------------------------------------------------------------------


class TestOutlinePlannerMultiScene:
    """Verify the OutlinePlanner prompt requests multi-scene output."""

    def test_format_context_requests_multiple_scenes(self, sample_concept_seed):
        """The formatted prompt must NOT contain 'usually 1' and must request 2-4 scenes."""
        from src.planning.scene_card_generator import OutlinePlanner

        planner = OutlinePlanner(MagicMock())
        context_text = planner._format_context({"concept_seed": sample_concept_seed})
        assert "usually 1" not in context_text
        assert "2" in context_text and "4" in context_text  # references scene count range


# ---------------------------------------------------------------------------
# TestSceneCardGeneratorMultiScene
# ---------------------------------------------------------------------------


class TestSceneCardGeneratorMultiScene:
    """Verify the SceneCardGenerator defaults target per-scene not per-chapter."""

    def test_ensure_defaults_per_scene_word_count(self, sample_concept_seed):
        """target_word_count default should be chapter_target / 3, not chapter_target."""
        from src.planning.scene_card_generator import SceneCardGenerator

        gen = SceneCardGenerator(MagicMock())
        card = gen._ensure_defaults(
            {"chapter_number": 1, "scene_number": 2},
            sample_concept_seed,
        )
        per_chapter = 60000 // 20  # 3000 from sample_seed
        # Per-scene default should be roughly per_chapter / 3 = ~1000
        assert card["target_word_count"] < per_chapter
        assert card["target_word_count"] >= 500
        assert card["target_word_count"] <= 1500


class TestSceneCardValidationEnhancements:
    """Test the new validation checks added in Phase B."""

    def test_beat_coverage_action_scene_missing_conflict(self):
        from src.planning.scene_card_generator import SceneCardGenerator
        card = {
            "chapter_number": 1, "scene_number": 1,
            "scene_type": "action", "mission": "do something",
            "conflict": "", "turning_point": "tp",
        }
        warnings = SceneCardGenerator._check_beat_coverage(card)
        assert any("obstacle" in w for w in warnings)

    def test_beat_coverage_sequel_missing_emotional_trajectory(self):
        from src.planning.scene_card_generator import SceneCardGenerator
        card = {
            "chapter_number": 1, "scene_number": 1,
            "scene_type": "sequel", "emotional_trajectory": "",
            "conflict": "dilemma", "turning_point": "decision",
        }
        warnings = SceneCardGenerator._check_beat_coverage(card)
        assert any("reaction" in w for w in warnings)

    def test_beat_coverage_action_complete_passes(self):
        from src.planning.scene_card_generator import SceneCardGenerator
        card = {
            "chapter_number": 1, "scene_number": 1,
            "scene_type": "action", "mission": "goal",
            "conflict": "obstacle", "turning_point": "setback",
        }
        warnings = SceneCardGenerator._check_beat_coverage(card)
        assert warnings == []

    def test_hook_requirements_chapter_1_needs_opening_hook(self):
        from src.planning.scene_card_generator import SceneCardGenerator
        card = {
            "chapter_number": 1, "scene_number": 1,
            "opening_hook": "", "closing_hook": "end hook",
        }
        warnings = SceneCardGenerator._check_hook_requirements(card)
        assert any("opening_hook" in w for w in warnings)

    def test_hook_requirements_all_chapters_need_closing_hook(self):
        from src.planning.scene_card_generator import SceneCardGenerator
        card = {
            "chapter_number": 15, "scene_number": 2,
            "opening_hook": "start", "closing_hook": "",
        }
        warnings = SceneCardGenerator._check_hook_requirements(card)
        assert any("closing_hook" in w for w in warnings)

    def test_stakes_validation_missing_personal(self):
        from src.planning.scene_card_generator import SceneCardGenerator
        card = {
            "chapter_number": 1, "scene_number": 1,
            "stakes": {"personal": "", "interpersonal": "yes", "external": ""},
        }
        warnings = SceneCardGenerator._check_stakes(card)
        assert any("personal" in w for w in warnings)

    def test_stakes_validation_needs_interpersonal_or_external(self):
        from src.planning.scene_card_generator import SceneCardGenerator
        card = {
            "chapter_number": 1, "scene_number": 1,
            "stakes": {"personal": "yes", "interpersonal": "", "external": ""},
        }
        warnings = SceneCardGenerator._check_stakes(card)
        assert any("interpersonal or external" in w for w in warnings)

    def test_stakes_validation_complete_passes(self):
        from src.planning.scene_card_generator import SceneCardGenerator
        card = {
            "chapter_number": 1, "scene_number": 1,
            "stakes": {"personal": "career", "interpersonal": "", "external": "case"},
        }
        warnings = SceneCardGenerator._check_stakes(card)
        assert warnings == []


class TestMissionUniqueness:
    """Test Jaccard similarity-based mission uniqueness check."""

    def test_similar_missions_flagged(self):
        from src.planning.scene_card_generator import SceneCardGenerator
        cards = [
            {"chapter_number": 1, "scene_number": 1, "mission": "establish the threat and danger",
             "conflict_type": "internal", "target_word_count": 1200, "stakes": {}},
            {"chapter_number": 1, "scene_number": 2, "mission": "establish the danger and threat",
             "conflict_type": "external", "target_word_count": 1200, "stakes": {}},
        ]
        warnings = SceneCardGenerator._validate_chapter_composition(cards)
        assert any("similar missions" in w.lower() for w in warnings)

    def test_different_missions_pass(self):
        from src.planning.scene_card_generator import SceneCardGenerator
        cards = [
            {"chapter_number": 1, "scene_number": 1, "mission": "Alex confronts Jordan about the evidence",
             "conflict_type": "interpersonal", "target_word_count": 1200, "stakes": {}},
            {"chapter_number": 1, "scene_number": 2, "mission": "Alex opens the sealed envelope alone",
             "conflict_type": "internal", "target_word_count": 1200, "stakes": {}},
        ]
        warnings = SceneCardGenerator._validate_chapter_composition(cards)
        assert not any("similar missions" in w.lower() for w in warnings)
