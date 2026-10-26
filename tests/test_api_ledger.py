"""Tests for read-only run-ledger API endpoints."""

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
    return create_test_app(settings_yaml, str(seed_path), phase=1)


@pytest_asyncio.fixture
async def client(app):
    state = app.state._app_state
    state.ledger.emit("pipeline_start", payload={"total_scenes": 5})
    state.ledger.emit(
        "lean_prose_only_saved", chapter_number=1, scene_number=1,
        payload={"word_count": 100},
    )
    state.ledger.emit(
        "scene_error", chapter_number=2, scene_number=1,
        payload={"error": "boom"},
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_get_events(client):
    resp = await client.get("/api/ledger/events")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 3


@pytest.mark.asyncio
async def test_get_events_filtered(client):
    resp = await client.get("/api/ledger/events?event_type=scene_error")
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert all(e["event_type"] == "scene_error" for e in events)


@pytest.mark.asyncio
async def test_get_events_by_chapter(client):
    resp = await client.get("/api/ledger/events?chapter=1")
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert all(e["chapter_number"] == 1 for e in events)


@pytest.mark.asyncio
async def test_latest_events(client):
    resp = await client.get("/api/ledger/events/latest?limit=3")
    assert resp.status_code == 200
    assert resp.json()["count"] <= 3
