"""Tests for the AdaptiveRevisionPipeline."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.revision.adaptive_revision import (
    AdaptiveRevisionPipeline,
    DialoguePolishEditor,
    WorldbuildingCoherenceReviewer,
)


@pytest.fixture
def ledger(tmp_path):
    from src.run_ledger import RunLedger
    rl = RunLedger(db_path=str(tmp_path / "test_ledger.db"))
    yield rl
    rl.close()


@pytest.fixture
def adaptive_pipeline(mock_router, ledger):
    return AdaptiveRevisionPipeline(mock_router, ledger)


@pytest.fixture
def base_context():
    return {
        "scene_card": {
            "chapter_number": 1,
            "scene_number": 1,
            "structural_phase": "setup",
            "pov_character": "Ben",
            "canon_elements_needed": [],
        },
        "story_state_summary": "",
        "prior_chapter_summary": "",
        "character_voices": "",
        "negative_constraints": "",
        "quality_flags": [],
    }


@pytest.fixture
def dialogue_heavy_prose():
    """Prose with >25% dialogue lines."""
    return (
        '"I need you to listen," Ben said.\n'
        '"I always listen," Kira replied.\n'
        '"Not like this." He paced the room.\n'
        '"Then tell me what\'s different."\n'
        '"Everything." Ben stopped at the window.\n'
        '"That\'s not helpful." She crossed her arms.\n'
        '"I know." He turned to face her.\n'
        '"So help me understand." She stepped closer.\n'
        'The silence stretched between them.\n'
        '"Fine," he said at last. "It started three weeks ago."\n'
    )


@pytest.fixture
def narration_heavy_prose():
    """Prose with minimal dialogue."""
    return (
        "Ben walked through the corridor. The lights flickered overhead. "
        "He could hear the hum of the ship's engines. The deck plating "
        "vibrated under his boots. Something felt wrong about this place. "
        "The air tasted metallic. He checked his chrono — three hours "
        "until they reached the coordinates. Three hours to prepare."
    )


class TestDialoguePolishEditor:

    def test_role(self, mock_router):
        editor = DialoguePolishEditor(mock_router)
        assert editor.role == "dialogue_polish_editor"

    def test_format_context_includes_prose(self, mock_router, dialogue_heavy_prose):
        editor = DialoguePolishEditor(mock_router)
        context = editor._format_context({"prose": dialogue_heavy_prose})
        assert "I need you to listen" in context

    def test_parse_response(self, mock_router):
        editor = DialoguePolishEditor(mock_router)
        result = editor._parse_response("Revised prose here.", {})
        assert result == {"prose": "Revised prose here."}


class TestWorldbuildingCoherenceReviewer:

    def test_role(self, mock_router):
        reviewer = WorldbuildingCoherenceReviewer(mock_router)
        assert reviewer.role == "worldbuilding_coherence_reviewer"

    def test_format_context_includes_canon_elements(self, mock_router):
        reviewer = WorldbuildingCoherenceReviewer(mock_router)
        context = reviewer._format_context({
            "prose": "Some prose.",
            "scene_card": {"canon_elements_needed": ["Jedi Temple", "Force Ghost"]},
        })
        assert "Jedi Temple" in context
        assert "Force Ghost" in context


class TestAdaptiveRevisionPipeline:

    @pytest.mark.asyncio
    async def test_bands_1_to_3_always_run(self, adaptive_pipeline, narration_heavy_prose, base_context):
        """Bands 1-3 always execute."""
        call_count = 0

        async def mock_complete(role, messages, **kwargs):
            nonlocal call_count
            call_count += 1
            return f"Revised prose from band {call_count}"

        adaptive_pipeline.router.complete = AsyncMock(side_effect=mock_complete)

        result = await adaptive_pipeline.run(narration_heavy_prose, base_context)

        assert "structural_continuity" in result["bands_applied"]
        assert "scene_emotion" in result["bands_applied"]
        assert "line_copy" in result["bands_applied"]
        assert len(result["bands_applied"]) >= 3

    @pytest.mark.asyncio
    async def test_band4_runs_when_dialogue_heavy(self, adaptive_pipeline, dialogue_heavy_prose, base_context):
        """Band 4 runs when dialogue ratio > 0.25."""
        adaptive_pipeline.router.complete = AsyncMock(return_value="Revised prose")

        result = await adaptive_pipeline.run(dialogue_heavy_prose, base_context)

        assert "dialogue_polish" in result["bands_applied"]

    @pytest.mark.asyncio
    async def test_band4_skips_when_narration_heavy(self, adaptive_pipeline, narration_heavy_prose, base_context):
        """Band 4 skips when dialogue ratio <= 0.25."""
        adaptive_pipeline.router.complete = AsyncMock(return_value="Revised prose")

        # Add quality metrics that would otherwise trigger band 4
        base_context["quality_metrics"] = {"voice": {"voice_fidelity_score": 0.5}}

        result = await adaptive_pipeline.run(narration_heavy_prose, base_context)

        assert "dialogue_polish" not in result["bands_applied"]

    @pytest.mark.asyncio
    async def test_band5_runs_when_canon_elements(self, adaptive_pipeline, narration_heavy_prose, base_context):
        """Band 5 runs when canon_elements_needed present."""
        adaptive_pipeline.router.complete = AsyncMock(return_value="Revised prose")

        base_context["scene_card"]["canon_elements_needed"] = ["Jedi Temple", "Lightsaber"]

        result = await adaptive_pipeline.run(narration_heavy_prose, base_context)

        assert "worldbuilding_coherence" in result["bands_applied"]

    @pytest.mark.asyncio
    async def test_band5_skips_when_no_canon(self, adaptive_pipeline, narration_heavy_prose, base_context):
        """Band 5 skips when no canon_elements_needed."""
        adaptive_pipeline.router.complete = AsyncMock(return_value="Revised prose")

        base_context["scene_card"]["canon_elements_needed"] = []

        result = await adaptive_pipeline.run(narration_heavy_prose, base_context)

        assert "worldbuilding_coherence" not in result["bands_applied"]

    @pytest.mark.asyncio
    async def test_all_five_bands(self, adaptive_pipeline, dialogue_heavy_prose, base_context):
        """All 5 bands run when conditions are met."""
        adaptive_pipeline.router.complete = AsyncMock(return_value="Revised prose")

        base_context["scene_card"]["canon_elements_needed"] = ["Force Ghost"]

        result = await adaptive_pipeline.run(dialogue_heavy_prose, base_context)

        assert "structural_continuity" in result["bands_applied"]
        assert "scene_emotion" in result["bands_applied"]
        assert "line_copy" in result["bands_applied"]
        assert "dialogue_polish" in result["bands_applied"]
        assert "worldbuilding_coherence" in result["bands_applied"]
        assert len(result["bands_applied"]) == 5

    @pytest.mark.asyncio
    async def test_result_structure(self, adaptive_pipeline, narration_heavy_prose, base_context):
        """Result has correct structure."""
        adaptive_pipeline.router.complete = AsyncMock(return_value="Revised prose")

        result = await adaptive_pipeline.run(narration_heavy_prose, base_context)

        assert "prose" in result
        assert "bands_applied" in result
        assert "band_results" in result
        assert isinstance(result["bands_applied"], list)
        assert isinstance(result["band_results"], list)
        assert len(result["bands_applied"]) == len(result["band_results"])

    def test_should_run_band4_logic(self, adaptive_pipeline, dialogue_heavy_prose, narration_heavy_prose):
        """Test band 4 decision logic directly."""
        # Dialogue heavy, no metrics -> should run
        assert adaptive_pipeline._should_run_band4(dialogue_heavy_prose) is True

        # Narration heavy -> should not run
        assert adaptive_pipeline._should_run_band4(narration_heavy_prose) is False

        # Dialogue heavy, high voice score -> should not run
        metrics = {"voice": {"voice_fidelity_score": 0.9}}
        assert adaptive_pipeline._should_run_band4(dialogue_heavy_prose, metrics) is False

    def test_should_run_band5_logic(self, adaptive_pipeline):
        """Test band 5 decision logic directly."""
        # Canon elements present, no metrics -> should run
        context = {"scene_card": {"canon_elements_needed": ["Lightsaber"]}}
        assert adaptive_pipeline._should_run_band5(context) is True

        # No canon elements -> should not run
        context = {"scene_card": {"canon_elements_needed": []}}
        assert adaptive_pipeline._should_run_band5(context) is False
