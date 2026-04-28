"""Final Gate agent — advisory contract check on the current text before save.

The Scene Gate evaluates the Prose Stylist draft. The Final Gate evaluates the
post-polish text against the same scene-card contract, catching violations the
polish pass may have introduced (closing-hook drift, structural regression).
If the compression guard reverted severe collapse, Final Gate receives that
current prose instead. Under the relay v3 refactor, Final Gate runs as
telemetry only — its verdict is logged but does not control the save path.

Reuses the verdict-derivation machinery and failure-code taxonomy from
`gate_critic` so both gates speak the same vocabulary.
"""

import json

from src.agents.base_agent import BaseAgent
from src.agents.gate_critic import (
    determine_route,
    determine_verdict,
)


# Relay v3 (Stage 1h): word-count enforcement has been removed from the gate
# taxonomy — chapter-level telemetry tracks drift in
# src/pipeline/word_count_telemetry.py. Only the four structural contract
# checks remain. Out-of-scope codes emitted by the model are dropped.
FINAL_GATE_CODES = {
    # Forward Relay v4: CHARACTER_PRESENCE_VIOLATION removed. PresenceChecker
    # is the sole authority on character presence (save-blocker layer). Before
    # this change, the same polish-induced violation emitted three times:
    # GateCritic (pre-polish), FinalGate (post-polish), PresenceChecker
    # (save-time). Only PresenceChecker can actually block the save, so the
    # gate emissions were pure duplicates. Turning-point + closing-hook stay
    # in both gates because pre-polish vs post-polish is real regression
    # coverage.
    "CLOSING_HOOK_VIOLATION",
    "MISSING_TURNING_POINT",
    "WEAK_TURNING_POINT",
}


class FinalGate(BaseAgent):
    """Narrow contract check on current prose after the polish stage.

    Focuses on closing-hook boundary and structural regression. Character
    presence and word-count drift are handled elsewhere.
    """

    def __init__(self, router, role: str = "final_gate"):
        super().__init__(router, role)

    def _format_context(self, context: dict) -> str:
        prose = context["prose"]
        scene_card = context["scene_card"]

        hard_constraints = {
            "characters_present": scene_card.get("characters_present", []),
            "closing_hook": scene_card.get("closing_hook", ""),
        }

        parts = []
        parts.append(
            f"## Scene Hard Constraints\n"
            f"```json\n{json.dumps(hard_constraints, indent=2)}\n```"
        )
        parts.append(f"## Scene Card (reference)\n```json\n{json.dumps(scene_card, indent=2)}\n```")
        parts.append(f"## Current Prose (to validate)\n{prose}")

        parts.append(
            "## Task\n"
            "Validate the current prose against the scene hard constraints. This is a "
            "narrow contract check, not a full quality review — the Scene Gate has "
            "already signed off on the pre-polish draft. Focus exclusively on "
            "violations the polish pass could have introduced.\n\n"
            "## Checks\n"
            "1. **Closing hook boundary** — The scene should end at or near the "
            "`closing_hook`. If content extends past it into the next scene's "
            "territory, emit `CLOSING_HOOK_VIOLATION`.\n"
            "2. **Structural regression** — Turning point must still be present and "
            "executed. If the polish removed or flattened it, emit "
            "`MISSING_TURNING_POINT` or `WEAK_TURNING_POINT`.\n\n"
            "Character-presence enforcement is handled exclusively by the "
            "PresenceChecker at save time. Do NOT emit "
            "`CHARACTER_PRESENCE_VIOLATION` here — it is out of scope under "
            "Forward Relay v4.\n\n"
            "Do NOT re-evaluate word count, voice, AI-tells, pacing, or other "
            "polish-level concerns — those are out of scope for Final Gate. "
            "Chapter-level word-count drift is tracked separately as telemetry.\n\n"
            "Valid failure codes for this gate:\n"
            "- CLOSING_HOOK_VIOLATION\n"
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
        """Run the Final Gate. Verdict is derived from failure codes.

        Relay v3 (Stage 1h): the 80% word-count floor enforcement was removed —
        chapter-level drift is now telemetry, not a gate. Out-of-scope codes
        emitted by the model (including any lingering WORD_COUNT_VIOLATION)
        are dropped by the FINAL_GATE_CODES allowlist below.
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
