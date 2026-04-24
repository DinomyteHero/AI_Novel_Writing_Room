"""Single-scene prose model bench.

Runs plot_architect ONCE on a given scene card, then calls prose_stylist
N times with different model overrides — same brief, same context,
different prose model — and writes each output to a labeled directory.

Usage:
    python scripts/bench_prose_models.py \\
        --concept-seed data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \\
        --scene-card data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_01_scene_01.json \\
        --run-name bench-2026-04-17-prose

By default runs the configured BENCH_CONFIGS matrix. Use ``--models`` to
limit the run to a focused subset (for example ``qwen,minimax,deepseek``).
Models are mutated in-memory on the ModelRouter's config between calls.

Costs depend on the selected matrix. Use ``--models`` for a focused A/B when
you want a cheap comparison run.
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

from src.agents.line_writer import LineWriter  # noqa: E402
from src.agents.micro_repair import MicroRepair  # noqa: E402
from src.agents.plot_architect import PlotArchitect  # noqa: E402
from src.agents.prose_stylist import ProseStylist  # noqa: E402
from src.agents.quality_polish import QualityPolish  # noqa: E402
from src.memory.context_assembler import ContextAssembler  # noqa: E402
from src.model_router import ModelRouter  # noqa: E402
from src.project_paths import ProjectPaths  # noqa: E402
from src.quality.literal_repair import apply_literal_repairs  # noqa: E402
from src.quality.scene_contract_validator import (  # noqa: E402
    load_contract,
    validate_prose_contract,
)


# Pricing per million tokens (OpenRouter models API, 2026-04-24).
PRICING = {
    "anthropic/claude-sonnet-4.6": (3.00, 15.00),
    "anthropic/claude-haiku-4.5": (1.00, 5.00),
    "deepseek/deepseek-v4-flash": (0.14, 0.28),
    "deepseek/deepseek-v4-pro": (1.74, 3.48),
    "qwen/qwen3.6-plus": (0.325, 1.95),
    "moonshotai/kimi-k2.5": (0.3827, 1.72),
    "moonshotai/kimi-k2.6": (0.95, 4.00),
    "google/gemini-3.1-pro-preview": (2.00, 12.00),
    "google/gemini-3-flash-preview": (0.50, 3.00),
    "x-ai/grok-4.20": (2.00, 6.00),
    "x-ai/grok-4.1-fast": (0.20, 0.50),
    "minimax/minimax-m2.7": (0.30, 1.20),
    "z-ai/glm-5.1": (0.95, 3.15),
    "xiaomi/mimo-v2.5-pro": (1.00, 3.00),
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
        "label": "deepseek-v4-flash-t070",
        "model_short": "deepseek",
        "model_full": "deepseek/deepseek-v4-flash",
        "temperature": 0.70,
        "extra_params": {"reasoning": {"effort": "none"}},
    },
    {
        "label": "deepseek-v4-pro-t070",
        "model_short": "deepseekpro",
        "model_full": "deepseek/deepseek-v4-pro",
        "temperature": 0.70,
        "extra_params": {"reasoning": {"effort": "none"}},
    },
    {
        "label": "qwen-36-plus-t070",
        "model_short": "qwen",
        "model_full": "qwen/qwen3.6-plus",
        "temperature": 0.70,
    },
    {
        "label": "kimi-k25-t070",
        "model_short": "kimi",
        "model_full": "moonshotai/kimi-k2.5",
        "temperature": 0.70,
    },
    {
        "label": "kimi-k26-t070",
        "model_short": "kimi26",
        "model_full": "moonshotai/kimi-k2.6",
        "temperature": 0.70,
    },
    {
        "label": "minimax-m27-t070",
        "model_short": "minimax",
        "model_full": "minimax/minimax-m2.7",
        "temperature": 0.70,
    },
    {
        "label": "grok-420-t070",
        "model_short": "grok420",
        "model_full": "x-ai/grok-4.20",
        "temperature": 0.70,
    },
    {
        "label": "grok-41-fast-t070",
        "model_short": "grok41fast",
        "model_full": "x-ai/grok-4.1-fast",
        "temperature": 0.70,
    },
    {
        "label": "glm-51-t070",
        "model_short": "glm",
        "model_full": "z-ai/glm-5.1",
        "temperature": 0.70,
    },
    {
        "label": "mimo-v25-pro-t070",
        "model_short": "mimo25pro",
        "model_full": "xiaomi/mimo-v2.5-pro",
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
    "deepseek":     "deepseek/deepseek-v4-flash",
    "deepseekpro":  "deepseek/deepseek-v4-pro",
    "kimi":         "moonshotai/kimi-k2.5",
    "kimi26":       "moonshotai/kimi-k2.6",
    "grok420":      "x-ai/grok-4.20",
    "grok41fast":   "x-ai/grok-4.1-fast",
    "glm":          "z-ai/glm-5.1",
    "mimo25pro":    "xiaomi/mimo-v2.5-pro",
    "gpt54":        "openai/gpt-5.4",
    "gpt54_mini":   "openai/gpt-5.4-mini",
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
    if model_short in {"deepseek", "deepseekpro"}:
        router.config["agent_routing"][agent_role]["params"]["reasoning"] = {
            "effort": "none"
        }


def default_scene_contract_path(scene_card_path: str | Path, scene_card: dict) -> Path:
    """Return the conventional scene-contract path for a scene card."""

    card_path = Path(scene_card_path)
    book_dir = card_path.parent.parent
    ch = int(scene_card["chapter_number"])
    sc = int(scene_card.get("scene_number", 1))
    return book_dir / "scene_contracts" / f"ch{ch:02d}_sc{sc:02d}.json"


def summarize_contract_validation(result: dict) -> str:
    """Compact status string for bench output."""

    status = "PASS" if result.get("passed") else "FAIL"
    return (
        f"{status} ({result.get('hard_failure_count', 0)} hard / "
        f"{result.get('failure_count', 0)} total)"
    )


def contract_failures_to_repair_requests(validation: dict) -> list[dict]:
    """Convert hard scene-contract failures into MicroRepair requests."""

    requests = []
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


def contract_validation_summary_entry(validation: dict, output_file: Path, paths) -> dict:
    """Small bench-summary payload for a validation artifact."""

    return {
        "passed": validation["passed"],
        "failure_count": validation["failure_count"],
        "hard_failure_count": validation["hard_failure_count"],
        "output_file": str(output_file.relative_to(paths.base)),
    }


async def run_contract_repair(
    *,
    micro_repair: MicroRepair | None,
    repair_model: str | None,
    prose: str,
    validation: dict,
    scene_contract: dict,
    scene_card: dict,
    bench_dir: Path,
    output_stem: str,
    paths,
    max_repairs: int,
    max_total_changed_chars: int,
    max_changed_ratio: float,
) -> dict | None:
    """Run MicroRepair on hard contract failures, apply, and revalidate."""

    if micro_repair is None or repair_model is None or validation.get("passed"):
        return None

    repair_requests = contract_failures_to_repair_requests(validation)
    if not repair_requests:
        return None

    print(
        f"    [contract_repair] {repair_model} on "
        f"{len(repair_requests)} hard failure(s) ..."
    )
    repair_result = await micro_repair.run({
        "prose": prose,
        "scene_card": scene_card,
        "repair_requests": repair_requests,
    })
    repair_json_path = bench_dir / f"{output_stem}__CONTRACT_REPAIR_{repair_model}.json"
    repair_json_path.write_text(
        json.dumps(repair_result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    application = apply_literal_repairs(
        prose,
        repair_result.get("repairs", []),
        max_repairs=max_repairs,
        max_total_changed_chars=max_total_changed_chars,
        max_changed_ratio=max_changed_ratio,
    )
    repaired_prose = application["prose"]
    repaired_path = bench_dir / f"{output_stem}__CONTRACT_REPAIRED_{repair_model}.md"
    repaired_path.write_text(repaired_prose, encoding="utf-8")

    repaired_validation = validate_prose_contract(repaired_prose, scene_contract)
    repaired_validation_path = (
        bench_dir / f"{output_stem}__CONTRACT_REPAIRED_{repair_model}__CONTRACT.json"
    )
    repaired_validation_path.write_text(
        json.dumps(repaired_validation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(
        "    [contract_repair] applied "
        f"{len(application['applied'])}/{len(repair_result.get('repairs', []))}; "
        f"{summarize_contract_validation(repaired_validation)}"
    )

    return {
        "model_short": repair_model,
        "repair_output_file": str(repair_json_path.relative_to(paths.base)),
        "output_file": str(repaired_path.relative_to(paths.base)),
        "application": {
            "applied_count": len(application["applied"]),
            "skipped_count": len(application["skipped"]),
            "changed_char_count": application["changed_char_count"],
            "change_budget": application["change_budget"],
            "applied": application["applied"],
            "skipped": application["skipped"],
        },
        "scene_contract_validation": contract_validation_summary_entry(
            repaired_validation,
            repaired_validation_path,
            paths,
        ),
    }


async def run_bench(
    concept_seed_path: str,
    scene_card_path: str,
    run_name: str,
    config_path: str = "config/settings.yaml",
    models_filter: list[str] | None = None,
    reuse_brief_from: str | None = None,
    plot_architect_model: str | None = None,
    line_edit_model: str | None = None,
    line_edit_temperature: float = 0.35,
    polish_model: str | None = None,
    scene_contract_path: str | None = None,
    auto_scene_contract: bool = False,
    fail_on_contract: bool = False,
    contract_repair_model: str | None = None,
    contract_repair_temperature: float = 0.1,
    contract_repair_max_repairs: int = 2,
    contract_repair_max_total_changed_chars: int = 500,
    contract_repair_max_changed_ratio: float = 0.12,
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

    scene_contract = None
    resolved_contract_path = None
    if scene_contract_path:
        resolved_contract_path = Path(scene_contract_path)
    elif auto_scene_contract:
        auto_path = default_scene_contract_path(scene_card_path, scene_card)
        if auto_path.exists():
            resolved_contract_path = auto_path
        else:
            print(f"[contract] no scene contract found at {auto_path}")
    if resolved_contract_path:
        if not resolved_contract_path.exists():
            print(f"[FATAL] scene contract path not found: {resolved_contract_path}")
            await router.close()
            return
        scene_contract = load_contract(resolved_contract_path)
        print(f"[contract] loaded {resolved_contract_path}")

    assembler = ContextAssembler(concept_seed_path=concept_seed_path)
    line_edit_models = [
        model.strip() for model in (line_edit_model or "").split(",") if model.strip()
    ]

    plot_architect = PlotArchitect(router)
    prose_stylist = ProseStylist(router)
    line_writer = LineWriter(router) if line_edit_models else None
    quality_polish = QualityPolish(router) if polish_model else None
    micro_repair = MicroRepair(router) if contract_repair_model else None

    if plot_architect_model:
        apply_model_override(router, "plot_architect", plot_architect_model, 0.4)
        print(f"[override] plot_architect -> {plot_architect_model} "
              f"({MODEL_ALIASES.get(plot_architect_model, plot_architect_model)}) @ t=0.4")
    if contract_repair_model:
        apply_model_override(
            router,
            "micro_repair",
            contract_repair_model,
            contract_repair_temperature,
            1800,
        )
        print(
            f"[override] micro_repair -> {contract_repair_model} "
            f"({MODEL_ALIASES.get(contract_repair_model, contract_repair_model)}) "
            f"@ t={contract_repair_temperature:.2f}"
        )
        if scene_contract is None:
            print("[contract_repair] ignored because no scene contract is loaded")
            micro_repair = None
            contract_repair_model = None

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
    any_contract_fail = False
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
                **cfg.get("extra_params", {}),
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

        if scene_contract is not None:
            validation = validate_prose_contract(prose, scene_contract)
            validation_path = bench_dir / f"{cfg['label']}__CONTRACT.json"
            validation_path.write_text(
                json.dumps(validation, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            result_entry["scene_contract_validation"] = (
                contract_validation_summary_entry(validation, validation_path, paths)
            )
            print(f"  [contract] {summarize_contract_validation(validation)}")
            if not validation["passed"]:
                for failure in validation["failures"][:5]:
                    location = (
                        f" line {failure['line']}" if "line" in failure else ""
                    )
                    speaker = (
                        f" {failure['speaker']}" if "speaker" in failure else ""
                    )
                    print(
                        f"    - {failure['severity']} {failure['check_id']}"
                        f"{speaker}{location}: {failure['message']}"
                    )
                repair_entry = await run_contract_repair(
                    micro_repair=micro_repair,
                    repair_model=contract_repair_model,
                    prose=prose,
                    validation=validation,
                    scene_contract=scene_contract,
                    scene_card=scene_card,
                    bench_dir=bench_dir,
                    output_stem=cfg["label"],
                    paths=paths,
                    max_repairs=contract_repair_max_repairs,
                    max_total_changed_chars=contract_repair_max_total_changed_chars,
                    max_changed_ratio=contract_repair_max_changed_ratio,
                )
                if repair_entry is not None:
                    result_entry["contract_repair"] = repair_entry
                    if not repair_entry["scene_contract_validation"]["passed"]:
                        any_contract_fail = True
                else:
                    any_contract_fail = True

        downstream_prose = prose

        # --- Optional post-generation line edit ---
        if line_writer is not None and line_edit_models:
            result_entry["line_edits"] = []
            for edit_model in line_edit_models:
                apply_model_override(
                    router,
                    "line_writer",
                    edit_model,
                    line_edit_temperature,
                    8192,
                )
                line_edit_full = MODEL_ALIASES.get(edit_model, edit_model)
                print(
                    f"  [line_edit] {edit_model} ({line_edit_full}) "
                    f"@ t={line_edit_temperature:.2f} ..."
                )
                line_edit_start = time.time()
                try:
                    line_edit_result = await line_writer.run({
                        "source_prose": prose,
                        "scene_card": scene_card,
                        "generation_brief": brief,
                        "characters_present": scene_card.get(
                            "characters_present", []
                        ),
                        "pov_approach": assembler.get_pov_approach(),
                        "franchise_profile_text": franchise_profile_text,
                    })
                    line_edited_prose = line_edit_result["prose"]
                except Exception as e:
                    print(
                        f"    [ERROR] line edit failed: "
                        f"{e.__class__.__name__}: {e}"
                    )
                    continue

                line_edit_duration = time.time() - line_edit_start
                line_edit_wc = len(line_edited_prose.split())
                line_edit_cc = len(line_edited_prose)
                le_in = count_tokens_rough(
                    prose + json.dumps(scene_card) + json.dumps(brief)
                )
                le_out = count_tokens_rough(line_edited_prose)
                le_cost = estimate_cost(line_edit_full, le_in, le_out)
                print(
                    f"    line-edited in {line_edit_duration:.1f}s - "
                    f"{line_edit_wc}w / {line_edit_cc}c "
                    f"(~{le_in}in + {le_out}out = ~${le_cost:.4f})"
                )

                line_edit_path = (
                    bench_dir / f"{cfg['label']}__LINE_EDIT_{edit_model}.md"
                )
                line_edit_path.write_text(line_edited_prose, encoding="utf-8")
                line_edit_entry = {
                    "model_short": edit_model,
                    "model_full": line_edit_full,
                    "temperature": line_edit_temperature,
                    "duration_s": round(line_edit_duration, 1),
                    "word_count": line_edit_wc,
                    "char_count": line_edit_cc,
                    "est_in_tokens": le_in,
                    "est_out_tokens": le_out,
                    "est_cost_usd": round(le_cost, 4),
                    "output_file": str(line_edit_path.relative_to(paths.base)),
                }
                if scene_contract is not None:
                    validation = validate_prose_contract(
                        line_edited_prose,
                        scene_contract,
                    )
                    validation_path = (
                        bench_dir
                        / f"{cfg['label']}__LINE_EDIT_{edit_model}__CONTRACT.json"
                    )
                    validation_path.write_text(
                        json.dumps(validation, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    line_edit_entry["scene_contract_validation"] = (
                        contract_validation_summary_entry(
                            validation,
                            validation_path,
                            paths,
                        )
                    )
                    print(
                        "    [contract] "
                        f"{summarize_contract_validation(validation)}"
                    )
                    if not validation["passed"]:
                        repair_entry = await run_contract_repair(
                            micro_repair=micro_repair,
                            repair_model=contract_repair_model,
                            prose=line_edited_prose,
                            validation=validation,
                            scene_contract=scene_contract,
                            scene_card=scene_card,
                            bench_dir=bench_dir,
                            output_stem=f"{cfg['label']}__LINE_EDIT_{edit_model}",
                            paths=paths,
                            max_repairs=contract_repair_max_repairs,
                            max_total_changed_chars=(
                                contract_repair_max_total_changed_chars
                            ),
                            max_changed_ratio=contract_repair_max_changed_ratio,
                        )
                        if repair_entry is not None:
                            line_edit_entry["contract_repair"] = repair_entry
                            if not repair_entry["scene_contract_validation"]["passed"]:
                                any_contract_fail = True
                        else:
                            any_contract_fail = True
                result_entry["line_edits"].append(line_edit_entry)
                result_entry["line_edit"] = line_edit_entry
                downstream_prose = line_edited_prose

        # --- Optional polish step ---
        if quality_polish is not None and polish_model:
            apply_model_override(router, "quality_polish", polish_model, 0.4)
            polish_full = MODEL_ALIASES.get(polish_model, polish_model)
            print(f"  [polish] {polish_model} ({polish_full}) @ t=0.4 …")
            polish_start = time.time()
            try:
                polish_result = await quality_polish.run({
                    "prose": downstream_prose,
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
                p_in = count_tokens_rough(
                    downstream_prose + json.dumps(scene_card) + neg_constraints
                )
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
                if scene_contract is not None:
                    validation = validate_prose_contract(polished_prose, scene_contract)
                    validation_path = bench_dir / f"{cfg['label']}__POLISHED__CONTRACT.json"
                    validation_path.write_text(
                        json.dumps(validation, indent=2, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    result_entry["polish"]["scene_contract_validation"] = (
                        contract_validation_summary_entry(
                            validation,
                            validation_path,
                            paths,
                        )
                    )
                    print(
                        "    [contract] "
                        f"{summarize_contract_validation(validation)}"
                    )
                    if not validation["passed"]:
                        repair_entry = await run_contract_repair(
                            micro_repair=micro_repair,
                            repair_model=contract_repair_model,
                            prose=polished_prose,
                            validation=validation,
                            scene_contract=scene_contract,
                            scene_card=scene_card,
                            bench_dir=bench_dir,
                            output_stem=f"{cfg['label']}__POLISHED",
                            paths=paths,
                            max_repairs=contract_repair_max_repairs,
                            max_total_changed_chars=(
                                contract_repair_max_total_changed_chars
                            ),
                            max_changed_ratio=contract_repair_max_changed_ratio,
                        )
                        if repair_entry is not None:
                            result_entry["polish"]["contract_repair"] = repair_entry
                            if not repair_entry["scene_contract_validation"]["passed"]:
                                any_contract_fail = True
                        else:
                            any_contract_fail = True

        results.append(result_entry)

    # Restore original routing
    router.config["agent_routing"]["prose_stylist"] = original_routing

    # --- Step 3: write summary ---
    summary = {
        "scene_card_path": scene_card_path,
        "scene_contract_path": (
            str(resolved_contract_path) if resolved_contract_path else None
        ),
        "scene_label": f"Ch{ch}S{sc}",
        "pov_character": scene_card.get("pov_character"),
        "target_word_count": scene_card.get("target_word_count"),
        "plot_architect_duration_s": round(pa_duration, 1),
        "contract_repair_model": contract_repair_model,
        "contract_repair_max_repairs": contract_repair_max_repairs,
        "contract_repair_max_total_changed_chars": (
            contract_repair_max_total_changed_chars
        ),
        "contract_repair_max_changed_ratio": contract_repair_max_changed_ratio,
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
    if fail_on_contract and any_contract_fail:
        print("[contract] --fail-on-contract requested and at least one output failed.")
        raise SystemExit(2)


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
        "--line-edit-model",
        default=None,
        help="Comma-separated short names of models to run LineWriter on each "
             "prose output (e.g. 'deepseek,gpt54_mini'). Skips line edit when "
             "omitted.",
    )
    p.add_argument(
        "--line-edit-temperature",
        type=float,
        default=0.35,
        help="Temperature for --line-edit-model. Default: 0.35.",
    )
    p.add_argument(
        "--polish-model",
        default=None,
        help="Short-name of model to run quality_polish on each prose output "
             "(e.g. 'haiku'). Skips polish step when omitted.",
    )
    p.add_argument(
        "--scene-contract",
        default=None,
        help="Path to a scene_contract JSON file to validate each prose output.",
    )
    p.add_argument(
        "--auto-scene-contract",
        action="store_true",
        help="Load data/.../scene_contracts/chNN_scMM.json when present.",
    )
    p.add_argument(
        "--fail-on-contract",
        action="store_true",
        help="Exit nonzero if any generated output fails the scene contract.",
    )
    p.add_argument(
        "--contract-repair-model",
        default=None,
        help="Short-name model for bounded exact-span contract repair "
             "(e.g. 'deepseekpro' or 'gpt54_mini'). Requires a scene contract.",
    )
    p.add_argument(
        "--contract-repair-temperature",
        type=float,
        default=0.1,
        help="Temperature for --contract-repair-model. Default: 0.1.",
    )
    p.add_argument(
        "--contract-repair-max-repairs",
        type=int,
        default=2,
        help="Maximum exact-span repairs to apply per output. Default: 2.",
    )
    p.add_argument(
        "--contract-repair-max-total-changed-chars",
        type=int,
        default=500,
        help="Maximum cumulative replacement span per output. Default: 500.",
    )
    p.add_argument(
        "--contract-repair-max-changed-ratio",
        type=float,
        default=0.12,
        help="Maximum replacement span as a ratio of prose length. Default: 0.12.",
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
        line_edit_model=args.line_edit_model,
        line_edit_temperature=args.line_edit_temperature,
        polish_model=args.polish_model,
        scene_contract_path=args.scene_contract,
        auto_scene_contract=args.auto_scene_contract,
        fail_on_contract=args.fail_on_contract,
        contract_repair_model=args.contract_repair_model,
        contract_repair_temperature=args.contract_repair_temperature,
        contract_repair_max_repairs=args.contract_repair_max_repairs,
        contract_repair_max_total_changed_chars=(
            args.contract_repair_max_total_changed_chars
        ),
        contract_repair_max_changed_ratio=args.contract_repair_max_changed_ratio,
    ))


if __name__ == "__main__":
    main()
