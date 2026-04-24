# Lean prose test summary

- Run: `test-lean-deepseek-v4-pro-t075-ch01-05-20260424`
- Date: 2026-04-24
- Scope: chapters 1-5, phase 1
- Pipeline: `runtime.lean_prose_only.enabled: true`
- Plot architect: `deepseek/deepseek-v4-flash` via `deepseek`
- Prose stylist: `deepseek/deepseek-v4-pro` via `deepseekpro`
- Prose temperature: `0.75`

## Result

- Scene files saved: 16
- Total words: 24,127
- Target words: 19,800
- Actual / target: 1.22x
- Quarantined scenes: 0
- Exported manuscript: `export/manuscript.md`
- Exported index: `export/chapter_index.md`

The CLI reports `saved_with_advisory` for all scenes because the lean path returns skipped evaluation results. The run logs confirm the intended path for each scene: Plot Architect brief, Prose Stylist draft, then immediate save with gates, checks, polish, save blockers, and post-save agents skipped.

## Chapter Counts

| Chapter | Scenes | Words | Target | Ratio |
| --- | ---: | ---: | ---: | ---: |
| 1 | 3 | 4,227 | 3,750 | 1.13x |
| 2 | 3 | 4,235 | 3,750 | 1.13x |
| 3 | 3 | 4,602 | 3,750 | 1.23x |
| 4 | 3 | 5,685 | 3,750 | 1.52x |
| 5 | 4 | 5,378 | 4,800 | 1.12x |

Chapter 4 is the expansion outlier, especially scenes 4.2 and 4.3.

## Scene Counts

| Scene | Words | Target | Ratio |
| --- | ---: | ---: | ---: |
| 01.01 | 1,140 | 1,250 | 0.91x |
| 01.02 | 1,554 | 1,250 | 1.24x |
| 01.03 | 1,533 | 1,250 | 1.23x |
| 02.01 | 1,428 | 1,200 | 1.19x |
| 02.02 | 1,508 | 1,300 | 1.16x |
| 02.03 | 1,299 | 1,250 | 1.04x |
| 03.01 | 1,257 | 1,300 | 0.97x |
| 03.02 | 1,651 | 1,200 | 1.38x |
| 03.03 | 1,694 | 1,250 | 1.36x |
| 04.01 | 1,285 | 1,200 | 1.07x |
| 04.02 | 2,114 | 1,300 | 1.63x |
| 04.03 | 2,286 | 1,250 | 1.83x |
| 05.01 | 1,359 | 1,400 | 0.97x |
| 05.02 | 1,345 | 1,200 | 1.12x |
| 05.03 | 1,372 | 1,200 | 1.14x |
| 05.04 | 1,302 | 1,000 | 1.30x |

## Smoke Checks

- Expected scene files present: 16 / 16
- Markdown code fences found in scene prose: 0
- Refusal markers found: 0
- One native search hit for `unable to` was ordinary narration, not a model refusal.
