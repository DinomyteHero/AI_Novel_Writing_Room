# CLI Usage

The main CLI entry point is `src/main.py`. It runs the lean multi-agent generation pipeline from the command line.

## Basic Usage

```bash
python -m src.main <concept_seed> <scene_cards_dir> [options]
```

**Required arguments:**

| Argument | Description |
|----------|-------------|
| `concept_seed` | Path to the concept seed JSON file |
| `scene_cards_dir` | Path to the directory containing scene card JSON files |

Both positional arguments are omitted when using `--import-summary` or `--server`.

## Options

### Pipeline Control

| Flag | Default | Description |
|------|---------|-------------|
| `--phase {1,2,3,4,5}` | 1 | Pipeline depth. Higher phases enable more subsystems (see [Phase Features](#phase-features)). The per-scene drafting path is the same lean forward pass at every phase. |
| `--chapter N` | all | Generate only this chapter number |
| `--config PATH` | `config/settings.yaml` | Path to the configuration file |
| `--output-dir PATH` | auto | Override the manuscript output directory |
| `--project SLUG` | auto | Project slug for project-scoped data isolation (auto-derived from concept seed title) |

### Plan Approval

The pipeline refuses to draft a seed whose plan has not been approved. A plan is approved when `compile_metadata.plan_approved` is `true` in the concept seed.

| Flag | Description |
|------|-------------|
| `--allow-unapproved-plan` | Bypass the plan-approval check (not recommended) |

Approve a plan with `python scripts/approve_plan.py --franchise <slug> --book <slug>`.

### Runtime Flags

| Flag | Description |
|------|-------------|
| `--runtime-flag KEY=VALUE` | Override a runtime flag with a dotted key, e.g. `--runtime-flag runtime.rhythm_validator.enabled=true`. May be repeated. |

Runtime flags resolve through `src/runtime_flags.py`: CLI overrides win over per-book `runtime_overrides.yaml`, then per-franchise, then the `runtime:` block in `config/settings.yaml`. See [Configuration](../reference/configuration.md#runtime-flags).

### Blueprint Flags (Phase 5)

| Flag | Description |
|------|-------------|
| `--no-blueprints` | Skip chapter blueprint auto-generation. Hand-authored blueprints at `data/franchises/<fr>/books/<bk>/chapter_blueprints/` are still loaded by the chapter-packet compiler if present. |
| `--regenerate-blueprints` | Overwrite existing chapter blueprints. Default behaviour preserves hand-authored blueprints (skip-if-exists). |

### Franchise and Book Scoping

| Flag | Default | Description |
|------|---------|-------------|
| `--franchise SLUG` | none | Franchise identifier. Scopes input data under `data/franchises/<franchise>/books/<book>/` and output under `output/<franchise>/<book>/runs/<run_id>/`. Also enables the worldbuilding service and post-save lore extraction. |
| `--book SLUG` | auto | Book identifier within a franchise (auto-derived from concept seed title if not provided) |
| `--series SLUG` | none | Series identifier for series-level state sharing between books. When set, shared state is written to `output/<franchise>/<series>/state/`. |
| `--run-name NAME` | auto-timestamped | Name for this pipeline run. Each run creates an isolated directory under `runs/` containing chapters, a config snapshot, a prompts snapshot, and session data. |

**Deprecated aliases (still accepted):**

| Deprecated Flag | Replacement |
|-----------------|-------------|
| `--universe-id` | `--franchise` |
| `--project-id` | `--book` |

**Backward compatibility:** The flat `data/projects/<slug>/` layout is still supported. When `--franchise` is not provided, the pipeline falls back to the project-scoped directory structure.

### Phase Features

The per-scene drafting path — `PlotArchitect → ProseStylist → [LineWriter] → save` — is identical at every phase. Higher phases attach more post-save and pre-run subsystems:

| Phase | What It Adds |
|-------|-------------|
| 1 | Lean drafting only: `PlotArchitect → ProseStylist → [LineWriter] → [rhythm stages] → save` |
| 2 | SQLite story state, ChromaDB chapter memory, knowledge layers, canon RAG, and the post-save memory chain (Summarizer → state diff → contradiction scan → worldbuilding extraction) |
| 3 | No additional subsystems beyond Phase 2 in the current pipeline |
| 4 | Session persistence (`--resume`), export (`--export`), and scene-card generation (`--generate-outline`) |
| 5 | Chapter blueprint auto-generation |

The chapter packet (`runtime.chapter_packet.enabled`) is on by default at every phase. Post-save lore extraction runs at Phase 2+ when `--franchise` is set and `worldbuilding.auto_extraction.enabled` is true.

### Export (Phase 4)

| Flag | Default | Description |
|------|---------|-------------|
| `--export` | off | Export manuscript after pipeline completes |
| `--export-only` | off | Export existing manuscript without running generation |
| `--export-formats FORMATS` | `md,docx,epub` | Comma-separated export formats |

### Scene Card Generation (Phase 4)

| Flag | Description |
|------|-------------|
| `--generate-outline` | Generate scene cards from the concept seed before running the pipeline |

**Alternative:** Generate scene cards externally (in Claude Chat, ChatGPT, etc.) and save them to the `scene_cards/` directory as `chapter_NN_scene_NN.json` files. Skip `--generate-outline` and run the pipeline directly. See the [scene card template](../scene-card-template.md).

### Summary Import and Validation

| Flag | Description |
|------|-------------|
| `--import-summary PATH` | Import a planning manuscript and convert it to a concept seed (requires `--project`) |
| `--validate-seed` | Run compliance validation on the concept seed and print a pass/fail report |

`--import-summary` does not require the positional `concept_seed` and `scene_cards_dir` arguments.

### Session Management (Phase 4)

| Flag | Description |
|------|-------------|
| `--resume` | Resume from a saved pipeline session |
| `--session-id ID` | Specify session ID (default: auto-generated) |

### Web Server

| Flag | Default | Description |
|------|---------|-------------|
| `--server` | off | Launch the web server instead of the CLI pipeline |
| `--host HOST` | `127.0.0.1` | Web server host (only with `--server`) |
| `--port PORT` | `8000` | Web server port (only with `--server`) |

### Removed flags

The `--raw-draft`, `--skip-gate-loop`, `--strict-lore`, `--judge`, and `--no-milestones` flags were removed in the 2026-05-19 lean teardown — the gate, polish, milestone-gate, and LLM-judge subsystems they controlled no longer exist. `--no-revision` is accepted as a hidden no-op for compatibility and prints a deprecation warning.

## Examples

All examples below use the shipped worked example at `data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/`. Substitute your own `--franchise`/`--book` slugs for your own projects.

### Generate one chapter at Phase 1

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --chapter 1 --phase 1
```

### Named run for output isolation

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --run-name draft-2 --phase 5
```

Output goes to `output/star-wars-legends-eu/the-ruusan-atonement/runs/draft-2/chapters/`. When `--run-name` is omitted, a timestamped run ID is generated automatically.

### Enable advisory rhythm telemetry for a diagnostic run

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --chapter 1 --phase 5 \
    --runtime-flag runtime.rhythm_validator.enabled=true \
    --runtime-flag runtime.revision_debt.enabled=true \
    --run-name ch1-rhythm-telemetry
```

The rhythm validator measures prose and writes advisory revision-debt rows; it never blocks a save. See [Benchmarking](../development/benchmarking.md).

### Series-level state sharing

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --series old-republic-trilogy --phase 5
```

Shared series state is written to `output/star-wars-legends-eu/old-republic-trilogy/state/`, accessible by other books with the same `--series` slug.

### Full pipeline with export

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --phase 5 --export
```

### Export-only (no generation)

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --export-only --export-formats docx,epub
```

### Generate scene cards from concept seed, then run pipeline

```bash
python -m src.main \
    data/franchises/my-franchise/books/my-novel/concept_seed.json \
    data/franchises/my-franchise/books/my-novel/scene_cards \
    --franchise my-franchise --book my-novel \
    --phase 5 --generate-outline
```

### Import a planning manuscript as concept seed

```bash
python -m src.main \
    --import-summary path/to/manuscript.md \
    --project my-novel \
    --phase 5
```

### Validate an existing concept seed

```bash
python -m src.main \
    data/franchises/my-franchise/books/my-novel/concept_seed.json \
    data/franchises/my-franchise/books/my-novel/scene_cards \
    --franchise my-franchise --book my-novel \
    --validate-seed
```

### Resume a previous session

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --phase 5 --resume
```

### Start the web server from main.py

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --server --port 8080
```

## Output

### Franchise-scoped layout (when `--franchise` is used)

Each run produces an isolated output directory:

```
output/<franchise>/<book>/
├── runs/
│   ├── <run_id>/
│   │   ├── chapters/
│   │   │   ├── chapter_01_scene_01.md
│   │   │   ├── chapter_02_scene_01.md
│   │   │   └── ...
│   │   ├── chapter_packets/        # compiled chapter packets (base + overlays)
│   │   ├── config_snapshot.yaml
│   │   ├── invocation.json
│   │   └── prompts_snapshot/
│   └── <run_id_2>/
│       └── ...
├── state/                         # story_state.db, chapter_memory/, run_ledger.db, revision_debt.db
└── export/
    ├── manuscript.md
    ├── manuscript.docx
    └── manuscript.epub
```

When `--series` is set, shared state is written to `output/<franchise>/<series>/state/`.

### Flat project layout (backward compatible)

When `--franchise` is not provided, output uses the legacy flat layout:

```
output/<project-slug>/
├── chapters/
│   ├── chapter_01_scene_01.md
│   └── ...
└── export/
```

Exports are saved to the `export/` directory under the book or project output root.

## Pipeline Output Summary

After completion, the CLI prints a summary:

```
============================================================
Pipeline Complete
============================================================
Scenes saved: 5
Total word count: 15,234
  saved_clean:          5
  Chapter 1.1: 3,012 words, status=saved_clean
  Chapter 2.1: 2,987 words, status=saved_clean
  ...
```

Every scene in the lean pipeline saves as `saved_clean` (or `saved_with_advisory` if an advisory-level signal fired). Contradiction flags from the post-save scan, when any are raised, are appended as `flags=N`.
