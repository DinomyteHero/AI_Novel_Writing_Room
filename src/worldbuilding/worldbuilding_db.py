"""SQLite-backed persistence for universes, lore entries, and relations.

Stores worldbuilding data in a standalone database (separate from story_state.db)
because universes span multiple projects. Follows the same SQLite patterns as
StoryState: WAL mode, foreign keys, migration tracking, _safe_json_loads.
"""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _safe_json_loads(value, default=None, context: str = ""):
    """Parse JSON from a database field, returning *default* on failure."""
    if value is None:
        return default
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Corrupt JSON in %s: %.80s", context or "field", value)
        return default if default is not None else value


LORE_CATEGORIES = [
    "faction", "location", "character_background", "political_system",
    "force_mechanic", "technology", "species_culture", "historical_event",
    "terminology", "custom",
]

LORE_STATUSES = ["canonical", "provisional", "deprecated"]

EXTRACTION_SOURCES = ["author", "concept_seed_import", "prose_extraction", "workshop"]

RELATION_TYPES = [
    "located_in", "member_of", "caused_by", "allied_with",
    "enemy_of", "succeeded_by", "part_of", "references",
]

VISIBILITY_LEVELS = ["public", "faction_internal", "secret"]

TIMELINE_SYSTEMS = ["forward", "bby_aby", "chapter_based", "custom"]

AFFILIATION_TYPES = ["member", "ally", "aware"]


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS universes (
    universe_id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    parent_universe_id TEXT,
    franchise TEXT,
    description TEXT,
    embedding_model TEXT NOT NULL DEFAULT 'nomic-ai/nomic-embed-text-v1.5',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (parent_universe_id) REFERENCES universes(universe_id)
);

CREATE TABLE IF NOT EXISTS lore_entries (
    entry_id TEXT PRIMARY KEY,
    universe_id TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN (
        'faction', 'location', 'character_background', 'political_system',
        'force_mechanic', 'technology', 'species_culture', 'historical_event',
        'terminology', 'custom'
    )),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'canonical' CHECK(status IN (
        'canonical', 'provisional', 'deprecated'
    )),
    valid_from TEXT,
    valid_until TEXT,
    thematic_notes TEXT,
    speech_patterns TEXT,
    canon_override INTEGER DEFAULT 0,
    override_notes TEXT,
    tags TEXT,
    source_project_id TEXT,
    introduced_in_project_id TEXT,
    extraction_source TEXT DEFAULT 'author' CHECK(extraction_source IN (
        'author', 'concept_seed_import', 'prose_extraction', 'workshop'
    )),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (universe_id) REFERENCES universes(universe_id)
);

CREATE TABLE IF NOT EXISTS lore_relations (
    source_entry_id TEXT NOT NULL,
    target_entry_id TEXT NOT NULL,
    relation_type TEXT NOT NULL CHECK(relation_type IN (
        'located_in', 'member_of', 'caused_by', 'allied_with',
        'enemy_of', 'succeeded_by', 'part_of', 'references'
    )),
    description TEXT,
    dialogue_implications TEXT,
    PRIMARY KEY (source_entry_id, target_entry_id, relation_type),
    FOREIGN KEY (source_entry_id) REFERENCES lore_entries(entry_id),
    FOREIGN KEY (target_entry_id) REFERENCES lore_entries(entry_id)
);

CREATE TABLE IF NOT EXISTS project_universe_binding (
    project_id TEXT PRIMARY KEY,
    universe_id TEXT NOT NULL,
    reading_order INTEGER DEFAULT 0,
    timeline_start TEXT,
    timeline_end TEXT,
    FOREIGN KEY (universe_id) REFERENCES universes(universe_id)
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);
"""

def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Add timeline sort keys, visibility, character affiliations."""
    conn.executescript("""
    ALTER TABLE universes ADD COLUMN timeline_system TEXT DEFAULT 'forward';

    ALTER TABLE lore_entries ADD COLUMN timeline_sort_start INTEGER;
    ALTER TABLE lore_entries ADD COLUMN timeline_sort_end INTEGER;
    ALTER TABLE lore_entries ADD COLUMN visibility TEXT DEFAULT 'public';

    ALTER TABLE project_universe_binding ADD COLUMN timeline_sort_start INTEGER;
    ALTER TABLE project_universe_binding ADD COLUMN timeline_sort_end INTEGER;

    CREATE TABLE IF NOT EXISTS character_lore_affiliations (
        character_id TEXT NOT NULL,
        entry_id TEXT NOT NULL,
        affiliation_type TEXT DEFAULT 'member'
            CHECK(affiliation_type IN ('member', 'ally', 'aware')),
        PRIMARY KEY (character_id, entry_id),
        FOREIGN KEY (entry_id) REFERENCES lore_entries(entry_id)
    );
    """)


_MIGRATIONS: list[tuple[int, str, callable]] = [
    (2, "Timeline sort keys, visibility, character affiliations", _migrate_v1_to_v2),
]


class WorldbuildingDB:
    """SQLite-backed persistence for universes, lore entries, and relations."""

    def __init__(self, db_path: str = "data/worldbuilding.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.executescript(_SCHEMA_SQL)
        self.conn.commit()

        # Seed baseline migration version if empty
        row = self.conn.execute(
            "SELECT MAX(version) as v FROM schema_migrations"
        ).fetchone()
        if row["v"] is None:
            self.conn.execute(
                "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                (1, "Baseline: worldbuilding schema (4 tables)"),
            )
            self.conn.commit()

        self._run_migrations()

    def _run_migrations(self) -> None:
        """Apply any pending schema migrations in order."""
        row = self.conn.execute(
            "SELECT MAX(version) as v FROM schema_migrations"
        ).fetchone()
        current_version = row["v"] if row["v"] is not None else 0

        for version, description, migrate_fn in _MIGRATIONS:
            if version > current_version:
                logger.info("Applying migration v%d: %s", version, description)
                migrate_fn(self.conn)
                self.conn.execute(
                    "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                    (version, description),
                )
                self.conn.commit()
                logger.info("Migration v%d applied successfully", version)

    def get_schema_version(self) -> int:
        row = self.conn.execute(
            "SELECT MAX(version) as v FROM schema_migrations"
        ).fetchone()
        return row["v"] if row["v"] is not None else 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        d = dict(row)
        if "tags" in d and d["tags"] is not None:
            d["tags"] = _safe_json_loads(d["tags"], [], "tags")
        return d

    def _rows_to_dicts(self, rows: list[sqlite3.Row]) -> list[dict]:
        return [self._row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Universes
    # ------------------------------------------------------------------

    def create_universe(
        self,
        universe_id: str,
        display_name: str,
        parent_universe_id: Optional[str] = None,
        franchise: Optional[str] = None,
        description: Optional[str] = None,
        embedding_model: Optional[str] = None,
        timeline_system: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO universes
               (universe_id, display_name, parent_universe_id, franchise,
                description, embedding_model, timeline_system)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                universe_id,
                display_name,
                parent_universe_id,
                franchise,
                description,
                embedding_model or "nomic-ai/nomic-embed-text-v1.5",
                timeline_system or "forward",
            ),
        )
        self.conn.commit()

    def get_universe(self, universe_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM universes WHERE universe_id = ?", (universe_id,)
        ).fetchone()
        return self._row_to_dict(row)

    def list_universes(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT u.*, COUNT(le.entry_id) as entry_count "
            "FROM universes u LEFT JOIN lore_entries le ON u.universe_id = le.universe_id "
            "GROUP BY u.universe_id ORDER BY u.created_at"
        ).fetchall()
        return self._rows_to_dicts(rows)

    def delete_universe(self, universe_id: str) -> None:
        """Delete a universe and cascade: relations, entries, bindings."""
        # Delete relations for entries in this universe
        self.conn.execute(
            """DELETE FROM lore_relations WHERE source_entry_id IN
               (SELECT entry_id FROM lore_entries WHERE universe_id = ?)
               OR target_entry_id IN
               (SELECT entry_id FROM lore_entries WHERE universe_id = ?)""",
            (universe_id, universe_id),
        )
        self.conn.execute(
            "DELETE FROM lore_entries WHERE universe_id = ?", (universe_id,)
        )
        self.conn.execute(
            "DELETE FROM project_universe_binding WHERE universe_id = ?",
            (universe_id,),
        )
        self.conn.execute(
            "DELETE FROM universes WHERE universe_id = ?", (universe_id,)
        )
        self.conn.commit()

    def get_universe_chain(self, universe_id: str) -> list[str]:
        """Walk the parent chain: [child, parent, grandparent, ...]."""
        chain = []
        current = universe_id
        visited = set()
        while current and current not in visited:
            visited.add(current)
            chain.append(current)
            row = self.conn.execute(
                "SELECT parent_universe_id FROM universes WHERE universe_id = ?",
                (current,),
            ).fetchone()
            if row is None:
                break
            current = row["parent_universe_id"]
        return chain

    # ------------------------------------------------------------------
    # Lore Entries
    # ------------------------------------------------------------------

    def create_lore_entry(
        self,
        entry_id: str,
        universe_id: str,
        category: str,
        title: str,
        content: str,
        status: str = "canonical",
        valid_from: Optional[str] = None,
        valid_until: Optional[str] = None,
        thematic_notes: Optional[str] = None,
        speech_patterns: Optional[str] = None,
        canon_override: bool = False,
        override_notes: Optional[str] = None,
        tags: Optional[list[str]] = None,
        source_project_id: Optional[str] = None,
        introduced_in_project_id: Optional[str] = None,
        extraction_source: str = "author",
        timeline_sort_start: Optional[int] = None,
        timeline_sort_end: Optional[int] = None,
        visibility: str = "public",
    ) -> None:
        self.conn.execute(
            """INSERT INTO lore_entries
               (entry_id, universe_id, category, title, content, status,
                valid_from, valid_until, thematic_notes, speech_patterns,
                canon_override, override_notes, tags, source_project_id,
                introduced_in_project_id, extraction_source,
                timeline_sort_start, timeline_sort_end, visibility)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id, universe_id, category, title, content, status,
                valid_from, valid_until, thematic_notes, speech_patterns,
                1 if canon_override else 0, override_notes,
                json.dumps(tags) if tags else None,
                source_project_id, introduced_in_project_id, extraction_source,
                timeline_sort_start, timeline_sort_end, visibility,
            ),
        )
        self.conn.commit()

    def get_lore_entry(self, entry_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM lore_entries WHERE entry_id = ?", (entry_id,)
        ).fetchone()
        if row is None:
            return None
        d = self._row_to_dict(row)
        d["canon_override"] = bool(d.get("canon_override", 0))
        return d

    _LORE_ENTRY_COLUMNS = {
        "category", "title", "content", "status", "valid_from", "valid_until",
        "thematic_notes", "speech_patterns", "canon_override", "override_notes",
        "tags", "source_project_id", "introduced_in_project_id", "extraction_source",
        "timeline_sort_start", "timeline_sort_end", "visibility",
    }

    def update_lore_entry(self, entry_id: str, **kwargs) -> None:
        if not kwargs:
            return
        invalid = set(kwargs) - self._LORE_ENTRY_COLUMNS
        if invalid:
            raise ValueError(f"Invalid column(s) for lore_entries: {invalid}")

        if "tags" in kwargs and kwargs["tags"] is not None:
            kwargs["tags"] = json.dumps(kwargs["tags"])
        if "canon_override" in kwargs:
            kwargs["canon_override"] = 1 if kwargs["canon_override"] else 0

        kwargs["updated_at"] = "CURRENT_TIMESTAMP"
        set_parts = []
        values = []
        for k, v in kwargs.items():
            if v == "CURRENT_TIMESTAMP":
                set_parts.append(f"{k} = CURRENT_TIMESTAMP")
            else:
                set_parts.append(f"{k} = ?")
                values.append(v)

        set_clause = ", ".join(set_parts)
        values.append(entry_id)
        self.conn.execute(
            f"UPDATE lore_entries SET {set_clause} WHERE entry_id = ?", values
        )
        self.conn.commit()

    def delete_lore_entry(self, entry_id: str) -> None:
        self.conn.execute(
            "DELETE FROM lore_relations WHERE source_entry_id = ? OR target_entry_id = ?",
            (entry_id, entry_id),
        )
        self.conn.execute(
            "DELETE FROM lore_entries WHERE entry_id = ?", (entry_id,)
        )
        self.conn.commit()

    def list_lore_entries(
        self,
        universe_id: str,
        category: Optional[str] = None,
        status: Optional[str] = None,
        text_search: Optional[str] = None,
    ) -> list[dict]:
        query = "SELECT * FROM lore_entries WHERE universe_id = ?"
        params: list = [universe_id]

        if category:
            query += " AND category = ?"
            params.append(category)
        if status:
            query += " AND status = ?"
            params.append(status)
        if text_search:
            query += " AND (title LIKE ? OR content LIKE ?)"
            pattern = f"%{text_search}%"
            params.extend([pattern, pattern])

        query += " ORDER BY title"
        rows = self.conn.execute(query, params).fetchall()
        results = self._rows_to_dicts(rows)
        for d in results:
            d["canon_override"] = bool(d.get("canon_override", 0))
        return results

    def promote_lore_entry(self, entry_id: str) -> None:
        self.conn.execute(
            "UPDATE lore_entries SET status = 'canonical', updated_at = CURRENT_TIMESTAMP "
            "WHERE entry_id = ?",
            (entry_id,),
        )
        self.conn.commit()

    def deprecate_lore_entry(self, entry_id: str) -> None:
        self.conn.execute(
            "UPDATE lore_entries SET status = 'deprecated', updated_at = CURRENT_TIMESTAMP "
            "WHERE entry_id = ?",
            (entry_id,),
        )
        self.conn.commit()

    def get_terminology_entries(self, universe_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM lore_entries WHERE universe_id = ? "
            "AND category = 'terminology' AND status != 'deprecated' ORDER BY title",
            (universe_id,),
        ).fetchall()
        return self._rows_to_dicts(rows)

    def get_speech_pattern_entries(self, universe_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM lore_entries WHERE universe_id = ? "
            "AND speech_patterns IS NOT NULL AND speech_patterns != '' "
            "AND status != 'deprecated' ORDER BY title",
            (universe_id,),
        ).fetchall()
        return self._rows_to_dicts(rows)

    def get_all_entry_ids(self, universe_id: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT entry_id FROM lore_entries WHERE universe_id = ?",
            (universe_id,),
        ).fetchall()
        return {r["entry_id"] for r in rows}

    # ------------------------------------------------------------------
    # Lore Relations
    # ------------------------------------------------------------------

    def create_relation(
        self,
        source_entry_id: str,
        target_entry_id: str,
        relation_type: str,
        description: Optional[str] = None,
        dialogue_implications: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO lore_relations
               (source_entry_id, target_entry_id, relation_type,
                description, dialogue_implications)
               VALUES (?, ?, ?, ?, ?)""",
            (source_entry_id, target_entry_id, relation_type,
             description, dialogue_implications),
        )
        self.conn.commit()

    def get_relations(self, entry_id: str) -> list[dict]:
        rows = self.conn.execute(
            """SELECT * FROM lore_relations
               WHERE source_entry_id = ? OR target_entry_id = ?""",
            (entry_id, entry_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_relation(
        self,
        source_entry_id: str,
        target_entry_id: str,
        relation_type: str,
    ) -> None:
        self.conn.execute(
            """DELETE FROM lore_relations
               WHERE source_entry_id = ? AND target_entry_id = ?
               AND relation_type = ?""",
            (source_entry_id, target_entry_id, relation_type),
        )
        self.conn.commit()

    def get_dialogue_implications(
        self,
        entry_ids: list[str],
    ) -> list[dict]:
        """Get relations with dialogue implications between the given entries."""
        if not entry_ids:
            return []
        placeholders = ", ".join("?" for _ in entry_ids)
        rows = self.conn.execute(
            f"""SELECT * FROM lore_relations
                WHERE dialogue_implications IS NOT NULL
                AND dialogue_implications != ''
                AND source_entry_id IN ({placeholders})
                AND target_entry_id IN ({placeholders})""",
            entry_ids + entry_ids,
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Project-Universe Binding
    # ------------------------------------------------------------------

    def bind_project(
        self,
        project_id: str,
        universe_id: str,
        reading_order: int = 0,
        timeline_start: Optional[str] = None,
        timeline_end: Optional[str] = None,
    ) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO project_universe_binding
               (project_id, universe_id, reading_order, timeline_start, timeline_end)
               VALUES (?, ?, ?, ?, ?)""",
            (project_id, universe_id, reading_order, timeline_start, timeline_end),
        )
        self.conn.commit()

    def get_project_binding(self, project_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM project_universe_binding WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_project_reading_order(self, project_id: str) -> int | None:
        binding = self.get_project_binding(project_id)
        if binding is None:
            return None
        return binding.get("reading_order", 0)

    # ------------------------------------------------------------------
    # Character-Lore Affiliations
    # ------------------------------------------------------------------

    def affiliate_character(
        self,
        character_id: str,
        entry_id: str,
        affiliation_type: str = "member",
    ) -> None:
        """Register a character's connection to a lore entry (faction/culture)."""
        self.conn.execute(
            """INSERT OR REPLACE INTO character_lore_affiliations
               (character_id, entry_id, affiliation_type)
               VALUES (?, ?, ?)""",
            (character_id, entry_id, affiliation_type),
        )
        self.conn.commit()

    def get_character_affiliations(self, character_id: str) -> list[dict]:
        """Get all lore entries a character is affiliated with."""
        rows = self.conn.execute(
            """SELECT cla.*, le.title, le.category, le.universe_id
               FROM character_lore_affiliations cla
               JOIN lore_entries le ON cla.entry_id = le.entry_id
               WHERE cla.character_id = ?""",
            (character_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_affiliated_characters(self, entry_id: str) -> list[dict]:
        """Get all characters affiliated with a lore entry."""
        rows = self.conn.execute(
            "SELECT * FROM character_lore_affiliations WHERE entry_id = ?",
            (entry_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def remove_character_affiliation(
        self, character_id: str, entry_id: str,
    ) -> None:
        self.conn.execute(
            "DELETE FROM character_lore_affiliations WHERE character_id = ? AND entry_id = ?",
            (character_id, entry_id),
        )
        self.conn.commit()

    def get_lore_for_character(
        self,
        character_id: str,
        universe_id: str,
    ) -> list[dict]:
        """Get lore entries visible to a character based on affiliations + visibility.

        Returns:
          - All 'public' entries in the universe
          - 'faction_internal' entries for factions the character is affiliated with
          - 'secret' entries are excluded (require explicit belief-layer knowledge)
        """
        # Get character's affiliated entry IDs
        affiliations = self.get_character_affiliations(character_id)
        affiliated_ids = {a["entry_id"] for a in affiliations}

        # Get all non-deprecated entries in the universe
        all_entries = self.list_lore_entries(universe_id)

        visible = []
        for entry in all_entries:
            if entry.get("status") == "deprecated":
                continue
            vis = entry.get("visibility", "public")
            if vis == "public":
                visible.append(entry)
            elif vis == "faction_internal" and entry["entry_id"] in affiliated_ids:
                visible.append(entry)
            # 'secret' entries require explicit belief-layer check (handled by LoreService)

        return visible

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None
