# Bench Summary - 2026-04-23

Scene: Ch1S1, Ben Skywalker training-salle hook
Shared brief: reused from `bench-2026-04-23-nonclaude-ch01-sc01/generation_brief.json`
Target: 1250 words

## Results

| Model | Words | Target % | Cost | Time | Read |
|---|---:|---:|---:|---:|---|
| MiniMax M2.7 | 1195 | 95.6% | $0.0075 | 105.7s | Best cost/obedience balance in this run. Good scene shape, no obvious canon trap in skim. |
| Qwen 3.6 Plus | 1107 | 88.6% | $0.0091 | 87.0s | Viable. Good structure, but one color/visual flourish and a slightly awkward opening. |
| Claude Sonnet 4.6 t=0.70 | 1125 | 90.0% | $0.0780 | 37.6s | Still clean and controlled, but about 10x MiniMax cost. |
| Claude Sonnet 4.6 t=0.80 | 1080 | 86.4% | $0.0779 | 37.2s | Production baseline. Good, but used "lightsaber" in sparring context. |
| Kimi K2.6 | 1057 | 84.6% | $0.0235 | 271.9s | Usable, but slow and not clearly better than Qwen/MiniMax. |
| Grok 4.20 | 1033 | 82.6% | $0.0455 | 20.4s | Fast and readable, but not cheap enough for the quality delta. |
| Kimi K2.5 | 987 | 79.0% | $0.0095 | 216.3s | Disqualified on this scene: hallucinated Ben as twenty-five. |
| GPT-5.4 | 1607 | 128.6% | $0.0799 | 53.5s | Strong prose, but not a cost savings and overshoots target. |
| GPT-5.4-mini | 1762 | 141.0% | $0.0247 | 23.3s | Strong voice/energy, but too expansive without tighter word discipline. |
| Grok 4.1 Fast | 718 | 57.4% | $0.0042 | 16.5s | Too compressed for drafter role. Better kept for canon scout/orchestration. |
| DeepSeek V3.2 | 569 | 45.5% | $0.0051 | 11.9s | Too thin/summary-like here. |
| GLM 5.1 | 0 | 0.0% | $0.0173 | 200.7s | Null content, finish_reason=length. Not production-safe under current prompt. |
| MiMo V2.5 Pro | 0 | 0.0% | $0.0182 | 100.9s | Null content, finish_reason=length. Not production-safe under current prompt. |

## Manual Notes

MiniMax M2.7 is the strongest Claude replacement candidate from this single scene. It hit the word target, respected the core scene contract, used "training saber" consistently, and avoided the worst diagnostic/prose-register traps.

Qwen 3.6 Plus is the second-best low-cost candidate. It was close to target and structurally coherent, but the prose showed a small visual/color bleed and needed a little more canon-tuned restraint.

GPT-5.4-mini may be a useful polish model or high-stakes scene fallback. As a drafter it produced lively Ben interiority, but it overshot the target by 41%, which is risky for full-book cost and pacing.

Kimi K2.6 did not justify its higher cost and high latency versus Qwen/MiniMax on this scene. Kimi K2.5 is not viable here because it hallucinated Ben's age.

GLM 5.1 and MiMo V2.5 Pro failed the harness by returning null content after hitting length. They may be retestable with stricter prompt/output caps, but they are not drop-in replacements for the current `prose_stylist`.

## Recommendation

Next bench should be a chapter-level A/B, not another single scene:

1. MiniMax M2.7 as `prose_stylist`.
2. Qwen 3.6 Plus as `prose_stylist`.
3. Sonnet 4.6 current production baseline.

Run Chapter 1 end-to-end for all three, then compare save status, gate advisories, word-count drift, canon reports, and human read.

Tentative routing candidate:

```yaml
prose_stylist: { backend: cloud, model: minimax, params: { temperature: 0.70, max_tokens: 8192 } }
```

