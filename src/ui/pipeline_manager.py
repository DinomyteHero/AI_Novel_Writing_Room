"""Pipeline lifecycle state machine for web-based pipeline control.

Manages starting, pausing, resuming, and monitoring the pipeline
as an asyncio background task. Handles milestone gate approvals
via asyncio.Future bridging.
"""

import asyncio
import logging
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class PipelineState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    MILESTONE_PENDING = "milestone_pending"
    COMPLETED = "completed"
    FAILED = "failed"


class PipelineManager:
    """Manages pipeline execution state and control signals."""

    def __init__(self):
        self.state: PipelineState = PipelineState.IDLE
        self._task: Optional[asyncio.Task] = None
        self.pause_event: asyncio.Event = asyncio.Event()
        self.pause_event.set()  # Start unpaused

        # Milestone gate support
        self._milestone_future: Optional[asyncio.Future] = None
        self._milestone_info: Optional[dict] = None
        self._milestone_pending: bool = False

        # Results tracking
        self.results: list[dict] = []
        self.current_chapter: Optional[int] = None
        self.total_chapters: int = 0
        self.session_id: Optional[str] = None
        self.error: Optional[str] = None

    def get_status(self) -> dict:
        """Return current pipeline status."""
        return {
            "state": self.state.value,
            "session_id": self.session_id,
            "current_chapter": self.current_chapter,
            "total_chapters": self.total_chapters,
            "completed_chapters": len(self.results),
            "error": self.error,
            "milestone_info": self._milestone_info if self.state == PipelineState.MILESTONE_PENDING else None,
        }

    async def start(self, coro) -> None:
        """Start the pipeline as a background task.

        Args:
            coro: The coroutine to run (typically web_orchestrator.run_pipeline(cards)).
        """
        if self.state == PipelineState.RUNNING:
            raise RuntimeError("Pipeline is already running")

        self.state = PipelineState.RUNNING
        self.results = []
        self.error = None
        self.pause_event.set()
        self._milestone_pending = False
        self._milestone_info = None

        self._task = asyncio.create_task(self._run_wrapper(coro))

    async def _run_wrapper(self, coro) -> None:
        """Wrap pipeline execution with state management."""
        try:
            results = await coro
            self.results = results or []
            self.state = PipelineState.COMPLETED
            logger.info("Pipeline completed with %d chapters", len(self.results))
        except asyncio.CancelledError:
            self.state = PipelineState.IDLE
            logger.info("Pipeline cancelled")
        except Exception as e:
            self.error = str(e)
            self.state = PipelineState.FAILED
            logger.error("Pipeline failed: %s", e)

    def pause(self) -> None:
        """Pause the pipeline after the current chapter completes."""
        if self.state != PipelineState.RUNNING:
            raise RuntimeError(f"Cannot pause pipeline in state: {self.state.value}")
        self.pause_event.clear()
        self.state = PipelineState.PAUSED

    def resume(self) -> None:
        """Resume a paused pipeline."""
        if self.state != PipelineState.PAUSED:
            raise RuntimeError(f"Cannot resume pipeline in state: {self.state.value}")
        self.state = PipelineState.RUNNING
        self.pause_event.set()

    def milestone_callback(self, milestone_info: dict) -> bool:
        """Synchronous callback for MilestoneGates.

        Returns True immediately -- actual gating happens in WebOrchestrator
        via await_milestone_approval().
        """
        self._milestone_info = milestone_info
        self._milestone_pending = True
        return True  # Let run_chapter complete; WebOrchestrator handles the await

    async def await_milestone_approval(self) -> bool:
        """Block pipeline until milestone is approved/rejected via API.

        Called by WebOrchestrator after run_chapter() returns if a milestone
        was detected. Creates a Future that the approve_milestone() method resolves.
        If the wait is cancelled (e.g. reset/shutdown), the manager clears the
        pending state cleanly and lets the cancellation propagate.
        """
        self.state = PipelineState.MILESTONE_PENDING
        loop = asyncio.get_event_loop()
        self._milestone_future = loop.create_future()

        should_continue = False
        try:
            should_continue = await self._milestone_future
        finally:
            self._milestone_future = None
            self._milestone_pending = False
            if should_continue:
                self.state = PipelineState.RUNNING

        return should_continue

    def approve_milestone(self, should_continue: bool) -> None:
        """Resolve the milestone Future (called from API endpoint)."""
        if not self._milestone_future or self._milestone_future.done():
            raise RuntimeError("No milestone pending approval")
        self._milestone_future.set_result(should_continue)
        if not should_continue:
            self._milestone_info = None

    def reset(self) -> None:
        """Reset to idle state for a new run."""
        if self._task and not self._task.done():
            self._task.cancel()
        self.state = PipelineState.IDLE
        self._task = None
        self.results = []
        self.current_chapter = None
        self.total_chapters = 0
        self.session_id = None
        self.error = None
        self._milestone_pending = False
        self._milestone_info = None
        self._milestone_future = None
        self.pause_event.set()
