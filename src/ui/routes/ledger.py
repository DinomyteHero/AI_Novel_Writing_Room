"""Read-only run-ledger endpoints."""

from typing import Optional

from fastapi import APIRouter, Query, Request

from src.ui.app import get_app_state

router = APIRouter(tags=["ledger"])


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
