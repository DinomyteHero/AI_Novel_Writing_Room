"""Tests for the FastAPI health endpoint and app creation."""

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
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["phase"] == 1
    assert data["pipeline_state"] == "idle"


@pytest.mark.asyncio
async def test_app_creation(app):
    routes = [r.path for r in app.routes if hasattr(r, "path")]
    assert "/api/health" in routes


@pytest.mark.asyncio
async def test_health_includes_pipeline_state(client):
    resp = await client.get("/api/health")
    data = resp.json()
    assert data["pipeline_state"] in ("idle", "running", "paused", "completed", "failed", "milestone_pending")
