"""State diff system for post-chapter story state updates.

After each chapter generation, the Summarizer produces a state diff.
This module validates and applies diffs to the SQLite story state,
computing state hashes and emitting events to the run ledger.

Phase 5 additions:
- old_value verification on character updates (optimistic: log conflict, still apply)
- subplot_updates, hook_updates, arc_phase_updates, terminology_updates handlers
"""

import json
import logging

from src.memory.knowledge_layers import KnowledgeLayers
from src.memory.story_state import StoryState
from src.run_ledger import RunLedger

logger = logging.getLogger(__name__)


class StateDiffApplier:
    """Validates and applies state diffs to the story state database."""

    def __init__(
        self,
        story_state: StoryState,
        knowledge_layers: KnowledgeLayers,
        ledger: RunLedger,
    ):
        self.state = story_state
        self.knowledge = knowledge_layers
        self.ledger = ledger

    def apply_diff(
        self, diff: dict, chapter_number: int, scene_number: int = 1
    ) -> str:
        """Apply a state diff and emit ledger events.

        Args:
            diff: State diff conforming to schemas/state_diff.json.
            chapter_number: Current chapter number.
            scene_number: Current scene number.

        Returns:
            The new state hash after applying the diff.
        """
        # Compute pre-diff state hash
        pre_hash = self.state.get_state_hash()

        # Emit proposed event
        self.ledger.emit(
            "state_diff_proposed",
            chapter_number=chapter_number,
            scene_number=scene_number,
            payload={"diff": diff, "pre_state_hash": pre_hash},
        )

        # Apply changes
        changes = diff.get("changes", {})
        self._apply_character_updates(changes.get("character_updates", []), chapter_number, scene_number)
        self._apply_plot_thread_updates(changes.get("plot_thread_updates", []))
        self._apply_new_knowledge(changes.get("new_knowledge", []), chapter_number)
        # Phase 5 change types
        self._apply_subplot_updates(changes.get("subplot_updates", []))
        self._apply_hook_updates(changes.get("hook_updates", []), chapter_number)
        self._apply_arc_phase_updates(changes.get("arc_phase_updates", []), chapter_number)
        self._apply_terminology_updates(changes.get("terminology_updates", []))

        # Compute post-diff state hash
        post_hash = self.state.get_state_hash()

        # Emit committed event
        self.ledger.emit(
            "state_diff_committed",
            chapter_number=chapter_number,
            scene_number=scene_number,
            payload={"post_state_hash": post_hash, "pre_state_hash": pre_hash},
        )

        return post_hash

    def _apply_character_updates(
        self, updates: list[dict], chapter_number: int, scene_number: int = 1
    ) -> None:
        """Apply character state updates with old_value verification."""
        for update in updates:
            char_id = update.get("character_id")
            field = update.get("field")
            new_value = update.get("new_value")

            if not char_id or not field:
                continue

            # Check if character exists
            character = self.state.get_character(char_id)
            if character is None:
                continue

            # Phase 5: old_value verification
            old_value = update.get("old_value")
            if old_value is not None:
                current_value = character.get(field)
                if current_value != old_value:
                    logger.warning(
                        "State diff conflict on character '%s' field '%s': "
                        "expected old_value=%r, actual=%r. Applying anyway (optimistic).",
                        char_id, field, old_value, current_value,
                    )
                    self.ledger.emit(
                        "state_diff_conflict",
                        chapter_number=chapter_number,
                        payload={
                            "entity_type": "character",
                            "entity_id": char_id,
                            "field": field,
                            "expected_old": old_value,
                            "actual_current": current_value,
                            "new_value": new_value,
                        },
                    )

            kwargs = {field: new_value}
            # Also update last_appearance
            kwargs["last_appearance_chapter"] = chapter_number
            kwargs["last_appearance_scene"] = scene_number
            self.state.update_character(char_id, **kwargs)

    def _apply_plot_thread_updates(self, updates: list[dict]) -> None:
        """Apply plot thread status updates."""
        for update in updates:
            thread_id = update.get("thread_id")
            field = update.get("field")
            new_value = update.get("new_value")

            if not thread_id or not field:
                continue

            thread = self.state.get_plot_thread(thread_id)
            if thread is None:
                # Auto-create the thread if it doesn't exist
                self.state.add_plot_thread(
                    id=thread_id,
                    description=thread_id.replace("_", " ").title(),
                    **{field: new_value},
                )
            else:
                self.state.update_plot_thread(thread_id, **{field: new_value})

    def _apply_new_knowledge(
        self, knowledge_entries: list[dict], chapter_number: int
    ) -> None:
        """Apply new knowledge entries as beliefs."""
        for entry in knowledge_entries:
            char_id = entry.get("character_id")
            fact = entry.get("fact")
            source = entry.get("source", "witnessed")

            if not char_id or not fact:
                continue

            # Guard: skip if character doesn't exist in the DB (FK constraint)
            if self.state.get_character(char_id) is None:
                logger.warning(
                    "Skipping new_knowledge for unknown character '%s'", char_id
                )
                continue

            # Generate a fact_id from the fact text
            fact_id = _make_fact_id(fact)

            # Add as a belief (default to accurate unless we know otherwise)
            self.knowledge.add_belief(
                character_id=char_id,
                fact_id=fact_id,
                description=fact,
                is_accurate=True,
                chapter=chapter_number,
                source=source,
            )

    # ------------------------------------------------------------------
    # Phase 5 diff handlers
    # ------------------------------------------------------------------

    def _apply_subplot_updates(self, updates: list[dict]) -> None:
        """Apply subplot board updates."""
        for update in updates:
            subplot_id = update.get("subplot_id")
            field = update.get("field")
            new_value = update.get("new_value")

            if not subplot_id or not field:
                continue

            subplot = self.state.get_subplot(subplot_id)
            if subplot is None:
                # Auto-create subplot
                self.state.add_subplot(
                    subplot_id=subplot_id,
                    subplot_name=subplot_id.replace("_", " ").title(),
                    **{field: new_value},
                )
            else:
                self.state.update_subplot(subplot_id, **{field: new_value})

    # Map common LLM field-name variations to actual DB column names
    _HOOK_FIELD_ALIASES: dict[str, str] = {
        "status": "current_status",
    }

    def _apply_hook_updates(
        self, updates: list[dict], chapter_number: int
    ) -> None:
        """Apply hook ledger updates with admission control."""
        for update in updates:
            hook_id = update.get("hook_id")
            field = update.get("field")
            new_value = update.get("new_value")

            # Normalise LLM field names to actual DB columns
            if field:
                field = self._HOOK_FIELD_ALIASES.get(field, field)

            if not hook_id:
                continue

            hook = self.state.get_hook(hook_id)
            if hook is None:
                # New hook — check admission control
                priority = update.get("priority", "soft")
                # Use a reasonable default target chapters
                if not self.state.can_admit_hook(priority, target_chapters=30):
                    logger.warning(
                        "Hook '%s' at priority '%s' denied admission — budget exceeded. "
                        "Recording anyway since prose may already reference it.",
                        hook_id, priority,
                    )
                    self.ledger.emit(
                        "hook_admission_denied",
                        chapter_number=chapter_number,
                        payload={"hook_id": hook_id, "priority": priority},
                    )

                # Auto-create hook with available fields from the update
                self.state.add_hook(
                    hook_id=hook_id,
                    description=update.get("description", hook_id.replace("_", " ")),
                    hook_type=update.get("hook_type", "foreshadow"),
                    planted_chapter=chapter_number,
                    priority=update.get("priority", "soft"),
                    related_subplot=update.get("related_subplot"),
                )
                if field and field != "current_status":
                    self.state.update_hook(hook_id, **{field: new_value})
            else:
                if field:
                    self.state.update_hook(hook_id, **{field: new_value})

    def _apply_arc_phase_updates(
        self, updates: list[dict], chapter_number: int
    ) -> None:
        """Apply character arc phase transitions with validation."""
        for update in updates:
            char_id = update.get("character_id")
            new_phase = update.get("new_phase")
            evidence = update.get("evidence")

            if not char_id or not new_phase:
                continue

            success = self.state.advance_arc_phase(
                character_id=char_id,
                new_phase=new_phase,
                chapter=chapter_number,
                evidence=evidence,
            )
            if not success:
                old_phase = update.get("old_phase", "unknown")
                logger.warning(
                    "Arc phase transition rejected for '%s': %s -> %s. "
                    "Invalid progression.",
                    char_id, old_phase, new_phase,
                )
                self.ledger.emit(
                    "arc_phase_transition_rejected",
                    chapter_number=chapter_number,
                    payload={
                        "character_id": char_id,
                        "old_phase": old_phase,
                        "new_phase": new_phase,
                        "evidence": evidence,
                    },
                )

    def _apply_terminology_updates(self, updates: list[dict]) -> None:
        """Apply terminology registry updates."""
        for update in updates:
            term = update.get("term")
            if not term:
                continue

            existing = self.state.get_term(term)
            if existing is None:
                # Auto-create term
                self.state.add_term(
                    term=term,
                    definition=update.get("definition", ""),
                    category=update.get("category", "concept"),
                    aliases=update.get("aliases"),
                    first_appearance_chapter=update.get("first_appearance_chapter"),
                )
            else:
                field = update.get("field")
                new_value = update.get("new_value")
                if field and new_value is not None:
                    self.state.update_term(term, **{field: new_value})

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_diff(self, diff: dict) -> list[str]:
        """Validate a state diff against expected structure.

        Returns list of validation errors (empty = valid).
        """
        errors = []

        if "chapter_number" not in diff:
            errors.append("Missing required field: chapter_number")

        if "changes" not in diff:
            errors.append("Missing required field: changes")
            return errors

        changes = diff["changes"]

        for i, cu in enumerate(changes.get("character_updates", [])):
            if "character_id" not in cu:
                errors.append(f"character_updates[{i}]: missing character_id")
            if "field" not in cu:
                errors.append(f"character_updates[{i}]: missing field")

        for i, pt in enumerate(changes.get("plot_thread_updates", [])):
            if "thread_id" not in pt:
                errors.append(f"plot_thread_updates[{i}]: missing thread_id")
            if "field" not in pt:
                errors.append(f"plot_thread_updates[{i}]: missing field")

        for i, nk in enumerate(changes.get("new_knowledge", [])):
            if "character_id" not in nk:
                errors.append(f"new_knowledge[{i}]: missing character_id")
            if "fact" not in nk:
                errors.append(f"new_knowledge[{i}]: missing fact")

        # Phase 5 validation
        for i, su in enumerate(changes.get("subplot_updates", [])):
            if "subplot_id" not in su:
                errors.append(f"subplot_updates[{i}]: missing subplot_id")

        for i, hu in enumerate(changes.get("hook_updates", [])):
            if "hook_id" not in hu:
                errors.append(f"hook_updates[{i}]: missing hook_id")

        for i, au in enumerate(changes.get("arc_phase_updates", [])):
            if "character_id" not in au:
                errors.append(f"arc_phase_updates[{i}]: missing character_id")
            if "new_phase" not in au:
                errors.append(f"arc_phase_updates[{i}]: missing new_phase")

        for i, tu in enumerate(changes.get("terminology_updates", [])):
            if "term" not in tu:
                errors.append(f"terminology_updates[{i}]: missing term")

        return errors


def _make_fact_id(fact_text: str) -> str:
    """Generate a stable fact ID from fact text."""
    import hashlib

    return "fact_" + hashlib.md5(fact_text.encode()).hexdigest()[:12]
