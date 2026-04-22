# Benchmarking

> **Status note (2026-04-21):** Treat the archived `BENCH_*` outputs and April 17-19 routing summaries as **historical only**. Ruusan's concept seed, chapter blueprints, scene cards, and prompt stack have all been materially revised since those benches were run. Do **not** use the older results as the sole basis for a production routing change; re-bench on current inputs first.

Two benchmarking tools live in the repo:

1. **`scripts/bench_prose_models.py`** — single-scene, same-brief, model-A/B/C comparison for the `prose_stylist` (and optionally `plot_architect` and `quality_polish`) roles.
2. **`--skip-gate-loop` CLI flag** — runs the full pipeline on real scene cards without the Gate Critic rewrite loop, so "stripped" pipeline behaviour can be compared against the full pipeline with the same config.

Both are designed for **apples-to-apples model evaluation**: swap one lever at a time and compare outputs on the same scene card with the same generation brief. Older benches remain useful as historical artifacts, but after a material planning or prompt revision they should be treated as stale until rerun on the current inputs.

---

## When to bench

Run a bench when you:

- Want to swap the `prose_stylist` model (or `plot_architect`, or `quality_polish`) and need to know if the new model's voice, word-count discipline, and ensemble handling hold up against the current production pick.
- Are deciding whether the Gate Critic rewrite loop is adding quality or eating cost on a specific scene archetype.
- Need a defensible artifact to justify the routing choice for arc-critical scenes (midpoint, pinch points, climax) that justify a more expensive model.

Skip a bench for purely mechanical changes (bug fixes, logging, non-behavioral refactors) — use the test suite and `--raw-draft` runs instead. If you changed the concept seed, scene cards, franchise profile, prompt stack, or routing around the role you are evaluating, the prior bench is no longer authoritative.

---

## `scripts/bench_prose_models.py` — single-scene model matrix

One `plot_architect` call produces one generation brief; the script then calls `prose_stylist` N times with different model/temperature pairs and writes each output to a labeled file. Same brief, same context, same scene card — only the model changes.

### Basic invocation

```bash
python scripts/bench_prose_models.py \
    --concept-seed data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    --scene-card   data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_01_scene_01.json \
    --run-name     bench-2026-04-17-prose
```

Default config: `config/settings.yaml`. Output lands at `output/<franchise>/<book>/runs/<run_name>/`.

### Flags

| Flag | Description |
|------|-------------|
| `--concept-seed PATH` | Concept seed JSON (franchise-scoped path). Required. |
| `--scene-card PATH` | Scene card JSON. The script benches prose for exactly this scene. |
| `--run-name NAME` | Output directory name under `runs/`. Use a descriptive slug so bench artifacts are easy to find later. |
| `--config PATH` | Path to a settings YAML. Default: `config/settings.yaml`. Pass `config/settings.bench.sonnet.yaml` or `config/settings.bench.gpt.yaml` to freeze the surrounding pipeline. |
| `--models FILTER` | Comma-separated list of model labels or short names to include (e.g. `deepseek,kimi26,qwen`). Default: run all configs currently listed in `BENCH_CONFIGS`. |
| `--reuse-brief-from PATH` | Path to an existing `generation_brief.json` to reuse instead of calling `plot_architect`. Keeps a bench apples-to-apples with a prior run. |
| `--plot-architect-model SHORT` | Override `plot_architect` routing (e.g. `grok420`). Ignored when `--reuse-brief-from` is set. |
| `--polish-model SHORT` | Run `quality_polish` on each prose output with the named model (e.g. `haiku`). Writes a separate `<label>__POLISHED.md` file. |

### Default model matrix

The script benches the ten configurations listed in `BENCH_CONFIGS` by default. Short names map to full OpenRouter slugs:

| Short | Full | Current use |
|-------|------|-------------|
| `claude` | `anthropic/claude-sonnet-4.6` | Production prose |
| `haiku` | `anthropic/claude-haiku-4.5` | Production polish + gates |
| `deepseek` | `deepseek/deepseek-v3.2` | Summarizer, lore_extractor |
| `kimi` | `moonshotai/kimi-k2.5` | Manuscript reviewer |
| `grok420` | `x-ai/grok-4.20` | Canon expert, judge_evaluator |
| `grok41fast` | `x-ai/grok-4.1-fast` | Orchestrator |
| `glm` | `z-ai/glm-5.1` | Bench-only |
| `gpt54` | `openai/gpt-5.4` | Bench-only |
| `gpt54mini` | `openai/gpt-5.4-mini` | Bench-only |
| `gemini` | `google/gemini-3.1-pro-preview` | Plot architect, outline planner |
| `gemini_flash` | `google/gemini-3-flash-preview` | Bench-only |

Each default config runs at `temperature=0.70` on the prose call (with a `claude` variant at 0.80 retained to compare against past production config). Override via the `BENCH_CONFIGS` list in the script when you need a different temperature sweep.

### Cost and runtime

The script prints a per-call cost estimate and a grand-total line at the end. Indicative costs per scene (1,250-1,600 word target):

| Model | Cost | Notes |
|-------|------|-------|
| `deepseek` | ~$0.003 | Cheapest; reliable word-count discipline |
| `gemini_flash` | ~$0.009 | Cheap; occasionally truncates |
| `grok420` | ~$0.025 | Good commercial register, ~half the cost of Sonnet |
| `claude` (Sonnet 4.6) | ~$0.04-0.05 | Best commercial register + best word-count discipline |
| `gpt54` | ~$0.05-0.06 | Sharpest sentence punch; overshoots word count 134%+ |

A full ten-model bench on one scene runs ~$0.20-0.25; the whole-scene pipeline bench (Sonnet + GPT on Ch1 and Ch13) came in at ~$0.21 total. Budget ~$0.50 for a thorough single-scene model sweep, ~$2-3 for a full-chapter A/B.

### Output layout

```
output/<franchise>/<book>/runs/<run_name>/
├── bench_summary.json              # Machine-readable results (words, cost, tokens, paths)
├── generation_brief.json           # The single shared plot_architect output
├── <label>.md                      # One markdown file per model config
├── <label>__POLISHED.md            # (optional, when --polish-model is used)
└── ...
```

The script restores the original routing before exiting, so running a bench does not leak configuration changes into subsequent runs.

### Reusing an existing brief

To A/B a second wave of models against the same brief the first wave used:

```bash
python scripts/bench_prose_models.py \
    --concept-seed ... --scene-card ... \
    --run-name bench-2026-04-17-prose-v2 \
    --reuse-brief-from output/.../runs/bench-2026-04-17-prose/generation_brief.json \
    --models grok420,glm,gpt54
```

---

## `--skip-gate-loop` — full-vs-stripped pipeline comparison

The Gate Critic rewrite loop adds cost and latency. For a given prose-stylist model, the `--skip-gate-loop` flag accepts the first ProseStylist draft without retries, so you can measure:

- Whether the gate loop is adding quality (comparison against the gate-looped version).
- Whether gate false-rejections are eating cost on scenes that were already passable.

QualityPolish and FinalGate still run (unless combined with `--raw-draft`), so the final saved file is still validated.

### Example: full vs stripped on Chapter 1

```bash
# Full pipeline (default) — Sonnet prose with gate rewrite loop
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --chapter 1 --config config/settings.bench.sonnet.yaml \
    --run-name bench-ch1-sonnet-FULL

# Stripped pipeline — same config, no gate loop
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --chapter 1 --config config/settings.bench.sonnet.yaml \
    --skip-gate-loop \
    --run-name bench-ch1-sonnet-STRIPPED
```

Repeat both with `config/settings.bench.gpt.yaml` to produce the four-cell matrix (model × pipeline depth). The `runs/` directory becomes self-documenting:

```
runs/
├── bench-ch1-sonnet-FULL/
├── bench-ch1-sonnet-STRIPPED/
├── bench-ch1-gpt-FULL/
└── bench-ch1-gpt-STRIPPED/
```

Each run saves its own `config_snapshot.yaml`, `invocation.json`, and `prompts_snapshot/` alongside the generated chapters.

---

## Bench configs

Two frozen routing snapshots live in `config/`:

- **`config/settings.bench.sonnet.yaml`** — `prose_stylist` on Sonnet 4.6 @ t=0.70, `plot_architect` on Grok 4.20, `quality_polish` on Haiku 4.5.
- **`config/settings.bench.gpt.yaml`** — identical except `prose_stylist` on GPT 5.4 @ t=0.70, and adds `gpt54: openai/gpt-5.4` to the cloud models map.

Both have Anthropic prompt caching enabled (`anthropic_ttl: 1h`) so repeated scene runs in the same chapter batch amortize input cost.

Add new bench configs as `config/settings.bench.<label>.yaml` when introducing a new prose candidate for chapter-scale comparison.

---

## Writing up a bench

Every meaningful bench should land a short markdown summary alongside its outputs. The existing analyses in `output/star-wars-legends-eu/the-ruusan-atonement/runs/` are the canonical examples:

| File | What it covers |
|------|----------------|
| `BENCH_SUMMARY_2026-04-17.md` | First prose-model sweep (v1): raw cost/words per model |
| `BENCH_SUMMARY_2026-04-17-v2.md` | Expanded analysis (v2): adds tier list and anti-pattern compliance |
| `BENCH_SUMMARY_2026-04-17-v3.md` | Sonnet at t=0.70 added; updates recommendation after temp correction |
| `BENCH_PIPELINE_ANALYSIS.md` | Step-by-step Grok-architect + Sonnet/GPT-prose + Haiku-polish pipeline analysis |
| `GATE_LOOP_COMPARISON.md` | Full-vs-stripped pipeline analysis using `--skip-gate-loop` |

Each summary should contain:

1. **Test configuration** — which models at which temperatures, which scenes, total cost.
2. **Raw numbers** — words, coverage vs target, duration, cost per call.
3. **Qualitative observations** — voice, register, ensemble handling, anti-pattern compliance, word-count discipline.
4. **Tier list or ranking** — which models are production-ready, which are disqualified, why.
5. **Recommendation** — a concrete proposed change to `config/settings.yaml` or a decision to leave the routing as-is.

Keep summaries dated. The `v2`, `v3` suffix convention is fine when you need to revise a prior analysis.

---

## What the bench does *not* do

- It does **not** bench agents other than `prose_stylist`, `plot_architect`, and (optionally) `quality_polish`. Benching `gate_critic`, `canon_expert`, `summarizer`, or `judge_evaluator` requires a different harness.
- It does **not** validate franchise canon. Use a human reviewer or `canon_expert` with the normal pipeline for that.
- It does **not** replace the `--judge` LLM-as-judge evaluation — the judge runs on full saved chapters, the bench runs on raw prose-stylist output.

## Pointers

- Script: [`scripts/bench_prose_models.py`](../../scripts/bench_prose_models.py)
- Bench configs: [`config/settings.bench.sonnet.yaml`](../../config/settings.bench.sonnet.yaml), [`config/settings.bench.gpt.yaml`](../../config/settings.bench.gpt.yaml)
- Analyses: `output/star-wars-legends-eu/the-ruusan-atonement/runs/BENCH_*.md`
- Related CLI flags: [`--skip-gate-loop`](../user-guide/cli-usage.md#pipeline-mode-flags), `--raw-draft`, `--judge`
- Production routing rationale: [`docs/architecture/model-selection-and-cost-review.md`](../architecture/model-selection-and-cost-review.md)
