"""Slice 3 promise ledger.

SQLite-backed store of declared setup/payoff obligations across a manuscript.

**Trust model (spec \u00a77.1 \u2014 declarative with defaults):**

- Ledger rows are seeded from planning artifacts (``concept_seed.story_physics
  .promise_payoff_ledger`` + ``scene_card.promises_planted`` / ``promises_paid``).
- Scene cards may declare ``promises_progressed: [<promise_id>, ...]``; each
  entry appends one row to ``progression_log`` with ``source: 'scene_card'``.
- ``SceneReviewer`` progression suggestions do **not** write here \u2014 they land as
  ``editorial.scene_reviewer`` revision-debt rows instead.
- ``overdue`` is derived, not stored. A promise is overdue when the current
  scene index has passed ``due_by_scene`` and ``payoff_scene`` is still null.

Consumed by:

- ``ChapterPacketCompiler`` (spec \u00a77.3) \u2014 ``list_top_urgent`` feeds the
  ``active_promises`` field of the overlay; total count tail prevents packet
  dilution at 5-cap.
- ``ChapterCloseMemoGenerator`` + ``MilestoneMemoGenerator`` \u2014
  ``pending_as_of_chapter`` surfaces open promises in the human-review memo.

Persistence: ``output/<franchise>/<book>/state/promise_ledger.db``. Kept
separate from ``story_state.db`` / ``revision_debt.db`` so its migration
surface stays stable as later slices iterate (spec \u00a77.2.3).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

logger = logging.getLogger(__name__)


PROMISE_TYPES: frozenset[str] = frozenset({
    "plot", "character", "thematic", "mystery", "romance", "other",
})
STATUSES: frozenset[str] = frozenset({
    "planted", "progressing", "paid", "broken", "retired",
})
SOURCES: frozenset[str] = frozenset({"scene_card", "manual", "planning"})

_SCENE_ID_RE = re.compile(r"^ch(\d{2,})_sc(\d{2,})$")
_CHAPTER_REF_RE = re.compile(r"(\d+)")


def _parse_scene_id(scene_id: str) -> tuple[int, int] | None:
    """Parse ``chNN_scMM`` into a (chapter, scene) tuple; None on mismatch."""
    if not isinstance(scene_id, str):
        return None
    m = _SCENE_ID_RE.match(scene_id)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _scene_id(chapter: int, scene: int) -> str:
    return f"ch{chapter:02d}_sc{scene:02d}"


def _scene_id_for_chapter_end(chapter: int) -> str:
    """Sentinel 'end of chapter' scene id used when planning only names a
    chapter (not a scene) as the due / payoff point. ``sc99`` is unreachable
    by normal scene-card numbering (max 2-digit scene) so ``scene_id <= X``
    comparisons always treat it as later than any real scene in the chapter.
    """
    return f"ch{chapter:02d}_sc99"


def _parse_chapter_ref(raw: Any) -> int | None:
    """Extract a chapter number from planning shapes like ``"Chapter 5"``,
    ``"Chapter 25-26"`` (earliest), or a bare int."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        m = _CHAPTER_REF_RE.search(raw)
        if m:
            return int(m.group(1))
    return None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PromiseLedger:
    """Promise-ledger store backed by SQLite.

    One row per promise. Progression beats accumulate in a JSON array column
    so read-path rebuilds the list without a join \u2014 the table is small
    (typically <100 rows per novel) and all queries scan it linearly.
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
            CREATE TABLE IF NOT EXISTS promise_ledger (
                promise_id TEXT PRIMARY KEY,
                description TEXT NOT NULL,
                promise_type TEXT,
                setup_scene TEXT NOT NULL,
                payoff_scene TEXT,
                due_by_scene TEXT,
                status TEXT NOT NULL,
                progression_log TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_promise_status ON promise_ledger(status)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_promise_setup ON promise_ledger(setup_scene)"
        )
        self.conn.commit()

    # ------------------------------------------------------------------ seed
    def initialize_from_planning(
        self,
        *,
        concept_seed: Mapping[str, Any],
        scene_cards: Iterable[Mapping[str, Any]],
    ) -> int:
        """Seed promises from planning artifacts. Returns count inserted.

        Idempotent: re-running updates in place (spec \u00a77.4.1).

        Sources (in order):
        1. ``concept_seed.story_physics.promise_payoff_ledger`` \u2014 canonical list.
        2. ``scene_card.promises_planted[i]`` \u2014 sets ``setup_scene`` for the
           matching ``promise_id`` if not already set by (1).
        3. ``scene_card.promises_paid[i]`` \u2014 sets ``payoff_scene`` + ``status=paid``.
        """
        # Coerce input once; scene cards get walked twice.
        cards = [dict(c) for c in scene_cards]
        # Sort for deterministic setup_scene picks when the same promise is
        # planted in multiple cards (earliest wins).
        cards.sort(
            key=lambda c: (int(c.get("chapter_number") or 0), int(c.get("scene_number") or 0))
        )
        seeds = self._collect_planning_seeds(concept_seed)
        seeds = self._augment_from_scene_cards(seeds, cards)

        count = 0
        for pid, entry in seeds.items():
            self._upsert(pid=pid, entry=entry)
            count += 1
        return count

    def _collect_planning_seeds(
        self, concept_seed: Mapping[str, Any],
    ) -> dict[str, dict]:
        seeds: dict[str, dict] = {}
        physics = concept_seed.get("story_physics") or {}
        raw_list = physics.get("promise_payoff_ledger") or []
        for raw in raw_list:
            if not isinstance(raw, Mapping):
                continue
            pid = raw.get("promise_id")
            if not pid:
                continue
            description = (
                raw.get("description") or raw.get("promise") or raw.get("summary") or ""
            )
            ptype = _normalize_type(raw.get("promise_type") or raw.get("type"))
            planted_ch = _parse_chapter_ref(raw.get("planted_chapter") or raw.get("planted_in"))
            payoff_ch = _parse_chapter_ref(raw.get("payoff_chapter") or raw.get("payoff_in"))
            status = _normalize_status(raw.get("status"))

            setup_scene: str | None = None
            if planted_ch is not None:
                setup_scene = _scene_id(planted_ch, 1)

            payoff_scene: str | None = None
            if payoff_ch is not None:
                payoff_scene = _scene_id_for_chapter_end(payoff_ch)

            due_by_scene: str | None = None
            if payoff_ch is not None:
                due_by_scene = _scene_id_for_chapter_end(payoff_ch)

            if status == "paid" and payoff_scene is None and payoff_ch is not None:
                payoff_scene = _scene_id_for_chapter_end(payoff_ch)

            seeds[pid] = {
                "description": description,
                "promise_type": ptype,
                "setup_scene": setup_scene,
                "payoff_scene": payoff_scene,
                "due_by_scene": due_by_scene,
                "status": status if status else ("paid" if payoff_scene else "planted"),
            }
        return seeds

    def _augment_from_scene_cards(
        self, seeds: dict[str, dict], cards: list[dict],
    ) -> dict[str, dict]:
        for card in cards:
            ch = card.get("chapter_number")
            sn = card.get("scene_number")
            if ch is None or sn is None:
                continue
            sid = _scene_id(int(ch), int(sn))
            for pid in card.get("promises_planted") or []:
                if not pid:
                    continue
                entry = seeds.setdefault(
                    pid,
                    {
                        "description": "",
                        "promise_type": None,
                        "setup_scene": None,
                        "payoff_scene": None,
                        "due_by_scene": None,
                        "status": "planted",
                    },
                )
                existing = entry.get("setup_scene")
                if existing is None or _scene_id_lt(sid, existing):
                    entry["setup_scene"] = sid
            for pid in card.get("promises_paid") or []:
                if not pid:
                    continue
                entry = seeds.setdefault(
                    pid,
                    {
                        "description": "",
                        "promise_type": None,
                        "setup_scene": sid,
                        "payoff_scene": None,
                        "due_by_scene": None,
                        "status": "planted",
                    },
                )
                existing = entry.get("payoff_scene")
                if existing is None or _scene_id_lt(sid, existing):
                    entry["payoff_scene"] = sid
                entry["status"] = "paid"
        # Any promise with no setup_scene is unusable; drop it so writes
        # don't violate the NOT NULL constraint.
        return {pid: e for pid, e in seeds.items() if e.get("setup_scene")}

    def _upsert(self, *, pid: str, entry: Mapping[str, Any]) -> None:
        now = _iso_now()
        existing = self.conn.execute(
            "SELECT progression_log, created_at FROM promise_ledger WHERE promise_id = ?",
            (pid,),
        ).fetchone()
        progression_log = json.dumps([])
        created_at = now
        if existing is not None:
            progression_log = existing["progression_log"] or json.dumps([])
            created_at = existing["created_at"] or now
        # On conflict we deliberately do NOT update `status`: re-seeding from
        # planning must not clobber a runtime status advanced by
        # record_progression / record_payoff / record_broken.
        self.conn.execute(
            """
            INSERT INTO promise_ledger (
                promise_id, description, promise_type, setup_scene, payoff_scene,
                due_by_scene, status, progression_log, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(promise_id) DO UPDATE SET
                description = excluded.description,
                promise_type = excluded.promise_type,
                setup_scene = excluded.setup_scene,
                payoff_scene = excluded.payoff_scene,
                due_by_scene = excluded.due_by_scene,
                updated_at = excluded.updated_at
            """,
            (
                pid,
                entry.get("description", ""),
                entry.get("promise_type"),
                entry.get("setup_scene"),
                entry.get("payoff_scene"),
                entry.get("due_by_scene"),
                entry.get("status", "planted"),
                progression_log,
                created_at,
                now,
            ),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ writes
    def record_progression(
        self, *, promise_id: str, scene_id: str, source: str = "scene_card",
        note: str = "",
    ) -> None:
        if source not in SOURCES:
            raise ValueError(
                f"PromiseLedger.record_progression: source={source!r} not in {sorted(SOURCES)}"
            )
        row = self._get_row(promise_id)
        if row is None:
            raise KeyError(
                f"PromiseLedger.record_progression: unknown promise_id {promise_id!r}"
            )
        log = json.loads(row["progression_log"] or "[]")
        log.append({
            "scene_id": scene_id,
            "source": source,
            "note": note,
            "timestamp": _iso_now(),
        })
        # Status transitions from planted \u2192 progressing when the first beat
        # is logged (spec \u00a77.1 \"defaults to progressing between setup and
        # payoff\"). Paid/broken/retired are terminal \u2014 no demotion.
        new_status = row["status"]
        if new_status == "planted":
            new_status = "progressing"
        self.conn.execute(
            "UPDATE promise_ledger SET progression_log = ?, status = ?, updated_at = ? "
            "WHERE promise_id = ?",
            (json.dumps(log), new_status, _iso_now(), promise_id),
        )
        self.conn.commit()

    def record_payoff(self, *, promise_id: str, scene_id: str) -> None:
        row = self._get_row(promise_id)
        if row is None:
            raise KeyError(
                f"PromiseLedger.record_payoff: unknown promise_id {promise_id!r}"
            )
        self.conn.execute(
            "UPDATE promise_ledger SET payoff_scene = ?, status = ?, updated_at = ? "
            "WHERE promise_id = ?",
            (scene_id, "paid", _iso_now(), promise_id),
        )
        self.conn.commit()

    def record_broken(
        self, *, promise_id: str, scene_id: str, reason: str,
    ) -> None:
        row = self._get_row(promise_id)
        if row is None:
            raise KeyError(
                f"PromiseLedger.record_broken: unknown promise_id {promise_id!r}"
            )
        log = json.loads(row["progression_log"] or "[]")
        log.append({
            "scene_id": scene_id,
            "source": "manual",
            "note": f"broken: {reason}",
            "timestamp": _iso_now(),
        })
        self.conn.execute(
            "UPDATE promise_ledger SET status = ?, progression_log = ?, updated_at = ? "
            "WHERE promise_id = ?",
            ("broken", json.dumps(log), _iso_now(), promise_id),
        )
        self.conn.commit()

    def retire(self, *, promise_id: str, reason: str = "") -> None:
        """Soft-delete: mark a promise retired (e.g. scope cut from the book)."""
        if self._get_row(promise_id) is None:
            raise KeyError(f"PromiseLedger.retire: unknown promise_id {promise_id!r}")
        self.conn.execute(
            "UPDATE promise_ledger SET status = ?, updated_at = ? WHERE promise_id = ?",
            ("retired", _iso_now(), promise_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------------- reads
    def get(self, promise_id: str) -> dict | None:
        row = self._get_row(promise_id)
        return self._row_to_dict(row) if row else None

    def list_all(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM promise_ledger ORDER BY setup_scene"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def list_active(self, *, at_scene: str) -> list[dict]:
        """Promises where setup_scene <= at_scene < payoff_scene (or payoff null).

        Excludes terminal statuses (paid / broken / retired). A planted or
        progressing promise whose setup_scene is strictly greater than
        ``at_scene`` is not yet live; excluded.
        """
        if _parse_scene_id(at_scene) is None:
            raise ValueError(
                f"PromiseLedger.list_active: at_scene={at_scene!r} must match chNN_scMM"
            )
        out: list[dict] = []
        for r in self.list_all():
            if r["status"] in ("paid", "broken", "retired"):
                continue
            setup = r.get("setup_scene")
            if not setup or _scene_id_lt(at_scene, setup):
                continue
            payoff = r.get("payoff_scene")
            if payoff and not _scene_id_lt(at_scene, payoff):
                continue
            out.append(r)
        return out

    def list_overdue(self, *, at_scene: str) -> list[dict]:
        """Active promises whose ``due_by_scene`` has already passed.

        Returns empty list for promises with no ``due_by_scene`` set
        (spec \u00a77.4.2: if no due info is available, ``list_overdue`` never
        returns the promise).
        """
        if _parse_scene_id(at_scene) is None:
            raise ValueError(
                f"PromiseLedger.list_overdue: at_scene={at_scene!r} must match chNN_scMM"
            )
        out: list[dict] = []
        for r in self.list_active(at_scene=at_scene):
            due = r.get("due_by_scene")
            if not due:
                continue
            if _scene_id_lt(due, at_scene):
                overdue = dict(r)
                overdue["overdue_by_scenes"] = _scene_id_distance(due, at_scene)
                out.append(overdue)
        return out

    def list_top_urgent(self, *, at_scene: str, n: int = 5) -> list[dict]:
        """Active + overdue promises sorted by due-scene proximity.

        The ChapterPacketCompiler calls this at overlay time to populate the
        ``active_promises`` field without dilution (spec \u00a77.3). Overdue
        promises are included and flagged ``status='overdue'`` in the result
        so the renderer can add the ``do-not-force-payoff`` hint.
        """
        if n < 0:
            raise ValueError("PromiseLedger.list_top_urgent: n must be >= 0")
        if _parse_scene_id(at_scene) is None:
            raise ValueError(
                f"PromiseLedger.list_top_urgent: at_scene={at_scene!r} must match chNN_scMM"
            )
        active = self.list_active(at_scene=at_scene)
        # Rank: overdue first (most overdue first), then by nearest-due,
        # then by setup_scene as a tiebreaker.
        def _rank(entry: dict) -> tuple:
            due = entry.get("due_by_scene")
            if not due:
                # No deadline \u2192 least urgent.
                return (2, 0, entry.get("setup_scene") or "")
            distance = _scene_id_distance(at_scene, due)
            if distance < 0:
                # Overdue \u2014 rank first, most-negative distance most urgent.
                return (0, distance, entry.get("setup_scene") or "")
            return (1, distance, entry.get("setup_scene") or "")

        ranked = sorted(active, key=_rank)[:n]
        out: list[dict] = []
        for entry in ranked:
            due = entry.get("due_by_scene")
            enriched = dict(entry)
            if due and _scene_id_lt(due, at_scene):
                enriched["status"] = "overdue"
                enriched["overdue_by_scenes"] = _scene_id_distance(due, at_scene)
            out.append(enriched)
        return out

    def count_active(self, *, at_scene: str) -> int:
        """Total active count; used by the packet compiler to render the
        ``active_promises_total_count`` tail alongside the top-n list."""
        return len(self.list_active(at_scene=at_scene))

    # ----------- chapter-scoped convenience wrappers (used by Slice 2 stubs) ---
    def active_for_chapter(self, chapter_number: int) -> list[dict]:
        """Promises active as of the first scene of the given chapter.

        Used by ``ChapterPacketCompiler.compile_base`` when the scene is not
        yet known. Overlay compilation uses ``list_top_urgent`` instead.
        """
        return self.list_active(at_scene=_scene_id(int(chapter_number), 1))

    def pending_as_of_chapter(self, chapter_number: int) -> list[dict]:
        """Promises still unpaid at the close of the given chapter.

        Used by ``ChapterCloseMemoGenerator`` + ``MilestoneMemoGenerator`` for
        the ``pending_promises`` field of the human-review memo.
        """
        return self.list_active(at_scene=_scene_id_for_chapter_end(int(chapter_number)))

    # -------------------------------------------------------------- helpers
    def _get_row(self, promise_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM promise_ledger WHERE promise_id = ?", (promise_id,),
        ).fetchone()

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["progression_log"] = json.loads(d["progression_log"] or "[]")
        return d

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "PromiseLedger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


# --------------------------------------------------------------------------- #
# Module helpers                                                              #
# --------------------------------------------------------------------------- #


def _scene_id_lt(a: str, b: str) -> bool:
    """Strict less-than comparison on scene IDs. Unparseable IDs sort last."""
    pa = _parse_scene_id(a)
    pb = _parse_scene_id(b)
    if pa is None or pb is None:
        # Fall back to string compare \u2014 deterministic but not meaningful.
        return (a or "") < (b or "")
    return pa < pb


def _scene_id_distance(a: str, b: str) -> int:
    """Signed distance in scenes between two IDs (b - a). Returns 0 on parse
    failure so callers do not propagate None arithmetic."""
    pa = _parse_scene_id(a)
    pb = _parse_scene_id(b)
    if pa is None or pb is None:
        return 0
    # Scene-major ordinal: 100 scenes per chapter is the implicit cap (sc99 is
    # the chapter-end sentinel, so sc00..sc99 is the full addressable range).
    return (pb[0] - pa[0]) * 100 + (pb[1] - pa[1])


def _normalize_type(raw: Any) -> str | None:
    if not raw:
        return None
    s = str(raw).strip().lower()
    # Planning commonly uses "setup_payoff" / "foreshadow" / "chekhov" from
    # the story_physics schema. Map onto the ledger's enum.
    if s in PROMISE_TYPES:
        return s
    if s in ("setup_payoff", "foreshadow", "chekhov"):
        return "plot"
    return "other"


def _normalize_status(raw: Any) -> str | None:
    if not raw:
        return None
    s = str(raw).strip().lower()
    if s in STATUSES:
        return s
    if s in ("unfulfilled",):
        return "planted"
    if s in ("fulfilled",):
        return "paid"
    if s in ("subverted",):
        return "broken"
    return None


__all__ = [
    "PROMISE_TYPES",
    "STATUSES",
    "SOURCES",
    "PromiseLedger",
]
