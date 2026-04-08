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
        reference_authors: list[str] | None = None,
        pacing_feel: str | None = None,
        custom_banned_words: list[str] | None = None,
        custom_banned_phrases: list[str] | None = None,
        anti_patterns: list[str] | None = None,
        narrative_voice_notes: str | None = None,
    ) -> dict:
        """Assemble a complete voice_definition object.

        Merges custom anti-slop rules with global negative constraints.
        """
        anti_slop = self.merge_anti_slop(
            custom_banned_words or [],
            custom_banned_phrases or [],
        )

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
            "pacing_feel": pacing_feel or "",
            "anti_slop": anti_slop,
            "anti_patterns": final_anti_patterns,
            "narrative_voice_notes": narrative_voice_notes or "",
        }

    def merge_anti_slop(
        self,
        custom_banned_words: list[str],
        custom_banned_phrases: list[str],
    ) -> dict:
        """Merge custom anti-slop rules with global negative constraints.

        Global banned phrases come from config/negative_constraints.yaml.
        Custom rules are added on top (no duplicates).
        """
        # Extract global banned phrases by category
        global_phrases = []
        banned = self.global_constraints.get("banned_phrases", {})
        for category, phrases in banned.items():
            if isinstance(phrases, list):
                global_phrases.extend(phrases)

        # Extract AI tells as banned words
        global_words = banned.get("ai_tells", []) if isinstance(banned, dict) else []

        # Merge with custom (deduplicate)
        all_words = list(dict.fromkeys(global_words + custom_banned_words))
        all_phrases = list(dict.fromkeys(global_phrases + custom_banned_phrases))

        return {
            "banned_words": all_words,
            "banned_phrases": all_phrases,
        }

    def validate_voice_definition(self, voice_def: dict) -> list[str]:
        """Validate a voice definition. Returns list of errors (empty = valid)."""
        errors = []
        if not voice_def.get("pov_approach"):
            errors.append("voice_definition.pov_approach is required")
        if not voice_def.get("prose_register"):
            errors.append("voice_definition.prose_register is required")
        return errors
