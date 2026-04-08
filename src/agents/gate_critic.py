"""Gate Critic agent — evaluates drafted prose against structural rubric.

Returns structured CriticFailure JSON with machine-readable failure codes
and routing decisions. This is the blocking gate — only structural failures
trigger a full rewrite loop.
"""

import json
from typing import Optional

from src.agents.base_agent import BaseAgent


# Valid failure codes from the taxonomy
STRUCTURAL_CODES = {
    "CONTINUITY_CONTRADICTION",
    "WEAK_TURNING_POINT",
    "MISSING_TURNING_POINT",
    "UNEARNED_RESOLUTION",
    "STRUCTURAL_PHASE_VIOLATION",
    "PROMISE_BROKEN",
    "MOTIVATION_GAP",
}

VOICE_CODES = {
    "OOC_DIALOGUE",
    "OOC_ACTION",
    "TELLING_NOT_SHOWING",
}

POLISH_CODES = {
    "EXPOSITION_LEAK",
    "PACING_FLATLINE",
    "PROSE_CLICHE_BURST",
    "CANON_VIOLATION",
}

ALL_CODES = STRUCTURAL_CODES | VOICE_CODES | POLISH_CODES


def determine_verdict(failure_codes: list[dict]) -> str:
    """Determine the overall verdict from a list of failure code dicts."""
    if not failure_codes:
        return "pass"

    codes = {fc["code"] for fc in failure_codes}

    if codes & STRUCTURAL_CODES:
        return "fail_structural"
    if codes & VOICE_CODES:
        return "fail_voice"
    return "fail_polish"


def determine_route(verdict: str) -> Optional[str]:
    """Map verdict to routing destination."""
    routing = {
        "pass": None,
        "fail_structural": "full_rewrite",
        "fail_voice": "targeted_revision",
        "fail_polish": "craft_edit",
    }
    return routing.get(verdict)


class GateCritic(BaseAgent):
    """Binary pass/fail evaluator. Checks structural integrity and returns
    structured CriticFailure JSON with failure codes and routing decisions."""

    def __init__(self, router, role: str = "gate_critic"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        scene_card = context["scene_card"]
        bible_summary = context.get("bible_summary", "")

        parts = []

        if bible_summary:
            parts.append(f"## Story Bible Summary\n{bible_summary}")

        parts.append(f"## Scene Card\n```json\n{json.dumps(scene_card, indent=2)}\n```")
        parts.append(f"## Drafted Prose\n{prose}")

        parts.append(
            "## Task\n"
            "Evaluate this drafted prose against the scene card requirements. "
            "Return a JSON object with the following structure:\n"
            "```json\n"
            "{\n"
            '  "verdict": "pass | fail_structural | fail_voice | fail_polish",\n'
            '  "failure_codes": [\n'
            "    {\n"
            '      "code": "FAILURE_CODE_NAME",\n'
            '      "location": "paragraph number or text span",\n'
            '      "description": "specific explanation",\n'
            '      "fix_hint": "suggested direction for revision"\n'
            "    }\n"
            "  ],\n"
            '  "severity": "blocking | non_blocking",\n'
            '  "route_to": "full_rewrite | targeted_revision | craft_edit | null",\n'
            '  "structural_score": 0.0-1.0,\n'
            '  "voice_score": 0.0-1.0,\n'
            '  "polish_score": 0.0-1.0\n'
            "}\n"
            "```\n\n"
            "Valid failure codes:\n"
            "- Structural: CONTINUITY_CONTRADICTION, WEAK_TURNING_POINT, "
            "MISSING_TURNING_POINT, UNEARNED_RESOLUTION, STRUCTURAL_PHASE_VIOLATION, "
            "PROMISE_BROKEN, MOTIVATION_GAP\n"
            "- Voice: OOC_DIALOGUE, OOC_ACTION, TELLING_NOT_SHOWING\n"
            "- Polish: EXPOSITION_LEAK, PACING_FLATLINE, PROSE_CLICHE_BURST, CANON_VIOLATION\n\n"
            "Check:\n"
            "1. Does the scene fulfill its mission from the scene card?\n"
            "2. Does the turning point land as specified?\n"
            "3. Are there continuity contradictions?\n"
            "4. Does the scene respect structural phase constraints?\n"
            "5. Are characters behaving consistently with their profiles?\n"
            "6. Is the prose quality acceptable (no info dumps, varied pacing)?\n"
        )

        return "\n\n".join(parts)

    async def run(self, context: dict) -> dict:
        """Run the gate critic and return structured evaluation."""
        messages = self._build_messages(context)
        result = await self.router.complete_structured(self.role, messages)

        # Validate and normalize the result
        failure_codes = result.get("failure_codes", [])
        verdict = result.get("verdict", determine_verdict(failure_codes))
        route_to = result.get("route_to", determine_route(verdict))
        severity = "blocking" if verdict in ("fail_structural", "fail_voice") else "non_blocking"

        return {
            "verdict": verdict,
            "failure_codes": failure_codes,
            "severity": severity,
            "route_to": route_to,
            "structural_score": result.get("structural_score", 0.0),
            "voice_score": result.get("voice_score", 0.0),
            "polish_score": result.get("polish_score", 0.0),
        }

    def _parse_response(self, response: str, context: dict) -> dict:
        # Not used — run() overrides the flow to use complete_structured
        return {}
