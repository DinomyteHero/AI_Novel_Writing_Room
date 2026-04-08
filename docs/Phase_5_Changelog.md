# Phase 5 Changelog & Migration Guide

Phase 5 adds series planning, subplot/hook governance, character arc tracking (K.M. Weiland model), voice definition, terminology consistency, adversarial stress testing, and manuscript-level review to the AI Writers' Room pipeline.

---

## What Changed

### Concept Workshop (6 to 10 Steps)

| Step | Name | Details |
|------|------|---------|
| 0 | Project Scope | Branching logic: `standalone` / `planned_series` / `continuation` |
| 0a | Series Seed Workshop | Conditional -- builds `series_seed.json` with cross-book arcs, promises, shared characters |
| 0b | Retroactive Series Promotion | Conditional -- promotes a completed standalone concept to a series after the fact |
| 4 | Character Arcs (enhanced) | Now includes K.M. Weiland beats: `lie_believed`, `ghost`, `want`, `need`, `arc_type` (`positive_change`/`flat`/`negative`/`disillusionment`), `arc_phase_targets` |
| 5 | Narrative Voice Discovery | POV approach, prose register, reference authors, anti-slop (banned words/phrases), anti-patterns |
| 7 | Subplot Architecture | `subplot_board` (A/B/C/D lines with interweave points), `hook_map` (chekhov/foreshadow/setup_callback/thematic_echo/mystery_question), `revelation_schedule` |
| 8 | Enhanced Scene Cards | Reference `active_subplots`, `hook_actions` (plant/advance/resolve/subvert), `revelations`, `pov_arc_phase`, `arc_phase_transition` |
| 9 | Terminology Registry | Canonical spelling, aliases, categories, first-appearance tracking |
| 10 | Adversarial Stress Test | 5-dimension scoring (0-10): `premise_strength`, `character_depth`, `structural_integrity`, `hook_coherence`, `series_viability` |

### New CLI Flags

Added to `workshop_runner.py`:

| Flag | Effect |
|------|--------|
| `--series` | Activates planned-series mode (triggers Step 0a) |
| `--continue-from <snapshot_path>` | Continue from a previous book's transition snapshot |
| `--promote-to-series` | Retroactively promote a standalone concept to series (triggers Step 0b) |

### New SQLite Tables (Schema v2)

Migration `_migrate_v1_to_v2` creates 6 tables. Applied automatically by `StoryState.__init__()`.

| Table | Key Columns | Purpose |
|-------|-------------|---------|
| `character_arcs` | `character_id`, `book_number`, `lie_believed`, `ghost`, `want`, `need`, `arc_type`, `current_phase`, `arc_phase_targets` | Weiland arc tracking per character per book |
| `subplot_board` | `subplot_id`, `line_type` (A/B/C/D), `current_status`, `interweave_points`, `book_number` | Subplot lifecycle and interweaving |
| `hook_ledger` | `hook_id`, `hook_type`, `priority` (hard/soft/series), `current_status`, `planted_chapter`, `payoff_chapter` | Promise/foreshadow governance |
| `terminology_registry` | `term`, `aliases`, `definition`, `category`, `first_appearance_chapter` | Canonical term spelling and usage |
| `propagation_debts` | `source_layer`, `change_description`, `affected_chapters`, `resolved_at` | Track downstream changes needed when upstream state changes |
| `style_fingerprint` | `source`, `metric_name`, `metric_value` | Store prose style metrics for drift detection |

### New Failure Codes

5 new codes added to `failure_code.json` and `config/failure_codes.yaml`:

| Code | Category | Route |
|------|----------|-------|
| `CHARACTER_ARC_STALL` | structural | `full_rewrite` |
| `HOOK_VIOLATION` | structural | `full_rewrite` |
| `SUBPLOT_DRIFT` | structural | `full_rewrite` |
| `TERMINOLOGY_DRIFT` | voice | `targeted_revision` |
| `VOICE_DEFINITION_VIOLATION` | voice | `targeted_revision` |

### New Modules

| File | Description |
|------|-------------|
| `src/concept_workshop/series_manager.py` | Series seed creation, transition snapshots, retroactive promotion |
| `src/concept_workshop/voice_discovery.py` | Voice definition builder with anti-slop merge |
| `src/concept_workshop/stress_test.py` | 5-dimension adversarial stress test runner |
| `src/concept_workshop/decision_detector.py` | LLM-based classification of confirmed workshop decisions |
| `src/concept_workshop/state_writer.py` | Incremental state persistence from workshop turns |
| `src/concept_workshop/workshop_state.py` | ConceptWorkshopState dataclass mirroring concept seed schema |
| `src/concept_workshop/workshop_runner.py` | CLI entry point for interactive workshop sessions |
| `src/concept_workshop/workshop_summarizer.py` | Conversation compression for multi-session workshops |
| `src/agents/manuscript_reviewer.py` | Dual-persona (Literary Critic + Structural Editor) full-manuscript review |
| `src/quality/style_fingerprint.py` | Prose style metric extraction, comparison, and storage |
| `src/quality/voice_checker.py` | Voice profile and anti-slop constraint checking |

### Schema Changes

**`concept_seed.json`** -- new optional fields:
- `meta.project_scope` (standalone/planned_series/continuation)
- `meta.series` (series_id + book_number reference)
- `meta.book_number`
- `ensemble_cast[].weiland_arc` (lie/ghost/want/need/arc_type/arc_phase_targets)
- `voice_definition` (pov_approach, prose_register, reference_authors, anti_slop, anti_patterns, narrative_voice_notes)
- `subplot_board` (array of subplot objects with line_type, interweave_points, current_status)
- `hook_map` (array of hook objects with hook_type, priority, planted/payoff chapters)
- `revelation_schedule` (array of info revelations with significance levels)
- `terminology_registry` (array of term objects with aliases and categories)
- `stress_test_results` (5-dimension scores + flagged_issues + human_approved)

**`scene_card.json`** -- new optional fields:
- `active_subplots` (subplot_ids active in this scene)
- `hook_actions` (array of {hook_id, action: plant/advance/resolve/subvert})
- `revelations` (info_ids from revelation schedule)
- `pov_arc_phase` (current Weiland arc phase)
- `arc_phase_transition` (new phase if transition occurs)

**`state_diff.json`** -- new change types:
- `subplot_updates` (subplot_id field changes)
- `hook_updates` (hook_id field changes with type/priority/related_subplot)
- `arc_phase_updates` (character_id old_phase/new_phase with evidence)
- `terminology_updates` (term field changes with definition/category/aliases)

**`failure_code.json`** -- 5 new codes (see above)

**NEW `series_seed.json`** -- full schema for multi-book series planning: `series_title`, `total_books` (2-5), `series_dramatic_question`, `series_antagonist_escalation`, `series_stakes_progression`, `series_theme`, `per_book_outline` (with `book_role_in_series`: setup/escalation/resolution, thread inheritance), `series_promises` (with setup_payoff/foreshadow/chekhov/thematic types), `shared_characters`

### Agent Pipeline Changes

**Context Assembler** -- 5 new context tiers (token budgets):
- `voice_rules` (300 tokens) -- voice definition injection
- `hook_agenda` (400 tokens) -- upcoming hook actions for current scene
- `arc_context` (300 tokens) -- POV character's Weiland arc state
- `subplot_context` (300 tokens) -- active subplot status
- `terminology` (200 tokens) -- relevant terminology entries

**PlotArchitect** -- receives hook/subplot/arc directives in scene context

**ProseStylist** -- voice definition rules injected into generation prompt

**Summarizer** -- expanded delta format with subplot_updates, hook_updates, arc_phase_updates, terminology_updates

**Gate Critic** -- 5 new failure codes with routing (see above)

**NEW ManuscriptReviewer** -- premium model, dual-persona evaluation (Literary Critic + Structural Editor), categorized issues with severity levels (critical/major/minor/suggestion), recommendation output (approve/revise_specific_chapters/major_revision_needed)

**NEW StyleFingerprinter** -- extracts prose metrics (sentence length distribution, dialogue ratio, adverb density, em-dash usage), compares against reference fingerprints, stores results in `style_fingerprint` table

---

## Migration Guide

### Database Migration

- **Automatic**: `StoryState.__init__()` runs all pending migrations on first connect
- **Schema v1 to v2**: Creates 6 new tables, preserves all existing data
- **Tracking**: `schema_migrations` table records applied version + timestamp + description
- **Safe to re-run**: All tables use `CREATE TABLE IF NOT EXISTS`

### Backward Compatibility

- All new `concept_seed` fields are optional -- existing seeds work unchanged
- All new `scene_card` fields are optional -- existing cards work unchanged
- Pipeline handles missing Phase 5 fields gracefully (`None` defaults throughout)
- Context assembler skips Phase 5 tiers when data is not present
- All 453 original tests continue to pass

### Test Coverage

- 163 new tests across 16 test files
- Total: **616 tests passing**

---

## New File Inventory

### Source (`src/`)

| Path | Description |
|------|-------------|
| `src/concept_workshop/__init__.py` | Package init |
| `src/concept_workshop/decision_detector.py` | LLM-based decision classification |
| `src/concept_workshop/series_manager.py` | Series seed CRUD and transition snapshots |
| `src/concept_workshop/state_writer.py` | Incremental concept state persistence |
| `src/concept_workshop/stress_test.py` | Adversarial 5-dimension stress test |
| `src/concept_workshop/voice_discovery.py` | Voice definition builder |
| `src/concept_workshop/workshop_runner.py` | Interactive workshop CLI |
| `src/concept_workshop/workshop_state.py` | Workshop state dataclass |
| `src/concept_workshop/workshop_summarizer.py` | Conversation history compression |
| `src/agents/manuscript_reviewer.py` | Dual-persona manuscript review agent |
| `src/quality/style_fingerprint.py` | Prose style metric extraction |
| `src/quality/voice_checker.py` | Voice profile and anti-slop checker |

### Tests (`tests/`)

| Path | Description |
|------|-------------|
| `tests/conftest_phase5.py` | Phase 5 shared fixtures |
| `tests/test_character_arcs.py` | Weiland arc CRUD and phase transitions |
| `tests/test_decision_detector.py` | Decision classification accuracy |
| `tests/test_failure_codes.py` | New failure code validation |
| `tests/test_gate_critic_new_codes.py` | Gate critic routing for new codes |
| `tests/test_hook_agenda_in_plot_architect.py` | Hook agenda injection into PlotArchitect |
| `tests/test_hook_governance.py` | Hook lifecycle and ledger operations |
| `tests/test_manuscript_reviewer.py` | Manuscript reviewer dual-persona output |
| `tests/test_propagation_debts.py` | Propagation debt creation and resolution |
| `tests/test_schema_migration.py` | v1 to v2 migration correctness |
| `tests/test_series_manager.py` | Series seed creation and validation |
| `tests/test_series_workflow.py` | End-to-end series workflow |
| `tests/test_stress_test.py` | Stress test scoring and issue flagging |
| `tests/test_style_fingerprint.py` | Style metric extraction and comparison |
| `tests/test_subplot_board.py` | Subplot CRUD and status transitions |
| `tests/test_summarizer_deltas.py` | Expanded delta format in summarizer |
| `tests/test_terminology_registry.py` | Terminology CRUD and drift detection |
| `tests/test_voice_checker.py` | Voice checking against profiles |
| `tests/test_voice_injection.py` | Voice rules injection into ProseStylist |
| `tests/test_workshop_runner.py` | Workshop runner session flow |
| `tests/test_workshop_state.py` | Workshop state persistence |
| `tests/test_workshop_summarizer.py` | Session summarization |
| `tests/test_workshop_to_pipeline.py` | Workshop to pipeline handoff |
| `tests/test_workshop_validation.py` | Concept seed validation from workshop |
| `tests/test_state_diff_validation.py` | New state diff change types |

### Schemas (`schemas/`)

| Path | Status |
|------|--------|
| `schemas/concept_seed.json` | Updated (new optional fields) |
| `schemas/scene_card.json` | Updated (new optional fields) |
| `schemas/state_diff.json` | Updated (new change types) |
| `schemas/failure_code.json` | Updated (5 new codes) |
| `schemas/series_seed.json` | **New** |

### Prompts (`prompts/`)

| Path | Status |
|------|--------|
| `prompts/concept_workshop.md` | Updated (10-step flow) |
| `prompts/stress_test_prompt.md` | **New** |
| `prompts/voice_definition_template.md` | **New** |
| `prompts/agent_system_prompts/manuscript_reviewer.md` | **New** |

### Config (`config/`)

| Path | Status |
|------|--------|
| `config/failure_codes.yaml` | Updated (5 new codes + categories) |
