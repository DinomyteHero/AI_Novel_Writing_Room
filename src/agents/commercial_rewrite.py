"""CommercialRewrite agent -- bounded scene-level craft revision.

This pass sits between the initial draft/telemetry checks and QualityPolish.
It is allowed to rebalance delivery at the paragraph/scene-execution level
while preserving all load-bearing story contracts. It is intentionally
franchise-agnostic: franchise voice and terminology arrive through the normal
franchise profile/system prompt path, not hard-coded prompt text.
"""

from __future__ import annotations

import json

from src.agents.base_agent import BaseAgent


class CommercialRewrite(BaseAgent):
    """Bounded craft rewrite for drafts with commercial-readability issues.

    Output is revised prose (plain text), not JSON. Returns ``{"prose": str}``
    to match ProseStylist / QualityPolish contracts used by the orchestrator.
    """

    def __init__(self, router, role: str = "commercial_rewrite"):
        super().__init__(router, role)

    async def run(self, context: dict) -> dict:
        messages = self._build_messages(context)
        raw = await self.router.complete(self.role, messages)
        return {"prose": self._strip_wrapping(raw)}

    def _format_context(self, context: dict) -> str:
        source_prose = context.get("source_prose", "")
        source_word_count = len(source_prose.split())
        scene_card = context.get("scene_card", {}) or {}
        generation_brief = context.get("generation_brief", {}) or {}
        gate_evaluation = context.get("gate_evaluation", {}) or {}
        quality_metrics = context.get("quality_metrics") or {}
        diagnostic_reasons = context.get("diagnostic_reasons") or []
        negative_constraints = context.get("negative_constraints", "") or ""
        pov_approach = context.get("pov_approach", "") or ""

        hard_constraints = {
            "characters_present": scene_card.get("characters_present", []),
            "closing_hook": scene_card.get("closing_hook", ""),
            "target_word_count": scene_card.get("target_word_count"),
            "source_word_count": source_word_count,
            "minimum_rewrite_word_count": int(source_word_count * 0.75),
            "maximum_rewrite_word_count": int(source_word_count * 1.35),
            "pov_character": scene_card.get("pov_character", ""),
            "pov_approach": pov_approach,
        }

        parts: list[str] = []
        parts.append(
            "## Hard Constraints (do not violate)\n"
            f"```json\n{json.dumps(hard_constraints, indent=2)}\n```"
        )
        parts.append(
            "## Scene Card\n"
            f"```json\n{json.dumps(scene_card, indent=2)}\n```"
        )
        parts.append(
            "## Generation Brief (structural contract)\n"
            f"```json\n{json.dumps(generation_brief, indent=2)}\n```"
        )
        if gate_evaluation:
            compact_gate = {
                "verdict": gate_evaluation.get("verdict"),
                "failure_codes": gate_evaluation.get("failure_codes", []),
            }
            parts.append(
                "## Gate Findings\n"
                f"```json\n{json.dumps(compact_gate, indent=2)}\n```"
            )
        if quality_metrics:
            compact_metrics = {
                "overall_score": quality_metrics.get("overall_score"),
                "passed": quality_metrics.get("passed"),
                "flags": (quality_metrics.get("flags") or [])[:15],
            }
            parts.append(
                "## Quality Metric Findings\n"
                f"```json\n{json.dumps(compact_metrics, indent=2)}\n```"
            )
        if diagnostic_reasons:
            parts.append(
                "## Revision Priorities\n"
                + "\n".join(f"- {reason}" for reason in diagnostic_reasons[:12])
            )
        if negative_constraints:
            parts.append(f"## Style Constraints\n{negative_constraints}")
        parts.append(f"## Source Prose\n{source_prose}")
        parts.append(
            "## Task\n"
            "Rewrite the source prose for clean execution in the project's "
            "declared prose register.\n\n"
            "You may rebalance paragraphs and sentences to improve scene-present "
            "readability: convert explanatory interiority into behavior, action, "
            "dialogue pressure, concrete sensory beats, or sharper close-POV "
            "reaction. Reduce repeated phrasing and repeated metaphor domains. "
            "Vary paragraph rhythm. Keep the scene moving through enacted choices "
            "rather than narrator explanation.\n\n"
            "Hard preservation rules:\n"
            "- Preserve every story beat in the same order.\n"
            "- Preserve the turning point and closing hook.\n"
            "- Preserve POV and do not head-hop.\n"
            "- Preserve the character roster; no new named characters may speak or act.\n"
            "- Preserve canon/franchise terminology exactly unless a finding asks for a fix.\n"
            "- Do not add new lore, exposition, plot content, or scene aftermath.\n"
            "- End at the closing hook. Do not continue into the next scene.\n\n"
            "Length rule: stay within the minimum/maximum rewrite word counts "
            "listed above. Do not summarize, compress, or expand into a new "
            "scene.\n\n"
            "Return ONLY the complete revised prose. No commentary, no notes, no "
            "markdown fences."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        return {"prose": self._strip_wrapping(response)}

    @staticmethod
    def _strip_wrapping(raw: str) -> str:
        text = (raw or "").strip()
        if text.startswith("```"):
            first_newline = text.find("\n")
            text = text[first_newline + 1 :] if first_newline != -1 else text[3:]
        if text.endswith("```"):
            text = text[:-3].rstrip()
        return text.strip()
