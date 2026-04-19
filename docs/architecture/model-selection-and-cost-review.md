# Model Selection & Cost Review — 2026-04-17

> **Update 2026-04-19:** The `kimi` alias in [config/settings.yaml](../../config/settings.yaml) now points at `moonshotai/kimi-k2.5` (released 2026-01-27, $0.38/$1.72 per M in/out). Historical analysis below references Kimi K2-Instruct (`moonshotai/kimi-k2`), which previously tested better for *prose drafting* than K2.5. The live config only uses `kimi` for `manuscript_reviewer` (a review role, not a drafter), so the prose-quality concern does not apply to the production routing. If a future Kimi-as-drafter experiment is run, re-bench K2.5 against K2-Instruct first.

> **Relay v3 addendum (2026-04-19):** Two new agents joined the routing table:
> - `presence_checker` — Haiku 4.5 @ t=0.1, binary character-presence check feeding the save-blocker layer. Cheap and precise; one call per saved scene.
> - `line_writer` — GPT 5.4 @ t=0.8, line-editing pass between drafter and gate. `max_tokens: 12000` because GPT benefits from headroom on an edit pass. Adds one LLM call per scene; skipped in `--raw-draft` mode. Expect a Stage 2 bench at 3 scenes × 2 arms ≈ $0.40 before wide rollout — the routing entry is live but the bench evidence lives separately.
>
> The gate stack is now forward-only telemetry (no rewrites), so the retry-driven cost variance documented below for Chapter 1 no longer applies — scenes take exactly one drafter call, one optional line-writer call, one gate call, one polish call, one continuity call, and one presence-checker call. Total cost per saved scene is predictable within a 10% band.

Evaluation of model routing in [config/settings.yaml](../../config/settings.yaml) in light of Ruusan Atonement's commercial-style register revision and the Chapter 1 credit burn.

Sources consulted: [OpenRouter Rankings](https://openrouter.ai/rankings) (overall + Roleplay + Marketing categories), [EQ-Bench Creative Writing v3](https://eqbench.com/creative_writing.html), [EVY aggregated benchmarks](https://evy.so/compare/best-llms-for-writing/), and multi-agent critique research from [Multi-Agent LLM Systems](https://www.emergentmind.com/topics/multi-agent-large-language-model-llm) / [arxiv 2603.19282](https://arxiv.org/abs/2603.19282).

---

## 1. Current setup — where the money goes

Routing lives at [config/settings.yaml:68-99](../../config/settings.yaml). The agents that dominate Chapter 1 spend:

| Agent | Model (current) | Temp | Cost /M in | Cost /M out | Role weight |
|---|---|---|---|---|---|
| **prose_stylist** | `anthropic/claude-sonnet-4.6` | 0.80 | $3.00 | **$15.00** | 1 call per scene, up to **6× under max retries** |
| **quality_polish** | `anthropic/claude-sonnet-4.6` | 0.5 | $3.00 | **$15.00** | 1 call per scene |
| plot_architect | `google/gemini-3.1-pro-preview` | 0.4 | $2.00 | $12.00 | 1 call per scene |
| gate_critic | `anthropic/claude-haiku-4.5` | 0.3 | $1.00 | $5.00 | 1–6 calls per scene |
| final_gate | `anthropic/claude-haiku-4.5` | 0.2 | $1.00 | $5.00 | 1 call per scene |
| chapter_gate_critic | `anthropic/claude-haiku-4.5` | 0.3 | $1.00 | $5.00 | 1 per chapter |
| judge_evaluator | `x-ai/grok-4.20` | 0.2 | $2.00 | $6.00 | 1 per scene (Phase 4) |
| canon_expert | `x-ai/grok-4.20` | 0.2 | $2.00 | $6.00 | pre-gate + on rewrites |
| summarizer / character_specialist / lore_extractor | `deepseek/deepseek-v3.2` | 0.2-0.3 | $0.26 | $0.38 | utility |

Retry loop at [src/orchestrator.py:982-1149](../../src/orchestrator.py:982): `max_structural_retries=3`, `max_voice_retries=2`. Each structural failure rebuilds prose (`prose_stylist`) + re-runs the gate. Worst case is 5 Sonnet calls for one scene.

**Rough per-scene cost today** (best case, ≈2.5k in / 3k out): `prose_stylist ≈ $0.053` + `quality_polish ≈ $0.056` + plot + gates + judge ≈ **$0.15–0.20 per scene**. A retry-heavy scene doubles that. The prose_stylist + quality_polish pair contributes ~65% of the Sonnet-driven cost — they are the only levers worth pulling.

**Cross-family audit:** `prose_stylist → quality_polish → gate_critic → final_gate` are **all Anthropic** today. That's the first thing to fix even before the cost question — you are effectively getting one family's taste marking its own homework.

---

## 2. Quality evidence from independent benchmarks

### EQ-Bench Creative Writing v3 (Elo, Sonnet 4.6 judge — noted bias)

| Model | Elo | Slop ↓ | Repetition ↓ | Rubric | Notes |
|---|---|---|---|---|---|
| gpt-5.4 | **1991.7** | 1.7 | 2.7 | 84.45 | Not on OpenRouter mainline |
| claude-sonnet-4.6 | 1937.7 | **1.4** | 4.1 | 82.50 | Current prose model |
| claude-opus-4.6 | 1911.3 | 1.7 | 4.0 | — | |
| claude-sonnet-4.5 | 1750.1 | 2.2 | 3.6 | 80.70 | |
| **Kimi-K2-Instruct** | **1709.8** | 2.2 | 3.4 | 82.00 | Strong mid-tier |
| grok-4.20-beta | 1645.5 | **2.2** | 4.5 | 72.55 | Current judge |
| GLM-5 | 1626.9 | 2.6 | 3.5 | 80.45 | |
| GLM-5.1 | 1601.8 | 3.3 | 3.8 | 81.30 | Slop regression vs 5 |
| **DeepSeek-V3.2** | 1486.3 | 3.2 | 4.1 | **81.40** | Top roleplay-share model |
| gemini-3-pro-preview | 1472.3 | 3.4 | 4.5 | 81.50 | |
| gemini-3.1-pro-preview | 1467.4 | **4.2** | 4.5 | 80.20 | Regression vs 3-pro; explains Ruusan "fancy" tone |
| DeepSeek-V3.1 | 1379.1 | 3.9 | 4.4 | 80.50 | |

Judge-bias caveat: Sonnet 4.6 being the judge probably inflates Anthropic scores by ~50-100 Elo. Treat the gap between Sonnet 4.6 and Kimi K2-Instruct (≈230 pts) as closer to ≈130-180 pts in reality.

### OpenRouter market signal (what paying users actually pick for creative)

Roleplay category (1.18T tokens over the window):

| Rank | Model | Share |
|---|---|---|
| 1 | **DeepSeek V3.2** | **38.1%** |
| 2 | gpt-oss-120b | 6.8% |
| 3 | Grok 4.1 Fast | 6.4% |
| 4 | Gemini 2.5 Flash Lite | 5.4% |
| 5 | Gemini 3 Flash Preview | 3.9% |
| 6–9 | Hunter Alpha, Step 3.5 Flash, GLM 5, DeepSeek V3 0324 | 1.8–2.5% |

Marketing (commercial-style short form) category:

| Rank | Model | Share |
|---|---|---|
| 1 | Gemini 2.5 Flash Lite | 22.1% |
| 2 | Grok 4.1 Fast | 14.7% |
| 3 | gpt-oss-120b | 12.6% |
| 4 | Gemini 2.5 Flash | 7.4% |
| 5 | Gemini 3 Flash Preview | 5.5% |
| 6 | Claude Haiku 4.5 | 4.1% |
| 7 | Claude Sonnet 4.6 | 3.2% |

Key reading: **DeepSeek V3.2 has displaced Claude for long-form creative** at market scale, and **Gemini Flash variants own the short commercial register** you revised Ruusan toward.

### Third-party commentary (important caveats)

- **DeepSeek V3.2** — "concise, image-rich English, favoring stoic narrative arcs and tight two-beat lyricism…unmatched price-performance" ([EVY benchmarks](https://evy.so/compare/best-llms-for-writing/)), but users report **tendency toward cliché** and **post-Feb-2026 updates made prose choppier/more robotic** ([DeepSeek issue #538](https://github.com/deepseek-ai/awesome-deepseek-integration/issues/538)). Matches commercial-thriller register, not literary.
- **Kimi K2** — "sharp under 300 words; wheels come off over 3,000 words" ([Adam Holter review](https://adam.holter.com/kimi-k2-thinking-aftermath-great-agent-mediocre-writer/)). Relevant because scene cards often hit 2,500-3,000 word targets. K2-Instruct tests better than K2-Thinking or K2.5 for prose.
- **Gemini 3.1 Pro Preview** scored **worse than Gemini 3 Pro** on creative (1467 vs 1472, Slop 4.2 vs 3.4). The "fancy" register you had to revise off Ruusan is reflected here.
- **Grok 4.20** — low Slop (2.2), mid Rubric (72.55). Decent low-slop judge; unremarkable prose writer.

---

## 3. Multi-agent critique: does cross-family actually help?

Research is consistent but measured:

- **Diverse-family ensembles slightly outperform same-family ensembles** on critique and debate tasks, with cross-family setups offering "more diverse candidate results." Quantified gap in the studies I found: ~1-2 points on aggregate metrics, not 10.
- **The bigger win is avoiding silent agreement.** When writer and critic come from the same pre-training and RLHF lineage, they share the same blind spots. Sonnet judging Sonnet prose is the closest analogue to a self-review — well-documented as weaker than external review.
- **The Sonnet-4.6 judge bias on EQ-Bench** (≈230pt Elo advantage for Anthropic models vs Grok/GPT judges) is an empirical measurement of this same effect.
- **Independence matters most for quality/taste judgments** (polish, voice, literary register) and least for structured contract checks (word count, character presence, JSON validation). So the FinalGate can stay same-family as prose without much loss; the JudgeEvaluator and QualityPolish should be different families than the writer.

Conclusion: **cross-family is a real but small quality lift**; the **main reason to do it is cost + avoiding correlated failure modes**, not a large Elo gain.

---

## 4. Step-by-step recommendations

### Step 1 — Bench the prose swap on a single scene before changing the config

Pick one Ruusan Chapter 1 scene that already ran on Sonnet. Run it three times with `--model-override prose_stylist=<candidate>` at temperature 0.80:

- `deepseek/deepseek-v3.2`
- `moonshotai/kimi-k2.5` (at 0.7, since K2.5 is less steerable at high temp)
- `google/gemini-3-flash-preview` (reference — cheapest possible)

Feed the three outputs through the existing gate_critic + judge_evaluator pipeline and compare Elo/rubric side-by-side. **Do not change config yet.** This is the decision data.

### Step 2 — Switch prose_stylist based on bench result

Most likely winner for Ruusan's commercial tie-in register: **DeepSeek V3.2**. Expected savings: output cost drops from $15/M → $0.38/M (~**40×**). Single-scene cost drops from ≈$0.053 to ≈$0.002.

```yaml
prose_stylist: { backend: cloud, model: deepseek, params: { temperature: 0.70, max_tokens: 8192 } }
```

Note the temperature drop from 0.80 → 0.70. DeepSeek at 0.80 starts producing the choppy/robotic prose users complained about post-Feb-2026. **If DeepSeek's cliché tendency hurts voice**, fall back to Kimi K2 at 0.7:

```yaml
prose_stylist: { backend: cloud, model: kimi, params: { temperature: 0.7, max_tokens: 8192 } }  # kimi now routes to moonshotai/kimi-k2.5 — bench before committing
```

Kimi is still ~6.5× cheaper on output than Sonnet (~$2.30/M vs $15/M). Avoid Kimi for scenes targeting >3,000 words — use scene-card length to route.

### Step 3 — Break the all-Anthropic critique chain

Switch quality_polish off Claude so prose-writer and polish-editor come from different families. Two options:

**Option A (conservative, keep Claude in the chain):**
```yaml
quality_polish: { backend: cloud, model: haiku, params: { temperature: 0.4, max_tokens: 8192 } }
```
Haiku 4.5 ($1/$5) is 3× cheaper than Sonnet and gives Anthropic's instruction-following for line edits while being structurally different enough from the DeepSeek draft to catch style issues.

**Option B (aggressive, full cross-family):**
```yaml
quality_polish: { backend: cloud, model: kimi, params: { temperature: 0.3, max_tokens: 8192 } }
```
Kimi K2-Instruct at low temp is strong at sentence-level polishing, and now you have DeepSeek → Kimi → Haiku → Claude — four families touching each scene.

### Step 4 — Promote the judge to a true cross-family reviewer

The JudgeEvaluator currently uses Grok 4.20 — fine, but Grok is also the CanonExpert and WorldbuildingCoherenceReviewer, so the same family is scoring three different rubrics. Split them:

```yaml
judge_evaluator:   { backend: cloud, model: claude, params: { temperature: 0.2, max_tokens: 4096 } }  # was grok420
canon_expert:      { backend: cloud, model: grok420, params: { temperature: 0.2 } }                   # unchanged
```

Rationale: the judge is a one-shot-per-scene holistic scorer — giving it to Sonnet 4.6 costs only $0.03-0.05 per scene and provides the best external quality signal (Elo 1937 on EQ-Bench). It's also a different family from the new DeepSeek writer, so it can see slop the writer can't.

If the per-scene $0.03 adder is too much, use `claude-sonnet-4.5` (Elo 1750, cheaper on OpenRouter if available) or keep Grok and accept the correlated-judgment risk.

### Step 5 — Keep the gates cheap but add failure-aware routing

The gate_critic is called inside the retry loop (up to 6× per scene). Haiku at $1/$5 is already right-sized — don't upgrade. But add **graduated escalation** in [src/orchestrator.py](../../src/orchestrator.py):

- Attempts 1-2: `gate_critic` on Haiku (current behavior).
- Attempt 3+ (close to `max_structural_retries`): promote to **Sonnet** for one reading before accepting best-attempt. Sonnet's higher taste ceiling may reveal *why* Haiku keeps failing it, and it only fires on the tail.

This is a small code change in `_gate_loop`; gate model is already a parameter.

### Step 6 — Shrink the retry blast radius

Cheaper prose means retries hurt less, but retries also fire more often on a weaker model. Add two guardrails:

1. **Lower `max_structural_retries` from 3 → 2** for DeepSeek prose. Three retries on a $15/M model made sense; three retries on a $0.38/M model is fine for cost but hides that DeepSeek isn't fitting the scene card — you want the orchestrator to surface that faster.
2. **Log retry-driven token burn per scene in RunLedger** so the ledger makes Chapter 1's real cost visible without calculating afterward.

### Step 7 — Turn on prompt caching savings fully

[settings.yaml:109-111](../../config/settings.yaml:109) already enables 1h caching for Anthropic. After the swap, Claude is still in the chain on `quality_polish` (if you picked Option A) and `judge_evaluator`. Make sure those calls **reuse the same system prompt prefix** across scenes in a chapter so cache hits dominate — current pipeline already structures calls this way, just confirm no per-scene timestamps or UUIDs leak into the system prompt.

DeepSeek has implicit caching on OpenRouter (automatic, no API flag). Gemini Flash also. No config change needed; just batch a chapter's scenes close in time.

### Step 8 — Match agents to Brooks + Weiland structure

Since plot_architect carries the Brooks four-part beat map and character_specialist enforces Weiland arc phases, the model choice for each should reflect what that framework demands:

- **plot_architect (Brooks beats)** — structured planning, not prose. Gemini 3.1 Pro's 1M context and strong structured output make sense. Keep it, **but drop temperature from 0.4 → 0.3** — Brooks beats are template-like, creativity at the outline level is where "fancy" register leaks in.
- **character_specialist (Weiland arc_phase_map)** — this is about psychological consistency across arc phases (lie/ghost/want/need). DeepSeek V3.2 at temp 0.3 is correct here (already the config); it's factual/analytic, not creative.
- **prose_stylist** receives the Brooks beat + Weiland arc phase in its brief. The writer model doesn't need to *know* Brooks/Weiland as frameworks, only to execute the assigned beat faithfully. DeepSeek's "tight two-beat lyricism" style *maps well to Brooks' scene-level beats* — that's a genuine fit, not just a cost argument.

### Step 9 — Rollout order

1. Bench DeepSeek/Kimi/Flash on one known scene (Step 1).
2. Swap `prose_stylist` only. Rerun Chapter 1. Compare cost, gate-pass rate, and judge score vs current run.
3. Swap `quality_polish` (Step 3).
4. Swap `judge_evaluator` (Step 4).
5. Ship graduated gate escalation (Step 5) and retry-cap tightening (Step 6).
6. Re-run Chapter 1 end-to-end, compare total credits vs the baseline in your current RunLedger.

---

## 5. Edge cases & risks

| Risk | Mitigation |
|---|---|
| DeepSeek V3.2 produces cliché / "flat" prose on emotional scenes | Keep Sonnet as a fallback via CLI flag `--prose-model=claude` for identified high-stakes scenes; check scene_card `emotional_intensity` tag to auto-promote. |
| Style drift across a chapter when DeepSeek's output goes through Kimi polish | Run the existing `voice_checker` + `character_specialist` on every scene. These already exist and will catch Ruusan-voice drift. |
| DeepSeek refuses or degrades on franchise-specific terminology | CanonExpert (Grok 4.20) runs pre-gate and can auto-correct. Already wired. |
| Kimi K2 quality degrades past 3,000 words | Route long scenes (scene_card `target_word_count > 2500`) back to DeepSeek or Sonnet. One-line guard in router. |
| Sonnet judge still biases toward Anthropic prose even when scoring DeepSeek | Consider using two judges — Sonnet + Grok — and averaging. Doubles judge cost but removes the bias. Phase 4 only. |
| Gate false-reject rate rises because Haiku is now stricter than DeepSeek's style | Tune failure-code weights in `_gate_loop` if this shows up in RunLedger; don't tune by lowering the bar. |
| Prompt caching benefits shrink on DeepSeek/Gemini (implicit caching, less predictable than Anthropic's explicit API) | Accept this — the base cost drop dominates the caching delta. |
| JSON schema adherence on gate_critic degrades if swapped away from Haiku | Do not swap gates. Keep Haiku. |
| OpenRouter provider routes DeepSeek to a slow backend | Pin `deepseek/deepseek-v3.2` to a specific provider with good latency via OpenRouter provider preferences. |
| Mid-chapter model change breaks voice continuity | Never swap models mid-chapter. Changes only apply from next chapter onward. |

---

## 6. Expected outcome

If Step 1–4 land and the bench confirms DeepSeek-quality is acceptable for Ruusan's commercial register:

- **Per-scene prose + polish cost: ~$0.11 → ~$0.011 (~10×)**
- **Per-chapter (5 scenes, 1.2× avg retry): ~$0.85 → ~$0.085**
- **Cross-family independence restored on the critique chain**
- Judge score variance visible to you for the first time, because the judge is now a different family from the writer — scoring signal becomes meaningful

If the bench shows DeepSeek can't hold Ruusan's voice, fall back to Kimi K2 (still ~6× cheaper) before retreating to Sonnet. The principle — writer ≠ polish ≠ judge family — stays intact either way.
