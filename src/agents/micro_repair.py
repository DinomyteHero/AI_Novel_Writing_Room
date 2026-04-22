"""MicroRepair agent -- bounded exact-span patch generator for final prose.

This agent does NOT free-write prose. It proposes a tiny list of literal
substring replacements that the orchestrator can apply safely after
post-polish checks discover a narrow issue (currently: presence violations).

The runtime enforces additional deterministic guards after the model returns:
- only exact literal substitutions, never regex
- per-scene repair-count cap
- changed-character budget cap
- unique-occurrence requirement for each pattern
- revalidation after patching before save
"""

from __future__ import annotations

import json
import re

from src.agents.base_agent import BaseAgent


class MicroRepair(BaseAgent):
    """Generate exact-span repair patches for narrow post-check issues."""

    def __init__(self, router, role: str = "micro_repair"):
        super().__init__(router, role)

    async def run(self, context: dict) -> dict:
        """Return ``{"repairs": [...], "summary": "..."}``."""
        messages = self._build_messages(context)
        try:
            result = await self.router.complete_structured(self.role, messages)
        except (json.JSONDecodeError, KeyError):
            raw = await self.router.complete(self.role, messages)
            result = self._parse_response(raw, context)
        return self._normalize_result(result)

    def _format_context(self, context: dict) -> str:
        prose = context.get("prose", "")
        scene_card = context.get("scene_card", {}) or {}
        repair_requests = context.get("repair_requests", []) or []

        parts = [
            "## Scene Card",
            f"```json\n{json.dumps(scene_card, indent=2)}\n```",
            "",
            "## Repair Requests",
            json.dumps(repair_requests, indent=2),
            "",
            "## Current Prose",
            prose,
            "",
            "## Task",
            "Produce the SMALLEST safe set of literal substring repairs needed to resolve the listed requests.",
            "",
            "Rules:",
            "- Use exact literal substrings copied from the current prose. No regex.",
            "- Prefer deleting or replacing one sentence / clause / dialogue line over rewriting a whole paragraph.",
            "- Do not add new beats, new named characters, new canon facts, or new exposition.",
            "- Do not move scene structure around.",
            "- If a request cannot be fixed safely with an exact-span patch, omit it.",
            "",
            "Return ONLY this JSON object:",
            "```json",
            "{",
            '  "summary": "one-sentence assessment",',
            '  "repairs": [',
            "    {",
            '      "issue_type": "presence_violation",',
            '      "pattern": "EXACT literal substring from the prose",',
            '      "replacement": "replacement text, possibly empty",',
            '      "reason": "why this exact patch resolves the issue"',
            "    }",
            "  ]",
            "}",
            "```",
            'If no safe exact-span repair exists, return {"summary": "...", "repairs": []}.',
        ]
        return "\n".join(parts)

    def _parse_response(self, response: str, context: dict) -> dict:
        stripped = re.sub(r"```(?:json)?\s*\n?", "", response).strip()
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass

        start = stripped.find("{")
        if start == -1:
            return {"summary": "", "repairs": []}
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
                        return {"summary": "", "repairs": []}
        return {"summary": "", "repairs": []}

    @staticmethod
    def _normalize_result(result: dict) -> dict:
        if not isinstance(result, dict):
            return {"summary": "", "repairs": []}
        repairs = result.get("repairs", [])
        if not isinstance(repairs, list):
            repairs = []
        normalized: list[dict] = []
        for repair in repairs:
            if not isinstance(repair, dict):
                continue
            issue_type = str(repair.get("issue_type", "")).strip()
            pattern = repair.get("pattern")
            replacement = repair.get("replacement")
            if not issue_type or not isinstance(pattern, str) or not pattern:
                continue
            if replacement is None:
                replacement = ""
            if not isinstance(replacement, str):
                continue
            normalized.append(
                {
                    "issue_type": issue_type,
                    "pattern": pattern,
                    "replacement": replacement,
                    "reason": str(repair.get("reason", "")).strip(),
                }
            )
        return {
            "summary": str(result.get("summary", "")).strip(),
            "repairs": normalized,
        }
