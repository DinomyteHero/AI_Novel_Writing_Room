# Benchmarking

> **Status note.** Bench numbers go stale fast. The pipeline shape changed materially in the 2026-05-19 lean teardown (gates, polish, save-blockers removed), and Ruusan's planning artifacts and prompt stack have been revised repeatedly. **All pre-2026-04-21 bench numbers are invalidated.** Before making any drafter or line-editor routing decision, re-run the target scene under the current config to re-establish a baseline. Treat archived `BENCH_*` outputs as historical only.

`scripts/bench_prose_models.py` is the single benchmarking tool: a single-scene, same-brief model A/B/C comparison for the `prose_stylist` role, with optional line-edit, rhythm-edit, and final-copy passes layered on top. It is designed for **apples-to-apples model evaluation** — swap one lever at a time and compare outputs on the same scene card with the same generation brief.

## When to bench

Run a bench when you:

- Want to swap the `prose_stylist` model (or `plot_architect`, `line_writer`) and need to know whether the new model's voice, word-count discipline, and rhythm metrics hold up against the current production pick.
- Need a defensible artifact to justify a routing choice for arc-critical scenes (midpoint, pinch points, climax) that might justify a more expensive model.

Skip a bench for purely mechanical changes (bug fixes, logging, non-behavioral refactors) — use the test suite instead. If you changed the concept seed, scene cards, franchise profile, prompt stack, or routing around the role you are evaluating, the prior bench is no longer authoritative.

Word-count discipline remains the load-bearing metric; rhythm metrics (`--rhythm-metrics`) are the secondary signal. Collect cost numbers fresh — do not compare against archived bench tables.

## `scripts/bench_prose_models.py` — single-scene model matrix

One `plot_architect` call produces one generation brief; the script then calls `prose_stylist` N times with different model/temperature pairs and writes each output to a labeled file. Same brief, same context, same scene card — only the model changes.

### Basic invocation

```bash
python scripts/bench_prose_models.py \
    --concept-seed data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    --scene-card   data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_01_scene_01.json \
    --run-name     bench-prose
```

Output lands at `output/<franchise>/<book>/runs/<run_name>/`.

### Flags

| Flag | Description |
|------|-------------|
| `--concept-seed PATH` | Concept seed JSON. Default: the Ruusan seed. |
| `--scene-card PATH` | Scene card JSON. The script benches prose for exactly this scene. |
| `--run-name NAME` | Output directory name under `runs/`. Use a descriptive slug. |
| `--config PATH` | Settings YAML. Default: `config/settings.yaml`. Pass a `config/bench/*.yaml` snapshot to freeze the surrounding pipeline. |
| `--models FILTER` | Comma-separated model labels/short names to include (e.g. `deepseekpro,gpt54`). Default: run all configs in `BENCH_CONFIGS`. |
| `--reuse-brief-from PATH` | Reuse an existing `generation_brief.json` instead of calling `plot_architect`. Keeps a second bench wave apples-to-apples with the first. |
| `--plot-architect-model SHORT` | Override `plot_architect` routing. Ignored when `--reuse-brief-from` is set. |
| `--line-edit-model SHORT[,SHORT]` | Run `LineWriter` on each prose output with the named model(s). Skips the line edit when omitted. |
| `--line-edit-temperature FLOAT` | Temperature for `--line-edit-model`. Default: `0.35`. |
| `--final-copy-model SHORT` | Run the post-draft literary-copy pass with the named model. Skips final-copy artifacts when omitted. |
| `--final-copy-temperature FLOAT` | Temperature for `--final-copy-model`. Default: `0.45`. |
| `--rhythm-metrics` | Compute RhythmValidator metrics (em-dash density, short-sentence runs, opener variance, dialogue-bearing fraction, abstract-tic density) for every prose variant and embed them in `bench_summary.json`. |
| `--rhythm-edit` | After ProseStylist (and optional line edit), run the RhythmEditor pass with bounded literal edits; pre/post metrics are recorded. |
| `--rhythm-edit-model SHORT` | Model override for the RhythmEditor pass. Defaults to the `rhythm_editor` routing. |
| `--rhythm-edit-temperature FLOAT` | Temperature for the RhythmEditor call. Default: `0.2`. |
| `--rhythm-edit-max-edits INT` | Max applied edits per scene. Default: `8`. |
| `--rhythm-edit-max-total-changed-chars INT` | Max cumulative changed characters. Default: `1500`. |
| `--rhythm-edit-max-changed-ratio FLOAT` | Max changed characters as a ratio of prose length. Default: `0.15`. |

### Output layout

```
output/<franchise>/<book>/runs/<run_name>/
├── bench_summary.json              # Machine-readable results (words, cost, tokens, rhythm metrics, paths)
├── generation_brief.json           # The single shared plot_architect output
├── <label>.md                      # One markdown file per model config
└── ...
```

The script prints a per-call cost estimate and a grand total, then restores the original routing before exiting, so a bench does not leak configuration changes into subsequent runs.

### Reusing an existing brief

To A/B a second wave of models against the brief the first wave used:

```bash
python scripts/bench_prose_models.py \
    --concept-seed ... --scene-card ... \
    --run-name bench-prose-v2 \
    --reuse-brief-from output/.../runs/bench-prose/generation_brief.json \
    --models gpt54,deepseekpro
```

## Bench configs

Frozen routing snapshots live in `config/bench/` (e.g. `settings.bench.sonnet.yaml`, `settings.bench.gpt.yaml`). They freeze the surrounding pipeline so only the lever under test changes. `config/bench/experimental-model-aliases.yaml` is the alias reference for candidates that are not part of the shipping routing in `config/settings.yaml`.

Add a new bench config as `config/bench/settings.bench.<label>.yaml` when introducing a new prose candidate for chapter-scale comparison. Bench runs use the lean pipeline — there is no separate non-lean path; a bench config simply leaves the optional rhythm/debt flags off unless the bench targets them.

## Writing up a bench

Every meaningful bench should land a short markdown summary alongside its outputs. Each summary should contain:

1. **Test configuration** — which models at which temperatures, which scene, total cost.
2. **Raw numbers** — words, coverage vs target, duration, cost per call, rhythm metrics.
3. **Qualitative observations** — voice, register, ensemble handling, anti-pattern compliance, word-count discipline.
4. **Ranking** — which models are production-ready, which are disqualified, why.
5. **Recommendation** — a concrete proposed change to `config/settings.yaml`, or a decision to leave routing as-is.

Keep summaries dated.

## What the bench does *not* do

- It benches the `prose_stylist` role (with optional `plot_architect`, `line_writer`, `rhythm_editor`, and final-copy layers). Benching `summarizer` or other utilities requires a different harness.
- It does **not** validate franchise canon — use a human reviewer or the canon-guidance preflight for that.
- It does **not** run the full post-save memory chain; it benches scene prose, not chapter memory or state diffs.

## Pointers

- Script: [`scripts/bench_prose_models.py`](../../scripts/bench_prose_models.py)
- Bench configs: [`config/bench/`](../../config/bench/)
- Current production workflow: [`docs/user-guide/new-manuscript-workflow.md`](../user-guide/new-manuscript-workflow.md)
