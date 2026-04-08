"""Tests for story state API endpoints."""

import json
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from tests.conftest_phase5 import create_test_app


@pytest.fixture
def app(temp_dir, settings_yaml, sample_concept_seed):
    seed_path = Path(temp_dir) / "concept_seed.json"
    seed_path.write_text(json.dumps(sample_concept_seed), encoding="utf-8")
    return create_test_app(settings_yaml, str(seed_path), phase=2)


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_characters(client):
    resp = await client.get("/api/state/characters")
    assert resp.status_code == 200
    chars = resp.json()["characters"]
    assert isinstance(chars, list)
    assert len(chars) >= 1


@pytest.mark.asyncio
async def test_get_character_not_found(client):
    resp = await client.get("/api/state/characters/nonexistent_char_id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_plot_threads(client):
    resp = await client.get("/api/state/plot-threads")
    assert resp.status_code == 200
    assert "plot_threads" in resp.json()


@pytest.mark.asyncio
async def test_timeline(client):
    resp = await client.get("/api/state/timeline")
    assert resp.status_code == 200
    assert "timeline" in resp.json()


@pytest.mark.asyncio
async def test_timeline_with_chapter_filter(client):
    resp = await client.get("/api/state/timeline?chapter=1")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_chekhov_guns(client):
    resp = await client.get("/api/state/chekhov-guns")
    assert resp.status_code == 200
    assert "chekhov_guns" in resp.json()


@pytest.mark.asyncio
async def test_knowledge_endpoint(client):
    resp = await client.get("/api/state/knowledge/__world__")
    assert resp.status_code == 200
    assert "knowledge" in resp.json()


@pytest.mark.asyncio
async def test_dramatic_irony(client):
    resp = await client.get("/api/state/dramatic-irony?chapter=1")
    assert resp.status_code == 200
    assert "dramatic_ironies" in resp.json()
