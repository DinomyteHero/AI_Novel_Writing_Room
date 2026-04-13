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

        # Phase 5: Voice rules injection
        voice_rules = context.get("voice_rules", "")
        if voice_rules:
            parts.append(voice_rules)

        scene_card = context.get("scene_card", {})
        target_words = scene_card.get("target_word_count")
        closing_hook = scene_card.get("closing_hook", "")
        characters_present = scene_card.get("characters_present", [])

        task_lines = [
            "## Task",
            "Write the complete scene prose following the generation brief above.",
            "Write in third-person limited POV. Focus on showing, not telling.",
            "Vary sentence length and structure. Avoid the banned phrases listed in constraints.",
            "The scene must contain the turning point specified in the brief.",
        ]
        if target_words:
            task_lines.append(
                f"Target length: approximately {target_words} words. "
                "Do not pad to reach the target — write the scene the story needs."
            )
        if closing_hook:
            task_lines.append(
                f"SCENE BOUNDARY: The scene ENDS at the closing hook: \"{closing_hook}\". "
                "Do not write any content beyond this moment. Do not advance into "
                "the next scene's territory."
            )
        if characters_present:
            task_lines.append(
                "CHARACTERS PRESENT: Only the following characters may have dialogue "
                f"or significant action in this scene: {', '.join(characters_present)}. "
                "Characters not in this list may only appear in the closing hook "
                "if specified there."
            )

        parts.append("\n".join(task_lines))

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        return {
            "prose": response,
            "scene_card": context.get("scene_card", {}),
        }
