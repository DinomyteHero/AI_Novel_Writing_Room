"""Slice 4 continuity-extractor eval harness tests.

Exercises the predictions-file path of ``scripts/eval_continuity_extractor.py``
so no live LLM calls are made. Validates the precision / recall / fp-rate
math against deterministic inputs and confirms the report schema.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_SET = REPO_ROOT / "tests" / "data" / "continuity_eval_set.json"
SCRIPT = REPO_ROOT / "scripts" / "eval_continuity_extractor.py"


def _run(args: list[str]) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT)] + args
    return subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)


def _write_predictions(path: Path, scenes: list[dict]) -> None:
    path.write_text(json.dumps({"scenes": scenes}), encoding="utf-8")


def _load_eval_set() -> dict:
    with EVAL_SET.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_perfect_predictions_yield_precision_1_recall_1(tmp_path: Path):
    """Copying ground-truth events into predictions at confidence 1.0 gives
    precision=1, recall=1, fp_rate=0 \u2014 the eval harness's upper bound."""
    eval_set = _load_eval_set()
    scenes = []
    for scene in eval_set["scenes"]:
        predicted = [
            {**ev, "confidence": 1.0} for ev in scene["ground_truth_events"]
        ]
        scenes.append({"scene_id": scene["scene_id"], "predicted_events": predicted})
    preds_path = tmp_path / "preds.json"
    _write_predictions(preds_path, scenes)

    result = _run([
        "--eval-set", str(EVAL_SET),
        "--predictions", str(preds_path),
        "--min-confidence", "0.85",
    ])
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["precision"] == 1.0
    assert report["recall"] == 1.0
    assert report["false_positive_count"] == 0


def test_empty_predictions_yield_recall_zero(tmp_path: Path):
    eval_set = _load_eval_set()
    scenes = [
        {"scene_id": s["scene_id"], "predicted_events": []}
        for s in eval_set["scenes"]
    ]
    preds_path = tmp_path / "preds.json"
    _write_predictions(preds_path, scenes)

    result = _run([
        "--eval-set", str(EVAL_SET),
        "--predictions", str(preds_path),
    ])
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    # Zero emitted \u2014 precision vacuously 1.0. Recall 0 because truth > 0.
    assert report["precision"] == 1.0
    assert report["recall"] == 0.0
    assert report["false_positive_count"] == 0


def test_sub_threshold_predictions_do_not_count(tmp_path: Path):
    eval_set = _load_eval_set()
    scenes = []
    for scene in eval_set["scenes"]:
        predicted = [
            {**ev, "confidence": 0.5} for ev in scene["ground_truth_events"]
        ]
        scenes.append({"scene_id": scene["scene_id"], "predicted_events": predicted})
    preds_path = tmp_path / "preds.json"
    _write_predictions(preds_path, scenes)

    result = _run([
        "--eval-set", str(EVAL_SET),
        "--predictions", str(preds_path),
        "--min-confidence", "0.85",
    ])
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["recall"] == 0.0
    assert report["false_positive_count"] == 0


def test_out_file_writes_report(tmp_path: Path):
    eval_set = _load_eval_set()
    scenes = [
        {"scene_id": s["scene_id"], "predicted_events": []}
        for s in eval_set["scenes"]
    ]
    preds_path = tmp_path / "preds.json"
    _write_predictions(preds_path, scenes)
    out_path = tmp_path / "report.json"

    result = _run([
        "--eval-set", str(EVAL_SET),
        "--predictions", str(preds_path),
        "--out", str(out_path),
    ])
    assert result.returncode == 0, result.stderr
    assert out_path.exists()
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert "precision" in report
    assert "recall" in report
    assert "per_scene" in report
