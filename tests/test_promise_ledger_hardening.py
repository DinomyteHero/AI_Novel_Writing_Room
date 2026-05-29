"""Regression tests for promise-ledger fixes.

- Re-seeding from planning must not clobber a runtime-advanced status.
- Scene IDs for chapters >= 100 must parse (the regex required exactly 2 digits).
"""

from pathlib import Path

import pytest

from src.memory.promise_ledger import PromiseLedger, _parse_scene_id


@pytest.fixture
def ledger(temp_dir):
    pl = PromiseLedger(db_path=str(Path(temp_dir) / "pl.db"))
    yield pl
    pl.conn.close()


def test_reseed_preserves_runtime_status(ledger):
    seed = {"story_physics": {"promise_payoff_ledger": [
        {"id": "p1", "description": "x", "planted_chapter": 1},
    ]}}
    cards = [{"chapter_number": 1, "scene_number": 1, "promises_planted": ["p1"]}]

    ledger.initialize_from_planning(concept_seed=seed, scene_cards=cards)
    assert ledger.get("p1")["status"] == "planted"

    ledger.record_progression(promise_id="p1", scene_id="ch02_sc01")
    assert ledger.get("p1")["status"] == "progressing"

    # Re-seed (e.g. migrate_promise_ledger re-run) must NOT revert the status.
    ledger.initialize_from_planning(concept_seed=seed, scene_cards=cards)
    assert ledger.get("p1")["status"] == "progressing"


def test_scene_id_parses_chapter_over_99():
    assert _parse_scene_id("ch100_sc01") == (100, 1)
    assert _parse_scene_id("ch05_sc03") == (5, 3)
    assert _parse_scene_id("bogus") is None
