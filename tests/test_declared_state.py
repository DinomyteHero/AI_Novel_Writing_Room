"""Declared-state apply — scene-card declarations write trusted state.

Trust model: characters.status is written from declared scene-card
``end_state`` at save time (declarations win over the Summarizer's
extracted diff), and declared ``start_state`` is verified against the
accumulated trusted state — drift surfaces as a ``declared_state_conflict``
warn event plus a ``prose.continuity.character_state_break`` revision-debt
row, never a block. Flag: ``runtime.declared_state.enabled`` (default off).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

from src.memory.story_state import StoryState
from src.orchestrator import Orchestrator
from src.pipeline.revision_debt import RevisionDebtStore
from src.run_ledger import RunLedger


def _make_orchestrator(
    tmp_path: Path,
    *,
    story_state: StoryState,
    declared_state_enabled: bool = True,
    debt_store: RevisionDebtStore | None = None,
    revision_debt_enabled: bool = False,
) -> tuple[Orchestrator, RunLedger]:
    ledger = RunLedger(db_path=str(tmp_path / "run_ledger.db"))
    flags = {
        "runtime": {
            "declared_state": {"enabled": declared_state_enabled},
            "revision_debt": {"enabled": revision_debt_enabled},
        }
    }
    orch = Orchestrator(
        router=MagicMock(),
        context_assembler=MagicMock(),
        ledger=ledger,
        manuscripts_dir=str(tmp_path / "chapters"),
        story_state=story_state,
        runtime_flags=flags,
        revision_debt_store=debt_store,
    )
    return orch, ledger


def _card(**extra) -> dict:
    base = {
        "chapter_number": 3,
        "scene_number": 1,
        "pov_character": "Ben Skywalker",
        "mission": "m",
        "conflict": "c",
        "turning_point": "t",
        "characters_present": ["Ben Skywalker"],
    }
    base.update(extra)
    return base


def test_fresh_db_is_v8_with_status_column(tmp_path):
    state = StoryState(str(tmp_path / "story_state.db"))
    assert state.get_schema_version() == 8
    state.add_character("ben", "Ben Skywalker")
    state.update_character("ben", status="alive")
    assert state.get_character("ben")["status"] == "alive"


def test_v7_database_migrates_to_v8(tmp_path):
    db_path = tmp_path / "story_state.db"
    StoryState(str(db_path)).conn.close()

    conn = sqlite3.connect(str(db_path))
    conn.execute("ALTER TABLE characters DROP COLUMN status")
    conn.execute("DELETE FROM schema_migrations WHERE version = 8")
    conn.commit()
    conn.close()

    migrated = StoryState(str(db_path))
    assert migrated.get_schema_version() == 8
    cols = {
        row[1]
        for row in migrated.conn.execute("PRAGMA table_info(characters)")
    }
    assert "status" in cols


def test_end_state_applies_and_wins_over_prior_status(tmp_path):
    state = StoryState(str(tmp_path / "story_state.db"))
    state.add_character("ben", "Ben Skywalker")
    state.update_character("ben", status="alive")
    orch, ledger = _make_orchestrator(tmp_path, story_state=state)

    orch._maybe_apply_declared_state(_card(end_state={"Ben Skywalker": "captured"}))

    row = state.get_character("ben")
    assert row["status"] == "captured"
    assert row["last_appearance_chapter"] == 3
    events = ledger.get_events(event_type="declared_state_applied")
    assert len(events) == 1
    assert events[0]["payload"]["applied"] == {"Ben Skywalker": "captured"}


def test_end_state_accepts_list_shape_and_normalizes(tmp_path):
    state = StoryState(str(tmp_path / "story_state.db"))
    state.add_character("ben", "Ben Skywalker")
    orch, _ = _make_orchestrator(tmp_path, story_state=state)

    orch._maybe_apply_declared_state(_card(
        end_state=[{"character": "Ben Skywalker", "state": "injured"}],
    ))

    assert state.get_character("ben")["status"] == "wounded"


def test_start_state_drift_emits_conflict_and_debt_row(tmp_path):
    state = StoryState(str(tmp_path / "story_state.db"))
    state.add_character("ben", "Ben Skywalker")
    state.update_character("ben", status="dead")
    debt = RevisionDebtStore(db_path=str(tmp_path / "revision_debt.db"))
    orch, ledger = _make_orchestrator(
        tmp_path, story_state=state, debt_store=debt, revision_debt_enabled=True,
    )

    # dead -> alive with no off-page bridge: requires_bridge drift.
    orch._maybe_apply_declared_state(_card(start_state={"Ben Skywalker": "alive"}))

    conflicts = ledger.get_events(event_type="declared_state_conflict")
    assert len(conflicts) == 1
    assert conflicts[0]["payload"]["transition"] == "requires_bridge"
    rows = debt.list_all()
    assert any(
        r["category"] == "prose.continuity.character_state_break" for r in rows
    )
    # Verification only — start_state never mutates trusted state.
    assert state.get_character("ben")["status"] == "dead"


def test_start_state_bridge_suppresses_conflict(tmp_path):
    state = StoryState(str(tmp_path / "story_state.db"))
    state.add_character("ben", "Ben Skywalker")
    state.update_character("ben", status="dead")
    orch, ledger = _make_orchestrator(tmp_path, story_state=state)

    orch._maybe_apply_declared_state(_card(
        start_state={"Ben Skywalker": "alive"},
        off_page_events=["Ben Skywalker survived the collapse and escaped."],
    ))

    assert ledger.get_events(event_type="declared_state_conflict") == []


def test_start_state_natural_transition_is_silent(tmp_path):
    state = StoryState(str(tmp_path / "story_state.db"))
    state.add_character("ben", "Ben Skywalker")
    state.update_character("ben", status="alive")
    orch, ledger = _make_orchestrator(tmp_path, story_state=state)

    orch._maybe_apply_declared_state(_card(start_state={"Ben Skywalker": "wounded"}))

    assert ledger.get_events(event_type="declared_state_conflict") == []


def test_unknown_character_warns_without_aborting(tmp_path):
    state = StoryState(str(tmp_path / "story_state.db"))
    state.add_character("ben", "Ben Skywalker")
    orch, ledger = _make_orchestrator(tmp_path, story_state=state)

    orch._maybe_apply_declared_state(_card(
        end_state={"Nobody Real": "dead", "Ben Skywalker": "wounded"},
    ))

    warns = ledger.get_events(event_type="declared_state_unknown_character")
    assert len(warns) == 1
    assert warns[0]["payload"]["character"] == "Nobody Real"
    assert state.get_character("ben")["status"] == "wounded"


def test_flag_off_is_a_noop(tmp_path):
    state = StoryState(str(tmp_path / "story_state.db"))
    state.add_character("ben", "Ben Skywalker")
    state.update_character("ben", status="alive")
    orch, ledger = _make_orchestrator(
        tmp_path, story_state=state, declared_state_enabled=False,
    )

    orch._maybe_apply_declared_state(_card(end_state={"Ben Skywalker": "dead"}))

    assert state.get_character("ben")["status"] == "alive"
    assert ledger.get_events(event_type="declared_state_applied") == []
