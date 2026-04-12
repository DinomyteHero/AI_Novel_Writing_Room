# Implementation Verification Checklist

## Test Suite Delta

- **Baseline**: 883 passed, 9 errors (all in test_pipeline_integration.py, pre-existing)
- **Final**: 884 passed, 9 errors (same pre-existing errors)
- **Delta**: +1 test (replaced `test_advance_arc_phase_same_rejected` with `test_advance_arc_phase_self_transition_allowed`, added `test_canon_violation_is_structural`)
- **No regressions**: All 883 baseline tests continue to pass

## Verification Checks

### 1. data_restructure_proposal.md exists
**PASS** - File exists at project root with all 6 required sections: current layout, proposed layout, migration plan, code changes, CLI changes, backward compatibility.

### 2. Test suite delta
**PASS** - 884 passed (up from 883). 1 test added (`test_canon_violation_is_structural`), 1 test updated (`test_advance_arc_phase_self_transition_allowed`). No tests broken.

### 3. canon_elements_needed no longer a blocking guard
**PASS** - `grep -rn "canon_elements_needed" src/orchestrator.py` shows it only in fallback element extraction (lines 298, 305), not as a blocking condition.

### 4. use_mock not hardcoded True
**PASS** - All three sites now read from config: `embed_cfg.get("use_mock", True)`. Lines 90, 631, 670.

### 5. Arc self-transition uses strict less-than
**PASS** - `story_state.py:1327` reads `if new_idx < current_idx:` (not `<=`).

### 6. Gate Critic has calibration anchors
**PASS** - gate_critic.py contains: "Scoring Instructions", calibration anchors (0.60-0.69, 0.70-0.79, 0.80-0.89, 0.90-1.00), chain-of-thought via "reasoning" JSON field.

### 7. Canon expert model in settings.yaml
**PASS** - `canon_expert: { backend: cloud, model: gemini_flash, params: { temperature: 0.2 } }`. User opted to keep gemini_flash (skip cross-model) but add low temperature for deterministic evaluation.

### 8. Canon expert has zero franchise-specific strings
**PASS** - `grep -n "Star Wars\|Legends\|High Republic\|ABY\|LIDAR" src/agents/canon_expert.py` returns no matches.

### 9. Concept seed has canon_profile
**PASS** - canon_profile populated with: franchise=star_wars, continuity=legends_eu, era_description (post-Abeloth 47 ABY), 6 cross_continuity_violations, 8 anachronistic_terms, 4 meta_reference_rules, franchise_terminology_notes.

### 10. Pipeline order is Prose Stylist -> Canon Expert -> Gate Critic -> Craft Editor
**PASS** - orchestrator.py execution order:
- Line 287: "Prose Stylist drafting..."
- Line 294: "Canon expert validating..." (Step 2.5, before Gate Critic)
- Line 336: "Gate Critic evaluating..." (Step 3)
- Line 339: "Craft Editor polishing..." (Step 4)

### 11. Canon expert returns corrected_prose
**PASS** - canon_expert.py contains 4 references to corrected_prose in the output format and handling.

### 12. Band 2 receives description ratio data
**PASS** - scene_emotion.py extracts `scene_type_distribution` from quality_metrics and injects "DESCRIPTION IMBALANCE" instruction when desc+introspection ratio > 0.60.

### 13. Event density thresholds adjusted
**PASS** - PHASE_DENSITY recalibrated: setup (20.0, 45.0), climax (35.0, 65.0), etc. Comment documents calibration against observed 34-57.5/1k range. No longer flags 100% of scenes.

### 14. Concept Workshop includes canon profile construction
**PASS** - prompts/concept_workshop.md Step 1 now includes "Canon Profile" sub-section with 5 targeted questions (continuity scope, cross-continuity risks, terminology rules, meta-reference rules, era context).

### 15. Contradiction scanner investigation
**FINDING**: NOT a stub. Has 5 real scanning dimensions (truth layer, belief layer, promise/payoff, timeline, relationships). Returns "clean" because: (a) truth layer uses narrow 200-char heuristic window, (b) belief layer needs populated knowledge entries, (c) promise threshold is 10 chapters (8-chapter run can't trigger), (d) timeline needs story_date data, (e) relationships need 5+ chapter gap. TODO comment added documenting findings and proposing LLM-powered upgrade.

## Files Modified

| File | Change |
|------|--------|
| `data_restructure_proposal.md` | NEW: Multi-franchise, multi-run directory structure proposal |
| `implementation_verification.md` | NEW: This verification document |
| `src/orchestrator.py` | Canon expert guard removed, fallback element extraction added, pipeline resequenced (Canon Expert before Gate Critic), dynamic overused words/description ratio injected into Prose Stylist, rejected arc transitions fed to Summarizer, arc state guidance in Summarizer context |
| `src/memory/story_state.py` | Arc self-transition allowed (`<=` to `<`), `initial_phase` read from concept seed, `get_valid_next_phases()` helper added |
| `src/memory/state_diff.py` | `_apply_arc_phase_updates()` returns rejected transitions list, stored as `last_rejected_transitions` |
| `src/memory/contradiction_scanner.py` | Investigation notes and TODO comment added |
| `src/agents/gate_critic.py` | CANON_VIOLATION promoted to STRUCTURAL_CODES, calibration anchors added, chain-of-thought reasoning field, failure code listing updated |
| `src/agents/canon_expert.py` | Full rewrite: franchise-agnostic template-driven agent, reads canon_profile from concept seed, structured JSON output with violations/verdict/corrected_prose |
| `src/quality/milestone_gates.py` | `_fired_milestones` dedup set added |
| `src/quality/pacing_analyzer.py` | PHASE_DENSITY recalibrated from (2-10) to (20-65) range |
| `src/quality/metrics_dashboard.py` | Cross-scene overused word tracker (manuscript-level Counter) |
| `src/revision/line_copy.py` | Structured quality flag extraction (flagged_words, show-don't-tell counts) |
| `src/revision/scene_emotion.py` | Description imbalance rebalancing instruction |
| `src/model_router.py` | Configurable max_retries, jitter added to exponential backoff |
| `src/main.py` | Mock embedding toggle via config, KeyboardInterrupt cleanup fixed |
| `config/settings.yaml` | `max_http_retries`, `embeddings.use_mock` config, canon_expert temperature 0.2 |
| `schemas/concept_seed.json` | `initial_phase` field in weiland_arc, `canon_profile` section |
| `data/projects/the-ruusan-atonement/concept_seed.json` | `initial_phase: "lie_established"` for all 6 characters, full `canon_profile` section |
| `prompts/concept_workshop.md` | Canon profile construction questions in Step 1 |
| `tests/test_character_arcs.py` | `test_advance_arc_phase_self_transition_allowed` (updated from rejection test) |
| `tests/test_failure_codes.py` | `test_canon_violation_is_structural` added, `test_polish_codes_exist` updated |
