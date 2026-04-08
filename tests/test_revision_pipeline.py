"""Tests for the three-band RevisionPipeline."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.revision.pipeline import RevisionPipeline
from src.run_ledger import RunLedger


@pytest.fixture
def revision_ledger(temp_dir):
    """RunLedger for revision tests."""
    from pathlib import Path
    ledger = RunLedger(db_path=str(Path(temp_dir) / "revision_ledger.db"))
    yield ledger
    ledger.close()


@pytest.fixture
def revision_pipeline(mock_router, revision_ledger):
    """RevisionPipeline with mock router and temp ledger."""
    return RevisionPipeline(mock_router, revision_ledger)


@pytest.fixture
def revision_context(sample_scene_card):
    """Context for the revision pipeline."""
    return {
        "scene_card": sample_scene_card,
        "story_state_summary": "",
        "prior_chapter_summary": "",
        "character_voices": "Ben: informal, precise.",
        "negative_constraints": "Avoid: delve, tapestry, testament.",
        "quality_flags": ["2 AI-tell words detected"],
    }


class TestRevisionPipeline:
    @pytest.mark.asyncio
    async def test_three_bands_run_sequentially(
        self, revision_pipeline, revision_context, mock_router
    ):
        """Verify all three bands run and return prose."""
        # Mock each band's router call to return modified prose
        call_count = 0

        async def mock_complete(role, messages, **kwargs):
            nonlocal call_count
            call_count += 1
            return f"Revised prose from band {call_count}"

        mock_router.complete = AsyncMock(side_effect=mock_complete)

        result = await revision_pipeline.run("Original prose.", revision_context)

        assert "prose" in result
        assert "bands_applied" in result
        assert "band_results" in result
        assert len(result["bands_applied"]) == 3
        assert result["bands_applied"] == [
            "structural_continuity",
            "scene_emotion",
            "line_copy",
        ]

    @pytest.mark.asyncio
    async def test_prose_passes_through_bands(
        self, revision_pipeline, revision_context, mock_router
    ):
        """Verify prose from each band feeds into the next."""
        outputs = []

        async def track_complete(role, messages, **kwargs):
            # Extract the prose from the user message
            user_msg = messages[-1]["content"]
            outputs.append(user_msg)
            return f"Output from {role}"

        mock_router.complete = AsyncMock(side_effect=track_complete)

        result = await revision_pipeline.run("Starting prose.", revision_context)

        # Each band should receive the output of the previous band
        # Band 1 receives "Starting prose." in its context
        assert "Starting prose." in outputs[0]
        # Band 2 receives Band 1's output
        assert "Output from structural_continuity_reviewer" in outputs[1]
        # Band 3 receives Band 2's output
        assert "Output from scene_emotion_reviewer" in outputs[2]
        # Final output is Band 3's result
        assert "Output from line_copy_editor" in result["prose"]

    @pytest.mark.asyncio
    async def test_ledger_events_emitted(
        self, revision_pipeline, revision_context, revision_ledger, mock_router
    ):
        """Verify revision_band_start/complete events emitted for each band."""
        mock_router.complete = AsyncMock(return_value="Revised prose.")

        await revision_pipeline.run("Test prose.", revision_context)

        starts = revision_ledger.get_events(event_type="revision_band_start")
        completes = revision_ledger.get_events(event_type="revision_band_complete")

        assert len(starts) == 3
        assert len(completes) == 3

        # Check band names in order
        start_bands = [e["payload"]["band_name"] for e in starts]
        assert start_bands == ["structural_continuity", "scene_emotion", "line_copy"]

    @pytest.mark.asyncio
    async def test_band_results_contain_metadata(
        self, revision_pipeline, revision_context, mock_router
    ):
        """Verify each band result has duration and word counts."""
        mock_router.complete = AsyncMock(return_value="Some revised text here.")

        result = await revision_pipeline.run("Original text here.", revision_context)

        for band_meta in result["band_results"]:
            assert "band_name" in band_meta
            assert "duration_ms" in band_meta
            assert "input_words" in band_meta
            assert "output_words" in band_meta
            assert band_meta["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_band_agent_roles(self, revision_pipeline):
        """Verify band agents have correct roles."""
        assert revision_pipeline.band1.role == "structural_continuity_reviewer"
        assert revision_pipeline.band2.role == "scene_emotion_reviewer"
        assert revision_pipeline.band3.role == "line_copy_editor"

    @pytest.mark.asyncio
    async def test_empty_prose(
        self, revision_pipeline, revision_context, mock_router
    ):
        """Pipeline handles empty prose without crashing."""
        mock_router.complete = AsyncMock(return_value="")

        result = await revision_pipeline.run("", revision_context)
        assert "prose" in result
        assert len(result["bands_applied"]) == 3
