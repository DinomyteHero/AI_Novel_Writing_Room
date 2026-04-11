"""Tests for LoreVectorStore — ChromaDB wrapper for worldbuilding."""

import pytest

chromadb = pytest.importorskip("chromadb", reason="chromadb not installed")

from src.rag.embedding import MockEmbeddingFunction
from src.worldbuilding.lore_vectorstore import LoreVectorStore


@pytest.fixture
def vs(tmp_path):
    return LoreVectorStore(
        persist_directory=str(tmp_path / "test_wb_vectors"),
        embedding_function=MockEmbeddingFunction(),
    )


class TestUpsertAndSearch:
    def test_upsert_and_search(self, vs):
        vs.upsert_entry("u1", "e1", "The Sith Order is an ancient faction",
                         {"category": "faction", "title": "Sith Order", "status": "canonical"})
        results = vs.search("u1", "ancient dark side faction", k=5)
        assert len(results) >= 1
        assert results[0]["id"] == "e1"

    def test_search_empty_collection(self, vs):
        results = vs.search("u1", "anything", k=5)
        assert results == []

    def test_multiple_entries(self, vs):
        vs.upsert_entry("u1", "e1", "Sith homeworld on Korriban",
                         {"category": "location", "status": "canonical"})
        vs.upsert_entry("u1", "e2", "Jedi temple on Coruscant",
                         {"category": "location", "status": "canonical"})
        vs.upsert_entry("u1", "e3", "Mandalorian armor traditions",
                         {"category": "species_culture", "status": "canonical"})
        results = vs.search("u1", "Jedi temple", k=2)
        assert len(results) <= 2

    def test_metadata_filtering(self, vs):
        vs.upsert_entry("u1", "e1", "A canonical faction",
                         {"category": "faction", "status": "canonical"})
        vs.upsert_entry("u1", "e2", "A deprecated faction",
                         {"category": "faction", "status": "deprecated"})
        results = vs.search("u1", "faction", k=5,
                            where={"status": {"$ne": "deprecated"}})
        assert all(r["metadata"]["status"] != "deprecated" for r in results)


class TestRemoveEntry:
    def test_remove(self, vs):
        vs.upsert_entry("u1", "e1", "Test content",
                         {"category": "faction", "status": "canonical"})
        vs.remove_entry("u1", "e1")
        results = vs.search("u1", "Test", k=5)
        assert len(results) == 0

    def test_remove_nonexistent_no_error(self, vs):
        vs.remove_entry("u1", "nonexistent")  # Should not raise


class TestSearchChain:
    def test_chain_search(self, vs):
        vs.upsert_entry("parent", "e1", "Parent universe lore about the Force",
                         {"category": "force_mechanic", "status": "canonical"})
        vs.upsert_entry("child", "e2", "Child universe specific lore about lightsabers",
                         {"category": "technology", "status": "canonical"})
        results = vs.search_chain(["child", "parent"], "Force and lightsabers", k=5)
        assert len(results) == 2

    def test_chain_deduplication(self, vs):
        # Same ID in parent and child (child overrides)
        vs.upsert_entry("parent", "e1", "Parent version of lore",
                         {"category": "faction", "status": "canonical"})
        vs.upsert_entry("child", "e1", "Child override of lore",
                         {"category": "faction", "status": "canonical"})
        results = vs.search_chain(["child", "parent"], "lore", k=5)
        # Should only have one entry (child version, since child is searched first)
        ids = [r["id"] for r in results]
        assert ids.count("e1") == 1

    def test_chain_respects_top_k(self, vs):
        for i in range(10):
            vs.upsert_entry("u1", f"e{i}", f"Lore entry number {i}",
                             {"category": "faction", "status": "canonical"})
        results = vs.search_chain(["u1"], "lore", k=3)
        assert len(results) == 3


class TestCollectionIsolation:
    def test_universes_isolated(self, vs):
        vs.upsert_entry("u1", "e1", "U1 content",
                         {"category": "faction", "status": "canonical"})
        vs.upsert_entry("u2", "e2", "U2 content",
                         {"category": "faction", "status": "canonical"})
        # Search only u1
        results = vs.search("u1", "content", k=5)
        ids = [r["id"] for r in results]
        assert "e1" in ids
        assert "e2" not in ids


class TestGetAllEntryIds:
    def test_gets_all_ids(self, vs):
        vs.upsert_entry("u1", "e1", "A", {"status": "canonical"})
        vs.upsert_entry("u1", "e2", "B", {"status": "canonical"})
        ids = vs.get_all_entry_ids("u1")
        assert ids == {"e1", "e2"}

    def test_empty_returns_empty_set(self, vs):
        assert vs.get_all_entry_ids("nonexistent") == set()


class TestDeleteCollection:
    def test_deletes_collection(self, vs):
        vs.upsert_entry("u1", "e1", "content", {"status": "canonical"})
        vs.delete_collection("u1")
        # After deletion, searching creates a new empty collection
        results = vs.search("u1", "content", k=5)
        assert len(results) == 0
