"""WebSocket-aware RunLedger that bridges events to an asyncio Queue.

Subclasses RunLedger to add real-time event streaming. Every emit() call
writes to SQLite (inherited) AND pushes the event dict to an asyncio.Queue
for WebSocket broadcasting. Zero changes to existing pipeline code.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from src.run_ledger import RunLedger

logger = logging.getLogger(__name__)


class WebSocketLedger(RunLedger):
    """RunLedger that also pushes events to a broadcast queue."""

    def __init__(self, db_path: str = "output/_fallback/run_ledger.db", queue: Optional[asyncio.Queue] = None):
        super().__init__(db_path)
        self._queue = queue or asyncio.Queue(maxsize=10000)
        self._dropped_count = 0

    @property
    def queue(self) -> asyncio.Queue:
        return self._queue

    def emit(
        self,
        event_type: str,
        chapter_number: Optional[int] = None,
        scene_number: Optional[int] = None,
        agent_role: Optional[str] = None,
        payload: Optional[dict] = None,
        attempt_id: Optional[str] = None,
    ) -> int:
        """Emit an event to SQLite and the WebSocket broadcast queue."""
        event_id = super().emit(
            event_type,
            chapter_number=chapter_number,
            scene_number=scene_number,
            agent_role=agent_role,
            payload=payload,
            attempt_id=attempt_id,
        )

        event_dict = {
            "id": event_id,
            "event_type": event_type,
            "chapter_number": chapter_number,
            "scene_number": scene_number,
            "agent_role": agent_role,
            "attempt_id": attempt_id,
            "payload": payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            self._queue.put_nowait(event_dict)
        except asyncio.QueueFull:
            self._dropped_count += 1
            if self._dropped_count % 100 == 1:
                logger.warning(
                    "Event queue full — %d event(s) dropped so far", self._dropped_count
                )

        return event_id
