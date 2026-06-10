"""Tests for schema migration infrastructure in StoryState."""

from pathlib import Path

import pytest

from src.memory.story_state import StoryState


class TestSchemaMigration:
    """Tests for the migration system."""

    def test_new_db_has_latest_version(self, temp_dir):
        """A fresh database is initialized at the latest schema version.

        Schema v6 was added by the relay v3 refactor (collapses the
        revision_status enum to draft / saved_clean / saved_with_advisory
        / quarantined). Schema v7 was added by Slice 1 of the architecture
        upgrade (gap_notes table for state-firewall isolations). Schema v8
        adds characters.status for the declared-state apply.
        """
        db_path = str(Path(temp_dir) / "test.db")
        state = StoryState(db_path=db_path)
        assert state.get_schema_version() == 8
        state.close()

    def test_migration_creates_phase5_tables(self, temp_dir):
        """Migration v1->v2 creates all six Phase 5 tables."""
        db_path = str(Path(temp_dir) / "test.db")
        state = StoryState(db_path=db_path)
        cursor = state.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row["name"] for row in cursor.fetchall()}
        phase5_tables = {
            "character_arcs",
            "subplots",
            "hooks",
            "terminology_registry",
            "propagation_debts",
        }
        assert phase5_tables.issubset(tables), f"Missing: {phase5_tables - tables}"
        state.close()

    def test_schema_migrations_table_tracks_versions(self, temp_dir):
        """The schema_migrations table records applied versions."""
        db_path = str(Path(temp_dir) / "test.db")
        state = StoryState(db_path=db_path)
        rows = state.conn.execute(
            "SELECT version, description FROM schema_migrations ORDER BY version"
        ).fetchall()
        versions = [dict(r) for r in rows]
        assert len(versions) >= 2
        assert versions[0]["version"] == 1
        assert versions[1]["version"] == 2
        state.close()

    def test_migration_idempotent(self, temp_dir):
        """Opening the same DB twice does not re-run migrations."""
        db_path = str(Path(temp_dir) / "test.db")
        state1 = StoryState(db_path=db_path)
        state1.close()
        state2 = StoryState(db_path=db_path)
        rows = state2.conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        # Should have exactly one entry per migration, no duplicates.
        # v7 adds the gap_notes table (Slice 1 architecture upgrade);
        # v8 adds characters.status (declared-state apply).
        versions = [r["version"] for r in rows]
        assert versions == [1, 2, 3, 4, 5, 6, 7, 8]
        state2.close()

    def test_existing_data_preserved_after_migration(self, temp_dir):
        """Data in Phase 1-4 tables survives migration."""
        db_path = str(Path(temp_dir) / "test.db")
        state = StoryState(db_path=db_path)
        state.add_character(id="test_char", name="Test Character")
        state.add_plot_thread(id="thread_1", description="A plot thread")
        state.close()

        # Re-open — migration should not destroy data
        state2 = StoryState(db_path=db_path)
        assert state2.get_character("test_char") is not None
        assert state2.get_plot_thread("thread_1") is not None
        state2.close()

    def test_phase1_tables_still_present(self, story_state):
        """All original Phase 1-4 tables still exist alongside Phase 5 tables."""
        cursor = story_state.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row["name"] for row in cursor.fetchall()}
        original_tables = {
            "characters", "character_knowledge", "character_relationships",
            "plot_threads", "timeline", "chekhov_guns", "chapter_log",
        }
        assert original_tables.issubset(tables)
