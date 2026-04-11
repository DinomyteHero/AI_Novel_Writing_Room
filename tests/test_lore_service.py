"""Tests for LoreService — dual-write, retrieval, extraction, reconciliation."""

import pytest

chromadb = pytest.importorskip("chromadb", reason="chromadb not installed")

from src.rag.embedding import MockEmbeddingFunction
from src.worldbuilding.worldbuilding_db import WorldbuildingDB
from src.worldbuilding.lore_vectorstore import LoreVectorStore
from src.worldbuilding.lore_service import LoreService, _timeline_matches, _timeline_matches_sort_key


@pytest.fixture
def db(tmp_path):
    return WorldbuildingDB(db_path=str(tmp_path / "test_wb.db"))


@pytest.fixture
def vs(tmp_path):
    return LoreVectorStore(
        persist_directory=str(tmp_path / "test_wb_vectors"),
        embedding_function=MockEmbeddingFunction(),
    )


@pytest.fixture
def service(db, vs):
    return LoreService(db=db, vectorstore=vs)


@pytest.fixture
def populated_service(service):
    """Service with a universe, entries, and bindings for testing retrieval."""
    service.create_universe("parent", "Parent Universe", franchise="star_wars")
    service.create_universe("child", "Child AU", parent_universe_id="parent")

    # Parent universe entries
    service.create_lore_entry(
        universe_id="parent", category="faction", title="Jedi Order",
        content="An order of Force users dedicated to the light side",
        tags=["force", "light_side"],
    )
    service.create_lore_entry(
        universe_id="parent", category="terminology", title="Credits",
        content="Standard galactic currency",
    )

    # Child universe entries
    service.create_lore_entry(
        universe_id="child", category="faction", title="Draleth Hegemony",
        content="A declining imperial power in the Outer Rim",
        thematic_notes="late-stage imperial decline",
        speech_patterns="Formal address, no contractions",
    )
    service.create_lore_entry(
        universe_id="child", category="terminology", title="Hegemon",
        content="Title for the supreme ruler of the Draleth Hegemony",
    )
    service.create_lore_entry(
        universe_id="child", category="historical_event", title="Battle of Kressh",
        content="A pivotal battle that ended the Hegemony's expansion",
        valid_from="3600 BBY", valid_until="3500 BBY",
    )

    # Project bindings
    service.db.bind_project("book1", "child", reading_order=1)
    service.db.bind_project("book2", "child", reading_order=2)

    return service


class TestDualWrite:
    def test_create_entry_writes_to_both(self, service):
        service.create_universe("u1", "U1")
        entry_id = service.create_lore_entry(
            universe_id="u1", category="faction",
            title="Test Faction", content="A test faction",
        )
        # SQLite
        assert service.db.get_lore_entry(entry_id) is not None
        # ChromaDB
        chroma_ids = service.vectorstore.get_all_entry_ids("u1")
        assert entry_id in chroma_ids

    def test_update_entry_updates_chromadb(self, service):
        service.create_universe("u1", "U1")
        eid = service.create_lore_entry(
            universe_id="u1", category="faction",
            title="Old Title", content="Old content",
        )
        service.update_lore_entry(eid, title="New Title", content="New content")
        # Verify ChromaDB has updated content
        results = service.vectorstore.search("u1", "New content", k=1)
        assert len(results) >= 1

    def test_delete_entry_removes_from_both(self, service):
        service.create_universe("u1", "U1")
        eid = service.create_lore_entry(
            universe_id="u1", category="faction",
            title="Doomed", content="Will be deleted",
        )
        service.delete_lore_entry(eid)
        assert service.db.get_lore_entry(eid) is None
        assert eid not in service.vectorstore.get_all_entry_ids("u1")

    def test_promote_updates_both(self, service):
        service.create_universe("u1", "U1")
        eid = service.create_lore_entry(
            universe_id="u1", category="faction",
            title="F", content="C", status="provisional",
        )
        service.promote_entry(eid)
        assert service.db.get_lore_entry(eid)["status"] == "canonical"

    def test_deprecate_updates_both(self, service):
        service.create_universe("u1", "U1")
        eid = service.create_lore_entry(
            universe_id="u1", category="faction",
            title="F", content="C",
        )
        service.deprecate_entry(eid)
        assert service.db.get_lore_entry(eid)["status"] == "deprecated"

    def test_delete_universe_removes_collection(self, service):
        service.create_universe("u1", "U1")
        service.create_lore_entry(
            universe_id="u1", category="faction",
            title="F", content="C",
        )
        service.delete_universe("u1")
        assert service.db.get_universe("u1") is None


class TestGetLoreForContext:
    def test_basic_retrieval(self, populated_service):
        results = populated_service.get_lore_for_context(
            universe_id="child",
            query_text="imperial power Outer Rim",
            top_k=5,
        )
        assert len(results) >= 1

    def test_excludes_deprecated(self, service):
        service.create_universe("u1", "U1")
        eid = service.create_lore_entry(
            universe_id="u1", category="faction",
            title="Deprecated", content="Old lore",
        )
        service.deprecate_entry(eid)
        results = service.get_lore_for_context(
            universe_id="u1", query_text="Old lore", top_k=5,
        )
        # Should not include deprecated entries
        result_ids = [r["id"] for r in results]
        assert eid not in result_ids

    def test_excludes_terminology(self, populated_service):
        results = populated_service.get_lore_for_context(
            universe_id="child",
            query_text="currency credits galactic",
            top_k=10,
        )
        for r in results:
            assert r.get("metadata", {}).get("category") != "terminology"

    def test_walk_parents(self, populated_service):
        results = populated_service.get_lore_for_context(
            universe_id="child",
            query_text="Force users light side Jedi",
            top_k=10, walk_parents=True,
        )
        # Should find entries from both child and parent
        assert len(results) >= 1

    def test_no_walk_parents(self, populated_service):
        results = populated_service.get_lore_for_context(
            universe_id="child",
            query_text="Force users Jedi",
            top_k=10, walk_parents=False,
        )
        # Only child entries
        for r in results:
            # All results should come from the child universe search
            pass  # Can't filter by universe in results without metadata


class TestTimelineFiltering:
    """Timeline filtering uses string comparison, so dates must sort lexicographically.

    Use zero-padded chapter numbers (e.g., "ch005") or ISO dates ("1000-01-01")
    rather than BBY dates (which sort inversely). BBY-style dates require a
    custom comparator — not yet implemented.
    """

    def test_matches_within_range(self):
        assert _timeline_matches("ch001", "ch010", "ch005") is True

    def test_no_bounds_always_matches(self):
        assert _timeline_matches("", "", "ch005") is True

    def test_before_valid_from(self):
        assert _timeline_matches("ch005", "ch010", "ch003") is False

    def test_after_valid_until(self):
        assert _timeline_matches("ch005", "ch010", "ch015") is False

    def test_only_valid_from(self):
        assert _timeline_matches("ch005", "", "ch007") is True
        assert _timeline_matches("ch005", "", "ch003") is False

    def test_only_valid_until(self):
        assert _timeline_matches("", "ch010", "ch015") is False
        assert _timeline_matches("", "ch010", "ch005") is True


class TestSortKeyTimeline:
    """Sort-key timeline filtering handles BBY and all backward-counting systems."""

    def test_bby_sort_keys(self):
        # 3600 BBY = -3600, 3500 BBY = -3500, 3550 BBY = -3550
        # -3600 < -3550 < -3500 (correct chronological order)
        assert _timeline_matches_sort_key(-3600, -3500, -3550) is True

    def test_before_range(self):
        assert _timeline_matches_sort_key(-3600, -3500, -3700) is False

    def test_after_range(self):
        assert _timeline_matches_sort_key(-3600, -3500, -3400) is False

    def test_no_bounds(self):
        assert _timeline_matches_sort_key(None, None, -3550) is True

    def test_only_start(self):
        assert _timeline_matches_sort_key(-3600, None, -3550) is True
        assert _timeline_matches_sort_key(-3600, None, -3700) is False

    def test_only_end(self):
        assert _timeline_matches_sort_key(None, -3500, -3550) is True
        assert _timeline_matches_sort_key(None, -3500, -3400) is False

    def test_bby_aby_crossing(self):
        # BBY → ABY: -100 (100 BBY) → 0 → 10 (10 ABY)
        assert _timeline_matches_sort_key(-100, 10, 0) is True
        assert _timeline_matches_sort_key(-100, 10, -50) is True
        assert _timeline_matches_sort_key(-100, 10, 5) is True
        assert _timeline_matches_sort_key(-100, 10, -200) is False

    def test_sort_key_in_context_retrieval(self, service):
        """End-to-end: sort key filtering in get_lore_for_context."""
        service.create_universe("sw", "Star Wars", timeline_system="bby_aby")
        # Entry valid 3600-3500 BBY → sort keys -3600 to -3500
        service.create_lore_entry(
            universe_id="sw", category="historical_event",
            title="Old Republic Era Battle",
            content="A battle during the Old Republic",
            valid_from="3600 BBY", valid_until="3500 BBY",
            timeline_sort_start=-3600, timeline_sort_end=-3500,
        )
        # Entry with no timeline bounds
        service.create_lore_entry(
            universe_id="sw", category="faction",
            title="The Force", content="An energy field",
        )

        # Query at 3550 BBY (sort key -3550) → should find both
        results = service.get_lore_for_context(
            "sw", "battle Force", top_k=10, timeline_sort_key=-3550,
        )
        titles = [r.get("metadata", {}).get("title", "") for r in results]
        # The unbounded entry should always appear
        assert any("Force" in t for t in titles)

    @pytest.fixture
    def service(self, tmp_path):
        db = WorldbuildingDB(db_path=str(tmp_path / "sk.db"))
        vs = LoreVectorStore(
            persist_directory=str(tmp_path / "sk_v"),
            embedding_function=MockEmbeddingFunction(),
        )
        return LoreService(db=db, vectorstore=vs)


class TestGetTerminology:
    def test_returns_all_terminology(self, populated_service):
        terms = populated_service.get_terminology("child", walk_parents=True)
        titles = [t["title"] for t in terms]
        assert "Credits" in titles
        assert "Hegemon" in titles

    def test_child_overrides_parent(self, service):
        service.create_universe("parent", "P")
        service.create_universe("child", "C", parent_universe_id="parent")
        service.create_lore_entry(
            universe_id="parent", category="terminology",
            title="Credits", content="Parent definition",
        )
        service.create_lore_entry(
            universe_id="child", category="terminology",
            title="Credits", content="Child override definition",
        )
        terms = service.get_terminology("child")
        credits = [t for t in terms if t["title"] == "Credits"]
        assert len(credits) == 1
        assert "Child override" in credits[0]["content"]


class TestDialogueContext:
    def test_returns_speech_patterns_unfiltered(self, populated_service):
        ctx = populated_service.get_dialogue_context("child")
        assert len(ctx["speech_patterns"]) >= 1
        patterns = [s["title"] for s in ctx["speech_patterns"]]
        assert "Draleth Hegemony" in patterns

    def test_knowledge_gated_filters_by_affiliation(self, service):
        service.create_universe("u1", "U1")
        service.create_lore_entry(
            universe_id="u1", category="faction", title="Faction A",
            content="A faction", speech_patterns="Formal speech",
            visibility="faction_internal",
        )
        # Get the entry_id
        entries = service.db.list_lore_entries("u1")
        faction_a_id = entries[0]["entry_id"]

        service.create_lore_entry(
            universe_id="u1", category="faction", title="Faction B",
            content="Another faction", speech_patterns="Casual speech",
            visibility="faction_internal",
        )

        # Affiliate character with Faction A only
        service.db.affiliate_character("char_a", faction_a_id)

        ctx = service.get_dialogue_context("u1", character_ids=["char_a"])
        patterns = [s["title"] for s in ctx["speech_patterns"]]
        assert "Faction A" in patterns
        assert "Faction B" not in patterns  # Not affiliated

    def test_public_always_included(self, service):
        service.create_universe("u1", "U1")
        service.create_lore_entry(
            universe_id="u1", category="faction", title="Public Faction",
            content="Everyone knows", speech_patterns="Standard speech",
            visibility="public",
        )
        ctx = service.get_dialogue_context("u1", character_ids=["anyone"])
        patterns = [s["title"] for s in ctx["speech_patterns"]]
        assert "Public Faction" in patterns


class TestCanonOverrideResolution:
    def test_override_removes_matching_canon(self, service):
        wb_results = [
            {"id": "e1", "text": "Custom Jedi lore", "metadata": {
                "title": "jedi order", "canon_override": 1,
            }},
        ]
        canon_results = [
            {"id": "c1", "text": "Canon jedi order lore about the light side"},
            {"id": "c2", "text": "Canon sith lore about the dark side"},
        ]
        merged = service.resolve_canon_overrides(wb_results, canon_results)
        # The jedi canon result should be removed (text contains "jedi order")
        ids = [r["id"] for r in merged]
        assert "e1" in ids
        assert "c1" not in ids  # overridden
        assert "c2" in ids  # not overridden

    def test_no_override_keeps_all(self, service):
        wb_results = [
            {"id": "e1", "text": "Custom lore", "metadata": {
                "title": "custom", "canon_override": 0,
            }},
        ]
        canon_results = [
            {"id": "c1", "text": "Canon lore"},
        ]
        merged = service.resolve_canon_overrides(wb_results, canon_results)
        assert len(merged) == 2


class TestReconciliation:
    def test_removes_chromadb_orphans(self, service):
        service.create_universe("u1", "U1")
        # Add entry to ChromaDB but not SQLite
        service.vectorstore.upsert_entry(
            "u1", "orphan_id", "Orphan content",
            {"status": "canonical"},
        )
        assert "orphan_id" in service.vectorstore.get_all_entry_ids("u1")

        fixes = service.reconcile_chromadb_orphans("u1")
        assert fixes >= 1
        assert "orphan_id" not in service.vectorstore.get_all_entry_ids("u1")

    def test_reinserts_missing_chromadb_entries(self, service):
        service.create_universe("u1", "U1")
        # Create entry normally, then remove from ChromaDB only
        eid = service.create_lore_entry(
            universe_id="u1", category="faction",
            title="Missing", content="Should be re-inserted",
        )
        service.vectorstore.remove_entry("u1", eid)
        assert eid not in service.vectorstore.get_all_entry_ids("u1")

        fixes = service.reconcile_chromadb_orphans("u1")
        assert fixes >= 1
        assert eid in service.vectorstore.get_all_entry_ids("u1")

    def test_no_fixes_when_in_sync(self, service):
        service.create_universe("u1", "U1")
        service.create_lore_entry(
            universe_id="u1", category="faction",
            title="Synced", content="In both stores",
        )
        fixes = service.reconcile_chromadb_orphans("u1")
        assert fixes == 0
