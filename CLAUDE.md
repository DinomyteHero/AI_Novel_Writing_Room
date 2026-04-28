# CLAUDE.md — AI Writers' Room

Load-bearing notes for working on this codebase. Read before making changes.

## What this project is

A multi-agent fiction generation system. Humans plan a novel through the **workflow kit** (per-surface skills that produce `workflows/*.json`); `scripts/compile_bundle.py` merges those into a `concept_seed.json` + `scene_cards/`; then the **autonomous pipeline** drafts, line-edits, evaluates, and saves each scene. Franchise-scoped, book-scoped, with per-run output isolation.

## The relay is forward-only — do not re-introduce retries

Since the Stage 1a–3 refactor, prose flows through a **single-pass relay**. Gates are telemetry. Retry loops have been deliberately removed. The canonical order per scene (as implemented in `src/orchestrator.py::run_chapter`):

```
PlotArchitect → ProseStylist → [LineWriter*] → GateCritic → [corrective_rerun?]
  → QualityMetrics → QualityPolish → compression guard → FinalGate
  → CanonExpert → [canon_local_fixes?] → collect_presence_violations
  → [micro_repair?] → save-blocker layer → save | quarantine
```

`*` optional. `?` flag-gated, default off.

Rules:

- **GateCritic** and **FinalGate** are **advisory**. `final_gate_rejection` carries `advisory_only=True`; it does not block, retry, or revert. The compression guard is the exception that can keep the gate-passed draft when polish collapses below 60%.
- **`max_structural_retries` / `max_voice_retries`** are pinned to `0` in `config/settings.yaml`. They are retained only for rollback. Do not raise them, and do not add new retry branches. The only non-zero drafter retry path is `runtime.corrective_rerun.enabled` (bounded to exactly one rerun; Forward Relay v4).
- **Compression guard is revert-on-regression.** Polish that shrinks below 60% of pre-polish word count causes `polished_prose` to revert to the gate-passed draft; a warn-level `compression_guard_fired` event fires with `reverted=True`, and downstream stages (FinalGate, CanonExpert, PresenceChecker, save-blocker layer) evaluate the reverted prose. This is the only place in the forward-only relay where a later stage can overwrite an earlier stage's output — justified because polish-below-60% has been observed to hollow scenes beyond what human review can reasonably repair. Soft compressions (60-100%) still save polished output unchanged.
- **Post-save stages are wrapped with broad error guards.** Physics validation, summarizer/state-diff, character specialist, LLM judge, chapter gate critic, and the promise ledger Slice-3 hook each catch `Exception` and emit a warn-level event (`post_save_error` with a `stage` tag, or stage-specific events like `physics_validation_post` with `status=error`). A crash in any post-save stage never aborts a saved scene — next-scene state may be stale, so the warn is load-bearing.
- **LineWriter is the narrow lean edit by default.** `runtime.lean_prose_only.enabled: true` skips the broad gate/polish/canon/save-blocker stack, but `runtime.lean_prose_only.line_edit.enabled: true` lets the orchestrator run `LineWriter` once before saving when `agent_routing.line_writer` is present. Disable only the lean line edit with `runtime.lean_prose_only.line_edit.enabled: false`; disable lean entirely with `runtime.lean_prose_only.enabled: false` for diagnostic/full-relay runs. LineWriter takes an **explicitly wired** context dict — do not let it reach into ambient `ContextAssembler`. Collapsed output (<40% source word count) falls back to drafter prose with a warn event.
- The **save-blocker layer** (`src/pipeline/save_blockers.py`) is the **only** hard-failure path. Three categories: `CHARACTER_PRESENCE_BLOCKER` (from PresenceChecker), `CANON_BLOCKER` (CanonExpert verdict = fail + severity ∈ {critical, moderate}, excluding `post_divergence_drift` which is clamped to advisory), and a POV advisory (not yet blocking). When a blocker fires, the run aborts and the offending scene is written to `<project>/quarantine/chNN_scMM/{prose.md, blockers.json, brief.json}` — unless `runtime.firewall.enabled` is on (then `StateFirewall` isolates + continues, Slice 1).
- **PresenceChecker is invoked once per scene.** `save_blockers.collect_presence_violations()` produces the normalized violations list; the orchestrator threads it through `_maybe_micro_repair` and into `check_save_blockers(..., presence_violations=...)` so the checker is not called twice in the same scene unless micro_repair mutated the prose.

## Forward Relay v4 — use the advice, diversify the judges

The forward-only relay is intact, but three editorial redundancies were collapsed and the latent corrective-rerun plumbing was activated behind a runtime flag. Design doc at `docs/architecture/forward_relay_v4_proposal.md`.

**Default-on changes (shipped without a flag):**
- **Lean LineWriter is default-on.** The `line_writer:` entry under `agent_routing` in `config/settings.yaml` is present, and the shipping runtime has `runtime.lean_prose_only.line_edit.enabled: true`, so lean production is `PlotArchitect -> ProseStylist -> LineWriter -> save`. To compare drafter-only output, set `runtime.lean_prose_only.line_edit.enabled: false`; to run the full relay, set `runtime.lean_prose_only.enabled: false`.
- **Presence triple-check collapsed.** `CHARACTER_PRESENCE_VIOLATION` was removed from `GateCritic.STRUCTURAL_CODES` and `FinalGate.FINAL_GATE_CODES`. `PresenceChecker` at save time is the sole authority on character presence — the gates used to echo it, producing the same violation three times across pre-polish / post-polish / save-blocker. Turning-point + closing-hook stay in both gates because pre-polish vs post-polish is real regression coverage.
- **Gate/contract checks now use Grok 4.1 Fast.** `gate_critic`, `final_gate`, and `presence_checker` route to `grok41fast` in `config/settings.yaml`; `canon_expert` and `judge_evaluator` route to `grok420`. Fallback if structured-JSON reliability regresses: `glm` or `gemini_flash`. Alternative cross-family candidates are documented in the historical proposal doc's "Alternatives considered" section for future benching.

**Flag-gated changes (default-off; shipping-book guards in place):**
- **Smart single corrective rerun** — `runtime.corrective_rerun.enabled: false` (default). When enabled, a narrow trigger set (`MISSING_TURNING_POINT` or `CLOSING_HOOK_VIOLATION` from GateCritic `fail_structural`) fires *exactly one* ProseStylist redraft with structured `failure_context` populated from `_format_failure_context(evaluation)`. Confusion-skip rules: >3 failure codes → skip (brief not landing), draft below 50% of `target_word_count` → skip (collapsed output is a different failure mode). `pipeline.max_structural_retries` stays pinned at 0; this flag is the only path to a non-zero drafter retry. Emits `corrective_rerun_fired`, `corrective_rerun_skipped`, `corrective_rerun_complete` events.
- **Slice 11.1 narrow canon repair** — `runtime.canon_expert.apply_local_fixes: false` + `runtime.canon_expert.local_fixes_whitelist: []` (both default-safe). CanonExpert can emit an optional `local_fixes: [{category, pattern, replacement, reason}]` list for violations it can fix with a literal string substitution. `Orchestrator._maybe_apply_canon_local_fixes` applies whitelisted fixes to `final_prose` via `str.replace` — no second polish pass, no additional model calls *for the fix itself*. When a whitelisted fix actually mutates the prose, CanonExpert is re-invoked on the patched text before the save-blocker layer runs (emits `continuity_editor_recheck_complete` info). Fixes outside the whitelist emit `canon_fix_rejected` (warn, reason `category_not_whitelisted`). Pattern-not-in-prose cases also emit `canon_fix_rejected` (reason `pattern_not_in_prose`). Applied fixes emit `canon_fix_applied` (info) plus a `canon.local_fix_applied:<category>` debt row.

**Shipping-book guards** at `tests/test_runtime_flags.py::test_shipping_books_keep_corrective_rerun_off` and `::test_shipping_books_keep_canon_apply_local_fixes_off` block an accidental `runtime_overrides.yaml` flipping either flag for Ruusan or Betrayal before their parity tests land. Same pattern as Slice 1–5.

**Deferred:** drafter/line-editor bench. Previous bench runs and assumptions are invalidated — none of the pre-2026-04-21 bench artifacts under `output/**/runs/bench-*` reflect the current pipeline shape (DeepSeek V4 Pro drafter, GPT-5.4 Mini lean LineWriter, Grok 4.1 Fast gates, new micro_repair stage). Rerun the climax bench before making a routing decision. Promote a new drafter or line editor only if word-count discipline, contract obedience, and cost all hold under the current lean config.

## Safe canon/presence repair path — `micro_repair` (feature-flagged, default off)

Commit `6227b21` added `src/agents/micro_repair.py` and a matching orchestrator stage so the save-blocker layer has a legible, safe "try to patch before we quarantine" option. It is **not** a rewrite loop — it only applies *exact literal substring replacements* the model copies from the already-drafted prose.

- **Agent.** `MicroRepair` (DeepSeek V4 Pro @ t=0.1, max_tokens=1800 in the shipping config) returns `{"summary": ..., "repairs": [{"issue_type", "pattern", "replacement", "reason"}]}`. The prompt at `prompts/agent_system_prompts/micro_repair.md` explicitly forbids new named characters, new lore, new beats, regex, placeholders, or paragraph rewrites. If no safe patch exists, the agent returns `{"repairs": []}`.
- **Orchestrator stage.** `Orchestrator._maybe_micro_repair` runs between CanonExpert (post-`_maybe_apply_canon_local_fixes`) and the final `check_save_blockers` call, at `src/orchestrator.py:1021`. It receives precomputed `presence_violations` from `collect_presence_violations` so it never duplicates the PresenceChecker round-trip. When repairs apply, CanonExpert is re-invoked on the patched prose before save-blockers evaluate.
- **Currently supported issue types:** `presence_violation` only. Other `issue_type` values are rejected (`unsupported_issue_type`). Canon and POV issues still flow through their existing paths.
- **Deterministic safety caps enforced in `_apply_micro_repairs` regardless of what the model returns:**
  - `runtime.micro_repair.max_repairs` (default 5) — cap on applied patches per scene. Widened from the original 2 after the final-copy workflow showed the narrower budget could not patch presence violations in long climactic scenes.
  - `runtime.micro_repair.max_total_changed_chars` (default 1000) — total byte budget across patches.
  - `runtime.micro_repair.max_changed_ratio` (default 0.12) — ratio ceiling vs. original prose length.
  - **Unique-occurrence requirement.** If `pattern` appears zero times → `pattern_not_in_prose`. If it appears more than once → `ambiguous_pattern_occurrences` (no fuzzy substitution; we refuse to guess which span to patch).
  - **Forbidden-name guard.** Any absent-character name from the original violation list that also appears in `replacement` (case-folded) → `forbidden_name_in_replacement` (prevents the model from "fixing" `Luke stepped from the doorway` → `Luke Skywalker stepped from the doorway`).
  - Other rejections: `empty_pattern`, `non_string_replacement`, `no_op_replacement`, `duplicate_pattern`, `changed_char_budget_exceeded`, `changed_ratio_exceeded`.
- **Ledger events.** `micro_repair_fired` (info, start), `micro_repair_applied` (info, per applied patch), `micro_repair_rejected` (warn, per rejected patch with `reason`), `micro_repair_complete` (info, summary including `canon_blocker_count` after recheck), `micro_repair_error` (warn, model or canon-recheck failure).
- **Shipping-book guard** at `tests/test_runtime_flags.py::test_shipping_books_keep_micro_repair_off` blocks an accidental `runtime_overrides.yaml` flipping `runtime.micro_repair.enabled` on Ruusan or Betrayal. `test_shipping_defaults_all_safe` also asserts the default caps to prevent silent widening.
- **Config wiring.** `agent_routing.micro_repair` is present in the shipping `config/settings.yaml` (DeepSeek V4 Pro, t=0.1, 1800 max_tokens). `src/main.py` instantiates `MicroRepair(router)` only when the routing entry exists — bench configs can drop it to keep runs even cheaper. The runtime flag decides whether `_maybe_micro_repair` ever attempts a patch; a missing routing entry is also a no-op.

## Slice 1: state firewall + Phase 0 gate (feature-flagged, default off)

Slice 1 of the architecture upgrade (`docs/architecture/architecture_upgrade_spec.md`) is in the tree but **off by default**. The defaults-off posture protects Ruusan and Betrayal until each book passes its own parity test.

- Runtime flags live at `config/settings.yaml` under `runtime:` and resolve through `src/runtime_flags.py` (precedence: CLI `--runtime-flag` > per-book `data/franchises/<franchise>/books/<book>/runtime_overrides.yaml` > per-franchise `runtime_overrides.yaml` > settings default). Do not hand-author a `runtime_overrides.yaml` for Ruusan or Betrayal until their parity tests land.
- `runtime.firewall.enabled: true` flips the save-blocker path from run-abort to isolate-and-continue. Isolation still writes prose + `blockers.json` to `<project>/quarantine/chNN_scMM/` (existing behavior) and additionally writes `gap_manifest.json` + records a `gap_notes` row in `story_state.db` (v7 migration adds the table; wrapper at `scripts/migrate_gap_notes.py`).
- `runtime.firewall.successor_classifier.enabled: true` enables `src/pipeline/successor_classifier.py`. **The 30-label gate is met at HEAD: `tests/data/successor_classifier_labels.json` has 30 hand-labeled pairs, 30/30 classifier agreement.** The flag is flipped on for the scratch book at `data/franchises/test-bench/books/classifier-smoke-test/` (see that book's `runtime_overrides.yaml`). Ruusan and Betrayal still hold global default (false) until their per-book parity tests approve the flip — a regression test at `tests/test_runtime_flags.py::test_shipping_books_keep_firewall_off` guards against an accidental `runtime_overrides.yaml` landing under either book.
- `gap_notes` table + `StoryState.{record_gap, list_open_gaps, resolve_gap, list_gaps_affecting}` are load-bearing for Slices 2 (overlay surfacing) and 6 (patch workflow). End-of-run summary in `src/main.py` prints open gaps.
- Phase 0 audit (`scripts/audit_phase0.py`, `schemas/phase0_audit.json`) is the gate for Slice 2 (chapter packet). The script evaluates six criteria (voice rules → drafter, scene contract → drafter, constraints survive assembly, cross-scene feedback, register single-source, audit report exists) against rendered prompts. Two evaluation modes: **dry-run** (default, offline, renders prompts via ContextAssembler + ProseStylist without any API calls) and **live-run** (reads captured prompts from a run directory when `runtime.phase0_audit.enabled: true` was on during the pipeline run — `src/pipeline/phase0_capture.Phase0PromptSnapshot` writes per-stage prompts under `<run_dir>/phase0_debug/chNN_scMM/`). **Current status: both Ruusan and Betrayal pass all six criteria at HEAD** (see `docs/audits/phase0_<date>_<book>.md`). The `tests/test_audit_phase0.py::test_audit_phase0_gate_passes_for_shipping_books` parametrized test enforces this gate on every run so prompt-assembly regressions get caught immediately. Slice 2 is unblocked.
- New ledger events: `scene_isolated` (error), `gap_note_recorded` (warn), `phase0_audit_emitted` (info). Use the existing `ledger.emit_{info,warn,error}` helpers.
- Parity scaffolds at `tests/test_pipeline_regression_{ruusan,betrayal}.py` opt in to live comparison via `PARITY_RUN_PATH=<chapter_01_scene_01.md>`; without it, only the baseline readability check runs. Baselines live at `tests/baselines/{ruusan,betrayal}_ch01_sc01.md` — refresh only with explicit human sign-off.
- Adding a new runtime flag without `default: false` (or the safest equivalent) is a review-blocker.

## Slice 2: chapter packet (shipping default ON; revision debt still default off)

Slice 2 ships the drafter's single inspectable runtime contract and the structured advisory store. **The chapter packet now ships on by default (D4a rollout).** Phase 0 audit and packet parity both pass on Ruusan and Betrayal at HEAD; the packet is the drafter's runtime contract. `runtime.revision_debt.enabled` remains default-off pending per-book sign-off.

- **One chapter packet contract.** `src/pipeline/chapter_packet.py` defines `ChapterPacket` (frozen dataclass) + `ChapterPacketCompiler`. The compiler builds a **base** once per chapter (`compile_base(chapter_number)`) from the blueprint + seed; a per-scene **overlay** composes the base with the current scene card and open gap notes (`compile_overlay(base, scene_card, trusted_state_snapshot)`). Bases are **immutable**; overlays return new packets with `overlay_version` incremented. The overlay renderer embeds the legacy `ContextAssembler.assemble()` output so the packet is a strict token-superset of flat (enforced by `tests/test_packet_parity.py`).
- **Shipping default: `runtime.chapter_packet.enabled: true`** (D4a). `ProseStylist` runs on the packet path; the orchestrator still computes flat `assembled_context` for the `runtime.chapter_packet.fallback_on_error: true` escape hatch. On compile error a `packet_fallback_flat` warn event fires and the drafter gets flat context. Compiled packets land at `<run_dir>/chapter_packets/chapter_NN.json` (base) + `chapter_NN_sc_MM_overlay.json` (overlay) with a `packet_base_compiled` / `packet_overlay_written` info event. Slice 3 (`active_promises`), Slice 4 (`continuity_events`), and Slice 5 (`relationship_context`) plug collaborators into the same compiler — those fields populate only when their per-feature flags are on (all default-off except chapter_packet itself).
- **Revision debt store.** `src/pipeline/revision_debt.py` (`RevisionDebtStore`) persists structured advisories to `output/<franchise>/<book>/state/revision_debt.db` (separate from `story_state.db` to keep that file's migration surface stable). The `category` enum is **closed** — `CATEGORIES` in the module and the `enum` in `schemas/revision_debt.json` must stay in lockstep, and `store.add` raises `ValueError` on unknown categories. `owner_or_reviewer_notes` is human-only: any agent trying to write to it raises on the `add` path.
- **Write-matrix (spec §6.2.1).** Every advisory stage routes through a wrapper in `src/pipeline/revision_debt_producers.py` — `emit_canon_advisory`, `emit_canon_fix_rejected`, `emit_canon_polish_drift`, `emit_gate_critic_advisory`, `emit_final_gate_advisory`, `emit_metric_advisory`, `emit_presence_near_miss`, `emit_blocker_record` (severity pinned `high`), `emit_wordcount_drift`, `emit_compression_advisory`, `emit_scene_reviewer_finding`, `emit_scene_reviewer_other`. Wrappers short-circuit to noop when `runtime.revision_debt.enabled: false`; the orchestrator never calls `store.add` directly. Status transitions go through `emit_status_update`, which logs `revision_debt_updated`.
- **Chapter memos.** `src/pipeline/chapter_memos.py` (`ChapterCloseMemoGenerator`, `MilestoneMemoGenerator`) synthesize debt + gap notes + pending promises into per-chapter and cross-chapter human-review memos under `<run_dir>/memos/`. The CLI at `scripts/debt_cli.py` supports `list`, `update`, `memo chapter`, `memo milestone`.
- **Migration.** `scripts/migrate_revision_debt.py` walks every `output/**/state/` dir and idempotently ensures `revision_debt.db` exists with the current schema. Re-running is safe.
- **New ledger events (all `emit_{info,warn,error}`):** `packet_base_compiled` (info), `packet_overlay_written` (info), `packet_fallback_flat` (warn), `revision_debt_added` (info), `revision_debt_updated` (info).
- **Shipping-book guards.** `tests/test_runtime_flags.py::test_shipping_books_run_chapter_packet_by_default` catches a runtime_override that *disables* the packet on Ruusan or Betrayal. `::test_shipping_books_keep_revision_debt_off` still blocks revision_debt from flipping on accidentally before its per-book sign-off.

## Slice 3: promise ledger (feature-flagged, default off)

Slice 3 ships the first trusted stateful-memory artifact: a **declaration-driven** promise ledger. Populated from planning + scene cards, never inferred by LLMs. `runtime.promise_ledger.enabled` defaults `false` on Ruusan and Betrayal until their per-book parity tests land.

- **Store.** `src/memory/promise_ledger.py` (`PromiseLedger`) backs `output/<franchise>/<book>/state/promise_ledger.db`. `initialize_from_planning(concept_seed, scene_cards)` seeds from `story_physics.promise_payoff_ledger` + scene-card `promises_planted` / `promises_paid` (idempotent; existing `progression_log` preserved). Scene IDs use `chNN_scMM`; the sentinel `chNN_sc99` represents chapter-end when planning only names a chapter. `initialize_from_planning` drops entries with no derivable `setup_scene` rather than writing a row that would fail the NOT NULL constraint.
- **Trust model (spec §7.1).** Ledger rows move through `record_progression` / `record_payoff` / `record_broken` only. `SceneReviewer` progression suggestions do **not** write here — those land as `editorial.scene_reviewer` revision-debt rows. `overdue` is derived at read time (`list_overdue`), never stored.
- **Scene-card contract.** New optional field `promises_progressed: [<promise_id>, ...]`. At save time the orchestrator appends one entry to each promise's `progression_log` with `source='scene_card'` and emits a `promise_progressed` info event. `promises_paid` emits `promise_paid`. Unknown IDs emit a warn-level event (planning drift) but do not abort the run.
- **Packet integration.** `ChapterPacketCompiler.compile_overlay` now calls `list_top_urgent(at_scene=scene_id, n=5)` so the drafter sees urgency-ranked promises *as of this scene*, not a chapter snapshot. `active_promises_total_count` tails the top-5 list (spec §7.3 dilution guard). Overdue rows carry `status='overdue'` + `overdue_by_scenes`; the renderer emits them under a separate *"Overdue promises (advisory only — do not force payoff)"* heading. `compile_base` still uses `active_for_chapter(chapter_number)` because the scene is not yet known there; the overlay replaces that snapshot per scene.
- **Migration.** `scripts/migrate_promise_ledger.py` walks every `output/<franchise>/<book>/state/` dir, pairs it with `data/franchises/<franchise>/books/<book>/`, seeds `promise_ledger.db` from that book's planning. Idempotent (UPSERT on `promise_id`). `--dry-run` reports plan without writes.
- **New ledger events (all `emit_{info,warn,error}`):** `promise_planted` (info), `promise_progressed` (info), `promise_paid` (info), `promise_overdue` (warn). The warn-level path fires from `_maybe_record_promise_deltas` after save so the human operator sees slipping promises in the feed.
- **Shipping-book guard** at `tests/test_runtime_flags.py::test_shipping_books_keep_promise_ledger_off` blocks an accidental `runtime_overrides.yaml` flipping the flag on Ruusan or Betrayal before their parity test lands.

## Slice 4: continuity event log (feature-flagged, default off — RISKY)

Slice 4 ships the first **LLM-extracted** trusted-memory artifact, with explicit trust-model guardrails. `runtime.continuity_log.enabled` defaults `false` on every book; the extractor is advisory-to-trusted, threshold-gated by `runtime.continuity_log.min_confidence` (default 0.85).

- **Narrow-by-design schema.** `schemas/continuity_event.json` permits exactly five event types: `location_change`, `injury_state`, `possession`, `revelation`, `status_change`. `oneOf` discriminates on `event_type` and pins each type's `details` shape (closed `additionalProperties: false`). Interpretive / emotional / relational events are **not** modeled here — those belong to Slice 5 sociogram or revision debt.
- **Store.** `src/memory/continuity_log.py` (`ContinuityLog`) backs `output/<franchise>/<book>/state/continuity_log.db`. `append` enforces the closed type set + required details at the Python layer (second line of defense behind the schema). Redaction is soft (`redacted=true` + `redacted_reason`) so audit trails survive.
- **Extractor.** `src/agents/continuity_extractor.py` (`ContinuityExtractor`) + `prompts/agent_system_prompts/continuity_extractor.md`. Haiku @ t=0.0, max_tokens=2048 (cost floor for the risky slice). The agent drops rows that fail structural validation (unknown type, bad details, out-of-range confidence) silently — scene-save path must never abort on extractor noise.
- **Suppression is absolute.** Sub-threshold events go **nowhere**: not stored, not rendered, not logged as content. Only `continuity_events_suppressed` (warn, payload=`{count, threshold}`) lands in the run ledger. Hallucinated facts cannot reach the packet by construction.
- **Packet integration.** `ChapterPacketCompiler.compile_overlay` now narrows chapter continuity events to those whose `subject` matches the POV or `characters_present`, bounded to strictly-before the current `scene_id`. An event from the drafting scene never appears in its own overlay (spec §8.1 invariant).
- **Eval harness.** `scripts/eval_continuity_extractor.py` supports both a live mode (drives the real router; spends credits) and a predictions-file mode (CI-safe). Produces `precision / recall / false_positive_rate / per-scene` report. Spec §8.4.3 gate for flipping the flag: precision ≥ 0.90 (≥ 0.95 for Ruusan), FP rate ≤ 0.05, recall ≥ 0.60 on the labeled corpus. The corpus lives at `tests/data/continuity_eval_set.json` — **the committed version is a 2-scene stub** for exercising the harness; the 30-scene Ruusan corpus is the prerequisite for flag flip and remains human-author-only work.
- **Orchestrator wiring.** `_maybe_extract_continuity` runs *after* save so quarantined scenes never produce trusted events. Per-event outcomes emit `continuity_event_recorded` (info); the suppression count emits `continuity_events_suppressed` (warn); extractor crashes emit `continuity_extractor_error` (warn) and do not abort the pipeline.
- **Migration.** `scripts/migrate_continuity_log.py` walks every `output/**/state/` dir and ensures an empty `continuity_log.db` exists. Idempotent.
- **New ledger events:** `continuity_event_recorded` (info), `continuity_events_suppressed` (warn), `continuity_extractor_error` (warn).
- **Shipping-book guard** at `tests/test_runtime_flags.py::test_shipping_books_keep_continuity_log_off` blocks an accidental flag flip on Ruusan or Betrayal before the precision gate passes.

## Slice 5: sociogram (feature-flagged, default off — highest inference risk)

Slice 5 ships the character-relationship graph. Declarative-first: planning seeds the initial state; scene-card `relationship_deltas` are the only auto-trusted write path. Assisted-suggestion mode is routed through revision debt, never directly into the graph.

- **Schema.** `schemas/sociogram_edge.json` pins directional edges (subject → object is distinct from object → subject). Three-axis scalar encoding: `trust`, `warmth`, `power_balance`, each in `[-1, 1]`. `arc_type` is a closed enum of 11 relationship shapes; the store normalizes planning aliases (`reconciling` → `enemies_to_allies`, etc.) to land on the enum.
- **Store.** `src/memory/sociogram.py` (`Sociogram`) backs `output/<franchise>/<book>/state/sociogram.db`. `initialize_from_planning` accepts both `concept_seed.relationship_arcs` (Ruusan convention: `dyad: "A/B"`) and `concept_seed.ensemble_cast[*].relationships` (spec convention). Re-seeding is idempotent and **does not** clobber scene-card-driven state — a repeat `initialize_from_planning` leaves `trust`/`warmth`/`power_balance` at whatever the deltas moved them to, appending only a planning note to history.
- **Scene-card contract.** New optional field `relationship_deltas: [{subject, object, trust_delta, warmth_delta, power_balance_delta, note}]`. Per-axis deltas capped at ±0.5 by both the schema and the store; larger swings must be decomposed across multiple scenes. `Sociogram.apply_scene_deltas` skips invalid rows with a warn log rather than aborting; valid rows emit `sociogram_delta_applied` info events.
- **Packet integration.** `ChapterPacketCompiler.compile_overlay` calls `sociogram.context_for_scene(scene_card)` — dyads whose subject AND object are both in `{pov_character} ∪ characters_present`. The non-surfaced count goes in `_unshown_edge_count`; the renderer emits it as `_(+N other edges not surfaced this scene)_` so the drafter sees dilution without being flooded. `compile_base` still uses `snapshot_for_chapter(chapter_number)` (scene-less view).
- **Renderer.** Per-dyad line: `Hunter │ Jora: trust -0.30; warmth -0.10; power_balance +0.20 [arc_type]`. Leading scene anchor `(current state as of chNN_scMM)` from the first entry's `updated_at_scene`.
- **Migration.** `scripts/migrate_sociogram.py` walks every `output/<franchise>/<book>/state/` dir, pairs it with `data/franchises/<franchise>/books/<book>/`, seeds `sociogram.db` from planning. Idempotent.
- **New ledger events:** `sociogram_delta_applied` (info), `sociogram_suggestion_recorded` (info, reserved for the assisted-suggestion path in Slice 11.1 wave).
- **Shipping-book guard** at `tests/test_runtime_flags.py::test_shipping_books_keep_sociogram_off` blocks an accidental flag flip on Ruusan or Betrayal before a non-shipping book has it enabled and produces relationally-grounded prose without drift (spec §9.6 go/no-go).

## Slice 6: manuscript lifecycle design + patch workflow

Slice 6 is the bridge between the forward-only scene runtime and coherent manuscript-level editorial. The design doc lives at `docs/architecture/manuscript_lifecycle_design.md`; the load-bearing CLI ships alongside it.

- **Design doc.** `docs/architecture/manuscript_lifecycle_design.md` specifies developmental / line / copy / proof passes and defines the invariant: manuscript-level passes never rewrite prose in place during a drafting run — mutations route through `scripts/patch_workflow.py`.
- **Patch workflow CLI.** `scripts/patch_workflow.py` with four subcommands:
  - `accept-isolated <scene_id>` promotes quarantined prose, resolves matching gap notes, marks downstream overlays stale, replays declarative state (promise + sociogram) from the scene card.
  - `replace <scene_id> --from <path> [--gap <gap_id>]` overwrites saved prose with a human edit; same replay semantics.
  - `overrule <gap_id>` resolves a gap without changing prose.
  - `apply-manuscript-patch <patch_path>` dispatches JSON batches matching `schemas/manuscript_patch.json`. Duplicate `replace` entries for the same scene are rejected before any mutation.
- **Replay semantics.** Scene card `promises_progressed` / `promises_paid` / `relationship_deltas` are re-applied on every `accept-isolated` / `replace`, so the stateful stores converge to the scene card's declaration. Continuity extraction does NOT run in the CLI (needs a live router) — instead `<run_dir>/continuity_log.STALE` markers let the next drafting run rebuild. Per-overlay markers at `<run_dir>/chapter_packets/chapter_NN_sc_MM_overlay.STALE` are advisory; `Orchestrator._maybe_compile_overlay` notices them, emits a `packet_overlay_written` info event with `stale_marker_cleared=true`, and deletes them (overlays already rebuild every scene so the marker is a human-audit trail, not a cache-invalidation signal).
- **Export scaffolding.** `scripts/manuscript_export.py` walks a run's `chapters/` dir and stitches `manuscript.md` + `chapter_index.md` under `<project_root>/export/`. Deliberately simple — EPUB / PDF wrapping is deferred.
- **Schema.** `schemas/manuscript_patch.json` with closed action enum (`accept-isolated`, `replace`, `overrule`) and scene-id pattern enforcement. `source_pass` tag lets downstream memos attribute each mutation to its originating pass.
- **Test coverage.** 12 new tests span every subcommand, the duplicate-replace rejection, and the export stitcher. All subprocess calls pass `--no-ledger` + `--base-dir tmp_path` so tests stay hermetic and don't touch the real run ledger.

## Lean prose path (shipping default)

`runtime.lean_prose_only.enabled: true` is the **shipping default**. When on, the orchestrator short-circuits the broad relay and, by default, runs the configured lean LineWriter once before saving (`runtime.lean_prose_only.line_edit.enabled: true`). This skips GateCritic, QualityMetrics, QualityPolish, FinalGate, CanonExpert, the canon local-fix path, the micro_repair stage, and the save-blocker layer. Prose lands as `saved_clean` directly.

Why it's safe by default: the structural framework (Brooks beat map + Weiland arc map + scene contract) is enforced *upstream* at planning + scene-card validation time. The save-time gates were originally inserted as cheap insurance against drafter drift; with the post-D2(c) enriched scene cards + chapter packet contract, the drafter has enough information to land the contract on the first pass for the vast majority of scenes. The gates are still wired and tested; the lean flag lets a shipping run skip them without removing them from the codebase.

When to disable lean (set `runtime.lean_prose_only.enabled: false`):
- Bench runs that need editorial judgement on every scene.
- Recovery runs after a drafter / model / prompt change, before re-ramping.
- Books on franchises with strict canon contracts where canon_expert + presence_checker are non-negotiable.

Disabling lean re-engages the full forward-only relay documented in the "relay is forward-only" section above.

## Pre-run architecture: canon guidance + preflight (commit `e67d5ff`)

Two pre-run subsystems landed alongside the lean path:

- **Canon guidance store + canon_scout agent.** `src/pipeline/canon_guidance.py` + `src/agents/canon_scout.py`. Persists franchise-level canon tips (terminology, mechanics, period detail) at `data/franchises/<franchise>/canon_guidance.json`. The chapter packet's `canon_guidance` field surfaces relevant entries to the drafter via the "Static Canon Guidance" section in the rendered packet. CLI: `scripts/canon_scout.py` for authoring; `data/franchises/<f>/canon_guidance.json` is read at packet compile time. Coverage gaps surface as preflight warnings.
- **Preflight runner.** `src/pipeline/run_preflight.py` + `scripts/preflight_run.py`. Runs deterministic checks on planning artifacts before any LLM call: scene-card schema validity, cross-surface references resolve, canon guidance coverage, presence chains tractable. Surfaces all findings as a single report so the operator never wastes a run on a planning gap that could have been caught in seconds.

## Manuscript-level passes (post-save, opt-in)

Three post-save / off-path subsystems extend the per-scene pipeline without touching the relay:

- **`src/quality/scene_contract_validator.py` + `src/quality/literal_repair.py`** (commit `c222462`). Deterministic per-scene contract checks (turning point present, characters present, structural-phase-appropriate moves). `bench_prose_models.py` exposes `--scene-contract`, `--auto-scene-contract`, `--fail-on-contract` to wire them into a bench run. Not in the per-scene shipping path; opt-in for diagnostic / recovery work.
- **Literary polish + final-copy** (commit `5820841`). `src/agents/literary_polish.py` + `src/pipeline/final_copy.py` + `scripts/final_copy_existing.py`. A post-production pass that runs *after* the per-scene pipeline finishes and prose is saved. Routes to a higher-tier model (default `gpt54`) for line-level literary polish. **Not** part of the per-scene relay; intended for the final pre-publication sweep, not for every drafting run.
- **Manuscript reviewer.** `src/agents/manuscript_reviewer.py` consumes the assembled manuscript for a developmental-pass review. Output lands in revision-debt rows (Slice 2) for human triage.

These three are the "manuscript lifecycle" implementations of the design at `docs/architecture/manuscript_lifecycle_design.md`. The per-scene pipeline does not invoke them.

## Idea-session capture (front-door planning, Claude/Codex portable)

`workflows/idea_session_capture/` is the **only** workflow surface that runs identically in Claude Code and Codex. The conversation contract is the SKILL.md (read by both); state mutation goes through `IdeaSessionCapture` (a headless api). Both tools mutate the same `capture.json` through the same Python entry points; only the surrounding chat experience differs.

- **Claude Code:** invokes the skill registered at `.claude/skills/idea-session-capture/SKILL.md` (thin wrapper; points at the workflow SKILL).
- **Codex:** reads `AGENTS.md` at the repo root, which orients to the workflow kit and the idea-session conversation contract.
- **Headless:** `from workflows.idea_session_capture import IdeaSessionCapture; cap = IdeaSessionCapture(title, franchise); cap.init_workspace(); cap.set_north_star(...); cap.add_decision(...); cap.expand_to_surface_drafts()`.
- **CLI:** `python scripts/idea_session_capture.py {init|status|expand}`.

`expand_to_surface_drafts()` is the bridge from the creative tier to the structural tier: it reads a populated capture and pre-seeds `workflows/{universe,canon,voice,characters,outline}.json` skeletons (and `workflows/scene_cards/_intent.md`). Existing artifacts are skipped unless `force=True`. The downstream surface sessions open to a partly-filled draft, not a blank file — the user does the creative thinking, the agent does the structural fleshing-out.

## Scene-count discipline (less is more)

Chapters carry **as many or as few scenes as the dramatic need calls for**. The schema does **not** force a minimum scene count per chapter — `outline.minItems = 1` for the chapter array, and `scene_cards/` may carry one card per chapter or several. A chapter with one load-bearing scene is healthier than a chapter padded with three scenes that share one turning point.

Rule of thumb (enforced by guidance in `outline-planner` and `scene-card-authoring` SKILLs, not by validation): only split a chapter when each resulting scene carries its own:

- distinct turning point (trigger / shift / cost)
- distinct mission for the POV character
- distinct emotional arc (start / shift / end)

If two candidate scenes share a turning point, fold them into one. This is the spirit of Brooks's chapter-as-dramatic-unit: chapters are sized to the beat they carry, not to a uniform cadence.

## Status vocabulary (three values only)

Per-scene save status lives in `src/memory/story_state.py`. Only three values are valid:

- `saved_clean` — all gates green, no advisories fired.
- `saved_with_advisory` — saved, but at least one advisory fired (final-gate rejection, compression guard warning, POV heuristic, word-count drift).
- `quarantined` — a save-blocker fired; scene is on disk at `quarantine/` and the run aborted.

The old vocabulary (`gate_passed`, `polished`, `approved`, `gate_failed`, `gate_skipped`, `final_gate_rejected`) is gone. `scripts/migrate_status_vocab.py` auto-migrates existing `story_state.db` files. Ledger emits carry a `level` (`info` / `warn` / `error`) in the payload.

## Franchise-scoped paths

Always route I/O through `src/project_paths.ProjectPaths`. Do not hand-construct paths under `data/` or `output/`.

- Inputs: `data/franchises/<franchise>/books/<book>/` (`concept_seed.json`, `scene_cards/`, `chapter_blueprints/`, `workflows/`).
- Franchise-shared resources: `data/franchises/<franchise>/{canon_db/, worldbuilding.db, worldbuilding_vectors/}` (shared across books in the franchise).
- Outputs: `output/<franchise>/<book>/` with `state/` (book-scoped or series-scoped SQLite/ChromaDB/ledger), `runs/<run_id>/chapters/` (per-run isolated prose + `config_snapshot.yaml`), `quarantine/`, `export/`.
- Series-level state lives at `output/<franchise>/<series>/state/` when `series_id` is set in `concept_seed.meta`.

`ProjectPaths.from_concept_seed(seed, run_id=...)` is the canonical constructor; `ProjectPaths.from_concept_seed_path(path, run_id=...)` works when you only have a file path.

## Key modules

| Concern | Path |
|--------|------|
| Pipeline orchestration | `src/orchestrator.py` |
| CLI entry point | `src/main.py` |
| Model routing (YAML → backend) | `src/model_router.py` |
| Runtime-flag resolver | `src/runtime_flags.py` |
| Path resolver | `src/project_paths.py` |
| Agents (incl. `micro_repair.py`, `presence_checker.py`) | `src/agents/` (see `src/agents/README.md` for the live/optional/utility split) |
| Save-blocker layer | `src/pipeline/save_blockers.py` |
| State firewall (Slice 1 isolate-and-continue) | `src/pipeline/state_firewall.py` |
| Successor classifier (Slice 1) | `src/pipeline/successor_classifier.py` |
| Chapter packet (Slice 2, shipping default ON) | `src/pipeline/chapter_packet.py` |
| Deterministic brief assembler (PlotArchitect successor; **WIP — not yet wired into the orchestrator**) | `src/pipeline/brief_assembler.py` |
| Canon guidance store + canon_scout agent | `src/pipeline/canon_guidance.py`, `src/agents/canon_scout.py`, `scripts/canon_scout.py` |
| Pre-run preflight | `src/pipeline/run_preflight.py`, `scripts/preflight_run.py` |
| Scene-contract validator + literal repair (bench/diagnostic) | `src/quality/scene_contract_validator.py`, `src/quality/literal_repair.py` |
| Literary polish + final-copy (post-production) | `src/agents/literary_polish.py`, `src/pipeline/final_copy.py`, `scripts/final_copy_existing.py` |
| Manuscript reviewer (developmental pass) | `src/agents/manuscript_reviewer.py` |
| Idea-session capture (Claude/Codex portable) | `workflows/idea_session_capture/api.py`, `scripts/idea_session_capture.py`, `AGENTS.md` |
| Scene-card cross-surface validator | `workflows/_shared/scene_card_references.py` |
| Scene-card enrichment migration | `scripts/enrich_scene_cards.py` |
| Revision-debt store + producers (Slice 2) | `src/pipeline/revision_debt.py`, `src/pipeline/revision_debt_producers.py` |
| Phase 0 prompt capture (Slice 1 audit harness) | `src/pipeline/phase0_capture.py` |
| Chapter memos | `src/pipeline/chapter_memos.py` |
| Promise ledger (Slice 3) | `src/memory/promise_ledger.py` |
| Continuity log (Slice 4) | `src/memory/continuity_log.py` |
| Sociogram (Slice 5) | `src/memory/sociogram.py` |
| Word-count telemetry | `src/pipeline/word_count_telemetry.py` |
| Ledger (typed events) | `src/run_ledger.py` |
| Context assembly | `src/memory/context_assembler.py` |
| Story state / knowledge / chapter memory | `src/memory/` |
| Canon RAG | `src/rag/` |
| Worldbuilding (lore DB + vectors) | `src/worldbuilding/` |
| Quality metrics | `src/quality/` |
| Web API + frontend | `src/ui/` |
| Workflow-kit surfaces (skills) | `.claude/skills/<surface>/` + `workflows/<surface>/` |
| Bundle compiler (workflows → concept_seed) | `scripts/compile_bundle.py` |
| Manuscript patch workflow (Slice 6) | `scripts/patch_workflow.py`, `scripts/manuscript_export.py` |
| Migration wrappers | `scripts/migrate_all.py`, plus per-store `migrate_*.py` scripts |
| Canonical shared helpers | `workflows/_shared/seed_transforms.py`, `workflows/_shared/scene_card_translator.py`, `workflows/voice_discovery/api.py` |

## Workflow kit is the only supported authoring path

The interactive `src.concept_workshop.workshop_runner` CLI was **removed**. Do not reference it in docs or code. New projects go through the per-surface skills, in order:

1. **`idea-session-capture`** (front door, Claude/Codex portable) — captures the author's intent, decisions, and open questions; pre-seeds the six structural surfaces.
2. **`universe-builder`** — premise, conflict, theme, setting.
3. **`canon-drafter`** — continuity rules, terminology.
4. **`voice-discovery`** — POV, register, reference authors.
5. **`character-forge`** — Weiland arc structure (lie/ghost/want/need/arc_type/arc_phase_map).
6. **`outline-planner`** — Brooks four-part beat map; chapters with variable scene counts.
7. **`scene-card-authoring`** — per-scene contract.

Then `scripts/compile_bundle.py` merges the surface outputs into the canonical `concept_seed.json`.

Canonical helpers live under `workflows/_shared/` (`seed_transforms.py`, `scene_card_translator.py`) and `workflows/voice_discovery/api.py` (`VoiceDiscovery`). The old re-export shims at `src/concept_workshop/{seed_transforms,scene_card_translator,voice_discovery}.py` have been removed. The remaining modules under `src/concept_workshop/` (`compliance_validator.py`, `series_manager.py`, `stress_test.py`) are canonical, not shims, and are still the right import path.

**Codex parity:** the `idea-session-capture` surface runs identically in Claude Code and Codex — the conversation contract is at `workflows/idea_session_capture/SKILL.md` and Codex enters via `AGENTS.md` at the repo root. The other six surfaces are Claude-Code-skill-shaped today; they have headless apis (`workflows/<surface>/api.py`) so Codex can drive them programmatically, but their interactive-chat ergonomics are tuned for the Claude Code skill harness. Use Codex for idea-session and scripted operations; use Claude Code for the structured-surface chats.

## Testing

- Full suite: `pytest -q` (≈1,950 tests across 140 files, ≈140s).
- Some tests skip without optional deps (chromadb, sentence-transformers, fastapi); that is expected.
- Web-path regression set: `pytest tests/test_websocket_ledger.py tests/test_run_ledger.py tests/test_api_pipeline.py tests/test_api_ledger.py tests/test_ui_pipeline_blueprint_wiring.py -q`.

### Windows Python invocation

In the current PowerShell workspace, `python` resolves correctly and is used throughout the docs. If a Windows shell ever routes bare `python` to the Microsoft Store installer stub, use `py -3` or the explicit interpreter at `/c/Users/lbouw/AppData/Local/Programs/Python/Python312/python.exe`.

## Benchmarking

`scripts/bench_prose_models.py` runs a single scene through multiple drafter/line-editor configurations and writes to `output/<franchise>/<book>/runs/bench-<date>-<scene>/`. Summary markdown goes under `docs/editorial/` or alongside the bench run.

**All pre-2026-04-21 bench numbers are invalidated.** The pipeline shape changed enough between them and HEAD that cost, word-count, and quality figures from those runs no longer predict current behavior:
- The lean production path now includes DeepSeek V4 Pro drafting plus GPT-5.4 Mini LineWriter before save.
- GateCritic, FinalGate, and PresenceChecker now route to Grok 4.1 Fast.
- New `micro_repair` stage sits between CanonExpert and the save-blocker layer (flag-gated but wired into the scene path).
- `corrective_rerun` + `canon_expert.apply_local_fixes` are newly landed escape hatches (flag-gated).

Before making any drafter/line-editor/judge config decision, re-run the climax scene **under the current config** to re-establish baselines. Word-count discipline remains the load-bearing metric. Cost and rerun-rate numbers should be collected fresh — do not compare against archived bench tables in `docs/editorial/`.

## Conventions to follow

- **Prefer editing existing files** to creating new ones, especially docs.
- **Do not add comments** unless the *why* is non-obvious. Current-task references (e.g. "added for Stage 3") rot fast — put those in the commit message.
- **Do not add backwards-compat shims** unless there is a concrete external caller that would break. Legacy shims under `src/concept_workshop/` already exist; do not add more.
- **Scene cards are contract.** `chapter_number`, `scene_number`, `pov_character`, `characters_present`, `mission`, `turning_point` are load-bearing required fields. Post-D2(c) additive enrichment: `turning_point_detail: {trigger, shift, cost}`, `emotional_arc: {start, shift, end}`, `key_beats: [3-5 items]`, `opening_mode`, and top-level `anti_patterns` are optional but land in the deterministic brief (`src/pipeline/brief_assembler.py`) when present. Legacy cards still validate; `brief_assembler` emits warnings to signal the migration backlog. `scripts/compile_bundle.py` runs jsonschema validation + cross-surface reference validation (`workflows/_shared/scene_card_references.py`) at compile time; bad cards fail `--strict` compile.
- **Agent context isolation**: LineWriter is the template — pass an explicit context dict. Do not let new agents reach into ambient `ContextAssembler` unless you have a reason.
- **Ledger events**: emit typed events with a `level` (info/warn/error) in the payload. Don't swallow errors in post-save phases silently — treat permanent failures as quarantine candidates.
