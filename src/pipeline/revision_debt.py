"""Slice 2 revision-debt store.

SQLite-backed store for structured advisories emitted by the pipeline. Every
advisory-producing stage (CanonExpert, GateCritic, FinalGate, MetricsDashboard,
PresenceChecker near-misses, compression guard, word-count telemetry,
StateFirewall, SceneReviewer) writes a row here via a wrapper in
``src/pipeline/revision_debt_producers.py``. The orchestrator never calls
``add`` directly.

Invariants (spec \u00a76.2):

- The ``category`` enum is closed. ``add`` raises ``ValueError`` on unknown
  categories so silent drift cannot land.
- ``severity`` is one of ``{low, medium, high}``.
- ``status`` is one of ``{open, deferred, resolved, overruled}``; new rows
  default to ``open``.
- ``owner_or_reviewer_notes`` is human-only \u2014 the ``add`` path refuses it.
- Every ``add`` returns a stable ``debt_id``. Callers may pre-supply one; when
  omitted the store mints ``debt_{YYYYMMDDhhmmss}_{shorthash}``.

Separate file from ``story_state.db`` so its migration surface stays stable
(spec \u00a76.2.3).
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)


# Closed category set. Mirrors schemas/revision_debt.json. Adding a new
# category requires bumping the schema AND this constant in the same change.
CATEGORIES: frozenset[str] = frozenset({
    "canon",
    "canon_fix_rejected",
    "editorial.gate_advisory",
    "editorial.final_gate_advisory",
    "editorial.scene_reviewer",
    "editorial.other",
    "editorial.canon_polish_drift",
    "metric",
    "presence_near_miss",
    "blocker_record",
    "wordcount_drift",
    "compression_advisory",
    "prose.rhythm.em_dash_overuse",
    "prose.rhythm.staccato_cluster",
    "prose.rhythm.opener_monotone",
    "prose.rhythm.dialogue_starved",
    "prose.rhythm.abstract_tic",
    "prose.continuity.character_state_break",
    "prose.continuity.location_break",
    "prose.continuity.object_location_break",
})

SEVERITIES: frozenset[str] = frozenset({"low", "medium", "high"})
STATUSES: frozenset[str] = frozenset({"open", "deferred", "resolved", "overruled"})
FIX_SCOPES: frozenset[str] = frozenset({"local", "scene", "chapter", "manuscript"})
SCOPE_LEVELS: frozenset[str] = frozenset({"scene", "chapter", "act", "manuscript"})


class RevisionDebtStore:
    """SQLite-backed revision-debt store.

    Expected path: ``output/<franchise>/<book>/state/revision_debt.db``. The
    orchestrator constructs one store per run via ``ProjectPaths``. Tests can
    point at ``:memory:`` for isolation.
    """

    def __init__(self, *, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self._create_table()

    def _create_table(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS revision_debt (
                debt_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                producer TEXT NOT NULL,
                scope TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                summary TEXT,
                details TEXT,
                fix_scope TEXT,
                status TEXT NOT NULL,
                resolved_at TEXT,
                resolution_notes TEXT,
                owner_or_reviewer_notes TEXT
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_revision_debt_status ON revision_debt(status)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_revision_debt_category ON revision_debt(category)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_revision_debt_scope ON revision_debt(scope)"
        )
        self.conn.commit()

    # ------------------------------------------------------------------ add
    def add(self, entry: Mapping[str, Any]) -> str:
        """Insert one debt row. Returns the ``debt_id``.

        Enforces the closed category enum + required fields. Raises
        ``ValueError`` on category/severity/status drift so silent bugs cannot
        land.
        """
        producer = entry.get("producer")
        if not producer:
            raise ValueError("RevisionDebtStore.add: missing 'producer'")

        scope = entry.get("scope")
        if not isinstance(scope, Mapping) or "level" not in scope:
            raise ValueError(
                "RevisionDebtStore.add: 'scope' must be a mapping with 'level'"
            )
        if scope["level"] not in SCOPE_LEVELS:
            raise ValueError(
                f"RevisionDebtStore.add: scope.level={scope['level']!r} "
                f"not in {sorted(SCOPE_LEVELS)}"
            )

        category = entry.get("category")
        if category not in CATEGORIES:
            raise ValueError(
                f"RevisionDebtStore.add: unknown category {category!r}. "
                f"Closed set: {sorted(CATEGORIES)}. Bump schemas/revision_debt.json "
                "and src/pipeline/revision_debt.py CATEGORIES together."
            )

        severity = entry.get("severity")
        if severity not in SEVERITIES:
            raise ValueError(
                f"RevisionDebtStore.add: severity={severity!r} not in {sorted(SEVERITIES)}"
            )

        status = entry.get("status", "open")
        if status not in STATUSES:
            raise ValueError(
                f"RevisionDebtStore.add: status={status!r} not in {sorted(STATUSES)}"
            )

        fix_scope = entry.get("fix_scope")
        if fix_scope is not None and fix_scope not in FIX_SCOPES:
            raise ValueError(
                f"RevisionDebtStore.add: fix_scope={fix_scope!r} not in {sorted(FIX_SCOPES)}"
            )

        if "owner_or_reviewer_notes" in entry:
            # Spec \u00a76.2.1: human-only field. Refuse on write.
            raise ValueError(
                "RevisionDebtStore.add: 'owner_or_reviewer_notes' is a human-only "
                "field and must not be populated by agents or producers."
            )

        created_at = entry.get("created_at") or datetime.now(timezone.utc).isoformat()
        details = entry.get("details") or {}
        summary = entry.get("summary", "")

        debt_id = entry.get("debt_id") or self._mint_id(
            producer=producer, scope=scope, category=category, summary=summary
        )

        self.conn.execute(
            """
            INSERT INTO revision_debt (
                debt_id, created_at, producer, scope, category, severity,
                summary, details, fix_scope, status, resolved_at,
                resolution_notes, owner_or_reviewer_notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
            """,
            (
                debt_id,
                created_at,
                producer,
                json.dumps(dict(scope), sort_keys=True),
                category,
                severity,
                summary,
                json.dumps(details, sort_keys=True),
                fix_scope,
                status,
            ),
        )
        self.conn.commit()
        return debt_id

    # --------------------------------------------------------------- list
    def list_open(self, *, scope: Mapping[str, Any] | None = None) -> list[dict]:
        return self._list(status_filter=("open",), scope_filter=scope)

    def list_by_status(
        self, *, statuses: Iterable[str], scope: Mapping[str, Any] | None = None,
    ) -> list[dict]:
        return self._list(status_filter=tuple(statuses), scope_filter=scope)

    def list_all(self) -> list[dict]:
        return self._list(status_filter=None, scope_filter=None)

    def list_for_chapter(self, chapter_number: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM revision_debt ORDER BY created_at"
        ).fetchall()
        hits: list[dict] = []
        for row in rows:
            hydrated = self._row_to_dict(row)
            sc = hydrated.get("scope", {})
            if sc.get("chapter_number") == chapter_number:
                hits.append(hydrated)
        return hits

    def _list(
        self,
        *,
        status_filter: tuple[str, ...] | None,
        scope_filter: Mapping[str, Any] | None,
    ) -> list[dict]:
        query = "SELECT * FROM revision_debt"
        where: list[str] = []
        params: list[Any] = []
        if status_filter:
            placeholders = ",".join(["?"] * len(status_filter))
            where.append(f"status IN ({placeholders})")
            params.extend(status_filter)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at"
        rows = self.conn.execute(query, params).fetchall()

        results = [self._row_to_dict(r) for r in rows]
        if scope_filter is None:
            return results

        def matches(entry: dict) -> bool:
            sc = entry.get("scope", {})
            for k, v in scope_filter.items():
                if sc.get(k) != v:
                    return False
            return True

        return [r for r in results if matches(r)]

    # -------------------------------------------------------------- update
    def update_status(
        self,
        debt_id: str,
        *,
        status: str,
        resolution_notes: str | None = None,
    ) -> dict:
        """Transition a debt row. Returns ``{old_status, new_status}`` \u2014 the
        orchestrator emits ``revision_debt_updated`` with this payload.
        """
        if status not in STATUSES:
            raise ValueError(
                f"RevisionDebtStore.update_status: status={status!r} not in {sorted(STATUSES)}"
            )
        row = self.conn.execute(
            "SELECT status FROM revision_debt WHERE debt_id = ?", (debt_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"RevisionDebtStore.update_status: no row {debt_id!r}")
        old_status = row["status"]

        resolved_at = None
        if status in ("resolved", "overruled"):
            resolved_at = datetime.now(timezone.utc).isoformat()

        self.conn.execute(
            """
            UPDATE revision_debt
               SET status = ?, resolved_at = ?, resolution_notes = ?
             WHERE debt_id = ?
            """,
            (status, resolved_at, resolution_notes, debt_id),
        )
        self.conn.commit()
        return {"old_status": old_status, "new_status": status}

    def set_owner_notes(self, debt_id: str, *, notes: str) -> None:
        """Human-only setter for ``owner_or_reviewer_notes`` (CLI path)."""
        cursor = self.conn.execute(
            "UPDATE revision_debt SET owner_or_reviewer_notes = ? WHERE debt_id = ?",
            (notes, debt_id),
        )
        if cursor.rowcount == 0:
            raise KeyError(f"RevisionDebtStore.set_owner_notes: no row {debt_id!r}")
        self.conn.commit()

    # -------------------------------------------------------------- summaries
    def summarize_for_chapter(self, chapter_number: int) -> dict:
        rows = self.list_for_chapter(chapter_number)
        return self._summarize(rows)

    def summarize_for_book(self) -> dict:
        rows = self.list_all()
        return self._summarize(rows)

    @staticmethod
    def _summarize(rows: list[dict]) -> dict:
        counts_by_category: dict[str, int] = {}
        counts_by_severity: dict[str, int] = {}
        open_ids: list[str] = []
        for row in rows:
            counts_by_category[row["category"]] = counts_by_category.get(row["category"], 0) + 1
            counts_by_severity[row["severity"]] = counts_by_severity.get(row["severity"], 0) + 1
            if row["status"] == "open":
                open_ids.append(row["debt_id"])
        return {
            "counts_by_category": counts_by_category,
            "counts_by_severity": counts_by_severity,
            "open_debt_ids": open_ids,
        }

    # -------------------------------------------------------------- helpers
    def get(self, debt_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM revision_debt WHERE debt_id = ?", (debt_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["scope"] = json.loads(d["scope"]) if d.get("scope") else {}
        d["details"] = json.loads(d["details"]) if d.get("details") else {}
        return d

    def _mint_id(
        self, *, producer: str, scope: Mapping[str, Any], category: str, summary: str,
    ) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        basis = f"{producer}|{json.dumps(dict(scope), sort_keys=True)}|{category}|{summary}"
        h = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:8]
        return f"debt_{ts}_{h}"

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "RevisionDebtStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = [
    "CATEGORIES",
    "SEVERITIES",
    "STATUSES",
    "FIX_SCOPES",
    "SCOPE_LEVELS",
    "RevisionDebtStore",
]
