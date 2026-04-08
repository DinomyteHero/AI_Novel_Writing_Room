"""Tests for scene cards API endpoints."""

import json
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest_phase5 import create_test_app


@pytest.fixture
def app(temp_dir, settings_yaml, sample_concept_seed, sample_scene_card):
    seed_path = Path(temp_dir) / "concept_seed.json"
    seed_path.write_text(json.dumps(sample_concept_seed), encoding="utf-8")

    scene_dir = Path(temp_dir) / "scene_cards"
    scene_dir.mkdir()
    (scene_dir / "chapter_01_scene_01.json").write_text(json.dumps(sample_scene_card), encoding="utf-8")

    return create_test_app(
        settings_yaml, str(seed_path), phase=1,
        scene_cards_dir=str(scene_dir),
    )


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_scene_cards(client):
    resp = await client.get("/api/scene-cards")
    assert resp.status_code == 200
    assert len(resp.json()["scene_cards"]) == 1


@pytest.mark.asyncio
async def test_get_scene_card(client):
    resp = await client.get("/api/scene-cards/1/1")
    assert resp.status_code == 200
    assert resp.json()["chapter_number"] == 1


@pytest.mark.asyncio
async def test_get_scene_card_not_found(client):
    resp = await client.get("/api/scene-cards/99/1")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_concept_seed(client):
    resp = await client.get("/api/concept-seed")
    assert resp.status_code == 200
    data = resp.json()
    assert "meta" in data or "premise" in data or "ensemble_cast" in data


@pytest.mark.asyncio
async def test_generate_not_available(client):
    resp = await client.post("/api/scene-cards/generate")
    assert resp.status_code == 503
