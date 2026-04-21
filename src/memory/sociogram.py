"""Slice 5 sociogram.

Directional relationship edges between named characters, three-axis scalar
encoded: ``trust`` / ``warmth`` / ``power_balance``, each clamped to
``[-1, 1]``. Declarative-first trust model (spec \u00a79.1):

1. **Primary (planning).** ``initialize_from_planning`` seeds edges from
   ``concept_seed.relationship_arcs`` (Ruusan shape) or
   ``concept_seed.ensemble_cast[*].relationships`` (spec-prose shape).
2. **Secondary (scene-card declarations).** ``apply_delta`` and
   ``apply_scene_deltas`` write per-scene trust/warmth/power_balance shifts
   declared on the scene card in ``relationship_deltas``.
3. **Tertiary (human-gated).** An assisted-suggestion mode may land proposals
   in revision debt; they only become edges after human acceptance. The
   sociogram never ingests extractor output directly.

The three axes are deliberately simple. Not: emotion histograms, not
communication modalities, not conflict-style. Start narrow, expand if needed.
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


ARC_TYPES: frozenset[str] = frozenset({
    "allies_to_enemies",
    "enemies_to_allies",
    "lovers_to_strangers",
    "strangers_to_found_family",
    "mentor_to_peer",
    "stable_opposition",
    "stable_alliance",
    "one_sided",
    "convergent",
    "divergent",
    "other",
})

DELTA_SOURCES: frozenset[str] = frozenset({
    "planning", "scene_card", "human_accepted_suggestion",
})

# Per-scene delta cap (spec \u00a79.3). Larger swings must be decomposed
# across multiple scenes.
MAX_ABS_DELTA = 0.5

_SCENE_ID_RE = re.compile(r"^ch\d{2}_sc\d{2}$")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _normalize_arc_type(raw: Any) -> str:
    if not raw:
        return "other"
    s = str(raw).strip().lower()
    if s in ARC_TYPES:
        return s
    # Map common planning labels onto the closed enum.
    aliases = {
        "reconciling": "enemies_to_allies",
        "deepening": "convergent",
        "rupturing": "allies_to_enemies",
        "found_family": "strangers_to_found_family",
        "alliance": "stable_alliance",
        "opposition": "stable_opposition",
        "one-sided": "one_sided",
        "one_sided": "one_sided",
    }
    return aliases.get(s, "other")


def _edge_id(subject: str, obj: str) -> str:
    basis = f"{subject.strip().lower()}::{obj.strip().lower()}"
    h = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]
    return f"rel_{h}"


class Sociogram:
    """SQLite-backed relationship graph.

    Expected path: ``output/<franchise>/<book>/state/sociogram.db``. Edges
    are directional: the ``Ben \u2192 Luke`` row and the ``Luke \u2192 Ben`` row are
    two rows with independent state, because trust and warmth are famously
    asymmetric in fiction.
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
            CREATE TABLE IF NOT EXISTS sociogram_edges (
                edge_id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                object TEXT NOT NULL,
                arc_type TEXT NOT NULL,
                trust REAL NOT NULL,
                warmth REAL NOT NULL,
                power_balance REAL NOT NULL,
                updated_at_scene TEXT NOT NULL,
                history TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sociogram_subject ON sociogram_edges(subject)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sociogram_object ON sociogram_edges(object)"
        )
        self.conn.commit()

    # ------------------------------------------------------------------ seed
    def initialize_from_planning(
        self, *, concept_seed: Mapping[str, Any],
    ) -> int:
        """Seed directional edges from planning. Returns count inserted.

        Accepts two shapes (in order):
        - ``concept_seed.relationship_arcs`` where each row has
          ``dyad: "A/B"``, ``arc_type``, ``arc_summary`` (Ruusan convention).
          Produces both A\u2192B and B\u2192A directed edges with mirrored initial
          state; authors can diverge them later via scene-card deltas.
        - ``concept_seed.ensemble_cast[*].relationships[*]`` with
          ``{target, arc_type, initial_trust, initial_warmth, initial_power}``.
          Produces subject\u2192target only.
        """
        count = 0
        count += self._seed_from_relationship_arcs(concept_seed)
        count += self._seed_from_ensemble_cast(concept_seed)
        return count

    def _seed_from_relationship_arcs(self, concept_seed: Mapping[str, Any]) -> int:
        rows = concept_seed.get("relationship_arcs") or []
        count = 0
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            dyad = row.get("dyad") or ""
            if "/" not in dyad:
                continue
            a, b = [x.strip() for x in dyad.split("/", 1)]
            if not a or not b:
                continue
            arc_type = _normalize_arc_type(row.get("arc_type"))
            note = row.get("arc_summary") or ""
            # Mirror the initial directed state. Scene-card deltas diverge
            # them over time.
            count += int(self._upsert_edge(
                subject=a, obj=b, arc_type=arc_type, note=note,
            ))
            count += int(self._upsert_edge(
                subject=b, obj=a, arc_type=arc_type, note=note,
            ))
        return count

    def _seed_from_ensemble_cast(self, concept_seed: Mapping[str, Any]) -> int:
        cast = concept_seed.get("ensemble_cast") or []
        count = 0
        for member in cast:
            if not isinstance(member, Mapping):
                continue
            subject = member.get("name")
            if not subject:
                continue
            rels = member.get("relationships") or []
            for rel in rels:
                if not isinstance(rel, Mapping):
                    continue
                target = rel.get("target") or rel.get("with") or rel.get("object")
                if not target:
                    continue
                arc_type = _normalize_arc_type(rel.get("arc_type"))
                initial = {
                    "trust": float(rel.get("initial_trust", 0.0)),
                    "warmth": float(rel.get("initial_warmth", 0.0)),
                    "power_balance": float(rel.get("initial_power", 0.0)),
                }
                note = rel.get("note", "")
                count += int(self._upsert_edge(
                    subject=str(subject), obj=str(target),
                    arc_type=arc_type, initial=initial, note=note,
                ))
        return count

    def _upsert_edge(
        self,
        *,
        subject: str,
        obj: str,
        arc_type: str,
        initial: Mapping[str, float] | None = None,
        note: str = "",
    ) -> bool:
        """Return True when the edge was newly created. Existing edges keep
        their current_state and history (planning re-seed is idempotent \u2014
        the planning note gets appended to history but trust/warmth/power
        stay at whatever scene deltas have moved them to)."""
        eid = _edge_id(subject, obj)
        existing = self.conn.execute(
            "SELECT history FROM sociogram_edges WHERE edge_id = ?", (eid,),
        ).fetchone()
        now = _iso_now()
        if existing is None:
            init = initial or {"trust": 0.0, "warmth": 0.0, "power_balance": 0.0}
            history = [{
                "scene_id": "planning",
                "source": "planning",
                "trust_delta": float(init.get("trust", 0.0)),
                "warmth_delta": float(init.get("warmth", 0.0)),
                "power_balance_delta": float(init.get("power_balance", 0.0)),
                "note": note,
            }]
            self.conn.execute(
                """
                INSERT INTO sociogram_edges (
                    edge_id, subject, object, arc_type, trust, warmth,
                    power_balance, updated_at_scene, history, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    eid, subject, obj, arc_type,
                    _clamp(float(init.get("trust", 0.0))),
                    _clamp(float(init.get("warmth", 0.0))),
                    _clamp(float(init.get("power_balance", 0.0))),
                    "planning",
                    json.dumps(history),
                    now, now,
                ),
            )
            self.conn.commit()
            return True
        # Existing edge \u2014 do not touch current_state; append planning note.
        history = json.loads(existing["history"] or "[]")
        history.append({
            "scene_id": "planning",
            "source": "planning",
            "trust_delta": 0.0, "warmth_delta": 0.0, "power_balance_delta": 0.0,
            "note": note,
        })
        self.conn.execute(
            "UPDATE sociogram_edges SET arc_type = ?, history = ?, updated_at = ? "
            "WHERE edge_id = ?",
            (arc_type, json.dumps(history), now, eid),
        )
        self.conn.commit()
        return False

    # ------------------------------------------------------------------ writes
    def apply_delta(
        self,
        *,
        subject: str,
        obj: str,
        scene_id: str,
        trust_delta: float = 0.0,
        warmth_delta: float = 0.0,
        power_balance_delta: float = 0.0,
        source: str = "scene_card",
        note: str = "",
    ) -> dict:
        """Apply a per-scene delta. Raises ``ValueError`` on cap / source /
        scene_id violations."""
        if source not in DELTA_SOURCES:
            raise ValueError(
                f"Sociogram.apply_delta: source={source!r} not in {sorted(DELTA_SOURCES)}"
            )
        if not _SCENE_ID_RE.match(scene_id):
            raise ValueError(
                f"Sociogram.apply_delta: scene_id={scene_id!r} must match chNN_scMM"
            )
        for axis, value in (
            ("trust_delta", trust_delta),
            ("warmth_delta", warmth_delta),
            ("power_balance_delta", power_balance_delta),
        ):
            if abs(float(value)) > MAX_ABS_DELTA + 1e-9:
                raise ValueError(
                    f"Sociogram.apply_delta: {axis}={value} exceeds "
                    f"\u00b1{MAX_ABS_DELTA} per-scene cap (spec \u00a79.3)"
                )
        eid = _edge_id(subject, obj)
        row = self.conn.execute(
            "SELECT * FROM sociogram_edges WHERE edge_id = ?", (eid,),
        ).fetchone()
        if row is None:
            # Scene declared a delta for a dyad the planning didn't seed.
            # Spec \u00a79.1 permits scene-card declarations to create new edges
            # so story_physics drift doesn't silently drop the update.
            self._upsert_edge(
                subject=subject, obj=obj, arc_type="other", note=note,
            )
            row = self.conn.execute(
                "SELECT * FROM sociogram_edges WHERE edge_id = ?", (eid,),
            ).fetchone()
        history = json.loads(row["history"] or "[]")
        new_trust = _clamp(float(row["trust"]) + float(trust_delta))
        new_warmth = _clamp(float(row["warmth"]) + float(warmth_delta))
        new_power = _clamp(float(row["power_balance"]) + float(power_balance_delta))
        history.append({
            "scene_id": scene_id,
            "source": source,
            "trust_delta": float(trust_delta),
            "warmth_delta": float(warmth_delta),
            "power_balance_delta": float(power_balance_delta),
            "note": note,
        })
        now = _iso_now()
        self.conn.execute(
            """
            UPDATE sociogram_edges
               SET trust = ?, warmth = ?, power_balance = ?,
                   updated_at_scene = ?, history = ?, updated_at = ?
             WHERE edge_id = ?
            """,
            (new_trust, new_warmth, new_power, scene_id, json.dumps(history), now, eid),
        )
        self.conn.commit()
        return {
            "edge_id": eid,
            "trust": new_trust, "warmth": new_warmth, "power_balance": new_power,
        }

    def apply_scene_deltas(
        self, *, scene_card: Mapping[str, Any],
    ) -> list[dict]:
        """Apply every ``relationship_deltas`` row on a scene card. Returns
        the list of updated edge snapshots. Invalid rows (missing subject /
        object, delta outside cap) emit a warn log and are skipped \u2014 the
        other rows still apply."""
        ch = scene_card.get("chapter_number")
        sn = scene_card.get("scene_number", 1)
        if ch is None:
            return []
        scene_id = f"ch{int(ch):02d}_sc{int(sn):02d}"
        out: list[dict] = []
        for delta in scene_card.get("relationship_deltas") or []:
            if not isinstance(delta, Mapping):
                continue
            subject = delta.get("subject")
            obj = delta.get("object")
            if not subject or not obj:
                continue
            try:
                updated = self.apply_delta(
                    subject=subject, obj=obj, scene_id=scene_id,
                    trust_delta=float(delta.get("trust_delta", 0.0)),
                    warmth_delta=float(delta.get("warmth_delta", 0.0)),
                    power_balance_delta=float(delta.get("power_balance_delta", 0.0)),
                    source="scene_card",
                    note=str(delta.get("note", "") or ""),
                )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "apply_delta failed for %s->%s at %s", subject, obj, scene_id,
                )
                continue
            out.append(updated)
        return out

    # ------------------------------------------------------------------- reads
    def get_edge(self, subject: str, obj: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM sociogram_edges WHERE edge_id = ?",
            (_edge_id(subject, obj),),
        ).fetchone()
        return self._row_to_dict(row) if row else None

    def list_all(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM sociogram_edges ORDER BY subject, object"
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def snapshot_for_chapter(self, chapter_number: int) -> dict:
        """Chapter-scoped snapshot keyed by ``subject\u2502object``. Used by
        ``ChapterPacketCompiler.compile_base`` when no scene context is
        available."""
        out: dict[str, dict] = {}
        for row in self.list_all():
            key = f"{row['subject']} \u2502 {row['object']}"
            out[key] = {
                "arc_type": row["arc_type"],
                "trust": row["trust"],
                "warmth": row["warmth"],
                "power_balance": row["power_balance"],
                "updated_at_scene": row["updated_at_scene"],
            }
        return out

    def context_for_scene(self, *, scene_card: Mapping[str, Any]) -> dict:
        """Overlay-time snapshot narrowed to dyads among
        ``characters_present`` (spec \u00a79.5). Includes a ``_tail`` key with
        the count of edges not surfaced so the drafter sees the total
        relational surface area without the renderer getting cluttered."""
        present: list[str] = []
        pov = scene_card.get("pov_character")
        if isinstance(pov, str) and pov:
            present.append(pov)
        for c in scene_card.get("characters_present") or []:
            if isinstance(c, str) and c and c not in present:
                present.append(c)
        all_edges = self.list_all()
        present_set = set(present)
        surfaced: dict[str, dict] = {}
        for row in all_edges:
            if row["subject"] in present_set and row["object"] in present_set:
                key = f"{row['subject']} \u2502 {row['object']}"
                surfaced[key] = {
                    "arc_type": row["arc_type"],
                    "trust": row["trust"],
                    "warmth": row["warmth"],
                    "power_balance": row["power_balance"],
                    "updated_at_scene": row["updated_at_scene"],
                }
        remainder = max(0, len(all_edges) - len(surfaced))
        if remainder:
            surfaced["_unshown_edge_count"] = remainder
        return surfaced

    def count(self) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM sociogram_edges"
        ).fetchone()
        return int(row["n"] if row else 0)

    # -------------------------------------------------------------- helpers
    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["history"] = json.loads(d["history"] or "[]")
        return d

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Sociogram":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = [
    "ARC_TYPES",
    "DELTA_SOURCES",
    "MAX_ABS_DELTA",
    "Sociogram",
]
