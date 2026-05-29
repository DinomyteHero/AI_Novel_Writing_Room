"""Run ledger and session management API endpoints."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from src.ui.app import get_app_state

router = APIRouter(tags=["ledger"])


# --- Ledger endpoints ---

@router.get("/ledger/events")
async def get_events(
    request: Request,
    event_type: Optional[str] = Query(None),
    chapter: Optional[int] = Query(None),
    agent_role: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
):
    """Query events from the run ledger with optional filters."""
    state = get_app_state(request)
    events = state.ledger.get_events(
        chapter_number=chapter,
        event_type=event_type,
        agent_role=agent_role,
        limit=limit,
    )
    return {"events": events, "count": len(events)}


@router.get("/ledger/events/latest")
async def get_latest_events(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
):
    """Get the most recent N events."""
    state = get_app_state(request)
    events = state.ledger.get_events(limit=limit)
    return {"events": events, "count": len(events)}


@router.get("/ledger/summary")
async def get_ledger_summary(request: Request):
    """Get aggregate statistics from the run ledger."""
    state = get_app_state(request)

    all_events = state.ledger.get_events(limit=10000)
    type_counts: dict[str, int] = {}
    for ev in all_events:
        t = ev.get("event_type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1

    return {
        "total_events": len(all_events),
        "events_by_type": type_counts,
    }


# --- Session endpoints ---

@router.get("/sessions")
async def list_sessions(request: Request):
    """List all saved pipeline sessions."""
    state = get_app_state(request)
    if not state.pipeline_session:
        return {"sessions": []}
    return {"sessions": state.pipeline_session.list_sessions()}


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, request: Request):
    """Get a single session's state."""
    state = get_app_state(request)
    if not state.pipeline_session:
        raise HTTPException(503, "Session persistence not available")

    session = state.pipeline_session.load(session_id)
    if not session:
        raise HTTPException(404, f"Session not found: {session_id}")
    return session


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    """Delete a saved session."""
    state = get_app_state(request)
    if not state.pipeline_session:
        raise HTTPException(503, "Session persistence not available")

    session_path = Path(state.pipeline_session.session_dir) / f"{session_id}.json"
    if not session_path.exists():
        raise HTTPException(404, f"Session not found: {session_id}")

    session_path.unlink()
    return {"status": "deleted", "session_id": session_id}
