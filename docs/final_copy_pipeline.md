# Final Copy Pipeline

This is the finalized final-copy lane after the Ch5S2 DeepSeek/GPT tests.

The core rule is simple: no prose is treated as final literary copy until it
passes the scene contract after polish. The polish model may improve the music,
but the validator gets the last word.

## Production Path

Use this path for contract-dense scenes and any chapter prose intended to become
part of the manuscript:

1. `PlotArchitect` builds the scene brief.
2. `ProseStylist` drafts with `deepseekpro` at temperature `0.70`.
3. Scene contract validation runs.
4. `MicroRepair` uses `deepseekpro` at temperature `0.10` for bounded
   exact-span contract repairs.
5. Optional `LineWriter` uses `gpt54_mini` at temperature `0.35`.
6. Final-copy diagnostics are generated:
   - continuity lockfile
   - motif ledger
   - copydesk report
   - read-aloud voltage report
7. `LiteraryPolish` uses `gpt54` at temperature `0.45`.
8. Final validation runs.
9. If polish introduced small contract drift, the post-polish velvet-rope scrub
   runs `MicroRepair` again with the full scene contract.
10. The repaired final copy is blessed only if final validation passes.

Configured model roles:

| Role | Model | Temperature | Purpose |
| --- | --- | ---: | --- |
| `prose_stylist` | `deepseekpro` | `0.70` | Primary cheap drafter |
| `line_writer` | `gpt54_mini` | `0.35` | Narrow sentence-level cleanup |
| `micro_repair` | `deepseekpro` | `0.10` | Exact-span contract repair |
| `literary_polish` | `gpt54` | `0.45` | Final literary taste pass |

Repair budgets:

| Setting | Value |
| --- | ---: |
| Max exact-span repairs | `5` |
| Max total changed characters | `1000` |
| Max changed ratio | `0.12` |

## Final-Copy Command

Run the tail against an existing contract-clean or nearly-clean artifact:

```powershell
python scripts/final_copy_existing.py `
  --scene-card data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_05_scene_02.json `
  --source-prose output/star-wars-legends-eu/the-ruusan-atonement/runs/contract-repair-existing-ch05s02-2026-04-25/deepseek-v4-pro-t070__LINE_EDIT_gpt54_mini__CONTRACT_REPAIRED_gpt54_mini.md `
  --generation-brief output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-2026-04-24-ch05s02-ruusan-consent-fix-retry/generation_brief.json `
  --auto-scene-contract `
  --run-name final-copy-ch05s02
```

By default, this runs:

- `gpt54` literary polish at `0.45`
- `deepseekpro` post-polish contract repair at `0.10`
- final validation against the scene contract, copydesk checks, and read-aloud
  voltage

To disable the post-polish scrub for a diagnostic comparison, pass
`--post-polish-contract-repair-model ""`. For production use, keep the scrub
enabled.

## Bench Command

Run draft, repair, and final-copy in one bench:

```powershell
python scripts/bench_prose_models.py `
  --scene-card data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_05_scene_02.json `
  --models deepseekpro `
  --auto-scene-contract `
  --contract-repair-model deepseekpro `
  --contract-repair-max-repairs 5 `
  --contract-repair-max-total-changed-chars 1000 `
  --final-copy-model gpt54 `
  --final-copy-temperature 0.45 `
  --run-name bench-final-copy-ch05s02
```

Reuse an existing brief when running model experiments:

```powershell
python scripts/bench_prose_models.py `
  --scene-card data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_05_scene_02.json `
  --reuse-brief-from output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-flash-draft-pro-polish-ch05s02-20260425/generation_brief.json `
  --models deepseek `
  --auto-scene-contract `
  --contract-repair-model deepseekpro `
  --final-copy-model deepseekpro `
  --final-copy-temperature 0.45 `
  --run-name bench-flash-draft-pro-polish
```

## Flash Experiment Result

The Ch5S2 experiment tested:

```text
DeepSeek V4 Flash draft -> DeepSeek V4 Pro repair -> DeepSeek V4 Pro literary polish -> DeepSeek V4 Pro post-polish scrub
```

Result:

- Source Flash/Pro-repaired prose still failed the tightened contract.
- Raw Pro polish still introduced survivor-owned public-record framing.
- Contract-aware post-polish scrub applied two exact-span repairs.
- Final validation passed with `0` hard failures.
- Read-aloud voltage was `23/25`.

Passing artifact:

```text
output/star-wars-legends-eu/the-ruusan-atonement/runs/final-copy-pro-polish-with-scrub-v5-contract-aware-repair-ch05s02-20260425/deepseek-v4-flash-t070__CONTRACT_REPAIRED_deepseekpro__FINAL_COPY_deepseekpro__CONTRACT_REPAIRED_deepseekpro.md
```

Verdict: Flash can be used as an exploratory cheap lane, but it is not the
recommended default for contract-dense scenes. The default production lane stays
`deepseekpro` draft plus `gpt54` final literary polish.

## Diagnostics Only

For a no-token sanity pass:

```powershell
python scripts/final_copy_existing.py `
  --scene-card path/to/scene_card.json `
  --source-prose path/to/prose.md `
  --auto-scene-contract `
  --diagnostics-only `
  --run-name final-copy-diagnostics
```
