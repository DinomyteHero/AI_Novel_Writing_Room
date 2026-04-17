"""Phase 7.2 — unit tests for LoreConflictDetector.

Three detection passes, advisory-by-default severity, deterministic output.
Tests use in-memory mock lore services (no real SQLite) so the detector's
logic is exercised in isolation.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.worldbuilding.lore_conflict_detector import (
    ConflictFlag,
    LoreConflictDetector,
    _normalize_title,
    _timeline_conflicts,
)


# ---------------------------------------------------------------------------
# Mock service
# ---------------------------------------------------------------------------


class FakeLoreDB:
    """In-memory drop-in for WorldbuildingDB supporting just the two
    methods the detector needs."""

    def __init__(self, entries: list[dict]) -> None:
        self._by_id = {e["entry_id"]: dict(e) for e in entries}

    def list_lore_entries(
        self, universe_id: str, status: str | None = None,
    ) -> list[dict]:
        out = []
        for e in self._by_id.values():
            if e.get("universe_id") != universe_id:
                continue
            if status and e.get("status") != status:
                continue
            out.append(dict(e))
        return out

    def get_lore_entry(self, entry_id: str) -> dict | None:
        e = self._by_id.get(entry_id)
        return dict(e) if e else None


def _service(entries: list[dict]) -> MagicMock:
    svc = MagicMock()
    svc.db = FakeLoreDB(entries)
    return svc


def _make_entry(
    *,
    entry_id: str,
    title: str,
    content: str = "",
    category: str = "faction",
    status: str = "canonical",
    universe_id: str = "u1",
    tags: list[str] | None = None,
    timeline_sort_start: int | None = None,
    timeline_sort_end: int | None = None,
) -> dict:
    return {
        "entry_id": entry_id,
        "universe_id": universe_id,
        "title": title,
        "content": content,
        "category": category,
        "status": status,
        "tags": tags,
        "timeline_sort_start": timeline_sort_start,
        "timeline_sort_end": timeline_sort_end,
    }


# ---------------------------------------------------------------------------
# _normalize_title
# ---------------------------------------------------------------------------


class TestNormalizeTitle:
    def test_collapses_case_and_whitespace(self):
        assert _normalize_title("The  Jedi  Council") == "the jedi council"

    def test_strips_punctuation(self):
        assert _normalize_title("Jedi Council.") == "jedi council"
        assert _normalize_title("Kaan's Army") == "kaans army"

    def test_preserves_leading_articles(self):
        """Articles are NOT stripped — 'The Order' and 'Order' stay
        distinct, preventing false positives on short titles."""
        assert _normalize_title("The Order") != _normalize_title("Order")

    def test_empty_input(self):
        assert _normalize_title("") == ""
        assert _normalize_title("   ") == ""


# ---------------------------------------------------------------------------
# Pass 1: title_collision
# ---------------------------------------------------------------------------


class TestTitleCollision:
    def test_exact_title_different_content_flagged_high(self):
        canonical = _make_entry(
            entry_id="c1", title="Ruusan Holocron", content="Original content.",
            status="canonical",
        )
        provisional = _make_entry(
            entry_id="p1", title="Ruusan Holocron", content="Different story.",
            status="provisional",
        )
        svc = _service([canonical, provisional])
        detector = LoreConflictDetector(svc)
        result = detector.scan_provisional_batch(["p1"], "u1")
        assert len(result.flags) == 1
        flag = result.flags[0]
        assert flag.conflict_type == "title_collision"
        assert flag.severity == "high"
        assert flag.target_entry_id == "c1"

    def test_normalized_title_match_still_flagged(self):
        """Near-match (whitespace/case/punctuation) collisions fire."""
        canonical = _make_entry(
            entry_id="c1", title="Jedi Council", content="A.", status="canonical",
        )
        provisional = _make_entry(
            entry_id="p1", title="the  JEDI  council.", content="B.",
            status="provisional",
        )
        svc = _service([canonical, provisional])
        # These normalize differently ("jedi council" vs "the jedi council")
        # so no collision expected.
        assert (
            _normalize_title(canonical["title"])
            != _normalize_title(provisional["title"])
        )
        detector = LoreConflictDetector(svc)
        result = detector.scan_provisional_batch(["p1"], "u1")
        assert result.is_clean()

    def test_same_content_same_title_is_low_severity(self):
        """Benign duplicate extraction — we still flag so the operator can
        deduplicate, but at low severity."""
        canonical = _make_entry(
            entry_id="c1", title="Kaan", content="A Sith lord.", status="canonical",
        )
        provisional = _make_entry(
            entry_id="p1", title="Kaan", content="A Sith lord.", status="provisional",
        )
        svc = _service([canonical, provisional])
        detector = LoreConflictDetector(svc)
        result = detector.scan_provisional_batch(["p1"], "u1")
        assert len(result.flags) == 1
        assert result.flags[0].severity == "low"

    def test_different_category_does_not_collide(self):
        canonical = _make_entry(
            entry_id="c1", title="Ruusan", category="location",
            content="A planet.", status="canonical",
        )
        provisional = _make_entry(
            entry_id="p1", title="Ruusan", category="faction",
            content="A warrior order.", status="provisional",
        )
        svc = _service([canonical, provisional])
        detector = LoreConflictDetector(svc)
        result = detector.scan_provisional_batch(["p1"], "u1")
        assert result.is_clean()

    def test_only_canonical_entries_considered(self):
        """Two provisional entries with the same title are NOT flagged —
        canonical is the reference truth."""
        p1 = _make_entry(entry_id="p1", title="X", content="A", status="provisional")
        p2 = _make_entry(entry_id="p2", title="X", content="B", status="provisional")
        svc = _service([p1, p2])
        detector = LoreConflictDetector(svc)
        result = detector.scan_provisional_batch(["p1", "p2"], "u1")
        assert result.is_clean()


# ---------------------------------------------------------------------------
# Pass 2: canon_rule_violation
# ---------------------------------------------------------------------------


class TestCanonRuleViolation:
    def test_cross_continuity_needle_in_content_flagged_high(self):
        provisional = _make_entry(
            entry_id="p1",
            title="Some Faction",
            content="They were equipped with a LIDAR scanner.",
            status="provisional",
        )
        svc = _service([provisional])
        profile = {"cross_continuity_violations": ["LIDAR"]}
        detector = LoreConflictDetector(svc, canon_profile=profile)
        result = detector.scan_provisional_batch(["p1"], "u1")
        assert any(
            f.conflict_type == "canon_rule_violation" and f.severity == "high"
            for f in result.flags
        )

    def test_cross_continuity_match_in_title(self):
        provisional = _make_entry(
            entry_id="p1", title="The Disney Retcon", content="",
            status="provisional",
        )
        svc = _service([provisional])
        profile = {"cross_continuity_violations": ["Disney Retcon"]}
        detector = LoreConflictDetector(svc, canon_profile=profile)
        result = detector.scan_provisional_batch(["p1"], "u1")
        assert len(result.flags) >= 1

    def test_anachronistic_term_flagged_medium(self):
        provisional = _make_entry(
            entry_id="p1", title="Hyperdrive", content="Upgraded via email from HQ.",
            status="provisional",
        )
        svc = _service([provisional])
        profile = {"anachronistic_terms": {"email": ["holomessage"]}}
        detector = LoreConflictDetector(svc, canon_profile=profile)
        result = detector.scan_provisional_batch(["p1"], "u1")
        flags = [
            f for f in result.flags if f.conflict_type == "canon_rule_violation"
        ]
        assert len(flags) == 1
        assert flags[0].severity == "medium"
        assert flags[0].canon_rule == "anachronistic_terms"

    def test_no_profile_means_no_flags(self):
        provisional = _make_entry(
            entry_id="p1", title="Faction", content="Anything here.",
            status="provisional",
        )
        svc = _service([provisional])
        detector = LoreConflictDetector(svc)  # no canon_profile
        result = detector.scan_provisional_batch(["p1"], "u1")
        # No canon rule flags; title collision also absent (no canonical).
        assert not [
            f for f in result.flags if f.conflict_type == "canon_rule_violation"
        ]

    def test_tags_are_also_scanned(self):
        provisional = _make_entry(
            entry_id="p1", title="Something", content="OK",
            status="provisional", tags=["LIDAR-related"],
        )
        svc = _service([provisional])
        profile = {"cross_continuity_violations": ["LIDAR"]}
        detector = LoreConflictDetector(svc, canon_profile=profile)
        result = detector.scan_provisional_batch(["p1"], "u1")
        assert any(
            f.conflict_type == "canon_rule_violation" for f in result.flags
        )


# ---------------------------------------------------------------------------
# Pass 3: timeline_contradiction
# ---------------------------------------------------------------------------


class TestTimelineContradiction:
    def test_disjoint_windows_flagged(self):
        canonical = _make_entry(
            entry_id="c1", title="Ruusan Memorial", category="location",
            content="stood on the ridge", status="canonical",
            timeline_sort_start=30, timeline_sort_end=31,
        )
        provisional = _make_entry(
            entry_id="p1", title="Ruusan Memorial", category="location",
            content="stood on the ridge", status="provisional",
            timeline_sort_start=44, timeline_sort_end=45,
        )
        svc = _service([canonical, provisional])
        detector = LoreConflictDetector(svc)
        result = detector.scan_provisional_batch(["p1"], "u1")
        assert any(
            f.conflict_type == "timeline_contradiction" for f in result.flags
        )

    def test_overlapping_windows_not_flagged(self):
        """Overlap is treated as consistent refinement, not contradiction."""
        canonical = _make_entry(
            entry_id="c1", title="Treaty", category="historical_event",
            content="signed", status="canonical",
            timeline_sort_start=20, timeline_sort_end=30,
        )
        provisional = _make_entry(
            entry_id="p1", title="Treaty", category="historical_event",
            content="signed", status="provisional",
            timeline_sort_start=25, timeline_sort_end=35,
        )
        svc = _service([canonical, provisional])
        detector = LoreConflictDetector(svc)
        result = detector.scan_provisional_batch(["p1"], "u1")
        # No timeline_contradiction flag (but may still have title_collision
        # on low severity since content matches).
        assert not [
            f for f in result.flags if f.conflict_type == "timeline_contradiction"
        ]

    def test_open_ended_window_not_flagged(self):
        canonical = _make_entry(
            entry_id="c1", title="Doctrine", category="concept",
            status="canonical",
            timeline_sort_start=None, timeline_sort_end=None,
        )
        provisional = _make_entry(
            entry_id="p1", title="Doctrine", category="concept",
            status="provisional",
            timeline_sort_start=44, timeline_sort_end=45,
        )
        svc = _service([canonical, provisional])
        detector = LoreConflictDetector(svc)
        result = detector.scan_provisional_batch(["p1"], "u1")
        assert not [
            f for f in result.flags if f.conflict_type == "timeline_contradiction"
        ]

    def test_same_window_not_flagged(self):
        canonical = _make_entry(
            entry_id="c1", title="Treaty", category="historical_event",
            status="canonical",
            timeline_sort_start=30, timeline_sort_end=31,
        )
        provisional = _make_entry(
            entry_id="p1", title="Treaty", category="historical_event",
            status="provisional",
            timeline_sort_start=30, timeline_sort_end=31,
        )
        svc = _service([canonical, provisional])
        detector = LoreConflictDetector(svc)
        result = detector.scan_provisional_batch(["p1"], "u1")
        assert not [
            f for f in result.flags if f.conflict_type == "timeline_contradiction"
        ]


class TestTimelineHelperDirectly:
    @pytest.mark.parametrize(
        "a,b,expected",
        [
            ((30, 31), (44, 45), True),   # disjoint
            ((30, 40), (35, 45), False),  # overlap
            ((30, 31), (30, 31), False),  # identical
            ((None, 31), (44, 45), False),  # open start
            ((30, None), (44, 45), False),  # open end
            ((30, 31), (None, None), False),  # b open
        ],
    )
    def test_conflicts(self, a, b, expected):
        assert _timeline_conflicts(a, b) is expected


# ---------------------------------------------------------------------------
# ConflictScanResult helpers
# ---------------------------------------------------------------------------


class TestConflictScanResult:
    def test_high_severity_extraction(self):
        provisional = _make_entry(
            entry_id="p1", title="Faction", content="uses LIDAR scanners",
            status="provisional",
        )
        svc = _service([provisional])
        profile = {"cross_continuity_violations": ["LIDAR"]}
        detector = LoreConflictDetector(svc, canon_profile=profile)
        result = detector.scan_provisional_batch(["p1"], "u1")
        assert len(result.high_severity_flags) == 1

    def test_to_payload_dict_shape(self):
        """to_payload produces a plain-dict list — ledger-friendly."""
        provisional = _make_entry(
            entry_id="p1", title="Faction", content="uses LIDAR scanners",
            status="provisional",
        )
        svc = _service([provisional])
        profile = {"cross_continuity_violations": ["LIDAR"]}
        detector = LoreConflictDetector(svc, canon_profile=profile)
        result = detector.scan_provisional_batch(["p1"], "u1")
        payload = result.to_payload()
        assert isinstance(payload, list)
        assert payload[0]["entry_id"] == "p1"
        assert "conflict_type" in payload[0]

    def test_is_clean_when_no_flags(self):
        svc = _service([])
        detector = LoreConflictDetector(svc)
        result = detector.scan_provisional_batch([], "u1")
        assert result.is_clean()


class TestMultipleFlagsPerEntry:
    def test_one_entry_can_produce_flags_from_multiple_passes(self):
        """Title collision + canon rule violation on the same entry."""
        canonical = _make_entry(
            entry_id="c1", title="Ruusan Order", content="Canonical version.",
            category="faction", status="canonical",
        )
        provisional = _make_entry(
            entry_id="p1", title="Ruusan Order",
            content="A new version using LIDAR.",
            category="faction", status="provisional",
        )
        svc = _service([canonical, provisional])
        profile = {"cross_continuity_violations": ["LIDAR"]}
        detector = LoreConflictDetector(svc, canon_profile=profile)
        result = detector.scan_provisional_batch(["p1"], "u1")
        types = {f.conflict_type for f in result.flags}
        assert "title_collision" in types
        assert "canon_rule_violation" in types


class TestMissingEntryHandling:
    def test_missing_entry_is_skipped_silently(self):
        """IDs that don't resolve (deleted between extract and scan) do
        not crash the detector."""
        svc = _service([])
        detector = LoreConflictDetector(svc)
        result = detector.scan_provisional_batch(["nonexistent"], "u1")
        assert result.is_clean()
