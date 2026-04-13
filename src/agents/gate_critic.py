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
    "CANON_VIOLATION",
    # Phase 5 additions
    "CHARACTER_ARC_STALL",
    "HOOK_VIOLATION",
    "SUBPLOT_DRIFT",
    # Scene card compliance
    "CLOSING_HOOK_VIOLATION",
    "CHARACTER_PRESENCE_VIOLATION",
    "OPENING_HOOK_MISMATCH",
}

VOICE_CODES = {
    "OOC_DIALOGUE",
    "OOC_ACTION",
    "TELLING_NOT_SHOWING",
    # Phase 5 additions
    "TERMINOLOGY_DRIFT",
    "VOICE_DEFINITION_VIOLATION",
}

POLISH_CODES = {
    "EXPOSITION_LEAK",
    "PACING_FLATLINE",
    "PROSE_CLICHE_BURST",
    "WORD_COUNT_VIOLATION",
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

        # Pre-compute word count so the LLM doesn't have to count
        word_count = len(prose.split())
        target = scene_card.get("target_word_count", 0)
        if target:
            pct = (word_count / target * 100) if target else 0
            parts.append(
                f"## Word Count (pre-computed)\n"
                f"Actual: {word_count} words | Target: {target} words | "
                f"Ratio: {pct:.0f}% | Tolerance: +/- 20%"
            )

        parts.append(
            "## Task\n"
            "Evaluate this drafted prose against the scene card requirements.\n\n"
            "## Scoring Instructions\n\n"
            "Before assigning scores, list 3-5 specific issues you found in the prose. "
            "For each issue, note the severity (minor/moderate/major) and which score it affects.\n\n"
            "Then assign scores using these calibration anchors:\n"
            "- 0.60-0.69: Significant issues — structural gaps, voice inconsistencies, or multiple polish problems\n"
            "- 0.70-0.79: Acceptable first draft — minor structural issues, some voice drift, typical AI-generated prose patterns\n"
            "- 0.80-0.89: Strong draft — structure is sound, voice is consistent, only minor polish issues remain\n"
            "- 0.90-1.00: Exceptional — reserved for prose that reads as polished, published-quality fiction with no detectable AI patterns\n\n"
            "Most AI-generated first drafts should score in the 0.70-0.79 range. "
            "A score above 0.90 on any dimension should be rare and justified by the absence of specific issues.\n\n"
            "## Check List\n"
            "1. Does the scene fulfill its mission from the scene card?\n"
            "2. Does the turning point land as specified?\n"
            "3. Are there continuity contradictions?\n"
            "4. Does the scene respect structural phase constraints?\n"
            "5. Are characters behaving consistently with their profiles?\n"
            "6. Is the prose quality acceptable (no info dumps, varied pacing)?\n"
            "7. Has the POV character's arc phase progressed as expected? (CHARACTER_ARC_STALL)\n"
            "8. Were required hooks planted/advanced/resolved per the hook agenda? (HOOK_VIOLATION)\n"
            "9. Are active subplots addressed as expected? (SUBPLOT_DRIFT)\n"
            "10. Are in-universe terms spelled correctly per the terminology registry? (TERMINOLOGY_DRIFT)\n"
            "11. Does the prose follow voice definition rules (banned words, anti-patterns)? (VOICE_DEFINITION_VIOLATION)\n"
            "12. Is the prose within +/- 20% of the target_word_count? Use the pre-computed word count above — do NOT count words yourself. (WORD_COUNT_VIOLATION)\n"
            "13. Does the scene end at or near the closing_hook? Does any content extend past it into the next scene? (CLOSING_HOOK_VIOLATION)\n"
            "14. Do only characters in characters_present have dialogue or significant action? (CHARACTER_PRESENCE_VIOLATION)\n"
            "15. Does the scene open consistent with the opening_hook if specified? (OPENING_HOOK_MISMATCH)\n\n"
            "Valid failure codes:\n"
            "- Structural: CONTINUITY_CONTRADICTION, WEAK_TURNING_POINT, "
            "MISSING_TURNING_POINT, UNEARNED_RESOLUTION, STRUCTURAL_PHASE_VIOLATION, "
            "PROMISE_BROKEN, MOTIVATION_GAP, CHARACTER_ARC_STALL, HOOK_VIOLATION, SUBPLOT_DRIFT, CANON_VIOLATION, "
            "CLOSING_HOOK_VIOLATION, CHARACTER_PRESENCE_VIOLATION, OPENING_HOOK_MISMATCH\n"
            "- Voice: OOC_DIALOGUE, OOC_ACTION, TELLING_NOT_SHOWING, "
            "TERMINOLOGY_DRIFT, VOICE_DEFINITION_VIOLATION\n"
            "- Polish: EXPOSITION_LEAK, PACING_FLATLINE, PROSE_CLICHE_BURST, WORD_COUNT_VIOLATION\n\n"
            "Return a JSON object with the following structure:\n"
            "```json\n"
            "{\n"
            '  "reasoning": "List 3-5 specific issues found, each with severity (minor/moderate/major) and affected dimension",\n'
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
            "```\n"
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
