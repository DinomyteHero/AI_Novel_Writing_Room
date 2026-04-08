"""Tests for pipeline control API endpoints."""

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

    manuscripts_dir = Path(temp_dir) / "manuscripts"
    manuscripts_dir.mkdir()

    return create_test_app(
        settings_yaml, str(seed_path), phase=1,
        manuscripts_dir=str(manuscripts_dir),
        scene_cards_dir=str(scene_dir),
    )


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_pipeline_status_idle(client):
    resp = await client.get("/api/pipeline/status")
    assert resp.status_code == 200
    assert resp.json()["state"] == "idle"


@pytest.mark.asyncio
async def test_pipeline_start_missing_path(client):
    resp = await client.post(
        "/api/pipeline/start",
        json={"concept_seed_path": "/nonexistent/path.json", "scene_cards_dir": "/nonexistent"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_pipeline_pause_when_idle(client):
    resp = await client.post("/api/pipeline/pause")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_pipeline_resume_when_idle(client):
    resp = await client.post("/api/pipeline/resume")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_pipeline_results_empty(client):
    resp = await client.get("/api/pipeline/results")
    assert resp.status_code == 200
    assert resp.json()["results"] == []


@pytest.mark.asyncio
async def test_milestone_approve_when_none(client):
    resp = await client.post(
        "/api/pipeline/milestone/approve",
        json={"should_continue": True},
    )
    assert resp.status_code == 409
