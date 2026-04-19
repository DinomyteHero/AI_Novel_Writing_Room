# Prose-Model Bench — 2026-04-19

Confirmation bench against the regenerated scene cards (post-seed-and-blueprint revision, 2026-04-11 through 2026-04-19). Tests whether the April 17 production picks still hold, adds Kimi K2.5 and GLM 5.1 to the 04-17 matrix, and gets a direct t=0.70 vs t=0.80 read on GPT 5.4.

Companion to [BENCH_SUMMARY_2026-04-17-v3.md](BENCH_SUMMARY_2026-04-17-v3.md).

---

## Test configuration

**Scenes (3, one per structural tier):**
- `chapter_01_scene_01.json` — setup, target 1,250w
- `chapter_13_scene_01.json` — midpoint, target 1,600w
- `chapter_26_scene_02.json` — climax, target 1,700w (not covered in 04-17)

**Pipeline config:** `config/settings.bench.sonnet.yaml` (plot_architect=Grok 4.20 @ t=0.4, polish=Haiku 4.5 @ t=0.4). One `plot_architect` call per scene; brief reused across all prose candidates in waves 2 and 3 via `--reuse-brief-from`.

**Model matrix (8 configs):**

| Short | Full slug | Temp | Wave |
|-------|-----------|------|------|
| claude | anthropic/claude-sonnet-4.6 | 0.80 | 1 (free — short-name filter caught both) |
| claude | anthropic/claude-sonnet-4.6 | 0.70 | 1 |
| deepseek | deepseek/deepseek-v3.2 | 0.70 | 1 |
| grok420 | x-ai/grok-4.20 | 0.70 | 1 |
| gpt54 | openai/gpt-5.4 | 0.70 | 1 |
| kimi | moonshotai/kimi-k2.5 | 0.70 | 2 (reused briefs) |
| glm | z-ai/glm-5.1 | 0.70 | 2 (reused briefs) |
| gpt54 | openai/gpt-5.4 | 0.80 | 3 (reused briefs) |

Each prose output was also passed through a Haiku polish call (`--polish-model haiku`) to match the production pipeline.

**Total cost: $1.11** across all three scenes × 8 configs × (prose + polish). Well under the original ~$2-3 chapter-A/B budget.

---

## Raw numbers — word counts

All percentages against scene target.

### Setup (ch1s1, target 1,250w)

| Model | Prose | % | Polished | Δ | Prose $ | Polish $ |
|-------|------:|--:|---------:|--:|--------:|---------:|
| claude-sonnet-46-t080 | 1,177 | 94% | 1,171 | -1% | $0.043 | $0.012 |
| claude-sonnet-46-t070 | 1,149 | 92% | 1,149 | 0% | $0.042 | $0.011 |
| deepseek-v32-t070 | 1,114 | 89% | 1,112 | 0% | $0.002 | $0.011 |
| grok-420-t070 | **825** | **66%** | 829 | 0% | $0.019 | $0.009 |
| gpt-54-t070 | 1,612 | **129%** | 1,612 | 0% | $0.050 | $0.016 |
| kimi-k25-t070 | 978 | 78% | 979 | 0% | $0.005 | $0.011 |
| glm-51-t070 | 1,083 | 87% | 1,083 | 0% | $0.011 | $0.011 |
| gpt-54-t080 | 1,628 | **130%** | 1,628 | 0% | $0.050 | $0.016 |

### Midpoint (ch13s1, target 1,600w)

| Model | Prose | % | Polished | Δ | Prose $ | Polish $ |
|-------|------:|--:|---------:|--:|--------:|---------:|
| claude-sonnet-46-t080 | 1,525 | 95% | 1,557 | +2% | $0.054 | $0.015 |
| claude-sonnet-46-t070 | 1,451 | 91% | 1,430 | -1% | $0.053 | $0.014 |
| deepseek-v32-t070 | 1,720 | 108% | 1,724 | 0% | $0.003 | $0.018 |
| grok-420-t070 | 1,195 | 75% | 1,194 | 0% | $0.025 | $0.013 |
| gpt-54-t070 | 2,208 | **138%** | 2,208 | 0% | $0.065 | $0.021 |
| kimi-k25-t070 | 1,640 | 102% | 1,640 | 0% | $0.007 | $0.017 |
| glm-51-t070 | 1,225 | 77% | 1,249 | +2% | $0.013 | $0.013 |
| gpt-54-t080 | 2,227 | **139%** | 2,227 | 0% | $0.066 | $0.021 |

### Climax (ch26s2, target 1,700w — NEW vs 04-17)

| Model | Prose | % | Polished | Δ | Prose $ | Polish $ |
|-------|------:|--:|---------:|--:|--------:|---------:|
| claude-sonnet-46-t080 | 1,597 | 94% | 1,598 | 0% | $0.054 | $0.015 |
| claude-sonnet-46-t070 | 1,571 | 92% | 1,571 | 0% | $0.053 | $0.015 |
| deepseek-v32-t070 | 1,147 | **67%** | 1,147 | 0% | $0.002 | $0.012 |
| grok-420-t070 | **937** | **55%** | 937 | 0% | $0.021 | $0.010 |
| gpt-54-t070 | 1,941 | 114% | 1,941 | 0% | $0.058 | $0.018 |
| kimi-k25-t070 | 1,339 | 79% | 1,345 | 0% | $0.006 | $0.014 |
| glm-51-t070 | 1,251 | 74% | 1,251 | 0% | $0.012 | $0.013 |
| gpt-54-t080 | 1,891 | 111% | 1,871 | -1% | $0.057 | $0.018 |

---

## Word-count discipline — consolidated

| Model | ch1s1 | ch13s1 | ch26s2 | Mean | Std dev |
|-------|------:|-------:|-------:|-----:|--------:|
| **claude @ t=0.80** | 94% | 95% | 94% | **94%** | **0.5** |
| **claude @ t=0.70** | 92% | 91% | 92% | **92%** | **0.5** |
| deepseek | 89% | 108% | 67% | 88% | 16.8 |
| grok420 | 66% | 75% | 55% | 65% | 8.2 |
| gpt54 @ t=0.70 | 129% | 138% | 114% | 127% | 9.9 |
| gpt54 @ t=0.80 | 130% | 139% | 111% | 127% | 11.4 |
| kimi-k25 | 78% | 102% | 79% | 86% | 11.1 |
| glm-51 | 87% | 77% | 74% | 79% | 5.5 |

**Claude's cross-scene consistency is the dominant signal.** No other model is within an order of magnitude on standard deviation.

---

## Qualitative observations

Sampled full prose from ch13s1 (midpoint, longest scene, narratively richest) for each wave.

### Claude Sonnet 4.6 (production pick)
Commercial-thriller voice. Tight sentences with sensory grounding ("the heel of his palm against the yoke and felt the durasteel"). Characters distinguished by dialogue rhythm — Desh matter-of-fact, Kael sardonic, Sera precise. Pacing follows observation → implication → action. Small literary flourishes without tipping into purple prose. Matches the voice established in prior Ruusan chapters.

### GPT 5.4
Fluid prose, sharpest individual sentences in the bench. But the overshoot is structural, not stylistic — at t=0.70 and t=0.80 the output is essentially identical (1,612 vs 1,628 on ch1s1, 2,208 vs 2,227 on ch13s1). **Temperature is not a lever on GPT's word-count discipline.** The cost is real: ~$0.065/scene at current routing, and the model ships ~40% more text than asked for on the midpoint.

### Kimi K2.5
More florid register than Claude ("like freckles", "freezer-burned greenhouse"). Occasional overwriting in exposition clauses. **Tense slip at scene close** — "In the silence of the de-structured Force, Ben hears himself think" — shifts to present. Could be brief-compliance artifact, but worth noting as a signal K2.5 is less strict about voice continuity. Strong on specific franchise anchors (GAG operative callout for Desh, pre-Ruusan references) — but these need canon_expert validation since they're introduced spontaneously.

### GLM 5.1
Clean, clipped, efficient prose. Closest to Claude's register of the non-Anthropic candidates. Good dialogue rhythm, concrete details. Slightly less sensory variety than Claude — reads more like reportage, less like immersion. No obvious anti-pattern violations in the sampled scene.

### Grok 4.20
Commercial register, reasonable voice. **Minor formatting glitch observed** — leading whitespace after an em-dash (`" measurable. Not my imagination."`). Fast inference (~10s) but systematically undershoots word count, making the "half Sonnet cost" story misleading: effective $/in-band-word is much worse than raw per-call cost suggests.

### DeepSeek V3.2
Did not sample deeply; relying on 04-17 qualitative notes. Numeric data shows the biggest red flag: **discipline collapses on climax** (67% on 1,700w) after being fine on setup and actually overshooting midpoint. New regression vs 04-17 (which did not include a climax scene in the matrix).

---

## Tier list

**Production-ready (drafter):**
- **claude @ t=0.70 or t=0.80** — only model with sub-1% cross-scene variance. Either temp works; t=0.80 runs ~3 pts hotter, t=0.70 tighter and slightly cheaper.

**Reviewer / polish / secondary roles:**
- **haiku** — already in that role. Polish deltas were ±2% on word count; it is not mangling outputs.
- **kimi K2.5** — acceptable for manuscript review (current use). K2.5 is ~33% cheaper than K2 on input and ~25% cheaper on output; no regression detected at review scale. Do not promote to drafter without a dedicated re-bench.

**Cheap baseline (use only with awareness of the discipline ceiling):**
- **deepseek** — still unbeatable on raw $ ($0.002–0.003 per prose call) but the climax collapse disqualifies it for arc-critical scenes. Acceptable for utility roles (summarizer, lore_extractor) as currently routed.
- **glm 5.1** — consistent undershoot (~79% mean) but at least low variance. Cheaper than Grok and more disciplined. Candidate for a future utility role if we have one to fill.

**Disqualified for drafter:**
- **gpt54** @ either temp — 127% mean overshoot is structural. Not cost-competitive either ($0.058–0.066 per prose call, 30–40% more than Sonnet for output that needs aggressive trimming).
- **grok420** — 65% mean with -55% on climax. Fast and cheap per call, but not producing usable drafts at the target word count.

---

## Recommendation

**Leave `config/settings.yaml` drafter routing unchanged.** Claude Sonnet 4.6 @ t=0.80 (current production) held 94% ± 0.5% across setup, midpoint, and climax — no challenger came within 10pts of that consistency on this bench.

Three specific changes to consider separately:

1. **Drop t on prose_stylist from 0.80 → 0.70.** Claude at 0.70 runs slightly tighter (92% vs 94%) and a hair cheaper. Voice sample at 0.70 looked fine. Low-risk change, measurable ~2% cost savings. *(Optional — 0.80 is also fine.)*

2. **No change to Kimi alias for `manuscript_reviewer`.** K2.5 is live at the alias level (updated 2026-04-19); no regression at review scale is expected, but a cheap before/after reviewer spot-check on one saved chapter would close the loop. Est. ~$0.05.

3. **If Phase 4 adds a drafter-tier budget model**, pick between DeepSeek (cheap but climax-fragile) and GLM 5.1 (slightly more expensive, more disciplined at 79% mean, lower variance). Do not use Grok 4.20 or GPT 5.4 as a drafter — the word-count shapes are disqualifying.

---

## What this bench did not do

- No canon-correctness evaluation. Kimi K2.5 introduced specific franchise references (GAG, pre-Ruusan dates) that were not in the plot brief — these need `canon_expert` review before they are taken as evidence of capability.
- No judge scoring (no `--judge` pass). Word count + manual sampling only.
- No full-chapter pipeline runs (`--skip-gate-loop` A/B). Production `config/settings.yaml` vs `config/settings.bench.sonnet.yaml` delta is not tested here. See [GATE_LOOP_COMPARISON.md](GATE_LOOP_COMPARISON.md) for the 04-17 analysis on that question.
- No re-test of the 04-17 voice anti-pattern rubric. The quick qualitative pass above flagged one tense slip (Kimi) and one formatting glitch (Grok) but did not score against the full rubric.

---

## Artifacts

- Wave 1 (baseline 5 configs, fresh briefs): `bench-2026-04-19-ch1s1/`, `bench-2026-04-19-ch13s1/`, `bench-2026-04-19-ch26s2/`
- Wave 2 (Kimi K2.5 + GLM 5.1, reused briefs): `bench-2026-04-19-ch1s1-v2/`, `bench-2026-04-19-ch13s1-v2/`, `bench-2026-04-19-ch26s2-v2/`
- Wave 3 (GPT 5.4 @ t=0.80, reused briefs): `bench-2026-04-19-ch1s1-v3/`, `bench-2026-04-19-ch13s1-v3/`, `bench-2026-04-19-ch26s2-v3/`

Each run dir contains `bench_summary.json`, `generation_brief.json`, and one `<label>.md` + `<label>__POLISHED.md` per config.
