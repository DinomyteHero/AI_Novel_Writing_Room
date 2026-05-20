"""Tests for the Slice 2 revision-debt store + producer write-matrix.

Covers:
- Closed category enforcement (unknown categories raise ValueError).
- Required field enforcement (producer, scope.level, severity, status).
- Refusal of owner_or_reviewer_notes on the agent write path.
- Producer wrappers (every row in spec \u00a76.2.1 fires correctly).
- update_status transitions + return payload.
- summarize_for_chapter / summarize_for_book shapes.
- Noop behavior when store is None (flag-off).
- Ledger revision_debt_added emission with level=info.
"""

from __future__ import annotations

import pytest

from src.pipeline.revision_debt import (
    CATEGORIES,
    SEVERITIES,
    STATUSES,
    RevisionDebtStore,
)
from src.pipeline.revision_debt_producers import (
    emit_canon_advisory,
    emit_canon_fix_rejected,
    emit_canon_polish_drift,
    emit_compression_advisory,
    emit_final_gate_advisory,
    emit_gate_critic_advisory,
    emit_metric_advisory,
    emit_presence_near_miss,
    emit_scene_reviewer_finding,
    emit_scene_reviewer_other,
    emit_status_update,
    emit_wordcount_drift,
)


class _LedgerStub:
    def __init__(self) -> None:
        self.info: list[dict] = []
        self.warn: list[dict] = []
        self.error: list[dict] = []

    def emit_info(self, event_type, *, chapter_number=None, scene_number=None, agent_role=None, payload=None, attempt_id=None):
        self.info.append({"event_type": event_type, "payload": payload or {}})

    def emit_warn(self, event_type, *, chapter_number=None, scene_number=None, agent_role=None, payload=None, attempt_id=None):
        self.warn.append({"event_type": event_type, "payload": payload or {}})

    def emit_error(self, event_type, *, chapter_number=None, scene_number=None, agent_role=None, payload=None, attempt_id=None):
        self.error.append({"event_type": event_type, "payload": payload or {}})


# --------------------------------------------------------------- store basics


def _store() -> RevisionDebtStore:
    return RevisionDebtStore(db_path=":memory:")


def _valid_entry(**overrides) -> dict:
    base = {
        "producer": "canon_expert",
        "scope": {"level": "scene", "chapter_number": 1, "scene_number": 1},
        "category": "canon",
        "severity": "medium",
        "summary": "terminology drift",
        "details": {"code": "CANON_TERMINOLOGY"},
    }
    base.update(overrides)
    return base


def test_categories_match_schema():
    """The code enum must stay in sync with schemas/revision_debt.json."""
    import json
    from pathlib import Path
    with Path("schemas/revision_debt.json").open(encoding="utf-8") as fh:
        schema = json.load(fh)
    schema_categories = set(schema["properties"]["category"]["enum"])
    assert schema_categories == set(CATEGORIES)


def test_add_rejects_unknown_category():
    store = _store()
    with pytest.raises(ValueError, match="unknown category"):
        store.add(_valid_entry(category="not_a_category"))


def test_add_rejects_missing_producer():
    store = _store()
    entry = _valid_entry()
    entry.pop("producer")
    with pytest.raises(ValueError, match="producer"):
        store.add(entry)


def test_add_rejects_missing_scope_level():
    store = _store()
    with pytest.raises(ValueError, match="scope"):
        store.add(_valid_entry(scope={"chapter_number": 1}))


def test_add_rejects_bad_severity():
    store = _store()
    with pytest.raises(ValueError, match="severity"):
        store.add(_valid_entry(severity="critical"))


def test_add_rejects_bad_status():
    store = _store()
    with pytest.raises(ValueError, match="status"):
        store.add(_valid_entry(status="pending"))


def test_add_rejects_owner_notes_field():
    """owner_or_reviewer_notes is human-only; producers must not write it."""
    store = _store()
    with pytest.raises(ValueError, match="owner_or_reviewer_notes"):
        store.add(_valid_entry(owner_or_reviewer_notes="my note"))


def test_add_assigns_debt_id_and_defaults_status_open():
    store = _store()
    debt_id = store.add(_valid_entry())
    assert debt_id.startswith("debt_")
    row = store.get(debt_id)
    assert row["status"] == "open"
    assert row["category"] == "canon"
    assert row["severity"] == "medium"


def test_add_respects_supplied_debt_id():
    store = _store()
    debt_id = store.add(_valid_entry(debt_id="debt_test_42"))
    assert debt_id == "debt_test_42"


def test_list_open_filters_status_and_scope():
    store = _store()
    a = store.add(_valid_entry(category="canon", severity="high"))
    store.add(_valid_entry(category="metric", severity="low",
                           scope={"level": "scene", "chapter_number": 2, "scene_number": 1}))
    opened = store.list_open()
    assert len(opened) == 2
    scoped = store.list_open(scope={"chapter_number": 1})
    assert len(scoped) == 1
    assert scoped[0]["debt_id"] == a


def test_update_status_returns_transition():
    store = _store()
    debt_id = store.add(_valid_entry())
    result = store.update_status(debt_id, status="resolved", resolution_notes="fixed")
    assert result == {"old_status": "open", "new_status": "resolved"}
    row = store.get(debt_id)
    assert row["status"] == "resolved"
    assert row["resolution_notes"] == "fixed"
    assert row["resolved_at"] is not None


def test_summaries_group_by_category_and_severity():
    store = _store()
    store.add(_valid_entry(category="canon", severity="high"))
    store.add(_valid_entry(category="canon", severity="low",
                           scope={"level": "scene", "chapter_number": 1, "scene_number": 2}))
    store.add(_valid_entry(category="metric", severity="medium",
                           scope={"level": "scene", "chapter_number": 2, "scene_number": 1}))
    chapter1 = store.summarize_for_chapter(1)
    assert chapter1["counts_by_category"] == {"canon": 2}
    assert chapter1["counts_by_severity"] == {"high": 1, "low": 1}
    book = store.summarize_for_book()
    assert book["counts_by_category"] == {"canon": 2, "metric": 1}
    assert len(book["open_debt_ids"]) == 3


# ---------------------------------------------------------------- producers


def test_producers_noop_when_store_none():
    ledger = _LedgerStub()
    assert emit_canon_advisory(None, ledger=ledger,
                               scope={"level": "scene", "chapter_number": 1},
                               advisory={"code": "CANON_X", "severity": "low"}) is None
    assert ledger.info == []  # no ledger emit when nothing was written


def test_producer_emits_debt_added_with_level_info():
    ledger = _LedgerStub()
    store = _store()
    debt_id = emit_canon_advisory(
        store, ledger=ledger,
        scope={"level": "scene", "chapter_number": 1, "scene_number": 2},
        advisory={"code": "CANON_TERMINOLOGY", "severity": "medium",
                  "description": "Jedi Master normalization"},
    )
    assert debt_id is not None
    assert len(ledger.info) == 1
    ev = ledger.info[0]
    assert ev["event_type"] == "revision_debt_added"
    assert ev["payload"]["debt_id"] == debt_id
    assert ev["payload"]["severity"] == "medium"
    assert ev["payload"]["category"] == "canon"


@pytest.mark.parametrize("wrapper,kwargs,category,producer", [
    (
        emit_canon_advisory,
        {"scope": {"level": "scene", "chapter_number": 1},
         "advisory": {"code": "CANON_X", "severity": "medium", "description": "d"}},
        "canon", "canon_expert",
    ),
    (
        emit_canon_fix_rejected,
        {"scope": {"level": "scene", "chapter_number": 1},
         "fix": {"category": "foo", "from": "a", "to": "b"}, "reason": "not whitelisted"},
        "canon_fix_rejected", "canon_expert",
    ),
    (
        emit_canon_polish_drift,
        {"scope": {"level": "scene", "chapter_number": 1},
         "drift": {"description": "drift", "code": "CANON_DRIFT"}},
        "editorial.canon_polish_drift", "canon_expert",
    ),
    (
        emit_gate_critic_advisory,
        {"scope": {"level": "scene", "chapter_number": 1},
         "failure": {"code": "F", "severity": "non_blocking", "description": "d"}},
        "editorial.gate_advisory", "gate_critic",
    ),
    (
        emit_final_gate_advisory,
        {"scope": {"level": "scene", "chapter_number": 1},
         "failure": {"code": "F", "severity": "advisory", "description": "d"}},
        "editorial.final_gate_advisory", "final_gate",
    ),
    (
        emit_metric_advisory,
        {"scope": {"level": "scene", "chapter_number": 1},
         "metric_name": "repetition", "value": 0.8, "threshold": 0.5, "bands_over": 0},
        "metric", "quality_metrics",
    ),
    (
        emit_presence_near_miss,
        {"scope": {"level": "scene", "chapter_number": 1}, "confidence": 0.6},
        "presence_near_miss", "presence_checker",
    ),
    (
        emit_wordcount_drift,
        {"scope": {"level": "chapter", "chapter_number": 1},
         "target": 3000, "actual": 2000, "pct_drift": -33.3},
        "wordcount_drift", "word_count_telemetry",
    ),
    (
        emit_compression_advisory,
        {"scope": {"level": "scene", "chapter_number": 1},
         "pre_polish_words": 1000, "post_polish_words": 500, "ratio": 0.5},
        "compression_advisory", "compression_guard",
    ),
    (
        emit_scene_reviewer_finding,
        {"scope": {"level": "scene", "chapter_number": 1},
         "finding": {"summary": "x", "severity": "low"}},
        "editorial.scene_reviewer", "scene_reviewer",
    ),
    (
        emit_scene_reviewer_other,
        {"scope": {"level": "scene", "chapter_number": 1},
         "note": "free text"},
        "editorial.other", "scene_reviewer",
    ),
])
def test_write_matrix_row_produces_expected_category(wrapper, kwargs, category, producer):
    store = _store()
    ledger = _LedgerStub()
    debt_id = wrapper(store, ledger=ledger, **kwargs)
    assert debt_id is not None
    row = store.get(debt_id)
    assert row["category"] == category
    assert row["producer"] == producer
    assert row["severity"] in SEVERITIES


def test_wordcount_drift_severity_crosses_30pct_band():
    store = _store()
    ledger = _LedgerStub()
    low = emit_wordcount_drift(
        store, ledger=ledger, scope={"level": "chapter", "chapter_number": 1},
        target=3000, actual=2500, pct_drift=-16.7,
    )
    high = emit_wordcount_drift(
        store, ledger=ledger, scope={"level": "chapter", "chapter_number": 2},
        target=3000, actual=1000, pct_drift=-66.7,
    )
    assert store.get(low)["severity"] == "low"
    assert store.get(high)["severity"] == "medium"


def test_metric_advisory_bands_over_bumps_to_medium():
    store = _store()
    ledger = _LedgerStub()
    one_band = emit_metric_advisory(
        store, ledger=ledger, scope={"level": "scene", "chapter_number": 1},
        metric_name="m", value=1.0, threshold=0.5, bands_over=1,
    )
    two_bands = emit_metric_advisory(
        store, ledger=ledger, scope={"level": "scene", "chapter_number": 1},
        metric_name="m", value=2.0, threshold=0.5, bands_over=2,
    )
    assert store.get(one_band)["severity"] == "low"
    assert store.get(two_bands)["severity"] == "medium"


def test_status_update_emits_ledger_event():
    store = _store()
    ledger = _LedgerStub()
    debt_id = emit_canon_advisory(
        store, ledger=ledger,
        scope={"level": "scene", "chapter_number": 1},
        advisory={"code": "CANON_X", "severity": "low"},
    )
    ledger.info.clear()
    result = emit_status_update(
        store, ledger=ledger, debt_id=debt_id,
        status="resolved", resolution_notes="human fix",
    )
    assert result == {"old_status": "open", "new_status": "resolved"}
    assert len(ledger.info) == 1
    assert ledger.info[0]["event_type"] == "revision_debt_updated"


# ----------------------------------------------- rhythm + continuity producers


def test_rhythm_advisory_maps_known_codes_to_categories():
    from src.pipeline.revision_debt_producers import emit_rhythm_advisory
    store = _store()
    ledger = _LedgerStub()
    debt_id = emit_rhythm_advisory(
        store, ledger=ledger,
        scope={"level": "scene", "chapter_number": 1, "scene_number": 1},
        issue={
            "code": "rhythm.em_dash_overuse",
            "severity": "medium",
            "message": "too many em-dashes",
            "metric_value": 12.4,
            "threshold": 6.0,
        },
    )
    row = store.get(debt_id)
    assert row["category"] == "prose.rhythm.em_dash_overuse"
    assert row["severity"] == "medium"
    assert row["producer"] == "rhythm_validator"
    assert "metric_value" in row["details"]


def test_rhythm_advisory_unknown_code_routes_to_editorial_other():
    from src.pipeline.revision_debt_producers import emit_rhythm_advisory
    store = _store()
    debt_id = emit_rhythm_advisory(
        store,
        scope={"level": "scene", "chapter_number": 1},
        issue={"code": "rhythm.new_code_we_have_not_added", "severity": "low",
               "message": "x", "metric_value": 1.0, "threshold": 0.5},
    )
    assert store.get(debt_id)["category"] == "editorial.other"


def test_rhythm_advisory_noop_when_store_is_none():
    from src.pipeline.revision_debt_producers import emit_rhythm_advisory
    result = emit_rhythm_advisory(
        None,
        scope={"level": "scene", "chapter_number": 1},
        issue={"code": "rhythm.em_dash_overuse", "severity": "low",
               "message": "x", "metric_value": 1.0, "threshold": 0.5},
    )
    assert result is None


def test_rhythm_advisory_includes_metrics_snapshot_when_provided():
    from src.pipeline.revision_debt_producers import emit_rhythm_advisory
    store = _store()
    debt_id = emit_rhythm_advisory(
        store,
        scope={"level": "scene", "chapter_number": 1},
        issue={"code": "rhythm.em_dash_overuse", "severity": "low",
               "message": "x", "metric_value": 7.0, "threshold": 6.0},
        metrics={"em_dashes_per_1k_words": 7.0, "sentence_count": 50},
    )
    details = store.get(debt_id)["details"]
    assert details["metrics_snapshot"]["em_dashes_per_1k_words"] == 7.0


def test_continuity_break_maps_known_kinds_to_categories():
    from src.pipeline.revision_debt_producers import emit_continuity_break
    store = _store()
    debt_id = emit_continuity_break(
        store,
        scope={"level": "chapter", "chapter_number": 33},
        break_kind="character_state",
        summary="Aevyn: dead at close of ch32_sc01 → alive at open of ch33_sc01",
        details={"previous_state": "dead", "next_state": "alive"},
    )
    row = store.get(debt_id)
    assert row["category"] == "prose.continuity.character_state_break"
    assert row["producer"] == "continuity_validator"
    assert row["severity"] == "medium"
    assert row["fix_scope"] == "chapter"


def test_continuity_break_unknown_kind_routes_to_editorial_other():
    from src.pipeline.revision_debt_producers import emit_continuity_break
    store = _store()
    debt_id = emit_continuity_break(
        store,
        scope={"level": "chapter", "chapter_number": 1},
        break_kind="hairstyle",
        summary="x",
    )
    assert store.get(debt_id)["category"] == "editorial.other"
