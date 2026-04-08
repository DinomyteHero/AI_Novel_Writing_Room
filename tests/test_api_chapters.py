"""Tests for chapter and manuscript API endpoints."""

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

    manuscripts_dir = Path(temp_dir) / "manuscripts"
    manuscripts_dir.mkdir()
    (manuscripts_dir / "chapter_01_scene_01.md").write_text(
        "Chapter one prose here. This is the first scene.", encoding="utf-8",
    )
    (manuscripts_dir / "chapter_02_scene_01.md").write_text(
        "Chapter two prose here. More content for the second chapter.", encoding="utf-8",
    )

    return create_test_app(
        settings_yaml, str(seed_path), phase=1,
        manuscripts_dir=str(manuscripts_dir),
    )


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_list_chapters(client):
    resp = await client.get("/api/chapters")
    assert resp.status_code == 200
    chapters = resp.json()["chapters"]
    assert len(chapters) == 2
    assert chapters[0]["chapter_number"] == 1


@pytest.mark.asyncio
async def test_get_chapter(client):
    resp = await client.get("/api/chapters/1/1")
    assert resp.status_code == 200
    data = resp.json()
    assert "Chapter one" in data["prose"]
    assert data["word_count"] > 0


@pytest.mark.asyncio
async def test_get_chapter_not_found(client):
    resp = await client.get("/api/chapters/99/1")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_manuscript_summary(client):
    resp = await client.get("/api/manuscript/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chapter_count"] == 2
    assert data["total_word_count"] > 0


@pytest.mark.asyncio
async def test_export_not_available(client):
    resp = await client.post("/api/export", json={"formats": ["md"]})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_download_no_exports(client):
    resp = await client.get("/api/export/download/md")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_invalid_format(client):
    resp = await client.get("/api/export/download/pdf")
    assert resp.status_code == 400
