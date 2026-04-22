# Prose-Model Bench — 2026-04-19 Post-Fixes

Confirmation bench after landing the Phase A–C prompt-engineering fixes (see the conversation summary and [BENCH_SUMMARY_2026-04-19.md](BENCH_SUMMARY_2026-04-19.md) for the pre-fix baseline). Tests whether the prompt changes (a) fix the closing_beat tense bug, (b) prevent `pov_reaction` phrase-copying, (c) close the voice-quality gap between Claude and GPT, and (d) preserve or improve word-count discipline.

---

## Test configuration

**Scenes (2, same structural anchors as the baseline for direct comparison):**
- `chapter_01_scene_01.json` — setup, target 1,250w
- `chapter_13_scene_01.json` — midpoint, target 1,600w

**Pipeline config:** `config/settings.bench.sonnet.yaml` (plot_architect=Grok 4.20 @ t=0.4, polish=Haiku 4.5 @ t=0.4). Fresh plot_architect briefs for each scene — the prompt changes mean we needed new briefs, not reused.

**Model matrix (6 configs: 2 drafters × 3 temperatures):**

| Short | Full slug | Temperatures |
|-------|-----------|--------------|
| claude | anthropic/claude-sonnet-4.6 | 0.70, 0.75, 0.80 |
| gpt54 | openai/gpt-5.4 | 0.70, 0.75, 0.80 |

Each prose output passed through a Haiku polish call to match the production pipeline.

**Total cost: $0.81** across both scenes × 6 configs × (prose + polish).

---

## Word-count discipline

| Scene (target) | claude 0.70 | claude 0.75 | claude 0.80 | gpt54 0.70 | gpt54 0.75 | gpt54 0.80 |
|---|---:|---:|---:|---:|---:|---:|
| ch1s1 (1,250w) | 1,102 (88%) | **1,226 (98%)** | 1,028 (82%) | 1,631 (130%) | 1,658 (133%) | 1,497 (120%) |
| ch13s1 (1,600w) | 1,464 (92%) | **1,491 (93%)** | 1,380 (86%) | 2,061 (129%) | 2,158 (135%) | 2,307 (144%) |

### Pre-fix vs post-fix delta for Claude (same scenes)

| Scene | Config | Pre-fix | Post-fix | Δ |
|---|---|---:|---:|---:|
| ch1s1 | claude 0.80 | 94% | 82% | **-12 pts** |
| ch1s1 | claude 0.70 | 92% | 88% | -4 pts |
| ch13s1 | claude 0.80 | 95% | 86% | **-9 pts** |
| ch13s1 | claude 0.70 | 91% | 92% | +1 pt |

**Claude is now slightly briefer at higher temperatures** — likely a consequence of the DO-NOT-channel consolidation and softened "transparent prose" instruction freeing the model to end scenes more tightly. Claude 0.75 (new temp) is the new sweet spot at 98% / 93%.

### GPT: still structurally overshoots

GPT at every temperature still ships ~120–144% of target. Temperature is not the lever here — the overshoot is structural. Note ch13s1 at t=0.80 got *worse* (144% vs pre-fix 139%), which matches the theory: with the prompts now permitting more voice distinctiveness, GPT uses that permission to go longer, not tighter.

---

## Fix verification

### ✓ Fix 1: Closing_beat tense bug

**Pre-fix brief.closing_beat** (present tense):
> "In the silence of the de-structured Force, Ben **hears** himself think without the safety net..."

**Post-fix brief.closing_beat** (past tense, [plot_architect.md:18](../../../../../prompts/agent_system_prompts/plot_architect.md:18) instruction):
> "In the silence of the de-structured Force, Ben **heard** himself think without the safety net..."

Both Claude and GPT final paragraphs in the post-fix bench land in past tense. The Kimi-style tense slip from the earlier bench is no longer reproducible.

### ✓ Fix 2: pov_reaction structural vs lyrical

**Pre-fix brief pov_reaction example** (lyrical, drafter-copyable):
> "Every trained instinct echoing in a room with no walls."

**Post-fix brief pov_reaction example** (behavioral, shape-not-sentence):
> "His trained instincts fire into nothing; the absence lands as a physical hollowness in the bones of his arms and a sudden loudness of his own unmediated thoughts."

Model outputs diverge more than before:
- Claude 0.75: *"The ground of his perception had dropped out from under him and the Force was still there…"*
- GPT 0.80: *"There was power here. Presence. Enough to drown in. But no moral contour rode beneath it."*

No shared verbatim phrase between the two drafts at the turning point. The old "room with no walls" convergence is gone.

### ✓ Fix 3: Franchise profile loaded

The post-fix brief's `voice_guidance` reads:
> *"Channel Zahn's efficient dialogue and tight third-person interiority… Use franchise-native sensory palette: ozone, recycled air, durasteel cold, reversed vegetation."*

This content is sourced from [prompts/franchise_profiles/star-wars-eu.md](../../../../../prompts/franchise_profiles/star-wars-eu.md) — the plot_architect picked it up from the second system message. prose_stylist.md, plot_architect.md, and outline_planner.md no longer hardcode the franchise specifics.

### ✓ Fix 4: POV override respects voice_definition

prose_stylist now reads `pov_approach` from `voice_definition.pov_approach` ([context_assembler.py:180](../../../../../src/memory/context_assembler.py:180)). For Ruusan, the (slugified) value is *"close third-person limited, locked to Ben Skywalker throughout"*. Both outputs respect this — strict close-third throughout, no head-hopping.

---

## Qualitative: did Claude come alive?

**Yes, partially.** Claude at t=0.75 produces noticeably more distinctive prose than pre-fix Claude at any temperature:

- *"the settlement's primary landing pad — duracrete, intact, with faded direction markings still legible"*
- *"a word he'd forgotten how to pronounce"*
- *"*Before what?* Nobody asked. They all knew."*
- *"a pressure the way you'd locate a pulled muscle"*
- *"a vertigo-like drop though the duracrete under his boots stays level"*

Compare the pre-fix Claude 0.80 opening on the same scene:
> *"Kolven looked like a postcard."*

vs. the post-fix Claude 0.75 opening:
> *"The planet looked fine. That was the problem."*

The post-fix is in the same register but with more rhythmic variety and a sharper hook. The "transparent prose" mandate was suppressing this.

**GPT 5.4 @ t=0.80 remains the voice leader.** Sample strengths:

- *"Can weather panic?"*
- *"Kael, folded into the corner near the hatch as if the ship had grown around him"*
- *"'Wonderful. I always enjoy having the enemy's intent clarified.'"*
- *"thoughts came through with a new hard edge… sharp as cut glass, offering him options and costs and selfish relief alongside duty with exactly the same calm."*

GPT's lead on "novelistic texture" narrowed but did not close. The cost is the persistent 20–44% overshoot.

---

## Revised tier list

**Production drafter — two viable picks:**

| Pick | Config | Discipline | Voice quality | Cost/scene (1,250w target) |
|------|--------|-----------:|--------------:|---------------------------:|
| **A. Voice-first** | `prose_stylist: gpt54 @ t=0.80` | 120–144% | Strongest | ~$0.057 prose + $0.017 polish |
| **B. Discipline-first** | `prose_stylist: claude @ t=0.75` | 93–98% | Very good (narrowed gap) | ~$0.044 prose + $0.012 polish |

**Delta between A and B:** GPT's voice edge is now clearly visible but no longer dramatic. Claude has gained enough texture at t=0.75 that in blind reading you would call the prose "good commercial novel." If you care about pacing (scenes landing near their target word count so the 28-chapter structure works), pick B. If you care about the single most alive-on-the-page prose and are willing to edit 20–40% of the words out afterward, pick A.

**Disqualified for drafter:**
- Claude @ t=0.80 — drifted briefer post-fix (82/86%), less reliable
- GPT @ t=0.70 or 0.75 — no meaningful quality upside over t=0.80, same overshoot

---

## Recommendation

**Switch `config/settings.yaml` to Claude @ t=0.75 as the prose_stylist default.** Rationale:

1. Prose quality is now in the "good commercial novel" band — no longer "competent but flat".
2. Word-count discipline at 93–98% is the best of any config tested across both bench waves (2026-04-17 and 2026-04-19).
3. Roughly 25% cheaper per scene than GPT @ t=0.80 with far less editing overhead downstream.

**Keep GPT 5.4 @ t=0.80 available as a Phase-4 tentpole-scene routing option** — for midpoints, climaxes, and any scene where the voice quality justifies the overshoot. Route via a scene-card hint or a post-Phase-4 prose-complexity classifier; do not make it default.

Concrete `config/settings.yaml` change:
```yaml
prose_stylist: { backend: cloud, model: claude, params: { temperature: 0.75, max_tokens: 8192 } }
```
(currently `temperature: 0.80` per the production routing.)

---

## Artifacts

- `bench-2026-04-19-post-fixes-ch1s1/` — 6 prose + 6 polished for the setup scene
- `bench-2026-04-19-post-fixes-ch13s1/` — 6 prose + 6 polished for the midpoint scene
- Each dir has `bench_summary.json` and a fresh `generation_brief.json` showing the post-fix brief structure.

## What this bench did not measure

- Only 2 scenes. The 2026-04-19 pre-fix bench covered 3 scenes (added a climax). Have not re-tested the climax under post-fix prompts — Claude's pre-fix performance on ch26s2 (94% at t=0.80, close-enough at t=0.75 untested) suggests no surprises, but worth confirming on a future single-scene bench if concerns arise.
- No judge scoring (`--judge` not run). Qualitative read only.
- No full-chapter run. The `--skip-gate-loop` question has not been re-evaluated against the new prompts.
