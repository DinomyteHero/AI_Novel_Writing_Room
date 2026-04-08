"""State diff system for post-chapter story state updates.

After each chapter generation, the Summarizer produces a state diff.
This module validates and applies diffs to the SQLite story state,
computing state hashes and emitting events to the run ledger.
"""

import json

from src.memory.knowledge_layers import KnowledgeLayers
from src.memory.story_state import StoryState
from src.run_ledger import RunLedger


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
        self._apply_character_updates(changes.get("character_updates", []), chapter_number)
        self._apply_plot_thread_updates(changes.get("plot_thread_updates", []))
        self._apply_new_knowledge(changes.get("new_knowledge", []), chapter_number)

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
        self, updates: list[dict], chapter_number: int
    ) -> None:
        """Apply character state updates."""
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

            kwargs = {field: new_value}
            # Also update last_appearance
            kwargs["last_appearance_chapter"] = chapter_number
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

        return errors


def _make_fact_id(fact_text: str) -> str:
    """Generate a stable fact ID from fact text."""
    import hashlib

    return "fact_" + hashlib.md5(fact_text.encode()).hexdigest()[:12]
