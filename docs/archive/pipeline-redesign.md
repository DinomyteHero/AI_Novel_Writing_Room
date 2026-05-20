# Pipeline Redesign

> **Archived 2026-05-19 — superseded by the lean teardown.** The forward-only relay this brief designed (gates, save-blockers, compression guard, quarantine, Final Gate) has been removed from the codebase. For the current lean single-pass pipeline see [CLAUDE.md](../../CLAUDE.md) and [agent-pipeline.md](../architecture/agent-pipeline.md). The body below is retained for design-decision history only.

> ## ⚠️ STATUS: HISTORICAL DESIGN BRIEF
>
> This document is the **planning brief** that drove the redesign — not a description of the shipped system. Retained for design-decision history and traceability, but **do not rely on the body below as current documentation**.
>
> **For current pipeline behavior, see [`docs/architecture/agent-pipeline.md`](./agent-pipeline.md).**
>
> What the shipped system actually does (Relay v3, 2026-04-19+):
>
> - **Forward-only relay, no retries.** `max_structural_retries` and `max_voice_retries` are pinned to `0` in `config/settings.yaml`. Retry branches were removed, not disabled.
> - **Gates run as telemetry.** Both `GateCritic` and `FinalGate` log verdicts to the ledger but never block or loop. Their verdicts feed the `saved_with_advisory` status, not save/reject control flow.
> - **Compression guard is revert-on-regression.** Polish output that compresses below 60% of pre-polish word count emits a `compression_guard_fired` warn event with `reverted: true`; the orchestrator keeps the gate-passed draft and downstream checks evaluate that reverted prose. The 80% floor remains as a soft instruction to the polish model.
> - **Save-blocker layer is the single hard-failure path** (`src/pipeline/save_blockers.py`). Three categories: `CHARACTER_PRESENCE_BLOCKER`, `CANON_BLOCKER` (critical or moderate), POV advisory (non-blocking in v1). When a blocker fires, the scene quarantines to `<run>/quarantine/chNN_scMM/{prose.md, blockers.json, brief.json}` and the run aborts.
> - **Canonical relay order:** `PlotArchitect → ProseStylist → [LineWriter] → GateCritic → QualityMetrics → QualityPolish → compression guard → FinalGate → CanonExpert → save-blocker layer → save | quarantine`. CanonExpert is the continuity editor on the current post-polish prose, which may be the gate-passed draft if the compression guard reverted severe collapse.
> - **Saved-scene status vocabulary:** `saved_clean`, `saved_with_advisory`, `quarantined`. The five-value legacy vocabulary (`gate_passed`, `polished`, `approved`, `gate_failed`, `gate_skipped`, `final_gate_rejected`) is gone; `scripts/migrations/migrate_status_vocab.py` auto-migrates existing databases.
> - **Chapter-level word-count drift** is tracked by `src/pipeline/word_count_telemetry.py` (±15% info, 15–30% warn, >30% error) and is not part of the scene gate taxonomy.
>
> The design intent captured below (single bounded polisher, typed generation brief, chapter blueprints, scene cards as contract, "final saved prose is the unit of truth") is the foundation of the shipped relay — but the enforcement model shifted from retry-and-reject to telemetry-and-quarantine during Stages 1a–1f. Sections that still describe retry loops, polish rejection, or Final Gate as binding are **superseded** and should be read as historical intent, not current behavior.

---

## Original brief (historical)

Working implementation brief for the execution pipeline, planning layer, and validation contract redesign. Supersedes the current post-gate rewrite stack and adds the missing chapter-level planning artifact.

## Problem statement

### The core contract violation

The pipeline gates one version of a scene, then saves a different one.

```
Gate evaluates:   Prose Stylist output (text A)
Metrics score:    Craft Editor output  (text B)
Saved file:       Revision Pipeline output (text C)
```

No quality check runs on the final saved text. Post-gate stages (Craft Editor + 3 revision bands) are full generative rewriters that can add characters, remove beats, and collapse word counts — all without validation.

### Ledger evidence

Prose Stylist output vs final saved file across runs 15-19:

| Run | Scene | Prose Stylist | Final saved | Delta | What happened |
|-----|------:|-------------:|------------:|------:|---------------|
| 15  |   1.1 |        1,174 |         986 |  -188 | Band 3 cut 189 words |
| 15  |   1.2 |          937 |         843 |   -94 | Band 2 cut 75, Band 3 cut 19 |
| 15  |   1.3 |        1,173 |       1,017 |  -156 | Band 3 cut 156 words |
| 16  |   1.1 |        1,159 |         943 |  -216 | Band 3 cut 210 words |
| 16  |   1.2 |        1,299 |         805 |  -494 | Craft cut 434, bands cut 60 |
| 17  |   1.1 |        1,196 |         714 |  -482 | Craft cut 567, bands added 85 |
| 17  |   1.2 |        1,128 |         718 |  -410 | Craft cut 391, bands cut 19 |

The Prose Stylist consistently produces 1,100-1,200 word drafts (88-96% of target). Post-gate stages then destroy 200-500 words.

### Baseline proof (run19)

Run19 used `--raw-draft` mode: Plot Architect, Prose Stylist, Gate Critic, save. No Craft Editor, no revision bands.

| Run | S1 | S2 | S3 | Total | Post-gate stages |
|-----|---:|---:|---:|------:|------------------|
| 15  | 986 | 843 | 1,017 | 2,846 | craft + 3 bands |
| 16  | 943 | 805 | 1,053 | 2,801 | craft + 3 bands |
| 17  | 714 | 718 | 1,122 | 2,554 | craft + 3 bands |
| **19** | **1,192** | **1,125** | **1,198** | **3,515** | **none** |

Quality metrics with no post-gate processing are comparable or better (scene 2 quality: 0.75 with full pipeline vs 0.80 baseline; show-don't-tell violations: 6 vs 1).

The writer+gate loop can stand on its own. The post-gate stack is currently net-negative.

## Design principles

1. **The final saved prose is the unit of truth.** Any quality check that does not run on the saved file is advisory, not binding.
2. **Any stage that can change scene content is a writer, not a polisher.** If it can add/remove beats or characters, it belongs in the writer rewrite loop, not in post-pass polish.
3. **Each planning layer gets exactly one persisted artifact.** Story-wide truth in `concept_seed`, chapter-level planning in `chapter_blueprint`, scene-level contracts in `scene_card`.
4. **Metrics advise; contracts block.** Metrics surface issues. Contract checks (wrong characters, missing turning point, word count violation) are deterministic blockers.
5. **One primary writer owns scene prose; critics diagnose, not re-author.** Reduce sequential generative rewriters from 4+ to 1 optional bounded polisher.

## Target architecture

```
Planning:
  concept_seed ──> chapter_blueprint ──> scene_card ──> typed generation_brief

Execution (per scene):
  Plot Architect (LLM)         ──> typed generation brief
  Prose Stylist (LLM)          ──> first draft
  Word count + sanity (CODE)   ──> reject if outside tolerance
  Scene Gate (LLM + CODE)      ──> structural/voice/contract evaluation
    fail_structural            ──> writer rewrite loop (back to Prose Stylist)
    fail_voice                 ──> writer rewrite with voice feedback
    pass / fail_polish         ──> continue
  Quality Metrics (CODE)       ──> measurement (feeds polish)
  Quality Polish (LLM)         ──> diff-bounded expression edits only
  Final Gate (LLM)             ──> contract check on actual polished text
    fail                       ──> reject polish, keep gate-passed draft
    pass                       ──> save
  Save + summarize + state update

Validation (per chapter):
  Chapter Gate (LLM)           ──> blueprint-aware chapter evaluation
```

### Current pipeline (for comparison)

```
Plot Architect → Prose Stylist → Gate Critic → Craft Editor
→ Quality Metrics → Band 1 (structural) → Band 2 (emotion)
→ Band 3 (line copy) → save
```

7+ LLM calls per scene, 4 of which are unvalidated generative rewriters. Gate evaluates pre-craft text. Metrics score pre-revision text. Saved file is post-revision.

### Target pipeline

```
Plot Architect → Prose Stylist → CODE checks → Scene Gate
→ (rewrite loop) → Quality Metrics → Quality Polish
→ Final Gate → save
```

4-5 LLM calls per scene. One optional bounded polisher. Final Gate validates the actual saved artifact.

## Planning layer

### Chapter blueprint schema

New artifact: `schemas/chapter_blueprint.json`

Storage: `data/franchises/{franchise}/books/{book}/chapter_blueprints/chapter_{NN}.json`

```json
{
  "chapter_number": 1,
  "chapter_mission": "Establish Ben's restlessness and the wrongness, launch the investigation",
  "chapter_turn": "Ben moves from passive unease to active pursuit with institutional cover",
  "structural_phase": "setup",
  "pov_allocation": ["Ben Skywalker"],
  "scene_count": 3,
  "scene_plan": [
    {
      "scene_number": 1,
      "role": "hook",
      "dialogue_expectation": "interior",
      "target_word_count": 1250,
      "purpose": "Establish wrongness through physical failure in sparring"
    },
    {
      "scene_number": 2,
      "role": "decision",
      "dialogue_expectation": "dialogue_led",
      "target_word_count": 1250,
      "purpose": "Father-son scene: Luke validates Ben's read, assigns the mission"
    },
    {
      "scene_number": 3,
      "role": "escalation",
      "dialogue_expectation": "balanced",
      "target_word_count": 1250,
      "purpose": "Ben chooses Desh over Jedi partner, departs, wrongness has direction"
    }
  ],
  "reveal_payload": ["R01"],
  "hook_movements": {
    "planted": ["H01"],
    "advanced": [],
    "resolved": []
  },
  "subplot_obligations": ["SP-A", "SP4"],
  "relationship_turns": [
    {
      "dyad": "Ben/Luke",
      "from": "institutional distance",
      "to": "private alliance"
    },
    {
      "dyad": "Ben/Desh",
      "from": "dormant contact",
      "to": "operational partnership"
    }
  ],
  "pacing_curve": "rising",
  "exit_vector": "Ben in hyperspace, wrongness pulling not just pointing — active, not ambient",
  "chapter_word_target": 3750,
  "notes": "R01 lands at end of scene 3. Chapter ends with the wrongness transforming from background to foreground."
}
```

Required fields: `chapter_number`, `chapter_mission`, `chapter_turn`, `structural_phase`, `scene_count`, `scene_plan`, `chapter_word_target`.

Scene cards remain the scene-level drafting contract. Blueprints own chapter-level orchestration that scene cards cannot naturally carry.

### Source-of-truth boundaries

| Artifact | Owns | Does not own |
|----------|------|--------------|
| `concept_seed` | Premise, cast, arcs, voice, hooks, revelations, subplots, canon, terminology | Chapter plans, scene-level contracts |
| `chapter_blueprint` | Chapter mission, turn, reveal schedule, subplot obligations, pacing, exit vector | Scene-level beats, prose control |
| `scene_card` | Scene mission, conflict, turning point, characters, hooks, word budget, dialogue expectation | Chapter-level orchestration |

Embedded scene cards in `concept_seed` (schema line 389) become workshop-only intermediates. Extracted scene card files are canonical. Compliance validator stops reading embedded cards as planning truth.

## Execution layer

### Typed generation brief schema

New artifact: `schemas/generation_brief.json`

Replaces the 8-section free-text brief from Plot Architect. Typed structure at the top, free text at the leaves.

```json
{
  "scene_objective": "string — what this scene must accomplish structurally",
  "opening_mode": "string — how to open (in medias res, sensory hook, dialogue, contrast)",
  "key_beats": [
    {
      "beat_description": "string",
      "state_change": "string — what changes",
      "pov_reaction": "string — POV internal response"
    }
  ],
  "turning_point": {
    "trigger": "string — what causes the turn",
    "shift": "string — how dynamics change",
    "cost": "string — what the turn costs"
  },
  "closing_beat": "string — derived from scene_card.closing_hook",
  "emotional_arc": {
    "start": "string",
    "shift": "string",
    "end": "string"
  },
  "voice_guidance": "string — sentence rhythm, vocabulary, tonal palette",
  "forbidden_moves": ["string — things that must NOT happen"],
  "delivery_preferences": {
    "reveal_mode": "string — direct/gradual/subtext",
    "exposition_budget": "string — concise/moderate/none",
    "register_override": "string or null"
  },
  "required_hooks": ["string — hook_ids to plant/advance/resolve"],
  "required_subplots": ["string — subplot_ids to touch"],
  "required_revelations": ["string — revelation_ids to deliver"],
  "anti_patterns": ["string — extracted from scene_card notes"],
  "target_word_count": 1250
}
```

This makes the planner-to-drafter handoff reproducible and diffable. Anti-patterns from scene card `notes` are extracted and surfaced with explicit salience rather than buried in a JSON blob.

### Pipeline contract

> **Historical — superseded by the shipped relay.** The table below describes the retry-and-reject model that was planned. The shipped pipeline is forward-only: gate verdicts and Final Gate rejections are logged as telemetry and never loop back to Prose Stylist. The compression guard is the narrow exception that may keep the gate-passed draft when polish collapses below 60%. Enforcement otherwise moved to the save-blocker layer. See `docs/architecture/agent-pipeline.md` for the current per-stage contracts.

Each step has an explicit scope: what it owns, what it cannot change, and how violations are enforced.

| Step | Agent | Owns | Cannot change | Enforcement |
|------|-------|------|---------------|-------------|
| 1 | Plot Architect | Generation brief | — | Schema validation |
| 2 | Prose Stylist | Scene prose | — | — |
| 3 | CODE | Word count check | — | Programmatic: if outside ±20%, inject `WORD_COUNT_VIOLATION` |
| 4 | Scene Gate | Pass/fail evaluation | Prose text | Verdict derived from failure codes (existing fix) |
| 5 | Prose Stylist | Rewrite (if gate fails) | — | Gate re-evaluates |
| 6 | CODE | Quality metrics | — | Produces flags + counts for polish |
| 7 | Quality Polish | Expression-level edits | Beats, characters, structure, turning point, scene boundary | Final Gate catches violations |
| 8 | Final Gate | Pass/fail on saved text | — | If fail: reject polish, keep gate-passed draft |
| 9 | CODE | Save + summarize | — | — |

### Quality polish contract

> **Historical on enforcement, accurate on scope.** The CAN/CANNOT lists below still describe what QualityPolish is allowed to do. But the **enforcement row is superseded**: Final Gate no longer rejects polish output (it is advisory only), and the compression guard now reverts only on severe collapse (<60% of the gate-passed draft). The prompt still instructs the model to respect the 80% floor.

The single post-gate polish pass replaces Craft Editor + 3 revision bands.

**CAN do:**
- Fix show-don't-tell violations (rewrite told emotions as shown)
- Improve word choice precision (vague → specific)
- Remove AI-tell phrases from constraints list
- Vary sentence rhythm and paragraph length
- Fix typos and grammar
- Improve dialogue tags (adverb-heavy → action beats)

**CANNOT do:**
- Add or remove story beats
- Add or remove characters
- Change the turning point or its execution
- Alter the scene's structural arc
- Extend past the closing hook boundary
- Introduce information not in the generation brief

**Enforcement:** Final Gate evaluates the polished text against the scene card contract. If violations are detected (character presence, closing hook drift, structural regression), the polish output is rejected and the Scene-Gate-passed draft is saved instead.

**Prompt receives:**
- The gate-passed prose (input)
- Quality metric results with specific flags
- Scene card hard constraints (characters_present, closing_hook, target_word_count)
- The pre-polish word count and minimum floor (do not compress below input)

### Model architecture

Current state: 7+ model families touch each scene's prose (Gemini, Claude, Haiku, Kimi, Mistral, DeepSeek, Grok).

Target: single-writer, multi-critic.

| Role | Model | Rationale |
|------|-------|-----------|
| Primary writer (prose_stylist + rewrite) | Claude Sonnet | Strongest prose quality in testing |
| Scene Gate / Final Gate | Haiku (or same family) | Fast, cheap, sufficient for evaluation |
| Quality Polish | Same family as writer | Minimizes style drift |
| Plot Architect | Can differ (Gemini fine) | Planning, not prose generation |
| Summarizer / diagnostics | Can differ | Not touching scene prose |

Key principle: only one model family writes or rewrites scene prose. Critics/evaluators can differ.

## Validation layer

### Scene Gate

Evaluates the Prose Stylist's draft against:
- Scene card contract (mission, turning point, characters, hooks, closing boundary)
- Typed generation brief (if available)
- Pre-computed word count (programmatic injection — not relying on LLM to count)

Programmatic word-count enforcement: if `abs(actual - target) / target > 0.20`, inject `WORD_COUNT_VIOLATION` into `failure_codes` before `determine_verdict()` runs. This is deterministic and cannot be ignored by the gate model.

### Final Gate

> **Historical — Final Gate is now advisory.** In the shipped relay, Final Gate still evaluates the polish output against the scene card contract, but it does not reject or revert. Rejections emit `final_gate_rejection` with `advisory_only=True` and the polished prose is saved unless the compression guard has already reverted to the gate-passed draft. The character-presence check migrated to a dedicated `PresenceChecker` agent inside the save-blocker layer, which is the only hard blocker.

Evaluates the Quality Polish output against:
- Scene card contract (same checks as Scene Gate)
- Additional check: character presence (`characters_present` only)
- Additional check: closing hook boundary (no content beyond `closing_hook`)
- Additional check: word count floor (polished text must not be below 80% of gate-passed text)

If Final Gate fails: reject polish output, save the Scene-Gate-passed draft instead. Log the rejection for diagnostics.

### Chapter Gate

Evaluates the full chapter (all scenes) against:
- Chapter blueprint (if present; graceful fallback if absent)
- Checks: chapter mission achieved, chapter turn landed, reveal payload delivered, subplot obligations touched, pressure curve matches, exit vector reached

Currently `ChapterGateCritic` evaluates only generic composition heuristics. With blueprints, it validates chapter intent.

## Implementation sequence

Ordered by impact. Execution stability before planning enhancements.

### Phase 1 — Execution stabilization

Most urgent. Fixes the "validates wrong artifact" problem.

1. **Add Final Gate on actual saved text.** Highest-leverage single fix. New agent or reuse Gate Critic with a "final check" mode. ~50 lines in orchestrator + prompt.

2. **Collapse Craft Editor + 3 bands into Quality Polish.** Replace `craft_editor.py` + `pipeline.py` + 3 band agents with one `quality_polish.py` agent. Merge prompts into `quality_polish.md`. ~100 lines of new code, deprecate ~400 lines.

3. **Add programmatic word-count enforcement at gate.** Compute ratio in `gate_critic.py`, inject `WORD_COUNT_VIOLATION` into `failure_codes` if outside ±20%. ~15 lines.

4. **Add post-polish compression guard.** In orchestrator: if polished text < 80% of gate-passed text word count, reject polish. ~10 lines.

### Phase 2 — Planning contracts

5. **Define and implement typed `generation_brief` schema.** New JSON schema. Update `plot_architect.py` to emit structured brief. Update `prose_stylist.py` to consume it. ~100 lines.

6. **Define `chapter_blueprint` schema.** New JSON schema at `schemas/chapter_blueprint.json`. ~50 lines.

7. **Manually author chapter 1 blueprint for Ruusan.** Reverse-derive from existing scene cards. One JSON file. ~40 lines.

### Phase 3 — Wiring

8. **Wire Plot Architect to emit typed brief.** Update `plot_architect.py` and `plot_architect.md`. ~60 lines.

9. **Wire Chapter Gate Critic to consume blueprints.** Update `chapter_gate_critic.py` to optionally load and validate against blueprint. ~80 lines. **Landed in Phase 5** of the historical rollout roadmap (see `docs/archive/implementation-roadmap.md`); also added `src/planning/chapter_blueprint_generator.py` so blueprints auto-generate from scene cards when none exist on disk. Critic remains advisory.

10. **Source-of-truth cleanup.** Update `compliance_validator.py` to stop reading embedded concept-seed scene cards as canonical. Mark embedded scene_cards in schema as workshop-only. ~30 lines.

### Phase 4 — Polish

11. **Attempt-scoping in ledger.** Add `attempt_id` to `run_ledger` schema. Small schema migration. ~20 lines.

12. **Richer metric outputs.** Extend `MetricsDashboard` to emit paragraph-level locations for show-don't-tell, repetition, and overused words. ~50 lines.

13. **Patch/span replacement for polish (if needed).** Only if full-prose polish proves unreliable after Final Gate is in place. Deferred.

## Migration plan

### Phase 1 files

| File | Action | Notes |
|------|--------|-------|
| `src/orchestrator.py` | Modify | Add Final Gate call, compression guard, conditionalize polish |
| `src/agents/craft_editor.py` | Deprecate | Replace with `quality_polish.py` |
| `src/agents/quality_polish.py` | New | Single bounded polish agent |
| `src/revision/pipeline.py` | Deprecate | No more 3-band sequential |
| `src/revision/scene_emotion.py` | Deprecate | Concerns move to gate taxonomy or polish |
| `src/revision/line_copy.py` | Deprecate | Merged into quality polish |
| `src/revision/structural_continuity.py` | Deprecate | Concerns move to gate taxonomy |
| `prompts/agent_system_prompts/craft_editor.md` | Deprecate | Replaced by `quality_polish.md` |
| `prompts/revision_prompts/*.md` | Deprecate | Merged into `quality_polish.md` |
| `prompts/agent_system_prompts/quality_polish.md` | New | Single polish prompt |
| `src/agents/gate_critic.py` | Modify | Add programmatic word-count injection |

### Phase 2 files

| File | Action | Notes |
|------|--------|-------|
| `schemas/chapter_blueprint.json` | New | Chapter-level planning schema |
| `schemas/generation_brief.json` | New | Typed planner-to-drafter contract |
| `src/agents/plot_architect.py` | Modify | Emit typed brief via `complete_structured` |
| `prompts/agent_system_prompts/plot_architect.md` | Modify | Updated output format |
| `src/agents/prose_stylist.py` | Modify | Consume typed brief fields |

### Phase 3 files

| File | Action | Notes |
|------|--------|-------|
| `src/agents/chapter_gate_critic.py` | Modify | Optionally load and validate against blueprint |
| `src/concept_workshop/compliance_validator.py` | Modify | Stop reading embedded scene_cards as canonical |
| `schemas/concept_seed.json` | Modify | Mark embedded scene_cards as workshop-only |

## What to preserve

These components are architecturally sound and should not change:

- `concept_seed` as story-wide truth
- Scene cards as scene-local contracts (all 87 Ruusan cards)
- Gate Critic failure code taxonomy (23 codes)
- Gate verdict reconciliation fix (failure_codes always derive verdict)
- Reproducibility snapshots (`invocation.json`, `config_snapshot.yaml`, `prompts_snapshot/`)
- Runtime state and memory layer (`StoryState`, `ChapterMemory`, `KnowledgeLayers`)
- `--raw-draft` baseline mode
- `dialogue_expectation` derivation logic
- Phase 2 components (summarizer, state diff, contradiction scanner)

## Verification

### Per-phase acceptance criteria

**Phase 1:**
- Run with new pipeline produces word counts within 10% of baseline (run19: 3,515)
- Final Gate catches a simulated regression (manually inject wrong character into polished text)
- Programmatic word-count enforcement fires when draft is outside ±20%
- Compression guard fires when polish output < 80% of input
- All existing tests pass (915+)

**Phase 2:**
- Plot Architect emits valid JSON matching `generation_brief` schema
- Chapter blueprint for Ruusan chapter 1 validates against schema
- Prose Stylist consumes typed brief and produces comparable output to free-text brief

**Phase 3:**
- Chapter Gate Critic validates chapter against blueprint
- Compliance validator ignores embedded concept-seed scene cards
- Full chapter 1 run produces prose quality comparable to run19

### Ongoing comparison

Every run should be compared against the run19 baseline:
- Word counts: target 90-100% of scene target (run19 achieved 90-96%)
- Quality metrics: no regression from baseline scores
- Final Gate: pass rate should be >90% (polish rarely needs rejection)
- Gate verdict overrides: tracked for prompt-tuning feedback

## Freeze list

Until Phase 1 lands, freeze:
- No new revision bands
- No register-tier taxonomy work
- No major scene-card schema changes
- No heavy metric recalibration
- No model-routing experiments

The system's main problem is not lack of nuance. It is that too many stages are allowed to rewrite prose without a final contract check. Fix that first.
