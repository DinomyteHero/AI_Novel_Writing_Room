"""VoiceDiscovery — guides voice definition during the workshop.

Step 5 of the expanded concept workshop. Builds the voice_definition
object from workshop decisions and merges anti-slop rules with the
global negative constraints.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


class VoiceDiscovery:
    """Assembles and validates the voice_definition object."""

    def __init__(
        self,
        negative_constraints_path: str = "config/negative_constraints.yaml",
    ):
        self.global_constraints = self._load_constraints(negative_constraints_path)

    def _load_constraints(self, path: str) -> dict:
        """Load global negative constraints."""
        p = Path(path)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        return {}

    def build_voice_definition(
        self,
        pov_approach: str,
        prose_register: str,
        reference_authors: list[dict] | None = None,
        character_voices: dict | None = None,
        anti_slop_rules: list[str] | None = None,
        anti_patterns: list[str] | None = None,
        force_description_guidelines: str | None = None,
        pacing_feel: str | None = None,
        narrative_voice_notes: str | None = None,
    ) -> dict:
        """Assemble a complete voice_definition object (post-Phase-5 structure).

        The new structure replaces the legacy nested anti_slop dict with a
        flat anti_slop_rules list, adds character_voices and
        force_description_guidelines, and treats reference_authors as a list
        of objects with emulate/avoid guidance.

        reference_authors items should be dicts with keys:
          {author, what_to_emulate, what_to_avoid}

        anti_slop_rules is a flat list of rule strings. Global negative
        constraints (from config/negative_constraints.yaml) are merged in
        as individual rule sentences so the voice checker has a single
        flat list to enforce.
        """
        merged_rules = self.merge_anti_slop_rules(anti_slop_rules or [])

        # Default anti-patterns if none provided
        default_anti_patterns = [
            "Every chapter opening with weather/environment description",
            "Every chapter ending with a reflective sigh or 'little did they know' hook",
            "Characters nodding, smiling, or raising eyebrows as default body language",
            "Dialogue attribution using anything other than said/asked more than 20% of the time",
            "Back-to-back paragraphs starting with the same word",
        ]
        final_anti_patterns = (anti_patterns or []) + [
            p for p in default_anti_patterns
            if p not in (anti_patterns or [])
        ]

        return {
            "pov_approach": pov_approach,
            "prose_register": prose_register,
            "reference_authors": reference_authors or [],
            "character_voices": character_voices or {},
            "anti_slop_rules": merged_rules,
            "anti_patterns": final_anti_patterns,
            "force_description_guidelines": force_description_guidelines or "",
            "pacing_feel": pacing_feel or "",
            "narrative_voice_notes": narrative_voice_notes or "",
        }

    def merge_anti_slop_rules(
        self,
        custom_rules: list[str],
    ) -> list[str]:
        """Merge custom anti-slop rules with global negative constraints.

        Returns a single flat list of rule strings. Global banned phrases
        and banned words (from config/negative_constraints.yaml) are
        converted to rule sentences of the form
        "Never use '<phrase>'" so they can sit alongside the custom
        hand-written rules. Duplicates (by string equality) are removed.
        """
        rules: list[str] = []

        banned = self.global_constraints.get("banned_phrases", {})
        if isinstance(banned, dict):
            for category, phrases in banned.items():
                if isinstance(phrases, list):
                    for phrase in phrases:
                        rules.append(f"Never use '{phrase}'")

        # Append custom rules verbatim — they are already hand-written.
        rules.extend(custom_rules)

        # Deduplicate while preserving order.
        return list(dict.fromkeys(rules))

    def validate_voice_definition(self, voice_def: dict) -> list[str]:
        """Validate a voice definition. Returns list of errors (empty = valid)."""
        errors = []
        if not voice_def.get("pov_approach"):
            errors.append("voice_definition.pov_approach is required")
        if not voice_def.get("prose_register"):
            errors.append("voice_definition.prose_register is required")
        return errors
