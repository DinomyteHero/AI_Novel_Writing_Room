"""LineWriter agent — prose line editor, NOT drafter (Stage 3 of relay v3).

Runs between the drafter (ProseStylist) and the copy editor (QualityPolish).
The drafter has already settled structure, beats, POV, and characters_present;
LineWriter rewrites at sentence level for rhythm, imagery, metaphor freshness,
dialogue beat-timing, and voice texture — without touching structure or canon.

The preservation-critical constraints are passed explicitly in the context
rather than read from the ambient ContextAssembler so this agent cannot be
accidentally misused from a call site that forgets to wire one of them:
``source_prose``, ``scene_card``, ``generation_brief``, ``characters_present``,
``franchise_profile_text``, ``pov_approach``.
"""

from __future__ import annotations

import json

from src.agents.base_agent import BaseAgent


class LineWriter(BaseAgent):
    """Prose line editor — GPT 5.4 @ t=0.8, post-drafter pass.

    Output is revised prose (plain text), not JSON. Returns ``{"prose": str}``
    to match the ProseStylist / QualityPolish contract used by the
    orchestrator.
    """

    def __init__(self, router, role: str = "line_writer"):
        super().__init__(router, role)

    async def run(self, context: dict) -> dict:
        """Run the line editor. Returns ``{"prose": <revised prose>}``."""
        messages = self._build_messages(context)
        raw = await self.router.complete(self.role, messages)
        return {"prose": self._strip_wrapping(raw)}

    def _format_context(self, context: dict) -> str:
        source_prose = context.get("source_prose", "")
        scene_card = context.get("scene_card", {}) or {}
        generation_brief = context.get("generation_brief", {}) or {}
        characters_present = (
            context.get("characters_present")
            or scene_card.get("characters_present", [])
            or []
        )
        pov_approach = context.get("pov_approach", "") or ""
        # franchise_profile_text is injected as a second system message by
        # BaseAgent._build_messages when present in the context — we don't
        # need to include it in the user prompt as well.

        parts: list[str] = []

        if pov_approach:
            parts.append(f"## POV Approach\n{pov_approach}")

        parts.append(
            "## characters_present (do not violate)\n"
            + "\n".join(f"- {c}" for c in characters_present)
        )

        parts.append(
            "## Scene Card\n"
            f"```json\n{json.dumps(scene_card, indent=2)}\n```"
        )
        parts.append(
            "## Generation Brief (structural contract)\n"
            f"```json\n{json.dumps(generation_brief, indent=2)}\n```"
        )
        parts.append(
            "## Source Prose (from drafter)\n"
            f"{source_prose}"
        )
        parts.append(
            "## Task\n"
            "Line-edit the source prose. Preserve every beat in the same order, "
            "executed by the same character. Preserve the turning point's "
            "position and executor. Preserve POV. Preserve characters_present. "
            "Preserve every canonical fact and franchise term. Preserve "
            "character voice.\n\n"
            "Within those constraints, improve sentence rhythm, imagery, "
            "metaphor freshness, dialogue beat-timing, and concrete sensory "
            "detail. Target 40–70% sentence-level change. Do NOT rewrite "
            "paragraphs wholesale. Do NOT introduce new characters, new beats, "
            "new franchise terms, or new plot content.\n\n"
            "Return ONLY the revised prose. No preamble, no commentary, no "
            "markdown fences, no change notes."
        )

        return "\n\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        # Unused — run() overrides the plain-completion flow.
        return {"prose": self._strip_wrapping(response)}

    @staticmethod
    def _strip_wrapping(raw: str) -> str:
        """Trim markdown fences and extraneous whitespace from the model output.

        GPT occasionally wraps output in ```…``` despite the explicit
        instruction not to. Strip those defensively so downstream agents
        receive clean prose.
        """
        text = (raw or "").strip()
        if text.startswith("```"):
            # Drop opening fence line (may have a language hint).
            first_newline = text.find("\n")
            if first_newline != -1:
                text = text[first_newline + 1 :]
            else:
                text = text[3:]
        if text.endswith("```"):
            text = text[:-3].rstrip()
        return text.strip()
