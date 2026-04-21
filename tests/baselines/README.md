# Baselines — frozen prose snapshots for parity tests

These are byte-level snapshots of Ruusan and Betrayal ch01 sc01 output captured **before Slice 1 of the architecture upgrade**. Parity tests (`tests/test_pipeline_regression_*.py`) compare against these to detect inadvertent prose drift from new code when feature flags are off.

## Files

| Baseline | Source run |
|---|---|
| `ruusan_ch01_sc01.md` | `output/star-wars-legends-eu/the-ruusan-atonement/runs/2026-04-19T22-27/chapters/chapter_01_scene_01.md` |
| `betrayal_ch01_sc01.md` | `output/star-wars-legends-eu/legacy-of-the-force-betrayal/runs/2026-04-19T21-43/chapters/chapter_01_scene_01.md` |

## Refresh policy

Only refresh a baseline when:
1. An intentional prose-affecting change has been merged and approved.
2. The new baseline has been human-reviewed for quality parity.
3. The commit message explicitly notes "refresh baseline" and why.

A parity test failure is a bug signal, not a prompt to regenerate the baseline.
