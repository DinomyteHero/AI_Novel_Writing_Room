"""Slice 4 ContinuityLog unit tests (spec §8.6)."""

from __future__ import annotations

import pytest

from src.memory.continuity_log import ContinuityLog, EVENT_TYPES


def _make_event(**overrides):
    ev = {
        "event_type": "location_change",
        "scene_id": "ch01_sc01",
        "subject": "Hunter",
        "details": {"from_location": "family_estate", "to_location": "Coruscant_spaceport"},
        "confidence": 0.95,
        "extractor_version": "v0.1",
    }
    ev.update(overrides)
    return ev


@pytest.fixture
def log() -> ContinuityLog:
    return ContinuityLog(db_path=":memory:")


# ------------------------------------------------------------------ append


def test_append_returns_stable_event_id(log):
    ev = _make_event()
    a = log.append(ev)
    # Re-appending the same content is a REPLACE — same id.
    b = log.append(ev)
    assert a == b
    assert a.startswith("evt_")


def test_append_rejects_unknown_event_type(log):
    with pytest.raises(ValueError):
        log.append(_make_event(event_type="emotional_shift"))


def test_append_rejects_bad_scene_id(log):
    with pytest.raises(ValueError):
        log.append(_make_event(scene_id="Chapter 1"))


def test_append_rejects_missing_subject(log):
    with pytest.raises(ValueError):
        log.append(_make_event(subject=""))


def test_append_rejects_non_mapping_details(log):
    with pytest.raises(ValueError):
        log.append(_make_event(details="not a dict"))


def test_append_rejects_out_of_range_confidence(log):
    with pytest.raises(ValueError):
        log.append(_make_event(confidence=1.5))
    with pytest.raises(ValueError):
        log.append(_make_event(confidence=-0.1))


def test_append_all_event_types_accepted(log):
    rows = [
        _make_event(event_type="location_change"),
        _make_event(event_type="injury_state", subject="Ben",
                    details={"severity": "minor", "body_part": "arm", "mechanism": "fall"}),
        _make_event(event_type="possession", subject="Ben",
                    details={"item": "datacube", "action": "acquired"}),
        _make_event(event_type="revelation", subject="Ben",
                    details={"revelation_id": "R01", "recipient": "Ben"}),
        _make_event(event_type="status_change", subject="Ben",
                    details={"status_id": "S01", "new_value": "initiated"}),
    ]
    ids = log.append_many(rows)
    assert len(set(ids)) == len(rows)


# ------------------------------------------------------------------ reads


def test_events_for_chapter_bucketizes_scene_ids(log):
    log.append(_make_event(scene_id="ch01_sc01", subject="Hunter"))
    log.append(_make_event(scene_id="ch02_sc03", subject="Hunter"))
    assert len(log.events_for_chapter(1)) == 1
    # Chapter 2 must include the ch01 location_change (propagates forward).
    assert len(log.events_for_chapter(2)) == 2


def test_events_for_chapter_skips_non_stateful_from_prior(log):
    # revelation does not propagate; location_change does.
    log.append(_make_event(
        scene_id="ch01_sc01", subject="Ben", event_type="revelation",
        details={"revelation_id": "R01", "recipient": "Ben"},
    ))
    log.append(_make_event(scene_id="ch01_sc02", subject="Ben"))  # loc_change
    ch02 = log.events_for_chapter(2)
    types = {e["event_type"] for e in ch02}
    assert "location_change" in types
    assert "revelation" not in types


def test_list_events_for_subject_filters_by_scene_id(log):
    log.append(_make_event(scene_id="ch01_sc01", subject="Hunter"))
    log.append(_make_event(
        scene_id="ch02_sc01", subject="Hunter",
        details={"from_location": "A", "to_location": "B"},
    ))
    rows = log.list_events_for_subject("Hunter", before_scene="ch02_sc00")
    assert len(rows) == 1
    assert rows[0]["scene_id"] == "ch01_sc01"


# ------------------------------------------------------------------ redact


def test_redaction_hides_from_reads_but_persists_on_disk(log):
    event_id = log.append(_make_event())
    log.redact(event_id, reason="duplicate")
    # Default read filters out redacted rows.
    assert log.list_all() == []
    # include_redacted=True brings them back.
    all_rows = log.list_all(include_redacted=True)
    assert len(all_rows) == 1
    assert all_rows[0]["redacted"] is True
    assert all_rows[0]["redacted_reason"] == "duplicate"


def test_redact_unknown_id_raises(log):
    with pytest.raises(KeyError):
        log.redact("missing", reason="x")


def test_mark_human_verified_sets_flag(log):
    event_id = log.append(_make_event())
    log.mark_human_verified(event_id)
    assert log.get(event_id)["human_verified"] is True


# ------------------------------------------------------------------ count


def test_count_excludes_redacted(log):
    a = log.append(_make_event())
    log.append(_make_event(scene_id="ch01_sc02"))
    assert log.count() == 2
    log.redact(a, reason="x")
    assert log.count() == 1
