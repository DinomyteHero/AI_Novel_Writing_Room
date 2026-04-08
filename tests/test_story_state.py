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
        """init_from_concept_seed creates all 4 characters with slugified IDs."""
        story_state.init_from_concept_seed(sample_concept_seed)
        all_chars = story_state.get_all_characters()
        assert len(all_chars) == 4

        # The concept seed uses em-dash (\u2014) in TBD names.
        # _slugify replaces spaces and hyphens but not em-dashes.
        em = "\u2014"
        expected_ids = {
            "ben_skywalker",
            f"tbd_{em}_jedi_scholar",
            f"tbd_{em}_mandalorian",
            f"tbd_{em}_non_force_sensitive_specialist",
        }
        actual_ids = {c["id"] for c in all_chars}
        assert actual_ids == expected_ids

    def test_init_from_concept_seed_sets_role_as_arc_position(
        self, story_state, sample_concept_seed
    ):
        """Each character's role from the seed is stored as arc_position."""
        story_state.init_from_concept_seed(sample_concept_seed)
        ben = story_state.get_character("ben_skywalker")
        assert ben is not None
        assert ben["arc_position"] == "Mission lead, primary POV"


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
            revision_status="gate_passed",
            word_count=3600,
        )
        log = story_state.get_chapter_log(1)
        assert log["revision_status"] == "gate_passed"
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
