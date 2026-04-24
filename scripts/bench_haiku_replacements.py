#!/usr/bin/env python3
"""Benchmark candidate replacements for Claude Haiku 4.5 agent roles.

This is a targeted live-call harness. It swaps the model alias used by Haiku
roles in a temporary config and runs small, role-specific probes against the
real agent wrappers. The goal is not prose beauty; it is structured-output
reliability, conservative judgment, and safe narrow repairs.

The default role set intentionally excludes ``plot_architect`` because that
long scene-card planning prompt can expose provider-specific hangs. Run it as
an explicit second pass with ``--roles plot_architect``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.eval_continuity_extractor import _evaluate as evaluate_continuity  # noqa: E402
from src.agents.chapter_gate_critic import ChapterGateCritic  # noqa: E402
from src.agents.continuity_extractor import ContinuityExtractor  # noqa: E402
from src.agents.final_gate import FinalGate  # noqa: E402
from src.agents.gate_critic import GateCritic  # noqa: E402
from src.agents.micro_repair import MicroRepair  # noqa: E402
from src.agents.plot_architect import REQUIRED_BRIEF_FIELDS, PlotArchitect  # noqa: E402
from src.agents.presence_checker import PresenceChecker  # noqa: E402
from src.model_router import ModelRouter  # noqa: E402


DEFAULT_MODELS = [
    "haiku",
    "grok41fast",
    "qwen",
    "deepseek",
    "gpt54_mini",
]

DEFAULT_ROLES = [
    "gate_critic",
    "continuity_extractor",
    "presence_checker",
    "final_gate",
    "micro_repair",
    "chapter_gate_critic",
]

ROLE_TO_AGENT = {
    "continuity_extractor": ContinuityExtractor,
    "presence_checker": PresenceChecker,
    "final_gate": FinalGate,
    "gate_critic": GateCritic,
    "micro_repair": MicroRepair,
    "plot_architect": PlotArchitect,
    "chapter_gate_critic": ChapterGateCritic,
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BOOK_ROOT = PROJECT_ROOT / "data/franchises/star-wars-legends-eu/books/the-ruusan-atonement"
RUNS_ROOT = PROJECT_ROOT / "output/star-wars-legends-eu/the-ruusan-atonement/runs"
CALL_TIMEOUT_SECONDS = 120.0


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_env(path: Path = PROJECT_ROOT / ".env") -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _parse_csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return list(default)
    return [part.strip() for part in value.split(",") if part.strip()]


def _base_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _config_for_model(
    base: dict,
    model_alias: str,
    roles: list[str],
    *,
    http_timeout_seconds: float,
) -> dict:
    cfg = deepcopy(base)
    for role in roles:
        routing = cfg.setdefault("agent_routing", {}).setdefault(role, {})
        routing["backend"] = "cloud"
        routing["model"] = model_alias
    cfg.setdefault("models", {}).setdefault("cloud", {})["timeout_seconds"] = http_timeout_seconds
    cfg.setdefault("pipeline", {})["max_http_retries"] = 0
    return cfg


def _write_temp_config(tmp_dir: Path, model_alias: str, cfg: dict) -> Path:
    path = tmp_dir / f"settings.haiku-bench.{model_alias}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return path


async def _close_router(router: ModelRouter) -> None:
    for attr in ("_local_client", "_cloud_client"):
        client = getattr(router, attr, None)
        if client is not None:
            await client.aclose()


async def _timed_call(coro) -> tuple[Any, float, str | None]:
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=CALL_TIMEOUT_SECONDS)
        return result, time.perf_counter() - start, None
    except TimeoutError:
        return None, time.perf_counter() - start, f"TimeoutError: exceeded {CALL_TIMEOUT_SECONDS:.1f}s"
    except Exception as exc:  # noqa: BLE001
        return None, time.perf_counter() - start, f"{type(exc).__name__}: {exc}"


def _agent(router: ModelRouter, role: str):
    return ROLE_TO_AGENT[role](router)


async def bench_continuity_extractor(router: ModelRouter) -> dict:
    eval_set = _load_json(PROJECT_ROOT / "tests/data/continuity_eval_set.json")
    extractor = _agent(router, "continuity_extractor")
    predictions_by_scene: dict[str, list[dict]] = {}
    latencies: list[float] = []
    errors: list[str] = []

    for scene in eval_set.get("scenes", []):
        result, latency, error = await _timed_call(
            extractor.extract(
                prose=scene.get("prose_inline") or "",
                scene_card=scene.get("scene_card") or {},
                concept_seed=scene.get("concept_seed") or {},
            )
        )
        latencies.append(latency)
        if error:
            errors.append(f"{scene.get('scene_id')}: {error}")
            predictions_by_scene[scene.get("scene_id", "")] = []
        else:
            predictions_by_scene[scene.get("scene_id", "")] = result or []

    report = evaluate_continuity(eval_set, predictions_by_scene, min_confidence=0.85)
    precision = float(report.get("precision", 0.0))
    recall = float(report.get("recall", 0.0))
    fp_rate = float(report.get("false_positive_rate", 1.0))
    score = round((0.45 * precision) + (0.45 * recall) + (0.10 * (1.0 - fp_rate)), 4)
    return {
        "score": score,
        "latency_seconds": round(sum(latencies), 3),
        "calls": len(latencies),
        "errors": errors,
        "details": report | {"predictions_by_scene": predictions_by_scene},
    }


PRESENCE_CASES = [
    {
        "id": "clean_reference_not_present",
        "scene_card": {"characters_present": ["Ben Skywalker"], "pov_character": "Ben Skywalker"},
        "prose": (
            "Ben studied the datapad in the empty office. Luke's name appeared "
            "in the header, but no one else spoke or moved in the room."
        ),
        "expected": [],
    },
    {
        "id": "absent_character_acts",
        "scene_card": {"characters_present": ["Ben Skywalker"], "pov_character": "Ben Skywalker"},
        "prose": (
            "Ben studied the datapad in the office. Luke Skywalker crossed the "
            "room, set a second file beside him, and said, \"Read this next.\""
        ),
        "expected": ["Luke Skywalker"],
    },
    {
        "id": "comm_call_is_not_physical_presence",
        "scene_card": {"characters_present": ["Ben Skywalker"], "pov_character": "Ben Skywalker"},
        "prose": (
            "Ben stood alone in the cockpit while the comlink crackled. "
            "\"Stay on the bearing,\" Luke Skywalker said over the encrypted channel."
        ),
        "expected": [],
    },
]


async def bench_presence_checker(router: ModelRouter) -> dict:
    checker = _agent(router, "presence_checker")
    rows = []
    total = 0.0
    latency_total = 0.0
    errors: list[str] = []
    for case in PRESENCE_CASES:
        result, latency, error = await _timed_call(checker.run(case))
        latency_total += latency
        if error:
            errors.append(f"{case['id']}: {error}")
            observed: list[str] = []
        else:
            observed = [
                v.get("character", "")
                for v in (result or {}).get("violations", [])
                if isinstance(v, dict)
            ]
        expected = case["expected"]
        if not expected:
            case_score = 1.0 if not observed else 0.0
        else:
            case_score = 1.0 if all(e in observed for e in expected) else 0.0
            if len(observed) > len(expected):
                case_score *= 0.5
        total += case_score
        rows.append({
            "case_id": case["id"],
            "expected": expected,
            "observed": observed,
            "score": case_score,
        })
    return {
        "score": round(total / len(PRESENCE_CASES), 4),
        "latency_seconds": round(latency_total, 3),
        "calls": len(PRESENCE_CASES),
        "errors": errors,
        "details": rows,
    }


FINAL_GATE_SCENE_CARD = {
    "characters_present": ["Ben Skywalker", "Luke Skywalker"],
    "pov_character": "Ben Skywalker",
    "turning_point": "Ben accepts the mission after seeing the anomaly cluster.",
    "closing_hook": "Ben asks how soon they leave.",
}

FINAL_GATE_CASES = [
    {
        "id": "clean_contract",
        "scene_card": FINAL_GATE_SCENE_CARD,
        "prose": (
            "Luke slid the datapad across the desk. Ben read the anomaly cluster, "
            "felt the same lag in the numbers, and stopped pretending it was only "
            "fatigue. He set the datapad down. \"How soon do we leave?\""
        ),
        "expected_any": [],
    },
    {
        "id": "closing_hook_violation",
        "scene_card": FINAL_GATE_SCENE_CARD,
        "prose": (
            "Luke slid the datapad across the desk. Ben read the anomaly cluster, "
            "felt the same lag in the numbers, and stopped pretending it was only "
            "fatigue. He set the datapad down. \"How soon do we leave?\" Two days "
            "later, the shuttle dropped from hyperspace above the first survey world."
        ),
        "expected_any": ["CLOSING_HOOK_VIOLATION"],
    },
    {
        "id": "weak_turning_point",
        "scene_card": FINAL_GATE_SCENE_CARD,
        "prose": (
            "Luke slid the datapad across the desk. Ben skimmed the report and "
            "said it looked routine. The two of them discussed filing procedures "
            "until the conversation ended without a decision."
        ),
        "expected_any": ["MISSING_TURNING_POINT", "WEAK_TURNING_POINT"],
    },
]


async def bench_gate_critic(router: ModelRouter) -> dict:
    gate = _agent(router, "gate_critic")
    rows = []
    total = 0.0
    latency_total = 0.0
    errors: list[str] = []
    for case in FINAL_GATE_CASES:
        result, latency, error = await _timed_call(
            gate.run(
                {
                    "scene_card": case["scene_card"],
                    "prose": case["prose"],
                    "bible_summary": "",
                }
            )
        )
        latency_total += latency
        if error:
            errors.append(f"{case['id']}: {error}")
            codes: list[str] = []
        else:
            codes = [
                fc.get("code", "")
                for fc in (result or {}).get("failure_codes", [])
                if isinstance(fc, dict)
            ]
        expected_any = case["expected_any"]
        if not expected_any:
            case_score = 1.0 if not codes else 0.0
        else:
            case_score = 1.0 if any(code in codes for code in expected_any) else 0.0
        total += case_score
        rows.append({
            "case_id": case["id"],
            "expected_any": expected_any,
            "observed_codes": codes,
            "score": case_score,
            "raw": result,
        })
    return {
        "score": round(total / len(FINAL_GATE_CASES), 4),
        "latency_seconds": round(latency_total, 3),
        "calls": len(FINAL_GATE_CASES),
        "errors": errors,
        "details": rows,
    }


async def bench_final_gate(router: ModelRouter) -> dict:
    gate = _agent(router, "final_gate")
    rows = []
    total = 0.0
    latency_total = 0.0
    errors: list[str] = []
    for case in FINAL_GATE_CASES:
        result, latency, error = await _timed_call(gate.run(case))
        latency_total += latency
        if error:
            errors.append(f"{case['id']}: {error}")
            codes: list[str] = []
        else:
            codes = [
                fc.get("code", "")
                for fc in (result or {}).get("failure_codes", [])
                if isinstance(fc, dict)
            ]
        expected_any = case["expected_any"]
        if not expected_any:
            case_score = 1.0 if not codes else 0.0
        else:
            case_score = 1.0 if any(code in codes for code in expected_any) else 0.0
        total += case_score
        rows.append({
            "case_id": case["id"],
            "expected_any": expected_any,
            "observed_codes": codes,
            "score": case_score,
            "raw": result,
        })
    return {
        "score": round(total / len(FINAL_GATE_CASES), 4),
        "latency_seconds": round(latency_total, 3),
        "calls": len(FINAL_GATE_CASES),
        "errors": errors,
        "details": rows,
    }


MICRO_REPAIR_CASES = [
    {
        "id": "presence_repair_exact_span",
        "scene_card": {"characters_present": ["Ben Skywalker"], "pov_character": "Ben Skywalker"},
        "prose": (
            "Ben studied the datapad alone. Luke Skywalker crossed the office "
            "and handed him a second report. Ben frowned at the new timestamp."
        ),
        "repair_requests": [
            {
                "issue_type": "presence_violation",
                "character": "Luke Skywalker",
                "evidence": "Luke Skywalker crossed the office and handed him a second report.",
            }
        ],
        "expect_repair": True,
    },
    {
        "id": "no_exact_span_needed",
        "scene_card": {"characters_present": ["Ben Skywalker"], "pov_character": "Ben Skywalker"},
        "prose": "Ben studied the datapad alone and frowned at the timestamp.",
        "repair_requests": [
            {
                "issue_type": "presence_violation",
                "character": "Luke Skywalker",
                "evidence": "Luke crossed the room.",
            }
        ],
        "expect_repair": False,
    },
]


async def bench_micro_repair(router: ModelRouter) -> dict:
    repairer = _agent(router, "micro_repair")
    rows = []
    total = 0.0
    latency_total = 0.0
    errors: list[str] = []
    for case in MICRO_REPAIR_CASES:
        result, latency, error = await _timed_call(repairer.run(case))
        latency_total += latency
        repairs = []
        if error:
            errors.append(f"{case['id']}: {error}")
        else:
            repairs = list((result or {}).get("repairs", []) or [])
        exact = all(
            isinstance(r, dict)
            and isinstance(r.get("pattern"), str)
            and r.get("pattern")
            and r["pattern"] in case["prose"]
            for r in repairs
        )
        if case["expect_repair"]:
            case_score = 1.0 if repairs and exact else 0.0
        else:
            case_score = 1.0 if not repairs else 0.0
        total += case_score
        rows.append({
            "case_id": case["id"],
            "expected_repair": case["expect_repair"],
            "observed_repair_count": len(repairs),
            "exact_patterns": exact,
            "score": case_score,
            "raw": result,
        })
    return {
        "score": round(total / len(MICRO_REPAIR_CASES), 4),
        "latency_seconds": round(latency_total, 3),
        "calls": len(MICRO_REPAIR_CASES),
        "errors": errors,
        "details": rows,
    }


def _plot_architect_cases() -> list[dict]:
    cards = [
        _load_json(BOOK_ROOT / "scene_cards/chapter_01_scene_01.json"),
        _load_json(BOOK_ROOT / "scene_cards/chapter_01_scene_02.json"),
    ]
    return [{"id": f"ch{c['chapter_number']:02d}_sc{c['scene_number']:02d}", "scene_card": c} for c in cards]


async def bench_plot_architect(router: ModelRouter) -> dict:
    architect = _agent(router, "plot_architect")
    rows = []
    total = 0.0
    latency_total = 0.0
    errors: list[str] = []
    cases = _plot_architect_cases()
    for case in cases:
        result, latency, error = await _timed_call(architect.run(case))
        latency_total += latency
        brief = (result or {}).get("generation_brief", {}) if not error else {}
        if error:
            errors.append(f"{case['id']}: {error}")
        missing = [field for field in REQUIRED_BRIEF_FIELDS if field not in brief]
        target_ok = brief.get("target_word_count") == case["scene_card"].get("target_word_count")
        field_score = (len(REQUIRED_BRIEF_FIELDS) - len(missing)) / len(REQUIRED_BRIEF_FIELDS)
        case_score = (0.8 * field_score) + (0.2 if target_ok else 0.0)
        total += case_score
        rows.append({
            "case_id": case["id"],
            "missing_required_fields": missing,
            "target_word_count_expected": case["scene_card"].get("target_word_count"),
            "target_word_count_observed": brief.get("target_word_count"),
            "score": round(case_score, 4),
        })
    return {
        "score": round(total / len(cases), 4),
        "latency_seconds": round(latency_total, 3),
        "calls": len(cases),
        "errors": errors,
        "details": rows,
    }


async def bench_chapter_gate_critic(router: ModelRouter) -> dict:
    critic = _agent(router, "chapter_gate_critic")
    run_dir = RUNS_ROOT / "bench-ch1-sonnet-20260423"
    scene_cards = [
        _load_json(BOOK_ROOT / f"scene_cards/chapter_01_scene_{i:02d}.json")
        for i in range(1, 4)
    ]
    scene_prose = [
        (run_dir / f"chapters/chapter_01_scene_{i:02d}.md").read_text(encoding="utf-8")
        for i in range(1, 4)
    ]
    context = {
        "scene_cards": scene_cards,
        "scene_prose": scene_prose,
        "chapter_number": 1,
        "franchise_slug": "star-wars-legends-eu",
        "book_slug": "the-ruusan-atonement",
        "base_dir": str(PROJECT_ROOT),
    }
    result, latency, error = await _timed_call(critic.run(context))
    expected = ["chapter_passed", "chapter_level_failures", "scene_level_flags", "metrics"]
    missing = [key for key in expected if not isinstance(result, dict) or key not in result]
    metrics_ok = isinstance((result or {}).get("metrics"), dict)
    score = 0.0 if error else (len(expected) - len(missing)) / len(expected)
    if metrics_ok and score:
        score = min(1.0, score + 0.1)
    return {
        "score": round(score, 4),
        "latency_seconds": round(latency, 3),
        "calls": 1,
        "errors": [error] if error else [],
        "details": {
            "missing_keys": missing,
            "raw": result,
        },
    }


ROLE_BENCHES = {
    "gate_critic": bench_gate_critic,
    "continuity_extractor": bench_continuity_extractor,
    "presence_checker": bench_presence_checker,
    "final_gate": bench_final_gate,
    "micro_repair": bench_micro_repair,
    "plot_architect": bench_plot_architect,
    "chapter_gate_critic": bench_chapter_gate_critic,
}


def _summarize(results: dict) -> str:
    lines = [
        "# Haiku 4.5 Replacement Benchmark",
        "",
        f"Generated: {results['generated_at']}",
        f"Base config: `{results['base_config']}`",
        "",
        "Scores are role-specific smoke/eval scores in [0, 1]. They measure",
        "structured reliability, conservative false-positive behavior, exact-span",
        "repair safety, and schema compliance. This is not a prose-quality bench.",
        "",
        "## Overall",
        "",
        "| Model alias | Model id | Avg score | Calls | Latency sec | Errors |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in results["leaderboard"]:
        lines.append(
            f"| {row['model_alias']} | `{row['model_id']}` | {row['avg_score']:.4f} | "
            f"{row['calls']} | {row['latency_seconds']:.3f} | {row['error_count']} |"
        )

    lines.extend(["", "## By Role", ""])
    for role in results["roles"]:
        lines.extend([
            f"### {role}",
            "",
            "| Model alias | Score | Calls | Latency sec | Errors |",
            "| --- | ---: | ---: | ---: | ---: |",
        ])
        role_rows = []
        for model_alias, model_result in results["models"].items():
            role_result = model_result["roles"].get(role)
            if not role_result:
                continue
            role_rows.append((model_alias, role_result))
        role_rows.sort(key=lambda item: item[1].get("score", 0.0), reverse=True)
        for model_alias, role_result in role_rows:
            lines.append(
                f"| {model_alias} | {float(role_result.get('score', 0.0)):.4f} | "
                f"{role_result.get('calls', 0)} | "
                f"{float(role_result.get('latency_seconds', 0.0)):.3f} | "
                f"{len(role_result.get('errors') or [])} |"
            )
        lines.append("")

    lines.extend([
        "## Notes",
        "",
        "- The continuity extractor corpus is still the small synthetic stub in",
        "  `tests/data/continuity_eval_set.json`; do not treat continuity precision",
        "  as production evidence until the human-labeled Ruusan corpus exists.",
        "- Chapter gate critic is scored for structured response shape only in this",
        "  harness because there is not yet a labeled chapter-level gold set.",
        "- A model that ties Haiku on score but runs slower or emits more errors is",
        "  not a good replacement for these roles.",
    ])
    return "\n".join(lines) + "\n"


async def run_bench(args: argparse.Namespace) -> dict:
    global CALL_TIMEOUT_SECONDS

    _load_env()
    CALL_TIMEOUT_SECONDS = float(args.timeout_seconds)

    base_config_path = PROJECT_ROOT / args.config
    base = _base_config(base_config_path)
    cloud_models = base.get("models", {}).get("cloud", {}).get("models", {})

    models = _parse_csv(args.models, DEFAULT_MODELS)
    roles = _parse_csv(args.roles, DEFAULT_ROLES)
    unknown_models = [m for m in models if m not in cloud_models]
    unknown_roles = [r for r in roles if r not in ROLE_BENCHES]
    if unknown_models:
        raise SystemExit(f"Unknown model aliases in config: {', '.join(unknown_models)}")
    if unknown_roles:
        raise SystemExit(f"Unknown roles for this harness: {', '.join(unknown_roles)}")

    stamp = args.stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp_dir = PROJECT_ROOT / ".tmp" / f"haiku_bench_{stamp}"
    out_dir = PROJECT_ROOT / args.out_dir if args.out_dir else RUNS_ROOT / f"bench-haiku-replacement-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_config": str(base_config_path.relative_to(PROJECT_ROOT)),
        "models_requested": models,
        "roles": roles,
        "models": {},
    }

    for model_alias in models:
        model_id = cloud_models[model_alias]
        print(f"[model] {model_alias} -> {model_id}", flush=True)
        cfg = _config_for_model(
            base,
            model_alias,
            roles,
            http_timeout_seconds=float(args.http_timeout_seconds),
        )
        temp_config = _write_temp_config(tmp_dir, model_alias, cfg)
        router = ModelRouter(str(temp_config))
        model_result = {
            "model_alias": model_alias,
            "model_id": model_id,
            "config_path": str(temp_config.relative_to(PROJECT_ROOT)),
            "roles": {},
        }
        for role in roles:
            print(f"  [role] {role}", flush=True)
            role_result = await ROLE_BENCHES[role](router)
            model_result["roles"][role] = role_result
            print(
                f"    score={role_result.get('score')} "
                f"calls={role_result.get('calls')} "
                f"errors={len(role_result.get('errors') or [])}",
                flush=True,
            )
        await _close_router(router)
        results["models"][model_alias] = model_result
        _write_json(out_dir / "results.partial.json", results)

    leaderboard = []
    for model_alias, model_result in results["models"].items():
        role_results = list(model_result["roles"].values())
        avg = sum(float(r.get("score", 0.0)) for r in role_results) / len(role_results)
        calls = sum(int(r.get("calls", 0)) for r in role_results)
        latency = sum(float(r.get("latency_seconds", 0.0)) for r in role_results)
        error_count = sum(len(r.get("errors") or []) for r in role_results)
        leaderboard.append({
            "model_alias": model_alias,
            "model_id": model_result["model_id"],
            "avg_score": round(avg, 4),
            "calls": calls,
            "latency_seconds": round(latency, 3),
            "error_count": error_count,
        })
    leaderboard.sort(key=lambda row: (row["avg_score"], -row["error_count"]), reverse=True)
    results["leaderboard"] = leaderboard

    _write_json(out_dir / "results.json", results)
    (out_dir / "BENCH_SUMMARY.md").write_text(_summarize(results), encoding="utf-8")
    print(f"[done] wrote {out_dir.relative_to(PROJECT_ROOT)}", flush=True)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--models", default=None, help="Comma-separated model aliases from config/settings.yaml")
    parser.add_argument("--roles", default=None, help="Comma-separated roles to benchmark")
    parser.add_argument("--out-dir", default=None, help="Output directory, relative to repo root unless absolute")
    parser.add_argument("--stamp", default=None, help="Stable timestamp/run suffix")
    parser.add_argument("--timeout-seconds", type=float, default=120.0, help="Per agent-call timeout")
    parser.add_argument("--http-timeout-seconds", type=float, default=90.0, help="Cloud HTTP timeout in temp configs")
    args = parser.parse_args()
    asyncio.run(run_bench(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
