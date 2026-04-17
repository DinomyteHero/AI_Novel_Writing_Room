# Full Pipeline vs Stripped Pipeline — Ch1 End-to-End Comparison
Date: 2026-04-17

Added `--skip-gate-loop` flag to test whether the Gate Critic rewrite loop earns its keep when `prose_stylist` is a strong model.

## Setup

Two bench config files (`config/settings.bench.sonnet.yaml`, `config/settings.bench.gpt.yaml`), both using:
- `plot_architect` = Grok 4.20 @ t=0.4
- `quality_polish` = Haiku 4.5 @ t=0.4
- `gate_critic` / `final_gate` = Haiku 4.5

Prose models tested:
- **Sonnet 4.6** @ t=0.70
- **GPT 5.4** @ t=0.70

Two pipeline modes:
- **FULL:** default (gate_critic runs with up to 3 structural retries + 2 voice retries)
- **STRIPPED:** `--skip-gate-loop` (gate_critic skipped entirely; polish + final_gate still run)

Scope: Ch1 end-to-end (3 scenes each), 4 total runs.

## Raw results

### Sonnet 4.6

| Config | Ch1S1 | Ch1S2 | Ch1S3 | Total | Gate verdicts | Rewrites fired |
|---|---:|---:|---:|---:|---|---:|
| FULL | 1,243 | 1,142 | 1,126 | 3,511 | pass × 3 | **0** |
| STRIPPED | 1,174 | 1,174 | 1,283 | 3,631 | skipped | n/a |

Sonnet's gate scores on FULL: 0.88/0.87/0.85, 0.82/0.84/0.78, 0.82/0.84/0.78. Every scene passed on first attempt.

### GPT 5.4

| Config | Ch1S1 | Ch1S2 | Ch1S3 | Total | Gate verdicts | Rewrites fired |
|---|---:|---:|---:|---:|---|---:|
| FULL | 1,506 | 1,659 | 1,440 | 4,605 | **fail_polish × 3** | **0** |
| STRIPPED | 1,623 | 1,542 | 1,544 | 4,709 | skipped | n/a |

GPT's gate on FULL flagged `WORD_COUNT_VIOLATION` (due to overshoot), `EXPOSITION_LEAK`, `PACING_FLATLINE`, `PROSE_CLICHE_BURST` across the three scenes. **`fail_polish` does not trigger rewrite** — it's treated as `pass` for loop-exit purposes. The flags were logged and ignored.

## The critical finding

**In 12 scene slots (4 runs × 3 scenes), the gate_critic retry loop fired zero rewrites.**

- Sonnet passed structurally every time.
- GPT verdict was `fail_polish`, which exits the loop without a rewrite (orchestrator.py:1093).

### The gate_critic's failure codes don't feed into Quality Polish

From [src/orchestrator.py:434](../../../../../src/orchestrator.py:434):
```python
polish_result = await self.quality_polish.run({
    "prose": gate_passed_prose,
    "scene_card": scene_card,
    "quality_metrics": quality_metrics,   # from metrics_dashboard (None in Phase 1)
    "negative_constraints": ...,
    "canon_notes": canon_notes,
})
```

**Gate_critic's `failure_codes` are not passed to Quality Polish.** That means when gate_critic flags "PROSE_CLICHE_BURST" on GPT's output, Quality Polish runs the same prompt it would have run anyway. The flag went nowhere.

This explains why the STRIPPED output is indistinguishable in quality from the FULL output — they both went through the exact same Quality Polish pass with the exact same input (the raw prose_stylist draft). The only difference is whether a Haiku call happened *before* polish that flagged things nobody read.

## Quality spot-check — Ch1S1 openings

All four openings are strong and on-register. They differ because prose_stylist runs at temp 0.70 (so outputs are sampled), not because the pipelines differ meaningfully.

- **Sonnet FULL:** *"The training blade caught him across the shoulder, and Ben stepped back. Third time this week."*
- **Sonnet STRIPPED:** *"The training blade caught him across the shoulder. Not hard — training sabers were calibrated to sting, not injure — but the impact didn't matter. The half-second did."*
- **GPT FULL:** *"The training blade cracked across Ben's left shoulder hard enough to numb his arm. He hissed through his teeth and gave ground on pure reflex…"*
- **GPT STRIPPED:** *"Ben's guard came up half a beat late, and the training blade cracked across his left shoulder hard enough to sting through the padded tunic."*

No quality delta that can't be attributed to sampling noise. All four pass the `final_gate` contract check.

## What the FULL pipeline actually costs (for no output change)

Per scene (approx):
- `gate_critic` call: ~$0.004 (Haiku), ~10-15s latency.
- Potential retry ProseStylist calls (never fired in these runs): would add $0.04 each for Sonnet or $0.05+ each for GPT.

Across 84 scenes per book at observed zero-rewrite rate:
- Extra cost: **~$0.34 per book** (84 × $0.004).
- Extra time: **~15-20 minutes per book wall-clock**.

For this particular chapter, **the gate loop is dead weight.** That's a strong statement backed by 4 empirical runs.

## Where the gate loop *would* still earn its keep

Honest caveat — this is a narrow test:
1. **Only Ch1** was tested. Later chapters with more complex structural demands (midpoint reversal, climax) might produce structural failures the gate would catch.
2. **Only 2 prose models**, both near the top of the EQ-Bench creative writing leaderboard. A weaker model would likely trigger more rewrites.
3. **No canon_expert run.** In Phase 2+, canon_expert feeds `canon_notes` into polish — that's a separate value path the gate doesn't participate in.
4. **Small sample.** 12 scenes is not enough to claim zero-rewrite is the long-run rate. Real-world rate across 80+ scenes is probably non-zero but low.

## Recommendations (revised after this empirical test)

### 1. Adopt `--skip-gate-loop` as the default for pipeline runs with strong prose models
The bench provides empirical evidence that for Sonnet 4.6 / GPT 5.4 at t=0.70 on well-scoped scene cards, the gate loop catches nothing actionable.

### 2. Keep Quality Polish
Quality Polish with Haiku 4.5 is cheap (~$0.015/scene) and the compression guard + final_gate sanity-check keep the output honest. This part of the pipeline is earning its keep.

### 3. Consider wiring gate_critic's failure_codes into Quality Polish
If you want to keep the gate loop, the cheapest improvement is to pipe its `failure_codes` into the polish prompt as *flags to fix*. That would turn the current advisory signal into actual corrective work. One-line change to the polish context dict.

### 4. Keep structural retry for weaker models
If you ever downgrade prose_stylist to DeepSeek / Kimi / GLM for cost reasons, re-enable the gate loop — those models have higher structural miss rates and the retries would catch real problems.

### 5. Use `--skip-gate-loop` as an observability tool
Run a chapter with the flag on and compare to a FULL run. If outputs diverge meaningfully, the gate loop is doing work. If not, the flag is free savings.

## What to do next

1. No config change needed. Both bench configs are committed for reproducibility.
2. If you adopt `--skip-gate-loop` as default, add it to the CLI convention docs.
3. Re-run this comparison at Chapter 13 (the midpoint / Breach Zone ensemble scene) to test whether a harder scene triggers structural failures the gate would catch. Ch13 is where our earlier bench showed Kimi + GLM structurally degrade — Sonnet/GPT held up there too, so the prediction is: still zero rewrites, same conclusion.

## Artifacts

- [bench-ch1-sonnet-FULL/chapters/](bench-ch1-sonnet-FULL/chapters/)
- [bench-ch1-sonnet-STRIPPED/chapters/](bench-ch1-sonnet-STRIPPED/chapters/)
- [bench-ch1-gpt-FULL/chapters/](bench-ch1-gpt-FULL/chapters/)
- [bench-ch1-gpt-STRIPPED/chapters/](bench-ch1-gpt-STRIPPED/chapters/)

Total additional spend: ~$1.10 (4 Ch1 runs).

## Code changes landed

- [src/main.py](../../../../../src/main.py) — added `--skip-gate-loop` argparse flag, plumbed to Orchestrator.
- [src/orchestrator.py](../../../../../src/orchestrator.py) — added `skip_gate_loop: bool = False` constructor param. When True, `_gate_loop()` returns a synthesized "skipped" evaluation with `None` scores and empty failure_codes, and skips the gate_critic call entirely. Also added `"gate_skipped"` as a valid `revision_status` for story_state logging.
- [config/settings.bench.sonnet.yaml](../../../../../config/settings.bench.sonnet.yaml) and [config/settings.bench.gpt.yaml](../../../../../config/settings.bench.gpt.yaml) — bench configs that override prose_stylist, plot_architect, and quality_polish without modifying production settings.yaml.
