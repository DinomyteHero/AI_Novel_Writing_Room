"""Tests for the one-shot scripts/migrate_status_vocab.py migration script.

The script walks for ``story_state.db`` files and opens each through
``StoryState``, which triggers the v5→v6 auto-migration. These tests seed
fixture DBs with legacy labels, run the script, and verify the remap.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

# Ensure the scripts directory is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts import migrate_status_vocab


def _seed_v5_db(db_path: Path) -> None:
    """Seed a DB that looks like v5: six-value revision_status CHECK."""
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        );
        CREATE TABLE chapter_log (
            chapter_number INTEGER PRIMARY KEY,
            word_count INTEGER,
            structural_phase TEXT,
            pov_character TEXT,
            summary TEXT,
            quality_scores TEXT,
            failure_codes TEXT,
            revision_status TEXT CHECK(revision_status IN (
                'draft', 'gate_failed', 'gate_passed', 'polished',
                'final_gate_rejected', 'approved'
            )),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            revised_at TIMESTAMP
        );
        CREATE TABLE scene_log (
            chapter_number INTEGER NOT NULL,
            scene_number INTEGER NOT NULL,
            word_count INTEGER,
            structural_phase TEXT,
            pov_character TEXT,
            summary TEXT,
            quality_scores TEXT,
            failure_codes TEXT,
            revision_status TEXT CHECK(revision_status IN (
                'draft', 'gate_failed', 'gate_passed', 'polished',
                'final_gate_rejected', 'approved'
            )),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            revised_at TIMESTAMP,
            PRIMARY KEY (chapter_number, scene_number)
        );
        CREATE TABLE characters (id TEXT PRIMARY KEY, name TEXT);
    """)
    for v in (1, 2, 3, 4, 5):
        conn.execute(
            "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
            (v, f"seeded v{v}"),
        )
    rows = [
        (1, 1000, "gate_passed"),
        (2, 2000, "gate_failed"),
        (3, 3000, "polished"),
        (4, 4000, "final_gate_rejected"),
        (5, 5000, "approved"),
    ]
    for ch, wc, status in rows:
        conn.execute(
            "INSERT INTO chapter_log (chapter_number, word_count, revision_status) VALUES (?, ?, ?)",
            (ch, wc, status),
        )
    conn.commit()
    conn.close()


class TestFindStoryStateDbs:
    def test_finds_nested_dbs(self, tmp_path):
        (tmp_path / "proj_a" / "state").mkdir(parents=True)
        (tmp_path / "proj_b").mkdir(parents=True)
        db_a = tmp_path / "proj_a" / "state" / "story_state.db"
        db_b = tmp_path / "proj_b" / "story_state.db"
        db_a.touch()
        db_b.touch()

        # Unrelated file doesn't match
        (tmp_path / "proj_a" / "other.db").touch()

        found = migrate_status_vocab.find_story_state_dbs([tmp_path])
        assert set(found) == {db_a, db_b}

    def test_ignores_missing_roots(self, tmp_path):
        found = migrate_status_vocab.find_story_state_dbs(
            [tmp_path / "does_not_exist"]
        )
        assert found == []


class TestSnapshotStatuses:
    def test_snapshot_counts_by_status(self, tmp_path):
        db = tmp_path / "story_state.db"
        _seed_v5_db(db)
        snap = migrate_status_vocab.snapshot_statuses(db)
        chapter_counts = snap["chapter_log"]
        assert chapter_counts["gate_passed"] == 1
        assert chapter_counts["gate_failed"] == 1
        assert chapter_counts["polished"] == 1
        assert chapter_counts["final_gate_rejected"] == 1
        assert chapter_counts["approved"] == 1

    def test_snapshot_on_missing_tables_returns_empty(self, tmp_path):
        db = tmp_path / "empty.db"
        # Create a DB with no log tables at all.
        sqlite3.connect(str(db)).close()
        snap = migrate_status_vocab.snapshot_statuses(db)
        assert snap == {"chapter_log": {}, "scene_log": {}}


class TestMigrateDb:
    def test_remaps_all_legacy_values(self, tmp_path):
        db = tmp_path / "story_state.db"
        _seed_v5_db(db)

        report = migrate_status_vocab.migrate_db(db)

        assert report["remapped"] is True
        assert report["schema_version"] >= 6

        after = report["after"]["chapter_log"]
        # Legacy labels collapse to the three-value enum.
        assert after.get("saved_clean", 0) == 3  # gate_passed + polished + approved
        assert after.get("saved_with_advisory", 0) == 2  # gate_failed + final_gate_rejected
        assert "gate_passed" not in after
        assert "final_gate_rejected" not in after

    def test_idempotent(self, tmp_path):
        db = tmp_path / "story_state.db"
        _seed_v5_db(db)

        first = migrate_status_vocab.migrate_db(db)
        second = migrate_status_vocab.migrate_db(db)

        assert first["remapped"] is True
        # Second run sees no legacy labels to remap.
        assert second["remapped"] is False
        assert second["after"] == first["after"]


class TestRunDryRun:
    def test_dry_run_does_not_mutate(self, tmp_path, capsys):
        db = tmp_path / "story_state.db"
        _seed_v5_db(db)

        before = migrate_status_vocab.snapshot_statuses(db)
        rc = migrate_status_vocab.run(roots=[tmp_path], dry_run=True)
        after = migrate_status_vocab.snapshot_statuses(db)

        assert rc == 0
        assert before == after
        captured = capsys.readouterr()
        assert "legacy values present: True" in captured.out


class TestRunMigrates:
    def test_run_migrates_all_dbs(self, tmp_path, capsys):
        db_a = tmp_path / "proj_a" / "story_state.db"
        db_b = tmp_path / "proj_b" / "story_state.db"
        db_a.parent.mkdir()
        db_b.parent.mkdir()
        _seed_v5_db(db_a)
        _seed_v5_db(db_b)

        rc = migrate_status_vocab.run(roots=[tmp_path], dry_run=False)
        assert rc == 0

        # Both DBs migrated.
        snap_a = migrate_status_vocab.snapshot_statuses(db_a)
        snap_b = migrate_status_vocab.snapshot_statuses(db_b)
        for snap in (snap_a, snap_b):
            assert "gate_passed" not in snap["chapter_log"]
            assert "saved_clean" in snap["chapter_log"]

        captured = capsys.readouterr()
        assert "Processed 2 DB(s)" in captured.out
        assert "had status-vocab changes" in captured.out
