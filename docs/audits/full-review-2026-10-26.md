# Full Review - AI Writers' Room

**Date:** 2026-10-26  
**Revision reviewed:** `main` @ `83b4ac8` (clean working tree)  
**Scope:** runtime correctness, planning/data integrity, documentation/operator flow,
security/configuration, tests/maintainability, and a light manuscript spot-check.

**Method.** Full `pytest -q` run, `ruff check .`, read-only code inspection, deterministic
preflight for all three books, schema/reference/physics probes, and read-only data analysis.
No LLM calls were made and no source files were changed.

**Baseline:** 1,685 tests passed, 2 skipped, 0 failed in ~105 s. `ruff check .` passes.
The two skips are the live prose-parity tests, which require an explicit `PARITY_RUN_PATH`.

> **Post-review cleanup (same day).** The outdated generated draft runs were removed.
> The dead modules/tests identified here were deleted, the read-only web console
> replaced the pipeline-control/quality/story-state/worldbuilding UI, and the core
> failure paths (failed-scene summary, empty prose, per-stage post-save guards,
> promise seeding/re-seed, chapter-log aggregation, memo metrics) were fixed.
> The suite now runs 1,569 tests. This report remains the pre-cleanup baseline.

---

## Verdict

This is a genuinely interesting and mostly coherent system. The lean forward-pass
architecture is internally consistent, the chapter packet is a real improvement over
ambient context assembly, the structural validators are thoughtful, and the unit test
surface is broad and fast.

It is **not release-clean**. The main risks are not missing features; they are
**silent bad states**: a failed scene can crash the run summary, empty prose is saved
as `saved_clean`, a post-save failure can skip the state diff without failing the
scene, and the promise ledger ignores the planning ledger for workflow-kit books.
Documentation also overstates several guarantees ("each post-save stage is guarded",
"`saved_with_advisory`", "preflight checks cross-surface references",
"canon guidance is franchise-level"), and the web surface bypasses the plan-approval
gate and has no authentication or Host/Origin validation.

The planning data is usable but uneven. Ruusan is the cleanest artifact set;
Betrayal has 65 unresolved character references and no enriched scene-card fields;
The Unfinished Shadow has 40/44 unresolvable POV strings and a missing series state
directory for the flags its runtime overrides enable.

### Scorecard

| Area | Grade | Comment |
|---|---|---|
| Lean runtime architecture | B+ | Clear stage order, explicit contracts, good degradation intent |
| Runtime failure handling | C | Several silent/incorrect failure paths (`P1` below) |
| Planning/data integrity | C+ | Valid schemas, but reference and blueprint drift is invisible to preflight |
| Documentation accuracy | C | Strong prose, but several material contradictions with code |
| Test suite | B+ | 1,685 tests, fast, but key failure paths are untested and parity tests skip |
| Security (loopback-only) | B- | Acceptable if never exposed; no auth/Host/Origin and a Windows path traversal |
| Security (if exposed) | D | Full read/write control of the project and manuscript |
| Maintainability | B- | Good structure; dead subsystems and stale comments remain |

---

## Fix-first list

| ID | Severity | Finding | Fix size |
|---|---|---|---|
| R1 | P1 | Failed scene crashes the CLI summary (`KeyError: word_count`) | Small |
| R2 | P1 | Empty drafter output is saved and reported `saved_clean` | Small |
| R3 | P1 | Post-save guard is outer, not per-stage; a ChromaDB failure skips state diff | Small |
| R4 | P1 | Promise ledger reads only `story_physics`; compiler/schema put the ledger top-level | Medium |
| R5 | P1 | Web runs bypass the plan-approval gate and abort on one scene failure | Small/Medium |
| R6 | P1 | Security cluster: session-ID traversal and unauthenticated web API (see SEC1/SEC2) | Medium |
| R7 | P2 | Multi-scene chapter log is overwritten by the last scene | Medium |
| R8 | P2 | Promise re-seed wipes runtime `payoff_scene` while leaving `status=paid` | Small |
| R9 | P2 | Preflight does not check cross-surface references or blueprint schema | Small |
| R10 | P2 | Word-count telemetry module is never called; memo word-count metrics are always zero | Small |
| R11 | P2 | Memo metrics: resolution rate always 0, max drift hardcoded 0, promises render as dicts | Small |
| R12 | P2 | `CancelledError` is retried; stop/shutdown can re-issue paid requests | Small |
| R13 | P2 | Placeholder skeletons can compile and be approved/drafted with no `<EDIT_ME>` guard | Small |
| R14 | P2 | `compile_bundle` writes seed/cards before schema/compliance failure | Medium |
| D1 | P1 | Unfinished Shadow's enabled state is absent | Data/ops |
| D2 | P2 | Betrayal: 65 unresolved character refs, 0/60 enriched cards, 0 promise links | Data fix |
| D3 | P2 | Unfinished POV shorthand defeats arc lookup (40/44 cards) | Data/code |
| D4 | P2 | Unfinished blueprints lag 5-6 added cards | Data fix |
| D5 | P2 | Ruusan: 2 invalid blueprint roles, promise plant/payoff drift | Data fix |
| D6 | P2 | Declared-state contract barely exercised on any book | Data fix |
| D7 | P2 | Word-count targets exceed meta on all three books | Planning call |
| D8 | P2 | Ruusan/Betrayal have no prose; cited output evidence is absent | Ops/repro |
| DOC1 | P2 | Plan approval missing from the A-to-Z docs | Small docs |
| DOC2 | P2 | Preflight-before-production always fails on missing blueprints | Small docs/code |
| DOC3 | P2 | `--book` is not applied to `ProjectPaths.project_slug` | Small |
| DOC4 | P2 | Canon-guidance location/scope wrong in three docs | Small docs |
| DOC5 | P2 | `saved_with_advisory` documented but unreachable | Small |
| DOC6 | P3 | Assorted current-doc contradictions (routing, export, import, patch, sessions) | Cleanup |
| SEC1 | P1 | No auth, Host validation, or WS Origin check | Medium |
| SEC2 | P1 | Windows session-ID traversal | Small |
| SEC3 | P2 | Arbitrary API path read/write and UNC egress | Medium |
| SEC4 | P2 | Live key in OneDrive; cloud egress default | Medium |
| SEC5 | P3 | Dependency/file hygiene | Medium |

---

## 1. Runtime correctness and reliability

### R1 (P1) - A failed scene crashes the run summary

`Orchestrator.run_pipeline` deliberately continues after a scene error and appends a
result with no `word_count`:

- `src/orchestrator.py:255-281` catches `Exception`, appends
  `{chapter_number, scene_number, error, status: "failed"}`, and continues.
- `src/main.py:1099` then does `sum(r["word_count"] for r in results)`.
- `src/main.py:1112` reads `r["word_count"]` again.

Any single scene failure therefore produces a `KeyError` in the post-run summary,
after all remaining scenes have already been drafted. The operator sees a traceback
rather than "4 saved, 1 failed". `pipeline_complete` is also emitted with
`chapters_generated=len(results)` (`src/orchestrator.py:302-305`), counting failed
scenes as generated.

**Fix:** use `r.get("word_count", 0)`, count `status == "failed"` separately, print a
failed-scene list, and return a non-zero exit code when any scene failed. This is a
small, high-value fix.

### R2 (P1) - Empty prose is saved as a clean scene

The drafter can return `""`; `Orchestrator._run_prose_stylist` emits a `prose_empty`
warn (`src/orchestrator.py:1227-1234`) but returns the empty string. `run_chapter`
then saves it (`src/orchestrator.py:373`; `_save_chapter` at `:1543-1547`), records
`word_count=0`, and `_run_post_save` writes `revision_status="saved_clean"`
(`src/orchestrator.py:556-559`). The test suite explicitly asserts only that the warn
fires, not that the scene is treated as degraded
(`tests/test_reliability_hardening.py:95-112`).

This is not a quality gate request; it is a failed-generation path. Saving a zero-word
file as a completed scene makes every downstream count wrong and can feed an empty
scene into the summarizer/state diff.

**Fix:** treat empty/whitespace prose as a scene failure (or at minimum
`saved_with_advisory` + a revision-debt row + `prose_empty` in the result). Do not write
the empty file over a prior good save.

### R3 (P1) - Post-save stages are not individually guarded

`run_chapter` wraps the whole `_run_post_save` call in one `try/except`
(`src/orchestrator.py:382-400`), but `_run_post_save` runs the stages sequentially
without per-stage guards (`src/orchestrator.py:482-580`):

1. Summarizer
2. `chapter_memory.add_summary`
3. `state_diff_applier.apply_diff`
4. chapter/scene log
5. contradiction scan
6. worldbuilding extraction (this one is separately guarded)

If ChromaDB raises at step 2, the state diff and scene log never run. The scene is
saved, the warn says "state may be stale", and the next scene drafts against stale
state. `CLAUDE.md` says "Summarizer / state-diff / contradiction scan / worldbuilding
extraction ... each catch Exception"; the code does not do that. The existing hardening
test only asserts the outer guard
(`tests/test_orchestrator_post_save_hardening.py:108-130`).

**Fix:** wrap each stage independently, emit `post_save_error` with a stage tag, and
continue. State-diff application should be the highest-priority stage to protect.

### R4 (P1) - Promise ledger ignores the canonical seed shape

`PromiseLedger._collect_planning_seeds` reads only
`concept_seed["story_physics"]["promise_payoff_ledger"]`
(`src/memory/promise_ledger.py:179-180`). The workflow-kit compiler writes
`seed["promise_payoff_ledger"]` at top level (`workflows/_shared/seed_transforms.py:166-170`,
called by `scripts/compile_bundle.py`), and `schemas/concept_seed.json` defines the
top-level property. `PhysicsEnforcer` also reads only `story_physics`
(`src/planning/physics_enforcer.py:52-66`).

Measured consequences (read-only, in-memory):

- Ruusan: 46 rows seeded, **0 from its 51-entry ledger**; 16 rows have no
  `due_by_scene`. The rows exist only because scene cards name promise IDs, so they
  are stubs with empty descriptions/types.
- Betrayal: 18 rows seeded, **0 from its 7-entry ledger**, all 18 are `hook_*` IDs.
- The Unfinished Shadow: 12 rows, all from `story_physics` (an ingested,
  non-compiler seed shape).

This also means the physics promise checks are vacuous for workflow-kit books, and the
migration script inherits the same bug
(`scripts/migrations/migrate_promise_ledger.py:119-127`).

**Fix:** read both shapes (`story_physics.promise_payoff_ledger` and top-level),
preferring the top-level canonical field, and add a migration/compile test that compiles
a book and seeds its ledger. Keep the ingest shape supported as a legacy fallback.

### R5 (P1/P2) - Web runs diverge from CLI safety

- **Plan approval is bypassed.** `CLI` enforces `check_plan_approval`
  (`src/main.py:686-694`). `POST /api/pipeline/start` loads the seed and starts the run
  with no approval check (`src/ui/routes/pipeline.py:50-148`). A user can draft an
  unapproved plan from the dashboard.
- **One scene failure aborts the run.** `WebOrchestrator.run_pipeline` calls
  `self.run_chapter(scene_card)` without the per-scene `try/except` the CLI orchestrator
  has (`src/ui/web_orchestrator.py:67` vs `src/orchestrator.py:255-281`). The exception
  reaches `PipelineManager._run_wrapper`, the state becomes `FAILED`, and remaining
  scenes are not attempted. Prior results are preserved in `pm.results`, but the run
  does not continue.
- **Enabled stores are not wired.** `_create_web_orchestrator` passes no
  `promise_ledger` and no `revision_debt_store`
  (`src/ui/routes/pipeline.py:372-398`). For The Unfinished Shadow, whose overrides turn
  on promise ledger, revision debt, continuity, and declared state, the web path
  silently runs with the promise/debt features off. `declared_state` still works if
  `story_state` is present.
- The web docs correctly call the dashboard a preview
  (`docs/user-guide/web-interface.md:17-19`), which mitigates but does not remove the
  plan-gate bypass.

**Fix:** apply `check_plan_approval` in the web route, share the per-scene failure guard
between CLI and web, and construct the same stores in both wiring paths (or explicitly
reject flags the web path cannot honor).

### R6 (P1 security) - Session-ID traversal and unauthenticated control surface

Detailed security findings are in section 4. The two runtime-relevant ones:

- `GET/DELETE /api/sessions/{session_id}` joins the raw path parameter into
  `Path(session_dir) / f"{session_id}.json"` and unlinks it
  (`src/ui/routes/ledger.py:73-97`; `src/pipeline_session.py:55-60`). On Windows,
  `%5C` decodes to `\`, so `..\..\...` escapes the session directory and can read or
  delete any `.json` the server user can access.
- The API has no authentication or Host/Origin validation; see section 4.

### R7 (P2) - Multi-scene chapter logs are last-scene-only

`_run_post_save` calls `add_chapter_log` on every scene
(`src/orchestrator.py:560-580`), but `chapter_log` has `chapter_number` as its primary
key and `add_chapter_log` uses `INSERT OR REPLACE`
(`src/memory/story_state.py:274-290, 1375-1403`). For a two-scene chapter, the second
scene silently overwrites the first scene's word count, structural phase, POV, summary,
scores, and status. `get_chapter_aggregate` exists (`story_state.py:1506-1513`) but is
unused.

Impact: chapter-level word count/quality shown by the API
(`src/ui/routes/chapters.py:55-56, 97-101`), story-state queries, and any future
chapter memo/telemetry read the last scene as if it were the chapter.

**Fix:** either keep `chapter_log` as a chapter-close aggregate written once per
chapter (sum `scene_log`, combine POV/phase, choose a chapter summary), or remove it
and read aggregates from `scene_log`.

### R8 (P2) - Re-seeding a paid promise erases its payoff scene

`_upsert` updates `payoff_scene` from the planning entry on conflict but deliberately
does not update `status` (`src/memory/promise_ledger.py:284-297`). Planning entries
normally have `payoff_scene=None`, so a re-seed after a runtime payoff produces:

```
after payoff: status=paid payoff_scene=ch01_sc02
after re-seed: status=paid payoff_scene=None
```

Confirmed with an in-memory reproduction. This makes the "status paid but no payoff
location" state possible, loses audit information, and can confuse memos/repatch logic.

**Fix:** on conflict, preserve `payoff_scene` when the existing status is terminal
(`paid`/`broken`/`retired`), or only update planning-owned columns while the row is
still `planted`/`progressing`.

### R9 (P2) - Preflight blind spots

`src/pipeline/run_preflight.py` checks concept-seed schema, scene-card schema, plan
approval, blueprint presence, canon guidance, and packet compilation. It does **not**
check:

- cross-surface character/promise/hook/subplot/revelation references (that lives in
  `scripts/compile_bundle.py:578-582`; `workflows/_shared/scene_card_references.py`);
- chapter-blueprint schema (Ruusan has two invalid `scene_plan[].role` values:
  `chapter_06.json` `reveal_and_aftermath`, `chapter_14.json` `processing_and_hook`);
- promise-ledger seeding or state-dir existence;
- continuity declarations (continuity is flag-gated in `compile_bundle`, not called by
  preflight);
- whether the run has prose/export artifacts.

Measured: all three books pass preflight with 0 errors, while Betrayal has 65
cross-reference warnings and Ruusan has 2 schema-invalid blueprints. The docs say
preflight checks cross-surface references (`README.md:87`, `CLAUDE.md:104`,
`docs/architecture/quality-and-revision.md:12`), which is false.

**Fix:** call `validate_all_scene_card_references` and blueprint-schema validation from
preflight, or correct the docs. Prefer the former; these are cheap deterministic checks.

### R10 (P2) - Word-count telemetry is orphaned

`src/pipeline/word_count_telemetry.py` defines the chapter-level drift emitter
(`emit_chapter_word_count_telemetry`) and `emit_wordcount_drift` exists in
`revision_debt_producers.py`. Neither is called anywhere outside tests. Consequences:

- `chapter_word_count_telemetry` events are never emitted.
- `wordcount_drift` revision-debt rows are never produced, so the chapter memo's
  word-count section is always zero (`src/pipeline/chapter_memos.py:228-231`).
- The `length_calibration` multiplier is applied to the prompt
  (`src/agents/prose_stylist.py:223-231`) but no code measures delivered length
  against the card target or the calibrated ask. `CLAUDE.md` says telemetry still
  measures against the card target; it does not.

**Fix:** at chapter close, group results by chapter, sum `word_count`, compare to the
blueprint's `scene_plan` targets, and call `emit_chapter_word_count_telemetry`. If
revision debt is on, also emit `wordcount_drift`.

### R11 (P2) - Memo metrics are misleading

- `MilestoneMemoGenerator` calls `story_state.list_open_gaps()` (open-only) and then
  counts `status in ("resolved", "overruled")` among those rows
  (`src/pipeline/chapter_memos.py:291-302`). The resolution rate is always 0 unless
  there are no gaps, and the test asserts that as documented behavior
  (`tests/test_chapter_memos.py:146-157`).
- `word_count_drift.max_abs_pct` is hardcoded to `0.0` in the milestone memo
  (`chapter_memos.py:329-331`).
- Pending promises are rendered as Python dict reprs (`chapter_memos.py:147-151`)
  rather than `promise_id: description`.
- Chapter-close counts include resolved/deferred rows in `counts_by_category` and
  `counts_by_severity`; only `open_debt_ids` is filtered
  (`chapter_memos.py:218-222`).

**Fix:** use an all-gaps query for the milestone resolution rate, derive max drift from
the rows, render promise fields explicitly, and either filter memo counts to open rows
or label them "all rows".

### R12 (P2) - Cancellation is swallowed and retried

`ModelRouter.complete` catches `asyncio.CancelledError` and retries with sleep
(`src/model_router.py:174-182`). This defeats cooperative cancellation: stopping a web
run or shutting down can wait through additional retries and re-issue paid requests.
429/502/503 retries are also non-idempotent (`model_router.py:117-123,164-172`), so an
interrupted request can be billed twice.

**Fix:** never retry `CancelledError`; re-raise immediately. Keep 429/5xx retries
bounded and consider idempotency keys where the provider supports them.

### R13 (P2) - Placeholder skeletons can compile without a guard

`IdeaSessionCapture.expand_to_surface_drafts()` deliberately writes schema-valid
`<EDIT_ME ...>` placeholders so the downstream surface sessions open to a partly-filled
draft (`workflows/idea_session_capture/api.py:863-985`; `AGENTS.md`). But no gate checks
for placeholders:

- `compile_bundle` validates JSON Schema and cross-surface references, not sentinel
  text (`scripts/compile_bundle.py:528-582`);
- `compliance_validator` has no `<EDIT_ME>`/placeholder check;
- `run_preflight` has no placeholder check;
- `approve_plan.py` only flips a boolean.

A user can therefore compile the skeletons, approve the resulting seed, and draft with
`<EDIT_ME>` missions/cast. The docs say the human fills the placeholders, but that is a
social contract, not an enforced one.

**Fix:** scan all compiled artifacts for `<EDIT_ME` (and the padded placeholder phrases
used by `scripts/init_project.py`) and fail compile/preflight, with an explicit override
for intentional scaffolding.

### R14 (P2) - Compile writes artifacts before declaring failure

`_write_scene_cards` validates each card but writes it even when the schema error was
recorded (`scripts/compile_bundle.py:266-312`). `compile_bundle` then writes
`concept_seed.json` (`:631-635`) before running compliance validation (`:638-646`).
`report_has_failures` only controls the process exit code. A failed compile can
therefore overwrite a previously-good live seed/card tree with invalid artifacts, and
the next drafting attempt reads them unless the operator notices the exit code.

**Fix:** stage the seed/cards in a temporary directory, validate the staged bundle, and
replace the live files only on success; keep a backup for `--force` runs.

---

## 2. Planning and data integrity

Read-only measurements across the three books:

| Book | Chapters | Scene cards | Blueprints (schema-valid) | Cards schema-valid | Enriched cards | POV resolves | `characters_present` resolves | Promise IDs |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| the-ruusan-atonement | 28 | 87 | 28 (26/28) | 87/87 | 87/87 | 87/87 | 86/87 cards | 46/51 used |
| legacy-of-the-force-betrayal | 34 | 60 | 34 (34/34) | 60/60 | 0/60 | 60/60 | 27/60 cards (65 refs) | 0/7; 18 hook IDs |
| the-unfinished-shadow | 38 | 44 | 38 (38/38) | 44/44 | 44/44 | 4/44 | 44/44 | 12/12 |

All three have chapters 1..`meta.target_chapters` with no gaps, no duplicate
`(chapter, scene)` pairs, no filename/content mismatches, and
`compile_metadata.plan_approved=true`. Preflight passes all three with 0 errors
(Betrayal has one warning: no `canon_contract.md`).

### D1 (P1) - The Unfinished Shadow's enabled state is missing

`data/franchises/star-wars-legends-eu/books/the-unfinished-shadow/runtime_overrides.yaml:62-68`
claims 12 promises are seeded into
`output/star-wars-legends-eu/the-unfinished-cycle/state/`. That directory does not
exist (nor does a book-scoped state directory). `promise_ledger`, `revision_debt`,
`continuity_validator`, and `declared_state` all resolve true for this book.

Measured persisted state: 0 ledger rows, no `story_state.db`, no `revision_debt.db`.
The ch1-10 run log shows the run did use series-scoped state
(`output/star-wars-legends-eu/the-unfinished-shadow/runs/ch1-10-v4pro-hardened/run.log:3`),
so this is lost state, not a run that never had it. A fresh run will recreate the
directory empty; every promise progressed/paid in those scenes becomes an "unknown
promise_id" warn until the migration is run, and the migration currently cannot seed
the canonical top-level ledger (R4).

The same override file claims "0 breaks, 29 silent pairs"; measured is 0 breaks,
33 skipped pairs of 43, with only 2 overlapping character-state comparisons (both
"same"). The declared-state contract is barely exercised.

**Fix:** run and commit the migration/state setup for the series, or make the run
initialize the ledger from planning on startup when the DB is empty. Correct the
override comment to the measured continuity numbers.

### D2 (P2) - Betrayal's planning set is internally disconnected

- **65 unresolved `characters_present` references** on 33/60 cards, against 43 seeded
  names. Examples: Kyp Durron (4), Kyle Katarn (4), Admiral Pellaeon (3),
  Saba Sebatyne (2), Tenel Ka (2), Dammant Killers security troops. Only 20 of 71
  distinct names resolve.
- **Promise ledger disconnected**: 30 promise refs / 18 distinct IDs, all hook IDs,
  0 ledger promise IDs. The 7 planning promises are never planted or paid by a card.
  They pass compile-time validation only because the validator accepts
  `promise_ids | hook_ids` (`workflows/_shared/scene_card_references.py:104`).
- **No enriched contract fields**: 0/60 cards have `turning_point_detail`,
  `emotional_arc`, `key_beats`, `opening_mode`, or `anti_patterns`. Ruusan and
  Unfinished are 100% enriched for the first four. The brief assembler explicitly
  degrades when `key_beats` is absent.

**Fix:** reconcile Betrayal's cast/reference list (or add referenced characters and
normalize shorthand), link scene-card promise fields to actual `promise_id`s, and
backfill the enriched fields before the next run.

### D3 (P2) - Unfinished Shadow's POV shorthand defeats arc lookup

40/44 cards use free-text POV values: `Ben` (21), `Ben / Talon` (6), `Talon or Ben`
(2), `Sela attack`, `Distant / image`, etc. Only 4/44 match a seed character name.
Story-state IDs are `_slugify(name)` (`ben_skywalker`), and
`ContextAssembler._assemble_arc_context` does an exact slug lookup
(`src/memory/context_assembler.py:741-744`), so `Ben` -> `ben` finds no arc. The
character-voice lookup still works by substring (`context_assembler.py:217-220`), but
the POV arc section is silently absent for most scenes.

`scene_card_references.validate_scene_card_references` never checks `pov_character`
(`workflows/_shared/scene_card_references.py:106-111`), so compile/preflight are
silent. Blueprints use the same shorthand, so they agree with the cards and disagree
with the seed.

**Fix:** normalize POV against a canonical character ID/name at compile time, accept
the shorthand as an alias map, or add a `pov_character_id` field. Add a validator check
that POV resolves.

### D4 (P2) - Unfinished blueprints lag the card set

The book has 44 cards across 38 chapters; 6 chapters have two cards. Five chapters
(1, 11, 16, 20, 32) have a blueprint with `scene_count=1` and only scene 1 in
`scene_plan`, while the cards split the word budget across two scenes. Example:
`chapter_32.json` plans `4,500` words for scene 1; the cards target `2,200 + 2,300`.
Five card scenes have no `scene_plan` entry, so they never reach the packet's pressure
ladder (`src/pipeline/chapter_packet.py:523-534`). Twelve scene-plan targets differ
from card targets; blueprint total is 112,800 vs cards 109,800 vs meta 105,000.

`ingest_report.json` is stale: it says 38 scene cards (actual 44), 99 terminology
entries (actual 107), and points to an absent `the-unfinished-shadow-v2` path under a
different `Github Repos` checkout.

**Fix:** regenerate/sync blueprints after adding cards, and make blueprint
`scene_count`/`scene_plan` consistency a preflight check.

### D5 (P2) - Ruusan blueprint and promise drift

- Two blueprints violate the closed `scene_plan[].role` enum:
  `chapter_06.json` (`reveal_and_aftermath`) and `chapter_14.json`
  (`processing_and_hook`). 26/28 validate. No pipeline/preflight/compile path validates
  this schema; only `tests/test_chapter_blueprint_schema.py` does.
- Five ledger plant-chapter drifts (PP09 5->6, PP12 5->1, PP13 9->8, PP16 8->6,
  PP17 8->7) and one payoff drift (PP44 ch25-26 -> card ch21 s3).
- Eight ledger entries have no planting card; 21 have no paying card.
- Seven entries use types outside `schemas/story_physics.json`
  (`atmospheric`, `relationship`, `ability`); `_normalize_type` maps them to `other`.

Ruusan is otherwise the cleanest artifact set: all 87 cards pass schema and required
contract fields, all 87 POVs resolve, and all cards carry the enriched fields.

### D6 (P2) - Declared-state contract is mostly unexercised

Ruusan (0/87) and Betrayal (0/60) declare no `start_state`, `end_state`,
`objects_at_*`, or `off_page_events`, so the continuity validator reports a vacuous
pass (86/86 and 59/59 skipped pairs). Unfinished has 3/44 start states, 10/44 end
states, 2/44 open objects, 5/44 close objects, 1/44 off-page event; 33/43 pairs are
skipped and only 2 overlapping character comparisons exist. No card declares Aevyn
dead, so the ch38 bridge never resolves a requires-bridge transition.

This is acceptable for legacy books, but the docs present declared state as the
trusted writer; on two of three books it is simply absent.

### D7 (P2) - Word-count targets exceed meta on all three

Card target sums: Ruusan 107,850 vs 100,000 (+7.85%); Betrayal 131,582 vs 120,000
(+9.65%); Unfinished 109,800 vs 105,000 (+4.57%). Ruusan's uniform 3-4 scenes per
chapter also runs against the "less is more" chapter/sizing guidance, though it may be
an intentional house style.

### D8 (P2) - No prose for Ruusan or Betrayal; evidence artifacts are missing

Ruusan has 87 cards but no `.md` chapter files anywhere under
`output/star-wars-legends-eu/the-ruusan-atonement`; its three run directories contain
empty `chapters/` folders. Betrayal has no `.md` files and no `runs/` directory. Both
`export/` directories are empty. The run ledger in the local ignored state records
saves that no longer have prose.

This is partly expected because `output/*/*/runs/` and `state/` are gitignored, but the
README says the Ruusan run is reproducible from inputs; the current checkout cannot
show the claimed output. Twenty concrete output paths cited in current docs are absent,
including the phase-0 prompt dumps cited by `docs/audits/phase0_2026-04-20_*.md`. Treat
those docs as evidence claims that need either committed artifacts or a clear
"regenerate with this command" note.

Unfinished has 10 chapters (29,325 words) in the `ch1-10-v4pro-hardened` run and 5
chapters (12,042 words) in `ch1-5-deepseekpro-2026-05-30`; that is 15 of 38 chapters,
not a complete manuscript.

---

## 3. Documentation and operator flow

Docs are well written and the major architectural story is accurate. The problem is
that several **operator-critical** steps and guarantees are not reflected in the code.
The docs audit found 0 dead relative Markdown links, which is a real strength.

### DOC1 (P1/P2) - Plan approval is missing from the A-to-Z path

`src/main.py:686-694` refuses to draft unless `compile_metadata.plan_approved` is
true. `scripts/compile_bundle.py` explicitly does not stamp it
(`compile_bundle.py:648-651` comments that approval is separate). The A-to-Z docs go
compile -> preflight -> production with no approval step:

- `docs/user-guide/new-manuscript-workflow.md:120-162`
- `docs/getting-started.md:200-212`

`docs/user-guide/cli-usage.md:34-40` documents the gate, but a new operator following
the main path will fail at the first production command.

**Fix:** insert `python scripts/approve_plan.py --franchise <fr> --book <bk>` before
preflight in both guides.

### DOC2 (P2) - Preflight-before-production cannot pass for a fresh book

`run_preflight.py:145-158` adds an error for every chapter lacking a blueprint.
`compile_bundle` does not generate blueprints. The documented sequence runs preflight
before production, and production is what generates blueprints at phase 5. A fresh
book therefore always fails the documented preflight.

**Fix:** either generate blueprints as part of compile (or a dedicated step before
preflight), document `--phase 5 --generate-outline` / blueprint generation first, or
downgrade missing blueprints to a warning when the packet fallback is enabled.

### DOC3 (P2) - `--book` does not do what the docs say

`docs/user-guide/cli-usage.md:62` says `--book` defaults to "auto" and is derived from
the seed title; `docs/reference/api-reference.md:15` says it sets `project_slug`.
`src/main.py:734` stores `book_id`, but the non-`--project` path constructs
`ProjectPaths.from_concept_seed` and only overrides `franchise_slug` and `series_slug`
(`main.py:748-754`). `paths.project_slug` remains the title slug.

Consequences: a `--book` that differs from the title writes blueprints to
`data/.../books/<book>/chapter_blueprints` (manual path in
`main.py:352-355`) while the packet compiler reads
`paths.chapter_blueprints_dir` at the title slug. Omitting `--book` makes `book_id`
`None` and silently skips phase-5 blueprint generation (`main.py:1076-1081`), even
though docs call it auto-derived.

**Fix:** set `paths.project_slug = book_id` when supplied, fall back to
`paths.project_slug` when not, and use `ProjectPaths` in `_ensure_chapter_blueprints`.

### DOC4 (P2) - Canon-guidance location and scope are wrong

`CLAUDE.md:103`, `docs/architecture/system-overview.md:105`, and
`docs/reference/schemas.md:17` describe a franchise-level
`data/franchises/<franchise>/canon_guidance.json`. The code uses a **book-level
directory** with per-scene sidecars
(`src/project_paths.py:290-292`, `src/pipeline/canon_guidance.py:169-174`), and the
worked example has 87 files under `<book>/canon_guidance/chNN_scMM.json`. A
franchise-level JSON is never read.

**Fix:** correct all three docs to the book-level directory/sidecar shape.

### DOC5 (P2) - `saved_with_advisory` is documented but unreachable

`CLAUDE.md:141-144`, `README.md:196`,
`docs/architecture/agent-pipeline.md:104`, and
`docs/architecture/system-overview.md:54` describe two saved statuses. The lean path
sets `saved_with_advisory` only when `polish_rejected=True`
(`src/orchestrator.py:556-559`), and `run_chapter` never passes that flag
(`orchestrator.py:384-386`). `src/main.py:1105` hard-codes `saved_clean`.

**Fix:** either make advisory signals set the status (empty prose, word-count drift,
rhythm debt) or document `saved_clean` as the only lean outcome and remove the dead
parameter.

### DOC6 (P2/P3) - Assorted current-doc contradictions

| Doc claim | Code reality |
|---|---|
| `README.md:87`, `CLAUDE.md:104`, `quality-and-revision.md:12`: preflight checks cross-surface refs | Not in `run_preflight.py`; only compile_bundle |
| `CLAUDE.md:103`: canon gaps surface as preflight warnings | `run_preflight.py:279-285` emits errors when a contract exists |
| `docs/reference/configuration.md:75-84`: prose/line-writer 8192 tokens, rhythm 2400, `plot_architect: deepseek`, `canon_scout: grok41fast/1800` | `config/settings.yaml:76-107`: 12000/12000/4096, `deepseekpro`, `deepseek/8192` |
| `docs/user-guide/cli-usage.md:196-204` + `getting-started.md:156-166`: `--export-only` exports the existing manuscript | `main.py:736` always makes a new run id; without `--run-name`/`--output-dir` it exports an empty new run |
| `docs/getting-started.md:222-229`: import with `--project` then run franchise path | `--import-summary` writes flat `data/projects/<slug>/` (`main.py:632-642`); the franchise path does not exist |
| `docs/architecture/manuscript_lifecycle_design.md:93`: accept-isolated/overrule no longer wired | `schemas/manuscript_patch.json:24` allows them and `scripts/patch_workflow.py:216-357` implements them |
| `CLAUDE.md:112`, `quality-and-revision.md:58`: manuscript reviewer writes revision-debt rows | `src/agents/manuscript_reviewer.py:145-200` returns a dict only; no debt import/CLI |
| `docs/user-guide/cli-usage.md:64`: sessions live in each run dir | `PipelineSession()` uses `output/_fallback/sessions` (`src/pipeline_session.py:24`); `ProjectPaths.sessions_dir` is unused |
| `docs/reference/api-reference.md:352`: WebSocket at `/ws/pipeline` | Actual is `/api/ws/pipeline` (`src/ui/app.py:198-204`) |
| `README.md:283`: "everything under `output/` is gitignored" | 85 tracked files under `output/`, including 15 Unfinished chapter files and prompt snapshots; `.gitignore:57-72` ignores only state/export/runs |

None of these are hard to fix; several are one-line doc edits. The plan-approval and
preflight omissions are the ones that actually break a new user's first run.

---

## 4. Security and configuration

**Threat model:** default bind is `127.0.0.1` (`src/ui/server.py:15,70-72`), which is
good. But "localhost" is not an authorization boundary: no authentication, no
`TrustedHostMiddleware`, and no WebSocket Origin check. The findings below are
high-severity if the UI is exposed (`--host 0.0.0.0`) or reached via DNS rebinding;
lower if the user never runs the server.

### SEC1 (P1) - No auth, Host validation, or WS Origin check

Every `/api` route is unauthenticated (`src/ui/app.py:154-204`); the WebSocket accepts
any origin (`src/ui/routes/websocket.py:9-27`). A malicious page can open the WS and
read ledger events; with DNS rebinding (no Host allowlist) it can also issue same-origin
HTTP requests from the attacker's hostname. `POST /api/pipeline/start` with `{}` starts
the default book run, spending the owner's API credits and overwriting chapter output
(`src/ui/routes/pipeline.py:50-148`).

**Fix:** require a per-session token (header/cookie), add a Host allowlist and WS
Origin check, and refuse a non-loopback bind without a token.

### SEC2 (P1) - Windows session-ID traversal

`GET/DELETE /api/sessions/{session_id}` does
`Path(session_dir) / f"{session_id}.json"` then `unlink()` without validating the ID
(`src/ui/routes/ledger.py:73-97`; `src/pipeline_session.py:55-60`). On Windows, an
encoded backslash (`%5C`) is a path separator, so `..\..\...` reads/deletes arbitrary
`.json` files, including `concept_seed.json` or scene cards.

**Fix:** reject any `session_id` that is not `Path(session_id).name == session_id` and
match `^[0-9]{8}_[0-9]{6}_[0-9a-f]{4}$`; resolve the path and assert it stays under
`session_dir`.

### SEC3 (P2) - Arbitrary path read/write and UNC egress

`POST /api/pipeline/start` accepts arbitrary `concept_seed_path` and `scene_cards_dir`
(`src/ui/routes/pipeline.py:60-70`), and `POST /api/export` accepts an arbitrary
`output_dir` (`src/ui/routes/chapters.py:16-19, 166-169`), which
`ExportManager` creates and writes into (`src/export/export_manager.py:89-110`). On
Windows a UNC path (`\\attacker\share`) can make the server authenticate outbound and
copy the manuscript to an attacker share.

**Fix:** confine API-supplied paths to the project root and reject UNC/device paths.

### SEC4 (P2) - Live key in OneDrive; cloud egress by default

The repo-root `.env` contains a populated `OPENROUTER_API_KEY` (not printed here). It
is not tracked and never appears in git history, logs, config snapshots, or prompt
snapshots. It does live under OneDrive, so it syncs to Microsoft's cloud, and `.env.*`
variants are not gitignored (`.gitignore:108` covers only `.env`/`.env.local`).

`config/settings.yaml:1` defaults to `deployment_mode: cloud`; normal runs send the
concept seed, scene cards, canon, prior prose, and character state to OpenRouter. The
local mode exists but requires a manually populated `models.local.models` and a running
llama-server, and the real embedding path uses
`SentenceTransformer(..., trust_remote_code=True)` (`src/rag/embedding.py:26`), which
downloads and executes hub code on first use.

**Fix:** rotate the key out of the OneDrive folder into an OS credential store; add
`.env.*` to `.gitignore`; add a short privacy/egress note to the README and web guide;
consider defaulting to mock embeddings and documenting local mode's limitations.

### SEC5 (P3) - Dependency and file hygiene

- `requirements.txt` is all `>=` with no lockfile/hashes; `sentence-transformers` is
  bounded but `chromadb`, `fastapi`, `uvicorn` are not. CI actions are pinned by tag,
  and `.github/workflows/ci.yml` has no `permissions:` block.
- SQLite DB/WAL files use default permissions (no `chmod`).
- `.gitignore` does not cover `output/*/*/chapters/`; a web run without `--run-name`
  writes prose there (`src/project_paths.py:351-359`), one `git add -A` from being
  committed.

These are hardening items, not active exploits.

---

## 5. Tests and maintainability

**Strengths**

- 1,685 tests pass in ~105 s; `ruff check .` is clean.
- The suite covers schemas, packet parity, runtime flags, promise ledger, revision
  debt, rhythm validator/editor, patch workflow, web API, migrations, and the three
  book fixtures.
- Shipping-book guard tests block accidental flag flips on Ruusan/Betrayal.
- `tests/test_runtime_flags.py` correctly checks the safe defaults.
- CLI/API validation tests exist for many edge cases.

**Gaps**

- No test for the failed-scene summary path (R1).
- No test for web per-scene failure or web plan approval (R5).
- `test_reliability_hardening.py` asserts empty prose only warns (R2).
- No test for top-level promise-ledger seeding (R4) or re-seed payoff preservation
  (R8).
- No test for multi-scene chapter-log aggregation (R7).
- `test_chapter_memos.py` asserts the broken zero resolution rate (R11).
- The two live prose-parity tests skip unless `PARITY_RUN_PATH` is set; CI never sets
  it, so the shipping-book parity claim is not automatically verified
  (`tests/test_pipeline_regression_ruusan.py:43`,
  `tests/test_pipeline_regression_betrayal.py:33`).
- No coverage measurement; no test for preflight cross-surface/blueprint schema checks
  (R9).

**Dead or stale surfaces**

- `src/quality/milestone_gates.py` is unused; `MetricsDashboard` and `LLMJudge` are
  referenced only by tests.
- `word_count_telemetry` is orphaned (R10).
- `saved_with_advisory` is unreachable (DOC5).
- `runtime.lean_prose_only.enabled` is read into `_lean_prose_only` and never used
  (`src/orchestrator.py:94`); the pipeline is lean-only.
- `config/failure_codes.yaml` is unreferenced and still discusses GateCritic,
  FinalGate, and PresenceChecker.
- Frontend `EventLog.tsx` and `api/types.ts` still model gate/quarantine events that
  the lean pipeline never emits. The web docs already call the dashboard a preview,
  so this is cleanup rather than a runtime bug.
- `src/run_ledger.py` `EVENT_TYPES` omits emitted types such as
  `chapter_blueprints_generated` and `lean_line_edit_unavailable`; it is advisory, but
  it should stay in sync with the real event surface.
- `main._ensure_chapter_blueprints` and `ui/routes/pipeline._ensure_chapter_blueprints`
  hand-construct paths under `data/` instead of using `ProjectPaths`, contrary to the
  repo convention.
- `BaseAgent._load_system_prompt` resolves `prompts/...` relative to the current
  working directory and silently falls back to "You are the X agent" if missing
  (`src/agents/base_agent.py:21-25`). Running from outside the repo root degrades every
  agent prompt without an error.

---

## 6. Manuscript spot-check

This is a light read, not a literary edit.

- **The Unfinished Shadow** has 15 drafted chapters across two runs (10 chapters /
  29,325 words in `ch1-10-v4pro-hardened`, 5 chapters / 12,042 words in
  `ch1-5-deepseekpro-2026-05-30`). Chapter 1 is competent commercial-style close
  third: concrete, procedurally grounded, with a clear hook. It also contains a
  duplicated clause:

  > "...and fourteen was the same age her son would have been, if the orbital
  > bombardment had come three days later. The same age her son would have been, if
  > the orbital bombardment had come three days later."

  The "Do not think about..." construction recurs several times in the same chapter;
  it reads as a deliberate motif but is close to overuse. This is exactly the class of
  issue the LineWriter / RhythmEditor pipeline is meant to catch, and it survived a
  `--line-edit` run.

- **The Ruusan Atonement** and **Legacy of the Force: Betrayal** have no chapter prose
  in this checkout, only planning artifacts. The review of those books is therefore a
  planning/data review, not a prose review.

- The saved `ch1-10-v4pro-hardened` run predates the current runtime overrides: its
  config snapshot has `promise_ledger`, `revision_debt`, `rhythm_validator`, and
  `rhythm_editor` all false. The current overrides turn them on, but the series state
  directory they depend on is absent (D1). Treat the checked-in prose as an earlier
  configuration's output, not evidence that the current flags work.

---

## 7. What is working

- The **lean forward-pass design** is coherent and well matched to the code: one
  drafting pass, one optional line edit, advisory rhythm stages, no gate loop.
- The **chapter packet** is a real architectural improvement and has parity tests.
- **Runtime flags** have a clear precedence and shipping-book guard tests.
- The **revision-debt / promise-ledger / memo** slices are thoughtfully structured even
  where wiring is incomplete.
- **Schema validation and cross-surface reference checks** exist and are useful; the
  problem is that preflight does not call all of them.
- **Docs** are unusually thorough for a research repo, with no dead relative links and
  a clear separation of archive/editorial/audit material.
- **No secrets are committed**: the `.env` key is untracked and does not appear in git
  history, logs, or snapshots.
- **SQL is parameterized** and dynamic column updates are guarded by whitelists.
- **No `eval`/`exec`/`pickle`/unsafe YAML** was found; subprocess calls use list args.
- **Tests are fast and broad**, which makes the recommended fixes low-risk to land.

---

## 8. Recommended sequence

**First (correctness, small diffs):**

1. R1 failed-result summary.
2. R2 empty-prose handling.
3. R3 per-stage post-save guards.
4. R8 promise re-seed preservation.
5. R5 web plan-approval + per-scene guard.
6. SEC2 session-ID validation.

**Second (integration/data):**

7. R4 dual-shape promise seeding + startup/migration initialization.
8. R7 chapter-log aggregation.
9. R9/R10 preflight reference/blueprint checks + word-count telemetry wiring.
10. R11 memo metrics.
11. D3 POV normalization; D4 blueprint/card sync; D2 Betrayal references.

**Third (docs/UX):**

12. DOC1/DOC2 plan approval and blueprint step in the A-to-Z guide.
13. DOC3 `--book` fix.
14. DOC4/DOC5/DOC6 doc corrections.
15. SEC1/SEC3 auth/path confinement if the web UI will ever be exposed.

**Cleanup:**

16. Remove or wire dead surfaces (`milestone_gates`, `word_count_telemetry`,
    `saved_with_advisory`, `lean_prose_only.enabled`), update the frontend event
    types, and add the missing tests above.

---

## Appendix: verification commands

```powershell
python -m pytest -q
ruff check .
python scripts/preflight_run.py --franchise star-wars-legends-eu --book the-ruusan-atonement
python scripts/preflight_run.py --franchise star-wars-legends-eu --book legacy-of-the-force-betrayal
python scripts/preflight_run.py --franchise star-wars-legends-eu --book the-unfinished-shadow
python -m pytest tests/test_pipeline_regression_ruusan.py tests/test_pipeline_regression_betrayal.py -q -rs
```

Read-only data probes used for the numbers in this report:

```python
from src.memory.promise_ledger import PromiseLedger
# top-level canonical ledger -> 0 rows; story_physics shape -> rows
# re-seed after record_payoff -> status=paid, payoff_scene=None
```

```python
from workflows._shared.scene_card_references import validate_all_scene_card_references
# Ruusan: 1 warning; Betrayal: 65 warnings; Unfinished: 0
```
