# Prose Model Bench — Ch13S1 (Breach Zone, ensemble, 1,600w target)
Date: 2026-04-17
Bench: DeepSeek V3.2 vs Kimi K2, same brief, same context, identical scene card.

## Why this bench

Ch1S1 (solo interior, 1,250w) showed Kimi K2 producing warmer relational detail than DeepSeek. The question: **does Kimi hold up on longer + ensemble scenes**, or does the known long-form degradation kick in?

## Raw numbers

| Model | Target | Delivered | Coverage | Latency | Cost |
|---|---:|---:|---:|---:|---:|
| **DeepSeek V3.2** | 1,600 w | **1,592 w** | **99.5%** | 103.5 s | $0.0025 |
| Kimi K2 | 1,600 w | **850 w** | **53.1%** | 40.3 s | $0.0067 |

**Kimi stopped at 53% of the requested word count.** DeepSeek hit target within 0.5%.

## Scene demands (the grader)

- **5 characters present** with distinct voices: Ben (POV), Sera, Torin, Kael, Desh (non-Force).
- **pov_arc_phase: `lie_challenged`** — Ben's "self-reliance as safety" lie under attack. The Weiland beat here is *seduction of the lie's opposite*, not rage.
- **Force wrongness: auditory/vibrational/absence only**, no visual/structural metaphors.
- **Closing hook:** "In the silence of the de-structured Force, Ben hears himself think without the safety net of Force intuition for the first time. The thoughts are his. All of them."

## Ensemble handling

### DeepSeek — 5 characters, each with distinct role and voice

- **Desh (non-Force):** Chrono drift, "grief with no object" — he's the objective register for what all non-Force-sensitives would feel. Appears four separate times with discrete observations.
- **Sera:** "*Structure isn't prison. It's what allows complexity. Without it, you get this.*" — intellectual/philosophical register. Three substantive lines.
- **Torin:** Physical warmth — "*put a hand on Ben's shoulder. A human gesture of comfort*" — then Ben *has to interpret it* because the Force no longer delivers the paternal warmth automatically. This is an outstanding beat: shows the lattice loss through relational mediation.
- **Kael:** Quiet observer — "*It's still alive. It's just following different rules.*"
- **Ben:** POV. Full arc from professional assessment → physiological pressure → the closing thought cascade.

### Kimi — characters present but under-served

- Sera: one elbow grip, one quoted line.
- Torin: one kneeling observation about flowers.
- Kael: "No insects" + "Grief. Without an object."
- Desh: chrono drift beat (good, but brief).
- Ben: full interior, but Kimi collapsed the middle beats and jumped to the closing.

Kimi name-drops the ensemble, DeepSeek stages the ensemble.

## Force-wrongness metaphor fidelity

### DeepSeek
- "*No texture. No direction. It was energy without current, light without shadow.*" — "*light/dark*" axis is established in the scene card's own conflict description, so not a breach.
- "*a mirror with no reflection*" — again, echoing the card's `sensory_details`: "*like trying to see in a world where light exists but nothing reflects it*."
- "*The handrail he hadn't even known he leaned on was gone. He was falling inward.*" — tactile/kinesthetic, fine.
- "*a presence that refused to communicate*" — abstract, fine.
- **0 breaches.** DeepSeek stayed inside the scene card's metaphor lexicon.

### Kimi
- "*questing tendrils grasping smoke*" — **visible phenomena** (smoke), **one breach**.
- "*how do you explain color to someone who'd only seen grayscale*" — borderline: visual comparison, but it's a *meta-comparison* about explaining the Force, not describing the Force. Grey-area.
- "*absence of music*" — good.
- "*library where all the books had been translated into a language that used familiar letters to mean different things*" — very good, zero visual.

**1 clear breach + 1 borderline.** Fewer than on Ch1S1, but still non-zero.

## The `lie_challenged` arc beat

The scene card is explicit: Ben's lie is "self-reliance as safety." The midpoint Weiland beat is not rage — it's the terrifying realization that the lie *might be true*, that the Force-mediated moral framework he's been leaning on is optional.

### DeepSeek — nails it

Closing thought cascade:
> *This is easier than I expected.*
> *The silence is clean.*
> *Why is that frightening?*
> *What if she's right?*
> *What if the handrail was just a crutch?*
> *I could do anything here, and no one would know. Not even me.*

This is the *seduction of the lie's inversion* — exactly what `lie_challenged` means in Weiland's framework. The last line is the ethical-autonomy beat: without external moral feedback, he can't police himself. That is textbook midpoint.

### Kimi — strong visceral, wrong arc phase

Kimi's Ben goes to violence:
> *something that lived in his bones, that whispered about the satisfaction of wrapping his hands around her throat and squeezing until her superior smile cracked*

Visceral, but this is dark-side-temptation rage, not lie-challenged seduction. The scene card asked for "*existential disorientation*" as the end-state emotional trajectory — Kimi delivered dark anger, which is a different arc beat entirely.

## Where Kimi's warmth observation from Ch1S1 actually shows up here

Honestly evaluating the user's point from Ch1S1:

**Kimi warmth beats in Ch13S1:**
- "*How did you explain color to someone who'd only seen grayscale? How did you describe the absence of music to someone born deaf?*" — this is a writer's empathy move that DeepSeek didn't make.
- "*Children who'd never learned to shield themselves, elderly Force-sensitives whose life-support systems had depended on their ability to maintain meditation trances?*" — concrete human casualty imagination, specific ages, specific types of vulnerability. DeepSeek didn't populate the dead planet with imagined casualties at all.

These are real. Kimi *does* reach for human detail DeepSeek doesn't. The problem is it only reached a few times before stopping — at 53% of target.

**DeepSeek warmth beats that Kimi didn't have:**
- The Torin shoulder gesture + Ben's forced interpretation of it — this is a *better* human-relational beat than anything in Kimi's version, because it dramatizes the Force-lattice loss through the broken automaticity of a family relationship.
- Ben's "*nervous tic he couldn't suppress*" about reaching for the Force — a specific, human, slightly humiliating self-observation.
- The "*naked map of his own judgment*" line — precise philosophical image, not clichéd.

On Ch13S1, DeepSeek's warm-human moments are actually *more numerous and better integrated* than Kimi's. My first-bench observation that Kimi had the warmer voice was a small-sample artifact — true for solo interior monologue at short length, not true for ensemble scenes with thematic complexity.

## Honest verdict

Kimi's degradation is worse than "wheels come off over 3,000 words." At **1,600 words with a 5-character ensemble, Kimi missed half the scene.** The word count miss isn't padding — it means entire ensemble beats, the middle of the emotional arc, and the "Veraine's field test" thematic recognition got compressed or skipped.

This is a structural capacity issue, not a prompt-tuning issue. Adjusting temperature or adding length-cue prompts might help at the margins, but the research finding the benchmarks warned about is showing up empirically on Ruusan's actual scene shapes.

**DeepSeek V3.2 is the writer.** It has a narrower warmth band than I'd hoped, but on the most demanding scene type in the book (ensemble midpoint, 1,600w, complex arc phase, strict anti-pattern) it delivered a draft I'd call genuinely strong prose — not merely "competent for the price."

## What this means for the config

Unchanged from the Ch1S1 recommendation:

1. `prose_stylist`: DeepSeek V3.2 @ temp 0.70.
2. `quality_polish`: move off Claude Sonnet. Options:
   - **Haiku 4.5** (conservative, keeps Anthropic instruction-following in the chain).
   - **Kimi K2 @ temp 0.3** (aggressive — Kimi's short-form strengths shine at this length of task).
3. `judge_evaluator`: Sonnet 4.6 so the judge is a different family from the writer.
4. Chapter-level check after the first real run: does DeepSeek's warmth-band feel thin at the chapter scale? If yes, consider tuning the ProseStylist prompt to include a voice directive like "*Include at least one moment of quiet relational observation per scene — the kind of detail that shows a character through what they notice, not what they say.*"

## Next action

Run Chapter 1 end-to-end (3 scenes, full pipeline: plot_architect → prose_stylist → gate_critic → quality_polish → final_gate) with the new config so we measure gate-pass rate, voice consistency across three scenes, and total chapter cost against the archived Sonnet baseline.
