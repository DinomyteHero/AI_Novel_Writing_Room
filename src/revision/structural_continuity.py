"""Band 1: Structural/Continuity revision agent.

Checks plot holes, arc consistency, timeline coherence, and knowledge state.
Returns revised prose with structural fixes applied.
"""

import json
from pathlib import Path

from src.agents.base_agent import BaseAgent


class StructuralContinuityReviewer(BaseAgent):
    """Band 1 revision agent for structural and continuity checks."""

    def __init__(self, router, role: str = "structural_continuity_reviewer"):
        super().__init__(router, role)

    def _load_system_prompt(self) -> str:
        """Load from revision_prompts directory."""
        prompt_path = Path(f"prompts/revision_prompts/structural_continuity.md")
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return f"You are the {self.role} agent."

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        scene_card = context["scene_card"]
        story_state_summary = context.get("story_state_summary", "")
        prior_chapter_summary = context.get("prior_chapter_summary", "")

        parts = []

        if prior_chapter_summary:
            parts.append(f"## Previous Chapter Summary\n{prior_chapter_summary}")

        if story_state_summary:
            parts.append(f"## Story State\n{story_state_summary}")

        parts.append(f"## Scene Card\n```json\n{json.dumps(scene_card, indent=2)}\n```")
        parts.append(f"## Current Prose\n{prose}")

        parts.append(
            "## Task\n"
            "Review this prose for structural and continuity issues. Fix:\n"
            "- Plot holes or logical gaps in the scene's events\n"
            "- Arc consistency — does the POV character's arc progress match the structural phase?\n"
            "- Timeline coherence — do temporal references make sense?\n"
            "- Knowledge state — does the prose respect what characters know/don't know?\n"
            "- Promise tracking — are planted promises referenced? Are paid promises set up?\n\n"
            "Return ONLY the complete revised prose text. Preserve the overall story, "
            "characters, and tone. Only fix structural/continuity issues."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        """Extract revised prose from the response."""
        # The response should be the complete revised prose
        return {"prose": response.strip()}
