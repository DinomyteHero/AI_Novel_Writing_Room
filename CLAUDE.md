# CLAUDE.md — AI Writers' Room

Load-bearing notes for working on this codebase. Read before making changes.

## What this project is

A multi-agent fiction generation system. Humans plan a novel through the **workflow kit** (per-surface skills that produce `workflows/*.json`); `scripts/compile_bundle.py` merges those into a `concept_seed.json` + `scene_cards/`; then the **autonomous pipeline** drafts, line-edits, and saves each scene. Franchise-scoped, book-scoped, with per-run output isolation.

## The pipeline is lean — one forward pass, no gates

Prose flows through a **single forward pass**. There are no gates, no save-blocker layer, no quarantine, no retries, and no canon/presence validation in the save path. The canonical per-scene order (as implemented in `src/orchestrator.py::run_chapter`):

```
PlotArchitect → ProseStylist → [LineWriter] → [RhythmValidator → RhythmEditor]
  → save → post-save memory
```

`[...]` = optional / flag-gated.

Post-save memory (when the dependencies are wired): `Summarizer → ChromaDB chapter memory → state diff → contradiction scan → worldbuilding extraction`.

Rules:

- **The drafter lands the contract on the first pass.** The structural framework (Brooks beat map + Weiland arc map + scene contract) is enforced *upstream* at planning + scene-card validation time, and the chapter packet hands the drafter a single inspectable runtime contract. There is no save-time editorial gate to catch drift — quality is a planning-and-prompt problem, not a retry problem.
- **No retries.** There is no retry branch in the relay. Do not add one. There is no `max_structural_retries` / `max_voice_retries`; those keys were removed.
- **Length calibration is a rendering multiplier, not a planning change.** `runtime.lean_prose_only.length_calibration` (default 1.0) inflates the word-count ask rendered into the drafter's Task block; the scene card's `target_word_count` stays the planning truth and word-count telemetry still measures drift against it. Measured 2026-06-09: DeepSeek V4 Pro delivers ~43-58% of any asked length, so The Unfinished Shadow sets 1.8 in its runtime_overrides. Tune per book from bench evidence, never by feel.
- **LineWriter is the single post-draft edit.** `runtime.lean_prose_only.line_edit.enabled: true` (shipping default) runs `LineWriter` once after the drafter when `agent_routing.line_writer` is present. Disable just the line edit with `runtime.lean_prose_only.line_edit.enabled: false`. LineWriter takes an **explicitly wired** context dict — do not let it reach into ambient `ContextAssembler`. Collapsed output (<40% source word count) falls back to drafter prose with a warn event (`line_writer_collapsed`); a LineWriter crash also degrades to drafter prose (`line_writer_error`).
- **RhythmValidator + RhythmEditor are advisory.** They run after LineWriter, both flag-gated and default-off. RhythmValidator only measures and emits revision-debt rows — it never blocks or mutates. RhythmEditor applies bounded literal edits under deterministic safety caps. Neither can abort a save.
- **Revision-debt rows and rhythm telemetry are advisory.** They are a structured store for human triage. Nothing in the save path reads them to decide whether to save.
- **Declared state is the trusted writer.** `runtime.declared_state.enabled` (default false) applies scene-card `end_state` declarations to `characters.status` (story_state schema v8) after post-save — declarations win over the Summarizer's extracted diff, so trusted physical state comes from planning, never LLM inference. Declared `start_state` is verified against accumulated state at scene open; drift outside the natural-transition taxonomy emits a `declared_state_conflict` warn plus a `prose.continuity.character_state_break` debt row, never a block. Events: `declared_state_applied` (info), `declared_state_conflict` / `declared_state_unknown_character` / `declared_state_error` (warn). The hook is `Orchestrator._maybe_apply_declared_state`, sharing collectors and transition taxonomy with `src/quality/cross_chapter_validator.py`.
- **Chapter-close memos auto-emit at chapter boundaries** when `runtime.revision_debt.enabled` is on: `Orchestrator._maybe_write_chapter_memo` writes the `ChapterCloseMemoGenerator` artifact to `<run_dir>/memos/` as each chapter closes (also after a failed last scene), emitting `chapter_memo_written` (info) / `chapter_memo_error` (warn). The memo is the operator's per-chapter triage checkpoint — no `debt_cli` invocation needed.
- **Post-save stages are wrapped with broad error guards.** Summarizer / state-diff / contradiction scan / worldbuilding extraction and the promise-ledger hook each catch `Exception` and emit a warn-level event (`post_save_error` with a `stage` tag, or a stage-specific event). A crash in any post-save stage never aborts a saved scene — next-scene state may be stale, so the warn is load-bearing.
- Adding a new runtime flag without `default: false` (or the safest equivalent) is a review-blocker.

## The lean prose path

`runtime.lean_prose_only.enabled: true` is the shipping default and describes **the** pipeline. The orchestrator drafts the scene, runs the configured `LineWriter` once before saving (`runtime.lean_prose_only.line_edit.enabled: true`), optionally runs the rhythm stages, then saves prose directly as `saved_clean`.

Why it is safe: the structural framework (Brooks beat map + Weiland arc map + scene contract) is enforced *upstream* at planning + scene-card validation time, and the post-D2(c) enriched scene cards + chapter packet give the drafter enough information to land the contract on the first pass. There is no separate "full relay" — gates, save-blockers, and quarantine were removed from the codebase, not merely flag-gated off.

## Slice 2: chapter packet (shipping default ON; revision debt default off)

Slice 2 ships the drafter's single inspectable runtime contract and the structured advisory store. **The chapter packet ships on by default (D4a rollout)** — it is the drafter's runtime contract. `runtime.revision_debt.enabled` remains default-off pending per-book sign-off.

- **One chapter packet contract.** `src/pipeline/chapter_packet.py` defines `ChapterPacket` (frozen dataclass) + `ChapterPacketCompiler`. The compiler builds a **base** once per chapter (`compile_base(chapter_number)`) from the blueprint + seed; a per-scene **overlay** composes the base with the current scene card (`compile_overlay(base, scene_card, trusted_state_snapshot)`). Bases are **immutable**; overlays return new packets with `overlay_version` incremented. The overlay renderer embeds the legacy `ContextAssembler.assemble()` output so the packet is a strict token-superset of flat (enforced by `tests/test_packet_parity.py`).
- **Shipping default: `runtime.chapter_packet.enabled: true`** (D4a). `ProseStylist` runs on the packet path; the orchestrator still computes flat `assembled_context` for the `runtime.chapter_packet.fallback_on_error: true` escape hatch. On compile error a `packet_fallback_flat` warn event fires and the drafter gets flat context. Compiled packets land at `<run_dir>/chapter_packets/chapter_NN.json` (base) + `chapter_NN_sc_MM_overlay.json` (overlay) with a `packet_base_compiled` / `packet_overlay_written` info event. Slice 3 (`active_promises`) plugs a collaborator into the same compiler; that field populates only when `runtime.promise_ledger.enabled` is on.
- **Revision debt store.** `src/pipeline/revision_debt.py` (`RevisionDebtStore`) persists structured advisories to `output/<franchise>/<book>/state/revision_debt.db` (separate from `story_state.db` to keep that file's migration surface stable). The `category` enum is **closed** — `CATEGORIES` in the module and the `enum` in `schemas/revision_debt.json` must stay in lockstep, and `store.add` raises `ValueError` on unknown categories. `owner_or_reviewer_notes` is human-only: any agent trying to write to it raises on the `add` path.
- **Write-matrix.** Every advisory stage routes through a wrapper in `src/pipeline/revision_debt_producers.py` — `emit_metric_advisory`, `emit_wordcount_drift`, `emit_rhythm_advisory`, `emit_continuity_break`, `emit_scene_reviewer_finding`, and the other producers. Wrappers short-circuit to noop when `runtime.revision_debt.enabled: false`; the orchestrator never calls `store.add` directly. Status transitions go through `emit_status_update`, which logs `revision_debt_updated`.
- **Chapter memos.** `src/pipeline/chapter_memos.py` (`ChapterCloseMemoGenerator`, `MilestoneMemoGenerator`) synthesize debt + pending promises into per-chapter and cross-chapter human-review memos under `<run_dir>/memos/`. The CLI at `scripts/debt_cli.py` supports `list`, `update`, `memo chapter`, `memo milestone`.
- **Migration.** `scripts/migrations/migrate_revision_debt.py` walks every `output/**/state/` dir and idempotently ensures `revision_debt.db` exists with the current schema. Re-running is safe.
- **New ledger events (all `emit_{info,warn,error}`):** `packet_base_compiled` (info), `packet_overlay_written` (info), `packet_fallback_flat` (warn), `revision_debt_added` (info), `revision_debt_updated` (info).
- **Shipping-book guards.** `tests/test_runtime_flags.py::test_shipping_books_run_chapter_packet_by_default` catches a runtime_override that *disables* the packet on Ruusan or Betrayal. `::test_shipping_books_keep_revision_debt_off` blocks revision_debt from flipping on accidentally before its per-book sign-off.

## Slice 3: promise ledger (feature-flagged, default off)

Slice 3 ships the first trusted stateful-memory artifact: a **declaration-driven** promise ledger. Populated from planning + scene cards, never inferred by LLMs. `runtime.promise_ledger.enabled` defaults `false` on Ruusan and Betrayal until their per-book parity tests land.

- **Store.** `src/memory/promise_ledger.py` (`PromiseLedger`) backs `output/<franchise>/<book>/state/promise_ledger.db`. `initialize_from_planning(concept_seed, scene_cards)` seeds from `story_physics.promise_payoff_ledger` + scene-card `promises_planted` / `promises_paid` (idempotent; existing `progression_log` preserved). **Seeding never marks a promise paid**: scene-card `promises_paid` is the *scheduled* payoff location and only refines `due_by_scene`; runtime `record_payoff` (scene save or patch replay) is the sole writer of `status='paid'` / `payoff_scene`. Scene IDs use `chNN_scMM`; the sentinel `chNN_sc99` represents chapter-end when planning only names a chapter. `initialize_from_planning` drops entries with no derivable `setup_scene` rather than writing a row that would fail the NOT NULL constraint.
- **Wiring.** `src/main.py` constructs the ledger at `paths.state_dir / "promise_ledger.db"` (series-scoped when `meta.series_id` is set) **only when the flag resolves on**, and passes it to both `build_chapter_packet_compiler` and the `Orchestrator` — packets must stay promise-free for books that haven't signed off.
- **Trust model.** Ledger rows move through `record_progression` / `record_payoff` / `record_broken` only. `overdue` is derived at read time (`list_overdue`), never stored.
- **Scene-card contract.** Optional field `promises_progressed: [<promise_id>, ...]`. At save time the orchestrator (`_maybe_record_promise_deltas`) appends one entry to each promise's `progression_log` with `source='scene_card'` and emits a `promise_progressed` info event. `promises_paid` emits `promise_paid`. Unknown IDs emit a warn-level event (planning drift) but do not abort the run.
- **Packet integration.** `ChapterPacketCompiler.compile_overlay` calls `list_top_urgent(at_scene=scene_id, n=5)` so the drafter sees urgency-ranked promises *as of this scene*, not a chapter snapshot. `active_promises_total_count` tails the top-5 list (dilution guard). Overdue rows carry `status='overdue'` + `overdue_by_scenes`; the renderer emits them under a separate *"Overdue promises (advisory only — do not force payoff)"* heading. `compile_base` still uses `active_for_chapter(chapter_number)` because the scene is not yet known there; the overlay replaces that snapshot per scene.
- **Migration.** `scripts/migrations/migrate_promise_ledger.py` walks every `output/<franchise>/<book>/state/` dir, pairs it with `data/franchises/<franchise>/books/<book>/`, seeds `promise_ledger.db` from that book's planning. Series-scoped state dirs (`output/<franchise>/<series>/state/`, no same-named book) resolve to every franchise book whose `meta.series_id` matches and seed from each. Idempotent (UPSERT on `promise_id`; re-seeding never clobbers a runtime status). `--dry-run` reports plan without writes.
- **New ledger events (all `emit_{info,warn,error}`):** `promise_planted` (info), `promise_progressed` (info), `promise_paid` (info), `promise_overdue` (warn). The warn-level path fires from `_maybe_record_promise_deltas` after save so the operator sees slipping promises in the feed.
- **Shipping-book guard** at `tests/test_runtime_flags.py::test_shipping_books_keep_promise_ledger_off` blocks an accidental `runtime_overrides.yaml` flipping the flag on Ruusan or Betrayal before their parity test lands.

## Slice 6: manuscript lifecycle design + patch workflow

Slice 6 is the bridge between the per-scene runtime and coherent manuscript-level editorial. The design doc lives at `docs/architecture/manuscript_lifecycle_design.md`; the load-bearing CLI ships alongside it.

- **Design doc.** `docs/architecture/manuscript_lifecycle_design.md` specifies developmental / line / copy / proof passes and defines the invariant: manuscript-level passes never rewrite prose in place during a drafting run — mutations route through `scripts/patch_workflow.py`.
- **Patch workflow CLI.** `scripts/patch_workflow.py` with these subcommands:
  - `replace <scene_id> --from <path>` overwrites saved prose with a human edit; replays declarative promise-ledger state from the scene card.
  - `apply-manuscript-patch <patch_path>` dispatches JSON batches matching `schemas/manuscript_patch.json`. Duplicate `replace` entries for the same scene are rejected before any mutation.
- **Replay semantics.** Scene-card `promises_progressed` / `promises_paid` are re-applied on every `replace`, so the promise ledger converges to the scene card's declaration. Per-overlay markers at `<run_dir>/chapter_packets/chapter_NN_sc_MM_overlay.STALE` are advisory; `Orchestrator._maybe_compile_overlay` notices them, emits a `packet_overlay_written` info event with `stale_marker_cleared=true`, and deletes them (overlays already rebuild every scene so the marker is a human-audit trail, not a cache-invalidation signal).
- **Export scaffolding.** `scripts/manuscript_export.py` walks a run's `chapters/` dir and stitches `manuscript.md` + `chapter_index.md` under `<project_root>/export/`. Deliberately simple — EPUB / PDF wrapping is deferred.
- **Schema.** `schemas/manuscript_patch.json` with a closed action enum and scene-id pattern enforcement. `source_pass` tags each mutation with its originating pass so downstream memos can attribute it.

## Prose-rhythm validator + cross-chapter continuity (feature-flagged, default off)

Two deterministic validators, scoped narrowly at the patterns a Zahn/Allston commercial-tie-in baseline catches and our manuscripts repeatedly miss. Both are pure analyzers — no LLM dependency — and both are default-off so shipping books keep current behavior until a per-book review approves the telemetry surface.

- **RhythmValidator** (`src/quality/rhythm_validator.py`). Pure measurement of five rhythm metrics: em-dash density per 1k words, consecutive short-sentence runs, default-opener percentage (He/She/They/It/The/There), dialogue-bearing paragraph percentage, and abstract-construction tic density ("the particular X", "something adjacent", "not quite Y", etc.). Default thresholds calibrated against the Scoundrels (Zahn, 2013) corpus baseline. Returns a `RhythmResult` dataclass; emits issues at `low` (advisory band) or `medium` (warn band). The validator never blocks a save — it produces revision-debt rows of category `prose.rhythm.*` through `emit_rhythm_advisory()`. Runtime flag: `runtime.rhythm_validator.enabled` (default false). Shipping-book guard at `tests/test_runtime_flags.py::test_shipping_books_keep_rhythm_validator_off`.
- **CrossChapterContinuityValidator** (`src/quality/cross_chapter_validator.py`). Pre-draft check that walks the ordered scene-card list at bundle-compile time and flags declared discontinuities in character state, location, and plot-object holders. Only fires on *declared contradictions* — silence is not a continuity break. Recognizes `_NATURAL_TRANSITIONS` (alive→wounded, alive→dead, etc.) and `_REQUIRES_BRIDGE` transitions (dead→alive, etc.) where an off-page event must explain the change. Emits revision-debt rows of category `prose.continuity.*` through `emit_continuity_break()`. Runtime flag: `runtime.continuity_validator.enabled` (default false). Shipping-book guard at `tests/test_runtime_flags.py::test_shipping_books_keep_continuity_validator_off`.
- **RhythmEditor agent** (`src/agents/rhythm_editor.py` + `prompts/agent_system_prompts/rhythm_editor.md`). LLM-driven literal-edit pass that consumes RhythmValidator issues and proposes bounded substring edits to fix them. Exact-span literal replacements only, no regex, unique-occurrence requirement, per-call edit cap, total changed-char budget, ratio ceiling. `apply_rhythm_edits()` is the deterministic orchestrator-side helper that enforces the caps regardless of model output. Handles four issue codes (`em_dash_overuse`, `staccato_cluster`, `opener_monotone`, `abstract_tic`); skips `dialogue_starved` because dialogue creation requires generative work the drafter should own. Runtime flag: `runtime.rhythm_editor.enabled` (default false) plus trigger-code list and safety caps. Shipping-book guard at `tests/test_runtime_flags.py::test_shipping_books_keep_rhythm_editor_off`. Agent routing entry at `agent_routing.rhythm_editor` (DeepSeek V4 Pro @ t=0.2, 4096 max_tokens).
- **Orchestrator integration** (`src/orchestrator.py::_maybe_rhythm_validate_and_edit`). The orchestrator invokes RhythmValidator and (when actionable issues are detected) RhythmEditor between LineWriter and `_save_chapter`, so the saved prose is the post-edit version. Flow: PlotArchitect → ProseStylist → LineWriter → RhythmValidator → [RhythmEditor → apply_rhythm_edits] → save. Both stages are flag-gated and noop when off. The `lean_prose_only_saved` ledger event carries `rhythm_validator_enabled`, `rhythm_editor_enabled`, and `rhythm_edit_applied` so a run's per-scene rhythm work is auditable. `dialogue_starved` is intentionally not in the editor's trigger set — that issue means the drafter should re-balance, not the editor should patch.
- **New revision-debt categories** (`schemas/revision_debt.json` + `src/pipeline/revision_debt.py::CATEGORIES`, in lockstep): `prose.rhythm.em_dash_overuse`, `prose.rhythm.staccato_cluster`, `prose.rhythm.opener_monotone`, `prose.rhythm.dialogue_starved`, `prose.rhythm.abstract_tic`, `prose.continuity.character_state_break`, `prose.continuity.location_break`, `prose.continuity.object_location_break`. The schema/Python enum-parity test at `tests/test_revision_debt.py::test_categories_match_schema` enforces lockstep.
- **Scene-card fields**:
  - `dialogue_density_target: high | medium | low` — optional. Consumed by ProseStylist (drafting bias) and by RhythmValidator (suppresses the dialogue-starved check when target is `low`). Default derivation: any scene with 2+ characters present and `dialogue_expectation != "interior"` defaults to `high`.
  - `interiority_budget: {max_words, max_paragraphs, rationale?}` — optional hard ceiling on per-scene interior-monologue word and paragraph counts. ProseStylist treats the values as ceilings, not targets, and converts overflow reflection into dialogue, action, or sensory observation. Default when omitted: derived from `dialogue_expectation` (`dialogue_led` → 150 words / 2 paragraphs; `balanced` → 250 / 3; `interior` → 600 / 6).
  - `start_state` / `end_state` — optional declared per-character physical state at scene open/close. Either a `{name: state}` map or a `[{character, state}]` list; closed vocabulary (alive / wounded / unconscious / dead / captured / free / off_screen, plus synonyms normalized by the validator). `objects_at_open` / `objects_at_close` declare plot-object → holder mappings (holder strings compared verbatim across consecutive scenes — keep names consistent); `off_page_events` declares bridges for requires-bridge transitions (dead → alive). Declare only what the card text already establishes — silence is never a break. Consumed by the compile-time continuity validator and the runtime declared-state hook.
- **ProseStylist prompt.** `prompts/agent_system_prompts/prose_stylist.md` has a "Sentence Rhythm and Opener Variety" section with hard targets (opener variance ≤30%, no staccato clusters of 3+ sentences, em-dash budget ~3/1k words, dialogue floor 55% in multi-character scenes), an "Anti-Tics" section with explicit DO NOT examples (the "particular X" family, "something adjacent", narrator aphorism, the "did not name the feeling" construction), an "Interiority Budget" section that reads the scene-card field, and a "Register Anchor" section pointing at mid-tier Bantam/Del Rey commercial tie-in (Zahn, Allston, Stackpole) as the shipping target.
- **Bench harness extension** (`scripts/bench_prose_models.py`). The `--rhythm-metrics` flag computes RhythmValidator output for every prose variant in a bench run and embeds the metrics + issue list into `bench_summary.json["results"][i]["rhythm_metrics"]`. Use this when picking between drafter or line-editor configs; rhythm metrics are a load-bearing signal alongside word-count discipline.
- **Multi-POV chapter braiding** (`workflows/outline_planner/schema.json` + `SKILL.md` + `validate.py`). Two optional outline-entry fields:
  - `pov_sequence: [string, ...]` — ordered POV characters across this chapter's scenes, signalling intent to braid multiple POVs (e.g. `["Ben", "Tess", "Ben"]` for an A-B-A weave). `pov_character` remains the dominant / framing POV; `pov_sequence` carries the full weave.
  - `scene_briefs: [{scene_number, pov?, thread?, turning_point_hint?, structural_role?}, ...]` — optional per-scene shape seeds consumed by scene-card-authoring. The `thread` field is load-bearing for braided chapters: it tells scene-card-authoring which plot or character line each scene advances, so the cards don't drift into rehashing the same beat from different angles.
  - Validator enforces alignment between `pov_sequence` and `scene_briefs[].pov` when both are present, and rejects scene_briefs whose `scene_number` exceeds `pov_sequence` length.

## Pre-run architecture: canon guidance + preflight

Two pre-run subsystems run before any drafting:

- **Canon guidance store + canon_scout agent.** `src/pipeline/canon_guidance.py` + `src/agents/canon_scout.py`. Persists franchise-level canon tips (terminology, mechanics, period detail) at `data/franchises/<franchise>/canon_guidance.json`. The chapter packet's `canon_guidance` field surfaces relevant entries to the drafter via the "Static Canon Guidance" section in the rendered packet. CLI: `scripts/canon_scout.py` for authoring; `data/franchises/<f>/canon_guidance.json` is read at packet compile time. Coverage gaps surface as preflight warnings.
- **Preflight runner.** `src/pipeline/run_preflight.py` + `scripts/preflight_run.py`. Runs deterministic checks on planning artifacts before any LLM call: scene-card schema validity, cross-surface references resolve, canon guidance coverage. Surfaces all findings as a single report so the operator never wastes a run on a planning gap that could have been caught in seconds.

## Manuscript-level passes (post-production, opt-in)

Three off-path subsystems extend the per-scene pipeline without touching the lean per-scene path:

- **`src/quality/scene_contract_validator.py` + `src/quality/literal_repair.py`**. Deterministic per-scene contract checks (turning point present, characters present, structural-phase-appropriate moves). Not in the per-scene shipping path; `scripts/validate_scene_contract.py` runs them as a standalone diagnostic (`--contract <json> --prose <file>`) for recovery work.
- **Literary polish + final-copy.** `src/agents/literary_polish.py` + `src/pipeline/final_copy.py` + `scripts/final_copy_existing.py`. A post-production pass that runs *after* the per-scene pipeline finishes and prose is saved. Routes to a higher-tier model (default `gpt54`) for line-level literary polish. **Not** part of the per-scene pipeline; intended for the final pre-publication sweep, not for every drafting run. Configured under `runtime.final_copy.*`.
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

## Status vocabulary

Per-scene save status lives in `src/memory/story_state.py`. The lean pipeline produces two values:

- `saved_clean` — scene saved, no advisory fired. This is the normal outcome.
- `saved_with_advisory` — saved, but an advisory-level signal fired.

A third value, `quarantined`, survives in the `revision_status` DB enum for migration compatibility but **the lean pipeline never produces it** — quarantine and the save-blocker layer were removed. The old vocabulary (`gate_passed`, `polished`, `approved`, `gate_failed`, `gate_skipped`, `final_gate_rejected`) is gone; `scripts/migrations/migrate_status_vocab.py` auto-migrates existing `story_state.db` files. Ledger emits carry a `level` (`info` / `warn` / `error`) in the payload.

## Franchise-scoped paths

Always route I/O through `src/project_paths.ProjectPaths`. Do not hand-construct paths under `data/` or `output/`.

- Inputs: `data/franchises/<franchise>/books/<book>/` (`concept_seed.json`, `scene_cards/`, `chapter_blueprints/`, `workflows/`).
- Franchise-shared resources: `data/franchises/<franchise>/{canon_db/, worldbuilding.db, worldbuilding_vectors/}` (shared across books in the franchise).
- Outputs: `output/<franchise>/<book>/` with `state/` (book-scoped or series-scoped SQLite/ChromaDB/ledger), `runs/<run_id>/chapters/` (per-run isolated prose + `config_snapshot.yaml`), `export/`.
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
| Agents | `src/agents/` (see `src/agents/README.md` for the scene-path/utility split) |
| Chapter packet (Slice 2, shipping default ON) | `src/pipeline/chapter_packet.py` |
| Canon guidance store + canon_scout agent | `src/pipeline/canon_guidance.py`, `src/agents/canon_scout.py`, `scripts/canon_scout.py` |
| Pre-run preflight | `src/pipeline/run_preflight.py`, `scripts/preflight_run.py` |
| Scene-contract validator + literal repair (bench/diagnostic) | `src/quality/scene_contract_validator.py`, `src/quality/literal_repair.py` |
| Rhythm validator (deterministic prose telemetry, default off) | `src/quality/rhythm_validator.py` |
| Rhythm editor agent (literal-edit pass, default off) | `src/agents/rhythm_editor.py`, `prompts/agent_system_prompts/rhythm_editor.md` |
| Cross-chapter continuity validator (default off) | `src/quality/cross_chapter_validator.py` |
| Literary polish + final-copy (post-production) | `src/agents/literary_polish.py`, `src/pipeline/final_copy.py`, `scripts/final_copy_existing.py` |
| Manuscript reviewer (developmental pass) | `src/agents/manuscript_reviewer.py` |
| Idea-session capture (Claude/Codex portable) | `workflows/idea_session_capture/api.py`, `scripts/idea_session_capture.py`, `AGENTS.md` |
| Scene-card cross-surface validator | `workflows/_shared/scene_card_references.py` |
| Scene-card enrichment migration | `scripts/enrich_scene_cards.py` |
| Revision-debt store + producers (Slice 2) | `src/pipeline/revision_debt.py`, `src/pipeline/revision_debt_producers.py` |
| Chapter memos | `src/pipeline/chapter_memos.py` |
| Promise ledger (Slice 3) | `src/memory/promise_ledger.py` |
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
| Migration wrappers | `scripts/migrations/migrate_all.py`, plus per-store `scripts/migrations/migrate_*.py` scripts |
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

**Hand-edit drift guard + provenance.** `compile_bundle.py` refuses to overwrite `concept_seed.json` / `scene_cards/` when they were never produced by a compile here (no `compile_report.json`), when they were hand-edited after the last compile while the workflow surfaces went stale (mtime check), or when the seed declares `compile_metadata.managed_by: "direct"` — the marker for ingested, hand-maintained books (The Unfinished Shadow is one; its `workflows/` skeleton is stale by design). Override with `--force-overwrite-newer`. Compiler-written seeds always stamp `managed_by: "workflow_kit"`. A blocked run writes nothing, not even the compile report.

Canonical helpers live under `workflows/_shared/` (`seed_transforms.py`, `scene_card_translator.py`) and `workflows/voice_discovery/api.py` (`VoiceDiscovery`). The old re-export shims at `src/concept_workshop/{seed_transforms,scene_card_translator,voice_discovery}.py` have been removed. The remaining modules under `src/concept_workshop/` (`compliance_validator.py`, `series_manager.py`, `stress_test.py`) are canonical, not shims, and are still the right import path.

**Codex parity:** the `idea-session-capture` surface runs identically in Claude Code and Codex — the conversation contract is at `workflows/idea_session_capture/SKILL.md` and Codex enters via `AGENTS.md` at the repo root. The other six surfaces are Claude-Code-skill-shaped today; they have headless apis (`workflows/<surface>/api.py`) so Codex can drive them programmatically, but their interactive-chat ergonomics are tuned for the Claude Code skill harness. Use Codex for idea-session and scripted operations; use Claude Code for the structured-surface chats.

## Testing

- Full suite: `pytest -q`.
- Some tests skip without optional deps (chromadb, sentence-transformers, fastapi); that is expected.
- Web-path regression set: `pytest tests/test_websocket_ledger.py tests/test_run_ledger.py tests/test_api_pipeline.py tests/test_api_ledger.py tests/test_ui_pipeline_blueprint_wiring.py -q`.

### Windows Python invocation

In the current PowerShell workspace, `python` resolves correctly and is used throughout the docs. If a Windows shell ever routes bare `python` to the Microsoft Store installer stub, use `py -3` or the explicit interpreter at `/c/Users/lbouw/AppData/Local/Programs/Python/Python312/python.exe`.

## Benchmarking

`scripts/bench_prose_models.py` runs a single scene through multiple drafter/line-editor configurations and writes to `output/<franchise>/<book>/runs/bench-<date>-<scene>/`. Summary markdown goes under `docs/editorial/` or alongside the bench run.

**All pre-2026-04-21 bench numbers are invalidated.** The pipeline shape changed enough between them and HEAD that cost, word-count, and quality figures from those runs no longer predict current behavior. Before making any drafter / line-editor config decision, re-run the climax scene **under the current config** to re-establish baselines. Word-count discipline remains the load-bearing metric; rhythm metrics (`--rhythm-metrics`) are the secondary signal. Cost numbers should be collected fresh — do not compare against archived bench tables in `docs/editorial/`.

## Conventions to follow

- **Prefer editing existing files** to creating new ones, especially docs.
- **Do not add comments** unless the *why* is non-obvious. Current-task references (e.g. "added for Stage 3") rot fast — put those in the commit message.
- **Do not add backwards-compat shims** unless there is a concrete external caller that would break. The old re-export shims under `src/concept_workshop/` (seed_transforms, scene_card_translator, voice_discovery) have already been removed; do not re-add them. The remaining modules in that package (`compliance_validator`, `series_manager`, `stress_test`) are canonical, not shims.
- **Scene cards are contract.** `chapter_number`, `scene_number`, `pov_character`, `characters_present`, `mission`, `turning_point` are load-bearing required fields. Additive enrichment: `turning_point_detail: {trigger, shift, cost}`, `emotional_arc: {start, shift, end}`, `key_beats: [3-5 items]`, `opening_mode`, `dialogue_density_target`, `interiority_budget`, `start_state` / `end_state` / `objects_at_open` / `objects_at_close` / `off_page_events`, and top-level `anti_patterns` are optional but consumed by the drafter, the rhythm validator, and the continuity/declared-state hooks when present. The translator passthrough list in `workflows/_shared/scene_card_translator.py` must carry every optional field — a field missing there is silently dropped on recompile. Legacy cards still validate. `scripts/compile_bundle.py` runs jsonschema validation + cross-surface reference validation (`workflows/_shared/scene_card_references.py`) at compile time; bad cards fail `--strict` compile.
- **Agent context isolation**: LineWriter is the template — pass an explicit context dict. Do not let new agents reach into ambient `ContextAssembler` unless you have a reason.
- **Ledger events**: emit typed events with a `level` (info/warn/error) in the payload. Don't swallow errors in post-save phases silently — emit a warn-level event so a stale-state run is auditable.
