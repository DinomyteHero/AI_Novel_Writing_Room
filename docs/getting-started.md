# Getting Started

This guide covers installation, configuration, and running your first pipeline.

## Prerequisites

- **Python 3.10+**
- **Node.js 18+** (only needed for the web dashboard)
- One of:
  - An [OpenRouter](https://openrouter.ai/) API key (cloud mode)
  - A running [llama-server](https://github.com/ggerganov/llama.cpp) instance (local mode)
  - Both (hybrid mode)

## Installation

```bash
git clone https://github.com/DinomyteHero/AI_Novel_Writing_Room.git
cd AI_Novel_Writing_Room
pip install -r requirements.txt
```

### Dependencies by Phase

Not all dependencies are required. The pipeline gracefully degrades when optional packages are missing:

| Dependency | Required For |
|-----------|-------------|
| httpx, pyyaml, pydantic | Core (all phases) |
| pytest, pytest-asyncio | Running tests |
| chromadb, sentence-transformers, numpy | Phase 2 (memory, canon, RAG) |
| nltk, scikit-learn | Optional prose-analysis tooling |
| python-docx, ebooklib | Phase 4 (DOCX/EPUB export) |
| fastapi, uvicorn, websockets | Web dashboard |

### Frontend Setup (Optional)

If you want to use the web dashboard:

```bash
cd src/ui/frontend
npm install
npm run build
cd ../../..
```

## Configuration

The main configuration file is `config/settings.yaml`. Key settings:

### Deployment Mode

```yaml
deployment_mode: cloud  # local | cloud | hybrid
```

- **local** -- All inference runs on your local llama-server
- **cloud** -- All inference goes through OpenRouter
- **hybrid** -- Local for high-volume drafting, cloud for critique and evaluation

### API Key

For cloud or hybrid mode, set your OpenRouter API key:

```bash
export OPENROUTER_API_KEY=your_key_here
```

The key is read from the environment variable specified in `config/settings.yaml` under `models.cloud.api_key_env`.

### Local Inference

For local mode, start llama-server with your chosen model:

```bash
llama-server -m /path/to/model.gguf --port 8080 -ngl 99
```

The local base URL defaults to `http://localhost:8080/v1` (configurable in `settings.yaml`).

## Your First Run

The project includes a worked example called "The Ruusan Atonement" — a 28-chapter Star Wars Legends EU novel — shipped under the franchise-scoped layout. The example's scene cards, concept seed, canon profile, chapter blueprints, and worldbuilding DB are all in-tree and used by the test suite.

### Directory Layout

The pipeline supports two input layouts. The shipped worked example uses the franchise-scoped layout; the flat layout is retained for ad-hoc projects.

**Franchise-scoped (used by the shipped worked example and recommended for new work):**
```
data/franchises/<franchise>/books/<book>/
├── concept_seed.json
├── scene_cards/
│   ├── chapter_01_scene_01.json
│   └── ...
├── chapter_blueprints/          # (optional, auto-generated when --phase 5)
└── worldbuilding.db             # shared across books in the franchise
```

**Flat project-scoped (still supported by the CLI for ad-hoc use):**
```
data/projects/<slug>/
├── concept_seed.json
└── scene_cards/
    ├── chapter_01_scene_01.json
    └── ...
```

Output is run-scoped when using `--franchise`:
```
output/<franchise>/<book>/runs/<run_id>/chapters/
```

Or flat when using the legacy layout:
```
output/<project-slug>/chapters/
```

### Run a Single Chapter (franchise-scoped, the shipped example)

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --chapter 1 --phase 1
```

This runs the lean scene path: `PlotArchitect -> ProseStylist -> [LineWriter] -> save`. The pipeline is a single forward pass — there is no save-time gate, polish pass, or save-blocker layer; the drafter lands the scene contract on the first pass.

Output goes to `output/star-wars-legends-eu/the-ruusan-atonement/runs/<auto-timestamp>/chapters/`.

### Run with Named Run Isolation

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --run-name first-draft --phase 5
```

Output goes to `output/star-wars-legends-eu/the-ruusan-atonement/runs/first-draft/chapters/`. Each run is fully isolated with its own chapters, config snapshot, prompts snapshot, and session data.

### Run with Full Features

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --phase 5
```

Phase 5 enables the highest pipeline depth: story state, chapter memory, the post-save memory chain, session persistence, and chapter blueprint generation. The per-scene drafting path is the same lean forward pass at every phase.

### Export the Manuscript

After generation, export to multiple formats:

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --export-only --export-formats md,docx,epub
```

### Run the Web Interface

```bash
python -m src.ui.server \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json
```

Open http://localhost:8000.

### Migrate Existing Data

If you have legacy data in the flat `data/projects/<slug>/` layout and want to move it to the franchise-scoped layout:

```bash
python scripts/migrations/migrate_to_franchise_layout.py --dry-run   # preview
python scripts/migrations/migrate_to_franchise_layout.py             # execute
```

The older `scripts/migrations/migrate_to_project_dirs.py` (flat-to-flat reorganization) is also preserved for historical migrations.

## Verify Your Setup

Run the test suite to confirm everything is installed correctly:

```bash
pytest
```

If some tests are skipped due to missing optional dependencies (chromadb, sentence-transformers, fastapi), that's expected — the tests for those subsystems are skipped when their dependencies aren't installed.

## Three Workflows

### Workflow A: Fully Automated (workflow kit, recommended)

Scaffold a fresh project from templates, author each surface, then compile and run:

```bash
python scripts/init_project.py --title "My Novel" --franchise "My Franchise" --depth original_light
# Author via workflow kit surfaces (chat skills, api.py, or markdown importers)
python scripts/compile_bundle.py --franchise my-franchise --book my-novel
python -m src.main \
    data/franchises/my-franchise/books/my-novel/concept_seed.json \
    data/franchises/my-franchise/books/my-novel/scene_cards \
    --franchise my-franchise --book my-novel --phase 5
```

See [Workflow Kit](user-guide/workflow-kit.md) for the six-surface breakdown.

The legacy `workshop_runner.py` 11-step CLI has been removed. Its replacement is the workflow kit above.

### Workflow B: External Concept, Auto Outline

Develop your concept in any LLM chat (Claude, ChatGPT, Gemini), import it, then auto-generate scene cards:

```bash
python -m src.main --import-summary manuscript.md --project my-novel --phase 5
python -m src.main \
    data/franchises/my-franchise/books/my-novel/concept_seed.json \
    data/franchises/my-franchise/books/my-novel/scene_cards \
    --franchise my-franchise --book my-novel \
    --generate-outline --phase 5
```

Best for: creative freedom during concept development, with automated scene card generation. See the [planning manuscript template](workshop-summary-template.md).

### Workflow C: Fully External

Develop both your concept seed AND scene cards in an external LLM chat, then run the pipeline directly:

```bash
python -m src.main \
    data/franchises/my-franchise/books/my-novel/concept_seed.json \
    data/franchises/my-franchise/books/my-novel/scene_cards \
    --franchise my-franchise --book my-novel --phase 5
```

Best for: maximum creative control over every scene. Skip `--generate-outline` entirely — just place your concept seed and scene card JSON files in the book directory. See the [scene card template](scene-card-template.md).

See [Workflow Kit](user-guide/workflow-kit.md) for the detailed guide.

## Next Steps

- [CLI Usage](user-guide/cli-usage.md) — All CLI flags and workflows
- [Workflow Kit](user-guide/workflow-kit.md) — Six-surface concept authoring
- [Web Interface](user-guide/web-interface.md) — Dashboard walkthrough
- [New Manuscript Workflow](user-guide/new-manuscript-workflow.md) — End-to-end path from idea chat to export
- [Benchmarking](development/benchmarking.md) — Prose-model A/B evaluation
- [System Overview](architecture/system-overview.md) — How the system works
