# Prose Model Bench v3 — Sonnet at t=0.70 added (2026-04-17)

Updates [BENCH_SUMMARY_2026-04-17-v2.md](BENCH_SUMMARY_2026-04-17-v2.md). The earlier Sonnet data was at t=0.80 (current production config). Running Sonnet at t=0.70 to match every other bench config meaningfully changes the picture.

## New raw numbers

| Scene | Config | Words | Coverage | Latency | Cost |
|---|---|---:|---:|---:|---:|
| Ch1S1 (1,250 w target) | Sonnet 4.6 @ t=0.80 | 1,089 | 87% | 42.8 s | $0.041 |
| Ch1S1 | **Sonnet 4.6 @ t=0.70** | **1,009** | 81% | 37.7 s | $0.039 |
| Ch13S1 (1,600 w target) | **Sonnet 4.6 @ t=0.70** | **1,535** | **96%** | 59.4 s | $0.053 |

For comparison on Ch13S1:
- DeepSeek V3.2: 1,592 w (99.5%), $0.003
- Sonnet 4.6 @ t=0.70: 1,535 w (96%), $0.053
- Grok 4.20: 1,401 w (88%), $0.025
- GPT 5.4: 2,141 w (134%), $0.063

## I was wrong about Sonnet on commercial register

On v1/v2 I said Sonnet leaned literary-over-commercial and recommended eliminating it. That conclusion was based on the **t=0.80** Ch1S1 run — which did have the flamboyant flourishes and meta-irony I flagged.

**At t=0.70 on Ch13S1, Sonnet is the strongest commercial-register prose in the entire bench.** Not close. Some evidence:

### Structural discipline

Sonnet used `---` section breaks to stage arrival → surface assessment → Force-reach. No other model did this. It's a commercial-thriller structural choice (think David Mitchell, Tana French) that matches exactly how the Ruusan scene cards read.

### Ensemble handling, all five characters working

- **Desh (non-Force):** "*Like I'm standing in a room where someone used to be and they left recently.*" — nails the scene card's "grief without an object" beat from the non-Force side.
- **Kael:** "*She used it as proof.*" + "*How many people lived here?*" — the single line that grounds 42,000 dead people in a character beat.
- **Torin:** "*stripped of the warmth, the easy authority, the paternal steadiness. He looked like a man standing in a place he recognized from a nightmare.*" — embeds backstory in present observation.
- **Sera:** "*She used this world as a test.*" — delivers the field-test recognition sharply.
- **Ben:** full arc, including a legendary closing paragraph (below).

### The Force description

> *"It was there. That was what he hadn't expected. He'd braced for absence—for the flat, dead silence he'd read about in the Codex descriptions of Nathema, the total severance that left Force-sensitives hollowed out. He'd prepared himself for nothing. What he got was everything, and none of it meant anything."*

That is the single best piece of prose in the entire bench. Sets up an expectation, subverts it, lands on "none of it meant anything." Zero anti-pattern breaches. Echoes the scene card's own metaphor vocabulary ("light exists but nothing reflects it").

### The arc beat (`lie_challenged`) — Sonnet's version

> *"He'd always known those thoughts were his. He wasn't naive enough to think the Force made him good. But he hadn't known, until now, how much of the time he'd been relying on it to make him careful."*

Compare GPT 5.4's version:

> *"Torin is compromised. / Sera will hold to principle until it kills someone. / Kael will run if the angle turns bad. / Desh should never have come here. / Veraine needs to die before she touches another node."*

Different approach. GPT enumerates *what* the unfiltered thoughts are — sharp, concrete, cinematic. Sonnet articulates *what the lattice was doing for him* — philosophical, unifying, mature. Both are world-class. GPT's is more immediately striking on first read; Sonnet's is the one you remember later.

### The "Ask me later" beat

Desh: "*You okay?*"
Ben: "*Ask me later.*"

Perfect Zahn-style deflection. Three words that tell you who Ben is.

## Sonnet t=0.80 vs Sonnet t=0.70 — why the difference matters

The temperature drop from 0.80 to 0.70 removes about 80% of the literary self-awareness I flagged earlier. You still get the craft, but the meta-ironic voice ("*the self-deprecating internal commentary he used to keep the honest version at a comfortable distance*") — the thing that read as "literary show-off" — is mostly gone at 0.70. What remains is tight commercial prose with philosophical weight.

The user's revision of the scene cards toward commercial register is matched much better by Sonnet t=0.70 than by Sonnet t=0.80. The 0.80 setting was pulling Sonnet toward its most showy mode; 0.70 lets it sit in a register that reads like Michael Connelly with Jedi furniture.

## Updated tier list

### Tier 1 — production-ready, premium voice
1. **Sonnet 4.6 @ t=0.70** — **new recommendation for arc-critical scenes.** Best commercial prose + most mature arc beat + hits word count + ensemble-fluent. Cost: $0.04-0.05 / scene.
2. **GPT 5.4 @ t=0.70** — sharpest individual sentences, best enumerated `lie_challenged` cascade. Overshoots word count by 34% (needs `max_tokens` cap to avoid bloat). Cost: $0.05-0.06 / scene.

### Tier 2 — production-ready, value voice
3. **Grok 4.20 @ t=0.70** — commercial register + propulsive + full ensemble. 88% coverage, ~half the cost of Sonnet/GPT. Cost: $0.02 / scene.
4. **DeepSeek V3.2 @ t=0.70** — cheapest, reliable, never fails. Less warmth-per-paragraph than Sonnet/GPT/Grok. Cost: $0.003 / scene.

### Tier 3 — cheap-and-fast, caveated
5. **Gemini 3 Flash** — $0.009/scene, 90% coverage. The "Jedi Lords" term I initially flagged as canon drift is actually canon-correct (pre-Ruusan Reformation title). Real remaining issue: closing-hook echoed verbatim from the brief.

### Tier 4 — structurally disqualified
6. Kimi K2 — truncates on ensemble (53%).
7. GLM 5.1 — truncates on long scenes (68%).
8. Gemini 3.1 Pro — truncates on prose (20%, 40%). Fine for plot_architect JSON.
9. GPT 5.4 mini — 198% bloat.

## Direct GPT 5.4 vs Sonnet 4.6 @ t=0.70 comparison

| Dimension | Sonnet 4.6 t=0.70 | GPT 5.4 |
|---|---|---|
| Commercial register | ★★★★★ | ★★★★ |
| Ensemble handling | ★★★★★ | ★★★★★ |
| Arc phase fidelity | ★★★★★ (philosophical) | ★★★★★ (enumerated) |
| Anti-pattern compliance | ★★★★★ | ★★★★★ |
| Word-count discipline | ★★★★ (96%) | ★★ (134% over) |
| Sentence-level punch | ★★★★ | ★★★★★ |
| Brief compliance (dramatizes hook) | ★★★★★ | ★★ (literal) |
| Cost / Ch13S1 | $0.053 | $0.063 |

Sonnet t=0.70 wins on every axis except sentence-level punch, and is 15% cheaper. If I had to pick one model to write Ruusan's prose, it would be Sonnet at temp 0.70 — assuming you're willing to pay the premium over DeepSeek/Grok.

## Implications for the config decision

The three options from v2 become four:

### Option A — DeepSeek everywhere (unchanged)
- ~$0.02-0.05 / chapter
- Simplest. Sacrifices the top-shelf voice for maximum savings.

### Option B — Hybrid DeepSeek + Grok 4.20 (unchanged)
- ~$0.05-0.12 / chapter
- Captures Grok's arc fidelity on ~6-8 pivotal scenes.

### Option C — Three-tier with GPT 5.4 for climax (unchanged)
- ~$0.08-0.20 / chapter
- Needs max_tokens cap on GPT 5.4 to control bloat.

### **Option D — Hybrid DeepSeek + Sonnet 4.6 @ t=0.70 for arc-critical (new)**
- ~$0.08-0.15 / chapter
- Keeps DeepSeek as the reliable workhorse for 70-80 routine scenes.
- Upgrades the 6-8 arc-pivotal scenes (`structural_phase ∈ {midpoint, pinch_1, pinch_2, climax_final}` or `pov_arc_phase` transitions) to Sonnet 4.6 @ t=0.70.
- Benefit: Anthropic prompt caching amortizes the Sonnet cost across chapter-level batches (1h TTL is already enabled in [settings.yaml:111](../../../../../../../config/settings.yaml:111)).
- Cost per chapter is similar to Option C but voice is tighter and word-count is reliable.

## My revised recommendation

**Option D over Option B or C.**

Reasoning:
- Sonnet t=0.70 on Ch13S1 was the best single output in the bench. Philosophical maturity matters at the midpoint and climax.
- Sonnet hits word count; GPT 5.4 doesn't. For a real production run across 84 scenes, the 134% overshoot from GPT would add meaningful rework.
- Anthropic prompt caching (1h TTL) is already turned on; Sonnet runs cheaper on chapter-level batches than the ticket price suggests.
- Cross-family is maintained: DeepSeek prose → Sonnet polish → Haiku gates. Only the `prose_stylist` model changes between routine and pivotal scenes.

Drop `quality_polish` from Sonnet 4.6 to **Haiku 4.5** regardless — Haiku is 3× cheaper and the bench showed Sonnet polish mostly adds craft, not structure fixes.

## Next action

1. Commit Option D. Patch [config/settings.yaml](../../../../../../../config/settings.yaml):
   - `prose_stylist: {model: deepseek, params: {temperature: 0.70, max_tokens: 8192}}` as default.
   - Add a small router hook that promotes `prose_stylist` to Sonnet 4.6 @ t=0.70 when `scene_card.structural_phase ∈ {midpoint, pinch_1, pinch_2, climax_final}` or `pov_arc_phase` is a transition beat.
   - `quality_polish: {model: haiku, params: {temperature: 0.40, max_tokens: 8192}}`.
   - `judge_evaluator: {model: claude, params: {temperature: 0.2}}` (Sonnet, cross-family from DeepSeek writer).
2. Run Ch1 end-to-end with Option D.
3. Compare gate-pass rate + voice consistency + total chapter cost against the archived Sonnet-only Ch1 run.

Total bench spend to date: **~$0.48** across 20 model-scene runs.

Ready to patch config and run Ch1?
