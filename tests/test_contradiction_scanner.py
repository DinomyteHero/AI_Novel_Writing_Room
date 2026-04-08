"""Tests for the ContradictionScanner.

Validates all five sub-scans (truth, belief, promises, timeline,
relationships) plus the combined scan() method and log_flags emission.
"""

from pathlib import Path

import pytest

from src.memory.contradiction_scanner import ContradictionScanner
from src.memory.knowledge_layers import KnowledgeLayers
from src.memory.story_state import StoryState
from src.run_ledger import RunLedger


@pytest.fixture
def _scanner_deps(tmp_path):
    """Set up StoryState, KnowledgeLayers, RunLedger, and scanner in a temp dir."""
    state = StoryState(db_path=str(tmp_path / "test_state.db"))
    knowledge = KnowledgeLayers(state)
    ledger = RunLedger(db_path=str(tmp_path / "test_ledger.db"))
    scanner = ContradictionScanner(state, knowledge, ledger)
    yield state, knowledge, ledger, scanner
    state.close()
    ledger.close()


# ------------------------------------------------------------------ #
# Helper to populate a basic character set
# ------------------------------------------------------------------ #


def _seed_characters(state: StoryState):
    """Add two characters at distinct locations."""
    state.add_character(
        id="ben_skywalker",
        name="Ben Skywalker",
        current_location="Jedi Temple",
        emotional_state="cautious",
    )
    state.add_character(
        id="jedi_scholar",
        name="Jedi Scholar",
        current_location="Library Archives",
        emotional_state="eager",
    )


# ================================================================== #
# _scan_truth_layer
# ================================================================== #


class TestScanTruthLayer:
    """Test truth-layer contradiction detection."""

    def test_detects_wrong_location(self, _scanner_deps):
        """Prose mentions a character near a wrong location."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        # Prose places Ben near "Library Archives" (the scholar's location)
        # but Ben's recorded location is "Jedi Temple".
        prose = (
            "Ben Skywalker strode through the library archives, "
            "scanning the ancient shelves for the holocron."
        )
        flags = scanner._scan_truth_layer(chapter_number=2, prose=prose)

        assert len(flags) >= 1
        assert flags[0]["type"] == "truth_contradiction"
        assert "ben skywalker" in flags[0]["description"].lower() or "Ben Skywalker" in flags[0]["description"]

    def test_no_flag_when_location_correct(self, _scanner_deps):
        """Prose mentions a character at their correct location."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        prose = (
            "Ben Skywalker stood in the Jedi Temple, "
            "watching the holographic star chart."
        )
        flags = scanner._scan_truth_layer(chapter_number=2, prose=prose)
        assert flags == []

    def test_no_flag_when_character_absent_from_prose(self, _scanner_deps):
        """Characters not mentioned in prose should not trigger flags."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        prose = "The wind howled across the empty plains."
        flags = scanner._scan_truth_layer(chapter_number=2, prose=prose)
        assert flags == []


# ================================================================== #
# _scan_belief_layer
# ================================================================== #


class TestScanBeliefLayer:
    """Test belief-layer inconsistency detection."""

    def test_flags_inaccurate_belief(self, _scanner_deps):
        """Characters with known false beliefs should be flagged."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        # Give Ben an inaccurate belief from chapter 1
        knowledge.add_belief(
            character_id="ben_skywalker",
            fact_id="scholar_loyalty",
            description="The Jedi Scholar is fully loyal to the Order",
            is_accurate=False,
            chapter=1,
            source="inferred",
        )

        scene_card = {
            "chapter_number": 3,
            "characters_present": ["Ben Skywalker"],
        }

        flags = scanner._scan_belief_layer(chapter_number=3, scene_card=scene_card)

        assert len(flags) == 1
        assert flags[0]["type"] == "belief_inconsistency"
        assert "inaccurate belief" in flags[0]["description"].lower()

    def test_no_flag_for_accurate_belief(self, _scanner_deps):
        """Accurate beliefs should not trigger flags."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        knowledge.add_belief(
            character_id="ben_skywalker",
            fact_id="temple_location",
            description="The Jedi Temple is on Coruscant",
            is_accurate=True,
            chapter=1,
            source="witnessed",
        )

        scene_card = {
            "chapter_number": 3,
            "characters_present": ["Ben Skywalker"],
        }

        flags = scanner._scan_belief_layer(chapter_number=3, scene_card=scene_card)
        assert flags == []

    def test_no_flag_for_absent_character(self, _scanner_deps):
        """Characters not in the scene should not be checked."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        knowledge.add_belief(
            character_id="ben_skywalker",
            fact_id="false_fact",
            description="Something wrong",
            is_accurate=False,
            chapter=1,
            source="told",
        )

        scene_card = {
            "chapter_number": 3,
            "characters_present": ["Jedi Scholar"],  # Ben not present
        }

        flags = scanner._scan_belief_layer(chapter_number=3, scene_card=scene_card)
        assert flags == []


# ================================================================== #
# _scan_promises
# ================================================================== #


class TestScanPromises:
    """Test Chekhov gun overdue detection."""

    def test_flags_long_unfired_gun(self, _scanner_deps):
        """A gun planted 10+ chapters ago should be flagged."""
        state, knowledge, ledger, scanner = _scanner_deps

        state.add_chekhov_gun(
            id="mysterious_artifact",
            item_description="The obsidian crystal hidden in the cargo bay",
            planted_chapter=1,
            planted_context="Scene where cargo is loaded",
        )

        flags = scanner._scan_promises(chapter_number=12)

        assert len(flags) == 1
        assert flags[0]["type"] == "promise_overdue"
        assert "obsidian crystal" in flags[0]["description"].lower()
        assert "11 chapters" in flags[0]["description"]

    def test_no_flag_for_recently_planted_gun(self, _scanner_deps):
        """A gun planted recently should not be flagged."""
        state, knowledge, ledger, scanner = _scanner_deps

        state.add_chekhov_gun(
            id="blaster_pistol",
            item_description="Concealed blaster under the pilot's seat",
            planted_chapter=5,
        )

        flags = scanner._scan_promises(chapter_number=8)
        assert flags == []

    def test_no_flag_for_fired_gun(self, _scanner_deps):
        """A fired gun should not be flagged."""
        state, knowledge, ledger, scanner = _scanner_deps

        state.add_chekhov_gun(
            id="comms_device",
            item_description="Encrypted comms device",
            planted_chapter=1,
        )
        state.fire_chekhov_gun("comms_device", fired_chapter=5)

        flags = scanner._scan_promises(chapter_number=15)
        assert flags == []


# ================================================================== #
# _scan_timeline
# ================================================================== #


class TestScanTimeline:
    """Test timeline ordering detection."""

    def test_flags_temporal_regression(self, _scanner_deps):
        """Events with dates going backward should be flagged."""
        state, knowledge, ledger, scanner = _scanner_deps

        state.add_timeline_entry(
            chapter_number=3, scene_number=1,
            story_date="45 ABY Day 5",
        )
        state.add_timeline_entry(
            chapter_number=3, scene_number=2,
            story_date="45 ABY Day 3",  # goes backward
        )

        flags = scanner._scan_timeline(chapter_number=3)

        assert len(flags) == 1
        assert flags[0]["type"] == "timeline_inconsistency"
        assert "regression" in flags[0]["description"].lower()

    def test_no_flag_for_correct_order(self, _scanner_deps):
        """Correctly ordered dates should not flag."""
        state, knowledge, ledger, scanner = _scanner_deps

        state.add_timeline_entry(
            chapter_number=3, scene_number=1,
            story_date="45 ABY Day 3",
        )
        state.add_timeline_entry(
            chapter_number=3, scene_number=2,
            story_date="45 ABY Day 5",
        )

        flags = scanner._scan_timeline(chapter_number=3)
        assert flags == []

    def test_no_flag_for_single_entry(self, _scanner_deps):
        """A single timeline entry cannot regress."""
        state, knowledge, ledger, scanner = _scanner_deps

        state.add_timeline_entry(
            chapter_number=3, scene_number=1,
            story_date="45 ABY Day 5",
        )

        flags = scanner._scan_timeline(chapter_number=3)
        assert flags == []


# ================================================================== #
# _scan_relationships
# ================================================================== #


class TestScanRelationships:
    """Test stale relationship detection."""

    def test_flags_stale_relationship(self, _scanner_deps):
        """Relationship last updated 5+ chapters ago with both chars present."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        state.add_relationship(
            character_a="ben_skywalker",
            character_b="jedi_scholar",
            relationship_type="professional",
            status="cautious allies",
            last_updated_chapter=1,
        )

        scene_card = {
            "chapter_number": 8,
            "characters_present": ["Ben Skywalker", "Jedi Scholar"],
        }

        flags = scanner._scan_relationships(chapter_number=8, scene_card=scene_card)

        assert len(flags) == 1
        assert flags[0]["type"] == "relationship_stale"
        assert "ben skywalker" in flags[0]["description"].lower()

    def test_no_flag_for_recently_updated_relationship(self, _scanner_deps):
        """A recently updated relationship should not flag."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        state.add_relationship(
            character_a="ben_skywalker",
            character_b="jedi_scholar",
            relationship_type="professional",
            status="cautious allies",
            last_updated_chapter=6,
        )

        scene_card = {
            "chapter_number": 8,
            "characters_present": ["Ben Skywalker", "Jedi Scholar"],
        }

        flags = scanner._scan_relationships(chapter_number=8, scene_card=scene_card)
        assert flags == []

    def test_no_flag_for_single_character_scene(self, _scanner_deps):
        """Fewer than 2 characters present should skip relationship checks."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        scene_card = {
            "chapter_number": 8,
            "characters_present": ["Ben Skywalker"],
        }

        flags = scanner._scan_relationships(chapter_number=8, scene_card=scene_card)
        assert flags == []


# ================================================================== #
# scan() combined
# ================================================================== #


class TestScanCombined:
    """Test the combined scan() method."""

    def test_scan_runs_all_subscans_and_returns_combined_flags(self, _scanner_deps):
        """scan() should aggregate flags from all sub-scans."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        # Set up a belief inconsistency
        knowledge.add_belief(
            character_id="ben_skywalker",
            fact_id="false_belief_1",
            description="The ship is safe",
            is_accurate=False,
            chapter=1,
            source="told",
        )

        # Set up an overdue Chekhov gun
        state.add_chekhov_gun(
            id="old_gun",
            item_description="A mysterious datapad",
            planted_chapter=1,
        )

        scene_card = {
            "chapter_number": 15,
            "characters_present": ["Ben Skywalker", "Jedi Scholar"],
        }
        prose = "Ben Skywalker sat in the Jedi Temple, reviewing mission files."

        flags = scanner.scan(chapter_number=15, prose=prose, scene_card=scene_card)

        flag_types = {f["type"] for f in flags}
        # At minimum, we should see the belief and promise flags
        assert "belief_inconsistency" in flag_types
        assert "promise_overdue" in flag_types

    def test_clean_scan_returns_empty_list(self, _scanner_deps):
        """A scan with no issues should return an empty list."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        scene_card = {
            "chapter_number": 2,
            "characters_present": ["Ben Skywalker"],
        }
        prose = "Ben Skywalker stood in the Jedi Temple, deep in thought."

        flags = scanner.scan(chapter_number=2, prose=prose, scene_card=scene_card)
        assert flags == []


# ================================================================== #
# log_flags
# ================================================================== #


class TestLogFlags:
    """Test that log_flags emits events to the run ledger."""

    def test_log_flags_emits_to_ledger(self, _scanner_deps):
        """log_flags should create a contradiction_scan event in the ledger."""
        state, knowledge, ledger, scanner = _scanner_deps

        test_flags = [
            {
                "type": "truth_contradiction",
                "severity": "warning",
                "description": "Test flag",
                "location": "chapter 3",
            },
            {
                "type": "promise_overdue",
                "severity": "warning",
                "description": "Another flag",
                "location": "planted chapter 1",
            },
        ]

        scanner.log_flags(test_flags, chapter_number=3)

        events = ledger.get_events(event_type="contradiction_scan")
        assert len(events) == 1

        payload = events[0]["payload"]
        assert payload["flag_count"] == 2
        assert payload["warning_count"] == 2
        assert payload["blocking_count"] == 0
        assert len(payload["flags"]) == 2

    def test_scan_with_flags_auto_logs(self, _scanner_deps):
        """scan() should automatically call log_flags when flags exist."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        state.add_chekhov_gun(
            id="overdue_item",
            item_description="Overdue item",
            planted_chapter=1,
        )

        scene_card = {
            "chapter_number": 15,
            "characters_present": ["Ben Skywalker"],
        }
        prose = "Ben Skywalker waited in the Jedi Temple."

        scanner.scan(chapter_number=15, prose=prose, scene_card=scene_card)

        events = ledger.get_events(event_type="contradiction_scan")
        assert len(events) == 1

    def test_clean_scan_does_not_log(self, _scanner_deps):
        """scan() should not log when there are no flags."""
        state, knowledge, ledger, scanner = _scanner_deps
        _seed_characters(state)

        scene_card = {
            "chapter_number": 2,
            "characters_present": ["Ben Skywalker"],
        }
        prose = "Ben Skywalker stood in the Jedi Temple."

        scanner.scan(chapter_number=2, prose=prose, scene_card=scene_card)

        events = ledger.get_events(event_type="contradiction_scan")
        assert len(events) == 0
