"""Phase 6.2 — scripts/spawn_next_book.py end-to-end.

Builds a minimal Book-1 project under tmp_path (concept_seed.json +
book_1_transition.json next to it), runs ``spawn_next_book``, and asserts:

  1. The target concept seed is written to the right path with
     meta.book_number bumped to 2, project_scope = continuation.
  2. Inherited hooks from the snapshot are prepended to the target seed.
  3. The target StoryState DB is seeded with characters, arcs, threads,
     hooks, and unfired guns.
  4. Dry-run produces a populated SpawnResult but writes nothing.
  5. Missing snapshot raises a clear error.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.spawn_next_book import spawn_next_book, main
from src.memory.story_state import StoryState


FRANCHISE = "test-franchise"
SOURCE_BOOK = "book-one"
TARGET_BOOK = "book-two"


@pytest.fixture
def source_seed() -> dict:
    return {
        "meta": {
            "project_title": "Book One",
            "franchise": "Test Franchise",
            "canon_status": "AU",
            "era": "Contemporary, 2026",
            "tone": "character_study",
            "target_word_count": 80000,
            "target_chapters": 20,
            "book_number": 1,
            "project_scope": "planned_series",
        },
        "premise": {
            "what_if": "What if the protagonist never learned to trust?" * 2,
            "central_dramatic_question": "Can trust be rebuilt?",
            "logline": "A novel of slow recovery.",
        },
        "conflict": {
            "primary_antagonistic_force": {
                "type": "internal",
                "motivation": "x" * 60,
                "escalation": "y" * 110,
            },
            "secondary_pressures": ["time pressure"],
            "lock_in_mechanism": "z" * 40,
        },
        "theme": {
            "thematic_premise": "Trust as the core need.",
            "thematic_argument": "a" * 120,
            "how_each_arc_tests_theme": {"char_a": "faces the lie"},
        },
        "ensemble_cast": [
            {
                "name": "Alice",
                "role": "protagonist",
                "three_dimensions": {
                    "surface": "s" * 55,
                    "backstory_inner_demons": "b" * 55,
                    "action_under_pressure": "p" * 55,
                },
            },
            {
                "name": "Bob",
                "role": "antagonist",
                "three_dimensions": {
                    "surface": "s" * 55,
                    "backstory_inner_demons": "b" * 55,
                    "action_under_pressure": "p" * 55,
                },
            },
        ],
        "canon_constraints": {
            "continuity": "primary",
            "canon_preserved": [],
            "style_constraints": [],
        },
        "hooks": [
            {
                "hook_id": "seed_only_hook",
                "hook_type": "soft",
                "planted_in": 3,
                "resolved_in": 17,
                "description": "A structural hook internal to Book 1.",
            }
        ],
        "revelation_schedule": [
            {"revelation_id": "r1", "what": "Book 1 reveal"}
        ],
        "subplots": [{"subplot_id": "sub1", "name": "Side quest"}],
    }


@pytest.fixture
def snapshot() -> dict:
    return {
        "book_number": 1,
        "generated_at": "2026-04-16T10:00:00Z",
        "character_end_states": [
            {
                "id": "alice",
                "name": "Alice",
                "location": "Home",
                "emotional_state": "hopeful",
                "arc_position": "truth_accepted",
            },
            {
                "id": "bob",
                "name": "Bob",
                "location": "Exile",
                "emotional_state": "bitter",
                "arc_position": "lie_deepened",
            },
        ],
        "character_arc_states": [
            {
                "character_id": "alice",
                "current_phase": "truth_accepted",
                "arc_type": "positive_change",
                "lie_believed": "Trust is weakness.",
                "need": "Connection.",
            }
        ],
        "unresolved_threads": [
            {
                "id": "thread_bob_vendetta",
                "description": "Bob's vendetta continues.",
                "status": "active",
                "urgency": "rising",
            }
        ],
        "unresolved_hooks": [
            {
                "hook_id": "hook_bob_return",
                "description": "Bob will return.",
                "priority": "hard",
                "current_status": "planted",
            }
        ],
        "unfired_chekhov_guns": [
            {
                "id": "gun_letter",
                "description": "Unread letter in the attic.",
                "planted_chapter": 12,
            }
        ],
    }


def _install_source_project(tmp_path: Path, seed: dict, snap: dict) -> Path:
    """Put source concept_seed and transition snapshot in the right tree."""
    book_dir = (
        tmp_path / "data" / "franchises" / FRANCHISE / "books" / SOURCE_BOOK
    )
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "concept_seed.json").write_text(
        json.dumps(seed, indent=2), encoding="utf-8"
    )
    (book_dir / "book_1_transition.json").write_text(
        json.dumps(snap, indent=2), encoding="utf-8"
    )
    return book_dir


def _load_target_seed(tmp_path: Path) -> dict:
    path = (
        tmp_path / "data" / "franchises" / FRANCHISE / "books" / TARGET_BOOK
        / "concept_seed.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


class TestSpawnNextBookHappyPath:
    def test_target_seed_written_at_expected_path(
        self, tmp_path, source_seed, snapshot
    ):
        _install_source_project(tmp_path, source_seed, snapshot)
        result = spawn_next_book(
            from_book=SOURCE_BOOK,
            to_book=TARGET_BOOK,
            franchise=FRANCHISE,
            base_dir=str(tmp_path),
        )
        expected = (
            tmp_path / "data" / "franchises" / FRANCHISE / "books"
            / TARGET_BOOK / "concept_seed.json"
        )
        assert result.target_seed_path == expected
        assert expected.exists()

    def test_meta_book_number_and_scope_bumped(
        self, tmp_path, source_seed, snapshot
    ):
        _install_source_project(tmp_path, source_seed, snapshot)
        spawn_next_book(
            from_book=SOURCE_BOOK, to_book=TARGET_BOOK,
            franchise=FRANCHISE, base_dir=str(tmp_path),
        )
        target = _load_target_seed(tmp_path)
        assert target["meta"]["book_number"] == 2
        assert target["meta"]["project_scope"] == "continuation"

    def test_inherited_hook_prepended(self, tmp_path, source_seed, snapshot):
        _install_source_project(tmp_path, source_seed, snapshot)
        spawn_next_book(
            from_book=SOURCE_BOOK, to_book=TARGET_BOOK,
            franchise=FRANCHISE, base_dir=str(tmp_path),
        )
        target = _load_target_seed(tmp_path)
        hook_ids = [h["hook_id"] for h in target.get("hooks", [])]
        assert "hook_bob_return" in hook_ids
        bob = next(h for h in target["hooks"] if h["hook_id"] == "hook_bob_return")
        assert bob["inherited_from_book"] == 1

    def test_source_structural_hooks_dropped(
        self, tmp_path, source_seed, snapshot
    ):
        """Book 1's purely-structural hooks (not carried via snapshot) do
        not leak into Book 2's seed — Book 2's outline is a fresh plan."""
        _install_source_project(tmp_path, source_seed, snapshot)
        spawn_next_book(
            from_book=SOURCE_BOOK, to_book=TARGET_BOOK,
            franchise=FRANCHISE, base_dir=str(tmp_path),
        )
        target = _load_target_seed(tmp_path)
        hook_ids = [h["hook_id"] for h in target.get("hooks", [])]
        assert "seed_only_hook" not in hook_ids

    def test_book_transition_audit_block(
        self, tmp_path, source_seed, snapshot
    ):
        _install_source_project(tmp_path, source_seed, snapshot)
        spawn_next_book(
            from_book=SOURCE_BOOK, to_book=TARGET_BOOK,
            franchise=FRANCHISE, base_dir=str(tmp_path),
        )
        target = _load_target_seed(tmp_path)
        record = target["extended_metadata"]["book_transition"]
        assert record["inherited_from_book"] == 1
        assert set(record["carried_character_ids"]) == {"alice", "bob"}

    def test_story_state_seeded_from_snapshot(
        self, tmp_path, source_seed, snapshot
    ):
        _install_source_project(tmp_path, source_seed, snapshot)
        result = spawn_next_book(
            from_book=SOURCE_BOOK, to_book=TARGET_BOOK,
            franchise=FRANCHISE, base_dir=str(tmp_path),
        )
        assert result.initialization_counts == {
            "characters": 2, "arcs": 1, "threads": 1, "hooks": 1, "guns": 1,
        }
        state = StoryState(db_path=str(result.target_story_state_path))
        try:
            alice = state.get_character("alice")
            assert alice is not None
            assert alice["current_location"] == "Home"
            arc = state.get_character_arc("alice", book_number=2)
            assert arc is not None
            assert arc["arc_type"] == "positive_change"
            threads = state.get_active_threads()
            assert any(t["id"] == "thread_bob_vendetta" for t in threads)
            hook = state.get_hook("hook_bob_return")
            assert hook is not None
            assert hook["planted_book"] == 1
            unfired = state.get_unfired_guns()
            assert any(g["id"] == "gun_letter" for g in unfired)
        finally:
            state.close()

    def test_target_title_defaulted(
        self, tmp_path, source_seed, snapshot
    ):
        _install_source_project(tmp_path, source_seed, snapshot)
        spawn_next_book(
            from_book=SOURCE_BOOK, to_book=TARGET_BOOK,
            franchise=FRANCHISE, base_dir=str(tmp_path),
        )
        target = _load_target_seed(tmp_path)
        assert "Book 2" in target["meta"]["project_title"]

    def test_explicit_title_overrides(
        self, tmp_path, source_seed, snapshot
    ):
        _install_source_project(tmp_path, source_seed, snapshot)
        spawn_next_book(
            from_book=SOURCE_BOOK, to_book=TARGET_BOOK,
            franchise=FRANCHISE, base_dir=str(tmp_path),
            title="Ruusan Reformation Vol II",
        )
        target = _load_target_seed(tmp_path)
        assert target["meta"]["project_title"] == "Ruusan Reformation Vol II"


class TestSpawnNextBookDryRun:
    def test_dry_run_writes_nothing(self, tmp_path, source_seed, snapshot):
        _install_source_project(tmp_path, source_seed, snapshot)
        result = spawn_next_book(
            from_book=SOURCE_BOOK, to_book=TARGET_BOOK,
            franchise=FRANCHISE, base_dir=str(tmp_path),
            dry_run=True,
        )
        assert result.dry_run is True
        assert result.target_seed_path is not None
        assert not result.target_seed_path.exists()
        # Story state DB not created either.
        assert result.target_story_state_path is not None
        assert not result.target_story_state_path.exists()

    def test_dry_run_still_reports_inherited_hooks(
        self, tmp_path, source_seed, snapshot
    ):
        _install_source_project(tmp_path, source_seed, snapshot)
        result = spawn_next_book(
            from_book=SOURCE_BOOK, to_book=TARGET_BOOK,
            franchise=FRANCHISE, base_dir=str(tmp_path),
            dry_run=True,
        )
        assert result.inherited_hook_ids == ["hook_bob_return"]
        assert set(result.carried_character_ids) == {"alice", "bob"}


class TestSpawnNextBookErrorPaths:
    def test_missing_source_seed_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="source concept seed"):
            spawn_next_book(
                from_book=SOURCE_BOOK, to_book=TARGET_BOOK,
                franchise=FRANCHISE, base_dir=str(tmp_path),
            )

    def test_missing_snapshot_raises(self, tmp_path, source_seed):
        # Install the seed but not the snapshot.
        book_dir = (
            tmp_path / "data" / "franchises" / FRANCHISE / "books" / SOURCE_BOOK
        )
        book_dir.mkdir(parents=True, exist_ok=True)
        (book_dir / "concept_seed.json").write_text(
            json.dumps(source_seed), encoding="utf-8"
        )
        with pytest.raises(FileNotFoundError, match="transition"):
            spawn_next_book(
                from_book=SOURCE_BOOK, to_book=TARGET_BOOK,
                franchise=FRANCHISE, base_dir=str(tmp_path),
            )

    def test_snapshot_with_mismatched_book_number_emits_warning(
        self, tmp_path, source_seed, snapshot
    ):
        # Save the snapshot as book_1 but claim book_number=5 inside.
        bad_snapshot = dict(snapshot)
        bad_snapshot["book_number"] = 5
        _install_source_project(tmp_path, source_seed, bad_snapshot)
        result = spawn_next_book(
            from_book=SOURCE_BOOK, to_book=TARGET_BOOK,
            franchise=FRANCHISE, base_dir=str(tmp_path),
        )
        assert any("book_number" in w for w in result.warnings)
        # filename wins: treated as book 1, next = 2.
        assert result.target_book_number == 2


class TestSpawnNextBookCLI:
    def test_main_exits_zero_on_success(
        self, tmp_path, source_seed, snapshot, capsys
    ):
        _install_source_project(tmp_path, source_seed, snapshot)
        exit_code = main([
            "--franchise", FRANCHISE,
            "--from-book", SOURCE_BOOK,
            "--to-book", TARGET_BOOK,
            "--base-dir", str(tmp_path),
        ])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Spawn Book 2" in captured.out

    def test_main_exits_nonzero_on_missing_source(self, tmp_path, capsys):
        exit_code = main([
            "--franchise", FRANCHISE,
            "--from-book", SOURCE_BOOK,
            "--to-book", TARGET_BOOK,
            "--base-dir", str(tmp_path),
        ])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "ERROR" in captured.err
