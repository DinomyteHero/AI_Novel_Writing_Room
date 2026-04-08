"""Tests for run ledger and sessions API endpoints."""

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
    # Seed the ledger with test events
    state = app.state._app_state
    state.ledger.emit("pipeline_start", payload={"total_scenes": 5})
    state.ledger.emit("chapter_start", chapter_number=1, scene_number=1, payload={"mission": "test"})
    state.ledger.emit("gate_pass", chapter_number=1, scene_number=1, payload={"verdict": "pass"})
    state.ledger.emit("gate_fail", chapter_number=2, scene_number=1, payload={"verdict": "fail_structural"})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_get_events(client):
    resp = await client.get("/api/ledger/events")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 4


@pytest.mark.asyncio
async def test_get_events_filtered(client):
    resp = await client.get("/api/ledger/events?event_type=gate_pass")
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert all(e["event_type"] == "gate_pass" for e in events)


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


@pytest.mark.asyncio
async def test_ledger_summary(client):
    resp = await client.get("/api/ledger/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_events"] >= 4
    assert data["gate_pass_count"] >= 1


@pytest.mark.asyncio
async def test_sessions_list(client):
    resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    assert "sessions" in resp.json()


@pytest.mark.asyncio
async def test_session_not_found(client):
    resp = await client.get("/api/sessions/nonexistent")
    assert resp.status_code in (404, 503)


@pytest.mark.asyncio
async def test_delete_session_not_found(client):
    resp = await client.delete("/api/sessions/nonexistent")
    assert resp.status_code in (404, 503)
