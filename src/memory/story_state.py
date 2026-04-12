"""Persistent story state tracker backed by SQLite.

Tracks characters, knowledge, relationships, plot threads, timeline,
Chekhov guns, chapter logs, character arcs, subplot board, hook ledger,
terminology registry, propagation debts, and style fingerprints across
the full novel pipeline.

All data is stored in a single SQLite file (no server needed).
Schema migrations are applied automatically on init.
"""

import hashlib
import json
import logging
import re
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


def _slugify(name: str) -> str:
    """Convert a name to a slug ID. 'Ben Skywalker' -> 'ben_skywalker'"""
    return name.lower().replace(" ", "_").replace("-", "_")


_CHAPTER_REF_RE = re.compile(r"(?:chapter\s*)?(\d+)", re.IGNORECASE)


def _parse_chapter_ref(ref) -> int | None:
    """Parse a chapter reference into an integer chapter number.

    Accepts either an integer (returned as-is), None (returned as None),
    or a string like 'Chapter 1', 'Chapter 4-5', 'Chapter 5 (First Plot Point)',
    'Chapter 10-16'. For ranges, returns the earliest chapter. For unparseable
    strings (including 'next_book'), returns None.
    """
    if ref is None:
        return None
    if isinstance(ref, int):
        return ref
    if isinstance(ref, str):
        match = _CHAPTER_REF_RE.search(ref)
        if match:
            return int(match.group(1))
        return None
    return None


def _normalize_arc_type(raw) -> str | None:
    """Coerce descriptive arc_type strings to the canonical 4-value enum.

    The concept workshop captures arc types as descriptive phrases like
    'Positive change — moves from the lie to the truth' or
    'Flat negative — enters certain, exits certain'. The character_arcs
    table has a strict enum: positive_change, flat, negative, disillusionment.
    This helper extracts the canonical form from descriptive prose.

    Order matters: 'flat negative' should map to 'negative' (the tragic
    'stays in the lie' arc), not 'flat' (the world-changer arc which
    requires the character to already hold the Truth).

    Returns None if the input is empty or unrecognizable.
    """
    if not raw:
        return None
    if not isinstance(raw, str):
        return None
    lower = raw.strip().lower()
    if not lower:
        return None
    # Exact enum match is the cleanest signal.
    if lower in ARC_TYPES:
        return lower
    # Order matters: disillusionment and negative before flat/positive.
    if "disillusionment" in lower:
        return "disillusionment"
    if "negative" in lower:
        return "negative"
    if "positive" in lower:
        # Catches 'positive change', 'minor positive', etc.
        return "positive_change"
    if lower.startswith("flat"):
        return "flat"
    return None


# Valid Weiland arc phases in progression order.
ARC_PHASES = [
    "lie_reinforced",
    "lie_questioned",
    "lie_cracking",
    "lie_confronted",
    "truth_accepted",
    "truth_rejected",
]

ARC_TYPES = ["positive_change", "flat", "negative", "disillusionment"]

HOOK_TYPES = ["chekhov", "foreshadow", "setup_callback", "thematic_echo", "mystery_question"]

HOOK_PRIORITIES = ["hard", "soft", "series"]

HOOK_STATUSES = ["planted", "advancing", "resolved", "subverted", "abandoned"]

SUBPLOT_LINE_TYPES = ["A", "B", "C", "D"]

SUBPLOT_STATUSES = ["planned", "active", "climaxing", "resolved", "abandoned"]

TERMINOLOGY_CATEGORIES = [
    "character_name", "place_name", "faction", "artifact",
    "concept", "species", "title",
]


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

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);
"""


# ------------------------------------------------------------------
# Migration functions
# ------------------------------------------------------------------

def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """Phase 5 migration: add character_arcs, subplots, hooks,
    terminology_registry, propagation_debts, style_fingerprint tables."""

    conn.executescript("""
    CREATE TABLE IF NOT EXISTS character_arcs (
        character_id TEXT NOT NULL,
        book_number INTEGER NOT NULL DEFAULT 1,
        lie_believed TEXT,
        ghost TEXT,
        want TEXT,
        need TEXT,
        arc_type TEXT CHECK(arc_type IN (
            'positive_change', 'flat', 'negative', 'disillusionment'
        )),
        current_phase TEXT NOT NULL DEFAULT 'lie_reinforced'
            CHECK(current_phase IN (
                'lie_reinforced', 'lie_questioned', 'lie_cracking',
                'lie_confronted', 'truth_accepted', 'truth_rejected'
            )),
        phase_chapter INTEGER,
        phase_evidence TEXT,
        arc_phase_targets TEXT,
        PRIMARY KEY (character_id, book_number),
        FOREIGN KEY (character_id) REFERENCES characters(id)
    );

    CREATE TABLE IF NOT EXISTS subplots (
        subplot_id TEXT PRIMARY KEY,
        subplot_name TEXT NOT NULL,
        line_type TEXT NOT NULL CHECK(line_type IN ('A', 'B', 'C', 'D')),
        characters_involved TEXT,
        start_chapter INTEGER,
        resolution_chapter INTEGER,
        structural_purpose TEXT,
        interweave_points TEXT,
        current_status TEXT DEFAULT 'planned'
            CHECK(current_status IN (
                'planned', 'active', 'climaxing', 'resolved', 'abandoned'
            )),
        book_number INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS hooks (
        hook_id TEXT PRIMARY KEY,
        description TEXT NOT NULL,
        hook_type TEXT NOT NULL CHECK(hook_type IN (
            'chekhov', 'foreshadow', 'setup_callback',
            'thematic_echo', 'mystery_question'
        )),
        planted_chapter INTEGER NOT NULL,
        planted_book INTEGER DEFAULT 1,
        payoff_chapter INTEGER,
        payoff_book INTEGER,
        advancement_chapters TEXT,
        priority TEXT NOT NULL CHECK(priority IN ('hard', 'soft', 'series')),
        related_subplot TEXT,
        current_status TEXT DEFAULT 'planted'
            CHECK(current_status IN (
                'planted', 'advancing', 'resolved', 'subverted', 'abandoned'
            )),
        last_advanced_chapter INTEGER,
        mention_only_count INTEGER DEFAULT 0,
        FOREIGN KEY (related_subplot) REFERENCES subplots(subplot_id)
    );

    CREATE TABLE IF NOT EXISTS terminology_registry (
        term TEXT PRIMARY KEY,
        aliases TEXT,
        definition TEXT NOT NULL,
        category TEXT NOT NULL CHECK(category IN (
            'character_name', 'place_name', 'faction', 'artifact',
            'concept', 'species', 'title'
        )),
        first_appearance_chapter INTEGER,
        book_number INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS propagation_debts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_layer TEXT NOT NULL,
        change_description TEXT NOT NULL,
        affected_chapters TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        resolved_at TIMESTAMP,
        resolution_method TEXT
    );

    CREATE TABLE IF NOT EXISTS style_fingerprint (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        metric_name TEXT NOT NULL,
        metric_value TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """Multi-scene migration: add scene_log table with composite PK."""
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS scene_log (
        chapter_number INTEGER NOT NULL,
        scene_number INTEGER NOT NULL,
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
        revised_at TIMESTAMP,
        PRIMARY KEY (chapter_number, scene_number)
    );
    """)


# Ordered list of migrations. Each entry is (version, description, callable).
_MIGRATIONS: list[tuple[int, str, callable]] = [
    (2, "Phase 5: character arcs, subplot board, hook ledger, terminology, propagation debts, style fingerprint", _migrate_v1_to_v2),
    (3, "Multi-scene: scene_log table with composite PK", _migrate_v2_to_v3),
]


class StoryState:
    """SQLite-backed persistent story state for the novel pipeline."""

    def __init__(self, db_path: str = "data/story_state.db") -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.executescript(_SCHEMA_SQL)
        self.conn.commit()

        # Seed baseline migration version if schema_migrations is empty
        row = self.conn.execute(
            "SELECT MAX(version) as v FROM schema_migrations"
        ).fetchone()
        if row["v"] is None:
            self.conn.execute(
                "INSERT INTO schema_migrations (version, description) VALUES (?, ?)",
                (1, "Baseline: Phase 1-4 schema (7 tables)"),
            )
            self.conn.commit()

        # Run pending migrations
        self._run_migrations()

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
        """Return the current schema version number."""
        row = self.conn.execute(
            "SELECT MAX(version) as v FROM schema_migrations"
        ).fetchone()
        return row["v"] if row["v"] is not None else 0

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
            """INSERT OR IGNORE INTO characters
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
            d["inventory"] = _safe_json_loads(d["inventory"], [], "inventory")
        return d

    _CHARACTER_COLUMNS = {
        "name", "current_location", "emotional_state",
        "arc_position", "inventory",
        "last_appearance_chapter", "last_appearance_scene",
    }

    def update_character(self, id: str, **kwargs: object) -> None:
        """Update only the provided fields for a character."""
        if not kwargs:
            return
        invalid = set(kwargs) - self._CHARACTER_COLUMNS
        if invalid:
            raise ValueError(f"Invalid column(s) for characters: {invalid}")
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
                d["inventory"] = _safe_json_loads(d["inventory"], [], "inventory")
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # Bulk Init
    # ------------------------------------------------------------------

    def init_from_concept_seed(self, concept_seed: dict) -> None:
        """Populate tables from a concept seed.

        Populates: characters, character_arcs (if weiland_arc present),
        terminology_registry, subplots, hooks.
        All Phase 5 fields are optional for consumers that don't use them.

        Expects the canonical workshop-native seed format: top-level
        ``subplots`` and ``hooks`` arrays, ``canonical_form`` or ``term``
        for terminology entries, and chapter references that may be either
        integers or strings like 'Chapter 1' or 'Chapter 4-5' (parsed via
        ``_parse_chapter_ref``).
        """
        book_number = concept_seed.get("meta", {}).get("book_number", 1)

        # Characters + arcs
        for char in concept_seed.get("ensemble_cast", []):
            char_id = _slugify(char["name"])
            self.add_character(
                id=char_id,
                name=char["name"],
                arc_position=char.get("role"),
            )
            # Phase 5: Weiland character arc
            weiland = char.get("weiland_arc")
            if weiland:
                # Normalize descriptive arc_type strings to the canonical
                # enum (positive_change/flat/negative/disillusionment).
                # The workshop captures these as prose; the DB has a strict
                # CHECK constraint.
                arc_type = _normalize_arc_type(weiland.get("arc_type"))
                if arc_type is None:
                    logger.warning(
                        "Skipping character arc for '%s': arc_type '%s' "
                        "is not recognizable. Expected one of %s or a "
                        "descriptive phrase containing one of those keywords.",
                        char["name"], weiland.get("arc_type"), ARC_TYPES,
                    )
                else:
                    self.add_character_arc(
                        character_id=char_id,
                        book_number=book_number,
                        lie_believed=weiland.get("lie_believed"),
                        ghost=weiland.get("ghost"),
                        want=weiland.get("want"),
                        need=weiland.get("need"),
                        arc_type=arc_type,
                        arc_phase_targets=weiland.get("arc_phase_targets")
                        or weiland.get("arc_phase_map"),
                    )

        # Phase 5: Terminology registry
        for term_entry in concept_seed.get("terminology_registry", []):
            # Accept both 'term' (canonical) and 'canonical_form' (workshop-native)
            term_name = term_entry.get("term") or term_entry.get("canonical_form")
            if not term_name:
                logger.warning(
                    "Skipping terminology entry with no 'term' or 'canonical_form': %s",
                    term_entry,
                )
                continue
            # first_appearance may be int, string ('Chapter 1'), or missing
            first_appearance_chapter = _parse_chapter_ref(
                term_entry.get("first_appearance")
            )
            # Coerce unknown categories to 'other' rather than failing the insert
            category = term_entry.get("category", "concept")
            if category not in TERMINOLOGY_CATEGORIES:
                logger.debug(
                    "Terminology category '%s' not in canonical set; storing as 'other'",
                    category,
                )
                category = "other" if "other" in TERMINOLOGY_CATEGORIES else "concept"
            self.add_term(
                term=term_name,
                definition=term_entry.get("definition", ""),
                category=category,
                aliases=term_entry.get("aliases"),
                first_appearance_chapter=first_appearance_chapter,
                book_number=book_number,
            )

        # Phase 5: Subplots
        # Workshop-native format: ``subplots`` array with name/function/
        # arc_summary/chapters_active fields. start_chapter/resolution_chapter
        # are derived from chapters_active.
        for subplot in concept_seed.get("subplots", []):
            chapters_active = subplot.get("chapters_active") or []
            start_chapter = min(chapters_active) if chapters_active else None
            resolution_chapter = max(chapters_active) if chapters_active else None
            self.add_subplot(
                subplot_id=subplot["subplot_id"],
                subplot_name=subplot.get("name") or subplot["subplot_id"],
                line_type=subplot.get("line_type", "B"),
                characters_involved=subplot.get("characters_involved"),
                start_chapter=start_chapter,
                resolution_chapter=resolution_chapter,
                structural_purpose=subplot.get("function") or subplot.get("arc_summary"),
                interweave_points=chapters_active or None,
                current_status=subplot.get("current_status", "planned"),
                book_number=book_number,
            )

        # Phase 5: Hooks
        # Workshop-native format: ``hooks`` array with hook_type field carrying
        # the priority (hard/soft/series). The DB's hook_type column is a
        # narrative classification (chekhov/foreshadow/etc.) — we default that
        # to 'foreshadow' here and derive the DB priority column from the seed's
        # hook_type value.
        for hook in concept_seed.get("hooks", []):
            seed_hook_type = hook.get("hook_type")
            if seed_hook_type in HOOK_PRIORITIES:
                priority = seed_hook_type
            else:
                priority = "soft"
            planted_chapter = _parse_chapter_ref(hook.get("planted_in")) or 1
            payoff_chapter = _parse_chapter_ref(hook.get("resolved_in"))
            self.add_hook(
                hook_id=hook["hook_id"],
                description=hook.get("description", ""),
                hook_type="foreshadow",
                planted_chapter=planted_chapter,
                planted_book=book_number,
                payoff_chapter=payoff_chapter,
                payoff_book=hook.get("payoff_book"),
                advancement_chapters=hook.get("advancement_chapters"),
                priority=priority,
                related_subplot=hook.get("related_subplot"),
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
            """INSERT OR IGNORE INTO character_relationships
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

    _RELATIONSHIP_COLUMNS = {
        "relationship_type", "status", "last_updated_chapter",
    }

    def update_relationship(
        self, character_a: str, character_b: str, **kwargs: object
    ) -> None:
        """Update fields on an existing relationship."""
        if not kwargs:
            return
        invalid = set(kwargs) - self._RELATIONSHIP_COLUMNS
        if invalid:
            raise ValueError(f"Invalid column(s) for character_relationships: {invalid}")
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
            """INSERT OR IGNORE INTO plot_threads
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
            d["related_characters"] = _safe_json_loads(d["related_characters"], [], "related_characters")
        return d

    _PLOT_THREAD_COLUMNS = {
        "description", "status", "planted_chapter",
        "urgency", "related_characters", "resolution_notes",
    }

    def update_plot_thread(self, id: str, **kwargs: object) -> None:
        """Update only the provided fields for a plot thread."""
        if not kwargs:
            return
        invalid = set(kwargs) - self._PLOT_THREAD_COLUMNS
        if invalid:
            raise ValueError(f"Invalid column(s) for plot_threads: {invalid}")
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
                d["related_characters"] = _safe_json_loads(d["related_characters"], [], "related_characters")
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
            """INSERT OR IGNORE INTO timeline
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
                d["key_events"] = _safe_json_loads(d["key_events"], [], "key_events")
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
            """INSERT OR IGNORE INTO chekhov_guns
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
            """INSERT OR REPLACE INTO chapter_log
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
            d["quality_scores"] = _safe_json_loads(d["quality_scores"], {}, "quality_scores")
        if d["failure_codes"] is not None:
            d["failure_codes"] = _safe_json_loads(d["failure_codes"], [], "failure_codes")
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
    # Scene Log (multi-scene chapter support)
    # ------------------------------------------------------------------

    def add_scene_log(
        self,
        chapter_number: int,
        scene_number: int,
        word_count: int | None = None,
        structural_phase: str | None = None,
        pov_character: str | None = None,
        summary: str | None = None,
        quality_scores: dict | None = None,
        failure_codes: list | None = None,
        revision_status: str = "draft",
    ) -> None:
        """Insert or replace a scene log entry."""
        self.conn.execute(
            """INSERT OR REPLACE INTO scene_log
               (chapter_number, scene_number, word_count, structural_phase,
                pov_character, summary, quality_scores, failure_codes,
                revision_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                chapter_number,
                scene_number,
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

    def get_scene_log(self, chapter_number: int, scene_number: int) -> dict | None:
        """Fetch a single scene log entry by (chapter, scene)."""
        row = self.conn.execute(
            "SELECT * FROM scene_log WHERE chapter_number = ? AND scene_number = ?",
            (chapter_number, scene_number),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["quality_scores"] is not None:
            d["quality_scores"] = _safe_json_loads(d["quality_scores"], {}, "quality_scores")
        if d["failure_codes"] is not None:
            d["failure_codes"] = _safe_json_loads(d["failure_codes"], [], "failure_codes")
        return d

    def get_chapter_scenes(self, chapter_number: int) -> list[dict]:
        """Return all scene logs for a chapter, ordered by scene_number."""
        rows = self.conn.execute(
            "SELECT * FROM scene_log WHERE chapter_number = ? ORDER BY scene_number",
            (chapter_number,),
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d["quality_scores"] is not None:
                d["quality_scores"] = _safe_json_loads(d["quality_scores"], {}, "quality_scores")
            if d["failure_codes"] is not None:
                d["failure_codes"] = _safe_json_loads(d["failure_codes"], [], "failure_codes")
            results.append(d)
        return results

    def get_chapter_aggregate(self, chapter_number: int) -> dict:
        """Return aggregated stats for a chapter: total_word_count, scene_count."""
        row = self.conn.execute(
            """SELECT COUNT(*) as scene_count, COALESCE(SUM(word_count), 0) as total_word_count
               FROM scene_log WHERE chapter_number = ?""",
            (chapter_number,),
        ).fetchone()
        return dict(row)

    def update_scene_log(self, chapter_number: int, scene_number: int, **kwargs: object) -> None:
        """Update only the provided fields for a scene log entry."""
        if not kwargs:
            return
        if "quality_scores" in kwargs and kwargs["quality_scores"] is not None:
            kwargs["quality_scores"] = json.dumps(kwargs["quality_scores"])
        if "failure_codes" in kwargs and kwargs["failure_codes"] is not None:
            kwargs["failure_codes"] = json.dumps(kwargs["failure_codes"])

        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [chapter_number, scene_number]
        self.conn.execute(
            f"UPDATE scene_log SET {set_clause} WHERE chapter_number = ? AND scene_number = ?",
            values,
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Character Arcs (Weiland)
    # ------------------------------------------------------------------

    def add_character_arc(
        self,
        character_id: str,
        book_number: int = 1,
        lie_believed: str | None = None,
        ghost: str | None = None,
        want: str | None = None,
        need: str | None = None,
        arc_type: str | None = None,
        current_phase: str = "lie_reinforced",
        phase_chapter: int | None = None,
        phase_evidence: str | None = None,
        arc_phase_targets: dict | None = None,
    ) -> None:
        """Insert a Weiland character arc entry."""
        self.conn.execute(
            """INSERT OR IGNORE INTO character_arcs
               (character_id, book_number, lie_believed, ghost, want, need,
                arc_type, current_phase, phase_chapter, phase_evidence, arc_phase_targets)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                character_id, book_number, lie_believed, ghost, want, need,
                arc_type, current_phase, phase_chapter, phase_evidence,
                json.dumps(arc_phase_targets) if arc_phase_targets is not None else None,
            ),
        )
        self.conn.commit()

    def get_character_arc(
        self, character_id: str, book_number: int = 1
    ) -> dict | None:
        """Fetch a character's arc for a specific book."""
        row = self.conn.execute(
            "SELECT * FROM character_arcs WHERE character_id = ? AND book_number = ?",
            (character_id, book_number),
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["arc_phase_targets"] is not None:
            d["arc_phase_targets"] = _safe_json_loads(d["arc_phase_targets"], {}, "arc_phase_targets")
        return d

    def update_character_arc(
        self, character_id: str, book_number: int = 1, **kwargs: object
    ) -> None:
        """Update fields on an existing character arc."""
        if not kwargs:
            return
        if "arc_phase_targets" in kwargs and kwargs["arc_phase_targets"] is not None:
            kwargs["arc_phase_targets"] = json.dumps(kwargs["arc_phase_targets"])
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [character_id, book_number]
        self.conn.execute(
            f"UPDATE character_arcs SET {set_clause} WHERE character_id = ? AND book_number = ?",
            values,
        )
        self.conn.commit()

    def get_all_character_arcs(self, book_number: int | None = None) -> list[dict]:
        """Return all character arcs, optionally filtered by book."""
        if book_number is not None:
            rows = self.conn.execute(
                "SELECT * FROM character_arcs WHERE book_number = ?",
                (book_number,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM character_arcs").fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d["arc_phase_targets"] is not None:
                d["arc_phase_targets"] = _safe_json_loads(d["arc_phase_targets"], {}, "arc_phase_targets")
            results.append(d)
        return results

    def advance_arc_phase(
        self,
        character_id: str,
        new_phase: str,
        chapter: int,
        evidence: str | None = None,
        book_number: int = 1,
    ) -> bool:
        """Advance a character's arc phase. Returns False if transition is invalid.

        Valid transitions follow ARC_PHASES order. Negative arcs may end at
        truth_rejected instead of truth_accepted. Phase cannot go backwards
        or skip more than one step ahead.
        """
        arc = self.get_character_arc(character_id, book_number)
        if arc is None:
            return False

        current = arc["current_phase"]
        if current not in ARC_PHASES or new_phase not in ARC_PHASES:
            return False

        current_idx = ARC_PHASES.index(current)
        new_idx = ARC_PHASES.index(new_phase)

        # Cannot go backwards
        if new_idx <= current_idx:
            return False

        # Cannot skip more than one phase ahead
        if new_idx > current_idx + 1:
            # Exception: truth_accepted and truth_rejected are peers (both index 4/5)
            if not (current_idx == 3 and new_idx in (4, 5)):
                return False

        self.update_character_arc(
            character_id,
            book_number,
            current_phase=new_phase,
            phase_chapter=chapter,
            phase_evidence=evidence,
        )
        return True

    # ------------------------------------------------------------------
    # Subplot Board
    # ------------------------------------------------------------------

    def add_subplot(
        self,
        subplot_id: str,
        subplot_name: str,
        line_type: str = "B",
        characters_involved: list | None = None,
        start_chapter: int | None = None,
        resolution_chapter: int | None = None,
        structural_purpose: str | None = None,
        interweave_points: list | None = None,
        current_status: str = "planned",
        book_number: int = 1,
    ) -> None:
        """Insert a new subplot into the subplot board."""
        self.conn.execute(
            """INSERT OR IGNORE INTO subplots
               (subplot_id, subplot_name, line_type, characters_involved,
                start_chapter, resolution_chapter, structural_purpose,
                interweave_points, current_status, book_number)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                subplot_id, subplot_name, line_type,
                json.dumps(characters_involved) if characters_involved is not None else None,
                start_chapter, resolution_chapter, structural_purpose,
                json.dumps(interweave_points) if interweave_points is not None else None,
                current_status, book_number,
            ),
        )
        self.conn.commit()

    def get_subplot(self, subplot_id: str) -> dict | None:
        """Fetch a single subplot by ID."""
        row = self.conn.execute(
            "SELECT * FROM subplots WHERE subplot_id = ?", (subplot_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["characters_involved"] is not None:
            d["characters_involved"] = _safe_json_loads(d["characters_involved"], [], "characters_involved")
        if d["interweave_points"] is not None:
            d["interweave_points"] = _safe_json_loads(d["interweave_points"], [], "interweave_points")
        return d

    def update_subplot(self, subplot_id: str, **kwargs: object) -> None:
        """Update fields on an existing subplot."""
        if not kwargs:
            return
        if "characters_involved" in kwargs and kwargs["characters_involved"] is not None:
            kwargs["characters_involved"] = json.dumps(kwargs["characters_involved"])
        if "interweave_points" in kwargs and kwargs["interweave_points"] is not None:
            kwargs["interweave_points"] = json.dumps(kwargs["interweave_points"])
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [subplot_id]
        self.conn.execute(
            f"UPDATE subplots SET {set_clause} WHERE subplot_id = ?", values
        )
        self.conn.commit()

    def get_active_subplots(self, book_number: int | None = None) -> list[dict]:
        """Return subplots that are not resolved or abandoned."""
        query = "SELECT * FROM subplots WHERE current_status NOT IN ('resolved', 'abandoned')"
        params: list = []
        if book_number is not None:
            query += " AND book_number = ?"
            params.append(book_number)
        rows = self.conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d["characters_involved"] is not None:
                d["characters_involved"] = _safe_json_loads(d["characters_involved"], [], "characters_involved")
            if d["interweave_points"] is not None:
                d["interweave_points"] = _safe_json_loads(d["interweave_points"], [], "interweave_points")
            results.append(d)
        return results

    def get_all_subplots(self, book_number: int | None = None) -> list[dict]:
        """Return all subplots, optionally filtered by book."""
        if book_number is not None:
            rows = self.conn.execute(
                "SELECT * FROM subplots WHERE book_number = ?", (book_number,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM subplots").fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d["characters_involved"] is not None:
                d["characters_involved"] = _safe_json_loads(d["characters_involved"], [], "characters_involved")
            if d["interweave_points"] is not None:
                d["interweave_points"] = _safe_json_loads(d["interweave_points"], [], "interweave_points")
            results.append(d)
        return results

    # ------------------------------------------------------------------
    # Hook Ledger
    # ------------------------------------------------------------------

    def add_hook(
        self,
        hook_id: str,
        description: str,
        hook_type: str,
        planted_chapter: int,
        planted_book: int = 1,
        payoff_chapter: int | None = None,
        payoff_book: int | None = None,
        advancement_chapters: list | None = None,
        priority: str = "soft",
        related_subplot: str | None = None,
        current_status: str = "planted",
    ) -> None:
        """Insert a new hook into the hook ledger."""
        self.conn.execute(
            """INSERT OR IGNORE INTO hooks
               (hook_id, description, hook_type, planted_chapter, planted_book,
                payoff_chapter, payoff_book, advancement_chapters, priority,
                related_subplot, current_status, last_advanced_chapter, mention_only_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                hook_id, description, hook_type, planted_chapter, planted_book,
                payoff_chapter, payoff_book,
                json.dumps(advancement_chapters) if advancement_chapters is not None else None,
                priority, related_subplot, current_status, None, 0,
            ),
        )
        self.conn.commit()

    def get_hook(self, hook_id: str) -> dict | None:
        """Fetch a single hook by ID."""
        row = self.conn.execute(
            "SELECT * FROM hooks WHERE hook_id = ?", (hook_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["advancement_chapters"] is not None:
            d["advancement_chapters"] = _safe_json_loads(d["advancement_chapters"], [], "advancement_chapters")
        return d

    def update_hook(self, hook_id: str, **kwargs: object) -> None:
        """Update fields on an existing hook."""
        if not kwargs:
            return
        if "advancement_chapters" in kwargs and kwargs["advancement_chapters"] is not None:
            kwargs["advancement_chapters"] = json.dumps(kwargs["advancement_chapters"])
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [hook_id]
        self.conn.execute(
            f"UPDATE hooks SET {set_clause} WHERE hook_id = ?", values
        )
        self.conn.commit()

    def get_all_hooks(self, book_number: int | None = None) -> list[dict]:
        """Return all hooks, optionally filtered by planted_book."""
        if book_number is not None:
            rows = self.conn.execute(
                "SELECT * FROM hooks WHERE planted_book = ?", (book_number,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM hooks").fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d["advancement_chapters"] is not None:
                d["advancement_chapters"] = _safe_json_loads(d["advancement_chapters"], [], "advancement_chapters")
            results.append(d)
        return results

    def can_admit_hook(self, priority: str, target_chapters: int) -> bool:
        """Check if a new hook at the given priority can be admitted.

        Hard hook budget: target_chapters / 3 (rounded down).
        Soft and series hooks are always admitted.
        """
        if priority != "hard":
            return True
        budget = max(1, target_chapters // 3)
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM hooks "
            "WHERE priority = 'hard' AND current_status NOT IN ('resolved', 'subverted', 'abandoned')"
        ).fetchone()
        return row["cnt"] < budget

    def advance_hook(
        self,
        hook_id: str,
        chapter: int,
        is_real_advancement: bool = True,
    ) -> dict | None:
        """Record a hook advancement. Returns warning dict if mention_only_count > 2."""
        hook = self.get_hook(hook_id)
        if hook is None:
            return None

        warning = None
        if is_real_advancement:
            chapters = hook.get("advancement_chapters") or []
            chapters.append(chapter)
            self.update_hook(
                hook_id,
                advancement_chapters=chapters,
                last_advanced_chapter=chapter,
                current_status="advancing",
            )
        else:
            new_count = (hook.get("mention_only_count") or 0) + 1
            self.update_hook(hook_id, mention_only_count=new_count)
            if new_count > 2:
                warning = {
                    "hook_id": hook_id,
                    "mention_only_count": new_count,
                    "message": f"Hook '{hook_id}' mentioned {new_count} times without real advancement — flag for review",
                }

        return warning

    def get_hook_debt(self, current_chapter: int | None = None) -> list[dict]:
        """Return hard hooks past their expected payoff chapter without resolution."""
        query = (
            "SELECT * FROM hooks "
            "WHERE priority = 'hard' "
            "AND current_status NOT IN ('resolved', 'subverted', 'abandoned') "
            "AND payoff_chapter IS NOT NULL"
        )
        params: list = []
        if current_chapter is not None:
            query += " AND payoff_chapter <= ?"
            params.append(current_chapter)
        rows = self.conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d["advancement_chapters"] is not None:
                d["advancement_chapters"] = _safe_json_loads(d["advancement_chapters"], [], "advancement_chapters")
            results.append(d)
        return results

    def get_chapter_hook_agenda(self, chapter: int) -> dict:
        """Return hooks to plant, advance, or resolve in a given chapter.

        Returns dict with keys: 'to_plant', 'to_advance', 'to_resolve'.
        """
        agenda: dict[str, list[dict]] = {
            "to_plant": [],
            "to_advance": [],
            "to_resolve": [],
        }

        all_hooks = self.get_all_hooks()
        for hook in all_hooks:
            if hook["planted_chapter"] == chapter and hook["current_status"] == "planted":
                # Hook should be planted this chapter (may already be in DB from concept seed)
                agenda["to_plant"].append(hook)
            elif hook["payoff_chapter"] == chapter and hook["current_status"] not in (
                "resolved", "subverted", "abandoned"
            ):
                agenda["to_resolve"].append(hook)
            else:
                # Check if this chapter is in the advancement_chapters list
                adv = hook.get("advancement_chapters") or []
                if chapter in adv and hook["current_status"] not in (
                    "resolved", "subverted", "abandoned"
                ):
                    agenda["to_advance"].append(hook)
                # Also advance if hook is active and this chapter is between plant and payoff
                elif (
                    hook["current_status"] in ("planted", "advancing")
                    and hook["planted_chapter"] < chapter
                    and (hook["payoff_chapter"] is None or chapter < hook["payoff_chapter"])
                ):
                    # Check interweave points from related subplot
                    if hook["related_subplot"]:
                        subplot = self.get_subplot(hook["related_subplot"])
                        if subplot and subplot.get("interweave_points"):
                            if chapter in subplot["interweave_points"]:
                                agenda["to_advance"].append(hook)

        return agenda

    # ------------------------------------------------------------------
    # Terminology Registry
    # ------------------------------------------------------------------

    def add_term(
        self,
        term: str,
        definition: str,
        category: str,
        aliases: list | None = None,
        first_appearance_chapter: int | None = None,
        book_number: int = 1,
    ) -> None:
        """Insert a new term into the terminology registry."""
        self.conn.execute(
            """INSERT OR IGNORE INTO terminology_registry
               (term, aliases, definition, category, first_appearance_chapter, book_number)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                term,
                json.dumps(aliases) if aliases is not None else None,
                definition, category, first_appearance_chapter, book_number,
            ),
        )
        self.conn.commit()

    def get_term(self, term: str) -> dict | None:
        """Fetch a single term by its canonical form."""
        row = self.conn.execute(
            "SELECT * FROM terminology_registry WHERE term = ?", (term,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["aliases"] is not None:
            d["aliases"] = _safe_json_loads(d["aliases"], [], "aliases")
        return d

    def update_term(self, term: str, **kwargs: object) -> None:
        """Update fields on an existing term."""
        if not kwargs:
            return
        if "aliases" in kwargs and kwargs["aliases"] is not None:
            kwargs["aliases"] = json.dumps(kwargs["aliases"])
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = list(kwargs.values()) + [term]
        self.conn.execute(
            f"UPDATE terminology_registry SET {set_clause} WHERE term = ?", values
        )
        self.conn.commit()

    def get_all_terms(self, book_number: int | None = None) -> list[dict]:
        """Return all terms, optionally filtered by book."""
        if book_number is not None:
            rows = self.conn.execute(
                "SELECT * FROM terminology_registry WHERE book_number = ?",
                (book_number,),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM terminology_registry").fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d["aliases"] is not None:
                d["aliases"] = _safe_json_loads(d["aliases"], [], "aliases")
            results.append(d)
        return results

    def find_term(self, search: str) -> dict | None:
        """Find a term by canonical form or alias (case-insensitive)."""
        # First try exact canonical match
        term = self.get_term(search)
        if term is not None:
            return term
        # Search aliases
        rows = self.conn.execute("SELECT * FROM terminology_registry").fetchall()
        search_lower = search.lower()
        for row in rows:
            d = dict(row)
            if d["term"].lower() == search_lower:
                if d["aliases"] is not None:
                    d["aliases"] = _safe_json_loads(d["aliases"], [], "aliases")
                return d
            if d["aliases"]:
                aliases = _safe_json_loads(d["aliases"], [], "aliases")
                if any(a.lower() == search_lower for a in aliases):
                    d["aliases"] = aliases
                    return d
        return None

    # ------------------------------------------------------------------
    # Propagation Debts
    # ------------------------------------------------------------------

    def add_propagation_debt(
        self,
        source_layer: str,
        change_description: str,
        affected_chapters: list[int],
        resolution_method: str | None = None,
    ) -> int:
        """Insert a propagation debt. Returns the new debt ID."""
        cursor = self.conn.execute(
            """INSERT OR IGNORE INTO propagation_debts
               (source_layer, change_description, affected_chapters, resolution_method)
               VALUES (?, ?, ?, ?)""",
            (source_layer, change_description, json.dumps(affected_chapters), resolution_method),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_propagation_debt(self, debt_id: int) -> dict | None:
        """Fetch a single propagation debt."""
        row = self.conn.execute(
            "SELECT * FROM propagation_debts WHERE id = ?", (debt_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        if d["affected_chapters"] is not None:
            d["affected_chapters"] = _safe_json_loads(d["affected_chapters"], [], "affected_chapters")
        return d

    def get_pending_debts(self) -> list[dict]:
        """Return all unresolved propagation debts."""
        rows = self.conn.execute(
            "SELECT * FROM propagation_debts WHERE resolved_at IS NULL"
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d["affected_chapters"] is not None:
                d["affected_chapters"] = _safe_json_loads(d["affected_chapters"], [], "affected_chapters")
            results.append(d)
        return results

    def resolve_propagation_debt(
        self, debt_id: int, resolution_method: str = "manual_review"
    ) -> None:
        """Mark a propagation debt as resolved."""
        self.conn.execute(
            "UPDATE propagation_debts SET resolved_at = CURRENT_TIMESTAMP, resolution_method = ? WHERE id = ?",
            (resolution_method, debt_id),
        )
        self.conn.commit()

    # ------------------------------------------------------------------
    # Style Fingerprint
    # ------------------------------------------------------------------

    def add_style_metric(
        self,
        source: str,
        metric_name: str,
        metric_value: object,
    ) -> int:
        """Insert a style fingerprint metric. Returns the new ID."""
        cursor = self.conn.execute(
            """INSERT OR IGNORE INTO style_fingerprint (source, metric_name, metric_value)
               VALUES (?, ?, ?)""",
            (source, metric_name, json.dumps(metric_value)),
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_style_metrics(self, source: str | None = None) -> list[dict]:
        """Return style metrics, optionally filtered by source."""
        if source is not None:
            rows = self.conn.execute(
                "SELECT * FROM style_fingerprint WHERE source = ?", (source,)
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM style_fingerprint").fetchall()
        results = []
        for row in rows:
            d = dict(row)
            d["metric_value"] = _safe_json_loads(d["metric_value"], "", "metric_value")
            results.append(d)
        return results

    def get_style_fingerprint_dict(self, source: str) -> dict:
        """Return style metrics as a {metric_name: metric_value} dict for a source."""
        metrics = self.get_style_metrics(source)
        return {m["metric_name"]: m["metric_value"] for m in metrics}

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_state_hash(self) -> str:
        """Return a SHA-256 hash of the current state across all tracked tables.

        Used by the state diff system for before/after comparison.
        """
        characters = self.get_all_characters()
        threads = self.get_active_threads()
        knowledge = self.get_knowledge()
        arcs = self.get_all_character_arcs()
        hooks = self.get_all_hooks()
        subplots = self.get_all_subplots()

        state = {
            "characters": characters,
            "plot_threads": threads,
            "knowledge": knowledge,
            "character_arcs": arcs,
            "hooks": hooks,
            "subplots": subplots,
        }
        serialized = json.dumps(state, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()
