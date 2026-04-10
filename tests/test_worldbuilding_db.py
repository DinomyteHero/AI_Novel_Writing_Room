"""Tests for WorldbuildingDB — SQLite schema, CRUD, relations, bindings."""

import json
import sqlite3
from pathlib import Path

import pytest

from src.worldbuilding.worldbuilding_db import WorldbuildingDB


@pytest.fixture
def db(tmp_path):
    db = WorldbuildingDB(db_path=str(tmp_path / "test_wb.db"))
    yield db
    db.close()


class TestInit:
    def test_creates_database_file(self, tmp_path):
        db_path = str(tmp_path / "sub" / "test.db")
        db = WorldbuildingDB(db_path=db_path)
        assert Path(db_path).exists()
        db.close()

    def test_wal_mode_enabled(self, db):
        row = db.conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"

    def test_foreign_keys_enabled(self, db):
        row = db.conn.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1

    def test_schema_migration_baseline(self, db):
        assert db.get_schema_version() == 2  # v1 baseline + v2 migration

    def test_tables_exist(self, db):
        tables = {r[0] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "universes" in tables
        assert "lore_entries" in tables
        assert "lore_relations" in tables
        assert "project_universe_binding" in tables
        assert "schema_migrations" in tables


class TestUniverses:
    def test_create_and_get(self, db):
        db.create_universe("test_u", "Test Universe", franchise="star_wars")
        u = db.get_universe("test_u")
        assert u is not None
        assert u["display_name"] == "Test Universe"
        assert u["franchise"] == "star_wars"

    def test_get_missing_returns_none(self, db):
        assert db.get_universe("nonexistent") is None

    def test_list_universes(self, db):
        db.create_universe("u1", "Universe 1")
        db.create_universe("u2", "Universe 2")
        universes = db.list_universes()
        assert len(universes) == 2

    def test_list_universes_with_entry_count(self, db):
        db.create_universe("u1", "Universe 1")
        db.create_lore_entry("e1", "u1", "faction", "Faction A", "Content")
        db.create_lore_entry("e2", "u1", "location", "Place B", "Content")
        universes = db.list_universes()
        assert universes[0]["entry_count"] == 2

    def test_parent_universe(self, db):
        db.create_universe("parent", "Parent Universe")
        db.create_universe("child", "Child", parent_universe_id="parent")
        child = db.get_universe("child")
        assert child["parent_universe_id"] == "parent"

    def test_get_universe_chain(self, db):
        db.create_universe("grandparent", "GP")
        db.create_universe("parent", "P", parent_universe_id="grandparent")
        db.create_universe("child", "C", parent_universe_id="parent")
        chain = db.get_universe_chain("child")
        assert chain == ["child", "parent", "grandparent"]

    def test_get_universe_chain_no_parent(self, db):
        db.create_universe("solo", "Solo")
        assert db.get_universe_chain("solo") == ["solo"]

    def test_delete_universe_cascades(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "F", "content")
        db.create_lore_entry("e2", "u1", "location", "L", "content")
        db.create_relation("e1", "e2", "located_in")
        db.bind_project("proj1", "u1")

        db.delete_universe("u1")

        assert db.get_universe("u1") is None
        assert db.get_lore_entry("e1") is None
        assert db.get_lore_entry("e2") is None
        assert db.get_project_binding("proj1") is None


class TestLoreEntries:
    def test_create_and_get(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "Sith Order", "An ancient order")
        entry = db.get_lore_entry("e1")
        assert entry is not None
        assert entry["title"] == "Sith Order"
        assert entry["category"] == "faction"
        assert entry["status"] == "canonical"
        assert entry["canon_override"] is False

    def test_create_with_all_fields(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry(
            "e1", "u1", "terminology", "Kriffing",
            content="An expletive used across the galaxy",
            status="canonical",
            valid_from="3500 BBY",
            valid_until="0 BBY",
            thematic_notes="Use sparingly for emphasis",
            speech_patterns="Working class, military informal",
            canon_override=True,
            override_notes="Replaces standard canon profanity",
            tags=["profanity", "slang"],
            source_project_id="proj1",
            introduced_in_project_id="proj1",
            extraction_source="workshop",
        )
        entry = db.get_lore_entry("e1")
        assert entry["valid_from"] == "3500 BBY"
        assert entry["canon_override"] is True
        assert entry["tags"] == ["profanity", "slang"]
        assert entry["extraction_source"] == "workshop"

    def test_update_entry(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "Old Name", "Old content")
        db.update_lore_entry("e1", title="New Name", content="New content")
        entry = db.get_lore_entry("e1")
        assert entry["title"] == "New Name"
        assert entry["content"] == "New content"

    def test_update_invalid_column_raises(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "F", "C")
        with pytest.raises(ValueError, match="Invalid column"):
            db.update_lore_entry("e1", nonexistent_field="value")

    def test_delete_entry(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "F", "C")
        db.delete_lore_entry("e1")
        assert db.get_lore_entry("e1") is None

    def test_list_entries(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "F1", "C1")
        db.create_lore_entry("e2", "u1", "location", "L1", "C2")
        db.create_lore_entry("e3", "u1", "faction", "F2", "C3")
        all_entries = db.list_lore_entries("u1")
        assert len(all_entries) == 3

    def test_list_entries_filter_category(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "F1", "C1")
        db.create_lore_entry("e2", "u1", "location", "L1", "C2")
        factions = db.list_lore_entries("u1", category="faction")
        assert len(factions) == 1
        assert factions[0]["category"] == "faction"

    def test_list_entries_filter_status(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "F1", "C1", status="canonical")
        db.create_lore_entry("e2", "u1", "faction", "F2", "C2", status="provisional")
        canonical = db.list_lore_entries("u1", status="canonical")
        assert len(canonical) == 1

    def test_list_entries_text_search(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "Sith Order", "Dark side users")
        db.create_lore_entry("e2", "u1", "faction", "Jedi Council", "Light side")
        results = db.list_lore_entries("u1", text_search="Dark")
        assert len(results) == 1

    def test_promote_entry(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "F", "C", status="provisional")
        db.promote_lore_entry("e1")
        assert db.get_lore_entry("e1")["status"] == "canonical"

    def test_deprecate_entry(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "F", "C")
        db.deprecate_lore_entry("e1")
        assert db.get_lore_entry("e1")["status"] == "deprecated"

    def test_get_terminology_entries(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "terminology", "Credits", "Currency")
        db.create_lore_entry("e2", "u1", "faction", "Sith", "Bad guys")
        db.create_lore_entry("e3", "u1", "terminology", "Holonet", "Internet", status="deprecated")
        terms = db.get_terminology_entries("u1")
        assert len(terms) == 1
        assert terms[0]["title"] == "Credits"

    def test_get_speech_pattern_entries(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "Sith", "C",
                             speech_patterns="Formal, archaic")
        db.create_lore_entry("e2", "u1", "faction", "Smugglers", "C")
        entries = db.get_speech_pattern_entries("u1")
        assert len(entries) == 1
        assert entries[0]["title"] == "Sith"

    def test_get_all_entry_ids(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "F1", "C")
        db.create_lore_entry("e2", "u1", "location", "L1", "C")
        ids = db.get_all_entry_ids("u1")
        assert ids == {"e1", "e2"}

    def test_tags_json_roundtrip(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "F", "C",
                             tags=["tag1", "tag2", "tag3"])
        entry = db.get_lore_entry("e1")
        assert entry["tags"] == ["tag1", "tag2", "tag3"]


class TestLoreRelations:
    def test_create_and_get(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "Sith", "C")
        db.create_lore_entry("e2", "u1", "location", "Korriban", "C")
        db.create_relation("e1", "e2", "located_in", description="Homeworld")

        rels = db.get_relations("e1")
        assert len(rels) == 1
        assert rels[0]["relation_type"] == "located_in"

    def test_get_relations_both_directions(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "A", "C")
        db.create_lore_entry("e2", "u1", "faction", "B", "C")
        db.create_relation("e1", "e2", "allied_with")

        # Should appear when querying either side
        assert len(db.get_relations("e1")) == 1
        assert len(db.get_relations("e2")) == 1

    def test_delete_relation(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "A", "C")
        db.create_lore_entry("e2", "u1", "faction", "B", "C")
        db.create_relation("e1", "e2", "enemy_of")
        db.delete_relation("e1", "e2", "enemy_of")
        assert len(db.get_relations("e1")) == 0

    def test_unique_constraint(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "A", "C")
        db.create_lore_entry("e2", "u1", "faction", "B", "C")
        db.create_relation("e1", "e2", "allied_with")
        with pytest.raises(sqlite3.IntegrityError):
            db.create_relation("e1", "e2", "allied_with")

    def test_dialogue_implications(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "A", "C")
        db.create_lore_entry("e2", "u1", "faction", "B", "C")
        db.create_relation("e1", "e2", "enemy_of",
                           dialogue_implications="Tension and distrust")
        implications = db.get_dialogue_implications(["e1", "e2"])
        assert len(implications) == 1
        assert implications[0]["dialogue_implications"] == "Tension and distrust"


class TestVisibilityAndSortKeys:
    def test_create_entry_with_visibility(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "Secret Faction", "C",
                             visibility="faction_internal")
        entry = db.get_lore_entry("e1")
        assert entry["visibility"] == "faction_internal"

    def test_create_entry_with_sort_keys(self, db):
        db.create_universe("u1", "U1", timeline_system="bby_aby")
        db.create_lore_entry("e1", "u1", "historical_event", "Battle", "C",
                             valid_from="3600 BBY", valid_until="3500 BBY",
                             timeline_sort_start=-3600, timeline_sort_end=-3500)
        entry = db.get_lore_entry("e1")
        assert entry["timeline_sort_start"] == -3600
        assert entry["timeline_sort_end"] == -3500

    def test_universe_timeline_system(self, db):
        db.create_universe("u1", "U1", timeline_system="bby_aby")
        u = db.get_universe("u1")
        assert u["timeline_system"] == "bby_aby"

    def test_default_visibility_is_public(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "F", "C")
        entry = db.get_lore_entry("e1")
        assert entry["visibility"] == "public"


class TestCharacterAffiliations:
    def test_affiliate_and_get(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "Sith", "C")
        db.affiliate_character("ben_skywalker", "e1", "member")
        affs = db.get_character_affiliations("ben_skywalker")
        assert len(affs) == 1
        assert affs[0]["entry_id"] == "e1"
        assert affs[0]["title"] == "Sith"

    def test_get_affiliated_characters(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "Sith", "C")
        db.affiliate_character("char_a", "e1")
        db.affiliate_character("char_b", "e1")
        chars = db.get_affiliated_characters("e1")
        assert len(chars) == 2

    def test_remove_affiliation(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e1", "u1", "faction", "Sith", "C")
        db.affiliate_character("ben", "e1")
        db.remove_character_affiliation("ben", "e1")
        assert len(db.get_character_affiliations("ben")) == 0

    def test_get_lore_for_character_visibility(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e_pub", "u1", "faction", "Public Faction", "C",
                             visibility="public")
        db.create_lore_entry("e_int", "u1", "faction", "Internal Faction", "C",
                             visibility="faction_internal")
        db.create_lore_entry("e_sec", "u1", "faction", "Secret Faction", "C",
                             visibility="secret")

        # Affiliate character with the internal faction
        db.affiliate_character("ben", "e_int")

        visible = db.get_lore_for_character("ben", "u1")
        titles = {v["title"] for v in visible}
        assert "Public Faction" in titles
        assert "Internal Faction" in titles
        assert "Secret Faction" not in titles

    def test_unaffiliated_sees_only_public(self, db):
        db.create_universe("u1", "U1")
        db.create_lore_entry("e_pub", "u1", "faction", "Public", "C",
                             visibility="public")
        db.create_lore_entry("e_int", "u1", "faction", "Internal", "C",
                             visibility="faction_internal")

        visible = db.get_lore_for_character("stranger", "u1")
        titles = {v["title"] for v in visible}
        assert "Public" in titles
        assert "Internal" not in titles


class TestProjectBinding:
    def test_bind_and_get(self, db):
        db.create_universe("u1", "U1")
        db.bind_project("proj1", "u1", reading_order=1,
                        timeline_start="3500 BBY", timeline_end="3490 BBY")
        binding = db.get_project_binding("proj1")
        assert binding is not None
        assert binding["universe_id"] == "u1"
        assert binding["reading_order"] == 1
        assert binding["timeline_start"] == "3500 BBY"

    def test_get_missing_returns_none(self, db):
        assert db.get_project_binding("nonexistent") is None

    def test_reading_order(self, db):
        db.create_universe("u1", "U1")
        db.bind_project("proj1", "u1", reading_order=2)
        assert db.get_project_reading_order("proj1") == 2

    def test_rebind_replaces(self, db):
        db.create_universe("u1", "U1")
        db.create_universe("u2", "U2")
        db.bind_project("proj1", "u1", reading_order=1)
        db.bind_project("proj1", "u2", reading_order=2)
        binding = db.get_project_binding("proj1")
        assert binding["universe_id"] == "u2"
