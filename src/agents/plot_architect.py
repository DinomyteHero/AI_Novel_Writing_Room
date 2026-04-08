"""Plot Architect agent — reads a scene card and produces a generation brief."""

import json

from src.agents.base_agent import BaseAgent


class PlotArchitect(BaseAgent):
    """Reads a scene card + story bible essentials and produces a generation
    brief with structured directions for the Prose Stylist."""

    def __init__(self, router, role: str = "plot_architect"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        scene_card = context["scene_card"]
        bible_summary = context.get("bible_summary", "")
        previous_chapter_summary = context.get("previous_chapter_summary", "")

        parts = []

        if bible_summary:
            parts.append(f"## Story Bible Summary\n{bible_summary}")

        if previous_chapter_summary:
            parts.append(f"## Previous Chapter Summary\n{previous_chapter_summary}")

        parts.append(f"## Scene Card\n```json\n{json.dumps(scene_card, indent=2)}\n```")

        # Phase 5: Hook agenda
        hook_agenda = context.get("hook_agenda")
        if hook_agenda:
            parts.append(f"## Hook Agenda\n{hook_agenda}")

        # Phase 5: Arc context for POV character
        arc_context = context.get("arc_context")
        if arc_context:
            parts.append(f"## POV Character Arc\n{arc_context}")

        # Phase 5: Active subplots
        subplot_context = context.get("subplot_context")
        if subplot_context:
            parts.append(f"## Active Subplots\n{subplot_context}")

        parts.append(
            "## Task\n"
            "Produce a detailed generation brief for the Prose Stylist. Include:\n"
            "1. **Scene objective**: What this scene must accomplish structurally\n"
            "2. **Opening beat**: How to open (hook, image, dialogue)\n"
            "3. **Key beats**: 3-5 specific beats that must occur in order\n"
            "4. **Turning point execution**: How the turning point should land\n"
            "5. **Closing beat**: How to close (hook into next scene)\n"
            "6. **Emotional arc**: The emotional trajectory for the POV character\n"
            "7. **Voice guidance**: Specific notes for this POV character's voice\n"
            "8. **Constraints**: What must NOT happen (structural phase rules, canon limits)\n"
            "9. **Hook directives**: Which hooks to plant, advance, or resolve (from Hook Agenda)\n"
            "10. **Subplot directives**: Which subplot lines this scene should touch\n"
            "11. **Arc phase directive**: Where the POV character should be in their arc after this scene\n"
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        return {
            "generation_brief": response,
            "scene_card": context["scene_card"],
        }
