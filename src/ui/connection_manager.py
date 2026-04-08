"""WebSocket connection manager for broadcasting pipeline events.

Manages a list of connected WebSocket clients and a background task
that drains events from the asyncio.Queue and sends them to all clients.
"""

import asyncio
import json
import logging
from typing import Optional

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and broadcasts events."""

    def __init__(self, queue: asyncio.Queue):
        self._connections: list[WebSocket] = []
        self._queue = queue
        self._broadcast_task: Optional[asyncio.Task] = None

    @property
    def active_connections(self) -> list[WebSocket]:
        return list(self._connections)

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection."""
        await websocket.accept()
        self._connections.append(websocket)
        logger.info("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection."""
        if websocket in self._connections:
            self._connections.remove(websocket)
            logger.info("WebSocket client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, message: dict) -> None:
        """Send a message to all connected clients."""
        if not self._connections:
            return

        data = json.dumps(message, default=str)
        dead: list[WebSocket] = []

        for ws in self._connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)

    async def start_broadcaster(self) -> None:
        """Start the background task that drains the queue and broadcasts."""
        self._broadcast_task = asyncio.create_task(self._run_broadcaster())

    async def stop_broadcaster(self) -> None:
        """Stop the background broadcaster task."""
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
            self._broadcast_task = None

    async def _run_broadcaster(self) -> None:
        """Drain queue and broadcast to all WebSocket clients."""
        try:
            while True:
                event = await self._queue.get()
                await self.broadcast(event)
                self._queue.task_done()
        except asyncio.CancelledError:
            pass
