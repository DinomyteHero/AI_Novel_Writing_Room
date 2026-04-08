"""Craft Editor agent — non-blocking voice/polish improvements.

Does NOT send scenes back to the Prose Stylist. Applies lighter revisions
for voice consistency, show-don't-tell, prose cliches, pacing, and
sentence variety. Prevents the "style homogenization through infinite
critique loops" failure mode.
"""

import json

from src.agents.base_agent import BaseAgent


class CraftEditor(BaseAgent):
    """Non-blocking quality improver. Applies voice and polish improvements
    to gate-passed prose without re-entering the gate."""

    def __init__(self, router, role: str = "craft_editor"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        scene_card = context["scene_card"]
        negative_constraints = context.get("negative_constraints", "")
        craft_notes = context.get("craft_notes", "")

        parts = []

        parts.append(f"## Scene Card\n```json\n{json.dumps(scene_card, indent=2)}\n```")
        parts.append(f"## Current Prose\n{prose}")

        if negative_constraints:
            parts.append(f"## Style Constraints\n{negative_constraints}")

        if craft_notes:
            parts.append(f"## Specific Improvement Notes\n{craft_notes}")

        parts.append(
            "## Task\n"
            "Improve this prose for voice and polish. DO NOT change the plot, "
            "structural beats, or turning point. Focus on:\n"
            "1. **Character voice consistency** — ensure dialogue and internal "
            "monologue match the POV character's voice profile\n"
            "2. **Show-don't-tell** — replace any told emotions with demonstrated ones\n"
            "3. **Prose cliche reduction** — eliminate AI-tell phrases and cliches "
            "from the constraints list\n"
            "4. **Pacing variety** — vary sentence length and structure\n"
            "5. **Sensory grounding** — ensure the setting is felt, not just described\n\n"
            "Return the COMPLETE revised prose. Do not add commentary or notes — "
            "output only the improved prose text."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        return {
            "prose": response,
            "scene_card": context["scene_card"],
            "was_craft_edited": True,
        }
