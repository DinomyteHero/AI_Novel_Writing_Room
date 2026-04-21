# CLAUDE.md — AI Writers' Room

Load-bearing notes for working on this codebase. Read before making changes.

## What this project is

A multi-agent fiction generation system. Humans plan a novel through the **workflow kit** (per-surface skills that produce `workflows/*.json`); `scripts/compile_bundle.py` merges those into a `concept_seed.json` + `scene_cards/`; then the **autonomous pipeline** drafts, line-edits, evaluates, and saves each scene. Franchise-scoped, book-scoped, with per-run output isolation.

## The relay is forward-only — do not re-introduce retries

Since the Stage 1a–3 refactor, prose flows through a **single-pass relay**. Gates are telemetry. Retry loops have been deliberately removed. The canonical order per scene:

```
PlotArchitect → ProseStylist → [LineWriter] → GateCritic → QualityMetrics
  → QualityPolish → compression advisory → FinalGate → CanonExpert
  → save-blocker layer → save | quarantine
```

Rules:

- **GateCritic** and **FinalGate** are **advisory**. `final_gate_rejection` carries `advisory_only=True`; the polished prose is saved regardless.
- **`max_structural_retries` / `max_voice_retries`** are pinned to `0` in `config/settings.yaml`. They are retained only for rollback. Do not raise them, and do not add new retry branches.
- **Compression guard** is advisory too: polish that shrinks below 60% of pre-polish word count emits a ledger event and is saved anyway.
- **LineWriter** is optional (GPT 5.4 @ t=0.8 by default). It takes an **explicitly wired** context dict — do not let it reach into ambient `ContextAssembler`. Collapsed output (<40% source word count) falls back to drafter prose with a warn event.
- The **save-blocker layer** (`src/pipeline/save_blockers.py`) is the **only** hard-failure path. Three categories: `CHARACTER_PRESENCE_BLOCKER` (from PresenceChecker), `CANON_BLOCKER` (CanonExpert verdict = fail + severity ∈ {critical, moderate}), and a POV advisory (not yet blocking). When a blocker fires, the run aborts and the offending scene is written to `<project>/quarantine/chNN_scMM/{prose.md, blockers.json, brief.json}`.

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

## Slice 2: chapter packet + revision debt (feature-flagged, default off)

Slice 2 ships the drafter's single inspectable runtime contract and the structured advisory store. Both are **off by default** on Ruusan and Betrayal until their per-book parity tests land.

- **One chapter packet contract.** `src/pipeline/chapter_packet.py` defines `ChapterPacket` (frozen dataclass) + `ChapterPacketCompiler`. The compiler builds a **base** once per chapter (`compile_base(chapter_number)`) from the blueprint + seed; a per-scene **overlay** composes the base with the current scene card and open gap notes (`compile_overlay(base, scene_card, trusted_state_snapshot)`). Bases are **immutable**; overlays return new packets with `overlay_version` incremented. The overlay renderer embeds the legacy `ContextAssembler.assemble()` output so the packet is a strict token-superset of flat (enforced by `tests/test_packet_parity.py`).
- `runtime.chapter_packet.enabled: true` switches `ProseStylist` to the packet path; the orchestrator still computes flat `assembled_context` for the `runtime.chapter_packet.fallback_on_error: true` escape hatch. On compile error a `packet_fallback_flat` warn event fires and the drafter gets flat context. Compiled packets land at `<run_dir>/chapter_packets/chapter_NN.json` (base) + `chapter_NN_sc_MM_overlay.json` (overlay) with a `packet_base_compiled` / `packet_overlay_written` info event. Slice 3 (`active_promises`), Slice 4 (`continuity_events`), and Slice 5 (`relationship_context`) plug collaborators into the same compiler — those fields stay empty at Slice 2.
- **Revision debt store.** `src/pipeline/revision_debt.py` (`RevisionDebtStore`) persists structured advisories to `output/<franchise>/<book>/state/revision_debt.db` (separate from `story_state.db` to keep that file's migration surface stable). The `category` enum is **closed** — `CATEGORIES` in the module and the `enum` in `schemas/revision_debt.json` must stay in lockstep, and `store.add` raises `ValueError` on unknown categories. `owner_or_reviewer_notes` is human-only: any agent trying to write to it raises on the `add` path.
- **Write-matrix (spec §6.2.1).** Every advisory stage routes through a wrapper in `src/pipeline/revision_debt_producers.py` — `emit_canon_advisory`, `emit_canon_fix_rejected`, `emit_canon_polish_drift`, `emit_gate_critic_advisory`, `emit_final_gate_advisory`, `emit_metric_advisory`, `emit_presence_near_miss`, `emit_blocker_record` (severity pinned `high`), `emit_wordcount_drift`, `emit_compression_advisory`, `emit_scene_reviewer_finding`, `emit_scene_reviewer_other`. Wrappers short-circuit to noop when `runtime.revision_debt.enabled: false`; the orchestrator never calls `store.add` directly. Status transitions go through `emit_status_update`, which logs `revision_debt_updated`.
- **Chapter memos.** `src/pipeline/chapter_memos.py` (`ChapterCloseMemoGenerator`, `MilestoneMemoGenerator`) synthesize debt + gap notes + pending promises into per-chapter and cross-chapter human-review memos under `<run_dir>/memos/`. The CLI at `scripts/debt_cli.py` supports `list`, `update`, `memo chapter`, `memo milestone`.
- **Migration.** `scripts/migrate_revision_debt.py` walks every `output/**/state/` dir and idempotently ensures `revision_debt.db` exists with the current schema. Re-running is safe.
- **New ledger events (all `emit_{info,warn,error}`):** `packet_base_compiled` (info), `packet_overlay_written` (info), `packet_fallback_flat` (warn), `revision_debt_added` (info), `revision_debt_updated` (info).
- **Shipping-book guards** at `tests/test_runtime_flags.py::test_shipping_books_keep_chapter_packet_off` and `::test_shipping_books_keep_revision_debt_off` block an accidental `runtime_overrides.yaml` flipping either flag for Ruusan or Betrayal before their parity test lands.

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

## Status vocabulary (three values only)

Per-scene save status lives in `src/memory/story_state.py`. Only three values are valid:

- `saved_clean` — all gates green, no advisories fired.
- `saved_with_advisory` — saved, but at least one advisory fired (final-gate rejection, compression advisory, POV heuristic, word-count drift).
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
| Path resolver | `src/project_paths.py` |
| Agents | `src/agents/` |
| Save-blocker layer | `src/pipeline/save_blockers.py` |
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
| Canonical shared helpers | `workflows/_shared/seed_transforms.py`, `workflows/_shared/scene_card_translator.py`, `workflows/voice_discovery/api.py` |

## Workflow kit is the only supported authoring path

The interactive `src.concept_workshop.workshop_runner` CLI was **removed**. Do not reference it in docs or code. New projects go through the per-surface skills (`universe-builder`, `canon-drafter`, `character-forge`, `outline-planner`, `voice-discovery`, `scene-card-authoring`). `scripts/compile_bundle.py` merges the surface outputs into the canonical `concept_seed.json`.

Canonical helpers live under `workflows/_shared/` (`seed_transforms.py`, `scene_card_translator.py`) and `workflows/voice_discovery/api.py` (`VoiceDiscovery`). The old re-export shims at `src/concept_workshop/{seed_transforms,scene_card_translator,voice_discovery}.py` have been removed. The remaining modules under `src/concept_workshop/` (`compliance_validator.py`, `series_manager.py`, `stress_test.py`) are canonical, not shims, and are still the right import path.

## Testing

- Full suite: `pytest -q` (≈1,440 tests across 103 files, ≈90s).
- Some tests skip without optional deps (chromadb, sentence-transformers, fastapi); that is expected.
- Web-path regression set: `pytest tests/test_websocket_ledger.py tests/test_run_ledger.py tests/test_api_pipeline.py tests/test_api_ledger.py tests/test_ui_pipeline_blueprint_wiring.py -q`.

### Windows: do not call `python` directly

The bare `python` alias routes to the Microsoft Store installer stub on this machine. Use `py -3` (resolves to Python 3.12.0) or the explicit interpreter at `/c/Users/lbouw/AppData/Local/Programs/Python/Python312/python.exe`. Do not run commands that hit the store stub. Verified working: `py -3 --version` → `Python 3.12.0`.

## Benchmarking

`scripts/bench_prose_models.py` runs a single scene through multiple drafter/line-editor configurations and writes to `output/<franchise>/<book>/runs/bench-<date>-<scene>/`. Cost per scene is typically ~$0.20 (full pipeline) or ~$0.12 (`--skip-gate-loop` / bench-cheap). Summary markdown goes under `docs/editorial/` or alongside the bench run. Before shipping a drafter/line-editor config change, re-run the climax scene at minimum — word-count discipline is the load-bearing metric, and GPT 5.4 overshoots at every temperature while Claude is the consistency floor.

## Conventions to follow

- **Prefer editing existing files** to creating new ones, especially docs.
- **Do not add comments** unless the *why* is non-obvious. Current-task references (e.g. "added for Stage 3") rot fast — put those in the commit message.
- **Do not add backwards-compat shims** unless there is a concrete external caller that would break. Legacy shims under `src/concept_workshop/` already exist; do not add more.
- **Scene cards are contract**. `chapter_number`, `scene_number`, `pov_character`, `characters_present`, `mission`, `turning_point` are load-bearing. There is no load-time schema validation yet; bad cards fail mid-pipeline.
- **Agent context isolation**: LineWriter is the template — pass an explicit context dict. Do not let new agents reach into ambient `ContextAssembler` unless you have a reason.
- **Ledger events**: emit typed events with a `level` (info/warn/error) in the payload. Don't swallow errors in post-save phases silently — treat permanent failures as quarantine candidates.
