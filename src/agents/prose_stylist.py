"""Prose Stylist agent — takes a generation brief + assembled context and drafts prose."""

from src.agents.base_agent import BaseAgent


class ProseStylist(BaseAgent):
    """Takes the generation brief from the Plot Architect plus assembled
    context from the ContextAssembler, and drafts the actual prose chapter."""

    def __init__(self, router, role: str = "prose_stylist"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        generation_brief = context["generation_brief"]
        assembled_context = context.get("assembled_context", "")
        negative_constraints = context.get("negative_constraints", "")
        failure_context = context.get("failure_context", "")

        parts = []

        if assembled_context:
            parts.append(assembled_context)

        parts.append(f"## Generation Brief\n{generation_brief}")

        if negative_constraints:
            parts.append(f"## Writing Constraints\n{negative_constraints}")

        if failure_context:
            parts.append(
                f"## Revision Notes (from previous attempt)\n{failure_context}"
            )

        parts.append(
            "## Task\n"
            "Write the complete scene prose following the generation brief above. "
            "Write in third-person limited POV. Focus on showing, not telling. "
            "Vary sentence length and structure. Avoid the banned phrases listed in constraints. "
            "The scene must contain the turning point specified in the brief."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        return {
            "prose": response,
            "scene_card": context.get("scene_card", {}),
        }
