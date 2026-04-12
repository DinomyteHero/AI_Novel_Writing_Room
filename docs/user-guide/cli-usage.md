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
| `--phase {1,2,3,4}` | 1 | Pipeline phase. Higher phases enable more features (see below) |
| `--chapter N` | all | Generate only this chapter number |
| `--config PATH` | `config/settings.yaml` | Path to the configuration file |
| `--output-dir PATH` | auto | Override the manuscript output directory |
| `--project SLUG` | auto | Project slug for project-scoped data isolation (auto-derived from concept seed title) |

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

**Backward compatibility:** The flat `data/projects/<slug>/` layout is still supported. When `--franchise` is not provided, the pipeline falls back to the project-scoped directory structure.

### Phase Features

| Phase | What It Adds |
|-------|-------------|
| 1 | Core pipeline: PlotArchitect, ProseStylist, CanonExpert, GateCritic, CraftEditor |
| 2 | SQLite story state, ChromaDB chapter memory, knowledge layers, canon RAG, contradiction scanner |
| 3 | Quality metrics (repetition, pacing, voice, slop), character specialist, 3-band revision, milestone gates |
| 4 | Physics enforcement, adaptive 5-band revision, export, session persistence, LLM judge, scene card generation |

### Revision and Milestones (Phase 3+)

| Flag | Description |
|------|-------------|
| `--no-revision` | Skip the revision pipeline |
| `--no-milestones` | Skip milestone gate pausing (gates at first plot point, midpoint, second plot point) |

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

### Generate one chapter at Phase 1 (flat project layout)

```bash
python -m src.main \
    data/projects/the-ruusan-atonement/concept_seed.json \
    data/projects/the-ruusan-atonement/scene_cards \
    --chapter 1 --phase 1
```

### Generate using franchise-scoped layout

```bash
python -m src.main \
    data/franchises/star-wars/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars --book the-ruusan-atonement \
    --phase 4
```

### Named run for output isolation

```bash
python -m src.main \
    data/franchises/star-wars/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars --book the-ruusan-atonement \
    --run-name draft-2 --phase 4
```

Output goes to `output/star-wars/the-ruusan-atonement/runs/draft-2/chapters/`. When `--run-name` is omitted, a timestamped run ID is generated automatically.

### Series-level state sharing

```bash
python -m src.main \
    data/franchises/star-wars/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars --book the-ruusan-atonement \
    --series old-republic-trilogy --phase 4
```

Shared series state is written to `output/star-wars/old-republic-trilogy/state/`, accessible by other books in the same series.

### Generate all chapters with quality metrics and revision

```bash
python -m src.main \
    data/projects/the-ruusan-atonement/concept_seed.json \
    data/projects/the-ruusan-atonement/scene_cards \
    --phase 3
```

### Full pipeline with export and LLM judge

```bash
python -m src.main \
    data/projects/the-ruusan-atonement/concept_seed.json \
    data/projects/the-ruusan-atonement/scene_cards \
    --phase 4 --export --judge
```

### Export-only (no generation)

```bash
python -m src.main \
    data/projects/the-ruusan-atonement/concept_seed.json \
    data/projects/the-ruusan-atonement/scene_cards \
    --export-only --export-formats docx,epub
```

### Generate scene cards from concept seed, then run pipeline

```bash
python -m src.main \
    data/projects/the-ruusan-atonement/concept_seed.json \
    data/projects/the-ruusan-atonement/scene_cards \
    --phase 4 --generate-outline
```

### Import a planning manuscript as concept seed

```bash
python -m src.main \
    --import-summary path/to/manuscript.md \
    --project my-novel \
    --phase 4
```

### Validate an existing concept seed

```bash
python -m src.main \
    data/projects/my-novel/concept_seed.json \
    --validate-seed
```

### Resume a previous session

```bash
python -m src.main \
    data/projects/the-ruusan-atonement/concept_seed.json \
    data/projects/the-ruusan-atonement/scene_cards \
    --phase 4 --resume
```

### Start the web server from main.py

```bash
python -m src.main \
    data/projects/the-ruusan-atonement/concept_seed.json \
    data/projects/the-ruusan-atonement/scene_cards \
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
