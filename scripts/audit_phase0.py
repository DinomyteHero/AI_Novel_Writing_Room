#!/usr/bin/env python3
"""Phase 0 diagnostic audit (Slice 1).

Runs the six-criteria gate defined in
``docs/architecture/architecture_upgrade_spec.md`` §5.1. The purpose is to
prove that declared drafter inputs actually reach the drafter prompt; until
this passes for Ruusan and Betrayal, Slice 2 (chapter packet) implementation
is blocked.

Current scope: v0.1 scaffold. The script resolves paths, computes git state,
writes the schema-conformant ``phase0_audit.json`` envelope, and emits a
human-readable stub report under ``docs/audits/``. Individual criterion
evaluations read already-captured artifacts from a target run directory
(``--run-dir``) if available; otherwise they mark the criterion failed with
an explanatory evidence string. Wiring criteria to a *live* pipeline run
(with per-stage prompt dumping into ``phase0_debug/``) is deferred to a
follow-up patch — this keeps Slice 1 shippable while providing the
downstream gate surface immediately.

Usage:
    py -3 scripts/audit_phase0.py \
        --concept-seed data/franchises/<franchise>/books/<book>/concept_seed.json \
        --chapter 1 \
        --run-label phase0_$(date +%F)

Optional:
    --run-dir <path>  # point at an existing run directory to inspect artifacts
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


CRITERIA_ORDER = (
    "voice_rules_reach_drafter",
    "scene_contract_reaches_drafter",
    "constraints_survive_assembly",
    "cross_scene_feedback_real",
    "register_policy_single_source",
    "audit_report_exists",
)


def _git_info() -> tuple[str, bool]:
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
    except Exception:  # noqa: BLE001
        sha = "unknown"
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"],
            stderr=subprocess.DEVNULL, text=True,
        )
        dirty = bool(out.strip())
    except Exception:  # noqa: BLE001
        dirty = False
    return sha, dirty


def _evaluate_criterion(
    name: str, *, run_dir: Path | None, report_path: Path,
) -> dict:
    """Evaluate one criterion. Evidence is deterministic: either a path +
    line range into an artifact, or a freeform explanation string.

    v0.1 scaffold: every criterion defaults to ``pass: false`` with an
    evidence message describing what to wire. ``audit_report_exists``
    uses the real filesystem check because the report is produced by
    this same script and is the gate's self-check.
    """
    if name == "audit_report_exists":
        exists = report_path.exists() and report_path.stat().st_size > 0
        return {
            "pass": exists,
            "evidence": str(report_path),
            "notes": "Self-check: this script emits the report; pass once it lands on disk.",
        }

    scaffold_msg = (
        "Scaffold stub: criterion not yet wired to prompt snapshots. "
        "Flip to pass: true by (1) running the pipeline with "
        "runtime.phase0_audit.enabled=true to capture phase0_debug/ prompts, "
        "(2) grep-checking the expected string, (3) updating this script's "
        "evaluation stub. See architecture_upgrade_spec.md §5.1.3."
    )
    evidence = scaffold_msg
    if run_dir is not None:
        debug_dir = run_dir / "phase0_debug"
        if debug_dir.exists():
            evidence = (
                f"Run dir has phase0_debug/ at {debug_dir}; evaluation stub "
                "still pending wire-in for this criterion."
            )
    return {"pass": False, "evidence": evidence}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--concept-seed",
        required=True,
        help="Path to the target book's concept_seed.json.",
    )
    parser.add_argument(
        "--chapter",
        type=int,
        default=1,
        help="Chapter number to audit (default: 1).",
    )
    parser.add_argument(
        "--run-label",
        default=None,
        help="Run label (default: phase0_<date>).",
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Optional existing run directory to inspect; defaults to a new "
             "run folder under output/<franchise>/<book>/runs/<run_label>/.",
    )
    args = parser.parse_args()

    seed_path = Path(args.concept_seed).resolve()
    if not seed_path.exists():
        print(f"ERROR: concept seed not found: {seed_path}", file=sys.stderr)
        return 2

    with seed_path.open(encoding="utf-8") as fh:
        seed = json.load(fh)

    from src.project_paths import ProjectPaths  # noqa: PLC0415

    run_label = args.run_label or f"phase0_{_dt.date.today().isoformat()}"
    paths = ProjectPaths.from_concept_seed_path(str(seed_path), run_id=run_label)

    franchise = paths.franchise_slug or "unknown-franchise"
    book = paths.project_slug

    run_dir = Path(args.run_dir).resolve() if args.run_dir else (
        Path("output") / franchise / book / "runs" / run_label
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    audits_dir = Path("docs/audits")
    audits_dir.mkdir(parents=True, exist_ok=True)
    report_path = audits_dir / f"phase0_{_dt.date.today().isoformat()}_{book}.md"

    criteria: dict[str, dict] = {}
    run_dir_for_eval = run_dir if (run_dir / "phase0_debug").exists() else None
    for name in CRITERIA_ORDER:
        criteria[name] = _evaluate_criterion(
            name, run_dir=run_dir_for_eval, report_path=report_path,
        )

    overall_pass = all(c["pass"] for c in criteria.values())

    sha, dirty = _git_info()
    audit = {
        "run_id": run_label,
        "git_sha": sha,
        "dirty": dirty,
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "franchise": franchise,
        "book": book,
        "chapter_audited": args.chapter,
        "criteria": criteria,
        "overall_pass": overall_pass,
    }

    audit_path = run_dir / "phase0_audit.json"
    audit_path.write_text(
        json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8",
    )

    report_lines = [
        f"# Phase 0 audit — {book}",
        "",
        f"- Run: `{run_label}`",
        f"- Franchise: `{franchise}`",
        f"- Chapter: {args.chapter}",
        f"- Generated: {audit['generated_at']}",
        f"- Git: `{sha}`{' (dirty)' if dirty else ''}",
        f"- Overall pass: **{'YES' if overall_pass else 'NO'}**",
        "",
        "## Criteria",
        "",
    ]
    for name in CRITERIA_ORDER:
        c = criteria[name]
        report_lines.append(
            f"- `{name}` — {'PASS' if c['pass'] else 'FAIL'} — {c['evidence']}",
        )
    report_lines.append("")
    report_lines.append(
        "## Next steps" if not overall_pass else "## Status",
    )
    report_lines.append("")
    if overall_pass:
        report_lines.append(
            "All six criteria pass. Slice 2 (chapter packet) is unblocked "
            "for this book."
        )
    else:
        report_lines.append(
            "Slice 2 is blocked until every criterion passes. Typical fixes: "
            "prompt truncation in `context_assembler.py`, voice rules not "
            "wired into `ProseStylist.run()` ingestion, contradictory "
            "register policy across voice.json / prose_stylist / voice_checker "
            "prompts. See spec §5.1.5."
        )
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    # Re-evaluate audit_report_exists now that the file lives on disk, then
    # recompute overall_pass so the two artifacts agree. (The report exists
    # check is the one criterion this script can truthfully assert.)
    criteria["audit_report_exists"] = _evaluate_criterion(
        "audit_report_exists", run_dir=run_dir_for_eval, report_path=report_path,
    )
    audit["criteria"] = criteria
    audit["overall_pass"] = all(c["pass"] for c in criteria.values())
    audit_path.write_text(
        json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8",
    )

    print(f"Wrote audit JSON -> {audit_path}")
    print(f"Wrote audit report -> {report_path}")
    print(f"Overall pass: {audit['overall_pass']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
