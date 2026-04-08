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
| `--output-dir PATH` | `data/manuscripts` | Override the manuscript output directory |

### Phase Features

| Phase | What It Adds |
|-------|-------------|
| 1 | Core pipeline: PlotArchitect, ProseStylist, GateCritic, CraftEditor |
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

### Generate one chapter at Phase 1

```bash
python -m src.main \
    data/story_bibles/beyond_the_veil/concept_seed.json \
    data/story_bibles/beyond_the_veil/scene_cards \
    --chapter 1 --phase 1
```

### Generate all chapters with quality metrics and revision

```bash
python -m src.main \
    data/story_bibles/beyond_the_veil/concept_seed.json \
    data/story_bibles/beyond_the_veil/scene_cards \
    --phase 3
```

### Full pipeline with export and LLM judge

```bash
python -m src.main \
    data/story_bibles/beyond_the_veil/concept_seed.json \
    data/story_bibles/beyond_the_veil/scene_cards \
    --phase 4 --export --judge
```

### Export-only (no generation)

```bash
python -m src.main \
    data/story_bibles/beyond_the_veil/concept_seed.json \
    data/story_bibles/beyond_the_veil/scene_cards \
    --export-only --export-formats docx,epub
```

### Generate scene cards from concept seed, then run pipeline

```bash
python -m src.main \
    data/story_bibles/beyond_the_veil/concept_seed.json \
    data/story_bibles/beyond_the_veil/scene_cards \
    --phase 4 --generate-outline
```

### Resume a previous session

```bash
python -m src.main \
    data/story_bibles/beyond_the_veil/concept_seed.json \
    data/story_bibles/beyond_the_veil/scene_cards \
    --phase 4 --resume
```

### Start the web server from main.py

```bash
python -m src.main \
    data/story_bibles/beyond_the_veil/concept_seed.json \
    data/story_bibles/beyond_the_veil/scene_cards \
    --server --port 8080
```

## Output

Generated chapters are saved as Markdown files in the manuscripts directory (default: `data/manuscripts/`):

```
data/manuscripts/
├── chapter_01_scene_01.md
├── chapter_02_scene_01.md
└── ...
```

Exports are saved to `data/export/`.

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
