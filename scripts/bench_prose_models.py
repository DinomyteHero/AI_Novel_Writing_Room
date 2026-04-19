"""Single-scene prose model bench.

Runs plot_architect ONCE on a given scene card, then calls prose_stylist
N times with different model overrides — same brief, same context,
different prose model — and writes each output to a labeled directory.

Usage:
    python scripts/bench_prose_models.py \\
        --concept-seed data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \\
        --scene-card data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_01_scene_01.json \\
        --run-name bench-2026-04-17-prose

By default benches three configurations (Sonnet control, DeepSeek, Kimi K2.5).
Models are mutated in-memory on the ModelRouter's config between calls.

Costs: ~$0.08 per full bench (1 Gemini-Pro brief + 3 prose calls).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()  # searches CWD then walks up; finds .env in main repo from worktree

from src.agents.plot_architect import PlotArchitect  # noqa: E402
from src.agents.prose_stylist import ProseStylist  # noqa: E402
from src.agents.quality_polish import QualityPolish  # noqa: E402
from src.memory.context_assembler import ContextAssembler  # noqa: E402
from src.model_router import ModelRouter  # noqa: E402
from src.project_paths import ProjectPaths  # noqa: E402


# Pricing per million tokens (from OpenRouter, 2026-04-17)
PRICING = {
    "anthropic/claude-sonnet-4.6": (3.00, 15.00),
    "anthropic/claude-haiku-4.5": (1.00, 5.00),
    "deepseek/deepseek-v3.2": (0.26, 0.38),
    "moonshotai/kimi-k2.5": (0.38, 1.72),
    "google/gemini-3.1-pro-preview": (2.00, 12.00),
    "google/gemini-3-flash-preview": (0.50, 3.00),
    "x-ai/grok-4.20": (2.00, 6.00),
    "x-ai/grok-4.1-fast": (0.20, 0.50),
    "z-ai/glm-5.1": (0.95, 3.15),
    "openai/gpt-5.4": (2.50, 15.00),
    "openai/gpt-5.4-mini": (0.75, 4.50),
}


def estimate_cost(model: str, in_tokens: int, out_tokens: int) -> float:
    if model not in PRICING:
        return 0.0
    ip, op = PRICING[model]
    return (in_tokens / 1_000_000) * ip + (out_tokens / 1_000_000) * op


def count_tokens_rough(text: str) -> int:
    """Rough token count: 1 token ≈ 0.75 words ≈ 4 chars."""
    return max(len(text) // 4, len(text.split()) * 4 // 3)


BENCH_CONFIGS = [
    {
        "label": "claude-sonnet-46-t080",
        "model_short": "claude",
        "model_full": "anthropic/claude-sonnet-4.6",
        "temperature": 0.80,
    },
    {
        "label": "claude-sonnet-46-t075",
        "model_short": "claude",
        "model_full": "anthropic/claude-sonnet-4.6",
        "temperature": 0.75,
    },
    {
        "label": "claude-sonnet-46-t070",
        "model_short": "claude",
        "model_full": "anthropic/claude-sonnet-4.6",
        "temperature": 0.70,
    },
    {
        "label": "deepseek-v32-t070",
        "model_short": "deepseek",
        "model_full": "deepseek/deepseek-v3.2",
        "temperature": 0.70,
    },
    {
        "label": "kimi-k25-t070",
        "model_short": "kimi",
        "model_full": "moonshotai/kimi-k2.5",
        "temperature": 0.70,
    },
    {
        "label": "grok-420-t070",
        "model_short": "grok420",
        "model_full": "x-ai/grok-4.20",
        "temperature": 0.70,
    },
    {
        "label": "glm-51-t070",
        "model_short": "glm",
        "model_full": "z-ai/glm-5.1",
        "temperature": 0.70,
    },
    {
        "label": "gpt-54-t070",
        "model_short": "gpt54",
        "model_full": "openai/gpt-5.4",
        "temperature": 0.70,
    },
    {
        "label": "gpt-54-t075",
        "model_short": "gpt54",
        "model_full": "openai/gpt-5.4",
        "temperature": 0.75,
    },
    {
        "label": "gpt-54-t080",
        "model_short": "gpt54",
        "model_full": "openai/gpt-5.4",
        "temperature": 0.80,
    },
    {
        "label": "gpt-54-mini-t070",
        "model_short": "gpt54mini",
        "model_full": "openai/gpt-5.4-mini",
        "temperature": 0.70,
    },
    {
        "label": "gemini-31-pro-t070",
        "model_short": "gemini",
        "model_full": "google/gemini-3.1-pro-preview",
        "temperature": 0.70,
    },
    {
        "label": "gemini-3-flash-t070",
        "model_short": "gemini_flash",
        "model_full": "google/gemini-3-flash-preview",
        "temperature": 0.70,
    },
]


# Registry of short-name -> full-model mappings we might override with.
# These are added into the router's cloud.models map on demand.
MODEL_ALIASES = {
    "claude":       "anthropic/claude-sonnet-4.6",
    "haiku":        "anthropic/claude-haiku-4.5",
    "deepseek":     "deepseek/deepseek-v3.2",
    "kimi":         "moonshotai/kimi-k2.5",
    "grok420":      "x-ai/grok-4.20",
    "grok41fast":   "x-ai/grok-4.1-fast",
    "glm":          "z-ai/glm-5.1",
    "gpt54":        "openai/gpt-5.4",
    "gpt54mini":    "openai/gpt-5.4-mini",
    "gemini":       "google/gemini-3.1-pro-preview",
    "gemini_flash": "google/gemini-3-flash-preview",
}


def apply_model_override(router, agent_role: str, model_short: str, temperature: float, max_tokens: int = 8192) -> None:
    """Mutate router.config so agent_role routes to model_short at given params."""
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


async def run_bench(
    concept_seed_path: str,
    scene_card_path: str,
    run_name: str,
    config_path: str = "config/settings.yaml",
    models_filter: list[str] | None = None,
    reuse_brief_from: str | None = None,
    plot_architect_model: str | None = None,
    polish_model: str | None = None,
) -> None:
    # Bootstrap
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
        print("[FATAL] run_dir is None — did you pass a run-name?")
        await router.close()
        return
    bench_dir.mkdir(parents=True, exist_ok=True)

    scene_card = json.loads(Path(scene_card_path).read_text(encoding="utf-8"))
    ch = scene_card["chapter_number"]
    sc = scene_card.get("scene_number", 1)
    print(f"[scene] Ch{ch}S{sc} — pov={scene_card.get('pov_character')} "
          f"target={scene_card.get('target_word_count')}w")

    assembler = ContextAssembler(concept_seed_path=concept_seed_path)

    plot_architect = PlotArchitect(router)
    prose_stylist = ProseStylist(router)
    quality_polish = QualityPolish(router) if polish_model else None

    if plot_architect_model:
        apply_model_override(router, "plot_architect", plot_architect_model, 0.4)
        print(f"[override] plot_architect -> {plot_architect_model} "
              f"({MODEL_ALIASES.get(plot_architect_model, plot_architect_model)}) @ t=0.4")

    # --- Step 1: plot_architect (once) — or reuse an existing brief ---
    if reuse_brief_from:
        reuse_path = Path(reuse_brief_from)
        if not reuse_path.exists():
            print(f"[FATAL] --reuse-brief-from path not found: {reuse_path}")
            await router.close()
            return
        pa_brief_json = reuse_path.read_text(encoding="utf-8")
        brief = json.loads(pa_brief_json)
        (bench_dir / "generation_brief.json").write_text(
            pa_brief_json, encoding="utf-8"
        )
        pa_duration = 0.0
        print(f"[plot_architect] reused brief from {reuse_path} "
              f"({len(pa_brief_json)} chars) — skipping generation")
    else:
        print("\n[plot_architect] generating brief…")
        pa_start = time.time()
        pa_context = {
            "scene_card": scene_card,
            "bible_summary": assembler.get_bible_summary(),
            "franchise_profile_text": assembler.get_franchise_profile_text(),
        }
        try:
            pa_result = await plot_architect.run(pa_context)
        except Exception as e:
            err_msg = str(e)
            if "402" in err_msg:
                print("\n[FATAL] OpenRouter returned 402 Payment Required — "
                      "account balance is insufficient or the requested model is "
                      "outside your credit tier. Top up at "
                      "https://openrouter.ai/credits and re-run.")
            else:
                print(f"[FATAL] plot_architect failed: {e.__class__.__name__}: {e}")
            await router.close()
            return
        brief = pa_result["generation_brief"]
        pa_duration = time.time() - pa_start
        pa_brief_json = json.dumps(brief, indent=2, ensure_ascii=False)
        (bench_dir / "generation_brief.json").write_text(
            pa_brief_json, encoding="utf-8"
        )
        print(f"[plot_architect] done in {pa_duration:.1f}s "
              f"(brief={len(pa_brief_json)} chars)")

    # Assemble prose context once — same input for each prose call
    assembled_context = assembler.assemble(scene_card)
    neg_constraints = assembler.get_negative_constraints()
    franchise_profile_text = assembler.get_franchise_profile_text()
    prose_input = {
        "generation_brief": brief,
        "assembled_context": assembled_context,
        "dynamic_feedback": "",
        "failure_context": "",
        "scene_card": scene_card,
        "pov_approach": assembler.get_pov_approach(),
        "franchise_profile_text": franchise_profile_text,
    }

    # Preserve original routing so we can restore it at the end
    original_routing = deepcopy(router.config["agent_routing"].get("prose_stylist", {}))

    # --- Step 2: prose_stylist (N times, different models) ---
    configs = BENCH_CONFIGS
    if models_filter:
        configs = [c for c in BENCH_CONFIGS if c["label"] in models_filter
                   or c["model_short"] in models_filter]
        if not configs:
            print(f"[FATAL] No configs matched filter: {models_filter}")
            await router.close()
            return
        print(f"[filter] running {len(configs)} of {len(BENCH_CONFIGS)} configs: "
              f"{[c['label'] for c in configs]}")

    results: list[dict] = []
    for cfg in configs:
        print(f"\n[prose_stylist] {cfg['label']} ({cfg['model_full']}, "
              f"temp={cfg['temperature']})…")

        # Mutate routing for this call
        router.config["agent_routing"]["prose_stylist"] = {
            "backend": "cloud",
            "model": cfg["model_short"],
            "params": {
                "temperature": cfg["temperature"],
                "max_tokens": 8192,
            },
        }
        # Inject model key into cloud.models map if it isn't already there
        cloud_models = router.config["models"]["cloud"]["models"]
        if cfg["model_short"] not in cloud_models:
            cloud_models[cfg["model_short"]] = cfg["model_full"]

        ps_start = time.time()
        try:
            result = await prose_stylist.run(prose_input)
            prose = result["prose"]
        except Exception as e:
            print(f"  [ERROR] {cfg['label']}: {e.__class__.__name__}: {e}")
            results.append({**cfg, "error": str(e), "duration_s": 0})
            continue
        ps_duration = time.time() - ps_start

        word_count = len(prose.split())
        char_count = len(prose)
        # Estimate input tokens from assembled context + brief
        in_tokens = count_tokens_rough(
            assembled_context + pa_brief_json + neg_constraints + json.dumps(scene_card)
        )
        out_tokens = count_tokens_rough(prose)
        cost = estimate_cost(cfg["model_full"], in_tokens, out_tokens)

        print(f"  done in {ps_duration:.1f}s — "
              f"{word_count}w / {char_count}c "
              f"(~{in_tokens}in + {out_tokens}out = ~${cost:.4f})")

        out_path = bench_dir / f"{cfg['label']}.md"
        out_path.write_text(prose, encoding="utf-8")

        result_entry = {
            **cfg,
            "duration_s": round(ps_duration, 1),
            "word_count": word_count,
            "char_count": char_count,
            "est_in_tokens": in_tokens,
            "est_out_tokens": out_tokens,
            "est_cost_usd": round(cost, 4),
            "output_file": str(out_path.relative_to(paths.base)),
        }

        # --- Optional polish step ---
        if quality_polish is not None and polish_model:
            apply_model_override(router, "quality_polish", polish_model, 0.4)
            polish_full = MODEL_ALIASES.get(polish_model, polish_model)
            print(f"  [polish] {polish_model} ({polish_full}) @ t=0.4 …")
            polish_start = time.time()
            try:
                polish_result = await quality_polish.run({
                    "prose": prose,
                    "scene_card": scene_card,
                    "quality_metrics": {},
                    "negative_constraints": neg_constraints,
                    "canon_notes": "",
                })
                polished_prose = polish_result["prose"]
            except Exception as e:
                print(f"    [ERROR] polish failed: {e.__class__.__name__}: {e}")
                polished_prose = None

            if polished_prose is not None:
                polish_duration = time.time() - polish_start
                polished_wc = len(polished_prose.split())
                polished_cc = len(polished_prose)
                p_in = count_tokens_rough(prose + json.dumps(scene_card) + neg_constraints)
                p_out = count_tokens_rough(polished_prose)
                p_cost = estimate_cost(polish_full, p_in, p_out)
                print(f"    polished in {polish_duration:.1f}s — {polished_wc}w / {polished_cc}c "
                      f"(~{p_in}in + {p_out}out = ~${p_cost:.4f})")

                polished_path = bench_dir / f"{cfg['label']}__POLISHED.md"
                polished_path.write_text(polished_prose, encoding="utf-8")
                result_entry["polish"] = {
                    "model_short": polish_model,
                    "model_full": polish_full,
                    "duration_s": round(polish_duration, 1),
                    "word_count": polished_wc,
                    "char_count": polished_cc,
                    "est_in_tokens": p_in,
                    "est_out_tokens": p_out,
                    "est_cost_usd": round(p_cost, 4),
                    "output_file": str(polished_path.relative_to(paths.base)),
                }

        results.append(result_entry)

    # Restore original routing
    router.config["agent_routing"]["prose_stylist"] = original_routing

    # --- Step 3: write summary ---
    summary = {
        "scene_card_path": scene_card_path,
        "scene_label": f"Ch{ch}S{sc}",
        "pov_character": scene_card.get("pov_character"),
        "target_word_count": scene_card.get("target_word_count"),
        "plot_architect_duration_s": round(pa_duration, 1),
        "results": results,
    }
    (bench_dir / "bench_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n" + "=" * 60)
    print(f"Bench complete. Output: {bench_dir.relative_to(paths.base)}")
    print("=" * 60)
    print(f"{'label':<30} {'words':>7} {'time_s':>8} {'cost_usd':>10}")
    for r in results:
        if "error" in r:
            print(f"{r['label']:<30} {'ERR':>7} {'-':>8} {'-':>10}")
        else:
            print(f"{r['label']:<30} {r['word_count']:>7} "
                  f"{r['duration_s']:>8} {'$' + str(r['est_cost_usd']):>10}")
    total = sum(r.get("est_cost_usd", 0) for r in results)
    print(f"{'TOTAL prose calls':<30} {'':>7} {'':>8} {'$' + str(round(total, 4)):>10}")

    await router.close()


def main() -> None:
    p = argparse.ArgumentParser(description="Single-scene prose model bench")
    p.add_argument(
        "--concept-seed",
        default="data/franchises/star-wars-legends-eu/books/"
                "the-ruusan-atonement/concept_seed.json",
    )
    p.add_argument(
        "--scene-card",
        default="data/franchises/star-wars-legends-eu/books/"
                "the-ruusan-atonement/scene_cards/chapter_01_scene_01.json",
    )
    p.add_argument("--run-name", default="bench-2026-04-17-prose")
    p.add_argument("--config", default="config/settings.yaml")
    p.add_argument(
        "--models",
        default=None,
        help="Comma-separated list of model labels or short names to include "
             "(e.g. 'deepseek,kimi'). Default: run all.",
    )
    p.add_argument(
        "--reuse-brief-from",
        default=None,
        help="Path to an existing generation_brief.json to reuse instead of "
             "calling plot_architect. Keeps the bench apples-to-apples with "
             "a prior run.",
    )
    p.add_argument(
        "--plot-architect-model",
        default=None,
        help="Short-name override for plot_architect (e.g. 'grok420'). "
             "Ignored when --reuse-brief-from is set.",
    )
    p.add_argument(
        "--polish-model",
        default=None,
        help="Short-name of model to run quality_polish on each prose output "
             "(e.g. 'haiku'). Skips polish step when omitted.",
    )
    args = p.parse_args()

    models_filter = None
    if args.models:
        models_filter = [m.strip() for m in args.models.split(",") if m.strip()]

    asyncio.run(run_bench(
        concept_seed_path=args.concept_seed,
        scene_card_path=args.scene_card,
        run_name=args.run_name,
        config_path=args.config,
        models_filter=models_filter,
        reuse_brief_from=args.reuse_brief_from,
        plot_architect_model=args.plot_architect_model,
        polish_model=args.polish_model,
    ))


if __name__ == "__main__":
    main()
