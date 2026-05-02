# Scene Card ↔ Seed Voice-Policy Alignment — Brief

**First written:** 2026-04-21, during Gate 4 of the diagnostic-voice fix.
**Revised:** 2026-04-21, after Codex review corrected two framing errors and identified a second blocker-class bug.
**Status:** Resolved in this PR (commit `<diagnostic-voice-followup>`). Regression-tested. Follow-up audit of other scene-level voice permissions (`stover_permitted`, free-text notes) still open.

---

## 1. The trigger event

After the first diagnostic-voice fix (three-edit commit) landed, bench-regenerated prose for Ruusan Ch 01 Sc 01 at Claude Sonnet 4.6 t=0.80 was:

- Free of all 6 baseline hard violations (`since Tuesday`, `lift chimes`, `the Force's`, `second beat`, `confirmation came`, `echo from`).
- In-register: tactile, body-first, self-deprecating close third.
- Faithful to the scene card's instruction to use one consistent metaphor — "the half-beat lag in the ambient field" — rendered as *"the ambient field had arrived late, like a chord struck and then heard."*

Canon_expert still returned `verdict: fail` with five moderate `franchise_voice` violations, all citing the scene-card-authorized metaphors. This triggered the investigation.

---

## 2. What was actually wrong (Codex review corrected the first brief)

### Bug 1 — seed-field mismatch (my Edit C was a no-op)

The franchise terminology rules live at `concept_seed.canon_profile.franchise_terminology_notes` per the schema and the Ruusan seed (line 2222 inside the `canon_profile` block that opens at line 2161). Canon_expert reads the correct path at [canon_expert.py:382](../../src/agents/canon_expert.py:382).

My Edit C in ContextAssembler read `concept_seed.canon_constraints.franchise_terminology_notes` — **the wrong key**. `canon_constraints` is a separate block starting at line 2349 and does not contain this field. Edit C was effectively dead code. The drafter was NEVER seeing the same franchise rule canon_expert was enforcing.

**Fix:** re-pointed ContextAssembler at `canon_profile.franchise_terminology_notes`. Regression test at [test_context_assembler.py](../../tests/test_context_assembler.py) pins the correct path and guards against a regression back to `canon_constraints`.

### Bug 2 — canon_expert ignored the scene card it already received

The orchestrator has always passed `scene_card` into `canon_expert.evaluate()` via the context dict. My first brief claimed "the orchestrator needs to pass scene_card." That was wrong — it already does. The bug is inside canon_expert:

- `evaluate()` pulled `concept_seed` out of context but dropped `scene_card`.
- `_format_context()` (the legacy path used via `BaseAgent.run()`) did the same.
- `_build_evaluation_prompt()` only consumed `concept_seed.canon_profile`.
- Scene_card was used only by `_retrieve_evidence_block` for RAG lookup on `canon_elements_needed`.

So canon_expert evaluated prose against franchise rules with zero visibility into scene-level permissions, even though those permissions were sitting in its context dict. When the drafter faithfully used the scene card's authorized "ambient field" metaphor, canon_expert had no way to know that metaphor was pre-approved.

**Fix:** `_build_evaluation_prompt()` now takes a `scene_card` parameter. A new `_section_scene_card_voice_permissions(scene_card)` method renders scene_card.notes, `stover_permitted`, and anti_patterns into a `## Scene-Level Voice Permissions (READ BEFORE FLAGGING FRANCHISE_VOICE)` section placed before the franchise checks. Both entry paths (`evaluate()` and `_format_context()`) now propagate scene_card through. Regression tests at [test_canon_expert_branch_point.py::TestSceneCardVoicePermissions](../../tests/test_canon_expert_branch_point.py) assert the section renders correctly.

### Bug 3 — franchise_voice severity never clamped (NEW, surfaced by Codex)

The canon_expert system prompt calibrates `franchise_voice` as advisory surface-drift — it should be `minor`. But `_normalize_output()` only clamped `post_divergence_drift` to minor. Meanwhile [save_blockers.py:165-180](../../src/pipeline/save_blockers.py:165) treated any `moderate` or `critical` violation outside `post_divergence_drift` as a hard block.

Mechanical consequence: the LLM could emit `franchise_voice` at `moderate` and the save-blocker fires, contradicting the prompt's own policy. In production (`firewall.enabled: true`) this would quarantine the scene; in Ruusan default (`firewall.enabled: false`) it would abort the run.

**Fix:** `_normalize_output()` now treats `post_divergence_drift` AND `franchise_voice` as advisory. Severity clamped to `minor`; never contributes to fail verdict. Verdict is now ALWAYS derived from normalized (advisory-clamped) violations — the LLM's stated verdict is advisory input only. Regression tests at [test_canon_expert_branch_point.py::TestFranchiseVoiceSeverityPolicy](../../tests/test_canon_expert_branch_point.py) pin this behavior for both `moderate` and `critical` franchise_voice flags.

---

## 3. Who reads what (corrected model)

```
SCENE CARD                    SEED (canon_profile)
  (per-scene notes)             (franchise-wide rules)
        |                                |
        |                                |
        v                                v
  prose_stylist                    prose_stylist
  — sees via Edit A's               — sees via ContextAssembler
    Scene Voice Contract              (reads canon_profile, POST-FIX)
        |                                |
        +-----> drafter sees both <------+


  canon_expert (save-blocker)
  — scene_card: POST-FIX now consumed via _section_scene_card_voice_permissions
  — canon_profile: always read via _section_* methods
  — advisory categories (post_divergence_drift, franchise_voice): clamped to minor
```

Pre-fix, canon_expert read franchise rules but not scene permissions. Drafter's view and save-blocker's view diverged. Post-fix, both see the full picture.

---

## 4. Why this mattered in production

Canon_expert is a save-blocker per CLAUDE.md:

> Save-blocker layer: Three categories: CHARACTER_PRESENCE_BLOCKER, CANON_BLOCKER (CanonExpert verdict = fail + severity ∈ {critical, moderate}), and a POV advisory.

A canon_expert verdict of `fail` with moderate severity blocks the scene from saving. Before the fix, a drafter that faithfully honored its scene card's authorized metaphors would produce a scene that canon_expert flagged as drift and the pipeline refused to save.

Two failure modes converged:
1. **False-positive franchise_voice flags.** LLM emits `franchise_voice: moderate` citing the scene card's own authorized metaphor; clamping absent, save blocked.
2. **Scene-card-invisible evaluation.** Even if franchise_voice were clamped, the LLM with no scene-card context still produces noisy output. Without permissions surfaced, the LLM has no basis to whitelist the scene-level register.

The fix needs BOTH: surface scene permissions (so the LLM doesn't flag) AND clamp franchise_voice (so any residual flags can't block). Defense in depth.

---

## 5. Out-of-scope follow-ups

### `stover_permitted` is authored but unread

Scene cards set `stover_permitted: true` on Ch 07 Sc 02, Ch 24 Sc 03, and likely others (Ch 13 midpoint, Ch 25/26 climax per the voice-rules scene-type mapping). Grep finds zero runtime consumers in `src/`. Canon_expert now reads it after this fix; nothing else does.

Audit needed: does ProseStylist need to read `stover_permitted` to unlock its register explicitly, or is the existing `scene_type_anchor_mapping` in voice_definition sufficient? If the latter, `stover_permitted` on the scene card is redundant auxiliary data. If the former, there's a missing read path.

### Free-text voice permissions in scene cards

Ruusan has many scene-level voice overrides in the free-text `notes` field beyond Ch 01 Sc 01 (e.g. permitted metaphor domains, tone anchors, register intensity). Canon_expert now surfaces the notes verbatim and trusts the LLM to interpret them as permissions. This works at the quality bench showed, but:

- A future canon_expert model change could interpret notes differently.
- A scene card with conflicting permissions (notes say X, `stover_permitted` says Y) has no resolution policy.

If this proves unreliable, escalate to a structured `voice_exceptions` / `metaphor_permissions` schema field — the "Option 2" path from the first brief, now with Codex's corrected framing.

### Other save-blocking categories

After clamping franchise_voice, the remaining blockable categories are `cross_continuity`, `anachronism`, `meta_reference`, and `era_accuracy`. Worth auditing: are any of these also advisory by design in the prompt but not clamped in code? Quick scan of [canon_expert.md:55-59](../../prompts/agent_system_prompts/canon_expert.md) suggests no — cross_continuity and anachronism are genuinely factual violations. But worth a look at the next revision.

---

## 6. Verification

| Gate | Result |
|---|---|
| Full pytest regression | ✅ 1772 passed, 2 skipped, zero new failures (+9 tests added) |
| Phase 0 audit (Ruusan + Betrayal) | ✅ 22/22 pass |
| New regression tests | ✅ `test_voice_rules_surface_franchise_terminology_notes_from_canon_profile` pins the seed path; `TestFranchiseVoiceSeverityPolicy` pins the clamp; `TestSceneCardVoicePermissions` pins the scene-card visibility in both entry paths |

Live canon_expert re-check against the post-first-fix bench prose was not re-run — the three code/test changes land the behavior change deterministically, and re-spending ~$0.06 on a live call would only verify the LLM exercises the new prompt structure correctly (which the unit tests already cover structurally).

---

## 7. What was learned

- **Trust-but-verify applies to my own fixes.** Edit C shipped as a no-op because the seed-field location wasn't verified in the source. Writing regression tests that pin the path would have caught this immediately.
- **Agents in the same pipeline should share the same view of scene permissions.** Gate_critic, final_gate, quality_polish all serialize the full scene card into their prompts. Canon_expert was the outlier. Any new save-blocker agent added in the future should surface the full scene card by default.
- **Advisory-class categories must be enforced in code, not just in the prompt.** The prompt's severity calibration is hint only; the runtime must clamp or the LLM can bypass the policy unintentionally.
