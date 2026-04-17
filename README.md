# AI Writers' Room

A multi-agent fiction generation system that produces novel-length (60-80K word) franchise fanfiction. The system uses a two-phase workflow: human-collaborative planning (with canon profile construction) followed by autonomous multi-agent drafting, canon validation, critique, revision, and export. Projects are organized by franchise and book, with per-run output isolation and optional series-level state sharing.

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

Using the franchise-scoped layout with per-run isolation (the shipped worked example):

```bash
python -m src.main \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
    --franchise star-wars-legends-eu --book the-ruusan-atonement \
    --run-name first-draft --phase 5
```

The flat `data/projects/<slug>/` layout is still supported by the code for ad-hoc projects, but the shipped worked example now lives under `data/franchises/`.

### Run the Web Interface

```bash
# Build the frontend (first time only)
cd src/ui/frontend && npm install && npm run build && cd ../../..

# Start the server
python -m src.ui.server \
    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json
```

Open http://localhost:8000 in your browser.

### Run the Concept Workshop

```bash
python -m src.concept_workshop.workshop_runner --project my_novel
```

Or start a new project from templates via the workflow kit — see [Workflow Kit](docs/user-guide/workflow-kit.md).

## How It Works

Each scene runs through an event-driven per-scene loop, with additional layers activating at higher pipeline depths:

1. **PlotArchitect** reads a scene card and produces a generation brief
2. **ProseStylist** drafts prose from the brief + assembled context
3. **GateCritic** evaluates the draft against a structural rubric (pass/fail with failure codes, calibration anchors, chain-of-thought reasoning); failures trigger a bounded retry loop back to the ProseStylist
4. **QualityMetrics** scores the Gate-passed draft (repetition, pacing, voice, AI-tell detection) via pure-Python checkers, no LLM call
5. **QualityPolish** makes a single bounded refinement pass targeting the flagged metrics
6. **Compression guard** rejects polish output that significantly compresses or drops material
7. **FinalGate** validates the polished prose against the scene card contract (character presence, closing-hook boundary, word-count floor, turning point); if it rejects the polish, the Gate-passed draft is saved instead

The saved file is always either polish-accepted-by-Final-Gate or the Gate-passed draft, never an unvalidated rewrite. Every step emits typed events to the RunLedger for reproducibility.

Depending on the pipeline depth selected (`--phase 1..5`), additional layers activate after the scene is saved:

| Pipeline depth | Adds |
|----------------|------|
| 1 | Per-scene loop only (PlotArchitect → ProseStylist → GateCritic → QualityMetrics → QualityPolish → compression guard → FinalGate → save) |
| 2 | Summarizer + StateDiff + ContradictionScanner (chapter memory, SQLite story state, ChromaDB, canon RAG) |
| 3 | CharacterSpecialist (OOC detection) + MilestoneGates (structural checkpoints at 25/50/75%) |
| 4 | PhysicsEnforcer (pre/post validation) + PipelineSession (save/resume) + optional LLM judge (`--judge`) |
| 5 | Chapter blueprint generation + ChapterGateCritic (advisory by default) |

Closed-loop lore (Phases 6–7, available at any depth with `--franchise`/`--book`):

- **Series continuation** — `scripts/spawn_next_book.py`, `branch_point` context in `canon_expert`, series-level shared state
- **Post-save lore extraction** — `lore_extractor` writes provisional lore after each scene; `scripts/promote_lore.py` reviews/promotes; `ChapterGateCritic` reads canonical lore; `--strict-lore` makes high-severity conflict flags blocking

Orthogonal feature sets available at any depth:

- **Voice definition + hook/subplot/terminology governance** — drives VoiceChecker, GateCritic, and the manuscript-level review
- **Character arcs (K.M. Weiland model)** — lie/ghost/want/need tracked through structural phases
- **Style fingerprinting** — prose-style drift detection across chapters
- **Manuscript review** — full-work dual-persona critique (Literary Critic + Structural Editor)
- **Web dashboard** — live pipeline control, event stream over WebSocket, chapter/quality/state inspectors
- **Export** — markdown, DOCX, EPUB
- **Prose model bench** — single-scene, same-brief A/B/C comparison across 10+ models via `scripts/bench_prose_models.py`; see [Benchmarking](docs/development/benchmarking.md)

See the [implementation roadmap](docs/development/implementation-roadmap.md) for the rollout-phase plan (not to be confused with `--phase 1..5`, which controls runtime depth).

## Directory Structure

**Input data (franchise-scoped):**
```
data/franchises/<franchise>/books/<book>/
├── concept_seed.json          # Story concept with canon_profile
└── scene_cards/               # Per-chapter scene cards
```

**Input data (flat, backward compatible):**
```
data/projects/<slug>/
├── concept_seed.json
└── scene_cards/
```

**Output (run-scoped):**
```
output/<franchise>/<book>/runs/<run_id>/
├── chapters/                  # Generated chapter markdown
├── config_snapshot.yaml       # Settings used for this run
└── session/                   # Session persistence data
```

**Series shared state (when `--series` is set):**
```
output/<franchise>/<series>/state/
```

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | Installation, configuration, first run |
| **User Guides** | |
| [CLI Usage](docs/user-guide/cli-usage.md) | All CLI flags and examples |
| [Workflow Kit](docs/user-guide/workflow-kit.md) | Six-surface concept authoring (universe/canon/voice/characters/outline/scene-cards) |
| [Web Interface](docs/user-guide/web-interface.md) | Dashboard walkthrough |
| [Concept Workshop](docs/user-guide/concept-workshop.md) | Legacy 11-step story planning CLI |
| **Architecture** | |
| [System Overview](docs/architecture/system-overview.md) | Components, data flow, directory structure |
| [Agent Pipeline](docs/architecture/agent-pipeline.md) | Multi-agent generation loop |
| [Memory & State](docs/architecture/memory-and-state.md) | SQLite, ChromaDB, knowledge layers |
| [Quality & Revision](docs/architecture/quality-and-revision.md) | Metrics, QualityPolish, compression guard, Final Gate, milestone gates |
| **Reference** | |
| [API Reference](docs/reference/api-reference.md) | FastAPI endpoints and WebSocket events |
| [Configuration](docs/reference/configuration.md) | settings.yaml, failure codes, constraints |
| [Schemas](docs/reference/schemas.md) | JSON schema definitions |
| **Development** | |
| [Contributing](docs/development/contributing.md) | Dev setup, testing, code style |
| [Adding Agents](docs/development/adding-agents.md) | How to extend the agent system |
| [Benchmarking](docs/development/benchmarking.md) | Prose-model bench, bench configs, pipeline A/B methodology |
| [Future Work](docs/development/future-work.md) | Deferred items and known follow-ups |

Historical implementation briefs from each build phase are preserved in [docs/archive/](docs/archive/).

## Tests

```bash
pytest                              # Run all tests (~1,457 collected)
pytest -k "test_orchestrator"       # Run specific tests
```

## License

TBD
