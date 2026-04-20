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
