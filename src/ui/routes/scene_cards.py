"""Scene cards and outline API endpoints."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from src.ui.app import get_app_state

router = APIRouter(tags=["scene-cards"])


@router.get("/scene-cards")
async def list_scene_cards(request: Request):
    """List all scene cards from the configured directory."""
    state = get_app_state(request)
    if not state.scene_cards_dir:
        return {"scene_cards": []}

    cards_dir = Path(state.scene_cards_dir)
    if not cards_dir.exists():
        return {"scene_cards": []}

    cards = []
    for card_file in sorted(cards_dir.glob("*.json")):
        with open(card_file, encoding="utf-8") as f:
            cards.append(json.load(f))

    return {"scene_cards": cards}


@router.get("/scene-cards/{chapter_num}/{scene_num}")
async def get_scene_card(chapter_num: int, scene_num: int, request: Request):
    """Get a single scene card."""
    state = get_app_state(request)
    if not state.scene_cards_dir:
        raise HTTPException(404, "No scene cards directory configured")

    filename = f"chapter_{chapter_num:02d}_scene_{scene_num:02d}.json"
    path = Path(state.scene_cards_dir) / filename
    if not path.exists():
        raise HTTPException(404, f"Scene card not found: {filename}")

    with open(path, encoding="utf-8") as f:
        return json.load(f)


@router.post("/scene-cards/generate")
async def generate_scene_cards(request: Request):
    """Generate scene cards from the concept seed using SceneCardGenerator."""
    state = get_app_state(request)

    if not state.scene_card_generator:
        raise HTTPException(503, "Scene card generator not available")
    if not state.concept_seed:
        raise HTTPException(400, "No concept seed loaded")

    cards = await state.scene_card_generator.generate(state.concept_seed)
    if not cards:
        raise HTTPException(500, "No scene cards generated")

    # Save to scene cards directory
    if state.scene_cards_dir:
        output_dir = Path(state.scene_cards_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        state.scene_card_generator.save_scene_cards(cards, str(output_dir))

    state.ledger.emit("outline_generated", payload={"count": len(cards)})
    return {"scene_cards": cards, "count": len(cards)}


@router.get("/concept-seed")
async def get_concept_seed(request: Request):
    """Get the loaded concept seed."""
    state = get_app_state(request)
    if not state.concept_seed:
        raise HTTPException(404, "No concept seed loaded")
    return state.concept_seed
