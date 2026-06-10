"""Automatic chapter-close memo emission at chapter boundaries.

Rides ``runtime.revision_debt.enabled``: when the debt store is live the
orchestrator writes the operator's triage memo to ``<run_dir>/memos/`` as
each chapter closes, instead of waiting for a ``debt_cli memo chapter``
invocation. Memo failures warn (``chapter_memo_error``) and never abort.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.memory.story_state import StoryState
from src.orchestrator import Orchestrator
from src.pipeline.revision_debt import RevisionDebtStore
from src.run_ledger import RunLedger


def _make_orchestrator(
    tmp_path: Path, *, revision_debt_enabled: bool = True,
) -> tuple[Orchestrator, RunLedger]:
    ledger = RunLedger(db_path=str(tmp_path / "run_ledger.db"))
    orch = Orchestrator(
        router=MagicMock(),
        context_assembler=MagicMock(),
        ledger=ledger,
        manuscripts_dir=str(tmp_path / "chapters"),
        story_state=StoryState(str(tmp_path / "story_state.db")),
        runtime_flags={
            "runtime": {"revision_debt": {"enabled": revision_debt_enabled}}
        },
        revision_debt_store=RevisionDebtStore(
            db_path=str(tmp_path / "revision_debt.db")
        ),
    )
    return orch, ledger


def _cards() -> list[dict]:
    return [
        {"chapter_number": 1, "scene_number": 1},
        {"chapter_number": 1, "scene_number": 2},
        {"chapter_number": 2, "scene_number": 1},
    ]


def test_memo_written_only_at_chapter_boundary(tmp_path):
    orch, ledger = _make_orchestrator(tmp_path)
    memos_dir = tmp_path / "memos"
    cards = _cards()

    orch._maybe_write_chapter_memo(cards, 0)
    assert not (memos_dir / "chapter_01_close_memo.md").exists()

    orch._maybe_write_chapter_memo(cards, 1)
    assert (memos_dir / "chapter_01_close_memo.md").exists()
    assert (memos_dir / "chapter_01_close_memo.json").exists()

    orch._maybe_write_chapter_memo(cards, 2)
    assert (memos_dir / "chapter_02_close_memo.md").exists()

    events = ledger.get_events(event_type="chapter_memo_written")
    assert [e["chapter_number"] for e in events] == [1, 2]


def test_memo_skipped_when_revision_debt_off(tmp_path):
    orch, ledger = _make_orchestrator(tmp_path, revision_debt_enabled=False)

    orch._maybe_write_chapter_memo(_cards(), 1)

    assert not (tmp_path / "memos").exists()
    assert ledger.get_events(event_type="chapter_memo_written") == []


@pytest.mark.asyncio
async def test_run_pipeline_writes_memo_even_when_scene_fails(tmp_path):
    orch, ledger = _make_orchestrator(tmp_path)
    orch.run_chapter = AsyncMock(side_effect=RuntimeError("boom"))

    results = await orch.run_pipeline([{"chapter_number": 1, "scene_number": 1}])

    assert results[0]["status"] == "failed"
    assert (tmp_path / "memos" / "chapter_01_close_memo.md").exists()
    assert len(ledger.get_events(event_type="chapter_memo_written")) == 1
