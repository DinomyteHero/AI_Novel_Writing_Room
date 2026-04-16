"""High-level worldbuilding service composing SQLite and ChromaDB.

Provides CRUD with dual-write (write-ahead sync pattern), semantic retrieval
with timeline/spoiler filtering, terminology always-include, dialogue context,
canon override resolution, and LLM-assisted extraction.
"""

import logging
import uuid
from typing import Optional, TYPE_CHECKING

from src.worldbuilding.worldbuilding_db import WorldbuildingDB
from src.worldbuilding.lore_vectorstore import LoreVectorStore

if TYPE_CHECKING:
    from src.model_router import ModelRouter

logger = logging.getLogger(__name__)


class LoreService:
    """Orchestrates worldbuilding persistence across SQLite and ChromaDB.

    All write operations use a write-ahead pattern:
      1. Begin SQLite transaction
      2. Write to SQLite
      3. Write to ChromaDB
      4. If ChromaDB fails -> rollback SQLite
      5. If ChromaDB succeeds -> commit SQLite
    """

    def __init__(
        self,
        db: WorldbuildingDB,
        vectorstore: LoreVectorStore,
    ):
        self.db = db
        self.vectorstore = vectorstore

    # ------------------------------------------------------------------
    # Universe CRUD (SQLite only — no vector data)
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
        self.db.create_universe(
            universe_id, display_name, parent_universe_id,
            franchise, description, embedding_model, timeline_system,
        )

    def ensure_universe(
        self,
        universe_id: str,
        display_name: str,
        franchise: Optional[str] = None,
    ) -> None:
        """Create the universe record if it doesn't already exist."""
        existing = self.db.get_universe(universe_id)
        if not existing:
            self.db.create_universe(
                universe_id=universe_id,
                display_name=display_name,
                franchise=franchise,
            )

    def ensure_cosmology(
        self,
        cosmology_id: str,
        display_name: str,
        description: Optional[str] = None,
    ) -> None:
        """Create a parentless top-level universe representing a cosmology.

        A cosmology is the optional meta-universe layer above franchise
        (Sanderson-style shared-cosmology projects). Member franchises set
        their ``parent_universe_id`` to this cosmology's id so the existing
        chain walk in ``get_lore_for_context(walk_parents=True)`` returns
        cosmology-wide shared lore alongside franchise-specific lore.

        This method is a thin semantic wrapper over ``create_universe``
        using the existing universe hierarchy; no new tables or columns are
        introduced.
        """
        existing = self.db.get_universe(cosmology_id)
        if not existing:
            self.db.create_universe(
                universe_id=cosmology_id,
                display_name=display_name,
                parent_universe_id=None,
                franchise=None,
                description=description,
            )

    def delete_universe(self, universe_id: str) -> None:
        """Delete universe from SQLite and its ChromaDB collection."""
        self.db.delete_universe(universe_id)
        self.vectorstore.delete_collection(universe_id)

    # ------------------------------------------------------------------
    # Lore Entry CRUD (dual-write)
    # ------------------------------------------------------------------

    def create_lore_entry(
        self,
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
    ) -> str:
        """Create a lore entry in SQLite and ChromaDB (write-ahead)."""
        entry_id = str(uuid.uuid4())

        # Write-ahead: SQLite first in a transaction
        try:
            self.db.conn.execute("BEGIN")
            self.db.conn.execute(
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
                    __import__("json").dumps(tags) if tags else None,
                    source_project_id, introduced_in_project_id, extraction_source,
                    timeline_sort_start, timeline_sort_end, visibility,
                ),
            )
        except Exception:
            self.db.conn.rollback()
            raise

        # ChromaDB write
        try:
            metadata = {
                "entry_id": entry_id,
                "category": category,
                "title": title,
                "status": status,
                "valid_from": valid_from or "",
                "valid_until": valid_until or "",
                "introduced_in_project_id": introduced_in_project_id or "",
                "canon_override": 1 if canon_override else 0,
                "tags": ", ".join(tags) if tags else "",
            }
            self.vectorstore.upsert_entry(universe_id, entry_id, content, metadata)
        except Exception as e:
            logger.warning("ChromaDB write failed, rolling back SQLite: %s", e)
            self.db.conn.rollback()
            raise

        self.db.conn.commit()
        return entry_id

    def update_lore_entry(self, entry_id: str, **fields) -> None:
        """Update a lore entry in SQLite and re-upsert to ChromaDB if content changed."""
        entry = self.db.get_lore_entry(entry_id)
        if entry is None:
            raise ValueError(f"Lore entry not found: {entry_id}")

        self.db.update_lore_entry(entry_id, **fields)

        # Re-upsert to ChromaDB if content or metadata changed
        if any(k in fields for k in ("content", "title", "status", "category",
                                      "valid_from", "valid_until",
                                      "introduced_in_project_id", "canon_override",
                                      "tags")):
            updated = self.db.get_lore_entry(entry_id)
            metadata = {
                "entry_id": entry_id,
                "category": updated["category"],
                "title": updated["title"],
                "status": updated["status"],
                "valid_from": updated.get("valid_from") or "",
                "valid_until": updated.get("valid_until") or "",
                "introduced_in_project_id": updated.get("introduced_in_project_id") or "",
                "canon_override": 1 if updated.get("canon_override") else 0,
                "tags": ", ".join(updated.get("tags", [])) if isinstance(updated.get("tags"), list) else "",
            }
            self.vectorstore.upsert_entry(
                updated["universe_id"], entry_id, updated["content"], metadata,
            )

    def delete_lore_entry(self, entry_id: str) -> None:
        """Delete from SQLite and ChromaDB."""
        entry = self.db.get_lore_entry(entry_id)
        if entry is None:
            return
        self.db.delete_lore_entry(entry_id)
        self.vectorstore.remove_entry(entry["universe_id"], entry_id)

    def promote_entry(self, entry_id: str) -> None:
        entry = self.db.get_lore_entry(entry_id)
        if entry is None:
            return
        self.db.promote_lore_entry(entry_id)
        # Update ChromaDB metadata
        updated = self.db.get_lore_entry(entry_id)
        metadata = {
            "entry_id": entry_id,
            "category": updated["category"],
            "title": updated["title"],
            "status": "canonical",
            "valid_from": updated.get("valid_from") or "",
            "valid_until": updated.get("valid_until") or "",
            "introduced_in_project_id": updated.get("introduced_in_project_id") or "",
            "canon_override": 1 if updated.get("canon_override") else 0,
            "tags": ", ".join(updated.get("tags", [])) if isinstance(updated.get("tags"), list) else "",
        }
        self.vectorstore.upsert_entry(
            updated["universe_id"], entry_id, updated["content"], metadata,
        )

    def deprecate_entry(self, entry_id: str) -> None:
        entry = self.db.get_lore_entry(entry_id)
        if entry is None:
            return
        self.db.deprecate_lore_entry(entry_id)
        updated = self.db.get_lore_entry(entry_id)
        metadata = {
            "entry_id": entry_id,
            "category": updated["category"],
            "title": updated["title"],
            "status": "deprecated",
            "valid_from": updated.get("valid_from") or "",
            "valid_until": updated.get("valid_until") or "",
            "introduced_in_project_id": updated.get("introduced_in_project_id") or "",
            "canon_override": 1 if updated.get("canon_override") else 0,
            "tags": ", ".join(updated.get("tags", [])) if isinstance(updated.get("tags"), list) else "",
        }
        self.vectorstore.upsert_entry(
            updated["universe_id"], entry_id, updated["content"], metadata,
        )

    def link_entries(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        description: Optional[str] = None,
        dialogue_implications: Optional[str] = None,
    ) -> None:
        self.db.create_relation(
            source_id, target_id, relation_type,
            description, dialogue_implications,
        )

    # ------------------------------------------------------------------
    # Context Retrieval
    # ------------------------------------------------------------------

    def get_lore_for_context(
        self,
        universe_id: str,
        query_text: str,
        top_k: int = 5,
        walk_parents: bool = True,
        timeline_date: Optional[str] = None,
        timeline_sort_key: Optional[int] = None,
        project_reading_order: Optional[int] = None,
        include_provisional: bool = True,
    ) -> list[dict]:
        """Retrieve worldbuilding lore for context assembly.

        Applies timeline filtering, spoiler isolation, and status filtering.

        Args:
            timeline_sort_key: Numeric timeline position for sort-key comparison.
                Preferred over timeline_date for backward-counting systems (BBY).
                When provided, uses sort keys on lore entries instead of string
                comparison on valid_from/valid_until.
        """
        # Build universe chain
        if walk_parents:
            chain = self.db.get_universe_chain(universe_id)
        else:
            chain = [universe_id]

        # Build ChromaDB where filter
        where = {"status": {"$ne": "deprecated"}}
        if not include_provisional:
            where = {"status": "canonical"}

        # Fetch more than top_k to allow for post-filtering
        raw_results = self.vectorstore.search_chain(
            chain, query_text, k=top_k * 3, where=where,
        )

        # Post-filter: exclude terminology (handled separately)
        results = [r for r in raw_results
                    if r.get("metadata", {}).get("category") != "terminology"]

        # Post-filter: timeline validity
        if timeline_sort_key is not None:
            # Use sort keys — look up from SQLite for accurate comparison
            filtered = []
            for r in results:
                entry = self.db.get_lore_entry(r["id"])
                if entry is None:
                    filtered.append(r)
                    continue
                sort_start = entry.get("timeline_sort_start")
                sort_end = entry.get("timeline_sort_end")
                if _timeline_matches_sort_key(sort_start, sort_end, timeline_sort_key):
                    filtered.append(r)
            results = filtered
        elif timeline_date is not None:
            results = [
                r for r in results
                if _timeline_matches(
                    r.get("metadata", {}).get("valid_from", ""),
                    r.get("metadata", {}).get("valid_until", ""),
                    timeline_date,
                )
            ]

        # Post-filter: spoiler isolation
        if project_reading_order is not None:
            filtered = []
            for r in results:
                intro_project = r.get("metadata", {}).get("introduced_in_project_id", "")
                if not intro_project:
                    filtered.append(r)
                    continue
                intro_order = self.db.get_project_reading_order(intro_project)
                if intro_order is None or intro_order <= project_reading_order:
                    filtered.append(r)
            results = filtered

        return results[:top_k]

    def get_terminology(
        self,
        universe_id: str,
        walk_parents: bool = True,
    ) -> list[dict]:
        """Get ALL terminology entries (always-include, not top-K)."""
        if walk_parents:
            chain = self.db.get_universe_chain(universe_id)
        else:
            chain = [universe_id]

        seen_titles: set[str] = set()
        all_terms: list[dict] = []

        for uid in chain:
            entries = self.db.get_terminology_entries(uid)
            for entry in entries:
                title_lower = entry["title"].lower()
                if title_lower not in seen_titles:
                    seen_titles.add(title_lower)
                    all_terms.append(entry)

        return all_terms

    def get_dialogue_context(
        self,
        universe_id: str,
        character_ids: Optional[list[str]] = None,
        knowledge_layers: Optional[object] = None,
    ) -> dict:
        """Get knowledge-gated speech patterns and dialogue implications.

        When character_ids are provided, filters speech patterns to only
        factions/cultures the characters are affiliated with. When
        knowledge_layers is provided, also includes secret-level lore
        that characters have belief-layer knowledge of.

        Returns:
            dict with keys: speech_patterns (list), dialogue_implications (list)
        """
        chain = self.db.get_universe_chain(universe_id)

        if character_ids:
            # Knowledge-gated: only include patterns for affiliated factions
            affiliated_entry_ids: set[str] = set()
            for char_id in character_ids:
                char_slug = char_id.lower().replace(" ", "_").replace("-", "_")
                for slug in (char_slug, char_id):
                    affs = self.db.get_character_affiliations(slug)
                    affiliated_entry_ids.update(a["entry_id"] for a in affs)

            speech_patterns = []
            for uid in chain:
                entries = self.db.get_speech_pattern_entries(uid)
                for entry in entries:
                    vis = entry.get("visibility", "public")
                    if vis == "public":
                        speech_patterns.append({
                            "title": entry["title"],
                            "category": entry["category"],
                            "speech_patterns": entry["speech_patterns"],
                        })
                    elif vis == "faction_internal" and entry["entry_id"] in affiliated_entry_ids:
                        speech_patterns.append({
                            "title": entry["title"],
                            "category": entry["category"],
                            "speech_patterns": entry["speech_patterns"],
                        })
                    elif vis == "secret" and knowledge_layers:
                        # Check if any character has belief-layer knowledge
                        fact_id = f"lore:{entry['entry_id']}"
                        for char_id in character_ids:
                            char_slug = char_id.lower().replace(" ", "_").replace("-", "_")
                            accuracy = knowledge_layers.check_belief_accuracy(
                                char_slug, fact_id,
                            )
                            if accuracy is not None:
                                speech_patterns.append({
                                    "title": entry["title"],
                                    "category": entry["category"],
                                    "speech_patterns": entry["speech_patterns"],
                                })
                                break

            # Dialogue implications between affiliated factions
            dialogue_implications = self.db.get_dialogue_implications(
                list(affiliated_entry_ids),
            )
        else:
            # Unfiltered fallback
            speech_patterns = []
            for uid in chain:
                entries = self.db.get_speech_pattern_entries(uid)
                for entry in entries:
                    speech_patterns.append({
                        "title": entry["title"],
                        "category": entry["category"],
                        "speech_patterns": entry["speech_patterns"],
                    })
            dialogue_implications = []

        return {
            "speech_patterns": speech_patterns,
            "dialogue_implications": dialogue_implications,
        }

    # ------------------------------------------------------------------
    # Truth/Belief Bridge
    # ------------------------------------------------------------------

    def sync_lore_to_beliefs(
        self,
        universe_id: str,
        knowledge_layers: object,
        chapter: int = 0,
    ) -> int:
        """Bridge lore entries into the Truth/Belief knowledge layer system.

        For each canonical lore entry:
          - Adds a truth-layer fact (world-level)
          - For characters affiliated with the entry's faction:
            public → all characters get beliefs
            faction_internal → affiliated characters get beliefs
            secret → no automatic beliefs

        Returns count of beliefs created.
        """
        entries = self.db.list_lore_entries(universe_id, status="canonical")
        count = 0

        for entry in entries:
            fact_id = f"lore:{entry['entry_id']}"
            description = f"{entry['title']}: {entry['content'][:200]}"

            # Add truth-layer fact
            try:
                knowledge_layers.add_truth(fact_id, description, chapter)
            except Exception:
                pass  # Already exists

            vis = entry.get("visibility", "public")
            if vis == "secret":
                continue  # No automatic beliefs for secrets

            # Get affiliated characters
            affiliated = self.db.get_affiliated_characters(entry["entry_id"])
            char_ids = {a["character_id"] for a in affiliated}

            if vis == "public":
                # All characters in the project should know public facts
                # We create beliefs only for affiliated characters since
                # we don't have access to all project characters here
                for char_id in char_ids:
                    try:
                        knowledge_layers.add_belief(
                            character_id=char_id,
                            fact_id=fact_id,
                            description=description,
                            is_accurate=True,
                            chapter=chapter,
                            source="faction_knowledge",
                        )
                        count += 1
                    except Exception:
                        pass
            elif vis == "faction_internal":
                for char_id in char_ids:
                    try:
                        knowledge_layers.add_belief(
                            character_id=char_id,
                            fact_id=fact_id,
                            description=description,
                            is_accurate=True,
                            chapter=chapter,
                            source="faction_knowledge",
                        )
                        count += 1
                    except Exception:
                        pass

        return count

    def grant_lore_knowledge(
        self,
        character_id: str,
        entry_id: str,
        knowledge_layers: object,
        chapter: int,
        is_accurate: bool = True,
        source: str = "learned",
    ) -> None:
        """Grant a character belief-layer knowledge of a specific lore entry.

        Use this when a character discovers a secret or learns about an
        enemy faction's internal workings through the story.
        """
        entry = self.db.get_lore_entry(entry_id)
        if entry is None:
            return
        fact_id = f"lore:{entry_id}"
        description = f"{entry['title']}: {entry['content'][:200]}"
        knowledge_layers.add_belief(
            character_id=character_id,
            fact_id=fact_id,
            description=description,
            is_accurate=is_accurate,
            chapter=chapter,
            source=source,
        )

    def resolve_canon_overrides(
        self,
        worldbuilding_results: list[dict],
        canon_results: list[dict],
    ) -> list[dict]:
        """Merge worldbuilding and canon results, applying overrides.

        Entries with canon_override=True suppress canon results with
        matching topics (by title similarity).
        """
        override_titles = set()
        for r in worldbuilding_results:
            meta = r.get("metadata", {})
            if meta.get("canon_override") in (True, 1, "1"):
                override_titles.add(meta.get("title", "").lower())

        if not override_titles:
            return worldbuilding_results + canon_results

        # Filter canon results that are overridden
        filtered_canon = []
        for cr in canon_results:
            canon_text = cr.get("text", "").lower()
            canon_id = cr.get("id", "").lower()
            overridden = any(
                title in canon_text or title in canon_id
                for title in override_titles
            )
            if not overridden:
                filtered_canon.append(cr)

        return worldbuilding_results + filtered_canon

    # ------------------------------------------------------------------
    # LLM-Assisted Extraction
    # ------------------------------------------------------------------

    async def import_from_concept_seed(
        self,
        concept_seed: dict,
        universe_id: str,
        router: "ModelRouter",
    ) -> list[str]:
        """Extract worldbuilding from a concept seed via LLM.

        All entries are created as provisional with extraction_source='concept_seed_import'.
        Returns list of created entry IDs.
        """
        from src.worldbuilding.lore_extractor import (
            build_concept_seed_extraction_prompt,
            parse_extraction_result,
        )

        messages = build_concept_seed_extraction_prompt(concept_seed)
        try:
            result = await router.complete(
                messages=messages,
                agent_role="lore_extractor",
            )
        except Exception as e:
            logger.warning("LLM extraction from concept seed failed: %s", e)
            return []

        parsed = parse_extraction_result(result)
        entry_ids = []

        for entry_data in parsed:
            try:
                entry_id = self.create_lore_entry(
                    universe_id=universe_id,
                    category=entry_data["category"],
                    title=entry_data["title"],
                    content=entry_data["content"],
                    status="provisional",
                    valid_from=entry_data.get("valid_from"),
                    valid_until=entry_data.get("valid_until"),
                    thematic_notes=entry_data.get("thematic_notes"),
                    speech_patterns=entry_data.get("speech_patterns"),
                    tags=entry_data.get("tags"),
                    extraction_source="concept_seed_import",
                )
                entry_ids.append(entry_id)
            except Exception as e:
                logger.warning("Failed to create extracted entry '%s': %s",
                               entry_data.get("title", "?"), e)

        return entry_ids

    async def extract_worldbuilding_from_chapter(
        self,
        chapter_text: str,
        scene_card: dict,
        universe_id: str,
        project_id: str,
        router: "ModelRouter",
    ) -> list[str]:
        """Extract worldbuilding from generated chapter prose via LLM.

        All entries are created as provisional with extraction_source='prose_extraction'.
        Returns list of created entry IDs.
        """
        from src.worldbuilding.lore_extractor import (
            build_chapter_extraction_prompt,
            parse_extraction_result,
        )

        # Verify universe exists before attempting extraction
        if not self.db.get_universe(universe_id):
            logger.error("Universe '%s' not found in worldbuilding DB — cannot extract", universe_id)
            return []

        # Get existing titles to prevent duplicates
        existing_entries = self.db.list_lore_entries(universe_id)
        existing_titles = [e["title"] for e in existing_entries]

        messages = build_chapter_extraction_prompt(
            chapter_text, scene_card, existing_titles,
        )
        try:
            result = await router.complete(
                messages=messages,
                agent_role="lore_extractor",
            )
        except Exception as e:
            logger.warning("LLM extraction from chapter failed: %s", e)
            return []

        parsed = parse_extraction_result(result)
        entry_ids = []

        for entry_data in parsed:
            try:
                entry_id = self.create_lore_entry(
                    universe_id=universe_id,
                    category=entry_data["category"],
                    title=entry_data["title"],
                    content=entry_data["content"],
                    status="provisional",
                    valid_from=entry_data.get("valid_from"),
                    valid_until=entry_data.get("valid_until"),
                    thematic_notes=entry_data.get("thematic_notes"),
                    speech_patterns=entry_data.get("speech_patterns"),
                    tags=entry_data.get("tags"),
                    source_project_id=project_id,
                    introduced_in_project_id=project_id,
                    extraction_source="prose_extraction",
                )
                entry_ids.append(entry_id)
            except Exception as e:
                logger.warning("Failed to create extracted entry '%s': %s",
                               entry_data.get("title", "?"), e)

        return entry_ids

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def reconcile_chromadb_orphans(self, universe_id: Optional[str] = None) -> int:
        """Fix mismatches between SQLite and ChromaDB.

        For each universe:
          - Delete ChromaDB entries with no matching SQLite row (orphans)
          - Re-insert SQLite entries missing from ChromaDB
        Returns total count of fixes.
        """
        universes = (
            [self.db.get_universe(universe_id)]
            if universe_id
            else self.db.list_universes()
        )

        fixes = 0
        for u in universes:
            if u is None:
                continue
            uid = u["universe_id"]
            sqlite_ids = self.db.get_all_entry_ids(uid)
            chroma_ids = self.vectorstore.get_all_entry_ids(uid)

            # Orphans in ChromaDB (not in SQLite)
            for orphan_id in chroma_ids - sqlite_ids:
                self.vectorstore.remove_entry(uid, orphan_id)
                fixes += 1
                logger.info("Removed ChromaDB orphan: %s", orphan_id)

            # Missing in ChromaDB (in SQLite but not ChromaDB)
            for missing_id in sqlite_ids - chroma_ids:
                entry = self.db.get_lore_entry(missing_id)
                if entry:
                    metadata = {
                        "entry_id": missing_id,
                        "category": entry["category"],
                        "title": entry["title"],
                        "status": entry["status"],
                        "valid_from": entry.get("valid_from") or "",
                        "valid_until": entry.get("valid_until") or "",
                        "introduced_in_project_id": entry.get("introduced_in_project_id") or "",
                        "canon_override": 1 if entry.get("canon_override") else 0,
                        "tags": ", ".join(entry.get("tags", [])) if isinstance(entry.get("tags"), list) else "",
                    }
                    self.vectorstore.upsert_entry(uid, missing_id, entry["content"], metadata)
                    fixes += 1
                    logger.info("Re-inserted missing ChromaDB entry: %s", missing_id)

        return fixes

    def close(self) -> None:
        self.db.close()
        self.vectorstore.close()


def _timeline_matches_sort_key(
    sort_start: int | None,
    sort_end: int | None,
    current_key: int,
) -> bool:
    """Check if a lore entry's sort key range includes the current position."""
    if sort_start is None and sort_end is None:
        return True
    if sort_start is not None and current_key < sort_start:
        return False
    if sort_end is not None and current_key > sort_end:
        return False
    return True


def _timeline_matches(
    valid_from: str,
    valid_until: str,
    current_date: str,
) -> bool:
    """Fallback: string comparison for timeline filtering.

    Only reliable for forward-counting systems (ABY, AC, CE, chapter numbers).
    For backward-counting systems (BBY, BCE), use sort keys instead.
    """
    if not valid_from and not valid_until:
        return True
    if valid_from and current_date and current_date < valid_from:
        return False
    if valid_until and current_date and current_date > valid_until:
        return False
    return True
