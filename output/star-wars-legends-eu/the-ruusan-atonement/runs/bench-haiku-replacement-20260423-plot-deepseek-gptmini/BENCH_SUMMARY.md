# Haiku 4.5 Replacement Benchmark

Generated: 2026-04-24T02:25:45.371311+00:00
Base config: `config\settings.yaml`

Scores are role-specific smoke/eval scores in [0, 1]. They measure
structured reliability, conservative false-positive behavior, exact-span
repair safety, and schema compliance. This is not a prose-quality bench.

## Overall

| Model alias | Model id | Avg score | Calls | Latency sec | Errors |
| --- | --- | ---: | ---: | ---: | ---: |
| deepseek | `deepseek/deepseek-v3.2` | 1.0000 | 2 | 69.923 | 0 |
| gpt54_mini | `openai/gpt-5.4-mini` | 1.0000 | 2 | 19.495 | 0 |

## By Role

### plot_architect

| Model alias | Score | Calls | Latency sec | Errors |
| --- | ---: | ---: | ---: | ---: |
| deepseek | 1.0000 | 2 | 69.923 | 0 |
| gpt54_mini | 1.0000 | 2 | 19.495 | 0 |

## Notes

- The continuity extractor corpus is still the small synthetic stub in
  `tests/data/continuity_eval_set.json`; do not treat continuity precision
  as production evidence until the human-labeled Ruusan corpus exists.
- Chapter gate critic is scored for structured response shape only in this
  harness because there is not yet a labeled chapter-level gold set.
- A model that ties Haiku on score but runs slower or emits more errors is
  not a good replacement for these roles.
