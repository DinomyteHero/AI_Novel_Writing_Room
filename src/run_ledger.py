"""Append-only run ledger for pipeline events.

Every step in the pipeline emits a typed event to this ledger.
SQLite-backed, queryable, provides the audit trail for the pipeline.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# Valid event types from the design doc
EVENT_TYPES = [
    "pipeline_start",
    "chapter_start",
    "agent_start",
    "agent_complete",
    "gate_pass",
    "gate_fail",
    # Final Gate / Quality Polish events (Phase 1 pipeline redesign)
    "final_gate_complete",
    "final_gate_rejection",
    "compression_guard_fired",
    "state_diff_proposed",
    "state_diff_committed",
    "milestone_reached",
    "milestone_gate_paused",
    "pipeline_complete",
    "contradiction_scan",
    "summarizer_complete",
    # Phase 4 event types:
    "physics_validation_pre",
    "physics_validation_post",
    "judge_evaluation",
    "session_save",
    "session_resume",
    "outline_generated",
    "export_complete",
    # Relay refactor Stage 1f: save-blocker / continuity-editor events
    "continuity_editor_complete",
    "save_blocked",
    "pov_advisory",
    "presence_check_error",
    # Relay refactor Stage 1h: chapter-level word-count telemetry
    "chapter_word_count_telemetry",
    # Relay refactor Stage 3: LineWriter telemetry
    "line_writer_error",
    "line_writer_collapsed",
    # Architecture upgrade Slice 1: state firewall + Phase 0 audit.
    # Payload shapes are documented in docs/architecture/architecture_upgrade_spec.md §11.4.
    "scene_isolated",          # error — StateFirewall isolates a scene
    "gap_note_recorded",       # warn  — gap row written to SQLite
    "phase0_audit_emitted",    # info  — audit_phase0.py completed
]


class RunLedger:
    """Append-only event log for pipeline execution."""

    def __init__(self, db_path: str = "output/_fallback/run_ledger.db", run_id: str | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self._create_table()
        self._migrate_schema()

    def _create_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS run_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                run_id TEXT,
                event_type TEXT NOT NULL,
                chapter_number INTEGER,
                scene_number INTEGER,
                attempt_id TEXT,
                agent_role TEXT,
                payload TEXT,
                state_hash TEXT
            )
        """)
        self.conn.commit()

    def _migrate_schema(self):
        """Add missing columns when migrating from older schemas."""
        columns = [
            row[1] for row in self.conn.execute("PRAGMA table_info(run_ledger)").fetchall()
        ]
        if "run_id" not in columns:
            self.conn.execute("ALTER TABLE run_ledger ADD COLUMN run_id TEXT")
            self.conn.commit()
        if "attempt_id" not in columns:
            # Attempt scoping lets consumers distinguish rewrite attempts
            # inside the Scene Gate loop. Older rows get NULL attempt_id.
            self.conn.execute("ALTER TABLE run_ledger ADD COLUMN attempt_id TEXT")
            self.conn.commit()

    def emit(
        self,
        event_type: str,
        chapter_number: Optional[int] = None,
        scene_number: Optional[int] = None,
        agent_role: Optional[str] = None,
        payload: Optional[dict] = None,
        attempt_id: Optional[str] = None,
    ) -> int:
        """Emit an event to the ledger. Returns the event ID.

        attempt_id scopes events within a single scene's rewrite loop so
        consumers can distinguish retry iterations. Events outside the
        gate loop leave it None.
        """
        state_hash = self._compute_hash(payload) if payload else None
        payload_json = json.dumps(payload) if payload else None

        cursor = self.conn.execute(
            """
            INSERT INTO run_ledger
                (timestamp, run_id, event_type, chapter_number, scene_number,
                 attempt_id, agent_role, payload, state_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                self.run_id,
                event_type,
                chapter_number,
                scene_number,
                attempt_id,
                agent_role,
                payload_json,
                state_hash,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    # Relay v3 (Stage 1i) — level helpers inject a ``level`` key into the
    # payload so UI/CLI consumers can filter or colour-code events without
    # special-casing event_type. The helpers are thin wrappers around
    # ``emit`` to keep the schema backward-compatible.
    def _emit_with_level(
        self,
        level: str,
        event_type: str,
        chapter_number: Optional[int] = None,
        scene_number: Optional[int] = None,
        agent_role: Optional[str] = None,
        payload: Optional[dict] = None,
        attempt_id: Optional[str] = None,
    ) -> int:
        payload_with_level = dict(payload) if payload else {}
        payload_with_level.setdefault("level", level)
        return self.emit(
            event_type,
            chapter_number=chapter_number,
            scene_number=scene_number,
            agent_role=agent_role,
            payload=payload_with_level,
            attempt_id=attempt_id,
        )

    def emit_info(
        self,
        event_type: str,
        chapter_number: Optional[int] = None,
        scene_number: Optional[int] = None,
        agent_role: Optional[str] = None,
        payload: Optional[dict] = None,
        attempt_id: Optional[str] = None,
    ) -> int:
        return self._emit_with_level(
            "info",
            event_type,
            chapter_number=chapter_number,
            scene_number=scene_number,
            agent_role=agent_role,
            payload=payload,
            attempt_id=attempt_id,
        )

    def emit_warn(
        self,
        event_type: str,
        chapter_number: Optional[int] = None,
        scene_number: Optional[int] = None,
        agent_role: Optional[str] = None,
        payload: Optional[dict] = None,
        attempt_id: Optional[str] = None,
    ) -> int:
        return self._emit_with_level(
            "warn",
            event_type,
            chapter_number=chapter_number,
            scene_number=scene_number,
            agent_role=agent_role,
            payload=payload,
            attempt_id=attempt_id,
        )

    def emit_error(
        self,
        event_type: str,
        chapter_number: Optional[int] = None,
        scene_number: Optional[int] = None,
        agent_role: Optional[str] = None,
        payload: Optional[dict] = None,
        attempt_id: Optional[str] = None,
    ) -> int:
        return self._emit_with_level(
            "error",
            event_type,
            chapter_number=chapter_number,
            scene_number=scene_number,
            agent_role=agent_role,
            payload=payload,
            attempt_id=attempt_id,
        )

    def get_events(
        self,
        chapter_number: Optional[int] = None,
        event_type: Optional[str] = None,
        agent_role: Optional[str] = None,
        attempt_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query events from the ledger."""
        conditions = []
        params = []

        if chapter_number is not None:
            conditions.append("chapter_number = ?")
            params.append(chapter_number)
        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        if agent_role is not None:
            conditions.append("agent_role = ?")
            params.append(agent_role)
        if attempt_id is not None:
            conditions.append("attempt_id = ?")
            params.append(attempt_id)

        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"SELECT * FROM run_ledger{where} ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_dict(row) for row in reversed(rows)]

    def get_latest(self, event_type: str) -> Optional[dict]:
        """Get the most recent event of a given type."""
        row = self.conn.execute(
            "SELECT * FROM run_ledger WHERE event_type = ? ORDER BY id DESC LIMIT 1",
            (event_type,),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        if d.get("payload"):
            d["payload"] = json.loads(d["payload"])
        return d

    @staticmethod
    def _compute_hash(data: dict) -> str:
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()[:16]

    def close(self):
        self.conn.close()
