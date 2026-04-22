# Prose Model Bench — Ch1S1 (Ben Skywalker, training salle)
Date: 2026-04-17
Bench: same generation brief, same assembled context, three prose models.

## Scene card expectations (the grader)

- Target: 1,250 words, tight third-person, Ben Skywalker POV.
- **Opening hook:** guard drops → training blade catches shoulder.
- **Closing hook:** Luke in doorway with datapad → mission.
- **Turning point:** Ben privately acknowledges the wrongness has the same structural quality he knew around Jacen and Abeloth.
- **Voice markers (Zahn-style):** sharp, self-aware, slightly defensive; *never* melodramatic.
- **Anti-pattern (hard rule):** the Force wrongness must be described in **auditory/vibrational** terms only — no color, no visible phenomena, no crack-in-the-structure imagery.
- **pov_arc_phase:** `lie_established` — the lie is "self-reliance as safety."
- **Conflict type:** interpersonal (Ben vs. the Order's baseline read).
- **Emotional trajectory:** restless unease → frustrated isolation → reluctant hope.

## Raw numbers

| Model | Words | Latency | Est. in | Est. out | Est. cost |
|---|---:|---:|---:|---:|---:|
| Claude Sonnet 4.6 (temp 0.80) | 1,089 | 42.8 s | 5,487 | 1,616 | **$0.0407** |
| DeepSeek V3.2 (temp 0.70) | 1,106 | 50.4 s | 5,487 | 1,601 | **$0.0020** |
| Kimi K2 (temp 0.70) | 1,010 | 48.9 s | 5,487 | 1,561 | **$0.0067** |

Brief (Gemini 3.1 Pro, plot_architect) was generated once and reused: 52.7 s / ~3,900 chars. Not counted above.

## Voice-marker grading

### Claude Sonnet 4.6 — [file](claude-sonnet-46-t080.md)

**Zahn-style tight third:** Strongest. Has the self-observing ironic layer ("*the self-deprecating internal commentary he used to keep the honest version at a comfortable distance*"). Sentence rhythm most varied.

**Anti-pattern (auditory only):** Clean. "*a note played slightly flat in a piece of music he'd known since childhood*" / "*pressing a key on an instrument that had been tuned correctly in every register except one*" — pure auditory throughout.

**Lie_established:** Best embedded — Ben's retreat into self-reliance is shown *through the irony of his own self-deprecation*, not told.

**Turning point:** "*he knew the difference between weather and a crack in the foundation. This felt like the second one.*" Slips a "crack in the foundation" metaphor but it's abstract/structural, not visual. Borderline on anti-pattern.

**Closing hook:** Quietest of the three — Luke arrives, Ben makes an internal choice to take the mission, scene lands on "He'd take it." Most Zahn-like ending.

**Weakness:** Slightly over-literary for a commercial register. Uses inversions and digressions that read as craft but aren't what you revised the scene cards *toward*.

### DeepSeek V3.2 — [file](deepseek-v32-t070.md)

**Zahn-style tight third:** Competent but less ironic. Reports Ben's thoughts rather than dramatizing the gap between what he thinks and what he says.

**Anti-pattern (auditory only):** Clean. "*A note played slightly flat*" / "*the music simply stopped*" / "*dissonance… woven through it*" — consistently auditory/musical. Never visual.

**Lie_established:** Shown through action — "*He observed. He cataloged. He got hit in training salles and blamed his reflexes.*" Tight list-of-three that captures the lie without naming it.

**Turning point:** Explicit. "*It wasn't a wound that bled darkness. It was a… silence.*" Clear, slightly on-the-nose.

**Closing hook:** Most literal — Luke's expression is "*mission-ready*" where Sonnet lets the datapad do the work. Clean but less subtext.

**Weaknesses:** One melodrama moment ("*The isolation of it was the worst part.*" — a *told* beat). Prose is dense and image-rich but slightly more standardized in paragraph shape. Matches "concise, image-rich English, stoic arcs" profile the benchmarks predicted.

**Commercial-register fit: best of the three.** Propulsive rhythm, no digressions, each paragraph advances.

### Kimi K2 — [file](kimi-k2-t070.md)

**Zahn-style tight third:** Has moments. "*Ben had been paired with him for three sessions now and kept forgetting to ask*" is exactly the dry self-awareness the card asked for.

**Anti-pattern (auditory only):** **Two breaches.** "*crack ran through its structure*" and "*whatever crack ran through reality itself*" — this is the forbidden structural/visible metaphor. Uses "flat note" and "dissonance" correctly elsewhere, but the two crack lines violate the rule.

**Lie_established:** Most explicit — "*some problems were better solved before they became Luke's problems too*." Names the lie more directly than either other model.

**Turning point:** "*But those had been emotional wrongness, darkness bleeding through the light. This felt mechanical. Like the Force itself had developed a fault line.*" Mechanical/fault-line is a further anti-pattern breach.

**Closing hook:** Mission-briefing framing is good, and the "felt the familiar mix of love and resignation" beat lands. Slightly softer than Sonnet's.

**Weaknesses:** Anti-pattern breaches on Force metaphors (above). A few melodrama beats ("*The isolation hit him like a physical blow*", "*made his teeth ache and his skin crawl*"). "*Thank the Force*" quip reads as sitcom dialogue.

## Apples-to-apples verdict

| Dimension | Sonnet | DeepSeek | Kimi |
|---|---|---|---|
| Zahn voice | ★★★★★ | ★★★☆ | ★★★ |
| Anti-pattern compliance | ★★★★ | ★★★★★ | ★★ (2 breaches) |
| Lie_established | ★★★★★ | ★★★★ | ★★★★ |
| Turning point | ★★★★ | ★★★★ | ★★★ |
| Closing hook | ★★★★★ | ★★★★ | ★★★★ |
| Commercial register fit | ★★★ | ★★★★★ | ★★★★ |
| Cost | 1× ($0.041) | 20× cheaper | 6× cheaper |

## Recommendation for Ruusan commercial register

**Primary: DeepSeek V3.2 at temp 0.70** for `prose_stylist`.
- Zero anti-pattern breaches.
- Tight propulsive paragraphs that match the commercial revision.
- 20× cost reduction.
- Weaknesses (one flat melodrama beat, slightly on-the-nose turning point) are *exactly what the critique chain was designed to catch* — and with a Claude-family polish/gate, they'll be caught.

**Fallback: Kimi K2 at temp 0.70** only if DeepSeek feels too stripped on specific scene types (more lyrical / character-study scenes). Anti-pattern breach risk is real — gate_critic would need a Force-metaphor check.

**Control: Claude Sonnet 4.6** remains the quality ceiling, but on this scene the *register* is literary-leaning where you wanted commercial. Demote to a fallback-only via CLI flag for high-stakes or highly emotional scenes.

## What to do next

1. Update [config/settings.yaml](../../../../../../../config/settings.yaml) `prose_stylist` to `{model: deepseek, params: {temperature: 0.70, max_tokens: 8192}}`.
2. Update `quality_polish` off Claude to a different family so the chain is not all-Anthropic. Candidates:
   - Haiku 4.5 (conservative, keeps Anthropic instruction-following; breaks writer-polish family tie since writer is now DeepSeek).
   - Kimi K2 at temp 0.3 (aggressive, full cross-family polish).
3. Run Ch1 end-to-end with the new config (full pipeline, not just prose) to measure actual gate-pass rate and final cost.
4. Compare to the archived Sonnet Ch1 run in `runs/_archive/2026-04-17-pre-model-bench/` for regression signal.
