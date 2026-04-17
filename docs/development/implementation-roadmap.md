# Implementation Roadmap

Durable reference for the multi-phase rebuild that takes the system from
"Ruusan-specific reference implementation" to a general-purpose, franchise-agnostic
novel writing platform with a clean workflow kit / pipeline separation.

Supersedes and complements
[`pipeline-redesign.md`](../architecture/pipeline-redesign.md), which describes
the execution-pipeline redesign that is already implemented in code. This
document covers everything that comes before the pipeline (the workflow kit)
and everything that has to change around it (schemas, bootstrap, series
mechanics, lore loop).

---

## 1. Context and problem statement

The pipeline redesign (Phases 1-4 of that doc) is implemented. The engine is
franchise-agnostic at the code level. But the only end-to-end validated project
is the Ruusan Atonement, and the scaffolding that produced it lives in a
single 767-line script (`scripts/install_ruusan_seed.py`) that hardcodes
Star Wars content.

Three consequences:

1. A new project cannot be started from an empty `data/` directory without
   either hand-authoring a concept seed that conforms to a non-trivial JSON
   schema, or forking the Ruusan installer and rewriting content line by line.
2. Several execution-time bugs only surface in the Ruusan reference path and
   would silently corrupt any second project (see Phase 0).
3. Architecturally valid but partially-wired work (chapter blueprints, series
   transitions, closed-loop lore, multi-universe cosmology) blocks genuine
   multi-book and multi-universe use.

This roadmap addresses all three in sequence.

---

## 2. Architectural decisions (locked)

### 2.1 Workflow kit vs pipeline

The system has two layers with a hard interface between them:

```
Workflow Kit                     Pipeline
(concept development)      =>    (prose execution)
flexible front-ends              single canonical flow
```

The workflow kit is **front-end diverse** — multiple ingress modes per surface,
multiple authoring tools, flexible depth. The pipeline is **back-end disciplined**
— one redesigned sequence (PlotArchitect -> ProseStylist -> GateCritic -> Polish
-> FinalGate), plus optional chapter-level and worldbuilding extensions.

The handoff is a validated bundle of JSON artifacts. Nothing in the pipeline
cares how the bundle was authored.

### 2.2 Three ingress modes per surface

Every workflow kit surface supports three orthogonal ways to produce its
canonical artifact:

1. **Interactive chat session** (SKILL.md, Claude Code today, frontend-agnostic
   prompt template tomorrow).
2. **Programmatic API** (headless, scriptable, callable from any frontend).
3. **Importers** (normalize external formats: plain markdown, Notion export,
   World Anvil JSON, legacy concept_seed, etc.).

All three converge on one schema per surface. This guarantees frontend
decoupling by construction: if Claude Code is replaced, the API and importers
still work; the chat-session frontend becomes one of three entry points.

### 2.3 Meta-universe (cosmology) layering

The current hierarchy is `franchise -> book`. Adding an optional `cosmology`
layer above franchise enables Sanderson-style shared-cosmology projects
(multiple universes sharing an underlying creation myth / physics) without
disturbing existing single-franchise projects.

Lore resolution walks: `project -> book -> universe -> cosmology -> global`.
Projects without `meta.cosmology_id` behave identically to today.

### 2.4 AU framing: Elseworlds / What-If

Workflow 4 (canon-divergent fanfic) is the target AU model. Franchise
terminology is preserved. `canon_expert` enforces internal consistency of the
AU's own canon; drift from the source franchise is permitted and declarative
via `universe_meta.branch_point`.

Workflow 6 (serial-numbers-off / terminology remap to commercially original
work) is explicitly out of scope.

### 2.5 Out of scope

- **Workflow 6** (serial-numbers-off). No entity-remap validator, no
  terminology map.
- **Non-English**. All voice, anti-slop, show-don't-tell heuristics remain
  English-only.
- **Multi-POV voice variance**. Single voice per book.
- **Run branching / what-if drafts**. Run ledger remains linear.
- **Canon reference corpus ingestion** (workflow 3 — Wookieepedia-style strict
  canon). Schema hooks exist; engine integration waits until a
  canon-compliant project requires it.
- **Cosmology-wide canon enforcement at engine level**. Schema supports it
  (Phase 2); engine integration waits until a cosmology project actually
  exists to use it.

---

## 3. Decision log

| Decision | Value | Rationale |
|---|---|---|
| AU framing | Elseworlds / What-If | Matches Ruusan's actual shape; keeps fanfic terminology |
| Meta-universe layer | Include in schema, engine uses lazily | Low cost to add now, expensive to retrofit |
| Workflow kit model | Three ingress modes per surface | Guarantees frontend decoupling by construction |
| Phase 4 chat-session frontend | Claude Code SKILL.md initially | Lowest infrastructure cost to validate the model |
| Frontend decoupling | Promoted to Phase 8 | Explicit phase rather than a note |
| Web UI run isolation | Deferred; CLI-only this iteration | Faster to reach first real run |
| ChapterGateCritic for first run | Off | Clean comparison against run19 baseline |
| Language support | English only | Heuristics are English-centric; i18n is a large separate project |

---

## 4. Phase plan

### Phase 0 — Preflight

Four code fixes and one doc update. Blocks Phase 1.

| # | Fix | Target | Est. LOC |
|---|---|---|---|
| 0.1 | Inject `concept_seed` on Orchestrator so CanonExpert receives non-empty dict | `src/orchestrator.py`, `src/main.py` constructor call, `src/ui/routes/pipeline.py` constructor call | ~15 |
| 0.2 | Pass franchise/book context to `--validate-seed` so extracted scene cards are recognized | `src/main.py:583-587` | ~10 |
| 0.3 | Add preview-mode banner to web UI documenting lack of run isolation | `src/ui/` templates | ~5 |
| 0.4 | Update stale pipeline references (CraftEditor, 3-band / 5-band revision) | `docs/user-guide/cli-usage.md:52-55` | ~5 |

**Deferred within Phase 0 per decision:**
- Web UI `ProjectPaths.from_concept_seed` run_id threading (banner substitutes).
- ChapterGateCritic instantiation (off until Phase 5).

**Acceptance:**
- `pytest` green.
- Ruusan `--validate-seed` reports "using N extracted canonical scene card(s)"
  rather than "no extracted scene cards".
- Orchestrator's CanonExpert receives non-empty concept_seed at runtime (verify
  via a one-line log or assertion during test run).
- `docs/user-guide/cli-usage.md` describes the redesigned pipeline.

---

### Phase 1 — Ruusan chapter 1 baseline run

No code changes. Execute the redesigned pipeline end-to-end on Ruusan
chapter 1 in two modes:

1. `--raw-draft` (PlotArchitect -> ProseStylist -> GateCritic -> save).
2. Full polish (adds QualityMetrics -> QualityPolish -> FinalGate).

Compare both against the run19 baseline recorded in `pipeline-redesign.md`:
total 3,515 words, scene 2 quality 0.80, show-don't-tell violations = 1.

**Acceptance:**
- Raw-draft run within +/-10% of run19 word count; no quality regression.
- Polish run FinalGate pass rate >= 90%.
- Compression guard does not fire on any scene (if it does, polish is too
  aggressive and Phase 1 fails until the polish prompt is tuned).
- All ledger artifacts (invocation.json, config_snapshot.yaml,
  prompts_snapshot/) present and well-formed.

**This is the gate for all subsequent phases.** A failure here means upstream
pipeline work before any new architectural rebuild.

---

### Phase 1.5 — Diagnostic cleanup

Surfaced by the Phase 1 polish run. None blocked Phase 1 acceptance but all muddy
Phase 2+ diagnostic visibility. Three targeted fixes:

| # | Fix | Target | Evidence |
|---|---|---|---|
| 1.5.1 | Drop spurious LLM-emitted `WORD_COUNT_VIOLATION` when programmatic tolerance check passes | `src/agents/gate_critic.py:198-223` | Phase 1 polish run: scenes 2 and 3 at 92% of target (within +/-20% tolerance) fired the code; no `Gate: injecting WORD_COUNT_VIOLATION` line in console confirms it came from the LLM, not the programmatic check. |
| 1.5.2 | Show both Scene Gate and Final Gate verdicts in run summary | `src/main.py:965-968` | Pipeline summary prints `gate=fail_polish` for scenes that saved cleanly after Final Gate pass — misleads the operator. |
| 1.5.3 | Print `Final Gate: pass` line on success (mirror existing rejection print) | `src/orchestrator.py:479-485` | Current code only emits a ledger event on Final Gate pass; console shows `[5/5] Final Gate evaluating polish output...` then jumps to `Saved:` with no verdict line. |

**Acceptance:**
- Scene Gate no longer reports `WORD_COUNT_VIOLATION` when actual word count is within 80-120% of target.
- Pipeline summary shows `gate=<scene>, final=<final>` when both ran, and includes `polish rejected: <reason>` when applicable.
- Every scene with polish enabled prints an explicit `Final Gate: pass` or `Final Gate: polish rejected ...` line.
- Rerun of Phase 1 polish produces a summary where scenes that saved cleanly no longer read as `fail_polish`.

### Phase 2 — Schema foundation for multi-universe

All additive; existing Ruusan seed remains valid.

| Target | Change |
|---|---|
| `schemas/cosmology_meta.json` | New. Fields: `cosmology_id`, `cosmology_name`, `shared_lore`, `shared_rules`, `member_universes[]`. |
| `schemas/universe_meta.json` | Extend. Add optional `cosmology_id`, optional `branch_point` (`{source_canon, divergence_point, divergence_description}`), `commercial_intent` enum (default `fanfiction_noncommercial`). |
| `schemas/concept_seed.json` | Extend. `meta` gains optional `cosmology_id`. Mark embedded `scene_cards` as workshop-only per pipeline-redesign.md. |
| `src/project_paths.py` | Extend. Optional `cosmology_slug`. Resolution order: project -> book -> universe -> cosmology -> global. |
| `src/worldbuilding/lore_service.py` | Extend. Lore lookup walks cosmology ancestor chain if present. |

**Acceptance:**
- Ruusan seed loads unchanged (schema back-compat test).
- Cosmology-scoped test project validates with and without `cosmology_id`.
- Path resolution tests cover flat, franchise, franchise+series, and
  franchise+cosmology layouts.

---

### Phase 3 — Generic bootstrap

Replaces `scripts/install_ruusan_seed.py` with reusable template-driven
scaffolding.

| Artifact | Purpose |
|---|---|
| `templates/canon_profile/fanfic_elseworlds.json` | Default for AU fanfic (primary use case) |
| `templates/canon_profile/fanfic_compliant.json` | Strict-canon fanfic (future use) |
| `templates/canon_profile/original_deep.json` | Sanderson/Tolkien-style |
| `templates/canon_profile/original_light.json` | Genre fiction with light worldbuilding |
| `templates/canon_profile/realistic.json` | Literary / contemporary, near-empty canon |
| `templates/voice_definition/default.json` | Voice scaffold |
| `scripts/init_project.py` | Scaffolds `data/franchises/<slug>/[cosmology/]books/<slug>/`. Writes universe_meta, canon_profile from template, empty voice_definition stub. |
| `scripts/install_seed.py` | Generic replacement for Ruusan installer: validate, enrich, extract scene cards, install. No franchise hardcodes. |
| `scripts/install_ruusan_seed.py` | Deprecate to thin wrapper calling `install_seed.py` with Ruusan template inputs. |

**Acceptance:**
- Fresh project (`--title ... --franchise ... --depth light`) produces a valid
  scaffolded tree that passes `validate_concept_seed`.
- Ruusan reinstall through the new generic path produces byte-identical (or
  semantically identical) artifacts to the current installer output.

---

### Phase 4 — Workflow kit (three ingress modes) — COMPLETE

The centerpiece of the rebuild. Each surface is a self-contained module:

```
workflows/<surface>/
  schema.json         - canonical output contract
  SKILL.md            - ingress 1: interactive chat session
  api.py              - ingress 2: programmatic / headless
  importers/          - ingress 3: external format normalizers
    plain_markdown.py
    notion_export.py
    world_anvil.py
    legacy_seed.py
  validate.py
  compile.py
```

**Surfaces and priority:**

| Surface | SKILL | API | Importers | Priority |
|---|---|---|---|---|
| universe-builder | P1 | P1 | legacy_seed, plain_markdown | Entry for every project |
| canon-drafter | P1 | P2 | legacy_seed, plain_markdown | Chat-guided authoring fit |
| voice-discovery | P1 | P2 | plain_markdown (samples), author_corpus | Voice elicitation best in chat |
| character-forge | P1 | P1 | legacy_seed, notion_export, world_anvil | Many writers use external tools |
| outline-planner | P1 | P1 | legacy_seed, plain_markdown | API critical for programmatic outlining |
| scene-card-authoring | P2 | P1 | legacy_seed, plain_markdown | Existing SceneCardGenerator covers API today |

P1 ships in Phase 4. P2 ships as follow-up.

**First importers to build:**
- `legacy_seed.py` — extract all six surface artifacts from an existing
  `concept_seed.json`. Critical for bringing Ruusan itself into the
  workflow-kit model without rewriting content.
- `plain_markdown.py` — lowest common denominator; unblocks ad-hoc use.

**Bundle compiler** (`scripts/compile_bundle.py`): reads all surface outputs
from a project, merges into canonical `concept_seed.json` + `scene_cards/` +
`chapter_blueprints/`, validates against `compliance_validator`, reports gaps.
This is the single entry point the pipeline consumes.

**Acceptance:**
- A fresh project goes from empty directory to compiled bundle entirely through
  workflow kit sessions.
- Pipeline runs clean on the compiled bundle with no manual artifact editing.
- Ruusan project, re-extracted via `legacy_seed.py` importers, produces a
  bundle equivalent to the current installer output.

**Status (delivered):**
- `workflows/<surface>/` tree with all six surfaces: `universe_builder`,
  `canon_drafter`, `voice_discovery`, `character_forge`, `outline_planner`,
  `scene_card_authoring`. Each ships `schema.json`, `SKILL.md`, `api.py`,
  `validate.py`, `importers/{legacy_seed,plain_markdown}.py` plus a
  per-importer `README.md`.
- Shared helpers at `workflows/_shared/`: `seed_transforms.py` and
  `scene_card_translator.py` moved here from `src/concept_workshop/` (with
  back-compat re-export shims at the original paths), plus new
  `markdown_parser.py`, `legacy_seed_loader.py`, `schema_loader.py`,
  `io.py`, and `SKILL_preamble.md`.
- `scripts/compile_bundle.py` — bundle compiler mirroring
  `scripts/install_seed.py::_apply_workshop_patch` ordering; idempotent;
  emits `compile_report.json`.
- `scripts/migrate_workshop.py` — forward migration helper that splits an
  existing `concept_seed.json` into the six surface artifacts.
- `.claude/skills/<surface>/SKILL.md` × 6 — Claude Code wrappers that
  reference `workflows/<surface>/SKILL.md` for auto-discovery.
- `workshop_runner.py` prints a deprecation banner pointing to the
  workflow kit; the existing 11-step CLI keeps working for in-flight
  workshops.
- Acceptance gates green:
  `tests/test_compile_bundle_ruusan_equivalence.py` (5 tests) +
  `tests/test_workflow_kit_empty_to_bundle.py` (3 tests) +
  `tests/test_compile_bundle_pipeline_clean.py` (1 test).
- See `docs/user-guide/workflow-kit.md` for end-to-end usage.

---

### Phase 5 — Planning completion

Fills the chapter-level planning gap that `pipeline-redesign.md` Phase 2
specified but did not fully implement.

| # | Work | Target |
|---|---|---|
| 5.1 | Chapter blueprint generator | New: `src/planning/chapter_blueprint_generator.py`. Derives blueprints from concept_seed + scene_cards. |
| 5.2 | Wire blueprint generation into pipeline | `src/main.py` — between seed load and scene execution, generate missing blueprints. |
| 5.3 | Instantiate ChapterGateCritic | `src/main.py`, `src/ui/routes/pipeline.py` — pass to Orchestrator when blueprints present. |
| 5.4 | OutlinePlanner emits blueprint draft alongside scene cards | `src/planning/scene_card_generator.py` |

**Acceptance:**
- Ruusan chapter 1 run produces and validates against an auto-generated
  blueprint equivalent in content to the hand-authored one at
  `data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/chapter_blueprints/chapter_01.json`.
- Hand-authored blueprint takes precedence if present.
- Full 28-chapter Ruusan run produces blueprints for all chapters;
  ChapterGateCritic enforces against them.

---

### Phase 6 — Series continuation

Enables book 2, book 3 in the same universe. Does not include universe fork
or terminology remap (workflow 6 is out of scope).

| # | Work | Target |
|---|---|---|
| 6.1 | Verify `SeriesManager.generate_transition_snapshot` end-to-end | `src/concept_workshop/series_manager.py` |
| 6.2 | CLI: `scripts/spawn_next_book.py` | New |
| 6.3 | Wire `universe_meta.branch_point` into canon_expert | `src/agents/canon_expert.py` |

**Acceptance:**
- `spawn_next_book.py --from-book <slug>` produces a new book directory with
  carried-over state (character positions, open hooks, resolved revelations
  removed from the schedule).
- Pipeline executes book 2 immediately without manual seed editing.
- canon_expert receives branch_point context and applies relaxed source-canon
  constraints past the divergence point.

---

### Phase 7 — Closed-loop lore

Makes the system compound: each scene teaches the universe about itself.

| # | Work | Target |
|---|---|---|
| 7.1 | Invoke `lore_extractor` after scene save | `src/orchestrator.py` — extract to `provisional` bucket |
| 7.2 | Lore conflict detector | New: `src/worldbuilding/lore_conflict_detector.py`. Compare provisional lore to canon_profile + established canonical lore. |
| 7.3 | Promotion workflow | CLI: `scripts/promote_lore.py` — human review `provisional` -> `canonical`. |
| 7.4 | ChapterGateCritic reads promoted lore | `src/agents/chapter_gate_critic.py` |

**Conflict detector stance:** advisory on first implementation (warn and
continue). Upgrade to blocking once confidence is established.

**Acceptance:**
- Writing chapter 2 references lore introduced in chapter 1 without manual
  canon_profile updates.
- Conflict detector flags at least one seeded contradiction in a test run.
- Promoted lore appears in chapter 3 generation context.

---

### Phase 8 — Frontend decoupling

Validates that the three-ingress model actually delivers frontend
independence. Deferred until after Phase 4 ships.

| # | Work | Target |
|---|---|---|
| 8.1 | Extract SKILL.md workshop logic into shared prompt templates | `prompts/workflow_kit/<surface>.md` referenced by Claude Code skill wrapper and any future frontend. |
| 8.2 | Reference frontend: minimal web UI per surface using `api.py` | New, small, proof-of-concept. |
| 8.3 | Deprecate SKILL.md wrappers in favor of prompts + frontend | Only after reference frontend is solid. |

**Acceptance:**
- A non-Claude-Code frontend can drive any surface to a valid artifact.
- SKILL.md files contain only the Claude-Code-specific wrapper; all authoring
  logic lives in the shared prompt templates.

---

## 5. Sequencing and parallelism

```
Phase 0 --> Phase 1 --> Phase 1.5 --+--> Phase 2 --+--> Phase 3 ---> Phase 4 (3-ingress kit) --+
                                    |              |                                           |
                                    +--> Phase 5 --+                                           +--> Phase 8
                                    |                                                          |     (decouple)
                                    +--> Phase 6 (series) ------------------------------------+
                                    |                                                          |
                                    +--> Phase 7 (lore loop) ---------------------------------+
```

- Phase 0 blocks Phase 1.
- Phase 1 is the gate for all architectural rebuild work.
- Phases 2, 5, 6, 7 can parallelize once Phase 1 is green.
- Phase 3 depends on Phase 2 (needs schema).
- Phase 4 depends on Phase 2 and Phase 3.
- Phase 8 depends on Phase 4.

## 6. Rough effort estimate

| Phase | Effort | Confidence |
|---|---|---|
| 0 | Half day | High |
| 1 | Half day (run + analysis) | High |
| 1.5 | 1-2 hours | High |
| 2 | 1-2 days | High |
| 3 | 3-4 days | Medium |
| 4 | 1-2 weeks | Low (depends on surface depth) |
| 5 | 3-4 days | Medium |
| 6 | 2-3 days | Medium |
| 7 | 1 week | Low (conflict detection is subtle) |
| 8 | 1 week | Medium |

## 7. Related documents

- [`docs/architecture/pipeline-redesign.md`](../architecture/pipeline-redesign.md)
  — execution pipeline redesign (already implemented).
- [`docs/architecture/system-overview.md`](../architecture/system-overview.md)
  — high-level architecture.
- [`docs/architecture/agent-pipeline.md`](../architecture/agent-pipeline.md)
  — agent responsibilities and contracts.
- [`docs/architecture/memory-and-state.md`](../architecture/memory-and-state.md)
  — memory/state layer.
- [`docs/architecture/quality-and-revision.md`](../architecture/quality-and-revision.md)
  — quality metrics and (legacy) revision bands.
- [`docs/architecture/deferred-work.md`](../architecture/deferred-work.md)
  — existing deferred-work log.
- [`schemas/`](../../schemas/) — all JSON schemas.

## 8. Open questions deferred to their phases

| Question | Resolves in |
|---|---|
| Exact form of `branch_point` schema fields | Phase 2 |
| Which external formats warrant first-class importers beyond `legacy_seed` and `plain_markdown` | Phase 4 |
| Whether ChapterGateCritic should be blocking or advisory by default | Phase 5 |
| Book-to-book state carryover: full StoryState serialization vs. minimal snapshot | Phase 6 |
| Conflict detector strictness (advisory vs. blocking) | Phase 7 |
| Whether to keep SKILL.md as a thin wrapper or delete it entirely post-Phase-8 | Phase 8 |
