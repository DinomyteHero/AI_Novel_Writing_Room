"""Run the final literary-copy tail on an existing prose artifact.

This is the fast path after a draft has already passed scene contracts:
source prose -> continuity lockfile -> motif/copydesk/voltage diagnostics ->
LiteraryPolish -> post-polish revalidation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from src.agents.literary_polish import LiteraryPolish  # noqa: E402
from src.agents.micro_repair import MicroRepair  # noqa: E402
from src.memory.context_assembler import ContextAssembler  # noqa: E402
from src.model_router import ModelRouter  # noqa: E402
from src.pipeline.final_copy import (  # noqa: E402
    build_continuity_lockfile,
    build_motif_ledger,
    run_copydesk_checks,
    score_read_aloud_voltage,
    validate_final_copy,
)
from src.project_paths import ProjectPaths  # noqa: E402
from src.quality.literal_repair import apply_literal_repairs  # noqa: E402
from src.quality.scene_contract_validator import (  # noqa: E402
    load_contract,
    validate_prose_contract,
)


MODEL_ALIASES = {
    "claude": "anthropic/claude-sonnet-4.6",
    "haiku": "anthropic/claude-haiku-4.5",
    "deepseek": "deepseek/deepseek-v4-flash",
    "deepseekpro": "deepseek/deepseek-v4-pro",
    "gpt54": "openai/gpt-5.4",
    "gpt54_mini": "openai/gpt-5.4-mini",
    "gpt54mini": "openai/gpt-5.4-mini",
    "gemini": "google/gemini-3.1-pro-preview",
    "grok420": "x-ai/grok-4.20",
    "grok41fast": "x-ai/grok-4.1-fast",
}

PRICING = {
    "anthropic/claude-sonnet-4.6": (3.00, 15.00),
    "deepseek/deepseek-v4-pro": (1.74, 3.48),
    "openai/gpt-5.4": (2.50, 15.00),
    "openai/gpt-5.4-mini": (0.75, 4.50),
}


def count_tokens_rough(text: str) -> int:
    return max(len(text) // 4, len(text.split()) * 4 // 3)


def estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    if model not in PRICING:
        return 0.0
    in_price, out_price = PRICING[model]
    return (in_tokens / 1_000_000) * in_price + (
        out_tokens / 1_000_000
    ) * out_price


def apply_model_override(
    router: ModelRouter,
    agent_role: str,
    model_short: str,
    temperature: float,
    max_tokens: int,
) -> None:
    cloud_models = router.config["models"]["cloud"]["models"]
    if model_short not in cloud_models:
        if model_short not in MODEL_ALIASES:
            raise ValueError(f"Unknown model short-name: {model_short}")
        cloud_models[model_short] = MODEL_ALIASES[model_short]
    router.config["agent_routing"][agent_role] = {
        "backend": "cloud",
        "model": model_short,
        "params": {"temperature": temperature, "max_tokens": max_tokens},
    }
    if model_short in {"deepseek", "deepseekpro"}:
        router.config["agent_routing"][agent_role]["params"]["reasoning"] = {
            "effort": "none"
        }


def default_scene_contract_path(scene_card_path: str | Path, scene_card: dict) -> Path:
    card_path = Path(scene_card_path)
    book_dir = card_path.parent.parent
    chapter = int(scene_card["chapter_number"])
    scene = int(scene_card.get("scene_number", 1))
    return book_dir / "scene_contracts" / f"ch{chapter:02d}_sc{scene:02d}.json"


def artifact_ref(path: Path, paths: ProjectPaths) -> str:
    try:
        return str(path.relative_to(paths.base))
    except ValueError:
        pass
    try:
        return str(path.resolve().relative_to(paths.base.resolve()))
    except ValueError:
        return str(path)


def contract_failures_to_repair_requests(validation: dict) -> list[dict]:
    """Convert hard scene-contract failures into MicroRepair requests."""

    requests: list[dict] = []
    for failure in validation.get("failures") or []:
        if failure.get("severity", "error") != "error":
            continue
        request = {
            "issue_type": failure.get("check_id", "scene_contract_failure"),
            "message": failure.get("message", ""),
            "pattern": failure.get("pattern"),
        }
        for key in ("speaker", "line", "excerpt"):
            if key in failure:
                request[key] = failure[key]
        requests.append(request)
    return requests


def summarize_contract_validation(validation: dict) -> str:
    status = "PASS" if validation.get("passed") else "FAIL"
    return (
        f"{status} ({validation.get('hard_failure_count', 0)} hard / "
        f"{validation.get('failure_count', 0)} total)"
    )


def final_validation_summary(validation: dict, validation_path: Path, paths) -> dict:
    contract_validation = validation.get("scene_contract_validation")
    return {
        "passed": validation["passed"],
        "output_file": artifact_ref(validation_path, paths),
        "copydesk_passed": validation["copydesk"]["passed"],
        "voltage_total": validation["read_aloud_voltage"]["total_score"],
        "scene_contract_validation": (
            None
            if contract_validation is None
            else {
                "passed": contract_validation["passed"],
                "failure_count": contract_validation["failure_count"],
                "hard_failure_count": contract_validation["hard_failure_count"],
            }
        ),
    }


async def run_post_polish_contract_repair(
    *,
    micro_repair: MicroRepair | None,
    repair_model: str | None,
    final_prose: str,
    final_validation: dict,
    scene_contract: dict | None,
    scene_card: dict,
    run_dir: Path,
    output_stem: str,
    source_word_count: int,
    paths: ProjectPaths,
    max_repairs: int,
    max_total_changed_chars: int,
    max_changed_ratio: float,
) -> tuple[str, dict, dict] | None:
    """Run a bounded literal scrub if final polish violates scene contract."""

    contract_validation = final_validation.get("scene_contract_validation")
    if (
        micro_repair is None
        or repair_model is None
        or scene_contract is None
        or contract_validation is None
        or contract_validation.get("passed")
    ):
        return None

    repair_requests = contract_failures_to_repair_requests(contract_validation)
    if not repair_requests:
        return None

    print(
        f"[post_polish_contract_repair] {repair_model} on "
        f"{len(repair_requests)} hard failure(s) ..."
    )
    repair_result = await micro_repair.run({
        "prose": final_prose,
        "scene_card": scene_card,
        "scene_contract": scene_contract,
        "repair_requests": repair_requests,
    })
    repair_json_path = run_dir / f"{output_stem}__CONTRACT_REPAIR_{repair_model}.json"
    repair_json_path.write_text(
        json.dumps(repair_result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    application = apply_literal_repairs(
        final_prose,
        repair_result.get("repairs", []),
        max_repairs=max_repairs,
        max_total_changed_chars=max_total_changed_chars,
        max_changed_ratio=max_changed_ratio,
    )
    repaired_prose = application["prose"]
    repaired_path = run_dir / f"{output_stem}__CONTRACT_REPAIRED_{repair_model}.md"
    repaired_path.write_text(repaired_prose, encoding="utf-8")

    repaired_validation = validate_final_copy(
        repaired_prose,
        scene_contract=scene_contract,
        source_word_count=source_word_count,
        scene_card=scene_card,
    )
    repaired_validation_path = (
        run_dir / f"{output_stem}__CONTRACT_REPAIRED_{repair_model}__VALIDATION.json"
    )
    repaired_validation_path.write_text(
        json.dumps(repaired_validation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    repaired_contract = repaired_validation.get("scene_contract_validation") or {}
    print(
        "[post_polish_contract_repair] applied "
        f"{len(application['applied'])}/{len(repair_result.get('repairs', []))}; "
        f"{summarize_contract_validation(repaired_contract)}"
    )

    entry = {
        "model_short": repair_model,
        "repair_output_file": artifact_ref(repair_json_path, paths),
        "output_file": artifact_ref(repaired_path, paths),
        "application": {
            "applied_count": len(application["applied"]),
            "skipped_count": len(application["skipped"]),
            "changed_char_count": application["changed_char_count"],
            "change_budget": application["change_budget"],
            "applied": application["applied"],
            "skipped": application["skipped"],
        },
        "validation": final_validation_summary(
            repaired_validation,
            repaired_validation_path,
            paths,
        ),
    }
    return repaired_prose, repaired_validation, entry


async def run_final_copy_existing(
    *,
    concept_seed_path: str,
    scene_card_path: str,
    source_prose_path: str,
    run_name: str,
    config_path: str,
    model: str,
    temperature: float,
    generation_brief_path: str | None,
    scene_contract_path: str | None,
    auto_scene_contract: bool,
    diagnostics_only: bool,
    allow_contract_fail: bool,
    post_polish_contract_repair_model: str | None,
    post_polish_contract_repair_temperature: float,
    post_polish_contract_repair_max_repairs: int,
    post_polish_contract_repair_max_total_changed_chars: int,
    post_polish_contract_repair_max_changed_ratio: float,
    no_fail: bool,
) -> int:
    paths = ProjectPaths.from_concept_seed_path(concept_seed_path, run_id=run_name)
    run_dir = paths.run_dir
    if run_dir is None:
        print("[FATAL] run_dir is None - did you pass a run-name?")
        return 1
    run_dir.mkdir(parents=True, exist_ok=True)

    scene_card = json.loads(Path(scene_card_path).read_text(encoding="utf-8"))
    generation_brief = {}
    if generation_brief_path:
        generation_brief = json.loads(
            Path(generation_brief_path).read_text(encoding="utf-8")
        )
    source_path = Path(source_prose_path)
    source_prose = source_path.read_text(encoding="utf-8")
    source_copy = run_dir / source_path.name
    source_copy.write_text(source_prose, encoding="utf-8")

    scene_contract = None
    resolved_contract_path = None
    if scene_contract_path:
        resolved_contract_path = Path(scene_contract_path)
    elif auto_scene_contract:
        candidate = default_scene_contract_path(scene_card_path, scene_card)
        if candidate.exists():
            resolved_contract_path = candidate
    if resolved_contract_path:
        scene_contract = load_contract(resolved_contract_path)
        print(f"[contract] loaded {resolved_contract_path}")

    contract_validation = None
    if scene_contract:
        contract_validation = validate_prose_contract(source_prose, scene_contract)
        contract_path = run_dir / f"{source_path.stem}__SOURCE_CONTRACT.json"
        contract_path.write_text(
            json.dumps(contract_validation, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        status = "PASS" if contract_validation["passed"] else "FAIL"
        print(
            f"[source contract] {status} "
            f"({contract_validation['hard_failure_count']} hard / "
            f"{contract_validation['failure_count']} total)"
        )
        if (
            not contract_validation["passed"]
            and not allow_contract_fail
            and not diagnostics_only
        ):
            print("[FATAL] source prose is not contract-clean; run repair first.")
            if not no_fail:
                return 2

    lockfile = build_continuity_lockfile(
        scene_card=scene_card,
        generation_brief=generation_brief,
        scene_contract=scene_contract,
        contract_validation=contract_validation,
        source_label=source_path.stem,
    )
    motif_ledger = build_motif_ledger(
        source_prose,
        character_names=scene_card.get("characters_present", []),
    )
    copydesk_report = run_copydesk_checks(
        source_prose,
        target_word_count=scene_card.get("target_word_count"),
        scene_card=scene_card,
    )
    voltage_report = score_read_aloud_voltage(source_prose, scene_card=scene_card)

    artifact_map = {
        "continuity_lockfile": run_dir / f"{source_path.stem}__CONTINUITY_LOCKFILE.json",
        "motif_ledger": run_dir / f"{source_path.stem}__MOTIF_LEDGER.json",
        "copydesk": run_dir / f"{source_path.stem}__COPYDESK.json",
        "read_aloud_voltage": run_dir / f"{source_path.stem}__READ_ALOUD_VOLTAGE.json",
    }
    artifact_map["continuity_lockfile"].write_text(
        json.dumps(lockfile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    artifact_map["motif_ledger"].write_text(
        json.dumps(motif_ledger, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    artifact_map["copydesk"].write_text(
        json.dumps(copydesk_report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    artifact_map["read_aloud_voltage"].write_text(
        json.dumps(voltage_report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    summary: dict = {
        "source_prose_path": source_prose_path,
        "source_copy": artifact_ref(source_copy, paths),
        "scene_card_path": scene_card_path,
        "generation_brief_path": generation_brief_path,
        "scene_contract_path": str(resolved_contract_path) if resolved_contract_path else None,
        "diagnostics": {k: artifact_ref(v, paths) for k, v in artifact_map.items()},
    }

    if diagnostics_only:
        summary_path = run_dir / "final_copy_summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[done] diagnostics only: {artifact_ref(run_dir, paths)}")
        return 0

    router = ModelRouter(config_path)
    ok, msg = await router.health_check()
    if not ok:
        print(f"[FATAL] OpenRouter health check failed: {msg}")
        await router.close()
        return 1
    print(f"[ok] {msg}")
    apply_model_override(router, "literary_polish", model, temperature, 12000)
    micro_repair = None
    if post_polish_contract_repair_model:
        if scene_contract is None:
            print("[post_polish_contract_repair] ignored: no scene contract loaded")
            post_polish_contract_repair_model = None
        else:
            apply_model_override(
                router,
                "micro_repair",
                post_polish_contract_repair_model,
                post_polish_contract_repair_temperature,
                1800,
            )
            micro_repair = MicroRepair(router)
            print(
                "[override] micro_repair -> "
                f"{post_polish_contract_repair_model} "
                f"({MODEL_ALIASES.get(post_polish_contract_repair_model, post_polish_contract_repair_model)}) "
                f"@ t={post_polish_contract_repair_temperature:.2f}"
            )
    assembler = ContextAssembler(concept_seed_path=concept_seed_path)
    agent = LiteraryPolish(router)

    model_full = MODEL_ALIASES.get(model, model)
    print(f"[literary_polish] {model} ({model_full}) @ t={temperature:.2f}")
    start = time.time()
    result = await agent.run({
        "source_prose": source_prose,
        "scene_card": scene_card,
        "generation_brief": generation_brief,
        "continuity_lockfile": lockfile,
        "motif_ledger": motif_ledger,
        "copydesk_report": copydesk_report,
        "voltage_report": voltage_report,
        "scene_contract": scene_contract,
        "scene_contract_validation": contract_validation,
        "franchise_profile_text": assembler.get_franchise_profile_text(),
    })
    final_prose = result["prose"]
    duration = time.time() - start
    final_path = run_dir / f"{source_path.stem}__FINAL_COPY_{model}.md"
    final_path.write_text(final_prose, encoding="utf-8")

    final_validation = validate_final_copy(
        final_prose,
        scene_contract=scene_contract,
        source_word_count=len(source_prose.split()),
        scene_card=scene_card,
    )
    final_validation_path = run_dir / f"{source_path.stem}__FINAL_COPY_{model}__VALIDATION.json"
    final_validation_path.write_text(
        json.dumps(final_validation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    in_tokens = count_tokens_rough(
        source_prose
        + json.dumps(lockfile)
        + json.dumps(motif_ledger)
        + json.dumps(copydesk_report)
        + json.dumps(voltage_report)
    )
    out_tokens = count_tokens_rough(final_prose)
    cost = estimate_cost(model_full, in_tokens, out_tokens)

    output_stem = f"{source_path.stem}__FINAL_COPY_{model}"
    post_repair = await run_post_polish_contract_repair(
        micro_repair=micro_repair,
        repair_model=post_polish_contract_repair_model,
        final_prose=final_prose,
        final_validation=final_validation,
        scene_contract=scene_contract,
        scene_card=scene_card,
        run_dir=run_dir,
        output_stem=output_stem,
        source_word_count=len(source_prose.split()),
        paths=paths,
        max_repairs=post_polish_contract_repair_max_repairs,
        max_total_changed_chars=(
            post_polish_contract_repair_max_total_changed_chars
        ),
        max_changed_ratio=post_polish_contract_repair_max_changed_ratio,
    )

    summary["final_copy"] = {
        "model_short": model,
        "model_full": model_full,
        "temperature": temperature,
        "duration_s": round(duration, 1),
        "word_count": len(final_prose.split()),
        "char_count": len(final_prose),
        "est_in_tokens": in_tokens,
        "est_out_tokens": out_tokens,
        "est_cost_usd": round(cost, 4),
        "output_file": artifact_ref(final_path, paths),
        "validation": artifact_ref(final_validation_path, paths),
        "passed": final_validation["passed"],
    }
    if post_repair is not None:
        repaired_prose, repaired_validation, repair_entry = post_repair
        summary["final_copy"]["post_polish_contract_repair"] = repair_entry
        if repair_entry["validation"]["passed"]:
            summary["final_copy"]["raw_output_file"] = summary["final_copy"][
                "output_file"
            ]
            summary["final_copy"]["raw_validation"] = summary["final_copy"][
                "validation"
            ]
            summary["final_copy"]["output_file"] = repair_entry["output_file"]
            summary["final_copy"]["validation"] = repair_entry["validation"][
                "output_file"
            ]
            summary["final_copy"]["passed"] = True
            summary["final_copy"]["word_count"] = len(repaired_prose.split())
            summary["final_copy"]["char_count"] = len(repaired_prose)
        else:
            summary["final_copy"]["passed"] = repaired_validation["passed"]
    summary_path = run_dir / "final_copy_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(
        f"[done] {summary['final_copy']['word_count']}w in {duration:.1f}s "
        f"(~${cost:.4f}) -> {summary['final_copy']['output_file']}"
    )
    await router.close()
    if not summary["final_copy"]["passed"] and not no_fail:
        return 2
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Final literary copy for an existing prose artifact"
    )
    parser.add_argument(
        "--concept-seed",
        default="data/franchises/star-wars-legends-eu/books/"
        "the-ruusan-atonement/concept_seed.json",
    )
    parser.add_argument("--scene-card", required=True)
    parser.add_argument("--source-prose", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument("--model", default="gpt54")
    parser.add_argument("--temperature", type=float, default=0.45)
    parser.add_argument("--generation-brief", default=None)
    parser.add_argument("--scene-contract", default=None)
    parser.add_argument("--auto-scene-contract", action="store_true")
    parser.add_argument("--diagnostics-only", action="store_true")
    parser.add_argument("--allow-contract-fail", action="store_true")
    parser.add_argument(
        "--post-polish-contract-repair-model",
        default="deepseekpro",
        help="Short-name model for a bounded literal scrub after final polish.",
    )
    parser.add_argument(
        "--post-polish-contract-repair-temperature",
        type=float,
        default=0.1,
        help="Temperature for post-polish contract repair. Default: 0.1.",
    )
    parser.add_argument(
        "--post-polish-contract-repair-max-repairs",
        type=int,
        default=5,
        help="Maximum exact-span repairs after final polish. Default: 5.",
    )
    parser.add_argument(
        "--post-polish-contract-repair-max-total-changed-chars",
        type=int,
        default=1000,
        help="Maximum cumulative repair span after final polish. Default: 1000.",
    )
    parser.add_argument(
        "--post-polish-contract-repair-max-changed-ratio",
        type=float,
        default=0.12,
        help="Maximum repair span ratio after final polish. Default: 0.12.",
    )
    parser.add_argument("--no-fail", action="store_true")
    args = parser.parse_args()

    code = asyncio.run(run_final_copy_existing(
        concept_seed_path=args.concept_seed,
        scene_card_path=args.scene_card,
        source_prose_path=args.source_prose,
        run_name=args.run_name,
        config_path=args.config,
        model=args.model,
        temperature=args.temperature,
        generation_brief_path=args.generation_brief,
        scene_contract_path=args.scene_contract,
        auto_scene_contract=args.auto_scene_contract,
        diagnostics_only=args.diagnostics_only,
        allow_contract_fail=args.allow_contract_fail,
        post_polish_contract_repair_model=args.post_polish_contract_repair_model,
        post_polish_contract_repair_temperature=(
            args.post_polish_contract_repair_temperature
        ),
        post_polish_contract_repair_max_repairs=(
            args.post_polish_contract_repair_max_repairs
        ),
        post_polish_contract_repair_max_total_changed_chars=(
            args.post_polish_contract_repair_max_total_changed_chars
        ),
        post_polish_contract_repair_max_changed_ratio=(
            args.post_polish_contract_repair_max_changed_ratio
        ),
        no_fail=args.no_fail,
    ))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
