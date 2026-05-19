"""RhythmEditor agent -- bounded literal-edit pass to fix detected rhythm issues.

This agent is the active complement to ``src/quality/rhythm_validator.py``. The
validator detects rhythm problems (em-dash overuse, staccato clusters,
monotonous sentence openers, abstract-construction tics); the editor proposes
exact-span literal substring edits to fix them. The orchestrator applies the
edits under the same deterministic safety caps that protect ``MicroRepair``.

What the agent CAN fix with literal edits:

- ``rhythm.em_dash_overuse`` — replace ``She walked — slowly — to the door``
  with ``She walked slowly to the door``.
- ``rhythm.staccato_cluster`` — merge ``He moved. He stopped.`` into
  ``He moved, then stopped.``.
- ``rhythm.opener_monotone`` — replace ``He walked to the door`` with
  ``Walking to the door, he reached for the handle`` (or similar).
- ``rhythm.abstract_tic`` — replace ``the particular weight of grief`` with
  ``grief, heavy and unwelcome``.

What the agent CANNOT fix with literal edits and should explicitly skip:

- ``rhythm.dialogue_starved`` — adding new dialogue requires writing content,
  not substituting it. The agent returns no edit for this issue type so the
  drafter pass on the next chapter can re-balance instead.

Safety model mirrors ``MicroRepair`` line for line: literal substrings only,
unique-occurrence requirement, per-scene edit cap, total changed-character
budget, ratio ceiling. Caps are enforced deterministically in the orchestrator
apply path regardless of what the model returns.
"""

from __future__ import annotations

import json
import re

from src.agents.base_agent import BaseAgent


class RhythmEditor(BaseAgent):
    """Generate bounded literal-edit patches that fix detected rhythm issues."""

    def __init__(self, router, role: str = "rhythm_editor"):
        super().__init__(router, role)

    async def run(self, context: dict) -> dict:
        """Return ``{"summary": str, "edits": [...]}``.

        ``context`` shape::

            {
              "prose": str,                # current scene prose
              "scene_card": dict,          # for character/voice context
              "rhythm_issues": [           # from RhythmValidator
                {"code": "rhythm.em_dash_overuse", "severity": "medium",
                 "message": "...", "metric_value": 10.1, "threshold": 6.0},
                ...
              ],
            }
        """
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
        rhythm_issues = context.get("rhythm_issues", []) or []

        # Filter out issue types this agent cannot safely fix with literal
        # substitutions. dialogue_starved requires generative work that
        # belongs in the drafter, not in a literal-edit pass.
        fixable = [
            issue for issue in rhythm_issues
            if issue.get("code") in {
                "rhythm.em_dash_overuse",
                "rhythm.staccato_cluster",
                "rhythm.opener_monotone",
                "rhythm.abstract_tic",
            }
        ]

        parts = [
            "## Scene Card (for character/voice context)",
            f"```json\n{json.dumps(scene_card, indent=2)}\n```",
            "",
            "## Detected Rhythm Issues",
            json.dumps(fixable, indent=2),
            "",
            "## Current Prose",
            prose,
            "",
            "## Task",
            (
                "Produce the SMALLEST safe set of literal substring edits to fix "
                "the listed rhythm issues. Each edit is an exact-span replacement: "
                "the `pattern` MUST be an exact substring copied from the current "
                "prose (no regex, no fuzzy match), and the `replacement` is what "
                "it becomes."
            ),
            "",
            "Rules:",
            "- Use exact literal substrings copied from the current prose. No regex.",
            "- The `pattern` must appear EXACTLY ONCE in the prose. If a phrase "
            "  appears multiple times, choose the longer surrounding context so "
            "  the pattern becomes unique.",
            "- For `rhythm.em_dash_overuse`: replace em-dash interruptions with "
            "  commas, periods, or restructured sentences. Aim to cut em-dash "
            "  density roughly in half per edit.",
            "- For `rhythm.staccato_cluster`: merge two or three consecutive "
            "  short sentences into one longer sentence using conjunctions, "
            "  semicolons, or subordinate clauses. The merged version must "
            "  preserve every action and image from the original.",
            "- For `rhythm.opener_monotone`: rewrite sentence openings so the "
            "  cluster does not all start with He/She/They/It/The/There. Use "
            "  prepositional phrases ('Behind him, ...'), subordinate clauses "
            "  ('If he'd waited, ...'), or short fragments. Do not add new "
            "  characters or actions.",
            "- For `rhythm.abstract_tic`: replace 'the particular X of Y' "
            "  constructions, 'something adjacent to Z', 'not quite W', and "
            "  similar tic patterns with concrete nouns, verbs, or images. "
            "  Preserve the meaning; lose the abstraction.",
            "- Do NOT add new named characters.",
            "- Do NOT add new lore, canon facts, or exposition.",
            "- Do NOT introduce a new beat or alter scene order.",
            "- Do NOT rewrite a full paragraph when a sentence-level edit is enough.",
            "- Replacement text should match the character voice of the surrounding "
            "  prose; if the scene uses a tight third-person POV, keep the edit "
            "  in that voice.",
            "- If an issue cannot be fixed safely with an exact-span edit, omit it.",
            "",
            "Return ONLY this JSON object:",
            "```json",
            "{",
            '  "summary": "one-sentence assessment of what you changed",',
            '  "edits": [',
            "    {",
            '      "fix_for_issue_code": "rhythm.em_dash_overuse",',
            '      "pattern": "EXACT literal substring from the prose",',
            '      "replacement": "the literal text it becomes",',
            '      "reason": "why this resolves the rhythm issue"',
            "    }",
            "  ]",
            "}",
            "```",
            'If no safe edits exist, return {"summary": "...", "edits": []}.',
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
            return {"summary": "", "edits": []}
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
                        return {"summary": "", "edits": []}
        return {"summary": "", "edits": []}

    @staticmethod
    def _normalize_result(result: dict) -> dict:
        """Validate the shape; drop malformed edits silently."""
        if not isinstance(result, dict):
            return {"summary": "", "edits": []}
        raw_edits = result.get("edits", [])
        if not isinstance(raw_edits, list):
            raw_edits = []
        normalized: list[dict] = []
        valid_codes = {
            "rhythm.em_dash_overuse",
            "rhythm.staccato_cluster",
            "rhythm.opener_monotone",
            "rhythm.abstract_tic",
        }
        for edit in raw_edits:
            if not isinstance(edit, dict):
                continue
            code = str(edit.get("fix_for_issue_code", "")).strip()
            pattern = edit.get("pattern")
            replacement = edit.get("replacement")
            if code not in valid_codes:
                continue
            if not isinstance(pattern, str) or not pattern:
                continue
            if replacement is None:
                replacement = ""
            if not isinstance(replacement, str):
                continue
            if pattern == replacement:
                continue  # no-op edit
            normalized.append(
                {
                    "fix_for_issue_code": code,
                    "pattern": pattern,
                    "replacement": replacement,
                    "reason": str(edit.get("reason", "")).strip(),
                }
            )
        return {
            "summary": str(result.get("summary", "")).strip(),
            "edits": normalized,
        }


# ---------------------------------------------------------------------------
# Deterministic apply path (orchestrator side, no LLM)
# ---------------------------------------------------------------------------


def _audit_row(edit: dict, action: str, rejection_reason: str | None) -> dict:
    """Build an audit row that preserves the rejection reason even when the
    edit dict carries its own `reason` field (the LLM's per-edit rationale).
    """
    row: dict = {"action": action}
    if rejection_reason is not None:
        row["reason"] = rejection_reason
    if edit.get("fix_for_issue_code"):
        row["code"] = edit["fix_for_issue_code"]
    if edit.get("reason"):
        row["edit_reason"] = edit["reason"]
    return row


def apply_rhythm_edits(
    prose: str,
    edits: list[dict],
    *,
    max_edits: int = 8,
    max_total_changed_chars: int = 1500,
    max_changed_ratio: float = 0.15,
) -> tuple[str, list[dict]]:
    """Apply a list of rhythm edits with deterministic safety caps.

    Mirrors ``src/agents/micro_repair._apply_micro_repairs`` (orchestrator-side
    helper). Caps are enforced regardless of what the LLM returned:

    - ``max_edits`` — total applied edits per call.
    - ``max_total_changed_chars`` — total character delta across applied edits.
    - ``max_changed_ratio`` — applied delta as fraction of original prose.

    Per-edit rejections (recorded in ``rejected`` for ledger visibility):

    - ``empty_pattern``
    - ``non_string_replacement``
    - ``no_op_replacement`` (pattern == replacement; should be filtered upstream
      but checked again defensively)
    - ``pattern_not_in_prose``
    - ``ambiguous_pattern_occurrences`` — pattern appears > 1 time
    - ``duplicate_pattern`` — same pattern proposed twice
    - ``changed_char_budget_exceeded``
    - ``changed_ratio_exceeded``
    - ``max_edits_exceeded``

    Returns ``(patched_prose, audit_log)`` where ``audit_log`` is a list of
    ``{action: "applied"|"rejected", reason: str, ...edit-fields}`` entries.
    """
    audit: list[dict] = []
    if not isinstance(prose, str) or not prose:
        return prose, audit
    if not isinstance(edits, list):
        return prose, audit

    original_len = len(prose)
    patched = prose
    applied_count = 0
    total_changed = 0
    seen_patterns: set[str] = set()

    for edit in edits:
        if not isinstance(edit, dict):
            continue
        pattern = edit.get("pattern")
        replacement = edit.get("replacement", "")
        code = edit.get("fix_for_issue_code", "")

        if not isinstance(pattern, str) or not pattern:
            audit.append(_audit_row(edit, "rejected", "empty_pattern"))
            continue
        if not isinstance(replacement, str):
            audit.append(_audit_row(edit, "rejected", "non_string_replacement"))
            continue
        if pattern == replacement:
            audit.append(_audit_row(edit, "rejected", "no_op_replacement"))
            continue
        if pattern in seen_patterns:
            audit.append(_audit_row(edit, "rejected", "duplicate_pattern"))
            continue

        occurrences = patched.count(pattern)
        if occurrences == 0:
            audit.append(_audit_row(edit, "rejected", "pattern_not_in_prose"))
            continue
        if occurrences > 1:
            row = _audit_row(edit, "rejected", "ambiguous_pattern_occurrences")
            row["occurrences"] = occurrences
            audit.append(row)
            continue

        if applied_count >= max_edits:
            audit.append(_audit_row(edit, "rejected", "max_edits_exceeded"))
            continue

        delta = abs(len(replacement) - len(pattern))
        if total_changed + delta > max_total_changed_chars:
            row = _audit_row(edit, "rejected", "changed_char_budget_exceeded")
            row["delta"] = delta
            row["running_total"] = total_changed
            audit.append(row)
            continue
        if original_len > 0 and (total_changed + delta) / original_len > max_changed_ratio:
            audit.append(_audit_row(edit, "rejected", "changed_ratio_exceeded"))
            continue

        # Apply
        patched = patched.replace(pattern, replacement, 1)
        seen_patterns.add(pattern)
        applied_count += 1
        total_changed += delta
        audit.append({
            "action": "applied",
            "code": code,
            "pattern_len": len(pattern),
            "replacement_len": len(replacement),
            "delta": delta,
        })

    return patched, audit
