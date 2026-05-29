"""SeriesManager — handles series seed creation, transition snapshots,
and retroactive series promotion.

Manages the lifecycle of multi-book series planning:
- Step 0a: Create a series seed for planned series
- Step 0b: Retroactive promotion of standalone to series
- Book transitions: Generate and import transition snapshots
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class SeriesManager:
    """Manages series-level planning and cross-book state."""

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir)
        self.project_dir.mkdir(parents=True, exist_ok=True)

    def create_series_seed(
        self,
        series_title: str,
        total_books: int,
        series_dramatic_question: str,
        series_antagonist_escalation: str,
        series_stakes_progression: str,
        series_theme: dict,
        per_book_outline: list[dict],
        series_promises: list[dict],
        shared_characters: list[dict] | None = None,
    ) -> dict:
        """Create and persist a series seed from workshop decisions.

        Returns the series seed dict.
        """
        seed = {
            "series_title": series_title,
            "total_books": total_books,
            "series_dramatic_question": series_dramatic_question,
            "series_antagonist_escalation": series_antagonist_escalation,
            "series_stakes_progression": series_stakes_progression,
            "series_theme": series_theme,
            "per_book_outline": per_book_outline,
            "series_promises": series_promises,
            "shared_characters": shared_characters or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        errors = self.validate_series_seed(seed)
        if errors:
            logger.warning("Series seed validation warnings: %s", errors)

        output_path = self.project_dir / "series_seed.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(seed, f, indent=2, ensure_ascii=False)

        logger.info("Series seed created → %s", output_path)
        return seed

    def load_series_seed(self) -> dict | None:
        """Load an existing series seed from the project directory."""
        path = self.project_dir / "series_seed.json"
        if not path.exists():
            return None
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def validate_series_seed(self, seed: dict) -> list[str]:
        """Validate a series seed. Returns list of errors (empty = valid)."""
        errors = []

        if seed.get("total_books", 0) < 2:
            errors.append("Series must have at least 2 books")

        if not seed.get("series_promises"):
            errors.append("Series must have at least one cross-book promise")

        series_q = seed.get("series_dramatic_question", "").strip().lower()
        for book in seed.get("per_book_outline", []):
            book_q = book.get("book_dramatic_question", "").strip().lower()
            if book_q and book_q == series_q:
                errors.append(
                    f"Book {book.get('book_number')}'s dramatic question is identical "
                    f"to the series question — each book should explore a distinct facet"
                )

        return errors

    def generate_transition_snapshot(
        self,
        story_state,
        book_number: int,
        concept_seed: dict | None = None,
    ) -> dict:
        """Generate a BookTransitionSnapshot from the current story state.

        Captures: character end states, unresolved threads, open promises,
        world state changes. Used to initialize the next book.
        """
        characters = story_state.get_all_characters()
        active_threads = story_state.get_active_threads()
        unfired_guns = story_state.get_unfired_guns()
        arcs = story_state.get_all_character_arcs(book_number=book_number)

        # Collect hook debts (unresolved hooks)
        all_hooks = story_state.get_all_hooks(book_number=book_number)
        unresolved_hooks = [
            h for h in all_hooks
            if h["current_status"] not in ("resolved", "subverted", "abandoned")
        ]

        snapshot = {
            "book_number": book_number,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "character_end_states": [
                {
                    "id": c["id"],
                    "name": c["name"],
                    "location": c["current_location"],
                    "emotional_state": c["emotional_state"],
                    "arc_position": c["arc_position"],
                }
                for c in characters
            ],
            "character_arc_states": [
                {
                    "character_id": a["character_id"],
                    "current_phase": a["current_phase"],
                    "arc_type": a["arc_type"],
                    "lie_believed": a["lie_believed"],
                    "need": a["need"],
                }
                for a in arcs
            ],
            "unresolved_threads": [
                {
                    "id": t["id"],
                    "description": t["description"],
                    "status": t["status"],
                    "urgency": t["urgency"],
                }
                for t in active_threads
            ],
            "unresolved_hooks": [
                {
                    "hook_id": h["hook_id"],
                    "description": h["description"],
                    "priority": h["priority"],
                    "current_status": h["current_status"],
                }
                for h in unresolved_hooks
            ],
            "unfired_chekhov_guns": [
                {
                    "id": g["id"],
                    "description": g["item_description"],
                    "planted_chapter": g["planted_chapter"],
                }
                for g in unfired_guns
            ],
        }

        # Persist
        output_path = self.project_dir / f"book_{book_number}_transition.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)

        logger.info("Transition snapshot generated → %s", output_path)
        return snapshot

    def import_transition_snapshot(self, snapshot_path: str | Path) -> dict:
        """Load and validate a transition snapshot for continuation.

        Returns the snapshot dict. Raises ValueError on invalid snapshot.
        """
        path = Path(snapshot_path)
        if not path.exists():
            raise FileNotFoundError(f"Transition snapshot not found: {path}")

        with open(path, encoding="utf-8") as f:
            snapshot = json.load(f)

        required = ["book_number", "character_end_states"]
        for field in required:
            if field not in snapshot:
                raise ValueError(f"Invalid snapshot: missing required field '{field}'")

        return snapshot

    # ------------------------------------------------------------------
    # Phase 6.1: transition application (consume a snapshot in Book N+1)
    # ------------------------------------------------------------------

    @staticmethod
    def apply_transition_to_seed(seed: dict, snapshot: dict) -> dict:
        """Mutate a Book N+1 concept seed in-place with inherited state.

        Decision D1 (Phase 6/7 plan): the snapshot carries the minimal
        contract — character end states, unresolved threads, open hooks,
        unfired Chekhov guns. This method reflects that state into the new
        book's concept seed at the level the seed can represent:

        1. Unresolved hooks are prepended to ``seed.hooks`` with an
           ``inherited_from_book`` tag so planner-level tooling (subplot
           audit, blueprint generator, chapter gate) sees them as existing
           contracts rather than fresh plants.
        2. A ``book_transition`` block is added under ``seed.extended_metadata``
           recording what was carried over — character IDs, inherited plot
           threads, unfired guns. This is visible to humans and to
           downstream tools without breaking the concept_seed schema.
        3. ``seed.meta.book_number`` and ``seed.meta.project_scope`` are
           set to reflect continuation when not already set by the caller.

        Character runtime state (location, emotional_state, arc_position,
        arc current_phase) is out of scope for the concept seed — it is
        loaded into the Book N+1 StoryState by
        ``StoryState.initialize_from_transition``.

        Idempotent on hooks: a hook_id already present in ``seed.hooks`` is
        not duplicated (the caller's explicit hook entry wins).

        Returns the mutated seed (same object) for fluent use.
        """
        source_book_number = int(snapshot.get("book_number", 0) or 0)
        if source_book_number < 1:
            raise ValueError(
                "transition snapshot missing or invalid 'book_number'; "
                "cannot apply to continuation seed"
            )

        # 1. Seed metadata — mark as continuation.
        meta = seed.setdefault("meta", {})
        if not meta.get("book_number"):
            meta["book_number"] = source_book_number + 1
        if not meta.get("project_scope"):
            meta["project_scope"] = "continuation"

        # 2. Prepend unresolved hooks (de-duplicate by hook_id).
        existing_hooks = list(seed.get("hooks") or [])
        existing_hook_ids = {h.get("hook_id") for h in existing_hooks if h.get("hook_id")}
        inherited_hooks: list[dict] = []
        for h in snapshot.get("unresolved_hooks") or []:
            hook_id = h.get("hook_id")
            if hook_id and hook_id in existing_hook_ids:
                continue  # caller's explicit entry wins
            entry = {
                "hook_id": hook_id or f"inherited_hook_{len(inherited_hooks) + 1}",
                "description": h.get("description", ""),
                "planted_in": f"book_{source_book_number}",
                "inherited_from_book": source_book_number,
                "priority": h.get("priority"),
                "current_status": h.get("current_status"),
            }
            # hook_type is required by the schema's enum; map from priority
            # when the snapshot is silent, defaulting to "series" (the
            # closest match for cross-book carryover).
            entry["hook_type"] = (
                "hard" if (h.get("priority") == "hard") else "series"
            )
            inherited_hooks.append(entry)
        if inherited_hooks:
            seed["hooks"] = inherited_hooks + existing_hooks

        # 3. Record an audit trail under extended_metadata.book_transition.
        transition_record = {
            "inherited_from_book": source_book_number,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "carried_character_ids": [
                c["id"] for c in snapshot.get("character_end_states") or []
                if c.get("id")
            ],
            "inherited_plot_threads": [
                {
                    "id": t.get("id"),
                    "description": t.get("description", ""),
                    "status": t.get("status"),
                    "urgency": t.get("urgency"),
                }
                for t in snapshot.get("unresolved_threads") or []
            ],
            "inherited_chekhov_guns": [
                {
                    "id": g.get("id"),
                    "description": g.get("description", ""),
                    "planted_chapter": g.get("planted_chapter"),
                }
                for g in snapshot.get("unfired_chekhov_guns") or []
            ],
            "inherited_hook_ids": [
                h["hook_id"] for h in inherited_hooks
            ],
        }
        extended = seed.setdefault("extended_metadata", {})
        extended["book_transition"] = transition_record

        return seed

    def promote_to_series(
        self,
        concept_seed: dict,
        series_title: str,
        total_books: int,
        series_dramatic_question: str,
        series_stakes_progression: str,
    ) -> dict:
        """Retroactively promote a standalone concept seed to Book 1 of a series.

        Creates a series seed where Book 1 is treated as 'setup'.
        Does NOT modify Book 1's concept seed. Returns the series seed.
        """
        book_1_question = concept_seed.get("premise", {}).get(
            "central_dramatic_question", ""
        )

        per_book_outline = [
            {
                "book_number": 1,
                "book_dramatic_question": book_1_question,
                "book_role_in_series": "setup",
                "threads_inherited": [],
                "threads_planted_for_later": [],
            }
        ]
        # Placeholder entries for remaining books
        for i in range(2, total_books + 1):
            role = "resolution" if i == total_books else "escalation"
            per_book_outline.append({
                "book_number": i,
                "book_dramatic_question": "",
                "book_role_in_series": role,
                "threads_inherited": [],
                "threads_planted_for_later": [],
            })

        series_theme = {
            "thematic_premise": concept_seed.get("theme", {}).get(
                "thematic_premise", ""
            ),
            "per_book_thematic_focus": [],
        }

        return self.create_series_seed(
            series_title=series_title,
            total_books=total_books,
            series_dramatic_question=series_dramatic_question,
            series_antagonist_escalation="",
            series_stakes_progression=series_stakes_progression,
            series_theme=series_theme,
            per_book_outline=per_book_outline,
            series_promises=[{
                "promise_id": "series_promotion_placeholder",
                "description": "Cross-book promise to be defined",
                "planted_book": 1,
                "payoff_book": total_books,
            }],
        )

    def validate_series_consistency(
        self, series_seed: dict, book_seed: dict
    ) -> list[str]:
        """Validate that a book concept seed is consistent with its series seed.

        Returns list of warnings (empty = consistent).
        """
        warnings = []
        book_number = book_seed.get("meta", {}).get("book_number", 1)

        # Find the book's outline entry
        outline = None
        for entry in series_seed.get("per_book_outline", []):
            if entry.get("book_number") == book_number:
                outline = entry
                break

        if outline is None:
            warnings.append(
                f"Book {book_number} not found in series per_book_outline"
            )
            return warnings

        # Check that book question contributes to series question
        series_q = series_seed.get("series_dramatic_question", "").strip().lower()
        book_q = book_seed.get("premise", {}).get(
            "central_dramatic_question", ""
        ).strip().lower()
        if book_q and series_q and book_q == series_q:
            warnings.append(
                "Book's dramatic question is identical to series question — "
                "should explore a distinct facet"
            )

        return warnings
