"""Run the final literary-copy tail on an existing prose artifact.

This is the fast path after a draft has already been saved:
source prose -> continuity lockfile -> motif/copydesk/voltage diagnostics ->
LiteraryPolish -> post-polish validation.
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


def artifact_ref(path: Path, paths: ProjectPaths) -> str:
    try:
        return str(path.relative_to(paths.base))
    except ValueError:
        pass
    try:
        return str(path.resolve().relative_to(paths.base.resolve()))
    except ValueError:
        return str(path)


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
    diagnostics_only: bool,
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

    lockfile = build_continuity_lockfile(
        scene_card=scene_card,
        generation_brief=generation_brief,
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
        "franchise_profile_text": assembler.get_franchise_profile_text(),
    })
    final_prose = result["prose"]
    duration = time.time() - start
    final_path = run_dir / f"{source_path.stem}__FINAL_COPY_{model}.md"
    final_path.write_text(final_prose, encoding="utf-8")

    final_validation = validate_final_copy(
        final_prose,
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
    parser.add_argument("--diagnostics-only", action="store_true")
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
        diagnostics_only=args.diagnostics_only,
        no_fail=args.no_fail,
    ))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
