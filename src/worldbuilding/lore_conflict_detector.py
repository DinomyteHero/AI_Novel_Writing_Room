"""Phase 7.2 — lore conflict detector.

Runs a small, deterministic battery of checks over freshly-extracted
provisional lore entries and flags anything that contradicts established
canonical lore or the project's canon_profile. Advisory-by-default per
Decision D3 in the Phase 6/7 plan; callers opt in to strict mode by
treating severity=high flags as blocking.

Three detection passes (all independent — a single provisional entry can
produce flags from multiple passes):

1. ``title_collision`` — a provisional entry whose ``(category, title)``
   pair already exists in the same universe as a canonical entry with
   different content. Near-match titles (case-insensitive, whitespace-
   normalized, punctuation-stripped) are also flagged at medium severity.
2. ``canon_rule_violation`` — the provisional entry's content or tags
   reference a term listed in ``canon_profile.cross_continuity_violations``
   or ``canon_profile.anachronistic_terms``. These are the same strings
   the canon_expert agent flags in-prose — we catch them here too so the
   lore store doesn't quietly drift.
3. ``timeline_contradiction`` — the provisional entry's ``(valid_from,
   valid_until)`` window overlaps with a canonical entry that shares the
   same ``(category, title)`` but has a different time window. Missing
   timeline values are not flagged (many entries are era-agnostic).

The detector is a pure-Python class with no I/O; it reads from a
LoreService that exposes ``list_lore_entries`` and ``get_lore_entry``.
Tests mock the service. Production invocation happens in the orchestrator
after ``extract_worldbuilding_from_chapter`` returns new entry IDs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.worldbuilding.lore_service import LoreService

logger = logging.getLogger(__name__)


_SEVERITY_LEVELS = ("high", "medium", "low")


@dataclass
class ConflictFlag:
    """A single lore conflict flag.

    Emitted to the run ledger and exposed to callers verbatim. Stable
    shape so downstream consumers (ChapterGateCritic, promote_lore.py,
    eventual UI) can rely on field names.
    """

    entry_id: str
    conflict_type: str
    severity: str
    rationale: str
    target_entry_id: Optional[str] = None
    canon_rule: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "conflict_type": self.conflict_type,
            "severity": self.severity,
            "rationale": self.rationale,
            "target_entry_id": self.target_entry_id,
            "canon_rule": self.canon_rule,
        }


@dataclass
class ConflictScanResult:
    """Structured scan output with convenient helpers."""

    flags: list[ConflictFlag] = field(default_factory=list)

    @property
    def high_severity_flags(self) -> list[ConflictFlag]:
        return [f for f in self.flags if f.severity == "high"]

    def to_payload(self) -> list[dict]:
        """Serialize for ledger / JSON emission."""
        return [f.to_dict() for f in self.flags]

    def is_clean(self) -> bool:
        return not self.flags


def _normalize_title(title: str) -> str:
    """Case-insensitive, whitespace-normalized, punctuation-stripped form.

    Used for near-match title collisions. ``"The Jedi Council"``,
    ``"jedi council"``, and ``"The  Jedi  Council."`` all normalize to
    ``"jedi council"`` (leading articles are NOT stripped — see tests).
    """
    lowered = title.lower().strip()
    no_punct = re.sub(r"[^\w\s]", "", lowered)
    collapsed = re.sub(r"\s+", " ", no_punct)
    return collapsed.strip()


class LoreConflictDetector:
    """Three-pass detector for provisional lore conflicts.

    Usage:
        detector = LoreConflictDetector(lore_service, canon_profile=profile)
        result = detector.scan_provisional_batch(
            entry_ids=new_entry_ids, universe_id=universe_id,
        )
        for flag in result.flags:
            ...  # log / block / ignore
    """

    def __init__(
        self,
        lore_service: "LoreService",
        canon_profile: Optional[dict] = None,
    ) -> None:
        self.lore_service = lore_service
        self.canon_profile = canon_profile or {}
        # Pre-compute lowercase needle lists so each pass doesn't repeat.
        self._cross_continuity_needles: list[str] = [
            v.lower()
            for v in (self.canon_profile.get("cross_continuity_violations") or [])
            if isinstance(v, str) and v.strip()
        ]
        anachronistic = self.canon_profile.get("anachronistic_terms") or {}
        if isinstance(anachronistic, dict):
            self._anachronistic_needles: list[str] = [
                k.lower() for k in anachronistic.keys() if isinstance(k, str)
            ]
        else:
            self._anachronistic_needles = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scan_provisional_batch(
        self,
        entry_ids: list[str],
        universe_id: str,
    ) -> ConflictScanResult:
        """Run all three detection passes across the given provisional IDs.

        Each pass is independent; a single entry may produce multiple
        flags. Missing entries (deleted between extraction and scan) are
        skipped silently.
        """
        if not entry_ids:
            return ConflictScanResult()

        canonical_cache = self._load_canonical_cache(universe_id)
        flags: list[ConflictFlag] = []

        for entry_id in entry_ids:
            entry = self._load_entry(entry_id)
            if entry is None:
                logger.debug("skip scan: entry %s not found", entry_id)
                continue

            flags.extend(self._check_title_collision(entry, canonical_cache))
            flags.extend(self._check_canon_rule_violation(entry))
            flags.extend(self._check_timeline_contradiction(entry, canonical_cache))

        return ConflictScanResult(flags=flags)

    # ------------------------------------------------------------------
    # Individual detection passes
    # ------------------------------------------------------------------

    def _check_title_collision(
        self, entry: dict, canonical_cache: list[dict]
    ) -> list[ConflictFlag]:
        entry_id = entry["entry_id"]
        category = entry.get("category")
        title_norm = _normalize_title(entry.get("title", ""))
        if not title_norm:
            return []
        out: list[ConflictFlag] = []
        for canonical in canonical_cache:
            if canonical["entry_id"] == entry_id:
                continue
            if canonical.get("category") != category:
                continue
            canonical_norm = _normalize_title(canonical.get("title", ""))
            if not canonical_norm:
                continue
            if canonical_norm == title_norm:
                # Exact-after-normalization collision: high severity only if
                # the two entries have different content. Same content = a
                # benign duplicate extraction.
                entry_content = (entry.get("content") or "").strip()
                canon_content = (canonical.get("content") or "").strip()
                severity = "high" if entry_content != canon_content else "low"
                rationale = (
                    f"Provisional entry title '{entry.get('title')}' "
                    f"collides with canonical entry "
                    f"'{canonical.get('title')}' (normalized equal; "
                    f"content {'differs' if severity == 'high' else 'matches'})."
                )
                out.append(
                    ConflictFlag(
                        entry_id=entry_id,
                        conflict_type="title_collision",
                        severity=severity,
                        rationale=rationale,
                        target_entry_id=canonical["entry_id"],
                    )
                )
        return out

    def _check_canon_rule_violation(
        self, entry: dict
    ) -> list[ConflictFlag]:
        haystack = " ".join(
            str(v) for v in (
                entry.get("title", ""),
                entry.get("content", ""),
                " ".join(entry.get("tags") or [])
                if isinstance(entry.get("tags"), list)
                else str(entry.get("tags") or ""),
            )
        ).lower()
        if not haystack.strip():
            return []
        entry_id = entry["entry_id"]
        out: list[ConflictFlag] = []
        for needle in self._cross_continuity_needles:
            if needle in haystack:
                out.append(
                    ConflictFlag(
                        entry_id=entry_id,
                        conflict_type="canon_rule_violation",
                        severity="high",
                        rationale=(
                            f"Provisional entry references "
                            f"'{needle}', which canon_profile."
                            f"cross_continuity_violations lists as "
                            f"off-limits for this continuity."
                        ),
                        canon_rule="cross_continuity_violations",
                    )
                )
        for needle in self._anachronistic_needles:
            if needle in haystack:
                out.append(
                    ConflictFlag(
                        entry_id=entry_id,
                        conflict_type="canon_rule_violation",
                        severity="medium",
                        rationale=(
                            f"Provisional entry uses anachronistic term "
                            f"'{needle}' — see canon_profile."
                            f"anachronistic_terms for the in-universe "
                            f"replacement."
                        ),
                        canon_rule="anachronistic_terms",
                    )
                )
        return out

    def _check_timeline_contradiction(
        self, entry: dict, canonical_cache: list[dict]
    ) -> list[ConflictFlag]:
        entry_id = entry["entry_id"]
        category = entry.get("category")
        title_norm = _normalize_title(entry.get("title", ""))
        if not title_norm:
            return []
        entry_start = _as_int(entry.get("timeline_sort_start"))
        entry_end = _as_int(entry.get("timeline_sort_end"))
        if entry_start is None and entry_end is None:
            return []
        out: list[ConflictFlag] = []
        for canonical in canonical_cache:
            if canonical["entry_id"] == entry_id:
                continue
            if canonical.get("category") != category:
                continue
            if _normalize_title(canonical.get("title", "")) != title_norm:
                continue
            canon_start = _as_int(canonical.get("timeline_sort_start"))
            canon_end = _as_int(canonical.get("timeline_sort_end"))
            if canon_start is None and canon_end is None:
                continue
            if _timeline_conflicts(
                (entry_start, entry_end), (canon_start, canon_end)
            ):
                out.append(
                    ConflictFlag(
                        entry_id=entry_id,
                        conflict_type="timeline_contradiction",
                        severity="medium",
                        rationale=(
                            f"Provisional timeline window "
                            f"[{entry_start}, {entry_end}] conflicts with "
                            f"canonical window "
                            f"[{canon_start}, {canon_end}] for the same "
                            f"{category} '{entry.get('title')}'."
                        ),
                        target_entry_id=canonical["entry_id"],
                    )
                )
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_canonical_cache(self, universe_id: str) -> list[dict]:
        """Pull the full canonical-entries list for this universe once.

        Small enough (O(hundreds) in practice) to compare in-memory for a
        typical scan. If volume grows an order of magnitude, swap for
        per-category / per-title-prefix queries.
        """
        try:
            return self.lore_service.db.list_lore_entries(
                universe_id=universe_id, status="canonical"
            )
        except AttributeError:
            # Tests may pass a mock without .db; accept list_lore_entries
            # directly on the service object as a back-compat escape.
            lister = getattr(self.lore_service, "list_lore_entries", None)
            if callable(lister):
                return lister(universe_id=universe_id, status="canonical")
            logger.warning(
                "lore_service has no .db.list_lore_entries; skipping cache"
            )
            return []

    def _load_entry(self, entry_id: str) -> Optional[dict]:
        try:
            return self.lore_service.db.get_lore_entry(entry_id)
        except AttributeError:
            getter = getattr(self.lore_service, "get_lore_entry", None)
            if callable(getter):
                return getter(entry_id)
            return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _timeline_conflicts(
    a: tuple[Optional[int], Optional[int]],
    b: tuple[Optional[int], Optional[int]],
) -> bool:
    """Return True when two timeline windows plausibly contradict.

    Either window may have an open start (None) or open end (None). The
    detector flags when both windows are bounded AND the windows are
    distinct but non-overlapping (e.g. provisional says 44 ABY-45 ABY and
    canonical says 30 ABY-31 ABY — same titled entity, different era →
    probably a contradiction).
    """
    a_start, a_end = a
    b_start, b_end = b
    # Open-ended windows: only flag when both endpoints are set.
    if None in (a_start, a_end, b_start, b_end):
        return False
    # Identical windows: not a conflict.
    if a_start == b_start and a_end == b_end:
        return False
    # Overlapping windows: treat as consistent refinement, not conflict.
    if a_start <= b_end and b_start <= a_end:
        return False
    # Non-overlapping, non-identical windows on the same title/category:
    # flag as a timeline contradiction.
    return True
