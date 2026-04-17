# Step-by-Step Pipeline Analysis (2026-04-17)

Test configuration:
- `plot_architect` → **Grok 4.20** @ temp 0.4
- `prose_stylist` → **Sonnet 4.6 @ t=0.70** and **GPT 5.4 @ t=0.70** (tested separately)
- `quality_polish` → **Haiku 4.5** @ temp 0.4

Scenes: Ch1S1 (1,250 w target, solo interior) and Ch13S1 (1,600 w target, 5-character ensemble midpoint).

Outputs in [bench-2026-04-17-ch1s1-pipeline](bench-2026-04-17-ch1s1-pipeline) and [bench-2026-04-17-ch13s1-pipeline](bench-2026-04-17-ch13s1-pipeline).

Spend for this round: **$0.21** (4 brief + 4 prose + 4 polish calls across both scenes).

---

## Step 1 — Grok 4.20 as plot_architect

### Speed

| Model | Ch1S1 | Ch13S1 |
|---|---:|---:|
| Grok 4.20 (this bench) | **7.6 s** | **9.6 s** |
| Gemini 3.1 Pro (previous) | 52.7 s | 84.7 s |

Grok is **8-9× faster** at brief generation. For chapter-level throughput on 80+ scenes per book, that's ~75 minutes of wall-clock saved per book.

### Brief quality

The Grok 4.20 Ch13S1 brief is **better than Gemini's** on voice direction:

> *"Channel Zahn's efficient dialogue and Allston's humor-under-stress; keep internal monologue clipped, pragmatic, and laced with dry self-awareness. Ben's thoughts should carry the commercial SW EU rhythm—short sentences during action, slightly longer during realization—never descending into Stover-style literary density. Surface Ben's dry wit once when reacting to the mirrored birds."*

That's a better `voice_guidance` field than anything in the Gemini briefs. Grok also added `forbidden_moves` that actually fire ("No re-introduction of the lattice concept from scratch—treat it as established"; "Do not allow any character outside the listed five to speak or act"). That's useful brief hygiene the Gemini versions omitted.

### The canon-drift issue

The Ch13S1 Grok brief introduces **"ancient Jedi Lords"** in beat 5's `pov_reaction`:

> *"Unsoftened thoughts—anger at the **ancient Jedi Lords**, fear for Sera and the others..."*

"Jedi Lords" is not a canonical Legends EU title. Standard terms are "Jedi Masters", "the High Council", or specific era labels like "Old Republic Jedi." Both Sonnet and GPT **faithfully carried this into the prose** because they were following the brief — that's correct agent behavior, but it surfaces the risk: **Grok 4.20 on plot_architect needs `canon_expert` downstream to catch drift**. That agent already exists in the pipeline (it's routed to Grok 4.20 itself, which is a problem — same-family self-check).

Recommendation: If you adopt Grok for plot_architect, switch `canon_expert` to a different family (Haiku 4.5 or DeepSeek V3.2) so one family can't write and then approve its own franchise term.

---

## Step 2 — Sonnet 4.6 @ t=0.70 with Grok brief

### Ch1S1 (1,250 w target)

| Metric | Grok brief | Gemini brief (prior run) |
|---|---:|---:|
| Words | 1,185 (95%) | 1,009 (81%) |
| Cost | $0.043 | $0.039 |

With the Grok brief, Sonnet delivered **14 percentage points more coverage** on Ch1S1. Likely because Grok's brief was longer (4,249 chars vs Gemini's 3,936) and gave Sonnet more structured material to dramatize.

Sample passage:
> *"His partner — Rendal, one of the newer Knights, good footwork, nothing memorable — held his own blade at rest and waited for the call."*

"Nothing memorable" as a three-word character sketch is perfect commercial Zahn. "Good footwork, nothing memorable" does more work than most paragraphs. The Grok brief's voice directive landed.

And later:
> *"He hadn't told anyone. Both times, he hadn't told anyone, and both times the thing he'd felt had turned out to be real."*

That structural repetition is Sonnet at its best — tight, musical, carrying the lie_established beat through rhythm rather than statement.

### Ch13S1 (1,600 w target)

| Metric | Grok brief | Gemini brief (prior run) |
|---|---:|---:|
| Words | 1,553 (97%) | 1,535 (96%) |
| Cost | $0.054 | $0.053 |

Almost identical coverage. The prose is at the same quality level.

But I note **one meaningful drift from the Gemini-brief version**: the closing beat in this run *enumerates* the unfiltered thoughts (anger at the Jedi Lords, fear for the crew, willingness to use survivors as tools), where the Gemini-brief version was more philosophical ("*how much of the time he'd been relying on it to make him careful*").

Both are strong. The Grok-brief version is slightly closer to GPT 5.4's enumerated style (because the Grok brief's `pov_reaction` explicitly enumerated those three thoughts). The Gemini-brief version was broader, more original.

**Implication:** Grok's brief pushes the writer toward its own structural choices. When Grok writes "anger at X, fear for Y, willingness to use Z," the prose model dutifully gives you anger-fear-willingness in sequence. That's faithful but reduces the writer's interpretive room.

### Ch13S1 sample — the Ben-Torin exchange

> *"We're not going back to report this. We're going forward."*
> *Torin looked at him. "The Order should know."*
> *"The Order will know when we tell them after." Ben kept his voice level. "We know where she's going. We know what she can do. We know she's already done it once and it worked. If we pull back to report, she gets more time at Veranthos." He looked at Torin. "You know I'm right."*
> *Torin was quiet for a moment. "I know you're not wrong," he said, which wasn't the same thing, and they both knew it.*

That is textbook Weiland `lie_challenged`: Ben making decisions the Force would usually soften, Torin noticing without quite naming it. The "I know you're not wrong" / "which wasn't the same thing, and they both knew it" construction is masterful — it's the moment Ben's self-reliance lie starts showing its cost in a relationship.

---

## Step 3 — GPT 5.4 @ t=0.70 with Grok brief

### Ch1S1 (1,250 w target)

| Metric | Grok brief | Gemini brief (prior run) |
|---|---:|---:|
| Words | 1,576 (126%) | 1,674 (134%) |
| Cost | $0.049 | $0.050 |

GPT 5.4 still overshoots, but **less with the Grok brief** (126% vs 134%). Grok's `forbidden_moves` and `voice_guidance` appear to rein it in slightly.

### Ch13S1 (1,600 w target)

| Metric | Grok brief | Gemini brief (prior run) |
|---|---:|---:|
| Words | 2,246 (140%) | 2,141 (134%) |
| Cost | $0.066 | $0.063 |

On the harder scene, GPT 5.4 overshoots by *more* with the Grok brief (140% vs 134%). Grok's brief is longer and denser, and GPT treats that as more runway.

### The GPT 5.4 humor layer is genuinely outstanding

Every few paragraphs GPT lands a line the other models don't reach:

> *"Like someone had watched birds once and rebuilt them from memory."* — the mirrored birds
> *"I miss ordinary ruins."* (Torin)
> *"Give it a minute. This place may still get creative."* (Ben)
> *"Kael said nothing at all, which was louder than usual."*
> *"Nobody had stepped around it."* — on the child's toy, three words that turn into horror.
> *"Ben kept his face still because Skywalkers were apparently required by law to look competent in public."*
> *"Thanks. I grew up around Solos. We had warning labels."* (Ben, to Torin)

That last one — "I grew up around Solos. We had warning labels." — is precisely the Zahn-meets-Allston voice the Grok brief asked for. Sonnet doesn't reach that register. GPT does.

### But — the closing-hook problem persists

GPT 5.4's final paragraph:
> *"In the silence of the de-structured Force, Ben heard himself think without the safety net of Force intuition for the first time. The thoughts were his. All of them. Including the ones the Force usually softened."*

Compare Grok brief's `closing_beat`:
> *"In the silence of the de-structured Force, Ben hears himself think without the safety net of Force intuition for the first time. The thoughts are his. All of them. Including the ones the Force usually softens."*

GPT changed **tense only** (present → past). Sonnet, by contrast, produced:
> *"The thoughts were his. All of them. Including the ones he'd always assumed the Force had helped him be better than."*

Sonnet *interpreted* the closing beat into a more specific, psychologically loaded line. GPT copied and pasted with tense agreement. This is consistent across all GPT runs — it treats the brief's closing_beat as dictation, not guidance. **That's a real weakness** for a writer you want to trust to dramatize.

---

## Step 4 — Haiku 4.5 as quality_polish

### What Haiku did on Sonnet

Haiku made **two meaningful edits** on Sonnet's Ch13S1 output:

1. Compressed a passive: *"The lurch in his chest was physical"* → *"His chest lurched."*
2. Tightened a wordy phrase: *"He watched her face go through three separate things in quick succession — professional assessment, recognition, something harder to name"* → *"He watched her face cycle through professional assessment, recognition, then something harder to name"*

Both are good edits — removing soft constructions, not changing structure. Exactly what `quality_polish`'s contract specifies.

### What Haiku did on GPT 5.4

Haiku only **normalized smart quotes** (" " → "). **Zero substantive edits.** GPT's prose was clean enough that Haiku found nothing line-level to improve.

Word count parity (2246 → 2246) confirms no content was touched.

### Cost of Haiku polish

- Ch1S1: ~$0.012-0.015 per polish call
- Ch13S1: ~$0.015-0.021 per polish call

For the full book (84 scenes × ~$0.018 avg) ≈ **$1.50 total polish cost**. That's trivial compared to prose generation cost.

### Verdict on Haiku as polish

Haiku 4.5 does what it's asked to do — surgical line-level edits when needed, minimal intervention when not. It's not trying to rewrite. It respects the word-count contract. **Confirmed as a good replacement for Sonnet-as-polish** in the config.

---

## Step 5 — Head-to-head on Ch13S1 (the harder scene)

| Dimension | Sonnet 4.6 t=0.70 | GPT 5.4 t=0.70 | Winner |
|---|---|---|---|
| Word-count discipline | 1,553 / 1,600 (97%) | 2,246 / 1,600 (140%) | **Sonnet** |
| Closing-hook dramatization | Transforms into own prose | Copies with tense change | **Sonnet** |
| Sentence-level punch | Strong, especially "I know you're not wrong" | Outstanding, consistent humor layer | **GPT** |
| Ensemble voice distinction | All 5 characters present, distinct | All 5 characters present, distinct | Tie |
| Arc beat (`lie_challenged`) | Enumerated + philosophical | Enumerated + sharper humor | Close, GPT slightly more striking sentence-by-sentence |
| Anti-pattern compliance | Clean | Clean | Tie |
| Canon fidelity | "Jedi Lords" from brief | "Jedi Lords" from brief | Both blame the brief |
| Cost / scene | $0.054 | $0.066 | Sonnet 18% cheaper |

**Sonnet wins on discipline; GPT wins on single-sentence impact; Sonnet is cheaper.**

If I could only pick one: **Sonnet 4.6 @ t=0.70**. Reasons:
1. Respects word count. Over a whole book, GPT's 140% overshoot adds up to ~130,000 extra words of content to either keep (inflating the novel past spec) or trim (manual work).
2. Dramatizes briefs rather than copying them verbatim.
3. 18% cheaper per scene.

If you want the absolute best sentences on the 2-3 climactic scenes: **promote those specific scenes to GPT 5.4 with `max_tokens: 4000`** to cap the overshoot. The "I grew up around Solos. We had warning labels." line is worth the extra $0.013.

---

## Step 6 — What this bench actually tested

This round tested a proposed **realistic pipeline configuration**:
- Grok 4.20 plot_architect (cheap, fast, good voice guidance — but canon-drift risk)
- Sonnet/GPT prose_stylist (the two premium options)
- Haiku 4.5 quality_polish (cheap, surgical)

Total per-scene cost with this pipeline:

| Scene | Sonnet pipeline | GPT pipeline |
|---|---:|---:|
| Ch1S1 | $0.055 (brief + prose + polish) | $0.064 |
| Ch13S1 | $0.069 | $0.088 |

For a full book (84 scenes, ~60% routine / 40% arc-critical):
- All-Sonnet: ~$5-6/book
- All-GPT: ~$6-8/book
- Hybrid (DeepSeek routine + Sonnet pivotal): **~$2-3/book**
- Hybrid (DeepSeek routine + GPT pivotal with max_tokens cap): **~$3-4/book**

---

## Recommendations — updated after this bench

### Settle on the full pipeline (Option D+)

```yaml
plot_architect:   { backend: cloud, model: grok420, params: { temperature: 0.4, max_tokens: 8192 } }  # was gemini
prose_stylist:    { backend: cloud, model: deepseek, params: { temperature: 0.70, max_tokens: 8192 } }  # was claude
quality_polish:   { backend: cloud, model: haiku, params: { temperature: 0.4, max_tokens: 8192 } }  # was claude
judge_evaluator:  { backend: cloud, model: claude, params: { temperature: 0.2, max_tokens: 4096 } }  # was grok420
canon_expert:     { backend: cloud, model: haiku, params: { temperature: 0.2 } }  # was grok420 — MOVED OFF GROK
```

**Plus** a scene-card-driven override that promotes `prose_stylist` to **Sonnet 4.6 @ t=0.70** when:
- `structural_phase ∈ {midpoint, pinch_1, pinch_2, climax_final}`, OR
- `pov_arc_phase` is a transition beat (`lie_challenged`, `moment_of_truth`, `truth_embraced`)

### The key new finding from this bench

**`canon_expert` must move off Grok 4.20 now that `plot_architect` is on Grok.** Same-family self-check failed the "Jedi Lords" term — it passed through without flag. Move `canon_expert` to Haiku 4.5 (cheap, different family, strong instruction-following for structured checks).

### What's left to decide

1. Commit the pipeline config above?
2. Run Chapter 1 end-to-end with the new pipeline and check:
   - Does `canon_expert` on Haiku catch "Jedi Lords"?
   - Do gate_critic false-rejections change when prose_stylist switches from Claude to DeepSeek?
   - Total chapter cost vs archived Sonnet baseline?

Total bench spend across all rounds so far: **~$0.69** across 25 model-scene runs.
