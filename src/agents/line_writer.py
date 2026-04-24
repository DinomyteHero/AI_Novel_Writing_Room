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
    """Prose line editor, post-drafter pass.

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
        prose = self._strip_wrapping(raw)
        prose = self._apply_pov_term_cleanup(prose, context)
        return {"prose": prose}

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
            "## Post-Generation Line-Edit Agenda\n"
            "This pass targets recurring DeepSeek prose issues seen in Ruusan "
            "bench runs. Preserve structure, but remove signs that the scene "
            "was expanded from a card.\n\n"
            "- Replace repeated card phrases with fresh sentence-level prose. "
            "Do not reuse scene-card wording verbatim unless it is a proper "
            "noun, required fixed text, or canonical phrase.\n"
            "- Reduce repeated Force-anomaly labels. Prefer consequence in "
            "action, dialogue, sensors, timing, and physical behavior over "
            "repeating words like 'wrongness', 'pressure', or 'chest'.\n"
            "- Remove AI-literary hedges and narrator labels such as 'the "
            "particular', 'the kind of', 'operational register', and 'braced "
            "for what came next'. Replace them with direct observation.\n"
            "- Make the page feel like Star Wars Legends EU commercial prose: "
            "clear movement, concrete ship/Temple/world detail, and dialogue "
            "doing real work. Do not turn the scene into literary summary.\n"
            "- Keep Ben's early-book interiority reactive and tactile, not "
            "diagnostic. Let him feel and decide before he explains.\n"
            "- Sharpen character voices already implied by the source and "
            "scene card. Add wit only when the source moment can naturally "
            "support it; do not bolt on jokes.\n"
            "- Mandatory cleanup: the returned prose must not contain these "
            "exact filler strings: 'the particular', 'the kind of', 'sort of', "
            "'not exactly', or 'braced for what came next'. Rewrite those "
            "phrases instead of preserving them. Also rewrite any sentence "
            "that reads like a mission-card label rather than POV prose.\n"
            "- Ben Skywalker close-third cleanup: do not use 'Luke's Order' "
            "or 'Luke’s Order' as narration unless a character is making a "
            "deliberately formal institutional distinction. Prefer 'his "
            "father's Order', 'his Order', 'the Jedi Order', or 'the Order "
            "his father rebuilt' according to the sentence.\n"
            "- Keep the central Force disturbance legible. Do not erase it; "
            "reduce repeated labels by varying the sentence work around it. "
            "Use concrete effects such as timing lag, failed blocks, altered "
            "sensorium, or bodily compensation. One or two explicit uses of "
            "'wrongness' are acceptable when the scene needs the term, but a "
            "cluster of repeated uses is not.\n"
            "- Return a visibly line-edited draft. If the source already works, "
            "still improve cadence, remove repeated phrasing, and sharpen "
            "transitions. Do not return the original text unchanged."
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

    @staticmethod
    def _apply_pov_term_cleanup(text: str, context: dict) -> str:
        """Clean narration-only terminology that leaks planning labels.

        The generated scene may inherit "Luke's Order" from planning context.
        In Ben Skywalker close third, that reads like an external franchise
        label rather than Ben's interior relationship to the institution.
        """
        scene_card = context.get("scene_card", {}) or {}
        if scene_card.get("pov_character") != "Ben Skywalker":
            return text

        replacements = {
            "Luke's Order": "his father's Order",
            "Luke’s Order": "his father's Order",
            "Luke's order": "his father's order",
            "Luke’s order": "his father's order",
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        return text
