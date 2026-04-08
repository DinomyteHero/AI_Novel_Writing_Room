"""ConceptWorkshopState — mirrors the concept seed JSON schema.

Tracks which fields have been confirmed during the workshop and supports
incremental population, round-trip JSON serialization, and open-question
reporting.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# Top-level concept seed fields and human-readable labels for open questions.
_SEED_FIELDS: dict[str, str] = {
    # Step 0: Project scope
    "meta.project_scope": "Project scope (standalone / planned_series / continuation)",
    "meta.project_title": "Project title",
    "meta.franchise": "Franchise",
    "meta.canon_status": "Canon status",
    "meta.era": "Era / timeline period",
    "meta.tone": "Tone",
    "meta.target_word_count": "Target word count",
    "meta.target_chapters": "Target chapter count",
    "meta.pov_structure": "POV structure",
    # Steps 2-3: Premise
    "premise.what_if": "What-if premise hook",
    "premise.central_dramatic_question": "Central dramatic question",
    "premise.logline": "Logline",
    "conflict.primary_antagonistic_force": "Primary antagonistic force",
    "conflict.secondary_pressures": "Secondary pressures",
    "conflict.lock_in_mechanism": "Lock-in mechanism",
    "theme.thematic_premise": "Thematic premise",
    "theme.thematic_argument": "Thematic argument",
    "theme.how_each_arc_tests_theme": "How each arc tests the theme",
    "protagonist_arc_type": "Protagonist arc type",
    # Step 4: Characters + Weiland arcs
    "ensemble_cast": "Ensemble cast",
    "force_mechanics": "Force / magic mechanics",
    # Step 5: Voice definition
    "voice_definition.pov_approach": "POV approach",
    "voice_definition.prose_register": "Prose register",
    "voice_definition.anti_slop": "Anti-slop rules",
    "voice_definition.anti_patterns": "Anti-pattern rules",
    "voice_definition.narrative_voice_notes": "Narrative voice notes",
    # Step 6: Structure
    "structural_notes.brooks_alignment": "Brooks four-part structure alignment",
    # Step 7: Subplots + hooks
    "subplot_board": "Subplot board",
    "hook_map": "Hook map",
    "revelation_schedule": "Revelation schedule",
    # Step 8: Scene cards (generated, not tracked here)
    # Step 9: Terminology
    "terminology_registry": "Terminology registry",
    # Step 10: Stress test
    "stress_test_results": "Stress test results",
    # Canon
    "canon_constraints.continuity": "Canon continuity",
    "canon_constraints.divergence_point": "Canon divergence point",
    "canon_constraints.canon_preserved": "Canon preserved",
    "canon_constraints.canon_overridden": "Canon overridden",
    "canon_constraints.style_constraints": "Style constraints",
}


@dataclass
class ConceptWorkshopState:
    """Incremental draft of a concept seed, populated during the workshop."""

    meta: dict = field(default_factory=dict)
    premise: dict = field(default_factory=dict)
    conflict: dict = field(default_factory=dict)
    theme: dict = field(default_factory=dict)
    protagonist_arc_type: Optional[str] = None
    ensemble_cast: list[dict] = field(default_factory=list)
    force_mechanics: dict = field(default_factory=dict)
    canon_constraints: dict = field(default_factory=dict)
    structural_notes: dict = field(default_factory=dict)
    # Phase 5 fields
    voice_definition: dict = field(default_factory=dict)
    subplot_board: list[dict] = field(default_factory=list)
    hook_map: list[dict] = field(default_factory=list)
    revelation_schedule: list[dict] = field(default_factory=list)
    author_only_secrets: Optional[str] = None
    terminology_registry: list[dict] = field(default_factory=list)
    stress_test_results: dict = field(default_factory=dict)
    confirmed_fields: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        d = {
            "meta": self.meta,
            "premise": self.premise,
            "conflict": self.conflict,
            "theme": self.theme,
            "protagonist_arc_type": self.protagonist_arc_type,
            "ensemble_cast": self.ensemble_cast,
            "force_mechanics": self.force_mechanics,
            "canon_constraints": self.canon_constraints,
            "structural_notes": self.structural_notes,
            "confirmed_fields": sorted(self.confirmed_fields),
        }
        # Phase 5 fields — include only when populated
        if self.voice_definition:
            d["voice_definition"] = self.voice_definition
        if self.subplot_board:
            d["subplot_board"] = self.subplot_board
        if self.hook_map:
            d["hook_map"] = self.hook_map
        if self.revelation_schedule:
            d["revelation_schedule"] = self.revelation_schedule
        if self.author_only_secrets:
            d["author_only_secrets"] = self.author_only_secrets
        if self.terminology_registry:
            d["terminology_registry"] = self.terminology_registry
        if self.stress_test_results:
            d["stress_test_results"] = self.stress_test_results
        return d

    @classmethod
    def from_dict(cls, data: dict) -> ConceptWorkshopState:
        """Deserialize from a dict (e.g. loaded from workshop_state.json)."""
        return cls(
            meta=data.get("meta", {}),
            premise=data.get("premise", {}),
            conflict=data.get("conflict", {}),
            theme=data.get("theme", {}),
            protagonist_arc_type=data.get("protagonist_arc_type"),
            ensemble_cast=data.get("ensemble_cast", []),
            force_mechanics=data.get("force_mechanics", {}),
            canon_constraints=data.get("canon_constraints", {}),
            structural_notes=data.get("structural_notes", {}),
            voice_definition=data.get("voice_definition", {}),
            subplot_board=data.get("subplot_board", []),
            hook_map=data.get("hook_map", []),
            revelation_schedule=data.get("revelation_schedule", []),
            author_only_secrets=data.get("author_only_secrets"),
            terminology_registry=data.get("terminology_registry", []),
            stress_test_results=data.get("stress_test_results", {}),
            confirmed_fields=set(data.get("confirmed_fields", [])),
        )

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #

    @classmethod
    def load(cls, path: Path) -> ConceptWorkshopState:
        """Load from an existing workshop_state.json, or return empty."""
        if path.exists():
            with open(path, encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        return cls()

    def save(self, path: Path) -> None:
        """Persist current state to *path* atomically.

        Writes to a temp file in the same directory, then renames — so
        ``workshop_state.json`` is never left in a partially-written state.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), suffix=".tmp", prefix=".ws_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
            os.replace(tmp, str(path))
        except BaseException:
            # Clean up temp file on any failure.
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    def get_open_questions(self) -> list[str]:
        """Return human-readable descriptions of unconfirmed fields."""
        open_items: list[str] = []
        for field_path, label in _SEED_FIELDS.items():
            if field_path not in self.confirmed_fields:
                open_items.append(f"{label} ({field_path}) — not yet confirmed")
        return open_items

    def get_confirmed_summary(self) -> str:
        """Return a formatted block of confirmed decisions."""
        if not self.confirmed_fields:
            return "No decisions confirmed yet."
        lines: list[str] = []
        for fp in sorted(self.confirmed_fields):
            label = _SEED_FIELDS.get(fp, fp)
            value = self._get_field(fp)
            # Truncate long values for summary display.
            val_str = str(value)
            if len(val_str) > 120:
                val_str = val_str[:117] + "..."
            lines.append(f"- {label}: {val_str}")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Field access
    # ------------------------------------------------------------------ #

    def set_field(self, field_path: str, value: Any) -> None:
        """Set a value at the given dot-notation path.

        Supports paths like ``meta.franchise``, ``ensemble_cast.0.name``,
        and simple top-level names like ``protagonist_arc_type``.
        """
        parts = field_path.split(".")
        target = self._navigate_to_parent(parts)
        key = parts[-1]

        if isinstance(target, ConceptWorkshopState):
            setattr(target, key, value)
        elif isinstance(target, list):
            idx = int(key)
            while len(target) <= idx:
                target.append({})
            target[idx] = value
        else:
            target[key] = value

    def confirm(self, field_path: str) -> None:
        """Mark *field_path* as confirmed."""
        self.confirmed_fields.add(field_path)

    def _get_field(self, field_path: str) -> Any:
        """Retrieve the value at *field_path*, or None."""
        parts = field_path.split(".")
        obj: Any = self
        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part)
            elif isinstance(obj, list):
                try:
                    obj = obj[int(part)]
                except (IndexError, ValueError):
                    return None
            elif hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                return None
            if obj is None:
                return None
        return obj

    def _navigate_to_parent(self, parts: list[str]) -> Any:
        """Walk the state tree to the parent of the final key.

        Creates intermediate dicts / extends lists as needed.
        """
        obj: Any = self
        for part in parts[:-1]:
            if isinstance(obj, ConceptWorkshopState):
                child = getattr(obj, part, None)
                if child is None:
                    child = {}
                    setattr(obj, part, child)
                obj = child
            elif isinstance(obj, dict):
                if part not in obj:
                    obj[part] = {}
                obj = obj[part]
            elif isinstance(obj, list):
                idx = int(part)
                while len(obj) <= idx:
                    obj.append({})
                obj = obj[idx]
        return obj
