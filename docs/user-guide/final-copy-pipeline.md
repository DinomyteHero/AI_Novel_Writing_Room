# Final Copy Pipeline

> **Production note.** The final-copy lane is **not** the default manuscript master path. For full books, use lean production followed by GPT-5.4 manuscript review, targeted revision, and targeted cleanup — see [Manuscript Production Lifecycle](../architecture/manuscript-production-lifecycle.md). `literary_polish` is a donor/comparison branch: run it on a scene, then cherry-pick safe improvements rather than adopting it wholesale.

The final-copy lane runs a high-tier **literary polish** pass over prose that has already been drafted and saved. It is a post-production diagnostic and donor lane — it is not part of the per-scene drafting pipeline.

## What the lane does

`scripts/final_copy_existing.py` runs the literary-copy tail on an existing prose artifact:

1. Build diagnostic artifacts from the source prose — a continuity lockfile, a motif ledger, a copydesk report, and a read-aloud voltage report.
2. Run `LiteraryPolish` (default `gpt54` at temperature `0.45`).
3. Validate the polished prose against the scene contract with `validate_final_copy`.

There is no contract-repair agent in the lane — the 2026-05-19 lean teardown removed `MicroRepair`. Polish output is validated, not auto-repaired; when validation fails, fix the prose by hand or re-run with a different model.

## Final-Copy Command

```powershell
python scripts/final_copy_existing.py `
  --scene-card data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_05_scene_02.json `
  --source-prose output/star-wars-legends-eu/the-ruusan-atonement/runs/<run>/chapter_05_scene_02.md `
  --run-name final-copy-ch05s02
```

| Flag | Default | Description |
| --- | --- | --- |
| `--scene-card` | required | Scene card JSON for the scene |
| `--source-prose` | required | The already-drafted prose to polish |
| `--run-name` | required | Output run directory name under `runs/` |
| `--concept-seed` | Ruusan seed | Concept seed path |
| `--config` | `config/settings.yaml` | Settings file |
| `--model` | `gpt54` | Short-name model for the literary polish pass |
| `--temperature` | `0.45` | Polish temperature |
| `--generation-brief` | none | Optional generation brief JSON for richer continuity context |
| `--diagnostics-only` | off | Build the diagnostic artifacts and stop — no LLM call, no token cost |
| `--no-fail` | off | Exit 0 even when final validation fails |

Output — the diagnostic artifacts, the polished prose, a validation report, and `final_copy_summary.json` — lands under `output/<franchise>/<book>/runs/<run-name>/`.

## Diagnostics-only pass

For a no-token sanity check of the source prose:

```powershell
python scripts/final_copy_existing.py `
  --scene-card path/to/scene_card.json `
  --source-prose path/to/prose.md `
  --diagnostics-only `
  --run-name final-copy-diagnostics
```

## Bench Command

`scripts/bench_prose_models.py` can run drafting and the final-copy pass in one bench with `--final-copy-model`:

```powershell
python scripts/bench_prose_models.py `
  --scene-card data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_05_scene_02.json `
  --models deepseekpro `
  --final-copy-model gpt54 `
  --final-copy-temperature 0.45 `
  --run-name bench-final-copy-ch05s02
```

Reuse an existing brief with `--reuse-brief-from` to keep model experiments apples-to-apples. See [Benchmarking](../development/benchmarking.md).
