"""Tests for WebOrchestrator pause gate and milestone handling."""

import asyncio

import pytest

from src.ui.pipeline_manager import PipelineManager, PipelineState


@pytest.mark.asyncio
async def test_pipeline_manager_state_transitions():
    """PipelineManager transitions: idle -> running -> paused -> running -> completed."""
    pm = PipelineManager()
    assert pm.state == PipelineState.IDLE

    # Simulate a fast pipeline
    async def fake_pipeline():
        await asyncio.sleep(0.01)
        return [{"chapter": 1}]

    await pm.start(fake_pipeline())
    assert pm.state == PipelineState.RUNNING

    # Wait for completion
    await asyncio.sleep(0.05)
    assert pm.state == PipelineState.COMPLETED
    assert len(pm.results) == 1


@pytest.mark.asyncio
async def test_pipeline_manager_pause_resume():
    """pause() and resume() toggle the Event and state."""
    pm = PipelineManager()

    # Use a manual gate to control when the pipeline proceeds
    proceed_gate = asyncio.Event()
    gate_reached = asyncio.Event()

    async def controlled_pipeline():
        gate_reached.set()
        await proceed_gate.wait()
        return [{"chapter": 1}]

    await pm.start(controlled_pipeline())
    await gate_reached.wait()
    assert pm.state == PipelineState.RUNNING

    # Pause
    pm.pause()
    assert pm.state == PipelineState.PAUSED
    assert not pm.pause_event.is_set()

    # Resume
    pm.resume()
    assert pm.state == PipelineState.RUNNING
    assert pm.pause_event.is_set()

    # Let the pipeline complete
    proceed_gate.set()
    await asyncio.sleep(0.05)
    assert pm.state == PipelineState.COMPLETED


@pytest.mark.asyncio
async def test_pipeline_manager_failed():
    """Pipeline sets FAILED state on exception."""
    pm = PipelineManager()

    async def failing_pipeline():
        raise RuntimeError("Test error")

    await pm.start(failing_pipeline())
    await asyncio.sleep(0.05)
    assert pm.state == PipelineState.FAILED
    assert pm.error == "Test error"


@pytest.mark.asyncio
async def test_pipeline_manager_double_start():
    """Starting when already running raises RuntimeError."""
    pm = PipelineManager()

    async def blocking_pipeline():
        await asyncio.sleep(10)
        return []

    await pm.start(blocking_pipeline())

    with pytest.raises(RuntimeError, match="already running"):
        await pm.start(blocking_pipeline())

    pm.reset()


@pytest.mark.asyncio
async def test_milestone_callback_and_approval():
    """milestone_callback sets flag; approve_milestone resolves future."""
    pm = PipelineManager()

    # Test the sync callback
    info = {"milestone_name": "Midpoint", "chapter_number": 5, "constraints": ["test"]}
    result = pm.milestone_callback(info)
    assert result is True  # Always returns True
    assert pm._milestone_pending is True
    assert pm._milestone_info == info


@pytest.mark.asyncio
async def test_milestone_approval_flow():
    """Full milestone: await_milestone_approval waits, approve_milestone resolves."""
    pm = PipelineManager()
    pm.state = PipelineState.RUNNING

    # Start awaiting in a background task
    approval_result = asyncio.Future()

    async def wait_and_capture():
        result = await pm.await_milestone_approval()
        approval_result.set_result(result)

    task = asyncio.create_task(wait_and_capture())

    # Give the task time to start
    await asyncio.sleep(0.01)
    assert pm.state == PipelineState.MILESTONE_PENDING

    # Approve
    pm.approve_milestone(True)

    await asyncio.sleep(0.01)
    assert approval_result.result() is True
    assert pm.state == PipelineState.RUNNING

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_milestone_rejection():
    """Rejecting a milestone returns False."""
    pm = PipelineManager()
    pm.state = PipelineState.RUNNING

    approval_result = asyncio.Future()

    async def wait_and_capture():
        result = await pm.await_milestone_approval()
        approval_result.set_result(result)

    task = asyncio.create_task(wait_and_capture())
    await asyncio.sleep(0.01)

    pm.approve_milestone(False)
    await asyncio.sleep(0.01)

    assert approval_result.result() is False

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_pipeline_manager_get_status():
    """get_status() returns correct dict shape."""
    pm = PipelineManager()
    pm.session_id = "test_session"
    pm.total_chapters = 5
    pm.current_chapter = 2

    status = pm.get_status()
    assert status["state"] == "idle"
    assert status["session_id"] == "test_session"
    assert status["total_chapters"] == 5
    assert status["current_chapter"] == 2
    assert status["completed_chapters"] == 0
    assert status["error"] is None


def test_pipeline_manager_reset():
    """reset() clears all state."""
    pm = PipelineManager()
    pm.state = PipelineState.COMPLETED
    pm.results = [{"test": True}]
    pm.session_id = "test"
    pm.error = "old error"

    pm.reset()

    assert pm.state == PipelineState.IDLE
    assert pm.results == []
    assert pm.session_id is None
    assert pm.error is None
