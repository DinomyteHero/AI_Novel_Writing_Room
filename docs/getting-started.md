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
| nltk, scikit-learn | Phase 3 (quality metrics) |
| python-docx, ebooklib | Phase 4 (DOCX/EPUB export) |
| fastapi, uvicorn, websockets | Phase 5 (web interface) |

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

The project includes a worked example called "The Ruusan Atonement" with a complete concept seed and scene cards for all 28 chapters.

### Run a Single Chapter

```bash
python -m src.main \
    data/projects/the-ruusan-atonement/concept_seed.json \
    data/projects/the-ruusan-atonement/scene_cards \
    --chapter 1 \
    --phase 1
```

This runs the basic pipeline (Phase 1): PlotArchitect, ProseStylist, GateCritic, CraftEditor.

All state data is automatically scoped under `data/projects/the-ruusan-atonement/` and output goes to `output/the-ruusan-atonement/chapters/`.

### Run with Full Features

```bash
python -m src.main \
    data/projects/the-ruusan-atonement/concept_seed.json \
    data/projects/the-ruusan-atonement/scene_cards \
    --phase 4
```

Phase 4 enables all features: story state tracking, quality metrics, adaptive revision, physics enforcement, and session persistence.

### Export the Manuscript

After generation, export to multiple formats:

```bash
python -m src.main \
    data/projects/the-ruusan-atonement/concept_seed.json \
    data/projects/the-ruusan-atonement/scene_cards \
    --export-only --export-formats md,docx,epub
```

### Run the Web Interface

```bash
python -m src.ui.server data/projects/the-ruusan-atonement/concept_seed.json
```

Open http://localhost:8000.

### Migrate Existing Data

If you have data from before the project-scoped layout, run the migration:

```bash
python scripts/migrate_to_project_dirs.py --dry-run  # preview
python scripts/migrate_to_project_dirs.py             # execute
```

## Verify Your Setup

Run the test suite to confirm everything is installed correctly:

```bash
pytest
```

All ~677 tests should pass. If some tests fail due to missing optional dependencies (chromadb, sentence-transformers, fastapi), that's expected -- the tests for those phases will be skipped.

## Three Workflows

### Workflow A: Fully Automated

Use the built-in workshop CLI to develop your concept, then auto-generate scene cards and run the pipeline:

```bash
python -m src.concept_workshop.workshop_runner --project my-novel
python -m src.main data/projects/my-novel/concept_seed.json data/projects/my-novel/scene_cards --generate-outline --phase 4
```

Best for: structured, guided development with validation gates at each step.

### Workflow B: External Concept, Auto Outline

Develop your concept in any LLM chat (Claude, ChatGPT, Gemini), import it, then auto-generate scene cards:

```bash
python -m src.main --import-summary manuscript.md --project my-novel --phase 4
python -m src.main data/projects/my-novel/concept_seed.json data/projects/my-novel/scene_cards --generate-outline --phase 4
```

Best for: creative freedom during concept development, with automated scene card generation. See the [planning manuscript template](workshop-summary-template.md).

### Workflow C: Fully External

Develop both your concept seed AND scene cards in an external LLM chat, then run the pipeline directly:

```bash
python -m src.main data/projects/my-novel/concept_seed.json data/projects/my-novel/scene_cards --phase 4
```

Best for: maximum creative control over every scene. Skip `--generate-outline` entirely — just place your concept seed and scene card JSON files in the project directory. See the [scene card template](scene-card-template.md).

See [Concept Workshop](user-guide/concept-workshop.md) for detailed guides on all three workflows.

## Next Steps

- [CLI Usage](user-guide/cli-usage.md) -- All CLI flags and workflows
- [Web Interface](user-guide/web-interface.md) -- Dashboard walkthrough
- [Concept Workshop](user-guide/concept-workshop.md) -- Create your own story from scratch
- [System Overview](architecture/system-overview.md) -- How the system works
