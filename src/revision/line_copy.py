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
        scene_card = context.get("scene_card", {})
        negative_constraints = context.get("negative_constraints", "")
        quality_flags = context.get("quality_flags", [])
        quality_metrics = context.get("quality_metrics", {})

        parts = []

        if negative_constraints:
            parts.append(f"## Writing Constraints\n{negative_constraints}")

        if quality_flags:
            parts.append("## Quality Issues to Address")
            for flag in quality_flags:
                parts.append(f"- {flag}")
            parts.append("")

        # Structured quality data for targeted revision
        if quality_metrics:
            for scene_result in quality_metrics.get("per_scene", []):
                rep = scene_result.get("repetition", {})
                flagged_words = rep.get("flagged_words", [])
                if flagged_words:
                    word_list = ", ".join(
                        f'"{w["word"]}" (appears {w["count"]}x, expected max {w["expected_max"]})'
                        for w in flagged_words
                    )
                    parts.append(
                        f"## OVERUSED WORDS\n"
                        f"Replace or eliminate each of the following. Do not simply swap synonyms; "
                        f"restructure sentences to remove dependence on these words:\n{word_list}"
                    )

                pacing = scene_result.get("pacing", {})
                show_dont_tell = 0
                for flag_entry in pacing.get("flags", []):
                    if flag_entry.get("type") == "scene_type_imbalance":
                        show_dont_tell += 1
                slop = scene_result.get("slop", {})
                tell_count = slop.get("tell_not_show_count", 0) if slop else 0
                if tell_count > 0:
                    parts.append(
                        f"## SHOW-DON'T-TELL\n"
                        f"This scene has {tell_count} flagged violations. Find passages that state "
                        f"emotions or reactions directly and rewrite them to convey the same "
                        f"information through action, sensation, or dialogue."
                    )

        # Word Count Status — gated at the target boundary (ratio >= 1.0),
        # not the craft-editor expansion trigger (0.85). Revision bands come
        # after craft editor and should not undo its work by compressing a
        # scene that is already inside the target range. The ledger on run16
        # showed Band 3 removing 210 words from scene 1 (entered at 92% of
        # target, exited at 75%) — that cut would have been prevented here.
        target_wc = scene_card.get("target_word_count")
        current_wc = len(prose.split()) if prose else 0
        if target_wc and target_wc > 0:
            ratio = current_wc / target_wc
            if ratio >= 1.0:
                status = (
                    f"Current: {current_wc} words / Target: {target_wc} "
                    f"({ratio:.0%}). Scene is at or above target — standard "
                    f"cutting behavior applies."
                )
            else:
                status = (
                    f"Current: {current_wc} words / Target: {target_wc} "
                    f"({ratio:.0%}). Scene is under target. Do not reduce "
                    f"word count further: restrict cuts to clear errors only "
                    f"(AI-tells, banned phrases, exact duplicates, grammar, "
                    f"typos). Achieve rhythm, variety, and paragraph-length "
                    f"improvements through rewriting at equal-or-greater "
                    f"length, not through cutting."
                )
            parts.append(f"## Word Count Status\n{status}")

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
