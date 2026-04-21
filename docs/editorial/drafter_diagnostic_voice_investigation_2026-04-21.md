# Drafter Diagnostic-Voice Investigation — 2026-04-21

**Symptom.** `canon_expert` flagged three "franchise_voice" (moderate) violations on `output/star-wars-legends-eu/the-ruusan-atonement/runs/2026-04-19T22-27/chapters/chapter_01_scene_01.md` — all instances of the *diagnostic voice trap*: clinical Force framing, mechanical/structural metaphors, mission-debrief-shaped sentences. The scene is Ben alone in the salle after a sparring loss; `pov_arc_phase` is `lie_established` (Part 1).

**Why this matters.** Four separate places in the authored data warn against this pattern:

| Warning source | Path |
|---|---|
| Scene-card note | `data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards/chapter_01_scene_01.json:59` |
| Ben voice CRITICAL TRAP block | `concept_seed.json:1726` |
| R11 "Ben's diagnostic-voice discipline" derived-rule | `concept_seed.json:1789` |
| R8 "Concept-vs-sensation rule (D4)" derived-rule | `concept_seed.json:1775` |
| `force_description_guidelines` (seed) | `concept_seed.json:1863` |
| `franchise_terminology_notes` (seed) | `concept_seed.json:2222` |

Yet the pattern still reaches the saved prose (lines 27, 33, 41, 49, 55 of the saved scene).

## Method

1. Rendered the ch01_sc01 drafter prompt offline with `scripts/audit_phase0._render_prose_stylist_prompt` via [tmp_diagnostic/render_prompt.py](../../tmp_diagnostic/render_prompt.py) and located every warning by character offset.
2. Read [src/memory/context_assembler.py](../../src/memory/context_assembler.py), [src/agents/prose_stylist.py](../../src/agents/prose_stylist.py), [src/agents/plot_architect.py](../../src/agents/plot_architect.py), and their system prompts to trace the prompt-assembly path.
3. Grepped saved chapters across the 22-27 production run and several bench runs for diagnostic-voice tokens (`structural`, `architecture`, `the Force's`, `a layer`, `handrail`, `second beat`, `half-beat`, `measurable`, `chrono-drift`, `pressurize`, `confirmation came`, `echo from`, `clinical`, `analyti`).
4. Ran one minimal-repro Sonnet 4.5 @ t=0.8 call with the anti-pattern reframed as a hard positive directive at the top of a short prompt ($0.006 — see [tmp_diagnostic/model_obedience_test.py](../../tmp_diagnostic/model_obedience_test.py) and [tmp_diagnostic/obedience_reframed.md](../../tmp_diagnostic/obedience_reframed.md)).

No pipeline code was changed. No runtime flags were flipped.

## Findings

### 1. Warning-salience map (drafter user prompt; 51,399 chars total)

| Warning | Char offset | % through prompt | Render form |
|---|---:|---:|---|
| Scene-card "Diagnostic-voice trap" | 8,905 | **17.3%** | inside `## Scene Card \`\`\`json … \"notes\": \"…\"\`\`\`` blob — no header, no directive framing |
| R8 Concept-vs-sensation rule | 22,815 | 44.4% | bullet inside `## Voice Rules > Architecture Rules` (16-rule list) |
| R11 Ben's diagnostic-voice discipline | 24,511 | 47.7% | bullet inside same 16-rule list |
| CRITICAL TRAP TO AVOID (Ben voice) | 40,372 | **78.5%** | inside `## Voice Rules > Character Voices > **Ben Skywalker**:` paragraph, buried in a 300-word voice-sketch |
| `franchise_terminology_notes` ("avoid 'energy field'") | — | — | **NEVER RENDERED** — ContextAssembler does not read `canon_constraints.franchise_terminology_notes` |
| Generation Brief `anti_patterns` | 48,436 | 94.2% | synthesized brief carries empty list; real PlotArchitect brief likely also empty (see §3) |

The Generation Brief — the one block designed for high-salience, per-scene instructions with a header that reads "## Anti-Patterns (extracted from scene card notes — do NOT do these)" — is at 94.2% of the prompt (**right before the Task**, the prime end-of-prompt slot) but **nothing ever lands there** for this scene.

### 2. Bench comparison: warnings directionally help but don't terminate the bug

Grepping `output/.../runs/bench-ch1-sonnet-STRIPPED/` (minimal prompt scaffolding) vs `output/.../runs/bench-ch1-sonnet-FULL/` (full) vs the 22-27 production run for diagnostic-voice tokens:

| Run | Count of overt diagnostic-voice phrases in ch01_sc01 |
|---|---|
| bench-ch1-sonnet-STRIPPED | **high** — "My read is that it's structural… Not emotional, not residue, not localized dark-side saturation", "Force lattice disruption", "in the architecture" |
| bench-ch1-sonnet-FULL | low — one soft mechanical metaphor ("like the floor had shifted a centimeter") |
| 2026-04-19T22-27 production | medium — "the Force's answer", "second beat runs under the first", "confirmation came in like an echo", "the layer under his own reach", "a note played slightly flat" |

The warnings work. They are just not strong enough for this specific Part-1 salle scene.

### 3. Brief `anti_patterns` extraction is likely failing for voice-level patterns

[plot_architect.md:41-43](../../prompts/agent_system_prompts/plot_architect.md) tells the LLM to extract forbidden-move language from `scene_card.notes`, with examples `"do not open with"`, `"avoid"`, `"don't start with"`, `"no flashback"`, `"no exposition dump"`. All examples are **structural/compositional** moves. The scene-card warning is **voice-register**: *"Diagnostic-voice trap — he should not, in this scene, arrive at any clinical articulation…"*. A strict interpreter might treat this as out-of-scope. Without a captured brief from the 22-27 run (live-capture needs `runtime.phase0_audit.enabled` — off globally), we can't confirm, but the prior-known fact that PlotArchitect outputs were reused in the 2026-04-19 post-fix bench and still failed suggests extraction did not surface this warning to the `anti_patterns` field.

### 4. Model-obedience floor is not the bottleneck

With the anti-pattern reframed as a top-of-prompt **hard positive directive** in ~300 words ("Narrate only through sensory register / auditory metaphor. DO NOT use structural, architectural, mechanical framing. If any sentence could be lifted into a mission debrief, it is wrong."), Claude Sonnet 4.5 @ t=0.8 produced 356 completion tokens of prose with zero occurrences of `structural`, `architecture`, `layer`, `measurable`, `the Force's answer`, or `second beat`. The output stayed tactile, sensory, Part-1-appropriate. Full output at [tmp_diagnostic/obedience_reframed.md](../../tmp_diagnostic/obedience_reframed.md).

This isolates the problem to prompt salience, not model capability. (Caveat: test used Sonnet 4.5; production uses Sonnet 4.6. The obedience delta between the two minor versions is small — call this a strong directional signal rather than a point estimate.)

### 5. Not a Part-1 vs Part-3 register contradiction

I searched `concept_seed.json` for cross-register elevation notes. The R11 text at line 1790 mentioned in the original bug brief turns out to be the *definition* of the anti-pattern, not a contradiction — it says explicitly: *"Parts 1-2 render his perception as first-approximation reading — reactive, tactile… Sharpening arrives at Ch 13 midpoint and Ch 21 SPP."* No competing directive exists in the seed. The rule is internally consistent; the pipeline just doesn't gate ch01 scenes against later-book register allowances (Stover-permitted Ch 13/25/26, Luceno payload density, etc.), all of which appear unfiltered in the voice-rules block.

### 6. Cross-scene — Part-1-specific, not a systemic collapse

Spot-grep of ch01_sc02 and ch01_sc03 in the 22-27 run did not surface the same cluster of tokens. The bench-STRIPPED run *does* show the same pattern crossing into dialogue in ch01_sc02 ("My read is that it's structural"), but production sc02/sc03 look OK. This bug is concentrated in **scenes where Ben is alone with the disturbance and has no one to talk it through with** — exactly the structural setup where the drafter has license to fill with interiority, and where the anti-pattern risk peaks.

## Root-cause hypotheses (ranked)

1. **Salience dilution (primary).** The scene-specific warning lives inside an indented JSON code block at 17% of the prompt with no directive framing. R8 and R11 are bullets 8/11 of 16 in the Architecture Rules list. The CRITICAL TRAP block is embedded inside a paragraph at 78.5%. The one slot designed for high-salience per-scene anti-patterns (Generation Brief → Anti-Patterns at 94%) is empty.
2. **PlotArchitect's anti-pattern extraction is pattern-matching, not semantic.** Its few-shot examples bias the extractor toward compositional moves (flashback, exposition dump), not voice-register moves (diagnostic voice, clinical framing). The brief that should carry the scene-card warning into the high-salience slot is empty.
3. **`franchise_terminology_notes` never renders.** The seed's "avoid 'energy field' — Luke's generation understands the Force as a living presence, not a measurable phenomenon" is orphaned data — ContextAssembler never reads `canon_constraints.franchise_terminology_notes`.
4. **No chapter-phase gating of later-book register allowances.** The drafter sees Stover-permitted Ch 13/25/26, Luceno payload, scene_type_anchor_mapping all at once, with no filter by `scene_card.pov_arc_phase` or `chapter_number`. A Part-1 scene could benefit from a narrowed register scope.
5. **Model-obedience floor** (not a root cause — model obeys cleanly when the directive is surfaced at the top).

## Recommended fix

A single prompt-engineering PR with three coordinated edits:

### A. Hoist scene-card-level voice/anti-pattern notes to the top of the drafter prompt

In [src/agents/prose_stylist.py:130-226](../../src/agents/prose_stylist.py) (`_format_context`), before `assembled_context` is appended, emit a new top-of-prompt `## Scene Voice Contract (READ FIRST — ABSOLUTE)` section built from:
- `scene_card.get("notes", "")` — rendered verbatim with the heading
- `scene_card.get("anti_patterns", [])` — if present
- `scene_card.get("pov_arc_phase")` and derived register guidance for that phase
Placing the scene-level anti-pattern at ~2% of the prompt (right after system message) is the single highest-leverage change.

### B. Broaden PlotArchitect's anti-pattern extraction

In [prompts/agent_system_prompts/plot_architect.md:41-43](../../prompts/agent_system_prompts/plot_architect.md), expand the few-shot examples to cover voice-register patterns: add `"do not arrive at clinical articulation"`, `"avoid diagnostic voice"`, `"keep it [sensory modality]"`, and add a rule that **any phrase inside `notes` containing "should not" / "do not" / "avoid" / "trap" / "anti-pattern" is eligible for extraction regardless of whether it describes structure or voice**. Prime the extractor to surface voice-level text.

### C. Surface `franchise_terminology_notes`

In [src/memory/context_assembler.py:643-646](../../src/memory/context_assembler.py) (around the `force_description_guidelines` render), read `concept_seed.canon_constraints.franchise_terminology_notes` and append it under a new `### Franchise Terminology Notes:` heading inside the voice-rules block. One-file, ~10-line addition.

### Verification

Re-run `scripts/bench_prose_models.py` on `chapter_01_scene_01.json` (and `chapter_13_scene_01.json` for regression check on a Stover-permitted climax scene) at Claude Sonnet 4.6 @ t=0.8. Expected: the six banned tokens disappear from ch01_sc01; ch13_sc01 stays within its permitted register allowance. Budget: ~$0.40 for the two bench scenes.

## "Commit this fix now?" judgment

**No — but close.** The fix is isolated (two prompt files + one module helper, ~60 lines total), but it is prompt engineering, not a config flip — it warrants a bench confirmation on ch01_sc01 and ch13_sc01 before landing, and ideally a second canon_expert pass on the regenerated ch01_sc01 prose. This is the next PR, not a hotfix.
