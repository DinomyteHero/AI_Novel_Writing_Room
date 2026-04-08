"""Pressure Matrix validation for per-character tension escalation."""

from __future__ import annotations


class PressureMatrix:
    """Validates that character pressure escalates properly across chapters.

    The matrix maps character names to arrays of per-chapter pressure objects,
    each containing chapter, external_pressure, internal_pressure, and
    pressure_level (1-10).
    """

    def __init__(self, matrix: dict) -> None:
        self._matrix: dict[str, list[dict]] = matrix

    def validate_escalation(self) -> list[dict]:
        """Flag characters with flat or non-escalating pressure arcs.

        Checks:
        - Coasting: pressure_level <= 2 for more than 1 consecutive chapter.
        - Flat arc: average pressure in the first third >= average in the
          last third (pressure should generally increase).
        - No climax peak: the maximum pressure does not occur in the final
          third of the story.
        """
        issues: list[dict] = []

        for character, entries in self._matrix.items():
            if not entries:
                continue

            sorted_entries = sorted(entries, key=lambda e: e["chapter"])
            levels = [e["pressure_level"] for e in sorted_entries]

            # --- Coasting check ---
            coast_run = 0
            for level in levels:
                if level <= 2:
                    coast_run += 1
                    if coast_run > 1:
                        issues.append({
                            "character": character,
                            "issue_type": "coasting",
                            "description": (
                                f"'{character}' has pressure_level <= 2 for "
                                f"more than 1 consecutive chapter."
                            ),
                        })
                        break
                else:
                    coast_run = 0

            # --- Flat arc check ---
            n = len(levels)
            if n >= 3:
                third = max(n // 3, 1)
                early_avg = sum(levels[:third]) / third
                late_avg = sum(levels[-third:]) / third

                if early_avg >= late_avg:
                    issues.append({
                        "character": character,
                        "issue_type": "flat_arc",
                        "description": (
                            f"'{character}' pressure does not escalate: "
                            f"early average ({early_avg:.1f}) >= late average "
                            f"({late_avg:.1f})."
                        ),
                    })

            # --- No climax peak check ---
            if n >= 3:
                third = max(n // 3, 1)
                final_third_start = n - third
                max_level = max(levels)
                peak_in_final = any(
                    levels[i] == max_level
                    for i in range(final_third_start, n)
                )
                if not peak_in_final:
                    issues.append({
                        "character": character,
                        "issue_type": "no_climax_peak",
                        "description": (
                            f"'{character}' peak pressure ({max_level}) does "
                            f"not occur in the final third of the story."
                        ),
                    })

        return issues

    def get_pressure_for_chapter(
        self, character: str, chapter: int
    ) -> dict | None:
        """Return the pressure entry for a specific character and chapter."""
        entries = self._matrix.get(character, [])
        for entry in entries:
            if entry["chapter"] == chapter:
                return entry
        return None

    def get_max_pressure_chapter(self, character: str) -> int:
        """Return the chapter number where the character hits peak pressure."""
        entries = self._matrix.get(character, [])
        if not entries:
            raise KeyError(f"No pressure data for character: {character}")
        return max(entries, key=lambda e: e["pressure_level"])["chapter"]
