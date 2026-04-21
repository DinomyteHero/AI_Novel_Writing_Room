"""Slice 4 continuity event log.

Trusted log of "what happened" events extracted from saved prose. The store
is dumb: it just persists rows that the extractor has *already* threshold-
filtered. Suppressed (low-confidence) events never reach this store \u2014
suppression is the orchestrator's job so hallucinated facts cannot poison
the packet.

See ``docs/architecture/architecture_upgrade_spec.md`` \u00a78.

Trust model (spec \u00a78.1 + \u00a78.3):

- Only five narrow event types are valid: ``location_change``, ``injury_state``,
  ``possession``, ``revelation``, ``status_change``. ``append`` rejects
  anything else so silent type drift cannot land.
- ``human_verified`` is a human-only bit. The extractor never sets it true.
  CLI / review workflows flip it via ``mark_human_verified``.
- Redaction is soft (``redacted=true`` with ``redacted_reason``) so audit
  trails stay intact and suppressed context cannot re-surface via the packet.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)


EVENT_TYPES: frozenset[str] = frozenset({
    "location_change",
    "injury_state",
    "possession",
    "revelation",
    "status_change",
})

_SCENE_ID_RE = re.compile(r"^ch(\d{2})_sc(\d{2})$")

DEFAULT_MIN_CONFIDENCE = 0.85


def _parse_scene_id(scene_id: str) -> tuple[int, int] | None:
    if not isinstance(scene_id, str):
        return None
    m = _SCENE_ID_RE.match(scene_id)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContinuityLog:
    """SQLite-backed store for trusted continuity events.

    Expected path: ``output/<franchise>/<book>/state/continuity_log.db``. One
    row per event. The store scans linearly (table stays O(n) per scene, tens
    to low hundreds of rows per book); a composite index on
    ``(scene_id, event_type, subject)`` supports the per-subject lookups.
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
            CREATE TABLE IF NOT EXISTS continuity_events (
                event_id TEXT PRIMARY KEY,
                scene_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                details TEXT NOT NULL,
                confidence REAL NOT NULL,
                extractor_version TEXT NOT NULL,
                human_verified INTEGER NOT NULL DEFAULT 0,
                redacted INTEGER NOT NULL DEFAULT 0,
                redacted_reason TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cont_scene "
            "ON continuity_events(scene_id, event_type, subject)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cont_subject "
            "ON continuity_events(subject)"
        )
        self.conn.commit()

    # ------------------------------------------------------------------ writes
    def append(self, event: Mapping[str, Any]) -> str:
        """Insert one event. Returns the stable ``event_id``.

        Raises ``ValueError`` on unknown ``event_type`` (closed set),
        unparseable ``scene_id``, or missing required fields.
        """
        event_type = event.get("event_type")
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"ContinuityLog.append: unknown event_type={event_type!r}. "
                f"Closed set: {sorted(EVENT_TYPES)}. Bump "
                "schemas/continuity_event.json and src/memory/continuity_log.py "
                "EVENT_TYPES together."
            )
        scene_id = event.get("scene_id")
        if _parse_scene_id(scene_id) is None:
            raise ValueError(
                f"ContinuityLog.append: scene_id={scene_id!r} must match chNN_scMM"
            )
        subject = event.get("subject")
        if not subject:
            raise ValueError("ContinuityLog.append: 'subject' is required")
        details = event.get("details")
        if not isinstance(details, Mapping):
            raise ValueError("ContinuityLog.append: 'details' must be an object")
        confidence = event.get("confidence")
        if not isinstance(confidence, (int, float)) or not (0.0 <= float(confidence) <= 1.0):
            raise ValueError(
                "ContinuityLog.append: 'confidence' must be a number in [0, 1]"
            )
        extractor_version = event.get("extractor_version")
        if not extractor_version:
            raise ValueError("ContinuityLog.append: 'extractor_version' is required")

        event_id = event.get("event_id") or self._mint_id(
            scene_id=scene_id, event_type=event_type, subject=subject,
            details=details,
        )
        created_at = event.get("created_at") or _iso_now()

        self.conn.execute(
            """
            INSERT OR REPLACE INTO continuity_events (
                event_id, scene_id, event_type, subject, details, confidence,
                extractor_version, human_verified, redacted, redacted_reason,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                scene_id,
                event_type,
                subject,
                json.dumps(dict(details), sort_keys=True),
                float(confidence),
                extractor_version,
                1 if event.get("human_verified") else 0,
                1 if event.get("redacted") else 0,
                event.get("redacted_reason"),
                created_at,
            ),
        )
        self.conn.commit()
        return event_id

    def append_many(self, events: Iterable[Mapping[str, Any]]) -> list[str]:
        return [self.append(e) for e in events]

    def mark_human_verified(self, event_id: str) -> None:
        row = self.conn.execute(
            "SELECT 1 FROM continuity_events WHERE event_id = ?", (event_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"ContinuityLog.mark_human_verified: no event {event_id!r}")
        self.conn.execute(
            "UPDATE continuity_events SET human_verified = 1 WHERE event_id = ?",
            (event_id,),
        )
        self.conn.commit()

    def redact(self, event_id: str, *, reason: str) -> None:
        """Soft-delete: mark redacted with a reason. Row stays on disk so
        the audit trail is preserved; read-paths filter redacted rows out."""
        row = self.conn.execute(
            "SELECT 1 FROM continuity_events WHERE event_id = ?", (event_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"ContinuityLog.redact: no event {event_id!r}")
        self.conn.execute(
            "UPDATE continuity_events SET redacted = 1, redacted_reason = ? "
            "WHERE event_id = ?",
            (reason, event_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------------- reads
    def get(self, event_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM continuity_events WHERE event_id = ?", (event_id,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_all(self, *, include_redacted: bool = False) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM continuity_events ORDER BY scene_id, event_id"
        ).fetchall()
        return [
            self._row_to_dict(r)
            for r in rows
            if include_redacted or not r["redacted"]
        ]

    def events_for_chapter(self, chapter_number: int) -> list[dict]:
        """Overlay-facing read. Returns events for scenes in the chapter
        plus carry-over events from earlier chapters still relevant
        (location_change and possession states propagate forward).
        """
        prefix = f"ch{int(chapter_number):02d}_"
        rows = self.conn.execute(
            "SELECT * FROM continuity_events WHERE redacted = 0 "
            "ORDER BY scene_id, event_id"
        ).fetchall()
        out: list[dict] = []
        for r in rows:
            scene = r["scene_id"] or ""
            if scene.startswith(prefix):
                out.append(self._row_to_dict(r))
                continue
            # Events from earlier chapters propagate when they describe
            # stateful changes that a later scene must not contradict.
            parsed = _parse_scene_id(scene)
            if parsed is None:
                continue
            if parsed[0] < chapter_number and r["event_type"] in (
                "location_change", "possession", "injury_state", "status_change",
            ):
                out.append(self._row_to_dict(r))
        return out

    # Alias matching spec §8.5 phrasing.
    list_relevant_to_chapter = events_for_chapter

    def list_events_for_subject(
        self, subject: str, *, before_scene: str | None = None,
    ) -> list[dict]:
        """All non-redacted events where ``subject`` matches; optionally
        bounded to scenes strictly before ``before_scene`` (for continuity
        lookups when drafting a new scene).
        """
        rows = self.conn.execute(
            "SELECT * FROM continuity_events WHERE subject = ? AND redacted = 0 "
            "ORDER BY scene_id, event_id",
            (subject,),
        ).fetchall()
        out = [self._row_to_dict(r) for r in rows]
        if before_scene is None:
            return out
        anchor = _parse_scene_id(before_scene)
        if anchor is None:
            return out
        filtered: list[dict] = []
        for ev in out:
            s = _parse_scene_id(ev["scene_id"])
            if s is None:
                continue
            if s < anchor:
                filtered.append(ev)
        return filtered

    def count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM continuity_events WHERE redacted = 0"
        ).fetchone()
        return int(row["n"] if row else 0)

    # -------------------------------------------------------------- helpers
    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["details"] = json.loads(d["details"] or "{}")
        d["human_verified"] = bool(d["human_verified"])
        d["redacted"] = bool(d["redacted"])
        return d

    def _mint_id(
        self, *, scene_id: str, event_type: str, subject: str,
        details: Mapping[str, Any],
    ) -> str:
        basis = f"{scene_id}|{event_type}|{subject}|{json.dumps(dict(details), sort_keys=True)}"
        h = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]
        return f"evt_{h}"

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ContinuityLog":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = [
    "EVENT_TYPES",
    "DEFAULT_MIN_CONFIDENCE",
    "ContinuityLog",
]
