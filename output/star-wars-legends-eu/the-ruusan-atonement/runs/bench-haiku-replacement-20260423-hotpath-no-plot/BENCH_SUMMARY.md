# Haiku 4.5 Replacement Benchmark

Generated: 2026-04-24T02:17:29.398307+00:00
Base config: `config\settings.yaml`

Scores are role-specific smoke/eval scores in [0, 1]. They measure
structured reliability, conservative false-positive behavior, exact-span
repair safety, and schema compliance. This is not a prose-quality bench.

## Overall

| Model alias | Model id | Avg score | Calls | Latency sec | Errors |
| --- | --- | ---: | ---: | ---: | ---: |
| grok41fast | `x-ai/grok-4.1-fast` | 0.9183 | 11 | 38.994 | 0 |
| qwen | `qwen/qwen3.6-plus` | 0.9183 | 11 | 280.306 | 0 |
| deepseek | `deepseek/deepseek-v3.2` | 0.9000 | 11 | 56.888 | 0 |
| haiku | `anthropic/claude-haiku-4.5` | 0.8500 | 11 | 31.385 | 0 |
| gpt54_mini | `openai/gpt-5.4-mini` | 0.8500 | 11 | 15.241 | 0 |

## By Role

### continuity_extractor

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| grok41fast | 0.5917 | 2 | 11.247 | 0 |
| qwen | 0.5917 | 2 | 69.103 | 0 |
| deepseek | 0.5000 | 2 | 10.878 | 0 |
| haiku | 0.2500 | 2 | 2.819 | 0 |
| gpt54_mini | 0.2500 | 2 | 2.280 | 0 |

### presence_checker

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| haiku | 1.0000 | 3 | 2.127 | 0 |
| grok41fast | 1.0000 | 3 | 5.488 | 0 |
| qwen | 1.0000 | 3 | 44.658 | 0 |
| deepseek | 1.0000 | 3 | 7.893 | 0 |
| gpt54_mini | 1.0000 | 3 | 5.101 | 0 |

### final_gate

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| haiku | 1.0000 | 3 | 5.172 | 0 |
| grok41fast | 1.0000 | 3 | 11.819 | 0 |
| qwen | 1.0000 | 3 | 88.443 | 0 |
| deepseek | 1.0000 | 3 | 20.552 | 0 |
| gpt54_mini | 1.0000 | 3 | 4.471 | 0 |

### micro_repair

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| haiku | 1.0000 | 2 | 3.533 | 0 |
| grok41fast | 1.0000 | 2 | 5.915 | 0 |
| qwen | 1.0000 | 2 | 46.322 | 0 |
| deepseek | 1.0000 | 2 | 4.190 | 0 |
| gpt54_mini | 1.0000 | 2 | 1.597 | 0 |

### chapter_gate_critic

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| haiku | 1.0000 | 1 | 17.734 | 0 |
| grok41fast | 1.0000 | 1 | 4.525 | 0 |
| qwen | 1.0000 | 1 | 31.780 | 0 |
| deepseek | 1.0000 | 1 | 13.375 | 0 |
| gpt54_mini | 1.0000 | 1 | 1.792 | 0 |

## Notes

- The continuity extractor corpus is still the small synthetic stub in
  `tests/data/continuity_eval_set.json`; do not treat continuity precision
  as production evidence until the human-labeled Ruusan corpus exists.
- Chapter gate critic is scored for structured response shape only in this
  harness because there is not yet a labeled chapter-level gold set.
- A model that ties Haiku on score but runs slower or emits more errors is
  not a good replacement for these roles.
