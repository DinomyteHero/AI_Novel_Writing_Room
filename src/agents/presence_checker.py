"""PresenceChecker agent — binary check for character-presence violations.

Grok 4.1 Fast @ t=0.1 in the shipping config: precise, cheap, single-purpose. Given final prose and a
scene card, identifies named characters who speak or physically act despite
being absent from ``characters_present``. Consumed by the save-blocker layer
as the ``CHARACTER_PRESENCE_BLOCKER`` source.
"""

import json
import logging
import re

from src.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)


class PresenceChecker(BaseAgent):
    """Detects character-presence violations in final prose.

    Output shape:
    ``{"violations": [{"character": "<name>", "evidence": "<quote>"}, ...]}``
    """

    def __init__(self, router, role: str = "presence_checker"):
        super().__init__(router, role)

    async def run(self, context: dict) -> dict:
        """Run the presence check and return ``{"violations": [...]}``."""
        messages = self._build_messages(context)
        try:
            result = await self.router.complete_structured(self.role, messages)
        except (json.JSONDecodeError, KeyError):
            raw = await self.router.complete(self.role, messages)
            result = self._parse_response(raw, context)
        return self._normalize_result(result)

    def _format_context(self, context: dict) -> str:
        prose = context.get("prose", "")
        scene_card = context.get("scene_card", {})
        characters_present = scene_card.get("characters_present", []) or []
        pov = scene_card.get("pov_character", "") or ""

        if characters_present:
            char_list = "\n".join(f"- {c}" for c in characters_present)
        else:
            char_list = "- (none listed)"

        return (
            "## Task\n"
            "Flag named characters who SPEAK or physically ACT in the prose below but "
            "are not in the characters_present list. Memories, dreams, visions, "
            "holograms, comms, reported speech, and subjects of discussion do NOT "
            "count as physical presence.\n\n"
            "## characters_present\n"
            f"{char_list}\n\n"
            f"POV character: {pov or '(unspecified)'}\n\n"
            "## Prose\n"
            f"{prose}\n\n"
            "## Output\n"
            "Return ONLY this JSON object:\n"
            '{"violations": [{"character": "<name>", "evidence": "<short quote>"}]}\n'
            'If there are no violations, return {"violations": []}.\n'
            "No markdown fences, no commentary."
        )

    def _parse_response(self, response: str, context: dict) -> dict:
        """Extract a JSON object from the raw model response."""
        stripped = re.sub(r"```(?:json)?\s*\n?", "", response).strip()
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass

        start = stripped.find("{")
        if start == -1:
            return {"violations": []}
        depth = 0
        for i in range(start, len(stripped)):
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stripped[start : i + 1])
                    except (json.JSONDecodeError, ValueError):
                        return {"violations": []}
        return {"violations": []}

    def _normalize_result(self, result: dict) -> dict:
        """Ensure the result shape is ``{"violations": [{character, evidence}]}``."""
        if not isinstance(result, dict):
            return {"violations": []}
        violations = result.get("violations", [])
        if not isinstance(violations, list):
            return {"violations": []}
        normalized = []
        for v in violations:
            if not isinstance(v, dict):
                continue
            char = (v.get("character") or "").strip()
            if not char:
                continue
            normalized.append(
                {
                    "character": char,
                    "evidence": (v.get("evidence") or "").strip(),
                }
            )
        return {"violations": normalized}
