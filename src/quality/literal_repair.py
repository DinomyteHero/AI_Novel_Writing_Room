"""Deterministic application of exact literal prose repairs."""

from __future__ import annotations

from typing import Any


def apply_literal_repairs(
    prose: str,
    repairs: list[dict[str, Any]],
    *,
    max_repairs: int = 2,
    max_total_changed_chars: int = 500,
    max_changed_ratio: float = 0.12,
) -> dict[str, Any]:
    """Apply safe exact-span replacements returned by MicroRepair.

    Repairs are intentionally conservative: each pattern must occur exactly
    once in the current prose, and the cumulative replacement span must fit
    both the absolute and proportional change budgets.
    """

    patched = prose
    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    max_changed_by_ratio = int(max(1, len(prose)) * max_changed_ratio)
    change_budget = min(max_total_changed_chars, max_changed_by_ratio)
    changed_chars = 0

    for repair in repairs:
        issue_type = str(repair.get("issue_type", "")).strip() or "unknown"
        pattern = repair.get("pattern")
        replacement = repair.get("replacement")
        reason = str(repair.get("reason", "")).strip()

        if len(applied) >= max_repairs:
            skipped.append({
                "issue_type": issue_type,
                "pattern": pattern if isinstance(pattern, str) else "",
                "reason": "max repair count reached",
            })
            continue
        if not isinstance(pattern, str) or not pattern:
            skipped.append({
                "issue_type": issue_type,
                "pattern": "",
                "reason": "missing literal pattern",
            })
            continue
        if replacement is None:
            replacement = ""
        if not isinstance(replacement, str):
            skipped.append({
                "issue_type": issue_type,
                "pattern": pattern,
                "reason": "replacement is not a string",
            })
            continue

        occurrence_count = patched.count(pattern)
        if occurrence_count != 1:
            skipped.append({
                "issue_type": issue_type,
                "pattern": pattern,
                "reason": f"pattern occurs {occurrence_count} times",
            })
            continue

        span_size = max(len(pattern), len(replacement))
        if changed_chars + span_size > change_budget:
            skipped.append({
                "issue_type": issue_type,
                "pattern": pattern,
                "reason": "change budget exceeded",
            })
            continue

        patched = patched.replace(pattern, replacement, 1)
        changed_chars += span_size
        applied.append({
            "issue_type": issue_type,
            "pattern": pattern,
            "replacement": replacement,
            "reason": reason,
            "changed_chars": span_size,
        })

    return {
        "prose": patched,
        "changed": patched != prose,
        "applied": applied,
        "skipped": skipped,
        "changed_char_count": changed_chars,
        "change_budget": change_budget,
    }
