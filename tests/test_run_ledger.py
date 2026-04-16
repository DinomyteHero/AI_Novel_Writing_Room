"""Unit tests for RunLedger — schema, emit/query, attempt_id scoping, migration."""

import sqlite3
from pathlib import Path

import pytest

from src.run_ledger import RunLedger


@pytest.fixture
def ledger_path(temp_dir):
    return str(Path(temp_dir) / "run_ledger.db")


@pytest.fixture
def ledger(ledger_path):
    ledger = RunLedger(db_path=ledger_path, run_id="test_run")
    try:
        yield ledger
    finally:
        ledger.close()


class TestRunLedgerSchema:
    """Tests for the table layout on a fresh database."""

    def test_fresh_db_has_attempt_id_column(self, ledger):
        """Fresh databases are created with attempt_id already in the schema."""
        columns = {
            row[1]
            for row in ledger.conn.execute("PRAGMA table_info(run_ledger)").fetchall()
        }
        assert "attempt_id" in columns
        assert "run_id" in columns

    def test_emit_without_attempt_id_works(self, ledger):
        """The attempt_id parameter defaults to None and stays None in the row."""
        event_id = ledger.emit(
            "pipeline_start",
            payload={"total_scenes": 3},
        )
        row = ledger.conn.execute(
            "SELECT attempt_id FROM run_ledger WHERE id = ?", (event_id,)
        ).fetchone()
        assert row["attempt_id"] is None


class TestAttemptIdScoping:
    """Tests for attempt_id persistence and querying."""

    def test_attempt_id_round_trips(self, ledger):
        """An emitted attempt_id is read back on the matching row."""
        event_id = ledger.emit(
            "gate_fail",
            chapter_number=1,
            scene_number=2,
            payload={"verdict": "fail_structural"},
            attempt_id="ch1_scene2_attempt_1",
        )
        row = ledger.conn.execute(
            "SELECT attempt_id FROM run_ledger WHERE id = ?", (event_id,)
        ).fetchone()
        assert row["attempt_id"] == "ch1_scene2_attempt_1"

    def test_filter_by_attempt_id_returns_only_matches(self, ledger):
        """get_events filters on attempt_id without leaking other attempts."""
        ledger.emit("agent_start", chapter_number=1, scene_number=1, attempt_id="ch1_scene1_attempt_1")
        ledger.emit("agent_complete", chapter_number=1, scene_number=1, attempt_id="ch1_scene1_attempt_1")
        ledger.emit("gate_fail", chapter_number=1, scene_number=1, attempt_id="ch1_scene1_attempt_1")
        ledger.emit("agent_start", chapter_number=1, scene_number=1, attempt_id="ch1_scene1_attempt_2")
        ledger.emit("agent_complete", chapter_number=1, scene_number=1, attempt_id="ch1_scene1_attempt_2")
        ledger.emit("gate_pass", chapter_number=1, scene_number=1, attempt_id="ch1_scene1_attempt_2")

        attempt1 = ledger.get_events(attempt_id="ch1_scene1_attempt_1")
        attempt2 = ledger.get_events(attempt_id="ch1_scene1_attempt_2")

        assert {e["event_type"] for e in attempt1} == {"agent_start", "agent_complete", "gate_fail"}
        assert {e["event_type"] for e in attempt2} == {"agent_start", "agent_complete", "gate_pass"}
        assert all(e["attempt_id"] == "ch1_scene1_attempt_1" for e in attempt1)
        assert all(e["attempt_id"] == "ch1_scene1_attempt_2" for e in attempt2)

    def test_null_attempt_id_not_returned_when_filtering(self, ledger):
        """Events without an attempt_id do not match attempt_id filters."""
        ledger.emit("pipeline_start")
        ledger.emit("gate_pass", chapter_number=1, scene_number=1, attempt_id="ch1_scene1_attempt_1")

        matched = ledger.get_events(attempt_id="ch1_scene1_attempt_1")
        assert len(matched) == 1
        assert matched[0]["event_type"] == "gate_pass"


class TestMigration:
    """Tests for the schema migration that adds attempt_id to older databases."""

    def _seed_pre_attempt_id_database(self, db_path: str) -> None:
        """Create a database that predates the attempt_id column (mirrors
        the shape shipped before the Phase 4 ledger update)."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE run_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                run_id TEXT,
                event_type TEXT NOT NULL,
                chapter_number INTEGER,
                scene_number INTEGER,
                agent_role TEXT,
                payload TEXT,
                state_hash TEXT
            )
        """)
        conn.execute(
            "INSERT INTO run_ledger (event_type, chapter_number) VALUES (?, ?)",
            ("pipeline_start", 1),
        )
        conn.commit()
        conn.close()

    def test_migration_adds_attempt_id_column(self, temp_dir):
        """Opening a pre-attempt_id database through RunLedger adds the column."""
        db_path = str(Path(temp_dir) / "pre_attempt_id.db")
        self._seed_pre_attempt_id_database(db_path)

        ledger = RunLedger(db_path=db_path, run_id="migrated")
        try:
            columns = {
                row[1]
                for row in ledger.conn.execute("PRAGMA table_info(run_ledger)").fetchall()
            }
            assert "attempt_id" in columns

            # Pre-existing rows survive the migration with NULL attempt_id
            rows = ledger.conn.execute(
                "SELECT attempt_id FROM run_ledger WHERE event_type = 'pipeline_start'"
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["attempt_id"] is None

            # New rows with attempt_id work post-migration
            event_id = ledger.emit(
                "gate_fail",
                chapter_number=1,
                scene_number=1,
                attempt_id="ch1_scene1_attempt_1",
            )
            row = ledger.conn.execute(
                "SELECT attempt_id FROM run_ledger WHERE id = ?", (event_id,)
            ).fetchone()
            assert row["attempt_id"] == "ch1_scene1_attempt_1"
        finally:
            ledger.close()

    def test_migration_is_idempotent(self, temp_dir):
        """Running RunLedger twice on the same database does not error or
        attempt to re-add the column."""
        db_path = str(Path(temp_dir) / "idempotent.db")
        self._seed_pre_attempt_id_database(db_path)

        ledger1 = RunLedger(db_path=db_path, run_id="first")
        ledger1.close()

        # Second open should succeed without raising on the duplicate ALTER
        ledger2 = RunLedger(db_path=db_path, run_id="second")
        try:
            columns = {
                row[1]
                for row in ledger2.conn.execute("PRAGMA table_info(run_ledger)").fetchall()
            }
            assert "attempt_id" in columns
        finally:
            ledger2.close()
