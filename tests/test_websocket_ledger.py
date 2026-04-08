"""Tests for WebSocketLedger event broadcasting."""

import asyncio

import pytest

from src.ui.websocket_ledger import WebSocketLedger


@pytest.fixture
def event_queue():
    return asyncio.Queue(maxsize=100)


@pytest.fixture
def ws_ledger(temp_dir, event_queue):
    from pathlib import Path

    db_path = str(Path(temp_dir) / "test_ws_ledger.db")
    ledger = WebSocketLedger(db_path=db_path, queue=event_queue)
    yield ledger
    ledger.close()


def test_emit_writes_to_sqlite_and_queue(ws_ledger, event_queue):
    """emit() writes to both SQLite (inherited) and the asyncio queue."""
    event_id = ws_ledger.emit(
        "pipeline_start",
        chapter_number=None,
        scene_number=None,
        payload={"total_scenes": 5},
    )
    assert event_id >= 1

    # SQLite has the event
    events = ws_ledger.get_events(event_type="pipeline_start")
    assert len(events) == 1
    assert events[0]["payload"]["total_scenes"] == 5

    # Queue has the event
    assert not event_queue.empty()
    queued = event_queue.get_nowait()
    assert queued["event_type"] == "pipeline_start"
    assert queued["id"] == event_id
    assert queued["payload"]["total_scenes"] == 5
    assert "timestamp" in queued


def test_emit_with_all_fields(ws_ledger, event_queue):
    """emit() passes all fields to the queue."""
    ws_ledger.emit(
        "agent_complete",
        chapter_number=3,
        scene_number=2,
        agent_role="prose_stylist",
        payload={"duration_ms": 1500, "word_count": 2000},
    )

    queued = event_queue.get_nowait()
    assert queued["chapter_number"] == 3
    assert queued["scene_number"] == 2
    assert queued["agent_role"] == "prose_stylist"
    assert queued["payload"]["word_count"] == 2000


def test_emit_queue_full_does_not_crash(temp_dir):
    """When queue is full, emit() still writes to SQLite and doesn't raise."""
    from pathlib import Path

    tiny_queue = asyncio.Queue(maxsize=1)
    db_path = str(Path(temp_dir) / "test_full_queue.db")
    ledger = WebSocketLedger(db_path=db_path, queue=tiny_queue)

    # Fill the queue
    ledger.emit("pipeline_start", payload={"total_scenes": 1})
    assert tiny_queue.full()

    # Second emit should not crash
    event_id = ledger.emit("chapter_start", chapter_number=1, payload={"mission": "test"})
    assert event_id >= 1

    # SQLite still has both events
    events = ledger.get_events()
    assert len(events) == 2

    # Queue only has the first
    assert tiny_queue.qsize() == 1

    ledger.close()


def test_multiple_emits(ws_ledger, event_queue):
    """Multiple emit calls produce multiple queued events."""
    for i in range(5):
        ws_ledger.emit("chapter_start", chapter_number=i + 1, payload={"mission": f"ch{i+1}"})

    assert event_queue.qsize() == 5

    # Drain and verify ordering
    for i in range(5):
        ev = event_queue.get_nowait()
        assert ev["chapter_number"] == i + 1


def test_ledger_inherits_get_events(ws_ledger):
    """WebSocketLedger inherits all query methods from RunLedger."""
    ws_ledger.emit("gate_pass", chapter_number=1, payload={"verdict": "pass"})
    ws_ledger.emit("gate_fail", chapter_number=2, payload={"verdict": "fail_structural"})

    events = ws_ledger.get_events(event_type="gate_pass")
    assert len(events) == 1
    assert events[0]["payload"]["verdict"] == "pass"

    latest = ws_ledger.get_latest("gate_fail")
    assert latest is not None
    assert latest["chapter_number"] == 2
