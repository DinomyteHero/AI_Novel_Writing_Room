"""Band 3: Line/Copy editing agent.

Fixes prose quality, grammar/style, readability, AI-tells, and rhythm.
Returns directly revised prose (not suggestions — actual edits).
"""

import json
from pathlib import Path

from src.agents.base_agent import BaseAgent


class LineCopyEditor(BaseAgent):
    """Band 3 revision agent for line-level prose quality."""

    def __init__(self, router, role: str = "line_copy_editor"):
        super().__init__(router, role)

    def _load_system_prompt(self) -> str:
        """Load from revision_prompts directory."""
        prompt_path = Path(f"prompts/revision_prompts/line_copy.md")
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return f"You are the {self.role} agent."

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        negative_constraints = context.get("negative_constraints", "")
        quality_flags = context.get("quality_flags", [])

        parts = []

        if negative_constraints:
            parts.append(f"## Writing Constraints\n{negative_constraints}")

        if quality_flags:
            parts.append("## Quality Issues to Address")
            for flag in quality_flags:
                parts.append(f"- {flag}")
            parts.append("")

        parts.append(f"## Current Prose\n{prose}")

        parts.append(
            "## Task\n"
            "Edit this prose at the line level for quality. Fix:\n"
            "- Sentence variety — vary length, structure, and rhythm\n"
            "- Word choice — replace vague words with precise ones, cut unnecessary modifiers\n"
            "- Grammar/style — fix errors, ensure consistency with the style guide\n"
            "- AI-tell removal — eliminate banned phrases, cliches, and slop patterns\n"
            "- Paragraph rhythm — vary paragraph lengths, avoid monotonous blocks\n"
            "- Dialogue tags — vary beyond 'said' where appropriate, use action beats\n\n"
            "Return ONLY the complete revised prose text. Preserve the plot, "
            "characters, structure, and emotional beats. Only improve line-level quality."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        """Extract revised prose from the response."""
        return {"prose": response.strip()}
