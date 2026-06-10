"""Slice 3 PromiseLedger unit tests (spec §7.5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.memory.promise_ledger import (
    PromiseLedger,
    _scene_id,
    _scene_id_distance,
    _scene_id_lt,
)


# ----------------------------- Helpers / fixtures ----------------------------


def _seed(ledger: PromiseLedger, rows: list[dict]) -> None:
    """Direct-seed the ledger bypassing initialize_from_planning so tests can
    craft exact setup/payoff/due topologies without fighting the planning
    heuristics."""
    from datetime import datetime, timezone
    import json

    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        ledger.conn.execute(
            """
            INSERT INTO promise_ledger (
                promise_id, description, promise_type, setup_scene, payoff_scene,
                due_by_scene, status, progression_log, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r["promise_id"],
                r.get("description", ""),
                r.get("promise_type"),
                r["setup_scene"],
                r.get("payoff_scene"),
                r.get("due_by_scene"),
                r.get("status", "planted"),
                json.dumps(r.get("progression_log") or []),
                r.get("created_at", now),
                r.get("updated_at", now),
            ),
        )
    ledger.conn.commit()


@pytest.fixture
def ledger() -> PromiseLedger:
    return PromiseLedger(db_path=":memory:")


# -------------------------------- scene-id algebra ---------------------------


def test_scene_id_helpers():
    assert _scene_id(3, 7) == "ch03_sc07"
    assert _scene_id_lt("ch01_sc01", "ch02_sc01") is True
    assert _scene_id_lt("ch02_sc01", "ch02_sc01") is False
    assert _scene_id_distance("ch01_sc01", "ch02_sc02") == 101
    assert _scene_id_distance("ch02_sc02", "ch01_sc01") == -101


# -------------------------------- list_active --------------------------------


def test_list_active_includes_promise_with_no_payoff_yet(ledger):
    _seed(ledger, [
        {
            "promise_id": "P1", "setup_scene": "ch01_sc01",
            "due_by_scene": "ch03_sc02", "status": "planted",
        },
    ])
    rows = ledger.list_active(at_scene="ch02_sc03")
    assert [r["promise_id"] for r in rows] == ["P1"]


def test_list_active_excludes_promise_before_setup(ledger):
    _seed(ledger, [
        {"promise_id": "P1", "setup_scene": "ch05_sc01"},
    ])
    assert ledger.list_active(at_scene="ch01_sc01") == []


def test_list_active_excludes_promise_after_payoff(ledger):
    _seed(ledger, [
        {
            "promise_id": "P1", "setup_scene": "ch01_sc01",
            "payoff_scene": "ch03_sc01", "status": "paid",
        },
    ])
    assert ledger.list_active(at_scene="ch03_sc02") == []


def test_list_active_includes_on_payoff_scene_boundary(ledger):
    # setup_scene <= at_scene < payoff_scene: equal to payoff is excluded.
    _seed(ledger, [
        {"promise_id": "P1", "setup_scene": "ch01_sc01",
         "payoff_scene": "ch03_sc01", "status": "progressing"},
    ])
    assert [r["promise_id"] for r in ledger.list_active(at_scene="ch02_sc09")] == ["P1"]
    assert ledger.list_active(at_scene="ch03_sc01") == []


def test_list_active_rejects_invalid_scene_id(ledger):
    with pytest.raises(ValueError):
        ledger.list_active(at_scene="not-a-scene")


# -------------------------------- list_overdue -------------------------------


def test_list_overdue_requires_due_by_scene_set(ledger):
    _seed(ledger, [
        {"promise_id": "P1", "setup_scene": "ch01_sc01", "due_by_scene": None},
    ])
    assert ledger.list_overdue(at_scene="ch05_sc01") == []


def test_list_overdue_returns_when_due_has_passed(ledger):
    _seed(ledger, [
        {"promise_id": "P1", "setup_scene": "ch01_sc01",
         "due_by_scene": "ch02_sc01", "status": "progressing"},
    ])
    rows = ledger.list_overdue(at_scene="ch03_sc01")
    assert len(rows) == 1
    assert rows[0]["overdue_by_scenes"] == 100


def test_list_overdue_empty_when_still_time(ledger):
    _seed(ledger, [
        {"promise_id": "P1", "setup_scene": "ch01_sc01",
         "due_by_scene": "ch05_sc01", "status": "progressing"},
    ])
    assert ledger.list_overdue(at_scene="ch02_sc01") == []


# -------------------------------- list_top_urgent ----------------------------


def test_list_top_urgent_respects_n_cap(ledger):
    rows = []
    for i in range(1, 9):
        rows.append({
            "promise_id": f"P{i}", "setup_scene": "ch01_sc01",
            "due_by_scene": f"ch0{i+1}_sc01", "status": "progressing",
        })
    _seed(ledger, rows)
    top = ledger.list_top_urgent(at_scene="ch02_sc00", n=3)
    assert len(top) == 3
    # Most urgent first: due_by nearest to at_scene wins.
    assert top[0]["promise_id"] == "P1"


def test_list_top_urgent_overdue_ranks_first(ledger):
    _seed(ledger, [
        {"promise_id": "FAR",  "setup_scene": "ch01_sc01",
         "due_by_scene": "ch09_sc01", "status": "progressing"},
        {"promise_id": "LATE", "setup_scene": "ch01_sc01",
         "due_by_scene": "ch02_sc01", "status": "progressing"},
        {"promise_id": "NEAR", "setup_scene": "ch01_sc01",
         "due_by_scene": "ch04_sc01", "status": "progressing"},
    ])
    top = ledger.list_top_urgent(at_scene="ch03_sc05", n=5)
    assert [e["promise_id"] for e in top] == ["LATE", "NEAR", "FAR"]
    assert top[0]["status"] == "overdue"
    assert top[0]["overdue_by_scenes"] > 0


def test_list_top_urgent_no_deadline_ranks_last(ledger):
    _seed(ledger, [
        {"promise_id": "A", "setup_scene": "ch01_sc01",
         "due_by_scene": "ch04_sc01", "status": "progressing"},
        {"promise_id": "B", "setup_scene": "ch01_sc01",
         "due_by_scene": None, "status": "progressing"},
    ])
    top = ledger.list_top_urgent(at_scene="ch02_sc01", n=5)
    assert [e["promise_id"] for e in top] == ["A", "B"]


def test_count_active_tracks_list_active(ledger):
    _seed(ledger, [
        {"promise_id": "P1", "setup_scene": "ch01_sc01",
         "status": "progressing", "due_by_scene": "ch05_sc01"},
        {"promise_id": "P2", "setup_scene": "ch02_sc01",
         "status": "planted", "due_by_scene": "ch06_sc01"},
        {"promise_id": "P3", "setup_scene": "ch01_sc01",
         "payoff_scene": "ch02_sc01", "status": "paid"},
    ])
    assert ledger.count_active(at_scene="ch03_sc01") == 2


# -------------------------------- record_* -----------------------------------


def test_record_progression_transitions_planted_to_progressing(ledger):
    _seed(ledger, [{"promise_id": "P1", "setup_scene": "ch01_sc01"}])
    ledger.record_progression(
        promise_id="P1", scene_id="ch02_sc01", source="scene_card", note="beat",
    )
    row = ledger.get("P1")
    assert row["status"] == "progressing"
    assert len(row["progression_log"]) == 1
    assert row["progression_log"][0]["scene_id"] == "ch02_sc01"


def test_record_progression_rejects_unknown_source(ledger):
    _seed(ledger, [{"promise_id": "P1", "setup_scene": "ch01_sc01"}])
    with pytest.raises(ValueError):
        ledger.record_progression(
            promise_id="P1", scene_id="ch02_sc01", source="nope",
        )


def test_record_progression_unknown_promise_raises(ledger):
    with pytest.raises(KeyError):
        ledger.record_progression(
            promise_id="missing", scene_id="ch02_sc01", source="scene_card",
        )


def test_record_payoff_moves_status_to_paid(ledger):
    _seed(ledger, [
        {"promise_id": "P1", "setup_scene": "ch01_sc01", "status": "progressing"},
    ])
    ledger.record_payoff(promise_id="P1", scene_id="ch05_sc01")
    row = ledger.get("P1")
    assert row["status"] == "paid"
    assert row["payoff_scene"] == "ch05_sc01"
    # Paid promise no longer listed as active.
    assert ledger.list_active(at_scene="ch06_sc01") == []


def test_record_broken_logs_reason_and_sets_status(ledger):
    _seed(ledger, [{"promise_id": "P1", "setup_scene": "ch01_sc01"}])
    ledger.record_broken(
        promise_id="P1", scene_id="ch03_sc01", reason="scope cut",
    )
    row = ledger.get("P1")
    assert row["status"] == "broken"
    assert any("scope cut" in entry["note"] for entry in row["progression_log"])


# -------------------------------- initialize_from_planning -------------------


def test_initialize_from_planning_seeds_story_physics_rows(ledger):
    concept_seed = {
        "story_physics": {
            "promise_payoff_ledger": [
                {
                    "promise_id": "PP01",
                    "description": "Ben will find the source of the wrongness",
                    "planted_chapter": 1,
                    "payoff_chapter": 5,
                    "type": "setup_payoff",
                    "status": "unfulfilled",
                },
                {
                    "promise_id": "PP02",
                    "description": "Ben + Desh acknowledge GAG history",
                    "planted_in": "Chapter 1",
                    "payoff_in": "Chapter 11",
                    "type": "character",
                    "status": "unfulfilled",
                },
            ],
        },
    }
    scene_cards = [
        {"chapter_number": 1, "scene_number": 1, "promises_planted": ["PP01", "PP02"]},
        {"chapter_number": 5, "scene_number": 4, "promises_paid": ["PP01"]},
    ]
    count = ledger.initialize_from_planning(
        concept_seed=concept_seed, scene_cards=scene_cards,
    )
    assert count == 2

    # Planning declares where payoffs are SCHEDULED \u2014 seeding never marks a
    # promise paid. Runtime record_payoff (scene save / patch replay) is the
    # only writer of status='paid' / payoff_scene.
    pp01 = ledger.get("PP01")
    assert pp01 is not None
    assert pp01["setup_scene"] == "ch01_sc01"
    assert pp01["payoff_scene"] is None
    assert pp01["status"] == "planted"
    assert pp01["due_by_scene"] == "ch05_sc04"  # card-refined from ch05_sc99
    assert pp01["promise_type"] == "plot"  # setup_payoff \u2192 plot

    pp02 = ledger.get("PP02")
    assert pp02["setup_scene"] == "ch01_sc01"
    assert pp02["payoff_scene"] is None
    assert pp02["status"] == "planted"
    assert pp02["due_by_scene"] == "ch11_sc99"  # chapter-end sentinel
    assert pp02["promise_type"] == "character"

    # Both must be visible to the packet compiler before their due scenes \u2014
    # this is the regression that left list_top_urgent empty on a freshly
    # seeded book whose cards declared future payoffs.
    active_ids = {
        e["promise_id"] for e in ledger.list_top_urgent(at_scene="ch02_sc01", n=5)
    }
    assert active_ids == {"PP01", "PP02"}


def test_initialize_from_planning_is_idempotent(ledger):
    concept_seed = {
        "story_physics": {
            "promise_payoff_ledger": [
                {
                    "promise_id": "PP01", "description": "x",
                    "planted_chapter": 1, "type": "plot", "status": "unfulfilled",
                },
            ],
        },
    }
    ledger.initialize_from_planning(concept_seed=concept_seed, scene_cards=[])
    ledger.initialize_from_planning(concept_seed=concept_seed, scene_cards=[])
    rows = ledger.list_all()
    assert [r["promise_id"] for r in rows] == ["PP01"]


def test_initialize_preserves_existing_progression_log(ledger):
    concept_seed = {
        "story_physics": {
            "promise_payoff_ledger": [
                {
                    "promise_id": "PP01", "description": "x",
                    "planted_chapter": 1, "type": "plot", "status": "unfulfilled",
                },
            ],
        },
    }
    ledger.initialize_from_planning(concept_seed=concept_seed, scene_cards=[])
    ledger.record_progression(
        promise_id="PP01", scene_id="ch01_sc02", source="scene_card",
    )
    ledger.initialize_from_planning(concept_seed=concept_seed, scene_cards=[])
    row = ledger.get("PP01")
    assert len(row["progression_log"]) == 1


def test_initialize_drops_entries_with_no_setup_scene(ledger):
    concept_seed = {
        "story_physics": {
            "promise_payoff_ledger": [
                {"promise_id": "X", "description": "missing setup"},
            ],
        },
    }
    assert ledger.initialize_from_planning(
        concept_seed=concept_seed, scene_cards=[],
    ) == 0


# -------------------------------- stub API compat ----------------------------


def test_active_for_chapter_matches_list_active_at_sc01(ledger):
    _seed(ledger, [
        {"promise_id": "P1", "setup_scene": "ch02_sc05", "status": "planted"},
    ])
    assert ledger.active_for_chapter(1) == []
    assert [r["promise_id"] for r in ledger.active_for_chapter(3)] == ["P1"]


def test_pending_as_of_chapter_includes_unpaid_from_prior_chapters(ledger):
    _seed(ledger, [
        {"promise_id": "P1", "setup_scene": "ch01_sc01",
         "status": "progressing", "due_by_scene": "ch02_sc01"},
        {"promise_id": "P2", "setup_scene": "ch02_sc01",
         "status": "paid", "payoff_scene": "ch02_sc09"},
    ])
    pending = ledger.pending_as_of_chapter(3)
    assert [r["promise_id"] for r in pending] == ["P1"]
