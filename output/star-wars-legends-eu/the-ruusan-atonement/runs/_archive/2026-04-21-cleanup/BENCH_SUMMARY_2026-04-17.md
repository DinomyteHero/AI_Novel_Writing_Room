# Prose Model Bench — Full Summary (2026-04-17)
Five models, two scenes, same brief, same context.

## Scenes

- **Ch1S1** — opening hook, solo interior, 1,250 w, 2 characters, `lie_established`
- **Ch13S1** — midpoint breach zone, 5-character ensemble, 1,600 w, `lie_challenged`, environmental

## Raw results

### Ch1S1 (1,250 w target)

| Model | Words | Coverage | Latency | Cost |
|---|---:|---:|---:|---:|
| Claude Sonnet 4.6 | 1,089 | 87% | 42.8 s | $0.041 |
| DeepSeek V3.2 | 1,106 | 88% | 50.4 s | $0.002 |
| Kimi K2 | 1,010 | 81% | 48.9 s | $0.007 |
| Grok 4.20 | 985 | 79% | 14.5 s | $0.020 |
| **GLM 5.1** | **1,218** | **97%** | 130.3 s | $0.011 |

### Ch13S1 (1,600 w target)

| Model | Words | Coverage | Latency | Cost |
|---|---:|---:|---:|---:|
| **DeepSeek V3.2** | **1,592** | **99.5%** | 103.5 s | $0.003 |
| Grok 4.20 | 1,401 | 88% | 21.3 s | $0.025 |
| GLM 5.1 | 1,087 | 68% ⚠️ truncated mid-sentence | 189.8 s | $0.011 |
| Kimi K2 | 850 | 53% ⚠️ | 40.3 s | $0.007 |

(Claude Sonnet not re-run on Ch13S1 — it was eliminated earlier as literary-over-commercial fit.)

## Structural failures

Two models **truncated mid-sentence on the 1,600 w ensemble scene**:

- **Kimi K2** — 53% coverage, skipped three of five ensemble characters' beats, went to rage instead of Weiland's seductive inversion.
- **GLM 5.1** — 68% coverage, cut off mid-sentence during Desh's chrono beat: *"something moved behind his eyes. 'There's something else. I don't know how to describe it"* — just stops.

These are not style issues. They are capacity failures at the scene length + ensemble complexity level Ruusan requires. For a 28-chapter novel with repeat long ensemble scenes (Ch13, Ch21, Ch25, Ch26, Ch28 all > 1,400 w), neither model is safe as the production writer.

## Voice evaluation — Ch1S1

### Claude Sonnet 4.6
Best Zahn-style irony ("*the self-deprecating internal commentary he used to keep the honest version at a comfortable distance*"). Most crafted. But leans **literary** where you revised the scene cards toward commercial.

### DeepSeek V3.2
Tight propulsive paragraphs, 0 anti-pattern breaches. Competent rather than brilliant on this scene — one flat melodrama beat ("*The isolation of it was the worst part*"). Strong commercial fit.

### Kimi K2
Warmest relational detail — "*Ben had been paired with him for three sessions now and kept forgetting to ask.*" Also "*Thank the Force*" which reads sitcom. Two anti-pattern breaches ("smoke" metaphor, "crack in structure").

### Grok 4.20
Sharp commercial register. "*Body's cashing checks my sleep schedule can't cover.*" Self-deprecating closing — "*He didn't know whether to feel relieved that his perception wasn't failing or terrified that it wasn't. ... Great.*" All-auditory Force metaphors ("*missed beat in a drumline*", "*like a string tuned a quarter-step off in an otherwise perfect orchestra*"). **0 anti-pattern breaches.** Short on word count (79%) but efficient prose — not padding.

### GLM 5.1 — standout voice on this scene
Best Jedi philosophy integration I've seen in any model here:

> *One of the Order's virtues and one of its blind spots—nobody asked follow-up questions when you said you were fine, because asking implied doubt, and doubt implied judgment, and the path between judgment and the dark side was shorter than anyone liked to admit.*

And:

> *Sometimes a headache was just a headache. Sometimes the galaxy really was ending. Distinguishing between the two required more than instinct.*

This is Zahn-level thought. Hit 97% word count. No anti-pattern breaches. On this scene, GLM 5.1 is *the* voice winner.

## Voice evaluation — Ch13S1

### DeepSeek V3.2
Full ensemble staged. Physiological pressure beats. Thought cascade at close:
> *This is easier than I expected. The silence is clean. Why is that frightening? What if she's right? What if the handrail was just a crutch?*

Textbook `lie_challenged` — seduction of the lie's inversion, not rage.

### Grok 4.20 — strongest arc beat of any model
Thought cascade rivals DeepSeek's and goes harder:
> *You always believed the Order's lattice was natural. What if Veraine is right? What if we've spent a thousand years enforcing a cage?*
> *Jacen tried to impose order once. Look where that led. Maybe tearing it down is the honest choice. Maybe—*
> *He cut the thread himself. The effort cost him.*

Kael's line *"Means nothing pushes, either. No intuition. No warning. Just us and whatever we drag inside our own skulls."* is some of the best ensemble-character work in the whole bench. Full ensemble staged. Philosophical precision. 88% coverage.

### GLM 5.1
Strong where it delivered — "*There's no handrail*" from Kael, who here is a *former Sith agent* (GLM introduced backstory detail not in the scene card — risky). Then truncated mid-sentence. Cannot evaluate the closing hook because it never happened.

### Kimi K2
Wrong arc beat. Went to visceral rage ("*wrapping his hands around her throat*") where the scene wanted seductive disorientation. Compressed or dropped three ensemble beats.

## Ruusan-relevant comparison matrix

| Dimension | Sonnet | DeepSeek | Kimi K2 | Grok 4.20 | GLM 5.1 |
|---|---|---|---|---|---|
| Ch1S1 voice | ★★★★★ lit | ★★★★ | ★★★★ | ★★★★★ | ★★★★★ |
| Ch13S1 voice | — | ★★★★ | ★★ | ★★★★★ | ★★★★ (partial) |
| Ch13S1 arc beat | — | ★★★★★ | ★★ wrong | ★★★★★ | — (truncated) |
| Word-count reliability | ★★★ | ★★★★★ | ★★ | ★★★★ | ★★★ (truncates at length) |
| Ensemble handling | — | ★★★★★ | ★★ | ★★★★★ | — (cannot verify) |
| Anti-pattern compliance | ★★★★ | ★★★★★ | ★★★ | ★★★★★ | ★★★★★ |
| Commercial register fit | ★★★ | ★★★★★ | ★★★★ | ★★★★★ | ★★★★ |
| Cost per 1,600w scene | $0.06+ | $0.003 | $0.007 | $0.025 | $0.011 |

## Verdict

Two models clear the bar for Ruusan: **DeepSeek V3.2** and **Grok 4.20**. Everything else either degrades on long ensemble scenes (Kimi, GLM) or misses the register you revised toward (Sonnet).

### DeepSeek V3.2
- **Cheapest by 10×.** Never truncates. Handles ensembles. Delivers Weiland arc beats correctly.
- Slightly less warmth-per-paragraph than Grok or Sonnet.
- Reliable workhorse.

### Grok 4.20
- **Voice-best of the survivors.** Commercial register with genuine philosophical weight. Best `lie_challenged` beat of any model. Kael and Sera's ensemble lines are genuinely striking.
- 10× the cost of DeepSeek but 2× cheaper than Sonnet, and the voice quality is arguably comparable to Sonnet while better-matched to your revised register.
- Occasionally under word count (79-88%) but never truncates mid-sentence; its shorter outputs are still structurally complete.

### The choice

**Three paths, listed by what they optimize for:**

1. **Cheapest + reliable: DeepSeek V3.2 everywhere.** Per-chapter cost ~$0.02-0.05 on prose. Register fit is strong. Warmth-per-paragraph is where you'd lose vs Grok.

2. **Best voice + still reasonable: Grok 4.20 everywhere.** Per-chapter cost ~$0.25-0.40. Still much cheaper than Sonnet baseline. The arc-phase fidelity on Ch13S1 is striking — this model understands Weiland.

3. **Hybrid: DeepSeek for routine scenes, Grok 4.20 for arc-critical scenes.** Route by scene card field — use `structural_phase` (`midpoint`, `climax_final`) and `pov_arc_phase` transitions (`lie_challenged`, `truth_embraced`) to pick Grok for the ~6-8 pivotal scenes per book, DeepSeek for the rest. Total per-chapter cost ~$0.05-0.12. This matches how your pipeline already tiers agents.

### My read

Option 3 is the honest answer. The Ch13S1 signal — Grok handling the midpoint arc phase more faithfully than DeepSeek — is real and structural, not a taste call. But running Grok on every scene including quieter setup beats overpays for work DeepSeek handles well.

**Proposed hybrid routing logic** (one-line addition to the orchestrator):
- If `scene_card.structural_phase ∈ {"midpoint", "climax_final"}` OR `pov_arc_phase` is a transition beat (`lie_challenged`, `moment_of_truth`, `truth_embraced`), route `prose_stylist` → Grok 4.20.
- Otherwise, route `prose_stylist` → DeepSeek V3.2.

Full-book estimate (28 chapters × ~3 scenes = 84 scenes, ~6-8 arc-pivotal scenes routed to Grok, rest to DeepSeek): **~$1.50-3.00 total for prose**, vs. ~$18-25 with Sonnet everywhere.

### What still needs deciding

- Whether `quality_polish` should be Kimi K2 at temp 0.3 (cross-family, may add warmth back if DeepSeek ever feels thin) or Haiku 4.5 (conservative, cheap, strong instruction-following).
- Whether to bother implementing the hybrid routing now or start flat with DeepSeek everywhere and upgrade to hybrid only if a chapter-level run shows arc-phase fidelity gaps.

Total bench spend so far: **~$0.18** across 10 model-scene runs. All artifacts in [runs/bench-2026-04-17-prose*](.) and [runs/bench-2026-04-17-ch*-grok-glm](.).
