"""Story state API endpoints (read-only)."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request

from src.ui.app import get_app_state

router = APIRouter(tags=["story-state"])


def _require_story_state(request: Request):
    state = get_app_state(request)
    if not state.story_state:
        raise HTTPException(503, "Story state not initialized")
    return state


@router.get("/state/characters")
async def list_characters(request: Request):
    """Get all characters."""
    state = _require_story_state(request)
    return {"characters": state.story_state.get_all_characters()}


@router.get("/state/characters/{character_id}")
async def get_character(character_id: str, request: Request):
    """Get a single character with relationships."""
    state = _require_story_state(request)

    character = state.story_state.get_character(character_id)
    if not character:
        raise HTTPException(404, f"Character not found: {character_id}")

    relationships = state.story_state.get_relationships(character_id)
    knowledge = state.story_state.get_knowledge(character_id=character_id)

    return {
        **character,
        "relationships": relationships,
        "knowledge": knowledge,
    }


@router.get("/state/plot-threads")
async def list_plot_threads(request: Request):
    """Get all plot threads."""
    state = _require_story_state(request)
    return {"plot_threads": state.story_state.get_active_threads()}


@router.get("/state/timeline")
async def get_timeline(
    request: Request,
    chapter: Optional[int] = Query(None, description="Filter by chapter number"),
):
    """Get timeline entries."""
    state = _require_story_state(request)
    return {"timeline": state.story_state.get_timeline(chapter_number=chapter)}


@router.get("/state/chekhov-guns")
async def list_chekhov_guns(request: Request):
    """Get all Chekhov's guns."""
    state = _require_story_state(request)
    return {"chekhov_guns": state.story_state.get_unfired_guns()}


@router.get("/state/knowledge/{character_id}")
async def get_character_knowledge(
    character_id: str,
    request: Request,
    layer: Optional[str] = Query(None, description="Filter by layer: truth, belief, narrative_exposure"),
):
    """Get knowledge layers for a character."""
    state = _require_story_state(request)
    knowledge = state.story_state.get_knowledge(
        character_id=character_id,
        layer=layer,
    )
    return {"character_id": character_id, "layer": layer, "knowledge": knowledge}


@router.get("/state/dramatic-irony")
async def get_dramatic_irony(
    request: Request,
    chapter: int = Query(1, description="Chapter number for irony analysis"),
):
    """Get current dramatic irony situations."""
    state = _require_story_state(request)

    if not state.knowledge_layers:
        raise HTTPException(503, "Knowledge layers not initialized")

    ironies = state.knowledge_layers.get_dramatic_irony(chapter)
    return {"chapter": chapter, "dramatic_ironies": ironies}
