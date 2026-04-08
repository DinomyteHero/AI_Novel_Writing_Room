"""WebSocket endpoint for real-time pipeline event streaming."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.ui.app import get_app_state

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/pipeline")
async def pipeline_websocket(websocket: WebSocket):
    """Stream pipeline events to connected WebSocket clients.

    Events match the RunLedger format:
    {event_type, chapter_number, scene_number, agent_role, payload, timestamp}
    """
    # Access app state via the websocket's app reference
    state = websocket.app.state._app_state
    cm = state.connection_manager

    await cm.connect(websocket)
    try:
        # Keep connection alive; the broadcaster task handles sending events.
        # We just read from the client to detect disconnects.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        cm.disconnect(websocket)
