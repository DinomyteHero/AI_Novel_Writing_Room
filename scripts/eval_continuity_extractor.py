#!/usr/bin/env python3
"""Slice 4 continuity-extractor eval harness (spec \u00a78.4).

Runs ``ContinuityExtractor`` against the labeled corpus at
``tests/data/continuity_eval_set.json`` and reports precision / recall /
false-positive rate per spec \u00a78.4.3.

Two run modes:

- Default: uses the configured ModelRouter (live LLM calls; spends credits).
  Requires ``OPENROUTER_API_KEY`` or equivalent per ``config/settings.yaml``.
- ``--predictions <path>``: reads a JSON file where predictions have already
  been produced (by a prior offline run or a fixture). Useful for CI + tests
  where live calls are not acceptable.

The predictions file shape mirrors the eval set so it can be diffed
side-by-side:

    {"scenes": [{"scene_id": "...", "predicted_events": [...]}]}

Each predicted event must carry ``event_type``, ``subject``, ``details``,
``confidence``. Unknown types or missing fields are counted as false
positives above the confidence threshold, zero otherwise.

Usage:
    py -3 scripts/eval_continuity_extractor.py \\
        --eval-set tests/data/continuity_eval_set.json \\
        --predictions fixtures/extractor_predictions.json \\
        --min-confidence 0.85 \\
        --out output/eval/continuity_extractor/2026-04-21.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).parent.parent))


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _event_matches_ground_truth(pred: Mapping[str, Any], truth: Mapping[str, Any]) -> bool:
    if pred.get("event_type") != truth.get("event_type"):
        return False
    if pred.get("subject") != truth.get("subject"):
        return False
    p_details = pred.get("details") or {}
    t_details = truth.get("details") or {}
    # Compatible details: every ground-truth field matches the predicted
    # value. Predictions may carry extra allowed fields (e.g.
    # possession.counterparty) without disqualifying the match.
    for key, value in t_details.items():
        if p_details.get(key) != value:
            return False
    return True


def _match(predictions: list[dict], truth: list[dict]) -> tuple[int, int, int]:
    """Return (true_positives, false_positives, false_negatives)."""
    used_truth: set[int] = set()
    tp = 0
    for pred in predictions:
        matched = False
        for i, t in enumerate(truth):
            if i in used_truth:
                continue
            if _event_matches_ground_truth(pred, t):
                used_truth.add(i)
                tp += 1
                matched = True
                break
        if not matched:
            continue
    fp = len(predictions) - tp
    fn = len(truth) - len(used_truth)
    return tp, fp, fn


def _load_predictions(path: Path) -> dict[str, list[dict]]:
    data = _load_json(path)
    by_scene: dict[str, list[dict]] = {}
    for row in data.get("scenes", []):
        by_scene[row.get("scene_id", "")] = list(row.get("predicted_events") or [])
    return by_scene


async def _run_live_predictions(
    eval_set: Mapping[str, Any],
) -> dict[str, list[dict]]:
    """Drive the real extractor against every labeled scene. Live LLM calls."""
    from src.agents.continuity_extractor import ContinuityExtractor  # noqa: PLC0415
    from src.model_router import ModelRouter  # noqa: PLC0415

    router = ModelRouter()
    extractor = ContinuityExtractor(router)
    by_scene: dict[str, list[dict]] = {}
    for scene in eval_set.get("scenes", []):
        scene_id = scene.get("scene_id", "")
        prose = scene.get("prose_inline") or _load_prose(scene)
        scene_card = scene.get("scene_card") or {}
        events = await extractor.extract(
            prose=prose or "",
            scene_card=scene_card,
            concept_seed=scene.get("concept_seed") or {},
        )
        by_scene[scene_id] = events
    return by_scene


def _load_prose(scene: Mapping[str, Any]) -> str:
    path_str = scene.get("prose_path")
    if not path_str:
        return ""
    p = Path(path_str)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8")


def _evaluate(
    eval_set: Mapping[str, Any],
    predictions_by_scene: Mapping[str, list[dict]],
    min_confidence: float,
) -> dict:
    per_scene: list[dict] = []
    total_tp = total_fp = total_fn = 0

    for scene in eval_set.get("scenes", []):
        scene_id = scene.get("scene_id", "")
        truth = list(scene.get("ground_truth_events") or [])
        raw_preds = predictions_by_scene.get(scene_id, []) or []
        trusted = [p for p in raw_preds if float(p.get("confidence", 0.0)) >= min_confidence]
        tp, fp, fn = _match(trusted, truth)
        per_scene.append({
            "scene_id": scene_id,
            "truth_count": len(truth),
            "prediction_count": len(raw_preds),
            "trusted_count": len(trusted),
            "tp": tp, "fp": fp, "fn": fn,
        })
        total_tp += tp
        total_fp += fp
        total_fn += fn

    emitted = total_tp + total_fp
    precision = (total_tp / emitted) if emitted else 1.0
    total_truth = total_tp + total_fn
    recall = (total_tp / total_truth) if total_truth else 1.0
    fp_rate = (total_fp / emitted) if emitted else 0.0

    return {
        "eval_set_version": eval_set.get("version", "unknown"),
        "min_confidence": min_confidence,
        "n_scenes": len(eval_set.get("scenes", [])),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "false_positive_rate": round(fp_rate, 4),
        "false_positive_count": total_fp,
        "per_scene": per_scene,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--eval-set", default="tests/data/continuity_eval_set.json",
        help="Path to labeled eval set JSON.",
    )
    parser.add_argument(
        "--predictions", default=None,
        help="Optional path to a pre-computed predictions JSON. When omitted "
             "the extractor is driven against each scene live.",
    )
    parser.add_argument(
        "--min-confidence", type=float, default=0.85,
        help="Threshold at which an event counts as trusted.",
    )
    parser.add_argument(
        "--out", default=None,
        help="Optional path to write the JSON report. When omitted the "
             "report is written to stdout.",
    )
    args = parser.parse_args()

    eval_set = _load_json(Path(args.eval_set))
    if args.predictions:
        preds = _load_predictions(Path(args.predictions))
    else:
        preds = asyncio.run(_run_live_predictions(eval_set))

    report = _evaluate(eval_set, preds, min_confidence=float(args.min_confidence))
    output = json.dumps(report, indent=2)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Wrote report to {out_path}")
    else:
        print(output)

    # Gate (spec \u00a78.4.3): precision >= 0.90 AND fp_rate <= 0.05 AND recall >= 0.60.
    # We return 0 regardless so CI can inspect; callers treat non-zero as a
    # hard fail only on explicit gating runs.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
