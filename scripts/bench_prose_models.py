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
from src.agents.literary_polish import LiteraryPolish  # noqa: E402
from src.agents.plot_architect import PlotArchitect  # noqa: E402
from src.agents.prose_stylist import ProseStylist  # noqa: E402
from src.agents.rhythm_editor import RhythmEditor, apply_rhythm_edits  # noqa: E402
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
from src.quality.rhythm_validator import validate_rhythm  # noqa: E402


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


def artifact_ref(path: Path, paths) -> str:
    """Return a stable artifact reference for bench summaries."""

    path = Path(path)
    base = Path(getattr(paths, "base", "."))
    try:
        return str(path.relative_to(base))
    except ValueError:
        pass
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path)


async def run_final_copy_pass(
    *,
    literary_polish: LiteraryPolish | None,
    final_copy_model: str | None,
    source_prose: str,
    source_stem: str,
    source_label: str,
    scene_card: dict,
    generation_brief: dict,
    bench_dir: Path,
    paths,
    franchise_profile_text: str,
) -> dict | None:
    """Run final-copy diagnostics, optional literary polish, and revalidation."""

    if literary_polish is None or final_copy_model is None:
        return None

    print(f"  [final_copy] building lockfile for {source_label} ...")
    lockfile = build_continuity_lockfile(
        scene_card=scene_card,
        generation_brief=generation_brief,
        source_label=source_label,
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
    voltage_report = score_read_aloud_voltage(
        source_prose,
        scene_card=scene_card,
    )

    lockfile_path = bench_dir / f"{source_stem}__CONTINUITY_LOCKFILE.json"
    motif_path = bench_dir / f"{source_stem}__MOTIF_LEDGER.json"
    copydesk_path = bench_dir / f"{source_stem}__COPYDESK.json"
    voltage_path = bench_dir / f"{source_stem}__READ_ALOUD_VOLTAGE.json"
    lockfile_path.write_text(
        json.dumps(lockfile, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    motif_path.write_text(
        json.dumps(motif_ledger, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    copydesk_path.write_text(
        json.dumps(copydesk_report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    voltage_path.write_text(
        json.dumps(voltage_report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    final_copy_full = MODEL_ALIASES.get(final_copy_model, final_copy_model)
    print(f"  [literary_polish] {final_copy_model} ({final_copy_full}) ...")
    start = time.time()
    polish_result = await literary_polish.run({
        "source_prose": source_prose,
        "scene_card": scene_card,
        "generation_brief": generation_brief,
        "continuity_lockfile": lockfile,
        "motif_ledger": motif_ledger,
        "copydesk_report": copydesk_report,
        "voltage_report": voltage_report,
        "franchise_profile_text": franchise_profile_text,
    })
    final_prose = polish_result["prose"]
    duration = time.time() - start
    final_wc = len(final_prose.split())
    final_cc = len(final_prose)
    in_tokens = count_tokens_rough(
        source_prose
        + json.dumps(lockfile)
        + json.dumps(motif_ledger)
        + json.dumps(copydesk_report)
        + json.dumps(voltage_report)
    )
    out_tokens = count_tokens_rough(final_prose)
    cost = estimate_cost(final_copy_full, in_tokens, out_tokens)

    final_path = bench_dir / f"{source_stem}__FINAL_COPY_{final_copy_model}.md"
    final_path.write_text(final_prose, encoding="utf-8")

    validation = validate_final_copy(
        final_prose,
        source_word_count=len(source_prose.split()),
        scene_card=scene_card,
    )
    validation_path = (
        bench_dir / f"{source_stem}__FINAL_COPY_{final_copy_model}__VALIDATION.json"
    )
    validation_path.write_text(
        json.dumps(validation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(
        f"    final copy in {duration:.1f}s - {final_wc}w / {final_cc}c "
        f"(~{in_tokens}in + {out_tokens}out = ~${cost:.4f})"
    )

    return {
        "model_short": final_copy_model,
        "model_full": final_copy_full,
        "duration_s": round(duration, 1),
        "word_count": final_wc,
        "char_count": final_cc,
        "est_in_tokens": in_tokens,
        "est_out_tokens": out_tokens,
        "est_cost_usd": round(cost, 4),
        "source_label": source_label,
        "output_file": artifact_ref(final_path, paths),
        "continuity_lockfile": artifact_ref(lockfile_path, paths),
        "motif_ledger": artifact_ref(motif_path, paths),
        "copydesk_report": artifact_ref(copydesk_path, paths),
        "read_aloud_voltage": artifact_ref(voltage_path, paths),
        "validation": {
            "passed": validation["passed"],
            "output_file": artifact_ref(validation_path, paths),
            "copydesk_passed": validation["copydesk"]["passed"],
            "voltage_total": validation["read_aloud_voltage"]["total_score"],
        },
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
    final_copy_model: str | None = None,
    final_copy_temperature: float = 0.45,
    rhythm_metrics: bool = False,
    rhythm_edit: bool = False,
    rhythm_edit_model: str | None = None,
    rhythm_edit_temperature: float = 0.2,
    rhythm_edit_max_edits: int = 8,
    rhythm_edit_max_total_changed_chars: int = 1500,
    rhythm_edit_max_changed_ratio: float = 0.15,
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
    line_edit_models = [
        model.strip() for model in (line_edit_model or "").split(",") if model.strip()
    ]

    plot_architect = PlotArchitect(router)
    prose_stylist = ProseStylist(router)
    line_writer = LineWriter(router) if line_edit_models else None
    literary_polish = LiteraryPolish(router) if final_copy_model else None
    rhythm_editor = RhythmEditor(router) if rhythm_edit else None
    if rhythm_editor and rhythm_edit_model:
        apply_model_override(
            router,
            "rhythm_editor",
            rhythm_edit_model,
            rhythm_edit_temperature,
            2400,
        )
        print(
            f"[override] rhythm_editor -> {rhythm_edit_model} "
            f"({MODEL_ALIASES.get(rhythm_edit_model, rhythm_edit_model)}) "
            f"@ t={rhythm_edit_temperature:.2f}"
        )

    if plot_architect_model:
        apply_model_override(router, "plot_architect", plot_architect_model, 0.4)
        print(f"[override] plot_architect -> {plot_architect_model} "
              f"({MODEL_ALIASES.get(plot_architect_model, plot_architect_model)}) @ t=0.4")
    if final_copy_model:
        apply_model_override(
            router,
            "literary_polish",
            final_copy_model,
            final_copy_temperature,
            12000,
        )
        print(
            f"[override] literary_polish -> {final_copy_model} "
            f"({MODEL_ALIASES.get(final_copy_model, final_copy_model)}) "
            f"@ t={final_copy_temperature:.2f}"
        )

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
            "output_file": artifact_ref(out_path, paths),
        }

        if rhythm_metrics:
            # Decide whether to require dialogue based on the scene card's
            # dialogue_density_target / dialogue_expectation. An `interior` /
            # `low` scene should not be penalised for dialogue starvation.
            density_target = scene_card.get("dialogue_density_target")
            dialogue_expectation = scene_card.get("dialogue_expectation")
            require_dialogue = not (
                density_target == "low"
                or dialogue_expectation == "interior"
            )
            rhythm_result = validate_rhythm(
                prose,
                scope="scene",
                scope_id=f"ch{ch:02d}_sc{sc:02d}__{cfg['label']}",
                require_dialogue=require_dialogue,
            )
            result_entry["rhythm_metrics"] = rhythm_result.to_dict()
            metrics_summary = rhythm_result.metrics
            issue_count = len(rhythm_result.issues)
            print(
                f"  [rhythm] em-dash/1k={metrics_summary.em_dashes_per_1k_words:.1f} "
                f"runs={metrics_summary.short_sentence_runs} "
                f"opener={metrics_summary.default_opener_pct:.0f}% "
                f"dialogue={metrics_summary.dialogue_bearing_paragraph_pct:.0f}% "
                f"tics={metrics_summary.abstract_constructions_per_1k_words:.2f} "
                f"-> {'PASS' if rhythm_result.passed else f'{issue_count} issue(s)'}"
            )
            for issue in rhythm_result.issues:
                print(f"    [{issue.severity}] {issue.code}")

        downstream_prose = prose
        downstream_stem = cfg["label"]
        downstream_label = cfg["label"]

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
                        "source_prose": downstream_prose,
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
                    downstream_prose + json.dumps(scene_card) + json.dumps(brief)
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
                    "output_file": artifact_ref(line_edit_path, paths),
                }
                result_entry["line_edits"].append(line_edit_entry)
                result_entry["line_edit"] = line_edit_entry
                downstream_prose = line_edited_prose
                downstream_stem = Path(line_edit_entry["output_file"]).stem
                downstream_label = f"{cfg['label']} line edit {edit_model}"

        # --- Optional rhythm-editor pass ---
        # Runs after line-edit (or after prose-stylist if no line edit) on
        # whatever is in downstream_prose. Detects rhythm issues with
        # RhythmValidator, calls the LLM editor for bounded literal-edit
        # patches, and applies them under deterministic safety caps.
        if rhythm_editor is not None:
            pre_edit_rhythm = validate_rhythm(
                downstream_prose,
                scope="scene",
                scope_id=f"ch{ch:02d}_sc{sc:02d}",
                require_dialogue=not (
                    scene_card.get("dialogue_density_target") == "low"
                    or scene_card.get("dialogue_expectation") == "interior"
                ),
            )
            trigger_codes = {
                "rhythm.em_dash_overuse",
                "rhythm.staccato_cluster",
                "rhythm.opener_monotone",
                "rhythm.abstract_tic",
            }
            actionable_issues = [
                i for i in pre_edit_rhythm.issues
                if i.code in trigger_codes
            ]
            if not actionable_issues:
                print("  [rhythm_edit] no actionable issues; skipping")
            elif len(pre_edit_rhythm.issues) > 5:
                print(
                    f"  [rhythm_edit] {len(pre_edit_rhythm.issues)} issues "
                    f"exceeds confusion threshold; skipping"
                )
            else:
                print(
                    f"  [rhythm_edit] {len(actionable_issues)} actionable "
                    f"issue(s) detected; invoking editor"
                )
                rhythm_edit_start = time.time()
                try:
                    editor_result = await rhythm_editor.run({
                        "prose": downstream_prose,
                        "scene_card": scene_card,
                        "rhythm_issues": [
                            {
                                "code": i.code,
                                "severity": i.severity,
                                "message": i.message,
                                "metric_value": i.metric_value,
                                "threshold": i.threshold,
                            }
                            for i in actionable_issues
                        ],
                    })
                except Exception as e:
                    print(
                        f"    [ERROR] rhythm editor failed: "
                        f"{e.__class__.__name__}: {e}"
                    )
                    editor_result = {"summary": "", "edits": []}
                rhythm_edit_duration = time.time() - rhythm_edit_start
                edits_proposed = editor_result.get("edits", [])
                patched_prose, audit = apply_rhythm_edits(
                    downstream_prose,
                    edits_proposed,
                    max_edits=rhythm_edit_max_edits,
                    max_total_changed_chars=rhythm_edit_max_total_changed_chars,
                    max_changed_ratio=rhythm_edit_max_changed_ratio,
                )
                applied = [a for a in audit if a["action"] == "applied"]
                rejected = [a for a in audit if a["action"] == "rejected"]
                print(
                    f"    proposed={len(edits_proposed)} "
                    f"applied={len(applied)} "
                    f"rejected={len(rejected)} "
                    f"in {rhythm_edit_duration:.1f}s"
                )
                for a in rejected[:3]:
                    print(f"      rejected: {a.get('reason')}")

                # Write the patched prose + audit + post-edit metrics.
                rhythm_edit_path = (
                    bench_dir / f"{cfg['label']}__RHYTHM_EDIT.md"
                )
                rhythm_edit_path.write_text(patched_prose, encoding="utf-8")
                post_edit_rhythm = validate_rhythm(
                    patched_prose,
                    scope="scene",
                    scope_id=f"ch{ch:02d}_sc{sc:02d}__rhythm_edit",
                    require_dialogue=not (
                        scene_card.get("dialogue_density_target") == "low"
                        or scene_card.get("dialogue_expectation") == "interior"
                    ),
                )
                post_metrics = post_edit_rhythm.metrics
                print(
                    f"  [rhythm post-edit] em-dash/1k="
                    f"{post_metrics.em_dashes_per_1k_words:.1f} "
                    f"runs={post_metrics.short_sentence_runs} "
                    f"opener={post_metrics.default_opener_pct:.0f}% "
                    f"dialogue={post_metrics.dialogue_bearing_paragraph_pct:.0f}% "
                    f"tics={post_metrics.abstract_constructions_per_1k_words:.2f} "
                    f"-> {'PASS' if post_edit_rhythm.passed else f'{len(post_edit_rhythm.issues)} issue(s)'}"
                )
                result_entry["rhythm_edit"] = {
                    "duration_s": round(rhythm_edit_duration, 1),
                    "summary": editor_result.get("summary", ""),
                    "proposed": len(edits_proposed),
                    "applied": len(applied),
                    "rejected": len(rejected),
                    "pre_edit_metrics": pre_edit_rhythm.to_dict()["metrics"],
                    "post_edit_metrics": post_edit_rhythm.to_dict()["metrics"],
                    "pre_edit_issues": [
                        {"code": i.code, "severity": i.severity}
                        for i in pre_edit_rhythm.issues
                    ],
                    "post_edit_issues": [
                        {"code": i.code, "severity": i.severity}
                        for i in post_edit_rhythm.issues
                    ],
                    "audit": audit,
                    "output_file": artifact_ref(rhythm_edit_path, paths),
                }
                downstream_prose = patched_prose
                downstream_stem = rhythm_edit_path.stem
                downstream_label = f"{cfg['label']} rhythm edit"

        # --- Optional final literary copy step ---
        if literary_polish is not None and final_copy_model:
            try:
                final_copy_entry = await run_final_copy_pass(
                    literary_polish=literary_polish,
                    final_copy_model=final_copy_model,
                    source_prose=downstream_prose,
                    source_stem=downstream_stem,
                    source_label=downstream_label,
                    scene_card=scene_card,
                    generation_brief=brief,
                    bench_dir=bench_dir,
                    paths=paths,
                    franchise_profile_text=franchise_profile_text,
                )
                if final_copy_entry is not None:
                    result_entry["final_copy"] = final_copy_entry
            except Exception as e:
                print(
                    f"    [ERROR] final copy failed: "
                    f"{e.__class__.__name__}: {e}"
                )
                result_entry["final_copy"] = {
                    "error": f"{e.__class__.__name__}: {e}"
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
        "final_copy_model": final_copy_model,
        "final_copy_temperature": final_copy_temperature,
        "results": results,
    }
    (bench_dir / "bench_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\n" + "=" * 60)
    print(f"Bench complete. Output: {artifact_ref(bench_dir, paths)}")
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
        "--final-copy-model",
        default=None,
        help="Short-name model for the final literary copy pass "
             "(e.g. 'gpt54'). Skips final-copy artifacts when omitted.",
    )
    p.add_argument(
        "--final-copy-temperature",
        type=float,
        default=0.45,
        help="Temperature for --final-copy-model. Default: 0.45.",
    )
    p.add_argument(
        "--rhythm-metrics",
        action="store_true",
        help="Compute prose-rhythm metrics (em-dash density, short-sentence "
             "runs, opener variance, dialogue-bearing fraction, abstract-tic "
             "density) for every prose variant and include them in "
             "bench_summary.json. Targets are calibrated against a Zahn / "
             "Scoundrels baseline.",
    )
    p.add_argument(
        "--rhythm-edit",
        action="store_true",
        help="After ProseStylist (and optional line edit), run the "
             "RhythmEditor LLM agent to fix detected rhythm issues via "
             "bounded literal substring edits. Pre and post metrics are "
             "recorded.",
    )
    p.add_argument(
        "--rhythm-edit-model",
        default=None,
        help="Short-name model override for the RhythmEditor pass (e.g. "
             "'deepseekpro', 'gpt54_mini'). Defaults to whatever the agent "
             "routing maps for 'rhythm_editor' in settings.yaml.",
    )
    p.add_argument(
        "--rhythm-edit-temperature",
        type=float,
        default=0.2,
        help="Temperature for the RhythmEditor LLM call. Default: 0.2.",
    )
    p.add_argument(
        "--rhythm-edit-max-edits",
        type=int,
        default=8,
        help="Maximum applied edits per scene. Default: 8.",
    )
    p.add_argument(
        "--rhythm-edit-max-total-changed-chars",
        type=int,
        default=1500,
        help="Maximum cumulative changed characters across applied edits. "
             "Default: 1500.",
    )
    p.add_argument(
        "--rhythm-edit-max-changed-ratio",
        type=float,
        default=0.15,
        help="Maximum changed characters as a ratio of prose length. "
             "Default: 0.15.",
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
        final_copy_model=args.final_copy_model,
        final_copy_temperature=args.final_copy_temperature,
        rhythm_metrics=args.rhythm_metrics,
        rhythm_edit=args.rhythm_edit,
        rhythm_edit_model=args.rhythm_edit_model,
        rhythm_edit_temperature=args.rhythm_edit_temperature,
        rhythm_edit_max_edits=args.rhythm_edit_max_edits,
        rhythm_edit_max_total_changed_chars=args.rhythm_edit_max_total_changed_chars,
        rhythm_edit_max_changed_ratio=args.rhythm_edit_max_changed_ratio,
    ))


if __name__ == "__main__":
    main()
