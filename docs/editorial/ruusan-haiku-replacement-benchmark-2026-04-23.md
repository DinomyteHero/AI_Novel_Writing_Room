# Ruusan Haiku 4.5 Replacement Benchmark

Date: 2026-04-23 local / 2026-04-24 UTC
Base config: `config/settings.yaml`
Harness: `scripts/bench_haiku_replacements.py`

This benchmark targets the roles currently using `anthropic/claude-haiku-4.5`.
The goal is structured reliability and pipeline safety, not prose quality.

## Roles Tested

Hot-path run:

- `continuity_extractor`
- `presence_checker`
- `final_gate`
- `micro_repair`
- `chapter_gate_critic`

Plot-only supplemental run:

- `plot_architect`

The harness default intentionally excludes `plot_architect` because the long
scene-card planning prompt can expose provider-specific hangs. Run it as a
separate pass when testing planning models.

## Run Artifacts

- Hot-path summary: `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-haiku-replacement-20260423-hotpath-no-plot/BENCH_SUMMARY.md`
- Hot-path raw JSON: `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-haiku-replacement-20260423-hotpath-no-plot/results.json`
- Plot-only DeepSeek/GPT summary: `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-haiku-replacement-20260423-plot-deepseek-gptmini/BENCH_SUMMARY.md`
- Earlier partial full-role run: `output/star-wars-legends-eu/the-ruusan-atonement/runs/bench-haiku-replacement-20260423-core-timeout/results.partial.json`

## Hot-Path Results

| Model alias | Model ID | Avg score | Calls | Latency sec | Errors |
| --- | --- | ---: | ---: | ---: | ---: |
| `grok41fast` | `x-ai/grok-4.1-fast` | 0.9183 | 11 | 38.994 | 0 |
| `qwen` | `qwen/qwen3.6-plus` | 0.9183 | 11 | 280.306 | 0 |
| `deepseek` | `deepseek/deepseek-v4-flash` | 0.9000 | 11 | 56.888 | 0 |
| `haiku` | `anthropic/claude-haiku-4.5` | 0.8500 | 11 | 31.385 | 0 |
| `gpt54_mini` | `openai/gpt-5.4-mini` | 0.8500 | 11 | 15.241 | 0 |

Continuity extractor scores on the small synthetic stub:

| Model alias | Score | Latency sec |
| --- | ---: | ---: |
| `grok41fast` | 0.5917 | 11.247 |
| `qwen` | 0.5917 | 69.103 |
| `deepseek` | 0.5000 | 10.878 |
| `haiku` | 0.2500 | 2.819 |
| `gpt54_mini` | 0.2500 | 2.280 |

All five models scored 1.0 on `presence_checker`, `final_gate`,
`micro_repair`, and `chapter_gate_critic` in this smoke set. The separation is
therefore driven by continuity extraction and latency.

## Plot Architect Supplemental

Clean plot-only scores:

| Model alias | Score | Calls | Latency sec | Notes |
| --- | ---: | ---: | ---: | --- |
| `gpt54_mini` | 1.0000 | 2 | 19.495 | Fastest clean plot-only pass |
| `haiku` | 1.0000 | 2 | 40.337 | Baseline from partial full-role run |
| `grok41fast` | 1.0000 | 2 | 41.276 | Clean non-Claude replacement candidate |
| `deepseek` | 1.0000 | 2 | 69.923 | Clean but slower |

Observed plot-planning concern:

- `qwen` stalled on `plot_architect` in the full-role queue after passing the
  earlier hot-path roles.
- `glm` also stalled on `plot_architect` and previously emitted null-content /
  length warnings in a continuity attempt.

## Pricing Snapshot

OpenRouter pricing pages checked on 2026-04-24 UTC:

| Model | OpenRouter page | Listed input | Listed output |
| --- | --- | ---: | ---: |
| Claude Haiku 4.5 | https://openrouter.ai/anthropic/claude-haiku-4.5 | $1.00/M | $5.00/M |
| Grok 4.1 Fast | https://openrouter.ai/x-ai/grok-4.1-fast | $0.20/M | $0.50/M |
| DeepSeek V4 Flash | https://openrouter.ai/deepseek/deepseek-v4-flash | $0.14/M | $0.28/M |
| Qwen 3.6 Plus | https://openrouter.ai/qwen/qwen3.6-plus | $0.325/M | $1.95/M |
| GPT 5.4-mini | https://openrouter.ai/openai/gpt-5.4-mini | $0.75/M | $4.50/M |

## Recommendation

Primary non-Claude replacement: `grok41fast`.

Reasons:

- Top hot-path score, tied with Qwen.
- Much lower latency than Qwen in the same hot-path run.
- Clean on all blocker-style checks.
- Clean on plot architect in the partial full-role pass.
- Current OpenRouter listed pricing is materially lower than Haiku 4.5.

Secondary candidate: `deepseek`.

Reasons:

- Nearly tied hot-path score.
- Good latency profile outside the plot-only run.
- Very low listed output price.
- Clean plot-only score, though slower than Grok/GPT mini.

Do not promote yet:

- `qwen`: strong structured scores, but too slow in hot-path roles and stalled
  on `plot_architect`.
- `glm`: promising in some quick checks, but stalled on planning and showed
  null-content/length warning behavior.
- `gpt54_mini`: very fast and clean on blocker checks, but did not improve
  continuity over Haiku in the stub and is close to Haiku pricing.

## Proposed Config Direction

If we want to move off Claude for the Haiku roles now, the conservative first
config to test is:

- `chapter_gate_critic`: `grok41fast`
- `continuity_extractor`: `grok41fast`
- `presence_checker`: `grok41fast`
- `final_gate`: `grok41fast`
- `micro_repair`: `grok41fast`
- `plot_architect`: `grok41fast`

The next validation step should be a Chapter 1 pipeline run with only these
Haiku-role swaps, leaving the drafter decision independent.

## Caveats

- The continuity extractor eval set is still the tiny synthetic stub in
  `tests/data/continuity_eval_set.json`; it is useful for smoke testing, not
  production-grade precision/recall.
- Chapter gate critic is scored for valid structured shape only; there is no
  labeled chapter-level gold set yet.
- Pricing is a snapshot from OpenRouter pages and can change.
