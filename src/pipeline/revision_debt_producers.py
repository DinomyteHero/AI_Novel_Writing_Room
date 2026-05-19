"""Write-matrix wrappers for the Slice 2 revision-debt store.

Every advisory-producing stage calls one of these functions rather than
``RevisionDebtStore.add`` directly. The matrix is enumerated in spec \u00a76.2.1:

    Producer              | Condition                             | Category                        | Default severity
    --------------------- | ------------------------------------- | ------------------------------- | ----------------
    CanonExpert           | advisory_notes[*] emitted             | canon                           | from advisory
    CanonExpert           | local_fixes rejected by whitelist     | canon_fix_rejected              | low
    CanonExpert (late)    | polish drift detected                 | editorial.canon_polish_drift    | medium
    GateCritic            | failure_codes with non_blocking sev.  | editorial.gate_advisory         | from failure
    FinalGate             | Any output (always advisory)          | editorial.final_gate_advisory   | from failure
    QualityMetrics        | Metric exceeds threshold              | metric                          | low<1-band, medium beyond
    PresenceChecker       | Confidence in [0.5, blocker_thresh)   | presence_near_miss              | low
    StateFirewall         | Scene isolated                        | blocker_record                  | high (pinned)
    word_count_telemetry  | Drift > \u00b115%                          | wordcount_drift                 | low <30%, medium >30%
    compression_guard     | Polish shrinks below 60% of pre       | compression_advisory            | medium
    SceneReviewer         | Any categorical finding               | editorial.scene_reviewer        | from finding

All wrappers accept ``store: RevisionDebtStore | None``. When ``None`` (or
``runtime.revision_debt.enabled: false``), the wrapper is a noop and returns
``None`` \u2014 the ledger emit is the caller's responsibility (existing behavior).

When ``store`` is present, the wrapper validates, constructs the entry, calls
``store.add``, optionally emits ``revision_debt_added`` via the provided
ledger, and returns the ``debt_id``.

See ``docs/architecture/architecture_upgrade_spec.md`` \u00a76.2.4.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

from src.pipeline.revision_debt import RevisionDebtStore

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- utils


def _severity_from_failure(failure: Mapping[str, Any]) -> str:
    """Map a failure code dict to a revision_debt severity.

    Failure codes carry ``severity`` in ``{blocker, non_blocking, advisory}``.
    For revision-debt purposes, blocker \u2192 high, non_blocking \u2192 medium,
    advisory (or missing) \u2192 low.
    """
    sev = (failure or {}).get("severity", "advisory")
    if sev == "blocker":
        return "high"
    if sev == "non_blocking":
        return "medium"
    return "low"


def _emit_added(ledger, debt_id: str, *, category: str, severity: str, scope: Mapping[str, Any]) -> None:
    """Emit ``revision_debt_added`` with level=info when a ledger is provided."""
    if ledger is None or debt_id is None:
        return
    try:
        ledger.emit_info(
            "revision_debt_added",
            chapter_number=scope.get("chapter_number"),
            scene_number=scope.get("scene_number"),
            payload={
                "debt_id": debt_id,
                "category": category,
                "severity": severity,
                "scope": dict(scope),
            },
        )
    except Exception:  # noqa: BLE001 -- ledger emit must never block the pipeline
        logger.exception("Failed to emit revision_debt_added for %s", debt_id)


def _write(
    store: Optional[RevisionDebtStore],
    *,
    ledger,
    producer: str,
    scope: Mapping[str, Any],
    category: str,
    severity: str,
    summary: str,
    details: Mapping[str, Any] | None = None,
    fix_scope: str | None = None,
) -> str | None:
    """Shared write path. Returns ``debt_id`` or ``None`` when ``store`` is off."""
    if store is None:
        return None
    debt_id = store.add({
        "producer": producer,
        "scope": dict(scope),
        "category": category,
        "severity": severity,
        "summary": summary,
        "details": dict(details or {}),
        "fix_scope": fix_scope,
        "status": "open",
    })
    _emit_added(ledger, debt_id, category=category, severity=severity, scope=scope)
    return debt_id


def emit_status_update(
    store: Optional[RevisionDebtStore],
    *,
    ledger,
    debt_id: str,
    status: str,
    resolution_notes: str | None = None,
) -> dict | None:
    """Transition a debt row and emit ``revision_debt_updated``."""
    if store is None:
        return None
    result = store.update_status(debt_id, status=status, resolution_notes=resolution_notes)
    if ledger is not None:
        try:
            ledger.emit_info(
                "revision_debt_updated",
                payload={"debt_id": debt_id, **result},
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to emit revision_debt_updated for %s", debt_id)
    return result


# ----------------------------------------------------- producer-specific rows


def emit_canon_advisory(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    advisory: Mapping[str, Any],
) -> str | None:
    """CanonExpert advisory_notes[*]: category=canon."""
    severity = (advisory.get("severity") or "low").lower()
    if severity not in {"low", "medium", "high"}:
        severity = "medium" if severity in {"moderate"} else "low"
    return _write(
        store,
        ledger=ledger,
        producer="canon_expert",
        scope=scope,
        category="canon",
        severity=severity,
        summary=str(advisory.get("description") or advisory.get("code") or "canon advisory"),
        details=dict(advisory),
        fix_scope=advisory.get("fix_scope"),
    )


def emit_canon_fix_rejected(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    fix: Mapping[str, Any],
    reason: str,
) -> str | None:
    """CanonExpert proposed a local_fix outside the Slice 11.1 whitelist."""
    return _write(
        store,
        ledger=ledger,
        producer="canon_expert",
        scope=scope,
        category="canon_fix_rejected",
        severity="low",
        summary=f"Rejected local_fix ({fix.get('category', 'unknown')}): {reason}",
        details={"fix": dict(fix), "reason": reason},
        fix_scope="local",
    )


def emit_canon_polish_drift(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    drift: Mapping[str, Any],
) -> str | None:
    """Second (late) CanonExpert pass detected drift reintroduced by polish."""
    return _write(
        store,
        ledger=ledger,
        producer="canon_expert",
        scope=scope,
        category="editorial.canon_polish_drift",
        severity="medium",
        summary=str(drift.get("description") or "canon drift reintroduced by polish"),
        details=dict(drift),
        fix_scope="scene",
    )


def emit_gate_critic_advisory(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    failure: Mapping[str, Any],
) -> str | None:
    """GateCritic non_blocking failure code."""
    return _write(
        store,
        ledger=ledger,
        producer="gate_critic",
        scope=scope,
        category="editorial.gate_advisory",
        severity=_severity_from_failure(failure),
        summary=str(failure.get("description") or failure.get("code") or "gate advisory"),
        details=dict(failure),
        fix_scope="scene",
    )


def emit_final_gate_advisory(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    failure: Mapping[str, Any],
) -> str | None:
    """FinalGate output \u2014 always advisory post-Stage 1."""
    return _write(
        store,
        ledger=ledger,
        producer="final_gate",
        scope=scope,
        category="editorial.final_gate_advisory",
        severity=_severity_from_failure(failure),
        summary=str(failure.get("description") or failure.get("code") or "final gate advisory"),
        details=dict(failure),
        fix_scope="scene",
    )


def emit_metric_advisory(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    metric_name: str,
    value: float,
    threshold: float,
    bands_over: int = 0,
    details: Mapping[str, Any] | None = None,
) -> str | None:
    """QualityMetrics: metric exceeds threshold. bands_over counts 1-threshold-band jumps."""
    severity = "medium" if bands_over > 1 else "low"
    return _write(
        store,
        ledger=ledger,
        producer="quality_metrics",
        scope=scope,
        category="metric",
        severity=severity,
        summary=f"{metric_name} = {value} (threshold {threshold})",
        details={
            "metric_name": metric_name,
            "value": value,
            "threshold": threshold,
            "bands_over": bands_over,
            **dict(details or {}),
        },
        fix_scope="scene",
    )


def emit_presence_near_miss(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    confidence: float,
    details: Mapping[str, Any] | None = None,
) -> str | None:
    """PresenceChecker confidence in the near-miss band."""
    return _write(
        store,
        ledger=ledger,
        producer="presence_checker",
        scope=scope,
        category="presence_near_miss",
        severity="low",
        summary=f"Presence near-miss (confidence {confidence:.2f})",
        details={"confidence": confidence, **dict(details or {})},
        fix_scope="scene",
    )


def emit_blocker_record(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    blocker_categories: list[str],
    gap_id: str | None = None,
) -> str | None:
    """StateFirewall isolated a scene. Severity pinned to 'high'."""
    return _write(
        store,
        ledger=ledger,
        producer="state_firewall",
        scope=scope,
        category="blocker_record",
        severity="high",
        summary=f"Scene isolated: {', '.join(blocker_categories) or 'unknown categories'}",
        details={
            "blocker_categories": list(blocker_categories),
            "gap_id": gap_id,
        },
        fix_scope="scene",
    )


def emit_wordcount_drift(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    target: int,
    actual: int,
    pct_drift: float,
) -> str | None:
    """word_count_telemetry drift outside \u00b115%."""
    severity = "medium" if abs(pct_drift) > 30 else "low"
    return _write(
        store,
        ledger=ledger,
        producer="word_count_telemetry",
        scope=scope,
        category="wordcount_drift",
        severity=severity,
        summary=f"Word-count drift {pct_drift:+.1f}% (target {target}, actual {actual})",
        details={"target": target, "actual": actual, "pct_drift": pct_drift},
        fix_scope="scene",
    )


def emit_compression_advisory(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    pre_polish_words: int,
    post_polish_words: int,
    ratio: float,
) -> str | None:
    """compression_guard: polish shrank below 60% of pre-polish word count."""
    return _write(
        store,
        ledger=ledger,
        producer="compression_guard",
        scope=scope,
        category="compression_advisory",
        severity="medium",
        summary=f"Polish compressed to {ratio:.0%} of pre-polish "
                f"({pre_polish_words} \u2192 {post_polish_words} words)",
        details={
            "pre_polish_words": pre_polish_words,
            "post_polish_words": post_polish_words,
            "ratio": ratio,
        },
        fix_scope="scene",
    )


def emit_scene_reviewer_finding(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    finding: Mapping[str, Any],
) -> str | None:
    """SceneReviewer (future) categorical finding."""
    severity = (finding.get("severity") or "low").lower()
    if severity not in {"low", "medium", "high"}:
        severity = "low"
    return _write(
        store,
        ledger=ledger,
        producer="scene_reviewer",
        scope=scope,
        category="editorial.scene_reviewer",
        severity=severity,
        summary=str(finding.get("summary") or finding.get("description") or "scene reviewer finding"),
        details=dict(finding),
        fix_scope=finding.get("fix_scope") or "scene",
    )


def emit_scene_reviewer_other(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    note: str,
    details: Mapping[str, Any] | None = None,
) -> str | None:
    """SceneReviewer (future) free-text note that doesn't fit a category."""
    merged_details = {"note": "uncategorized", "text": note, **dict(details or {})}
    return _write(
        store,
        ledger=ledger,
        producer="scene_reviewer",
        scope=scope,
        category="editorial.other",
        severity="low",
        summary=note[:120],
        details=merged_details,
        fix_scope="scene",
    )


def emit_rhythm_advisory(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    issue: Mapping[str, Any],
    metrics: Mapping[str, Any] | None = None,
) -> str | None:
    """RhythmValidator advisory: one row per detected rhythm issue.

    ``issue`` is a serialised ``RhythmIssue`` (code, severity, message,
    metric_value, threshold). ``code`` is mapped to its closed-enum category
    name. Unknown codes route to ``editorial.other`` so the wrapper never
    rejects a future RhythmValidator code with a hard error.
    """
    code = issue.get("code") or ""
    severity = (issue.get("severity") or "low").lower()
    if severity not in {"low", "medium", "high"}:
        severity = "low"

    code_to_category = {
        "rhythm.em_dash_overuse": "prose.rhythm.em_dash_overuse",
        "rhythm.staccato_cluster": "prose.rhythm.staccato_cluster",
        "rhythm.opener_monotone": "prose.rhythm.opener_monotone",
        "rhythm.dialogue_starved": "prose.rhythm.dialogue_starved",
        "rhythm.abstract_tic": "prose.rhythm.abstract_tic",
    }
    category = code_to_category.get(code, "editorial.other")

    details: dict[str, Any] = {
        "code": code,
        "metric_value": issue.get("metric_value"),
        "threshold": issue.get("threshold"),
    }
    if metrics:
        details["metrics_snapshot"] = dict(metrics)
    return _write(
        store,
        ledger=ledger,
        producer="rhythm_validator",
        scope=scope,
        category=category,
        severity=severity,
        summary=str(issue.get("message") or code or "rhythm advisory"),
        details=details,
        fix_scope="scene",
    )


def emit_continuity_break(
    store: Optional[RevisionDebtStore],
    *,
    ledger=None,
    scope: Mapping[str, Any],
    break_kind: str,
    summary: str,
    details: Mapping[str, Any] | None = None,
) -> str | None:
    """Cross-chapter continuity validator finding.

    ``break_kind`` is one of ``character_state``, ``location``,
    ``object_location``. Unknown kinds route to ``editorial.other``.
    """
    kind_to_category = {
        "character_state": "prose.continuity.character_state_break",
        "location": "prose.continuity.location_break",
        "object_location": "prose.continuity.object_location_break",
    }
    category = kind_to_category.get(break_kind, "editorial.other")
    return _write(
        store,
        ledger=ledger,
        producer="continuity_validator",
        scope=scope,
        category=category,
        severity="medium",
        summary=summary[:200],
        details=dict(details or {}),
        fix_scope="chapter",
    )


__all__ = [
    "emit_canon_advisory",
    "emit_canon_fix_rejected",
    "emit_canon_polish_drift",
    "emit_gate_critic_advisory",
    "emit_final_gate_advisory",
    "emit_metric_advisory",
    "emit_presence_near_miss",
    "emit_blocker_record",
    "emit_wordcount_drift",
    "emit_compression_advisory",
    "emit_scene_reviewer_finding",
    "emit_scene_reviewer_other",
    "emit_rhythm_advisory",
    "emit_continuity_break",
    "emit_status_update",
]
