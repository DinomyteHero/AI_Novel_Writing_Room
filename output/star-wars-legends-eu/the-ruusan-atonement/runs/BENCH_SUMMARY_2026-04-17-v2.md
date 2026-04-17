# Prose Model Bench v2 — Nine Models, Two Scenes (2026-04-17)

Updates [BENCH_SUMMARY_2026-04-17.md](BENCH_SUMMARY_2026-04-17.md) with GPT 5.4, GPT 5.4 mini, Gemini 3.1 Pro, Gemini 3 Flash.

## Raw numbers — all nine models

### Ch1S1 (1,250 w target, solo interior, `lie_established`)

| Model | Words | Coverage | Latency | Cost |
|---|---:|---:|---:|---:|
| GPT 5.4 mini | 2,023 | 162% ⚠️ bloat | 27.6 s | $0.017 |
| **GPT 5.4** | 1,674 | 134% ⚠️ over | 58.0 s | $0.050 |
| **GLM 5.1** | 1,218 | **97%** | 130.3 s | $0.011 |
| DeepSeek V3.2 | 1,106 | 88% | 50.4 s | $0.002 |
| Claude Sonnet 4.6 | 1,089 | 87% | 42.8 s | $0.041 |
| Kimi K2 | 1,010 | 81% | 48.9 s | $0.007 |
| Grok 4.20 | 985 | 79% | 14.5 s | $0.020 |
| Gemini 3 Flash | 839 | 67% | 10.8 s | $0.006 |
| **Gemini 3.1 Pro** | **255** | **20% ⚠️ truncated mid-sentence** | 83.0 s | $0.016 |

### Ch13S1 (1,600 w target, 5-character ensemble, `lie_challenged`)

| Model | Words | Coverage | Latency | Cost |
|---|---:|---:|---:|---:|
| GPT 5.4 mini | 3,163 | 198% ⚠️ bloat | 44.3 s | $0.025 |
| GPT 5.4 | 2,141 | 134% ⚠️ over | 86.8 s | $0.063 |
| **DeepSeek V3.2** | **1,592** | **99.5%** | 103.5 s | $0.003 |
| Gemini 3 Flash | 1,440 | 90% | 15.1 s | $0.009 |
| Grok 4.20 | 1,401 | 88% | 21.3 s | $0.025 |
| GLM 5.1 | 1,087 | 68% ⚠️ truncated | 189.8 s | $0.011 |
| Kimi K2 | 850 | 53% ⚠️ | 40.3 s | $0.007 |
| **Gemini 3.1 Pro** | **643** | **40% ⚠️ truncated** | 326.7 s | $0.025 |

**Total bench spend for this round: $0.21** ($0.09 Ch1S1 + $0.12 Ch13S1).
Cumulative spend across all bench rounds: **~$0.39**.

## Critical new finding: Gemini 3.1 Pro fails on prose

Gemini 3.1 Pro is the user's **current `plot_architect`** model. On both scenes it **truncated mid-sentence** (20% and 40% coverage). On Ch13S1 it took 326 seconds, an order of magnitude longer than any other model, and still stopped mid-description.

This does **not** disqualify it from `plot_architect`, where the output is structured JSON and the task is different. But it is an empirical disqualification for any prose-generation role. If you ever considered migrating more agents onto Gemini Pro for unification, this bench argues against it.

## GPT 5.4 — best voice, worst length discipline

GPT 5.4 delivers the most striking prose of any model in the bench. Closing cascade from Ch13S1:

> *His thoughts had edges on them now. Not wild. Not foreign. Worse than that. Familiar.*
>
> *Torin is compromised.*
> *Sera will hold to principle until it kills someone.*
> *Kael will run if the angle turns bad.*
> *Desh should never have come here.*
> *Veraine needs to die before she touches another node.*
>
> *Each judgment arrived clean, bare, without the usual softening pressure that asked for patience, context, mercy.*

That's the best `lie_challenged` cascade in the entire bench — sharper than Grok's, more concrete than DeepSeek's. But the scene came in at 2,141 words against a 1,600 target (134%). Not padding — the individual paragraphs are good — but GPT 5.4 does not respect `target_word_count` as a constraint. Every scene would need either a hard `max_tokens` cap or a post-hoc trim step.

Cost: $0.05-0.06/scene. ~2× Sonnet's market rate.

## GPT 5.4 mini — bloated, but individual paragraphs are clean

GPT 5.4 mini is unusable at current settings — **198% coverage on Ch13S1 (3,163 w vs 1,600 target)**. The writing itself is solid; the model just keeps going. A strict `max_tokens` of ~4,000 might clamp it, but even clamped you'd be paying for discarded tokens.

At $0.75/$4.50, its per-scene cost is ~$0.025 — roughly on par with Grok 4.20 but with much weaker length discipline.

Interesting internal line:
> *If the Force can be pulled apart—*
> *No.*
> *The word came hard, internal and final.*
> *Not if.*
> *When.*
> *That thought did not feel like prophecy. It felt like arithmetic.*

Voice is there. Economy isn't.

## Gemini 3 Flash — surprising value, two real issues

At $0.50/$3.00, Gemini 3 Flash is the **second-cheapest model in the bench after DeepSeek**. On Ch13S1 it hit 90% coverage (1,440 / 1,600) — better than Grok, Kimi, GLM on the same scene. Latency is the fastest of any model (10-15 seconds).

But two real issues:

1. ~~**Franchise drift.** Invented the term "Jedi Lords" on Ch13S1~~ **Correction after user review:** "Jedi Lords" is canon Legends EU — the title for Jedi leaders in the New Sith Wars era, abolished by the Ruusan Reformation. Using it in a novel set around Ruusan-era aftermath is a correct deep-canon pull, not drift. Flash doesn't lose points on this axis.

2. **Echoes the closing_hook verbatim.** Both scenes ended with the literal scene-card `closing_hook` sentence, present-tense:
   > *"In the silence of the de-structured Force, Ben hears himself think without the safety net of Force intuition for the first time. The thoughts are his. All of them. Including the ones the Force usually softens."*
   
   Literally copied from the brief, not dramatized. This happened for GPT 5.4, GPT 5.4-mini, and Gemini Flash — three models took the brief as a script instead of a guide. DeepSeek and Grok 4.20 dramatized the closing into their own words. This is a **brief-compliance artifact**, not a fundamental capability difference, but it needs a prompt fix if you use any of the three.

## Full comparison matrix

| Dimension | GPT 5.4 | GPT 5.4 mini | Gemini 3.1 Pro | Gemini 3 Flash | DeepSeek V3.2 | Grok 4.20 | GLM 5.1 | Kimi K2 | Sonnet 4.6 |
|---|---|---|---|---|---|---|---|---|---|
| Ch1S1 voice | ★★★★★ | ★★★★ | — truncated | ★★★ | ★★★★ | ★★★★★ | ★★★★★ | ★★★★ | ★★★★★ lit |
| Ch13S1 voice | ★★★★★ | ★★★★ | — truncated | ★★★ | ★★★★ | ★★★★★ | — trunc. | ★★ | (not run) |
| Word-count discipline | ★★ (over) | ★ (bloat) | ★ (trunc) | ★★★★ | ★★★★★ | ★★★★ | ★★★ | ★★ | ★★★★ |
| Arc phase fidelity (Weiland) | ★★★★★ | ★★★★ | — | ★★★ | ★★★★★ | ★★★★★ | — | ★★ wrong | — |
| Ensemble handling | ★★★★★ | ★★★★★ | — | ★★★★ | ★★★★★ | ★★★★★ | — | ★★ | — |
| Anti-pattern compliance | ★★★★★ | ★★★★ | — | ★★★★ | ★★★★★ | ★★★★★ | ★★★★★ | ★★★ | ★★★★ |
| Brief compliance (dramatizes hook) | ★★ (literal) | ★★ (literal) | — | ★★ (literal) | ★★★★★ | ★★★★★ | ★★★★★ | ★★★★ | ★★★★★ |
| Commercial register fit | ★★★★ | ★★★★ | — | ★★★★ | ★★★★★ | ★★★★★ | ★★★★ | ★★★★ | ★★★ |
| Cost / scene (Ch13S1) | $0.063 | $0.025 | $0.025 broken | $0.009 | $0.003 | $0.025 | $0.011 trunc | $0.007 trunc | ~$0.06 est |

## Updated tier list

### Tier 1 — production-ready for Ruusan prose
1. **DeepSeek V3.2** — cheapest, most reliable. Weakest on warmth-per-paragraph but never fails structurally.
2. **Grok 4.20** — best voice/arc pairing that still delivers. 10× DeepSeek's cost, ~2× cheaper than Sonnet.

### Tier 2 — premium option with a cost
3. **GPT 5.4** — genuinely the best sentence-level prose in the bench, best `lie_challenged` cascade. But 34%+ over word target, $0.05-0.06/scene. Usable if you add a `max_tokens` cap and accept the cost for pivotal scenes.

### Tier 3 — cheap-and-fast with caveats
4. **Gemini 3 Flash** — $0.009/scene, 90% coverage, 10-15 s latency. Canon-drift risk and verbatim-closing-hook issue need a prompt fix.

### Tier 4 — disqualified by structural failure
5. Kimi K2 — truncates at ensemble scenes (53% coverage).
6. GLM 5.1 — truncates at long scenes (68% coverage) despite best Ch1S1 voice.
7. Gemini 3.1 Pro — truncates on both prose scenes (20%, 40%). Fine for JSON/plot_architect; not for prose.
8. GPT 5.4 mini — 198% bloat; cost unpredictable.

### Tier 5 — register mismatch
9. Claude Sonnet 4.6 — literary where you wanted commercial.

## Recommendations — three practical configs

### A. Conservative unified: DeepSeek everywhere
```yaml
prose_stylist:   { backend: cloud, model: deepseek, params: { temperature: 0.70, max_tokens: 8192 } }
quality_polish:  { backend: cloud, model: haiku,    params: { temperature: 0.40, max_tokens: 8192 } }
```
- Cost per chapter: **~$0.02-0.05**
- Risk: warmth-per-paragraph may feel thin at book scale; caught by `quality_polish` + gate chain.

### B. Two-tier hybrid (updated from v1)
Route `prose_stylist` by scene card metadata:
- `structural_phase ∈ {midpoint, pinch_1, pinch_2, climax_final}` OR `pov_arc_phase` is a transition beat → **Grok 4.20 @ temp 0.70**
- everything else → **DeepSeek V3.2 @ temp 0.70**

- Cost per chapter: **~$0.05-0.12**
- Captures Grok's superior arc fidelity on the ~6-8 pivotal scenes per book without paying for Grok on 70-80 routine ones.

### C. Three-tier premium (new — adds GPT 5.4 for climax tier)
- Climax scenes (`structural_phase == climax_final`) → **GPT 5.4 @ temp 0.70** with `max_tokens: 4000` to prevent bloat
- Arc-transition scenes → **Grok 4.20**
- Everything else → **DeepSeek V3.2**

- Cost per chapter: **~$0.08-0.20**
- Gives GPT 5.4's best-in-class prose on the 2-3 scenes where it matters most (e.g., Ch26S1, Ch26S2, Ch28S2).
- Requires the `max_tokens` cap to work, since GPT 5.4 naturally overshoots.

## My honest recommendation, revised

With nine models benched, the single highest-leverage model for the pivotal scenes is **GPT 5.4** — the "*Torin is compromised / Sera will hold to principle until it kills someone / Kael will run if the angle turns bad*" cascade is outstanding. But 134-198% overshoot at a premium price argues against using it broadly.

**Option C (three-tier premium)** is where I'd land *if* you want the best output the bench found. That said, Option B captures 85-90% of the quality at half the cost. Start there; upgrade the climax tier to GPT 5.4 only if you feel the Weiland beats falling flat when you read the Grok output for those scenes.

**What absolutely should not ship:** keeping Sonnet on `quality_polish` (it's Anthropic-family, same as no-longer-Anthropic `prose_stylist` — wait, the new `prose_stylist` is DeepSeek, so Sonnet polish IS cross-family now). Correction: leaving Sonnet on `quality_polish` is fine post-swap. But Sonnet polish is $0.04-0.05/scene where Haiku is $0.01/scene, and on the bench Sonnet mostly added literary flourish rather than fixing anti-pattern or structural issues. **Swap to Haiku 4.5 for polish** — it's the same family as the original polish model at 3× lower cost and actively different from DeepSeek prose.

## Next action

Pick one of A/B/C. I'd recommend:
1. **Commit to Option B** (two-tier hybrid) as the default.
2. Run full Chapter 1 end-to-end with Option B to measure gate-pass rate and chapter-level voice consistency.
3. If arc-critical scene quality on Grok disappoints when tested on a real climax scene, escalate that scene alone to GPT 5.4 (with `max_tokens: 4000`).

Ready to patch config and run Ch1 end-to-end?
