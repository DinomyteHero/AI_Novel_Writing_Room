"""Final Gate agent — contract check on the polished text before save.

The Scene Gate evaluates the Prose Stylist draft. The Final Gate evaluates the
Quality Polish output against the same scene-card contract, catching violations
the polish pass may have introduced (wrong characters, closing-hook drift,
compression beyond the 80% floor). If Final Gate fails, the orchestrator
rejects the polish and saves the Scene-Gate-passed draft.

Reuses the verdict-derivation machinery and failure-code taxonomy from
`gate_critic` so both gates speak the same vocabulary.
"""

import json

from src.agents.base_agent import BaseAgent
from src.agents.gate_critic import (
    determine_route,
    determine_verdict,
)


# Only these five failure codes are in scope for the Final Gate per
# prompts/agent_system_prompts/final_gate.md. Out-of-scope codes (VOICE_VIOLATION,
# pacing codes, anti-pattern codes from the broader Scene Gate taxonomy) must
# be dropped — the prompt explicitly promises the model they will be, and
# historically the implementation was accepting them via ALL_CODES.
FINAL_GATE_CODES = {
    "CHARACTER_PRESENCE_VIOLATION",
    "CLOSING_HOOK_VIOLATION",
    "WORD_COUNT_VIOLATION",
    "MISSING_TURNING_POINT",
    "WEAK_TURNING_POINT",
}


class FinalGate(BaseAgent):
    """Contract check on polished prose. Narrower than Scene Gate — focuses on
    the violations a polish pass can introduce: character presence, closing hook
    boundary, word-count floor, and structural regression.
    """

    def __init__(self, router, role: str = "final_gate"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        scene_card = context["scene_card"]
        gate_passed_word_count = context.get("gate_passed_word_count", 0)

        polished_wc = len(prose.split())
        floor = int(gate_passed_word_count * 0.80) if gate_passed_word_count else 0

        hard_constraints = {
            "characters_present": scene_card.get("characters_present", []),
            "closing_hook": scene_card.get("closing_hook", ""),
            "target_word_count": scene_card.get("target_word_count", 0),
        }

        parts = []
        parts.append(
            f"## Scene Hard Constraints\n"
            f"```json\n{json.dumps(hard_constraints, indent=2)}\n```"
        )
        parts.append(f"## Scene Card (reference)\n```json\n{json.dumps(scene_card, indent=2)}\n```")
        parts.append(
            f"## Word Count Status\n"
            f"Gate-passed word count (pre-polish): {gate_passed_word_count}\n"
            f"Polished word count: {polished_wc}\n"
            f"Minimum floor (80% of gate-passed): {floor}\n"
            f"Polished is {'ABOVE' if polished_wc >= floor else 'BELOW'} the floor."
        )
        parts.append(f"## Polished Prose (to validate)\n{prose}")

        parts.append(
            "## Task\n"
            "Validate the polished prose against the scene hard constraints. This is a "
            "narrow contract check, not a full quality review — the Scene Gate has "
            "already signed off on the pre-polish draft. Focus exclusively on "
            "violations the polish pass could have introduced.\n\n"
            "## Checks\n"
            "1. **Character presence** — Only characters in `characters_present` may "
            "have dialogue or significant action. If a character not in the list "
            "speaks or acts meaningfully, emit `CHARACTER_PRESENCE_VIOLATION`.\n"
            "2. **Closing hook boundary** — The scene should end at or near the "
            "`closing_hook`. If content extends past it into the next scene's "
            "territory, emit `CLOSING_HOOK_VIOLATION`.\n"
            "3. **Word count floor** — Polished prose must be >= 80% of gate-passed "
            "word count. If below, emit `WORD_COUNT_VIOLATION`.\n"
            "4. **Structural regression** — Turning point must still be present and "
            "executed. If the polish removed or flattened it, emit "
            "`MISSING_TURNING_POINT` or `WEAK_TURNING_POINT`.\n\n"
            "Do NOT re-evaluate voice, AI-tells, pacing, or other polish-level "
            "concerns — those are out of scope for Final Gate.\n\n"
            "Valid failure codes for this gate:\n"
            "- CHARACTER_PRESENCE_VIOLATION\n"
            "- CLOSING_HOOK_VIOLATION\n"
            "- WORD_COUNT_VIOLATION\n"
            "- MISSING_TURNING_POINT\n"
            "- WEAK_TURNING_POINT\n\n"
            "Return JSON:\n"
            "```json\n"
            "{\n"
            '  "verdict": "pass | fail_structural | fail_voice | fail_polish",\n'
            '  "failure_codes": [\n'
            "    {\n"
            '      "code": "FAILURE_CODE_NAME",\n'
            '      "location": "paragraph or span",\n'
            '      "description": "specific explanation",\n'
            '      "fix_hint": "suggested direction"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n"
        )

        return "\n\n".join(parts)

    async def run(self, context: dict) -> dict:
        """Run the Final Gate. Verdict is derived from failure codes, same as Scene Gate.

        Also performs a programmatic word-count floor check: if polished prose is
        below 80% of gate-passed word count, inject WORD_COUNT_VIOLATION
        deterministically (same mechanism as Scene Gate's programmatic injection).
        """
        messages = self._build_messages(context)
        result = await self.router.complete_structured(self.role, messages)

        raw_failure_codes = result.get("failure_codes", [])
        failure_codes = []
        for fc in raw_failure_codes:
            if isinstance(fc, dict) and fc.get("code") in FINAL_GATE_CODES:
                failure_codes.append(fc)
            else:
                bad = fc.get("code") if isinstance(fc, dict) else fc
                print(f"    FinalGate: dropping out-of-scope failure_code {bad!r}")

        # Programmatic word-count floor enforcement (belt-and-suspenders with the
        # compression guard in the orchestrator, which runs before this gate).
        prose = context.get("prose", "")
        gate_passed_wc = context.get("gate_passed_word_count", 0)
        if gate_passed_wc:
            polished_wc = len(prose.split())
            if polished_wc < 0.80 * gate_passed_wc:
                already_present = any(
                    fc.get("code") == "WORD_COUNT_VIOLATION" for fc in failure_codes
                )
                if not already_present:
                    pct = (polished_wc / gate_passed_wc * 100) if gate_passed_wc else 0
                    failure_codes.append({
                        "code": "WORD_COUNT_VIOLATION",
                        "location": "whole scene",
                        "description": (
                            f"Polished prose is {polished_wc} words; gate-passed was "
                            f"{gate_passed_wc} ({pct:.0f}% of gate-passed, floor is 80%)."
                        ),
                        "fix_hint": (
                            "Rewrite polish in place rather than compressing below the floor."
                        ),
                    })
                    print(
                        f"    FinalGate: injecting WORD_COUNT_VIOLATION "
                        f"({polished_wc}/{gate_passed_wc} words, {pct:.0f}%)"
                    )

        verdict = determine_verdict(failure_codes)
        route_to = determine_route(verdict)
        severity = "blocking" if verdict in ("fail_structural", "fail_voice") else "non_blocking"

        model_verdict = result.get("verdict")
        if model_verdict and model_verdict != verdict:
            codes_list = [fc["code"] for fc in failure_codes]
            print(
                f"    FinalGate: model verdict '{model_verdict}' overridden to "
                f"'{verdict}' based on failure codes {codes_list}"
            )

        return {
            "verdict": verdict,
            "failure_codes": failure_codes,
            "severity": severity,
            "route_to": route_to,
        }

    def _parse_response(self, response: str, context: dict) -> dict:
        # Not used — run() overrides the flow to use complete_structured
        return {}
