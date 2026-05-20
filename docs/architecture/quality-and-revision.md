# Quality and Revision

The lean pipeline runs **no save-time quality gate**. Prose flows through a single forward pass and saves directly — there is no GateCritic, no QualityPolish, no FinalGate, no save-blocker layer, and no retry loop.

Quality is a planning-and-prompt problem, not a retry problem. The structural framework (Brooks beat map + Weiland arc map + the scene contract) is enforced **upstream**, at planning and scene-card validation time. The chapter packet hands the drafter a single inspectable runtime contract so it can land the scene on the first pass. The remaining quality machinery is **advisory** (deterministic telemetry written to a human-review store) or **post-production** (manuscript-level review that runs after a draft is complete).

## Quality enforced upstream

The drafter never sees a save-time gate, so the leverage moves earlier:

- **Workflow kit + `compile_bundle.py`.** Each surface validates against its schema; the bundle compiler runs JSON-schema validation and cross-surface reference validation. Bad scene cards fail a `--strict` compile.
- **Preflight.** `scripts/preflight_run.py` runs deterministic checks on planning artifacts before any LLM call — scene-card schema validity, cross-surface references, canon-guidance coverage.
- **Chapter packet.** `src/pipeline/chapter_packet.py` composes the drafter's runtime contract from the blueprint, seed, scene card, and trusted state. A drafter working from a complete, inspectable contract is the lean pipeline's substitute for a corrective gate.

## Deterministic prose telemetry (advisory)

Two pure analyzers measure prose without an LLM call. Both are default-off so shipping books keep current behavior until a per-book review approves the telemetry surface. Neither can block or mutate a save.

### RhythmValidator (`src/quality/rhythm_validator.py`)

Pure measurement of five rhythm metrics:

- em-dash density per 1,000 words
- consecutive short-sentence runs (staccato clusters)
- default-opener percentage (He/She/They/It/The/There)
- dialogue-bearing paragraph percentage
- abstract-construction tic density (the "particular X" family, "something adjacent", "not quite Y", etc.)

Default thresholds are calibrated against the *Scoundrels* (Zahn, 2013) corpus baseline. The validator returns a `RhythmResult` and emits issues at `low` (advisory band) or `medium` (warn band) as revision-debt rows of category `prose.rhythm.*`. Runtime flag: `runtime.rhythm_validator.enabled` (default false). When `runtime.rhythm_editor.enabled` is also on, `RhythmEditor` consumes the issues and proposes bounded literal edits — see [Agent Pipeline](agent-pipeline.md#5-rhythm-validation--edit-optional-advisory).

### CrossChapterContinuityValidator (`src/quality/cross_chapter_validator.py`)

A pre-draft check that walks the ordered scene-card list at bundle-compile time and flags **declared** discontinuities in character state, location, and plot-object holders. It only fires on declared contradictions — silence is not a continuity break. It recognizes `_NATURAL_TRANSITIONS` (alive→wounded, alive→dead) and `_REQUIRES_BRIDGE` transitions (dead→alive) where an off-page event must explain the change. Findings land as revision-debt rows of category `prose.continuity.*`. Runtime flag: `runtime.continuity_validator.enabled` (default false).

## Revision-debt store

`src/pipeline/revision_debt.py` (`RevisionDebtStore`) persists structured advisories to `output/<franchise>/<book>/state/revision_debt.db` (separate from `story_state.db` to keep that file's migration surface stable). It is a structured store for human triage — **nothing in the save path reads it to decide whether to save**.

- The `category` enum is **closed** — `CATEGORIES` in the module and the `enum` in `schemas/revision_debt.json` stay in lockstep; `store.add` raises on an unknown category.
- `owner_or_reviewer_notes` is human-only: an agent attempting to write to it raises.
- Every advisory stage routes through a wrapper in `src/pipeline/revision_debt_producers.py` (`emit_rhythm_advisory`, `emit_continuity_break`, `emit_metric_advisory`, etc.). Wrappers short-circuit to noop when `runtime.revision_debt.enabled` is false; the orchestrator never calls `store.add` directly.
- `src/pipeline/chapter_memos.py` synthesizes debt + pending promises into per-chapter and milestone human-review memos. The CLI at `scripts/debt_cli.py` supports `list`, `update`, `memo chapter`, and `memo milestone`.

`runtime.revision_debt.enabled` is default-off pending per-book sign-off.

## Anti-slop constraints

`config/negative_constraints.yaml` defines banned phrases (faux profundity, sensory clichés, magic adverbs, AI-tells) and structural rules (adverb density, sentence-length variance, repeated-opener ceiling, metaphor cooldown). The `ContextAssembler` bakes the banned-phrase list into the drafter's prompt, so anti-slop guidance reaches the drafter at draft time rather than being checked after the fact. Per-project voice rules from the concept seed's `voice_definition` are merged with these static constraints.

## Scene-contract validator (bench / diagnostic)

`src/quality/scene_contract_validator.py` + `src/quality/literal_repair.py` provide deterministic per-scene contract checks (turning point present, characters present, structural-phase-appropriate moves). They are **not** in the per-scene shipping path — `scripts/validate_scene_contract.py` runs them as a standalone diagnostic for recovery work.

## Manuscript-level review (post-production)

After the per-scene pipeline finishes and prose is saved, manuscript-level editorial passes run separately. They never rewrite prose in place during a drafting run — mutations route through `scripts/patch_workflow.py`.

- **Manuscript reviewer.** `src/agents/manuscript_reviewer.py` consumes the assembled manuscript for a developmental-pass review (the live route uses GPT-5.4). Output becomes an editorial docket; categorized issues can also land in revision-debt rows for human triage.
- **Literary polish + final copy.** `src/agents/literary_polish.py` + `src/pipeline/final_copy.py` run a higher-tier line-level polish *after* drafting. Targeted cleanup is the default final polish branch; full literary polish is an opt-in donor/comparison branch. Configured under `runtime.final_copy.*`.

See [Manuscript Production Lifecycle](manuscript-production-lifecycle.md) for the full operator sequence.

## Gold Evaluation Corpus

`data/eval_corpus/` contains reference chapters used to calibrate the deterministic prose analyzers — they provide the ground-truth baselines for the rhythm thresholds.
