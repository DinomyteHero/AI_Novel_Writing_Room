# Lean prose test summary

- Run: `test-lean-deepseek-v4-pro-t070-ch01-05-20260424`
- Date: 2026-04-24
- Scope: chapters 1-5, phase 1
- Pipeline: `runtime.lean_prose_only.enabled: true`
- Plot architect: `deepseek/deepseek-v4-flash` via `deepseek`
- Prose stylist: `deepseek/deepseek-v4-pro` via `deepseekpro`
- Prose temperature: `0.70`

## Result

- Scene files saved: 16
- Total words: 22,835
- Target words: 19,800
- Actual / target: 1.15x
- Quarantined scenes: 0
- Exported manuscript: `export/manuscript.md`
- Exported index: `export/chapter_index.md`

The CLI reports `saved_with_advisory` for all scenes because the lean path returns skipped evaluation results. The run logs confirm the intended path for each scene: Plot Architect brief, Prose Stylist draft, then immediate save with gates, checks, polish, save blockers, and post-save agents skipped.

## Comparison To 0.75 Run

| Metric | Temp 0.70 | Temp 0.75 | Delta |
| --- | ---: | ---: | ---: |
| Total words | 22,835 | 24,127 | -1,292 |
| Actual / target | 1.15x | 1.22x | -0.07x |
| Chapter 1 | 3,928 | 4,227 | -299 |
| Chapter 2 | 4,024 | 4,235 | -211 |
| Chapter 3 | 4,264 | 4,602 | -338 |
| Chapter 4 | 4,537 | 5,685 | -1,148 |
| Chapter 5 | 6,082 | 5,378 | +704 |

Temperature `0.70` tightened the total run, especially chapter 4. Chapter 5 moved in the opposite direction, mainly scene 5.3.

## Chapter Counts

| Chapter | Scenes | Words | Target | Ratio |
| --- | ---: | ---: | ---: | ---: |
| 1 | 3 | 3,928 | 3,750 | 1.05x |
| 2 | 3 | 4,024 | 3,750 | 1.07x |
| 3 | 3 | 4,264 | 3,750 | 1.14x |
| 4 | 3 | 4,537 | 3,750 | 1.21x |
| 5 | 4 | 6,082 | 4,800 | 1.27x |

## Scene Counts

| Scene | Words | Target | Ratio |
| --- | ---: | ---: | ---: |
| 01.01 | 1,112 | 1,250 | 0.89x |
| 01.02 | 1,332 | 1,250 | 1.07x |
| 01.03 | 1,484 | 1,250 | 1.19x |
| 02.01 | 1,290 | 1,200 | 1.08x |
| 02.02 | 1,416 | 1,300 | 1.09x |
| 02.03 | 1,318 | 1,250 | 1.05x |
| 03.01 | 1,275 | 1,300 | 0.98x |
| 03.02 | 1,497 | 1,200 | 1.25x |
| 03.03 | 1,492 | 1,250 | 1.19x |
| 04.01 | 1,393 | 1,200 | 1.16x |
| 04.02 | 1,390 | 1,300 | 1.07x |
| 04.03 | 1,754 | 1,250 | 1.40x |
| 05.01 | 1,432 | 1,400 | 1.02x |
| 05.02 | 1,337 | 1,200 | 1.11x |
| 05.03 | 1,786 | 1,200 | 1.49x |
| 05.04 | 1,527 | 1,000 | 1.53x |

## Smoke Checks

- Expected scene files present: 16 / 16
- Markdown code fences found in scene prose: 0
- Refusal artifacts found: 0
- Search hits for `unable to` / `I can't` are ordinary in-world report text or dialogue.
