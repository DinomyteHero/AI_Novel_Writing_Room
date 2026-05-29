"""Regression tests for state-write hardening.

- update_* methods reject column names that aren't real columns (closes the
  LLM-field SQL-injection / silent-OperationalError surface).
- StateDiffApplier.apply_diff (and any transaction() block) is atomic: a
  mid-sequence failure rolls back instead of committing a partial diff.
"""

from pathlib import Path

import pytest

from src.memory.story_state import StoryState


@pytest.fixture
def state(temp_dir):
    s = StoryState(db_path=str(Path(temp_dir) / "ss.db"))
    yield s
    s.conn.close()


def test_update_rejects_injected_column(state):
    state.add_hook(
        hook_id="h1", description="d", hook_type="foreshadow", planted_chapter=1
    )
    # An injected, SQL-bearing field name must be rejected before any execute.
    with pytest.raises(ValueError):
        state.update_hook("h1", **{"current_status = 'paid', priority": "x"})
    # A plain unknown column is also rejected.
    with pytest.raises(ValueError):
        state.update_hook("h1", not_a_column="x")
    # The hook is untouched, and a real column still updates.
    assert state.get_hook("h1")["current_status"] == "planted"
    state.update_hook("h1", current_status="resolved")
    assert state.get_hook("h1")["current_status"] == "resolved"


def test_transaction_rolls_back_on_error(state):
    state.add_character(id="c1", name="Char", current_location="start")
    with pytest.raises(RuntimeError):
        with state.transaction():
            state.update_character("c1", current_location="moved")
            raise RuntimeError("boom")
    # The uncommitted update was rolled back.
    assert state.get_character("c1")["current_location"] == "start"


def test_transaction_commits_on_success(state):
    state.add_character(id="c2", name="Char2", current_location="start")
    with state.transaction():
        state.update_character("c2", current_location="end")
    assert state.get_character("c2")["current_location"] == "end"
