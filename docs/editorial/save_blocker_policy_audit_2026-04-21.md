# Save-Blocker Policy Audit — 2026-04-21

Two linked audits surfaced while fixing the canon_expert scene-card-visibility bug ([docs/editorial/scene_card_seed_contradiction_brief_2026-04-21.md](docs/editorial/scene_card_seed_contradiction_brief_2026-04-21.md), PR [b17f409](https://github.com/DinomyteHero/AI_Novel_Writing_Room/commit/b17f409)). Code-and-data-reading only — no pipeline changes.

## TL;DR

**Audit 1 — `stover_permitted`.** Load-bearing but asymmetrically consumed. Canon_expert reads it structurally (post-fix); ProseStylist reads it only indirectly via free-text `scene_card.notes`. The field is NOT redundant with `voice_definition.scene_type_anchor_mapping` — that mapping is scene-type-wide (e.g. `action` → Zahn primary), while `stover_permitted` is a per-scene budget gate on top of whatever anchor dominates. Recommendation: add a structured ProseStylist read for parity with canon_expert, matching the "don't trust the LLM to parse prose when structured data exists" argument used to justify the canon_expert fix.

**Audit 2 — save-blockable category alignment.** Four of six categories align cleanly across prompt / runtime clamp / save-blocker gate. Two leave defensible gaps: `meta_reference` (prompt does not calibrate it; blockable by default) and `era_accuracy` (blockable only if the LLM correctly reclassifies post-divergence facts). Both are low-probability failures today but neither has a runtime safety net if the LLM miscalibrates. Recommended: hold `cross_continuity` / `anachronism` at status quo; consider a structured scene-level `canon_exceptions` field if Ruusan or Betrayal produces a false-positive in either of the two ambiguous categories during the next shipping-book parity run.

---

## Audit 1 — `stover_permitted` consumption

### Matrix

| Dimension | Evidence |
|---|---|
| Ruusan scene cards setting `true` | 14 files (Ch 05/07/09/11/13/15/17/18/20/21/21/24/24/25/26) |
| Ruusan scene cards setting `false` | ~24 files (explicit negative signaling) |
| Betrayal scene cards setting any value | 0 — field is Ruusan-only |
| Runtime reads in `src/` (excluding tests/docs) | 1: [src/agents/canon_expert.py:244](src/agents/canon_expert.py:244) via `_section_scene_card_voice_permissions` |
| ProseStylist read | None. `_scene_voice_contract` ([src/agents/prose_stylist.py:154](src/agents/prose_stylist.py:154)) reads `notes`, `anti_patterns`, `pov_arc_phase` — not `stover_permitted` |
| ContextAssembler read | None for `stover_permitted`. Reads `voice_definition.scene_type_anchor_mapping` ([src/memory/context_assembler.py:558](src/memory/context_assembler.py:558)) — franchise-level mapping |
| Scene card fields equally unread | `primary_anchor`, `supporting_anchor` — 0 src reads |

### Semantic relationship with `scene_type_anchor_mapping`

The mapping is a franchise-level default: e.g. `action` → `primary=Zahn`. The scene card can override via `primary_anchor` (Ch 07 Sc 02: `scene_type: "action"`, `primary_anchor: "Luceno"`) AND separately unlock a Stover beat via `stover_permitted: true`. The three fields encode three different signals:

- `scene_type_anchor_mapping[scene_type]` — which anchor leads this kind of scene franchise-wide.
- `scene_card.primary_anchor` — which anchor leads THIS specific scene (can diverge from the default).
- `scene_card.stover_permitted` — whether any Stover-register beat is budgeted for this scene, regardless of primary anchor.

`anti_slop_rules` rule #5 explicitly names this as a budget control: *"One Stover-permitted interior beat per chapter maximum outside Ch 13 / 25 / 26 (extended allowances there). Scene-card marker: `stover_permitted: true`."*

### Verdict

**Hypothesis (b) — load-bearing but under-consumed.** Not redundant with the anchor mapping; they encode different axes. The signal currently reaches the drafter only via `scene_card.notes` (free-text prose, e.g. Ch 07 Sc 02: *"one permitted Stover-interior beat when Ben reads the Veranthos warning notation"*), which requires LLM interpretation and has no structural enforcement on `false` cases.

### Recommendation

Add a structured ProseStylist read — surface `stover_permitted` (and the Ch 13/25/26 extended-allowance override) in the Scene Voice Contract block, paralleling the canon_expert fix. Same defense-in-depth rationale: don't trust the LLM to parse free-text when structured data exists, especially for negative gates (`stover_permitted: false` is currently invisible to the drafter as structure; the budget is enforced only by canon_expert flagging afterwards, which is now clamped to advisory-minor anyway).

Scope note: `primary_anchor` / `supporting_anchor` are equally unread. Fixing only `stover_permitted` leaves the broader pattern (scene cards authoring structured voice metadata that no agent consumes structurally) unresolved. Worth a single pass.

---

## Audit 2 — Save-blockable category alignment

### Matrix

| Category | Prompt policy (canon_expert.md §Severity Calibration) | `_normalize_output` clamp | `save_blockers.py` gate | Aligned? |
|---|---|---|---|---|
| `cross_continuity` | Critical example explicitly listed ("character appearing before introduction") | None | Block at critical/moderate | ✅ |
| `anachronism` | Critical example explicitly listed ("franchise-era anachronism") | None | Block at critical/moderate | ✅ |
| `meta_reference` | **Not calibrated** — category listed in output schema but §Severity Calibration silent | None | Block at critical/moderate | ⚠️ Prompt silent |
| `era_accuracy` | Critical example overlaps "franchise-era anachronism"; branch_point path reclassifies to `post_divergence_drift` minor | None (relies on LLM to reclassify) | Block at critical/moderate | ⚠️ Trust-the-LLM |
| `franchise_voice` | Explicit minor ("surface-level drift ... advisory only") | Clamp to minor + re-derive verdict | Gate unchanged (clamp prevents block) | ✅ (post-b17f409) |
| `post_divergence_drift` | Explicit minor ("MUST use severity minor and NEVER cause fail") | Clamp to minor + re-derive verdict | Explicit skip: `if category == "post_divergence_drift": continue` ([src/pipeline/save_blockers.py:177](src/pipeline/save_blockers.py:177)) | ✅ Triple-aligned |

### Disagreements surfaced

**1. `meta_reference` — prompt undercalibrated.** The prompt lists `meta_reference` as a category in the output schema ([canon_expert.md:34](prompts/agent_system_prompts/canon_expert.md:34)) and the generic header for Check 3 says *"flag any references where characters appear to have knowledge of being in a story"* ([src/agents/canon_expert.py:372](src/agents/canon_expert.py:372)), but §Severity Calibration does not name it in any tier. The LLM is free to emit any severity. Ruusan's `meta_reference_rules` in the canon_profile ([concept_seed.json:2216](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json:2216)) includes ABY/BBY dating conventions and "Legends/Canon" terminology — these ARE genuine canon violations. But a scene intentionally staging a register-bending fourth-wall adjacency (e.g. a character quoting a Jedi parable that echoes a meta-reference) has no override path; it blocks at moderate.

**2. `era_accuracy` — branch_point reclassification is LLM-trust-only.** The flow says: if a violating fact belongs to source canon after `branch_point.divergence_point`, the LLM SHOULD reclassify as `post_divergence_drift` + minor ([src/agents/canon_expert.py:420](src/agents/canon_expert.py:420)). If the LLM fails to reclassify and emits `era_accuracy: critical`, the save-blocker fires — even though the intended policy is "minor". No runtime safety net exists: `_normalize_output` doesn't auto-reclassify, and `save_blockers.py` doesn't re-read branch_point. A misclassifying LLM can quarantine a legitimate AU scene.

### Scene-level override possibility

None exists today for these four categories. `stover_permitted` is the only per-scene voice-register whitelist; there is no `canon_exceptions: ["meta_reference"]` or equivalent. A scene intentionally including a meta-reference (per concept_seed's definition) cannot whitelist it.

### Verdict per category

- `cross_continuity` — **keep blockable.** Factual contradiction; prompt calibrated; no case for override.
- `anachronism` — **keep blockable.** Anachronistic-terms map is explicit and narrow; false positives easy to fix by author.
- `meta_reference` — **risk acknowledged; no action yet.** Prompt should explicitly calibrate this (one-line edit) but not our scope. Elevate if a false positive lands on Ruusan/Betrayal parity.
- `era_accuracy` — **risk acknowledged; no action yet.** Branch_point reclassification works in practice (Ruusan passes Phase 0 today). Add runtime safety only if a quarantine fires on a legitimate AU scene.
- `franchise_voice` — **aligned post-b17f409.** No action.
- `post_divergence_drift` — **triple-aligned.** No action; guardrails correctly redundant.

### Ranked recommendations

1. **(Do nothing, highest priority).** Four of six categories align. The two with ambiguity have no observed false-positive incidents; acting now is speculative engineering.
2. **One-line prompt edit.** Add an explicit severity calibration sentence for `meta_reference` in [canon_expert.md](prompts/agent_system_prompts/canon_expert.md) §Severity Calibration ("meta_reference severity follows the critical/moderate/minor tiers above; intentional fourth-wall adjacency authored in scene_card.notes is not a violation"). Zero code change, clarifies the policy. Low risk.
3. **Deferred — structured `canon_exceptions` scene-card field.** If Ruusan or Betrayal parity run produces a quarantine on an intentional meta_reference or a post-divergence era fact the LLM miscategorizes, introduce a per-scene whitelist. Parallel to `stover_permitted`. Do not build speculatively.

---

## Combined recommendations

Both audits share the theme **"scene-level structured overrides are missing across the board"**. Canon_expert now reads `stover_permitted`; ProseStylist does not. Scene cards have `primary_anchor` / `supporting_anchor` / `stover_permitted` / `anti_patterns` — only the last is consumed in both relevant agents. The broader pattern — authors write structured voice metadata, pipeline consumes it inconsistently — deserves a single-sweep fix rather than per-bug patching.

Pragmatic next step: one small PR hoists `stover_permitted` (and optionally `primary_anchor`) into ProseStylist's Scene Voice Contract. Defers the `canon_exceptions` mechanism until a concrete quarantine forces it.

## Out of scope / next steps

- **Scene-card schema validation.** Nothing validates `stover_permitted` as a bool or `primary_anchor` against the anchor enum. A bad value silently becomes LLM-trust-only. Worth a follow-up when schema validation is prioritized.
- **Free-text `notes` reliability.** PR [b17f409](https://github.com/DinomyteHero/AI_Novel_Writing_Room/commit/b17f409) notes this as an open risk: canon_expert surfaces notes verbatim and trusts the LLM. If a future canon_expert model interprets notes differently, the seed-contradiction brief proposes a structured `voice_exceptions` schema — same solution shape as `canon_exceptions` here. Unify the design if/when either lands.
- **Betrayal parity run.** `stover_permitted` is Ruusan-only today. If Betrayal's voice rules evolve to require a similar register-intensity budget, re-evaluate whether the field generalizes or needs a neutral rename (e.g. `register_intensity_permitted`).
