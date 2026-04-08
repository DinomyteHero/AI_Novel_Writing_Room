"""Scene Economics validation for scene card justification."""

from __future__ import annotations

# Phrases that indicate a generic / placeholder why_now value.
_GENERIC_PATTERNS: list[str] = [
    "because the outline says so",
    "it was in the outline",
    "the plan requires it",
    "it needs to happen",
    "next in the sequence",
    "follows the previous scene",
    "plot progression",
    "to advance the plot",
    "because it's next",
    "outlined here",
    "as planned",
    "per the outline",
]


class SceneEconomics:
    """Validates that every scene card earns its place in the manuscript."""

    def validate_scene_cards(self, scene_cards: list[dict]) -> list[dict]:
        """Check that each scene card has a substantive why_now field.

        Returns issues for cards that are missing the field entirely or
        that contain only generic boilerplate text.
        """
        issues: list[dict] = []

        for card in scene_cards:
            chapter = card.get("chapter_number", "?")
            scene = card.get("scene_number", "?")
            why_now = card.get("why_now")

            if not why_now or not str(why_now).strip():
                issues.append({
                    "chapter_number": chapter,
                    "scene_number": scene,
                    "issue_type": "missing_why_now",
                    "description": (
                        f"Scene {scene} in chapter {chapter} has no "
                        f"'why_now' justification."
                    ),
                })
                continue

            normalised = str(why_now).strip().lower()
            if any(pattern in normalised for pattern in _GENERIC_PATTERNS):
                issues.append({
                    "chapter_number": chapter,
                    "scene_number": scene,
                    "issue_type": "generic_why_now",
                    "description": (
                        f"Scene {scene} in chapter {chapter} has a generic "
                        f"why_now ('{why_now}'). Each scene needs a specific "
                        f"causal or emotional justification."
                    ),
                })

        return issues
