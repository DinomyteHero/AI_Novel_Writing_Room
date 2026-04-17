"""Phase 6.1 — book-to-book carryover.

Covers two new methods:

1. ``SeriesManager.apply_transition_to_seed(seed, snapshot)`` — mutates a
   Book N+1 concept seed with inherited hooks + extended_metadata audit.
2. ``StoryState.initialize_from_transition(snapshot)`` — seeds the
   Book N+1 runtime DB from the snapshot (characters, arcs, threads,
   hooks, Chekhov guns).

These two are the load-bearing pieces ``scripts/spawn_next_book.py``
(Phase 6.2) composes to go from a Book N transition snapshot to a
runnable Book N+1 project.
"""

from __future__ import annotations

import pytest

from src.concept_workshop.series_manager import SeriesManager
from src.memory.story_state import StoryState


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def snapshot() -> dict:
    """A realistic snapshot matching generate_transition_snapshot's shape."""
    return {
        "book_number": 1,
        "generated_at": "2026-04-16T10:00:00Z",
        "character_end_states": [
            {
                "id": "char_protagonist",
                "name": "Lira",
                "location": "Ruusan Memorial",
                "emotional_state": "resolute",
                "arc_position": "new_truth_demonstrated",
            },
            {
                "id": "char_antagonist",
                "name": "Drev",
                "location": "Korriban Shrine",
                "emotional_state": "vengeful",
                "arc_position": "lie_deepened",
            },
        ],
        "character_arc_states": [
            {
                "character_id": "char_protagonist",
                "current_phase": "new_truth_demonstrated",
                "arc_type": "positive_change",
                "lie_believed": "Self-reliance is safety.",
                "need": "Collective trust.",
            }
        ],
        "unresolved_threads": [
            {
                "id": "thread_lost_holocron",
                "description": "The Ruusan holocron remains missing.",
                "status": "planted",
                "urgency": "high",
            }
        ],
        "unresolved_hooks": [
            {
                "hook_id": "hook_ghost_of_kaan",
                "description": "The Sith Lord Kaan's lingering influence.",
                "priority": "hard",
                "current_status": "planted",
            },
            {
                "hook_id": "hook_ruusan_echo",
                "description": "Mysterious Force-echoes near the memorial.",
                "priority": "soft",
                "current_status": "advanced",
            },
        ],
        "unfired_chekhov_guns": [
            {
                "id": "gun_kyber_shard",
                "description": "A fractured kyber shard Lira pocketed.",
                "planted_chapter": 18,
            }
        ],
    }


@pytest.fixture
def blank_seed() -> dict:
    return {
        "meta": {
            "project_title": "Book 2",
            "franchise": "Star Wars Legends",
            "canon_status": "AU",
            "era": "post-Ruusan",
            "tone": "heroic_with_weight",
            "target_word_count": 80000,
        },
        "ensemble_cast": [],
    }


# ---------------------------------------------------------------------------
# SeriesManager.apply_transition_to_seed
# ---------------------------------------------------------------------------


class TestApplyTransitionToSeed:
    def test_hooks_are_prepended_with_inheritance_metadata(
        self, snapshot: dict, blank_seed: dict
    ):
        SeriesManager.apply_transition_to_seed(blank_seed, snapshot)
        hooks = blank_seed["hooks"]
        assert len(hooks) == 2
        ids = {h["hook_id"] for h in hooks}
        assert ids == {"hook_ghost_of_kaan", "hook_ruusan_echo"}
        for h in hooks:
            assert h["inherited_from_book"] == 1
            assert h["planted_in"] == "book_1"
            assert h["hook_type"] in ("hard", "series")

    def test_hard_priority_maps_to_hard_hook_type(
        self, snapshot: dict, blank_seed: dict
    ):
        SeriesManager.apply_transition_to_seed(blank_seed, snapshot)
        by_id = {h["hook_id"]: h for h in blank_seed["hooks"]}
        assert by_id["hook_ghost_of_kaan"]["hook_type"] == "hard"
        assert by_id["hook_ruusan_echo"]["hook_type"] == "series"

    def test_existing_hook_id_is_not_duplicated(
        self, snapshot: dict, blank_seed: dict
    ):
        # Caller has already authored hook_ruusan_echo with their own copy.
        blank_seed["hooks"] = [
            {
                "hook_id": "hook_ruusan_echo",
                "hook_type": "soft",
                "planted_in": 2,
                "description": "Caller's description",
            }
        ]
        SeriesManager.apply_transition_to_seed(blank_seed, snapshot)
        by_id = {h["hook_id"]: h for h in blank_seed["hooks"]}
        assert by_id["hook_ruusan_echo"]["description"] == "Caller's description"
        # The other unresolved hook IS added; the duplicate is NOT.
        assert "hook_ghost_of_kaan" in by_id
        assert len(blank_seed["hooks"]) == 2

    def test_book_number_and_project_scope_defaulted(
        self, snapshot: dict, blank_seed: dict
    ):
        SeriesManager.apply_transition_to_seed(blank_seed, snapshot)
        assert blank_seed["meta"]["book_number"] == 2
        assert blank_seed["meta"]["project_scope"] == "continuation"

    def test_caller_supplied_book_number_is_preserved(
        self, snapshot: dict, blank_seed: dict
    ):
        blank_seed["meta"]["book_number"] = 7
        blank_seed["meta"]["project_scope"] = "planned_series"
        SeriesManager.apply_transition_to_seed(blank_seed, snapshot)
        assert blank_seed["meta"]["book_number"] == 7
        assert blank_seed["meta"]["project_scope"] == "planned_series"

    def test_extended_metadata_audit_trail(
        self, snapshot: dict, blank_seed: dict
    ):
        SeriesManager.apply_transition_to_seed(blank_seed, snapshot)
        record = blank_seed["extended_metadata"]["book_transition"]
        assert record["inherited_from_book"] == 1
        assert set(record["carried_character_ids"]) == {
            "char_protagonist", "char_antagonist"
        }
        assert record["inherited_plot_threads"][0]["id"] == "thread_lost_holocron"
        assert record["inherited_chekhov_guns"][0]["id"] == "gun_kyber_shard"
        assert "hook_ghost_of_kaan" in record["inherited_hook_ids"]
        assert "imported_at" in record

    def test_raises_on_missing_book_number(self, blank_seed: dict):
        with pytest.raises(ValueError, match="book_number"):
            SeriesManager.apply_transition_to_seed(
                blank_seed, {"character_end_states": []}
            )

    def test_empty_snapshot_sections_noop_cleanly(self, blank_seed: dict):
        snapshot = {"book_number": 1, "character_end_states": []}
        SeriesManager.apply_transition_to_seed(blank_seed, snapshot)
        # Audit trail still written (so downstream can see 'nothing inherited').
        assert blank_seed["extended_metadata"]["book_transition"][
            "inherited_from_book"
        ] == 1
        # No hooks added.
        assert "hooks" not in blank_seed or blank_seed["hooks"] == []


# ---------------------------------------------------------------------------
# StoryState.initialize_from_transition
# ---------------------------------------------------------------------------


class TestStoryStateInitializeFromTransition:
    @pytest.fixture
    def state(self, tmp_path) -> StoryState:
        s = StoryState(db_path=str(tmp_path / "state.db"))
        yield s
        s.close()

    def test_counts_report_what_was_seeded(self, state: StoryState, snapshot: dict):
        counts = state.initialize_from_transition(snapshot)
        assert counts["characters"] == 2
        assert counts["arcs"] == 1
        assert counts["threads"] == 1
        assert counts["hooks"] == 2
        assert counts["guns"] == 1

    def test_characters_seeded_with_end_state(
        self, state: StoryState, snapshot: dict
    ):
        state.initialize_from_transition(snapshot)
        lira = state.get_character("char_protagonist")
        assert lira is not None
        assert lira["name"] == "Lira"
        assert lira["current_location"] == "Ruusan Memorial"
        assert lira["emotional_state"] == "resolute"
        assert lira["arc_position"] == "new_truth_demonstrated"

    def test_character_arcs_scoped_to_target_book(
        self, state: StoryState, snapshot: dict
    ):
        # Default target_book = snapshot.book_number + 1 = 2. The snapshot
        # fixture uses the concept-seed planning label "new_truth_demonstrated"
        # which initialize_from_transition maps to the DB-native phase
        # "truth_accepted" via CONCEPT_SEED_PHASE_MAP.
        state.initialize_from_transition(snapshot)
        arc = state.get_character_arc("char_protagonist", book_number=2)
        assert arc is not None
        assert arc["current_phase"] == "truth_accepted"
        assert arc["arc_type"] == "positive_change"
        assert arc["lie_believed"] == "Self-reliance is safety."

    def test_explicit_target_book_number_is_honoured(
        self, state: StoryState, snapshot: dict
    ):
        state.initialize_from_transition(snapshot, target_book_number=5)
        arc = state.get_character_arc("char_protagonist", book_number=5)
        assert arc is not None

    def test_threads_marked_active(self, state: StoryState, snapshot: dict):
        state.initialize_from_transition(snapshot)
        threads = state.get_active_threads()
        ids = {t["id"] for t in threads}
        assert "thread_lost_holocron" in ids

    def test_hooks_recorded_with_source_book(
        self, state: StoryState, snapshot: dict
    ):
        """hooks.hook_type (DB-level) defaults to 'setup_callback' for
        inherited entries — a narrative classification distinct from the
        concept-seed hook_type ('hard'/'soft'/'series') which maps to the
        DB's priority column. The DB priority column preserves the
        snapshot's 'priority' value verbatim."""
        state.initialize_from_transition(snapshot)
        hard = state.get_hook("hook_ghost_of_kaan")
        assert hard is not None
        assert hard["hook_type"] == "setup_callback"  # DB narrative class
        assert hard["priority"] == "hard"              # from snapshot
        assert hard["planted_book"] == 1
        soft = state.get_hook("hook_ruusan_echo")
        assert soft is not None
        assert soft["hook_type"] == "setup_callback"
        assert soft["priority"] == "soft"

    def test_chekhov_guns_carried_unfired(
        self, state: StoryState, snapshot: dict
    ):
        state.initialize_from_transition(snapshot)
        unfired = state.get_unfired_guns()
        ids = {g["id"] for g in unfired}
        assert "gun_kyber_shard" in ids

    def test_idempotent_second_apply_does_not_corrupt(
        self, state: StoryState, snapshot: dict
    ):
        state.initialize_from_transition(snapshot)
        counts_first = state.initialize_from_transition(snapshot)
        # Second run still reports the same counts (the writes are
        # OR IGNORE, not OR REPLACE; nothing is clobbered).
        assert counts_first["characters"] == 2
        # And we still only have 2 characters total (not 4).
        assert len(state.get_all_characters()) == 2

    def test_malformed_entries_skip_without_crash(self, state: StoryState):
        """Defensive: entries missing required fields are skipped, not
        fatal."""
        bad_snapshot = {
            "book_number": 1,
            "character_end_states": [{"name": "no_id_here"}, {"id": "ok", "name": "OK"}],
            "unresolved_hooks": [{"description": "no id"}, {"hook_id": "h1", "description": "ok"}],
            "unresolved_threads": [{"description": "no id"}, {"id": "t1", "description": "ok"}],
            "unfired_chekhov_guns": [{"description": "no id"}, {"id": "g1"}],
        }
        counts = state.initialize_from_transition(bad_snapshot)
        assert counts == {
            "characters": 1, "arcs": 0, "threads": 1, "hooks": 1, "guns": 1,
        }
