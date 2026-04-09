# AI Writers' Room

A multi-agent fiction generation system that produces novel-length (60-80K word) franchise fanfiction. The system uses a two-phase workflow: human-collaborative planning followed by autonomous multi-agent drafting, critique, revision, and export.

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+ (for the web dashboard, optional)
- An [OpenRouter](https://openrouter.ai/) API key (for cloud mode), or a local [llama-server](https://github.com/ggerganov/llama.cpp) instance (for local mode)

### Installation

```bash
git clone https://github.com/DinomyteHero/AI_Novel_Writing_Room.git
cd AI_Novel_Writing_Room
pip install -r requirements.txt
```

Set your OpenRouter API key (for cloud or hybrid mode):

```bash
export OPENROUTER_API_KEY=your_key_here
```

### Run the CLI Pipeline

```bash
python -m src.main data/story_bibles/the_ruusan_atonement/concept_seed.json \
    data/story_bibles/the_ruusan_atonement/scene_cards \
    --phase 4
```

### Run the Web Interface

```bash
# Build the frontend (first time only)
cd src/ui/frontend && npm install && npm run build && cd ../../..

# Start the server
python -m src.ui.server data/story_bibles/the_ruusan_atonement/concept_seed.json
```

Open http://localhost:8000 in your browser.

### Run the Concept Workshop

```bash
python -m src.concept_workshop.workshop_runner --project my_novel
```

## How It Works

The pipeline generates chapters through a multi-agent loop:

1. **PlotArchitect** reads a scene card and produces a generation brief
2. **ProseStylist** drafts prose from the brief + assembled context
3. **GateCritic** evaluates the draft against a structural rubric (pass/fail with 19 failure codes)
4. **CraftEditor** applies non-blocking polish improvements
5. **RevisionPipeline** runs up to 5 revision passes (structural continuity, scene emotion, line copy, dialogue polish, worldbuilding coherence)
6. **QualityMetrics** scores the output (repetition, pacing, voice, AI-tell detection)

Higher phases add more capabilities:

| Phase | Features |
|-------|----------|
| 1 | Core 4-agent pipeline, failure codes, retry logic |
| 2 | SQLite story state, ChromaDB chapter memory, knowledge layers, canon RAG |
| 3 | Quality metrics, character specialist, 3-band revision, milestone gates |
| 4 | Export (md/docx/epub), physics enforcement, adaptive revision, LLM judge, session persistence |
| 5 | Series planning, voice definition, hook/subplot governance, character arcs (Weiland), terminology registry, stress testing, manuscript review, style fingerprinting, web dashboard with WebSocket streaming |

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | Installation, configuration, first run |
| **User Guides** | |
| [CLI Usage](docs/user-guide/cli-usage.md) | All CLI flags and examples |
| [Web Interface](docs/user-guide/web-interface.md) | Dashboard walkthrough |
| [Concept Workshop](docs/user-guide/concept-workshop.md) | Interactive story planning |
| **Architecture** | |
| [System Overview](docs/architecture/system-overview.md) | Components, data flow, directory structure |
| [Agent Pipeline](docs/architecture/agent-pipeline.md) | Multi-agent generation loop |
| [Memory & State](docs/architecture/memory-and-state.md) | SQLite, ChromaDB, knowledge layers |
| [Quality & Revision](docs/architecture/quality-and-revision.md) | Metrics, revision bands, milestone gates |
| **Reference** | |
| [API Reference](docs/reference/api-reference.md) | FastAPI endpoints and WebSocket events |
| [Configuration](docs/reference/configuration.md) | settings.yaml, failure codes, constraints |
| [Schemas](docs/reference/schemas.md) | JSON schema definitions |
| **Development** | |
| [Contributing](docs/development/contributing.md) | Dev setup, testing, code style |
| [Adding Agents](docs/development/adding-agents.md) | How to extend the agent system |

Historical implementation briefs from each build phase are preserved in [docs/archive/](docs/archive/).

## Tests

```bash
pytest                    # Run all tests (616)
pytest -k "test_orchestrator"   # Run specific tests
```

## License

TBD
