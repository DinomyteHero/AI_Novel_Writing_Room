"""Plot Architect agent — reads a scene card and produces a typed generation brief.

Emits JSON matching `schemas/generation_brief.json`. Consumed by Prose Stylist,
which surfaces the typed fields as labeled prompt sections.
"""

import json

from src.agents.base_agent import BaseAgent


# Required fields per schemas/generation_brief.json. Used for the semantic
# check after the LLM response returns — missing required fields log a
# warning but do not hard-fail (the orchestrator still needs a brief to
# continue; missing fields surface as reduced Prose Stylist guidance, which
# Final Gate catches downstream).
REQUIRED_BRIEF_FIELDS = [
    "scene_objective",
    "turning_point",
    "closing_beat",
    "emotional_arc",
    "target_word_count",
]


class PlotArchitect(BaseAgent):
    """Reads a scene card + story bible essentials and produces a typed
    generation brief for the Prose Stylist."""

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
            "Produce a typed generation brief as a JSON object matching the "
            "GenerationBrief schema. Required fields: scene_objective, "
            "turning_point (with trigger/shift/cost), closing_beat, "
            "emotional_arc (with start/shift/end), target_word_count.\n\n"
            "Optional fields: opening_mode (in_medias_res | sensory_hook | "
            "dialogue_hook | contrast), key_beats (3-5 items each with "
            "beat_description/state_change/pov_reaction), voice_guidance, "
            "forbidden_moves, delivery_preferences (reveal_mode: "
            "direct|gradual|subtext; exposition_budget: concise|moderate|none; "
            "register_override: string or null), required_hooks, "
            "required_subplots, required_revelations, anti_patterns.\n\n"
            "**Anti-pattern extraction (IMPORTANT):** scan the scene card's "
            "`notes` field for forbidden-move language ('do not open with a "
            "flashback', 'avoid exposition dump', etc.) and populate the "
            "`anti_patterns` array. Surfacing them explicitly in the brief "
            "raises their salience for the drafter; they would otherwise be "
            "buried in the raw scene card.\n\n"
            "**target_word_count** must equal scene_card.target_word_count — "
            "echo it so Prose Stylist does not have to cross-reference.\n\n"
            "Return JSON only. No surrounding prose or markdown fences."
        )

        return "\n\n".join(parts)

    async def run(self, context: dict) -> dict:
        """Run the Plot Architect and return a typed generation brief.

        Uses `complete_structured` so the LLM output is parsed as JSON with
        one automatic retry on parse failure. Semantic validation checks
        required fields; missing fields are logged but do not raise — the
        pipeline continues with a partial brief, and Final Gate catches
        downstream contract violations.
        """
        messages = self._build_messages(context)
        brief = await self.router.complete_structured(self.role, messages)

        missing = [f for f in REQUIRED_BRIEF_FIELDS if f not in brief]
        if missing:
            print(
                f"    PlotArchitect: generation_brief missing required fields "
                f"{missing} — Prose Stylist will render with reduced guidance"
            )

        return {
            "generation_brief": brief,
            "scene_card": context["scene_card"],
        }

    def _parse_response(self, response: str, context: dict) -> dict:
        # Not used — run() overrides the flow to use complete_structured
        return {}
