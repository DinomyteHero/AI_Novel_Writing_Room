"""Tests for worldbuilding API endpoints."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.rag.embedding import MockEmbeddingFunction
from src.ui.app import AppState, create_app, get_app_state
from src.worldbuilding.worldbuilding_db import WorldbuildingDB
from src.worldbuilding.lore_vectorstore import LoreVectorStore
from src.worldbuilding.lore_service import LoreService


@pytest.fixture
def app_with_worldbuilding(tmp_path):
    """Create a test app with worldbuilding service initialized."""
    # Create minimal config
    config = {
        "deployment_mode": "local",
        "models": {"local": {"base_url": "http://localhost:8080/v1"}},
        "pipeline": {},
    }
    config_path = tmp_path / "settings.yaml"
    import yaml
    config_path.write_text(yaml.dump(config))

    # Create minimal concept seed
    seed = {
        "meta": {"project_title": "Test"},
        "premise": {"what_if": "Test"},
        "conflict": {"primary_antagonistic_force": {"identity": "X", "motivation": "Y"}},
        "theme": {"thematic_premise": "Test"},
        "ensemble_cast": [],
    }
    seed_path = tmp_path / "concept_seed.json"
    seed_path.write_text(json.dumps(seed))

    # Build the app (we'll manually inject the lore service)
    from fastapi import FastAPI
    from src.ui.routes.worldbuilding import router as worldbuilding_router

    app = FastAPI()
    state = AppState()

    # Initialize worldbuilding
    db = WorldbuildingDB(db_path=str(tmp_path / "wb.db"))
    vs = LoreVectorStore(
        persist_directory=str(tmp_path / "wb_vectors"),
        embedding_function=MockEmbeddingFunction(),
    )
    state.lore_service = LoreService(db=db, vectorstore=vs)

    app.state._app_state = state
    app.include_router(worldbuilding_router, prefix="/api")

    return app


@pytest.fixture
def client(app_with_worldbuilding):
    return TestClient(app_with_worldbuilding)


class TestUniverseEndpoints:
    def test_create_universe(self, client):
        resp = client.post("/api/worldbuilding/universes", json={
            "universe_id": "test_u",
            "display_name": "Test Universe",
            "franchise": "star_wars",
        })
        assert resp.status_code == 201
        assert resp.json()["universe_id"] == "test_u"

    def test_list_universes(self, client):
        client.post("/api/worldbuilding/universes", json={
            "universe_id": "u1", "display_name": "U1",
        })
        resp = client.get("/api/worldbuilding/universes")
        assert resp.status_code == 200
        assert len(resp.json()["universes"]) == 1

    def test_get_universe(self, client):
        client.post("/api/worldbuilding/universes", json={
            "universe_id": "u1", "display_name": "U1",
        })
        resp = client.get("/api/worldbuilding/universes/u1")
        assert resp.status_code == 200
        assert resp.json()["display_name"] == "U1"
        assert "inheritance_chain" in resp.json()

    def test_get_nonexistent_universe(self, client):
        resp = client.get("/api/worldbuilding/universes/nope")
        assert resp.status_code == 404

    def test_delete_universe(self, client):
        client.post("/api/worldbuilding/universes", json={
            "universe_id": "u1", "display_name": "U1",
        })
        resp = client.delete("/api/worldbuilding/universes/u1")
        assert resp.status_code == 200


class TestLoreEntryEndpoints:
    def _setup_universe(self, client):
        client.post("/api/worldbuilding/universes", json={
            "universe_id": "u1", "display_name": "U1",
        })

    def test_create_entry(self, client):
        self._setup_universe(client)
        resp = client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "faction",
            "title": "Sith Order",
            "content": "An ancient order of dark side Force users",
        })
        assert resp.status_code == 201
        assert "entry_id" in resp.json()

    def test_list_entries(self, client):
        self._setup_universe(client)
        client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "faction", "title": "F1", "content": "C1",
        })
        client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "location", "title": "L1", "content": "C2",
        })
        resp = client.get("/api/worldbuilding/universes/u1/lore")
        assert resp.status_code == 200
        assert resp.json()["count"] == 2

    def test_list_entries_with_filter(self, client):
        self._setup_universe(client)
        client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "faction", "title": "F1", "content": "C1",
        })
        client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "location", "title": "L1", "content": "C2",
        })
        resp = client.get("/api/worldbuilding/universes/u1/lore?category=faction")
        assert resp.json()["count"] == 1

    def test_get_entry(self, client):
        self._setup_universe(client)
        create_resp = client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "faction", "title": "Sith", "content": "Dark side",
        })
        entry_id = create_resp.json()["entry_id"]
        resp = client.get(f"/api/worldbuilding/lore/{entry_id}")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Sith"
        assert "relations" in resp.json()

    def test_get_nonexistent_entry(self, client):
        resp = client.get("/api/worldbuilding/lore/nonexistent")
        assert resp.status_code == 404

    def test_update_entry(self, client):
        self._setup_universe(client)
        create_resp = client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "faction", "title": "Old", "content": "Old content",
        })
        entry_id = create_resp.json()["entry_id"]
        resp = client.put(f"/api/worldbuilding/lore/{entry_id}", json={
            "title": "New Title",
        })
        assert resp.status_code == 200

    def test_delete_entry(self, client):
        self._setup_universe(client)
        create_resp = client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "faction", "title": "Doomed", "content": "C",
        })
        entry_id = create_resp.json()["entry_id"]
        resp = client.delete(f"/api/worldbuilding/lore/{entry_id}")
        assert resp.status_code == 200

    def test_promote_entry(self, client):
        self._setup_universe(client)
        create_resp = client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "faction", "title": "Prov", "content": "C",
            "status": "provisional",
        })
        entry_id = create_resp.json()["entry_id"]
        resp = client.post(f"/api/worldbuilding/lore/{entry_id}/promote")
        assert resp.status_code == 200
        assert resp.json()["status"] == "canonical"

    def test_deprecate_entry(self, client):
        self._setup_universe(client)
        create_resp = client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "faction", "title": "Old", "content": "C",
        })
        entry_id = create_resp.json()["entry_id"]
        resp = client.post(f"/api/worldbuilding/lore/{entry_id}/deprecate")
        assert resp.json()["status"] == "deprecated"

    def test_bulk_promote(self, client):
        self._setup_universe(client)
        ids = []
        for i in range(3):
            resp = client.post("/api/worldbuilding/universes/u1/lore", json={
                "category": "faction", "title": f"F{i}", "content": "C",
                "status": "provisional",
            })
            ids.append(resp.json()["entry_id"])
        resp = client.post("/api/worldbuilding/lore/bulk-promote", json={
            "entry_ids": ids,
        })
        assert resp.json()["count"] == 3


class TestRelationEndpoints:
    def _setup(self, client):
        client.post("/api/worldbuilding/universes", json={
            "universe_id": "u1", "display_name": "U1",
        })
        r1 = client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "faction", "title": "A", "content": "C",
        })
        r2 = client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "location", "title": "B", "content": "C",
        })
        return r1.json()["entry_id"], r2.json()["entry_id"]

    def test_create_relation(self, client):
        e1, e2 = self._setup(client)
        resp = client.post("/api/worldbuilding/lore/relations", json={
            "source_entry_id": e1,
            "target_entry_id": e2,
            "relation_type": "located_in",
        })
        assert resp.status_code == 201

    def test_get_relations(self, client):
        e1, e2 = self._setup(client)
        client.post("/api/worldbuilding/lore/relations", json={
            "source_entry_id": e1,
            "target_entry_id": e2,
            "relation_type": "located_in",
        })
        resp = client.get(f"/api/worldbuilding/lore/{e1}/relations")
        assert len(resp.json()["relations"]) == 1


class TestTerminologyEndpoint:
    def test_get_terminology(self, client):
        client.post("/api/worldbuilding/universes", json={
            "universe_id": "u1", "display_name": "U1",
        })
        client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "terminology", "title": "Credits",
            "content": "Standard currency",
        })
        resp = client.get("/api/worldbuilding/universes/u1/terminology")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1


class TestProjectBinding:
    def test_bind_and_get(self, client):
        client.post("/api/worldbuilding/universes", json={
            "universe_id": "u1", "display_name": "U1",
        })
        resp = client.post("/api/worldbuilding/projects/proj1/bind-universe", json={
            "universe_id": "u1", "reading_order": 1,
        })
        assert resp.status_code == 201

        resp = client.get("/api/worldbuilding/projects/proj1/universe")
        assert resp.status_code == 200
        assert resp.json()["binding"]["universe_id"] == "u1"


class TestPendingEntries:
    def test_list_pending(self, client):
        client.post("/api/worldbuilding/universes", json={
            "universe_id": "u1", "display_name": "U1",
        })
        client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "faction", "title": "Provisional",
            "content": "C", "status": "provisional",
        })
        client.post("/api/worldbuilding/universes/u1/lore", json={
            "category": "faction", "title": "Canonical",
            "content": "C", "status": "canonical",
        })
        resp = client.get("/api/worldbuilding/universes/u1/pending")
        assert resp.json()["count"] == 1
