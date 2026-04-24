"""Run LineWriter on an existing prose file.

Useful for post-generation A/B testing without regenerating the source draft.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.agents.line_writer import LineWriter  # noqa: E402
from src.memory.context_assembler import ContextAssembler  # noqa: E402
from src.model_router import ModelRouter  # noqa: E402
from src.project_paths import ProjectPaths  # noqa: E402


PRICING = {
    "deepseek/deepseek-v4-flash": (0.14, 0.28),
    "openai/gpt-5.4-mini": (0.75, 4.50),
}

MODEL_ALIASES = {
    "deepseek": "deepseek/deepseek-v4-flash",
    "gpt54_mini": "openai/gpt-5.4-mini",
    "gpt54mini": "openai/gpt-5.4-mini",
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
        if model_short in MODEL_ALIASES:
            cloud_models[model_short] = MODEL_ALIASES[model_short]
        else:
            raise ValueError(f"Unknown model short-name: {model_short}")
    router.config["agent_routing"][agent_role] = {
        "backend": "cloud",
        "model": model_short,
        "params": {"temperature": temperature, "max_tokens": max_tokens},
    }
    if model_short == "deepseek":
        router.config["agent_routing"][agent_role]["params"]["reasoning"] = {
            "effort": "none"
        }


async def run_line_edit(
    *,
    concept_seed_path: str,
    scene_card_path: str,
    source_prose_path: str,
    run_name: str,
    config_path: str,
    models: list[str],
    temperature: float,
    generation_brief_path: str | None,
) -> None:
    router = ModelRouter(config_path)
    ok, msg = await router.health_check()
    if not ok:
        print(f"[FATAL] OpenRouter health check failed: {msg}")
        await router.close()
        return
    print(f"[ok] {msg}")

    paths = ProjectPaths.from_concept_seed_path(concept_seed_path, run_id=run_name)
    bench_dir = paths.run_dir
    if bench_dir is None:
        print("[FATAL] run_dir is None - did you pass a run-name?")
        await router.close()
        return
    bench_dir.mkdir(parents=True, exist_ok=True)

    scene_card = json.loads(Path(scene_card_path).read_text(encoding="utf-8"))
    source_path = Path(source_prose_path)
    source_prose = source_path.read_text(encoding="utf-8")
    generation_brief = {}
    if generation_brief_path:
        generation_brief = json.loads(
            Path(generation_brief_path).read_text(encoding="utf-8")
        )

    assembler = ContextAssembler(concept_seed_path=concept_seed_path)
    line_writer = LineWriter(router)

    source_copy = bench_dir / source_path.name
    source_copy.write_text(source_prose, encoding="utf-8")
    print(
        f"[source] {source_path} "
        f"({len(source_prose.split())}w / {len(source_prose)}c)"
    )

    results = []
    for model_short in models:
        apply_model_override(router, "line_writer", model_short, temperature, 8192)
        model_full = MODEL_ALIASES.get(model_short, model_short)
        print(f"[line_edit] {model_short} ({model_full}) @ t={temperature:.2f}")
        start = time.time()
        try:
            result = await line_writer.run({
                "source_prose": source_prose,
                "scene_card": scene_card,
                "generation_brief": generation_brief,
                "characters_present": scene_card.get("characters_present", []),
                "pov_approach": assembler.get_pov_approach(),
                "franchise_profile_text": assembler.get_franchise_profile_text(),
            })
        except Exception as exc:
            print(f"  [ERROR] {exc.__class__.__name__}: {exc}")
            results.append({"model_short": model_short, "error": str(exc)})
            continue

        edited = result["prose"]
        duration = time.time() - start
        out_path = bench_dir / f"{source_path.stem}__LINE_EDIT_{model_short}_t{temperature:.2f}.md"
        out_path.write_text(edited, encoding="utf-8")
        in_tokens = count_tokens_rough(
            source_prose + json.dumps(scene_card) + json.dumps(generation_brief)
        )
        out_tokens = count_tokens_rough(edited)
        cost = estimate_cost(model_full, in_tokens, out_tokens)
        entry = {
            "model_short": model_short,
            "model_full": model_full,
            "temperature": temperature,
            "duration_s": round(duration, 1),
            "word_count": len(edited.split()),
            "char_count": len(edited),
            "changed": edited != source_prose,
            "est_in_tokens": in_tokens,
            "est_out_tokens": out_tokens,
            "est_cost_usd": round(cost, 4),
            "output_file": str(out_path.relative_to(paths.base)),
        }
        results.append(entry)
        print(
            f"  done in {duration:.1f}s - {entry['word_count']}w / "
            f"{entry['char_count']}c changed={entry['changed']} "
            f"(~${cost:.4f})"
        )

    summary = {
        "scene_card_path": scene_card_path,
        "source_prose_path": source_prose_path,
        "generation_brief_path": generation_brief_path,
        "results": results,
    }
    (bench_dir / "line_edit_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"[done] {bench_dir.relative_to(paths.base)}")
    await router.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Line-edit an existing prose file")
    parser.add_argument(
        "--concept-seed",
        default="data/franchises/star-wars-legends-eu/books/"
        "the-ruusan-atonement/concept_seed.json",
    )
    parser.add_argument("--scene-card", required=True)
    parser.add_argument("--source-prose", required=True)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument(
        "--models",
        default="deepseek,gpt54_mini",
        help="Comma-separated LineWriter model short names.",
    )
    parser.add_argument("--temperature", type=float, default=0.35)
    parser.add_argument("--generation-brief", default=None)
    args = parser.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    asyncio.run(run_line_edit(
        concept_seed_path=args.concept_seed,
        scene_card_path=args.scene_card,
        source_prose_path=args.source_prose,
        run_name=args.run_name,
        config_path=args.config,
        models=models,
        temperature=args.temperature,
        generation_brief_path=args.generation_brief,
    ))


if __name__ == "__main__":
    main()
