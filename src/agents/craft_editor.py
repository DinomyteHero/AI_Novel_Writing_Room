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
        # Optional: orchestrator can pass a structural_flags_clean bool
        # indicating whether structural-continuity and low-dialogue flags
        # were absent on the last measurement. When absent from context,
        # treat as clean (the craft editor still falls back to cuts-only
        # below 85% if unclean, so this defaults to the safer choice of
        # allowing expansion when we lack signal).
        structural_flags_clean = context.get("structural_flags_clean", True)

        parts = []

        parts.append(f"## Scene Card\n```json\n{json.dumps(scene_card, indent=2)}\n```")
        parts.append(f"## Current Prose\n{prose}")

        # Word Count Status — drives the length-aware editing branch in
        # craft_editor.md. Cuts-first when at/over target; expand
        # under-described beats when below 85% and structural flags are
        # clean; hybrid (cuts allowed but no expansion pressure) otherwise.
        target_wc = scene_card.get("target_word_count")
        current_wc = len(prose.split()) if prose else 0
        if target_wc and target_wc > 0:
            ratio = current_wc / target_wc
            if ratio >= 0.85:
                status = (
                    f"Current: {current_wc} words / Target: {target_wc} "
                    f"({ratio:.0%}). Scene is at or above target — favor cuts."
                )
            elif structural_flags_clean:
                status = (
                    f"Current: {current_wc} words / Target: {target_wc} "
                    f"({ratio:.0%}). Scene is under-length AND structural flags are clean. "
                    f"Expand under-described beats to reach 90-100% of target. Add "
                    f"environmental detail, physical action between dialogue, or unspoken "
                    f"reaction — preserve plot, scene goal, and emotional trajectory."
                )
            else:
                status = (
                    f"Current: {current_wc} words / Target: {target_wc} "
                    f"({ratio:.0%}). Scene is under-length BUT structural flags are active. "
                    f"Do not expand — fix the structural issue in subsequent revision bands. "
                    f"If editing now, minimize cuts to avoid further compression."
                )
            parts.append(f"## Word Count Status\n{status}")

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
            "5. **Sensory grounding** — ensure the setting is felt, not just described\n"
            "6. **Canon compliance** — if Canon Notes are provided in the Specific "
            "Improvement Notes section, treat every canon correction as a HARD "
            "CONSTRAINT. Do not revert corrected terminology, names, or "
            "universe-specific references to their pre-correction forms. These "
            "corrections have been validated by the Canon Expert.\n\n"
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
