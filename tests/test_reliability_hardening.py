"""Reliability-hardening regression tests.

Locks in the fixes that keep a long multi-chapter run alive:
- one scene's exception must not abort the remaining scenes (run_pipeline guard)
- a non-dict generation brief must not crash the drafter (type-confusion guard)
- empty drafter prose must emit a warn rather than silently saving a 0-word scene
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.orchestrator import Orchestrator
from src.run_ledger import RunLedger


@pytest.fixture
def ledger(temp_dir):
    _ledger = RunLedger(db_path=str(Path(temp_dir) / "test_ledger.db"))
    yield _ledger
    _ledger.close()


@pytest.fixture
def mock_assembler():
    assembler = MagicMock()
    assembler.get_bible_summary.return_value = "Test bible summary"
    assembler.assemble.return_value = "Test assembled context"
    assembler.get_pov_approach.return_value = "third_limited"
    assembler.get_franchise_profile_text.return_value = ""
    return assembler


def _build(mock_router, mock_assembler, ledger, temp_dir):
    async def fake_complete(agent_role, messages, *args, **kwargs):
        return " ".join(["word"] * 100)

    mock_router.complete = AsyncMock(side_effect=fake_complete)
    mock_router.complete_structured = AsyncMock(
        return_value={"scene_objective": "obj", "target_word_count": 100}
    )
    return Orchestrator(
        router=mock_router,
        context_assembler=mock_assembler,
        ledger=ledger,
        manuscripts_dir=str(Path(temp_dir) / "manuscripts"),
    )


async def test_run_pipeline_survives_one_failing_scene(
    mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
):
    orch = _build(mock_router, mock_assembler, ledger, temp_dir)

    cards = [
        {**sample_scene_card, "chapter_number": 1, "scene_number": 1},
        {**sample_scene_card, "chapter_number": 2, "scene_number": 1},
        {**sample_scene_card, "chapter_number": 3, "scene_number": 1},
    ]

    attempted = []

    async def fake_run_chapter(card):
        attempted.append(card["chapter_number"])
        if card["chapter_number"] == 2:
            raise RuntimeError("scene 2 boom")
        return {
            "chapter_number": card["chapter_number"],
            "scene_number": 1,
            "output_path": "x",
            "word_count": 100,
        }

    orch.run_chapter = fake_run_chapter

    results = await orch.run_pipeline(cards)

    # All three scenes attempted despite #2 raising.
    assert attempted == [1, 2, 3]
    assert len(results) == 3
    failed = [r for r in results if r.get("status") == "failed"]
    assert len(failed) == 1
    assert failed[0]["chapter_number"] == 2
    errs = [e for e in ledger.get_events() if e["event_type"] == "scene_error"]
    assert errs and "RuntimeError" in errs[0]["payload"].get("error", "")


async def test_non_dict_brief_does_not_crash_drafter(
    mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
):
    orch = _build(mock_router, mock_assembler, ledger, temp_dir)
    # PlotArchitect's model returns a top-level JSON array, not an object.
    mock_router.complete_structured = AsyncMock(return_value=[{"scene_objective": "x"}])

    result = await orch.run_chapter(sample_scene_card)

    # Coerced to {} -> drafter still ran and the scene saved.
    assert Path(result["output_path"]).exists()


async def test_empty_prose_emits_warn(
    mock_router, mock_assembler, ledger, temp_dir, sample_scene_card
):
    orch = _build(mock_router, mock_assembler, ledger, temp_dir)

    async def empty_complete(agent_role, messages, *args, **kwargs):
        return ""

    mock_router.complete = AsyncMock(side_effect=empty_complete)

    await orch.run_chapter(sample_scene_card)

    warns = [e for e in ledger.get_events() if e["event_type"] == "prose_empty"]
    assert warns
    assert warns[0]["payload"].get("level") == "warn"
