"""Persistent story state tracker backed by SQLite.

Tracks characters, knowledge, relationships, plot threads, timeline,
Chekhov guns, and chapter logs across the full novel pipeline.
All data is stored in a single SQLite file (no server needed).
"""

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Optional


def _slugify(name: str) -> str:
    """Convert a name to a slug ID. 'Ben Skywalker' -> 'ben_skywalker'"""
    return name.lower().replace(" ", "_").replace("-", "_")


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS characters (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    current_location TEXT,
    emotional_state TEXT,
    arc_position TEXT,
    inventory TEXT,
    last_appearance_chapter INTEGER,
    last_appearance_scene INTEGER
);

CREATE TABLE IF NOT EXISTS character_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id TEXT NOT NULL REFERENCES characters(id),
    fact_id TEXT NOT NULL,
    fact_description TEXT NOT NULL,
    layer TEXT CHECK(layer IN ('truth', 'belief', 'narrative_exposure')) NOT NULL,
    is_accurate BOOLEAN,
    acquired_chapter INTEGER,
    source TEXT,
    UNIQUE(character_id, fact_id, layer)
);

CREATE TABLE IF NOT EXISTS character_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_a TEXT NOT NULL REFERENCES characters(id),
    character_b TEXT NOT NULL REFERENCES characters(id),
    relationship_type TEXT,
    status TEXT,
    last_updated_chapter INTEGER,
    UNIQUE(character_a, character_b)
);

CREATE TABLE IF NOT EXISTS plot_threads (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT CHECK(status IN ('planted', 'active', 'escalating', 'resolving', 'resolved')),
    planted_chapter INTEGER,
    urgency TEXT CHECK(urgency IN ('background', 'rising', 'critical', 'climactic')),
    related_characters TEXT,
    resolution_notes TEXT
);

CREATE TABLE IF NOT EXISTS timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_number INTEGER,
    scene_number INTEGER,
    story_date TEXT,
    elapsed_time TEXT,
    key_events TEXT
);

CREATE TABLE IF NOT EXISTS chekhov_guns (
    id TEXT PRIMARY KEY,
    item_description TEXT NOT NULL,
    planted_chapter INTEGER,
    planted_context TEXT,
    fired_chapter INTEGER DEFAULT NULL,
    fired_status TEXT CHECK(fired_status IN ('unfired', 'fired', 'subverted')) DEFAULT 'unfired'
);

CREATE TABLE IF NOT EXISTS chapter_log (
    chapter_number INTEGER PRIMARY KEY,
    word_count INTEGER,
    structural_phase TEXT,
    pov_character TEXT,
    summary TEXT,
    quality_scores TEXT,
    failure_codes TEXT,
    revision_status TEXT CHECK(revision_status IN (
        'draft', 'gate_failed', 'gate_passed', 'craft_edited', 'revised', 'approved'
    )),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revised_at TIMESTAMP
);
"""


class StoryState:
    """SQLite-backed persistent story state for the novel pipeline."""

    def __init__(self, db_path: str = "data/story_state.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA_SQL)
        self.conn.commit()

        # Ensure the sentinel __world__ character exists for truth-layer knowledge
        existing = self.conn.execute(
            "SELECT id FROM characters WHERE id = ?", ("__world__",)
        ).fetchone()
        if existing is None:
            self.conn.execute(
                "INSERT INTO characters (id, name) VALUES (?, ?)",
                ("__world__", "__world__"),
            )
            self.conn.commit()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        """Convert a sqlite3.Row to a plain dict, or return None."""
        if row is None:
            return None
        return dict(row)

    def _rows_to_dicts(self, rows: list[sqlite3.Row]) -> list[dict]:
        """Convert a list of sqlite3.Row objects to plain dicts."""
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Characters
    # ------------------------------------------------------------------

    def add_character(
        self,
        id: str,
        name: str,
        current_location: str | None = None,
        emotional_state: str | None = None,
        arc_position: str | None = None,
        inventory: list | None = None,
    ) -> None:
        """Insert a new character into the characters table."""
        self.conn.execute(
            """INSERT INTO characters
               (id, name, current_location, emotional_state, arc_position, inventory)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                id,
                name,
                current_location,
                emotional_state,
                arc_position,
                json.dumps(inventory) if inventory is not None else None,
            ),
        )
        self.conn.commit()

    def get_character(self, id: str) -> dict | None:
        """Fetch a single character by ID."""
        row = self.conn.execute(
            "SELECT * FROM characters WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["inventory"] is not None:
            d["inventory"] = json.loads(d["inventory"])
        return d

    def update_character(self, id: str, **kwargs: object) -> None:
        """Update only the provided fields for a character."""
        if not kwargs:
            return
        if "inventory" in kwargs and kwargs["inventory"] is not None:
            kwargs["inventory"] = json.dumps(kwargs["inventory"])

        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [id]
        self.conn.execute(
            f"UPDATE characters SET {set_clause} WHERE id = ?", values
        )
        self.conn.commit()

    def get_all_characters(self) -> list[dict]:
        """Return every character as a list of dicts (excludes __world__ sentinel)."""
        rows = self.conn.execute(
            "SELECT * FROM characters WHERE id != '__world__'"
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d["inventory"] is not None:
                d["inventory"] = json.loads(d["inventory"])
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # Bulk Init
    # ------------------------------------------------------------------

    def init_from_concept_seed(self, concept_seed: dict) -> None:
        """Populate the characters table from a concept seed's ensemble_cast."""
        for char in concept_seed.get("ensemble_cast", []):
            char_id = _slugify(char["name"])
            self.add_character(
                id=char_id,
                name=char["name"],
                arc_position=char.get("role"),
            )

    # ------------------------------------------------------------------
    # Knowledge
    # ------------------------------------------------------------------

    def add_knowledge(
        self,
        character_id: str,
        fact_id: str,
        fact_description: str,
        layer: str,
        is_accurate: bool | None = None,
        acquired_chapter: int | None = None,
        source: str | None = None,
    ) -> None:
        """Insert or replace a knowledge entry (respects UNIQUE constraint)."""
        self.conn.execute(
            """INSERT OR REPLACE INTO character_knowledge
               (character_id, fact_id, fact_description, layer,
                is_accurate, acquired_chapter, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                character_id,
                fact_id,
                fact_description,
                layer,
                is_accurate,
                acquired_chapter,
                source,
            ),
        )
        self.conn.commit()

    def get_knowledge(
        self,
        character_id: str | None = None,
        layer: str | None = None,
        fact_id: str | None = None,
    ) -> list[dict]:
        """Query knowledge with optional filters."""
        clauses: list[str] = []
        params: list[object] = []

        if character_id is not None:
            clauses.append("character_id = ?")
            params.append(character_id)
        if layer is not None:
            clauses.append("layer = ?")
            params.append(layer)
        if fact_id is not None:
            clauses.append("fact_id = ?")
            params.append(fact_id)

        query = "SELECT * FROM character_knowledge"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)

        rows = self.conn.execute(query, params).fetchall()
        return self._rows_to_dicts(rows)

    # ------------------------------------------------------------------
    # Relationships
    # ------------------------------------------------------------------

    def add_relationship(
        self,
        character_a: str,
        character_b: str,
        relationship_type: str,
        status: str,
        last_updated_chapter: int | None = None,
    ) -> None:
        """Insert a new relationship between two characters."""
        self.conn.execute(
            """INSERT INTO character_relationships
               (character_a, character_b, relationship_type, status, last_updated_chapter)
               VALUES (?, ?, ?, ?, ?)""",
            (character_a, character_b, relationship_type, status, last_updated_chapter),
        )
        self.conn.commit()

    def get_relationships(self, character_id: str) -> list[dict]:
        """Return all relationships involving a character (either side)."""
        rows = self.conn.execute(
            """SELECT * FROM character_relationships
               WHERE character_a = ? OR character_b = ?""",
            (character_id, character_id),
        ).fetchall()
        return self._rows_to_dicts(rows)

    def update_relationship(
        self, character_a: str, character_b: str, **kwargs: object
    ) -> None:
        """Update fields on an existing relationship."""
        if not kwargs:
            return
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [character_a, character_b]
        self.conn.execute(
            f"""UPDATE character_relationships SET {set_clause}
                WHERE character_a = ? AND character_b = ?""",
            values,
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Plot Threads
    # ------------------------------------------------------------------

    def add_plot_thread(
        self,
        id: str,
        description: str,
        status: str = "planted",
        planted_chapter: int | None = None,
        urgency: str = "background",
        related_characters: list | None = None,
        resolution_notes: str | None = None,
    ) -> None:
        """Insert a new plot thread."""
        self.conn.execute(
            """INSERT INTO plot_threads
               (id, description, status, planted_chapter, urgency,
                related_characters, resolution_notes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                id,
                description,
                status,
                planted_chapter,
                urgency,
                json.dumps(related_characters) if related_characters is not None else None,
                resolution_notes,
            ),
        )
        self.conn.commit()

    def get_plot_thread(self, id: str) -> dict | None:
        """Fetch a single plot thread by ID."""
        row = self.conn.execute(
            "SELECT * FROM plot_threads WHERE id = ?", (id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["related_characters"] is not None:
            d["related_characters"] = json.loads(d["related_characters"])
        return d

    def update_plot_thread(self, id: str, **kwargs: object) -> None:
        """Update only the provided fields for a plot thread."""
        if not kwargs:
            return
        if "related_characters" in kwargs and kwargs["related_characters"] is not None:
            kwargs["related_characters"] = json.dumps(kwargs["related_characters"])

        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [id]
        self.conn.execute(
            f"UPDATE plot_threads SET {set_clause} WHERE id = ?", values
        )
        self.conn.commit()

    def get_active_threads(self) -> list[dict]:
        """Return all plot threads whose status is not 'resolved'."""
        rows = self.conn.execute(
            "SELECT * FROM plot_threads WHERE status != 'resolved'"
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d["related_characters"] is not None:
                d["related_characters"] = json.loads(d["related_characters"])
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    def add_timeline_entry(
        self,
        chapter_number: int,
        scene_number: int = 1,
        story_date: str | None = None,
        elapsed_time: str | None = None,
        key_events: list | None = None,
    ) -> None:
        """Insert a new timeline entry."""
        self.conn.execute(
            """INSERT INTO timeline
               (chapter_number, scene_number, story_date, elapsed_time, key_events)
               VALUES (?, ?, ?, ?, ?)""",
            (
                chapter_number,
                scene_number,
                story_date,
                elapsed_time,
                json.dumps(key_events) if key_events is not None else None,
            ),
        )
        self.conn.commit()

    def get_timeline(self, chapter_number: int | None = None) -> list[dict]:
        """Return timeline entries, optionally filtered by chapter."""
        if chapter_number is not None:
            rows = self.conn.execute(
                "SELECT * FROM timeline WHERE chapter_number = ?",
                (chapter_number,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM timeline ORDER BY chapter_number, scene_number"
            ).fetchall()

        results = []
        for row in rows:
            d = dict(row)
            if d["key_events"] is not None:
                d["key_events"] = json.loads(d["key_events"])
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # Chekhov Guns
    # ------------------------------------------------------------------

    def add_chekhov_gun(
        self,
        id: str,
        item_description: str,
        planted_chapter: int | None = None,
        planted_context: str | None = None,
    ) -> None:
        """Register a new Chekhov gun (defaults to unfired)."""
        self.conn.execute(
            """INSERT INTO chekhov_guns
               (id, item_description, planted_chapter, planted_context)
               VALUES (?, ?, ?, ?)""",
            (id, item_description, planted_chapter, planted_context),
        )
        self.conn.commit()

    def fire_chekhov_gun(
        self, id: str, fired_chapter: int, fired_status: str = "fired"
    ) -> None:
        """Mark a Chekhov gun as fired or subverted."""
        self.conn.execute(
            "UPDATE chekhov_guns SET fired_chapter = ?, fired_status = ? WHERE id = ?",
            (fired_chapter, fired_status, id),
        )
        self.conn.commit()

    def get_unfired_guns(self) -> list[dict]:
        """Return all Chekhov guns that have not been fired yet."""
        rows = self.conn.execute(
            "SELECT * FROM chekhov_guns WHERE fired_status = 'unfired'"
        ).fetchall()
        return self._rows_to_dicts(rows)

    # ------------------------------------------------------------------
    # Chapter Log
    # ------------------------------------------------------------------

    def add_chapter_log(
        self,
        chapter_number: int,
        word_count: int | None = None,
        structural_phase: str | None = None,
        pov_character: str | None = None,
        summary: str | None = None,
        quality_scores: dict | None = None,
        failure_codes: list | None = None,
        revision_status: str = "draft",
    ) -> None:
        """Insert a new chapter log entry."""
        self.conn.execute(
            """INSERT INTO chapter_log
               (chapter_number, word_count, structural_phase, pov_character,
                summary, quality_scores, failure_codes, revision_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chapter_number,
                word_count,
                structural_phase,
                pov_character,
                summary,
                json.dumps(quality_scores) if quality_scores is not None else None,
                json.dumps(failure_codes) if failure_codes is not None else None,
                revision_status,
            ),
        )
        self.conn.commit()

    def get_chapter_log(self, chapter_number: int) -> dict | None:
        """Fetch a single chapter log entry."""
        row = self.conn.execute(
            "SELECT * FROM chapter_log WHERE chapter_number = ?",
            (chapter_number,),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["quality_scores"] is not None:
            d["quality_scores"] = json.loads(d["quality_scores"])
        if d["failure_codes"] is not None:
            d["failure_codes"] = json.loads(d["failure_codes"])
        return d

    def update_chapter_log(self, chapter_number: int, **kwargs: object) -> None:
        """Update only the provided fields for a chapter log entry."""
        if not kwargs:
            return
        if "quality_scores" in kwargs and kwargs["quality_scores"] is not None:
            kwargs["quality_scores"] = json.dumps(kwargs["quality_scores"])
        if "failure_codes" in kwargs and kwargs["failure_codes"] is not None:
            kwargs["failure_codes"] = json.dumps(kwargs["failure_codes"])

        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [chapter_number]
        self.conn.execute(
            f"UPDATE chapter_log SET {set_clause} WHERE chapter_number = ?",
            values,
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_state_hash(self) -> str:
        """Return a SHA-256 hash of the current characters + threads + knowledge state.

        Used by the state diff system for before/after comparison.
        """
        characters = self.get_all_characters()
        threads = self.get_active_threads()
        knowledge = self.get_knowledge()

        state = {
            "characters": characters,
            "plot_threads": threads,
            "knowledge": knowledge,
        }
        serialized = json.dumps(state, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
