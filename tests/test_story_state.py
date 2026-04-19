"""Tests for StoryState SQLite-backed persistent state tracker."""

import json
import sqlite3
from pathlib import Path

import pytest

from src.memory.story_state import StoryState


class TestStoryStateInit:
    """Tests for database creation and table setup."""

    def test_creates_database_file(self, temp_dir):
        """StoryState creates the SQLite database file on init."""
        db_path = str(Path(temp_dir) / "test.db")
        state = StoryState(db_path=db_path)
        assert Path(db_path).exists()
        state.close()

    def test_creates_all_tables(self, story_state):
        """All expected tables are created during init."""
        cursor = story_state.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {row["name"] for row in cursor.fetchall()}
        expected = {
            "characters",
            "character_knowledge",
            "character_relationships",
            "plot_threads",
            "timeline",
            "chekhov_guns",
            "chapter_log",
        }
        assert expected.issubset(tables)


class TestCharacters:
    """Tests for character CRUD operations."""

    def test_add_and_get_character(self, story_state):
        """add_character followed by get_character round-trips correctly."""
        story_state.add_character(
            id="ben_skywalker",
            name="Ben Skywalker",
            current_location="Jedi Temple",
            emotional_state="determined",
            arc_position="Mission lead",
            inventory=["lightsaber", "datapad"],
        )
        char = story_state.get_character("ben_skywalker")
        assert char is not None
        assert char["name"] == "Ben Skywalker"
        assert char["current_location"] == "Jedi Temple"
        assert char["emotional_state"] == "determined"
        assert char["inventory"] == ["lightsaber", "datapad"]

    def test_get_character_returns_none_for_missing(self, story_state):
        """get_character returns None for a non-existent ID."""
        assert story_state.get_character("nonexistent") is None

    def test_update_character_partial(self, story_state):
        """update_character updates only the specified fields."""
        story_state.add_character(
            id="ben_skywalker",
            name="Ben Skywalker",
            current_location="Jedi Temple",
            emotional_state="calm",
        )
        story_state.update_character(
            "ben_skywalker",
            emotional_state="anxious",
            current_location="Unknown Regions",
        )
        char = story_state.get_character("ben_skywalker")
        assert char["emotional_state"] == "anxious"
        assert char["current_location"] == "Unknown Regions"
        assert char["name"] == "Ben Skywalker"  # unchanged

    def test_update_character_inventory(self, story_state):
        """update_character serializes inventory as JSON."""
        story_state.add_character(id="ben", name="Ben", inventory=["lightsaber"])
        story_state.update_character("ben", inventory=["lightsaber", "holocron"])
        char = story_state.get_character("ben")
        assert char["inventory"] == ["lightsaber", "holocron"]


class TestInitFromConceptSeed:
    """Tests for bulk init from concept seed."""

    def test_init_from_concept_seed(self, story_state, sample_concept_seed):
        """init_from_concept_seed creates all cast characters with slugified IDs."""
        story_state.init_from_concept_seed(sample_concept_seed)
        all_chars = story_state.get_all_characters()
        # The synthetic fixture has 4 cast members. get_all_characters()
        # already excludes the __world__ sentinel.
        assert len(all_chars) == 4

        expected_ids = {
            "alex_reyes",
            "morgan_kade",
            "sam_okafor",
            "dr._elena_voss",
        }
        actual_ids = {c["id"] for c in all_chars}
        assert actual_ids == expected_ids

    def test_init_from_concept_seed_sets_role_as_arc_position(
        self, story_state, sample_concept_seed
    ):
        """Each character's role from the seed is stored as arc_position."""
        story_state.init_from_concept_seed(sample_concept_seed)
        lead = story_state.get_character("alex_reyes")
        assert lead is not None
        assert lead["arc_position"] == "Lead investigator, primary POV"


class TestKnowledge:
    """Tests for knowledge CRUD operations."""

    def test_add_and_get_knowledge(self, story_state):
        """add_knowledge and get_knowledge round-trip correctly."""
        story_state.add_character(id="ben", name="Ben")
        story_state.add_knowledge(
            character_id="ben",
            fact_id="scholar_secret",
            fact_description="The scholar has visited the markers before",
            layer="belief",
            is_accurate=True,
            acquired_chapter=3,
            source="observation",
        )
        results = story_state.get_knowledge(character_id="ben")
        assert len(results) == 1
        assert results[0]["fact_id"] == "scholar_secret"
        assert results[0]["layer"] == "belief"

    def test_get_knowledge_with_filters(self, story_state):
        """get_knowledge filters by character_id, layer, and fact_id."""
        story_state.add_character(id="ben", name="Ben")
        story_state.add_character(id="mando", name="Mando")
        story_state.add_knowledge(
            character_id="ben",
            fact_id="fact_a",
            fact_description="A",
            layer="belief",
        )
        story_state.add_knowledge(
            character_id="ben",
            fact_id="fact_b",
            fact_description="B",
            layer="truth",
        )
        story_state.add_knowledge(
            character_id="mando",
            fact_id="fact_a",
            fact_description="C",
            layer="belief",
        )

        # Filter by character
        assert len(story_state.get_knowledge(character_id="ben")) == 2
        # Filter by layer
        assert len(story_state.get_knowledge(layer="belief")) == 2
        # Filter by fact_id
        assert len(story_state.get_knowledge(fact_id="fact_a")) == 2
        # Combine filters
        assert len(story_state.get_knowledge(character_id="ben", layer="belief")) == 1


class TestRelationships:
    """Tests for relationship CRUD operations."""

    def test_add_and_get_relationships(self, story_state):
        """add_relationship and get_relationships round-trip correctly."""
        story_state.add_character(id="ben", name="Ben")
        story_state.add_character(id="mando", name="Mando")
        story_state.add_relationship(
            character_a="ben",
            character_b="mando",
            relationship_type="crew_mates",
            status="tense",
            last_updated_chapter=3,
        )
        rels = story_state.get_relationships("ben")
        assert len(rels) == 1
        assert rels[0]["relationship_type"] == "crew_mates"
        assert rels[0]["status"] == "tense"

        # Also visible from mando's side
        rels_mando = story_state.get_relationships("mando")
        assert len(rels_mando) == 1


class TestPlotThreads:
    """Tests for plot thread CRUD operations."""

    def test_add_and_get_plot_thread(self, story_state):
        """add_plot_thread and get_plot_thread round-trip correctly."""
        story_state.add_plot_thread(
            id="betrayal",
            description="The scholar's hidden agenda",
            status="planted",
            planted_chapter=1,
            urgency="background",
            related_characters=["ben", "scholar"],
        )
        thread = story_state.get_plot_thread("betrayal")
        assert thread is not None
        assert thread["description"] == "The scholar's hidden agenda"
        assert thread["related_characters"] == ["ben", "scholar"]

    def test_update_plot_thread(self, story_state):
        """update_plot_thread updates only specified fields."""
        story_state.add_plot_thread(
            id="betrayal",
            description="The scholar's hidden agenda",
            status="planted",
            urgency="background",
        )
        story_state.update_plot_thread(
            "betrayal",
            status="active",
            urgency="rising",
        )
        thread = story_state.get_plot_thread("betrayal")
        assert thread["status"] == "active"
        assert thread["urgency"] == "rising"

    def test_get_active_threads(self, story_state):
        """get_active_threads excludes resolved threads."""
        story_state.add_plot_thread(
            id="thread_a", description="Active thread", status="active"
        )
        story_state.add_plot_thread(
            id="thread_b", description="Resolved thread", status="resolved"
        )
        story_state.add_plot_thread(
            id="thread_c", description="Planted thread", status="planted"
        )
        active = story_state.get_active_threads()
        active_ids = {t["id"] for t in active}
        assert active_ids == {"thread_a", "thread_c"}

    def test_get_plot_thread_returns_none_for_missing(self, story_state):
        """get_plot_thread returns None for a non-existent ID."""
        assert story_state.get_plot_thread("nonexistent") is None


class TestTimeline:
    """Tests for timeline operations."""

    def test_add_and_get_timeline(self, story_state):
        """add_timeline_entry and get_timeline round-trip correctly."""
        story_state.add_timeline_entry(
            chapter_number=1,
            scene_number=1,
            story_date="47 ABY Day 1",
            elapsed_time="0 hours",
            key_events=["Crew assembles", "Mission briefing"],
        )
        story_state.add_timeline_entry(
            chapter_number=1,
            scene_number=2,
            story_date="47 ABY Day 1",
            elapsed_time="3 hours",
            key_events=["Departure"],
        )
        entries = story_state.get_timeline(chapter_number=1)
        assert len(entries) == 2
        assert entries[0]["key_events"] == ["Crew assembles", "Mission briefing"]

    def test_get_timeline_all(self, story_state):
        """get_timeline with no filter returns all entries ordered."""
        story_state.add_timeline_entry(chapter_number=2, scene_number=1)
        story_state.add_timeline_entry(chapter_number=1, scene_number=1)
        entries = story_state.get_timeline()
        assert len(entries) == 2
        assert entries[0]["chapter_number"] == 1
        assert entries[1]["chapter_number"] == 2


class TestChekhovGuns:
    """Tests for Chekhov gun operations."""

    def test_add_and_get_unfired_guns(self, story_state):
        """add_chekhov_gun creates an unfired entry retrievable by get_unfired_guns."""
        story_state.add_chekhov_gun(
            id="scholars_datapad",
            item_description="The scholar's encrypted personal datapad",
            planted_chapter=2,
            planted_context="Seen on the scholar's desk during briefing",
        )
        unfired = story_state.get_unfired_guns()
        assert len(unfired) == 1
        assert unfired[0]["id"] == "scholars_datapad"
        assert unfired[0]["fired_status"] == "unfired"

    def test_fire_chekhov_gun(self, story_state):
        """fire_chekhov_gun marks a gun as fired and records the chapter."""
        story_state.add_chekhov_gun(
            id="scholars_datapad",
            item_description="The scholar's encrypted personal datapad",
            planted_chapter=2,
        )
        story_state.fire_chekhov_gun("scholars_datapad", fired_chapter=8)

        unfired = story_state.get_unfired_guns()
        assert len(unfired) == 0

    def test_fire_chekhov_gun_subverted(self, story_state):
        """fire_chekhov_gun can mark a gun as subverted."""
        story_state.add_chekhov_gun(
            id="red_herring", item_description="A mysterious signal", planted_chapter=1
        )
        story_state.fire_chekhov_gun("red_herring", fired_chapter=10, fired_status="subverted")

        unfired = story_state.get_unfired_guns()
        assert len(unfired) == 0


class TestChapterLog:
    """Tests for chapter log operations."""

    def test_add_and_get_chapter_log(self, story_state):
        """add_chapter_log and get_chapter_log round-trip correctly."""
        story_state.add_chapter_log(
            chapter_number=1,
            word_count=3500,
            structural_phase="setup",
            pov_character="Ben Skywalker",
            summary="The crew assembles at the Jedi Temple.",
            quality_scores={"structural": 0.85, "voice": 0.80},
            failure_codes=["minor_pacing"],
            revision_status="draft",
        )
        log = story_state.get_chapter_log(1)
        assert log is not None
        assert log["word_count"] == 3500
        assert log["quality_scores"] == {"structural": 0.85, "voice": 0.80}
        assert log["failure_codes"] == ["minor_pacing"]

    def test_update_chapter_log(self, story_state):
        """update_chapter_log updates only specified fields."""
        story_state.add_chapter_log(
            chapter_number=1,
            word_count=3500,
            revision_status="draft",
        )
        story_state.update_chapter_log(
            1,
            revision_status="saved_clean",
            word_count=3600,
        )
        log = story_state.get_chapter_log(1)
        assert log["revision_status"] == "saved_clean"
        assert log["word_count"] == 3600

    def test_get_chapter_log_returns_none_for_missing(self, story_state):
        """get_chapter_log returns None for a non-existent chapter."""
        assert story_state.get_chapter_log(999) is None


class TestStateHash:
    """Tests for the state hash utility."""

    def test_get_state_hash_consistent(self, story_state):
        """get_state_hash returns the same value for the same state."""
        story_state.add_character(id="ben", name="Ben")
        hash1 = story_state.get_state_hash()
        hash2 = story_state.get_state_hash()
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex length

    def test_get_state_hash_changes_on_mutation(self, story_state):
        """get_state_hash changes when state is modified."""
        hash_empty = story_state.get_state_hash()
        story_state.add_character(id="ben", name="Ben")
        hash_with_char = story_state.get_state_hash()
        assert hash_empty != hash_with_char


class TestCloseAndReopen:
    """Tests for persistence across close/reopen."""

    def test_close_reopen_preserves_data(self, temp_dir):
        """Data persists when the database is closed and reopened."""
        db_path = str(Path(temp_dir) / "persist_test.db")

        state = StoryState(db_path=db_path)
        state.add_character(id="ben", name="Ben Skywalker")
        state.add_plot_thread(id="betrayal", description="Secret agenda")
        state.close()

        state2 = StoryState(db_path=db_path)
        char = state2.get_character("ben")
        thread = state2.get_plot_thread("betrayal")
        state2.close()

        assert char is not None
        assert char["name"] == "Ben Skywalker"
        assert thread is not None
        assert thread["description"] == "Secret agenda"


class TestRevisionStatusEnum:
    """Tests for the revision_status CHECK constraint post relay v3.

    Pre-v3 the enum accepted six values (draft, gate_failed, gate_passed,
    polished, final_gate_rejected, approved). The Stage 1i migration
    collapses the five saved states into three:
      - 'saved_clean'          — all gates green
      - 'saved_with_advisory'  — any gate fired advisory-level signal
      - 'quarantined'          — scene blocked pre-save (reserved)
    plus the pre-save 'draft'.
    """

    @pytest.mark.parametrize(
        "status",
        ["draft", "saved_clean", "saved_with_advisory", "quarantined"],
    )
    def test_accepts_new_enum_values_on_chapter_log(self, story_state, status):
        """Fresh databases accept every post-relay-v3 revision_status value."""
        story_state.add_chapter_log(
            chapter_number=hash(status) % 1000,  # unique PK per status
            word_count=100,
            revision_status=status,
        )

    @pytest.mark.parametrize(
        "status",
        ["draft", "saved_clean", "saved_with_advisory", "quarantined"],
    )
    def test_accepts_new_enum_values_on_scene_log(self, story_state, status):
        """Fresh databases accept every post-relay-v3 revision_status value on scene_log."""
        story_state.add_scene_log(
            chapter_number=hash(status) % 1000,
            scene_number=1,
            word_count=100,
            revision_status=status,
        )

    @pytest.mark.parametrize(
        "status",
        ["craft_edited", "revised", "gate_passed", "polished",
         "final_gate_rejected", "approved", "gate_failed"],
    )
    def test_rejects_legacy_status_values(self, story_state, status):
        """Every pre-v3 status value is rejected by the new CHECK constraint.

        Production rows carrying these labels are remapped by the v5→v6
        migration (see TestV6Migration); after migration, no code path
        should attempt to insert them directly.
        """
        with pytest.raises(sqlite3.IntegrityError):
            story_state.add_chapter_log(
                chapter_number=hash(status) % 1000 + 10000,
                word_count=100,
                revision_status=status,
            )


class TestV5AndV6Migration:
    """Tests for the chained v4→v5→v6 migration.

    A v4 database carries the legacy {craft_edited, revised, approved}
    labels. Opening it through StoryState runs v5 (remapping craft_edited/
    revised -> polished), then v6 (collapsing the five saved states to
    saved_clean / saved_with_advisory / quarantined).
    """

    def _seed_v4_database(self, db_path: str) -> None:
        """Create a database that looks like v4: old CHECK constraint with
        legacy enum values, schema_migrations pinned at version 4, and one
        row per legacy label so the migration has something to remap."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
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
                    'draft', 'gate_failed', 'gate_passed', 'craft_edited', 'revised', 'approved'
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
                    'draft', 'gate_failed', 'gate_passed', 'craft_edited', 'revised', 'approved'
                )),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                revised_at TIMESTAMP,
                PRIMARY KEY (chapter_number, scene_number)
            );
            CREATE TABLE characters (
                id TEXT PRIMARY KEY,
                name TEXT
            );
        """)
        for v in (1, 2, 3, 4):
            conn.execute(
                "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                (v, f"seeded v{v}"),
            )
        conn.execute(
            "INSERT INTO chapter_log (chapter_number, word_count, revision_status) VALUES (?, ?, ?)",
            (1, 3500, "craft_edited"),
        )
        conn.execute(
            "INSERT INTO chapter_log (chapter_number, word_count, revision_status) VALUES (?, ?, ?)",
            (2, 3700, "revised"),
        )
        conn.execute(
            "INSERT INTO chapter_log (chapter_number, word_count, revision_status) VALUES (?, ?, ?)",
            (3, 3800, "approved"),
        )
        conn.execute(
            "INSERT INTO scene_log (chapter_number, scene_number, word_count, revision_status) VALUES (?, ?, ?, ?)",
            (1, 1, 1200, "craft_edited"),
        )
        conn.execute(
            "INSERT INTO scene_log (chapter_number, scene_number, word_count, revision_status) VALUES (?, ?, ?, ?)",
            (1, 2, 1100, "revised"),
        )
        conn.commit()
        conn.close()

    def test_migration_remaps_legacy_labels(self, temp_dir):
        """Opening a v4 database through StoryState runs v5 + v6 in sequence.

        v5 remaps craft_edited/revised -> polished; v6 then folds polished
        and approved into 'saved_clean', and any {gate_failed,
        final_gate_rejected, gate_skipped} into 'saved_with_advisory'.
        """
        db_path = str(Path(temp_dir) / "v4_legacy.db")
        self._seed_v4_database(db_path)

        state = StoryState(db_path=db_path)
        try:
            ch1 = state.conn.execute(
                "SELECT revision_status FROM chapter_log WHERE chapter_number=1"
            ).fetchone()
            ch2 = state.conn.execute(
                "SELECT revision_status FROM chapter_log WHERE chapter_number=2"
            ).fetchone()
            ch3 = state.conn.execute(
                "SELECT revision_status FROM chapter_log WHERE chapter_number=3"
            ).fetchone()
            sc11 = state.conn.execute(
                "SELECT revision_status FROM scene_log WHERE chapter_number=1 AND scene_number=1"
            ).fetchone()
            sc12 = state.conn.execute(
                "SELECT revision_status FROM scene_log WHERE chapter_number=1 AND scene_number=2"
            ).fetchone()
            version = state.conn.execute(
                "SELECT MAX(version) as v FROM schema_migrations"
            ).fetchone()["v"]
        finally:
            state.close()

        # All three legacy labels collapse to saved_clean under the chained
        # migration: craft_edited -> polished -> saved_clean, same for revised,
        # and approved -> saved_clean directly.
        assert ch1["revision_status"] == "saved_clean"
        assert ch2["revision_status"] == "saved_clean"
        assert ch3["revision_status"] == "saved_clean"
        assert sc11["revision_status"] == "saved_clean"
        assert sc12["revision_status"] == "saved_clean"
        assert version >= 6

    def test_migration_is_idempotent(self, temp_dir):
        """Running StoryState twice on the same database does not re-run
        the migration or lose data."""
        db_path = str(Path(temp_dir) / "v4_legacy_idempotent.db")
        self._seed_v4_database(db_path)

        state = StoryState(db_path=db_path)
        state.close()

        state2 = StoryState(db_path=db_path)
        try:
            ch1 = state2.conn.execute(
                "SELECT revision_status FROM chapter_log WHERE chapter_number=1"
            ).fetchone()
            count = state2.conn.execute(
                "SELECT COUNT(*) AS n FROM chapter_log"
            ).fetchone()["n"]
        finally:
            state2.close()

        assert ch1["revision_status"] == "saved_clean"
        assert count == 3  # no duplicates


class TestV6Migration:
    """Tests for the v5→v6 migration that collapses the six-value enum."""

    def _seed_v5_database(self, db_path: str) -> None:
        """Seed a v5 database with one row per legacy status the relay v3
        migration should remap."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
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
            (1, 1000, "draft"),
            (2, 2000, "gate_failed"),
            (3, 3000, "gate_passed"),
            (4, 4000, "polished"),
            (5, 5000, "final_gate_rejected"),
            (6, 6000, "approved"),
        ]
        for ch, wc, status in rows:
            conn.execute(
                "INSERT INTO chapter_log (chapter_number, word_count, revision_status) VALUES (?, ?, ?)",
                (ch, wc, status),
            )
        conn.execute(
            "INSERT INTO scene_log (chapter_number, scene_number, word_count, revision_status) VALUES (?, ?, ?, ?)",
            (1, 1, 1000, "gate_passed"),
        )
        conn.execute(
            "INSERT INTO scene_log (chapter_number, scene_number, word_count, revision_status) VALUES (?, ?, ?, ?)",
            (1, 2, 1100, "final_gate_rejected"),
        )
        conn.commit()
        conn.close()

    def test_migration_remaps_all_legacy_values(self, temp_dir):
        """Every legacy status maps to the correct new enum value."""
        db_path = str(Path(temp_dir) / "v5_for_v6.db")
        self._seed_v5_database(db_path)

        state = StoryState(db_path=db_path)
        try:
            def s(ch):
                return state.conn.execute(
                    "SELECT revision_status FROM chapter_log WHERE chapter_number=?",
                    (ch,),
                ).fetchone()["revision_status"]

            assert s(1) == "draft"
            assert s(2) == "saved_with_advisory"  # gate_failed
            assert s(3) == "saved_clean"           # gate_passed
            assert s(4) == "saved_clean"           # polished
            assert s(5) == "saved_with_advisory"   # final_gate_rejected
            assert s(6) == "saved_clean"           # approved

            sc11 = state.conn.execute(
                "SELECT revision_status FROM scene_log WHERE chapter_number=1 AND scene_number=1"
            ).fetchone()
            sc12 = state.conn.execute(
                "SELECT revision_status FROM scene_log WHERE chapter_number=1 AND scene_number=2"
            ).fetchone()
            assert sc11["revision_status"] == "saved_clean"
            assert sc12["revision_status"] == "saved_with_advisory"

            version = state.conn.execute(
                "SELECT MAX(version) as v FROM schema_migrations"
            ).fetchone()["v"]
            assert version >= 6
        finally:
            state.close()

    def test_post_migration_rejects_legacy_inserts(self, temp_dir):
        """After migration the new CHECK constraint rejects any legacy label."""
        db_path = str(Path(temp_dir) / "v5_reject.db")
        self._seed_v5_database(db_path)

        state = StoryState(db_path=db_path)
        try:
            with pytest.raises(sqlite3.IntegrityError):
                state.add_chapter_log(
                    chapter_number=999,
                    word_count=1,
                    revision_status="approved",
                )
        finally:
            state.close()
