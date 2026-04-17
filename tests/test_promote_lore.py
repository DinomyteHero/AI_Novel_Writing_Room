"""Phase 7.3 — scripts/promote_lore.py decision flow.

Covers the core ``promote_lore`` function directly (not the CLI wrapper)
because the flow's correctness is about decisions + DB writes, not argv
parsing. One additional test exercises the argparse path with
``--accept-all`` against an in-memory fake service to confirm wiring.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.promote_lore import (
    PromotionReport,
    _format_summary,
    promote_lore,
)


# ---------------------------------------------------------------------------
# In-memory fake LoreService
# ---------------------------------------------------------------------------


class FakeLoreService:
    """Mirrors just the surface promote_lore uses."""

    def __init__(self, entries: list[dict]) -> None:
        self._by_id = {e["entry_id"]: dict(e) for e in entries}
        self.db = MagicMock()
        self.db.list_lore_entries = self._list_lore_entries
        self.db.get_lore_entry = self._get_lore_entry
        self.db.update_lore_entry = self._update_lore_entry
        self.promote_calls: list[str] = []

    def _list_lore_entries(
        self,
        universe_id: str,
        category: str | None = None,
        status: str | None = None,
    ) -> list[dict]:
        results = []
        for e in self._by_id.values():
            if e.get("universe_id") != universe_id:
                continue
            if category and e.get("category") != category:
                continue
            if status and e.get("status") != status:
                continue
            results.append(dict(e))
        return results

    def _get_lore_entry(self, entry_id: str) -> dict | None:
        e = self._by_id.get(entry_id)
        return dict(e) if e else None

    def _update_lore_entry(self, entry_id: str, **kwargs) -> None:
        if entry_id in self._by_id:
            self._by_id[entry_id].update(kwargs)

    def promote_entry(self, entry_id: str) -> None:
        self.promote_calls.append(entry_id)
        if entry_id in self._by_id:
            self._by_id[entry_id]["status"] = "canonical"


def _entry(
    *,
    entry_id: str,
    title: str,
    category: str = "faction",
    status: str = "provisional",
    content: str = "placeholder",
    universe_id: str = "u1",
) -> dict:
    return {
        "entry_id": entry_id,
        "universe_id": universe_id,
        "title": title,
        "content": content,
        "category": category,
        "status": status,
        "tags": None,
        "timeline_sort_start": None,
        "timeline_sort_end": None,
    }


# ---------------------------------------------------------------------------
# Non-interactive modes
# ---------------------------------------------------------------------------


class TestAcceptAllMode:
    def test_promotes_every_provisional(self):
        svc = FakeLoreService([
            _entry(entry_id="p1", title="A"),
            _entry(entry_id="p2", title="B"),
        ])
        report = promote_lore(
            lore_service=svc, universe_id="u1", mode="accept-all",
        )
        assert report.total_provisional == 2
        assert len(report.promoted) == 2
        assert {d.entry_id for d in report.promoted} == {"p1", "p2"}
        assert svc.promote_calls == ["p1", "p2"]

    def test_ignores_already_canonical_entries(self):
        svc = FakeLoreService([
            _entry(entry_id="p1", title="A"),
            _entry(entry_id="c1", title="Already canonical", status="canonical"),
        ])
        report = promote_lore(
            lore_service=svc, universe_id="u1", mode="accept-all",
        )
        assert report.total_provisional == 1
        assert svc.promote_calls == ["p1"]


class TestRejectAllMode:
    def test_sets_every_entry_to_deprecated(self):
        svc = FakeLoreService([_entry(entry_id="p1", title="A")])
        report = promote_lore(
            lore_service=svc, universe_id="u1", mode="reject-all",
        )
        assert len(report.rejected) == 1
        # The entry's status is now deprecated.
        assert svc._by_id["p1"]["status"] == "deprecated"
        # promote_entry was NOT called.
        assert svc.promote_calls == []


class TestDryRun:
    def test_dry_run_records_decisions_without_writing(self):
        svc = FakeLoreService([
            _entry(entry_id="p1", title="A"),
            _entry(entry_id="p2", title="B"),
        ])
        report = promote_lore(
            lore_service=svc, universe_id="u1",
            mode="accept-all", dry_run=True,
        )
        assert report.dry_run is True
        assert len(report.promoted) == 2
        # DB is untouched.
        assert svc.promote_calls == []
        assert svc._by_id["p1"]["status"] == "provisional"


# ---------------------------------------------------------------------------
# Interactive mode
# ---------------------------------------------------------------------------


class TestInteractiveMode:
    def test_per_entry_decisions_honoured(self):
        svc = FakeLoreService([
            _entry(entry_id="p1", title="A"),
            _entry(entry_id="p2", title="B"),
            _entry(entry_id="p3", title="C"),
        ])
        # promote, reject, skip
        answers = iter(["p", "r", "s"])

        def fake_prompt(_):
            return next(answers)

        report = promote_lore(
            lore_service=svc, universe_id="u1",
            mode="interactive", prompt=fake_prompt, printer=lambda _: None,
        )
        decisions = {d.entry_id: d.decision for d in report.decisions}
        assert decisions["p1"] == "promote"
        assert decisions["p2"] == "reject"
        assert decisions["p3"] == "skip"
        assert svc.promote_calls == ["p1"]
        assert svc._by_id["p2"]["status"] == "deprecated"
        assert svc._by_id["p3"]["status"] == "provisional"  # untouched

    def test_quit_treats_remaining_as_skip(self):
        svc = FakeLoreService([
            _entry(entry_id="p1", title="A"),
            _entry(entry_id="p2", title="B"),
            _entry(entry_id="p3", title="C"),
        ])
        # promote p1, then quit — p2 and p3 become skip.
        answers = iter(["p", "q"])

        def fake_prompt(_):
            return next(answers)

        report = promote_lore(
            lore_service=svc, universe_id="u1",
            mode="interactive", prompt=fake_prompt, printer=lambda _: None,
        )
        assert svc.promote_calls == ["p1"]
        decisions = {d.entry_id: d.decision for d in report.decisions}
        assert decisions["p2"] == "skip"
        assert decisions["p3"] == "skip"

    def test_invalid_input_retries(self):
        svc = FakeLoreService([_entry(entry_id="p1", title="A")])
        answers = iter(["bogus", "also-bogus", "p"])

        def fake_prompt(_):
            return next(answers)

        report = promote_lore(
            lore_service=svc, universe_id="u1",
            mode="interactive", prompt=fake_prompt, printer=lambda _: None,
        )
        assert len(report.promoted) == 1


# ---------------------------------------------------------------------------
# Conflict flags threaded through
# ---------------------------------------------------------------------------


class TestConflictFlagsIncluded:
    def test_decision_records_include_detector_flags(self):
        """When a conflict_profile is supplied, flags appear on the
        decision record so the JSON report can surface them."""
        svc = FakeLoreService([
            _entry(
                entry_id="p1",
                title="LIDAR Faction",
                content="They hunt with LIDAR scanners.",
            ),
        ])
        profile = {"cross_continuity_violations": ["LIDAR"]}
        report = promote_lore(
            lore_service=svc, universe_id="u1",
            canon_profile=profile, mode="accept-all",
        )
        assert len(report.decisions) == 1
        flags = report.decisions[0].conflict_flags
        assert len(flags) >= 1
        assert any(f["conflict_type"] == "canon_rule_violation" for f in flags)


# ---------------------------------------------------------------------------
# Report + formatting
# ---------------------------------------------------------------------------


class TestPromotionReport:
    def test_to_dict_round_trip(self):
        svc = FakeLoreService([
            _entry(entry_id="p1", title="A"),
            _entry(entry_id="p2", title="B"),
        ])
        report = promote_lore(
            lore_service=svc, universe_id="u1", mode="accept-all",
        )
        payload = report.to_dict()
        assert payload["universe_id"] == "u1"
        assert payload["promoted_count"] == 2
        # Round-trip through JSON to verify serializability.
        as_json = json.dumps(payload)
        assert "promoted_count" in as_json

    def test_format_summary_mentions_counts(self):
        report = PromotionReport(
            universe_id="u1", total_provisional=3, dry_run=True,
        )
        output = _format_summary(report)
        assert "universe=u1" in output
        assert "DRY-RUN" in output
        assert "total provisional reviewed: 3" in output


# ---------------------------------------------------------------------------
# Empty / happy-path edge cases
# ---------------------------------------------------------------------------


class TestEmptyUniverse:
    def test_no_provisional_entries_returns_empty_report(self):
        svc = FakeLoreService([])
        report = promote_lore(
            lore_service=svc, universe_id="u1", mode="accept-all",
            printer=lambda _: None,
        )
        assert report.total_provisional == 0
        assert report.decisions == []
        assert svc.promote_calls == []


class TestCategoryFilter:
    def test_category_filter_passes_through_to_list(self):
        svc = FakeLoreService([
            _entry(entry_id="p1", title="Faction A", category="faction"),
            _entry(entry_id="p2", title="Loc B", category="location"),
        ])
        report = promote_lore(
            lore_service=svc, universe_id="u1",
            mode="accept-all", category="faction",
        )
        assert report.total_provisional == 1
        assert report.decisions[0].entry_id == "p1"
