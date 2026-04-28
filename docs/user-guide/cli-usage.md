# CLI Usage

The main CLI entry point is `src/main.py`. It runs the multi-agent generation pipeline from the command line.

## Basic Usage

```bash
python -m src.main <concept_seed> <scene_cards_dir> [options]
```

**Required arguments:**

| Argument | Description |
|----------|-------------|
| `concept_seed` | Path to the concept seed JSON file |
| `scene_cards_dir` | Path to the directory containing scene card JSON files |

## Options

### Pipeline Control

| Flag | Default | Description |
|------|---------|-------------|
| `--phase {1,2,3,4,5}` | 1 | Pipeline depth. Higher phases enable more subsystems (see below). The shipping lean runtime still bypasses broad gates, save-blockers, and post-save LLM agents unless lean is disabled. |
| `--chapter N` | all | Generate only this chapter number |
| `--config PATH` | `config/settings.yaml` | Path to the configuration file |
| `--output-dir PATH` | auto | Override the manuscript output directory |
| `--project SLUG` | auto | Project slug for project-scoped data isolation (auto-derived from concept seed title) |

### Pipeline Mode Flags

| Flag | Description |
|------|-------------|
| `--raw-draft` | Non-lean baseline mode: skip QualityPolish and FinalGate. Saves the Scene-Gate-passed draft directly. Use this to measure drafting plus gate telemetry before polish. In lean mode, broad gates and polish are already skipped. |
| `--skip-gate-loop` | Skip the GateCritic LLM call entirely and synthesize a `skipped` verdict. The forward-only relay has no rewrite loop, so this flag only bypasses the gate-critic call. In non-lean runs, QualityPolish and FinalGate still run unless combined with `--raw-draft`; in lean runs they are already skipped. Useful for bench configs and cheap runs where gate telemetry is not needed. Flag name is historical from the retry-era pipeline. |
| `--strict-lore` | Phase 7: promote high-severity `LoreConflictDetector` flags to blocking status. Default is advisory — flags land in the run ledger under `lore_conflicts` and the scene is still saved. |
| `--no-milestones` | Skip milestone gate pausing (Phase 3/4 only) |

### Phase 5 Blueprint Flags

| Flag | Description |
|------|-------------|
| `--no-blueprints` | Phase 5: skip chapter blueprint auto-generation. Hand-authored blueprints at `data/franchises/<fr>/books/<bk>/chapter_blueprints/` are still loaded by `ChapterGateCritic` if present. |
| `--regenerate-blueprints` | Phase 5: overwrite existing chapter blueprints. Default behaviour preserves hand-authored blueprints (skip-if-exists). |

### Franchise and Book Scoping

| Flag | Default | Description |
|------|---------|-------------|
| `--franchise SLUG` | none | Franchise identifier. Scopes input data under `data/franchises/<franchise>/books/<book>/` and output under `output/<franchise>/<book>/runs/<run_id>/` |
| `--book SLUG` | auto | Book identifier within a franchise (auto-derived from concept seed title if not provided) |
| `--series SLUG` | none | Series identifier for series-level state sharing between books. When set, shared state is written to `output/<franchise>/<series>/state/` |
| `--run-name NAME` | auto-timestamped | Name for this pipeline run. Each run creates an isolated directory under `runs/` containing chapters, a config snapshot, and session data |

**Deprecated aliases (still accepted):**

| Deprecated Flag | Replacement |
|-----------------|-------------|
| `--universe-id` | `--franchise` |
| `--project-id` | `--book` |
| `--no-revision` | Removed rewrite-era flag. Still accepted as a hidden no-op for compatibility; use `--raw-draft` for pre-polish baseline mode. |

**Backward compatibility:** The flat `data/projects/<slug>/` layout is still supported. When `--franchise` is not provided, the pipeline falls back to the project-scoped directory structure.

### Phase Features

| Phase | What It Adds |
|-------|-------------|
| 1 | Shipping lean path: PlotArchitect -> ProseStylist -> [LineWriter] -> save. Non-lean diagnostic relay: PlotArchitect -> ProseStylist -> [LineWriter] -> GateCritic (advisory) -> QualityMetrics -> QualityPolish -> compression guard -> FinalGate (advisory) -> CanonExpert -> save-blocker layer -> save \| quarantine |
| 2 | SQLite story state, ChromaDB chapter memory, knowledge layers, canon RAG, CanonExpert, Summarizer, StateDiff, ContradictionScanner |
| 3 | Quality metrics (repetition, pacing, voice, slop), CharacterSpecialist, milestone gates at 25/50/75% |
| 4 | PhysicsEnforcer, export, session persistence (save/resume), optional LLM judge (`--judge`), scene card generation (`--generate-outline`) |
| 5 | Chapter blueprint generation + `ChapterGateCritic` (advisory by default) |

Phases 6 and 7 are orthogonal runtime features. They activate when their corresponding CLI flags or scripts are used, but post-save lore extraction requires a non-lean/full-relay run because lean mode skips post-save LLM agents.

| Orthogonal | What It Adds |
|------------|-------------|
| 6 | Series continuation (`scripts/spawn_next_book.py`), `branch_point` consumed by `canon_expert`, series-level shared state via `--series` |
| 7 | Closed-loop lore: post-save `lore_extractor` writes `provisional` entries, `LoreConflictDetector` flags (advisory; blocking with `--strict-lore`), `scripts/promote_lore.py` CLI, canonical lore consulted by `ChapterGateCritic` |

### Closed-loop lore (Phase 7)

In non-lean runs, each saved scene runs the `lore_extractor` agent against the prose and
creates `provisional` lore entries in the franchise-scoped
worldbuilding DB (`data/franchises/<fr>/worldbuilding.db`). To enable:

- Pass `--franchise` and `--book` (both required so `lore_service` has a
  universe + project binding).
- Enable it in `config/settings.yaml` under
  `worldbuilding.auto_extraction.enabled: true` (default). The
  orchestrator's `worldbuilding_auto_extract` flag flips on
  automatically whenever a `lore_service` + franchise binding is in
  place; there is no separate CLI flag.

Provisional entries don't affect generation until promoted. Use
`scripts/promote_lore.py` to review and promote provisional entries to
`canonical`; canonical entries are then available to `ChapterGateCritic`
for lore-consistency checks. Pass `--strict-lore` to the pipeline to
make high-severity conflict flags blocking (default is advisory —
flags land in the run ledger under `lore_conflicts` and the scene is
still saved).

### Export (Phase 4)

| Flag | Default | Description |
|------|---------|-------------|
| `--export` | off | Export manuscript after pipeline completes |
| `--export-only` | off | Export existing manuscript without running generation |
| `--export-formats FORMATS` | `md,docx,epub` | Comma-separated export formats |

### Scene Card Generation (Phase 4)

| Flag | Description |
|------|-------------|
| `--generate-outline` | Generate scene cards from concept seed before running the pipeline |

**Alternative:** You can generate scene cards externally (in Claude Chat, ChatGPT, etc.) and save them directly to the `scene_cards/` directory as `chapter_NN_scene_NN.json` files. Skip `--generate-outline` and run the pipeline directly. See the [scene card template](../scene-card-template.md) for the required fields and generation rules.

### Summary Import and Validation

| Flag | Description |
|------|-------------|
| `--import-summary PATH` | Import a planning manuscript and convert it to a concept seed (requires `--project`) |
| `--validate-seed` | Run compliance validation on the concept seed and print a pass/fail report |

Note: `--import-summary` does not require the positional `concept_seed` and `scene_cards_dir` arguments.

### Session Management (Phase 4)

| Flag | Description |
|------|-------------|
| `--resume` | Resume from a saved pipeline session |
| `--session-id ID` | Specify session ID (default: auto-generated) |

### LLM Judge (Phase 4)

| Flag | Description |
|------|-------------|
| `--judge` | Run LLM-as-judge evaluation after generation (uses cloud model) |

### Web Server

| Flag | Default | Description |
|------|---------|-------------|
| `--server` | off | Launch the web server instead of the CLI pipeline |
| `--host HOST` | `127.0.0.1` | Web server host (only with `--server`) |
| `--port PORT` | `8000` | Web server port (only with `--server`) |

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

### Raw-draft baseline (skip polish and final gate)

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --chapter 1 --phase 1 --raw-draft --run-name ch1-raw
```

Useful for isolating drafting plus gate telemetry before evaluating polish. See [Benchmarking](../development/benchmarking.md).

### Skip GateCritic telemetry

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --chapter 1 --skip-gate-loop --run-name ch1-no-gate-loop
```

Bypass the GateCritic LLM call and synthesize a `skipped` verdict. Polish and Final Gate still run in non-lean mode. Primarily used in benchmarking to isolate prose quality from gate telemetry cost.

### Series-level state sharing

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --series old-republic-trilogy --phase 5
```

Shared series state is written to `output/star-wars-legends-eu/old-republic-trilogy/state/`, accessible by other books with the same `--series` slug.

### Full pipeline with export and LLM judge

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --phase 5 --export --judge
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
│   │   ├── config_snapshot.yaml
│   │   └── session/
│   └── <run_id_2>/
│       └── ...
└── export/
    ├── manuscript.md
    ├── manuscript.docx
    └── manuscript.epub
```

When `--series` is set, shared state is written alongside the book output:

```
output/<franchise>/<series>/state/
```

### Flat project layout (backward compatible)

When `--franchise` is not provided, output uses the legacy flat layout:

```
output/<project-slug>/
├── chapters/
│   ├── chapter_01_scene_01.md
│   ├── chapter_02_scene_01.md
│   └── ...
└── export/
    ├── manuscript.md
    ├── manuscript.docx
    └── manuscript.epub
```

Exports are saved to the `export/` directory under the book or project output root.

## Pipeline Output Summary

After completion, the CLI prints a summary:

```
============================================================
Pipeline Complete
============================================================
Chapters generated: 5
Total word count: 15,234
  Chapter 1.1: 3,012 words, gate=pass, quality=0.72, chars=pass
  Chapter 2.1: 2,987 words, gate=pass, quality=0.68
  ...
```

The summary includes gate verdict, contradiction flags (Phase 2+), quality score (Phase 3+), character analysis verdict (Phase 3+), and LLM judge score (Phase 4, when `--judge` is used).
