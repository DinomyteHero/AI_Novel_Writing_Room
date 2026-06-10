# Bench baseline — The Unfinished Shadow ch32 (climax duel), 2026-06-09

First baseline under the post-teardown pipeline shape (all pre-2026-04-21
numbers remain invalidated). Run dir:
`output/star-wars-legends-eu/the-unfinished-shadow/runs/bench-2026-06-09-ch32-baseline/`
(gitignored; reproducible from the checked-in scene card + seed).

Config: current shipping routing — PlotArchitect + ProseStylist on
`deepseek/deepseek-v4-pro` (t=0.4 / t=0.7), `--rhythm-metrics`, LineWriter
A/B on `deepseek-v4-pro` vs `gpt-5.4-mini` (both t=0.35).

## Drafter baseline (deepseek-v4-pro-t070)

| Metric | Value | Band |
|---|---|---|
| Word count | **2,440 vs 4,500 target (54%)** | undershoot — load-bearing finding |
| Em-dash / 1k words | **13.6** (Zahn baseline ~3.1, warn >10) | warn |
| Staccato runs | 8 (warn >8) | at threshold |
| Default-opener % | 42% (warn >45%) | advisory |
| Dialogue-bearing ¶ % | 23% (duel scene) | flagged `dialogue_starved` |
| Abstract tics / 1k | 0.40 | clean |
| Cost (draft) | $0.048 (~20.6k in / 3.5k out), 75s | — |

Issues fired: `em_dash_overuse` (med), `staccato_cluster` (med),
`opener_monotone` (low), `dialogue_starved` (med — expected low-dialogue
scene; check the card's `dialogue_density_target` before treating as real).

## LineWriter A/B

| Line editor | Words | Δ rhythm metrics | Time | Cost |
|---|---|---|---|---|
| deepseek-v4-pro @ t=0.35 | 2,439 (−1) | none — output near-identical to source | 43.4s | $0.027 |
| gpt-5.4-mini @ t=0.35 | 2,402 (−38) | negligible (±0.2 on all metrics) | 17.2s | $0.022 |

**Decision: keep LineWriter on `gpt-5.4-mini`** (current routing). V4 Pro as
line editor barely edits at this temperature and is 2.5× slower for no
measurable rhythm gain. Neither line editor resolves rhythm issues — that is
the RhythmEditor's job (enabled on this book), not the LineWriter's.

## Watch items for the ch11+ drafting run

1. **Word-count discipline**: 54% of target on the climax card is the
   number to re-check across the real run (`chapter_word_count_telemetry`).
2. **Em-dash density**: 13.6/1k confirms `rhythm_editor` (trigger
   `em_dash_overuse`) earning its keep on this book.
3. Total bench spend: ~$0.10 all calls in.

---

## Addendum — same-day follow-up series (4 samples total)

| Run | Ask | Delivered | Ratio | Notes |
|---|---|---|---|---|
| ch32 baseline | 4,500 | 2,440 | 54% | pre-prompt-pass |
| ch32 post-prompt | 4,500 | 1,888 | 42% | hard length contract + per-beat budgets in prompt — no effect |
| ch32_sc02 (split) | 2,300 | 1,331 | 58% | scene split to an "achievable" target — ratio unchanged |
| ch32_sc02 calib | 4,000 | 1,707 | 43% (74% of 2,300 intent) | inflated ask on the same card |

**Finding:** DeepSeek V4 Pro delivers ~43-58% of *any* asked length — output
scales with the ask at roughly half-gain, and prompt-language strengthening
does not move it. Em-dash density (13.6-19.9/1k across all four samples) is
likewise prompt-resistant.

**Decisions shipped:**
1. `runtime.lean_prose_only.length_calibration` — rendering-side multiplier
   on the drafter's word-count ask (default 1.0; this book 1.8). Card targets
   stay planning truth; telemetry measures against them.
2. Five oversized cards (ch01/11/16/20/32, 4,200-4,500 targets) split at
   their natural beat seams into two scenes each (44 cards total), keeping
   per-scene intents ≤2,900.
3. Rhythm-editor caps raised for this book (20 edits / 3,500 chars) and the
   editor prompt gained a copy-don't-reconstruct rule — the calib run showed
   7 of 13 proposed edits rejected as `pattern_not_in_prose` (paraphrased
   spans), and the surviving 6 only cut em-dashes 19.9 → 16.2/1k.
4. Expected manuscript length at calibration 1.8 ≈ card-target sum (~110k
   words); per-chapter telemetry is the live check during the real run.
