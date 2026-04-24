# Haiku 4.5 Replacement Benchmark

Generated: 2026-04-24T04:43:24.624665+00:00
Base config: `config\settings.yaml`

Scores are role-specific smoke/eval scores in [0, 1]. They measure
structured reliability, conservative false-positive behavior, exact-span
repair safety, and schema compliance. This is not a prose-quality bench.

## Overall

| Model alias | Model id | Avg score | Calls | Latency sec | Errors |
| --- | --- | ---: | ---: | ---: | ---: |
| grok41fast | `x-ai/grok-4.1-fast` | 0.8994 | 16 | 143.222 | 0 |
| deepseek | `deepseek/deepseek-v4-flash` | 0.8731 | 16 | 120.033 | 0 |

## By Role

### gate_critic

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| grok41fast | 1.0000 | 3 | 66.005 | 0 |
| deepseek | 0.6667 | 3 | 54.239 | 0 |

### continuity_extractor

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| deepseek | 0.4450 | 2 | 5.334 | 0 |
| grok41fast | 0.2958 | 2 | 10.418 | 0 |

### presence_checker

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| grok41fast | 1.0000 | 3 | 5.704 | 0 |
| deepseek | 1.0000 | 3 | 2.979 | 0 |

### final_gate

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| grok41fast | 1.0000 | 3 | 16.550 | 0 |
| deepseek | 1.0000 | 3 | 6.801 | 0 |

### micro_repair

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| grok41fast | 1.0000 | 2 | 6.839 | 0 |
| deepseek | 1.0000 | 2 | 3.546 | 0 |

### chapter_gate_critic

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| grok41fast | 1.0000 | 1 | 7.981 | 0 |
| deepseek | 1.0000 | 1 | 5.160 | 0 |

### plot_architect

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| grok41fast | 1.0000 | 2 | 29.725 | 0 |
| deepseek | 1.0000 | 2 | 41.974 | 0 |

## Notes

- The continuity extractor corpus is still the small synthetic stub in
  `tests/data/continuity_eval_set.json`; do not treat continuity precision
  as production evidence until the human-labeled Ruusan corpus exists.
- Chapter gate critic is scored for structured response shape only in this
  harness because there is not yet a labeled chapter-level gold set.
- A model that ties Haiku on score but runs slower or emits more errors is
  not a good replacement for these roles.
