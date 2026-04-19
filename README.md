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

### Start a new project

Use the workflow kit to scaffold a new project from templates — see [Workflow Kit](docs/user-guide/workflow-kit.md). The earlier interactive `src.concept_workshop.workshop_runner` CLI has been removed; all new projects flow through the per-surface workflow kit and are compiled via `scripts/compile_bundle.py`.

## How It Works

Each scene runs through a forward-only relay (post-v3 refactor — no retry loops, gates are telemetry, save-blocker is the only hard-failure path):

1. **PlotArchitect** reads a scene card and produces a generation brief
2. **ProseStylist (drafter)** drafts prose from the brief + assembled context
3. **LineWriter** — optional line-editing pass (GPT 5.4 @ t=0.8) that preserves beats, turning point, POV, characters_present, and canon while rewriting sentence-level rhythm, imagery, and voice texture. Skipped in `--raw-draft` mode and when no `line_writer` routing entry is configured.
4. **GateCritic** evaluates the draft against a structural rubric (pass/fail with failure codes); runs as telemetry under the relay — verdicts are logged but do not block the pipeline
5. **QualityMetrics** scores the draft (repetition, pacing, voice, AI-tell detection) via pure-Python checkers, no LLM call
6. **QualityPolish (copy editor)** makes a single bounded refinement pass targeting the flagged metrics
7. **Compression advisory** logs a ledger event when polish cuts below 60% of pre-polish word count; kept for telemetry, no longer reverts
8. **FinalGate** validates polished prose against the scene contract (character presence, closing-hook boundary, turning point); advisory only
9. **Continuity Editor (canon_expert)** runs on FINAL polished prose — the last reader before save
10. **Save-blocker layer** — three blocker categories can abort the run: `CHARACTER_PRESENCE_BLOCKER` (dedicated PresenceChecker agent), `CANON_BLOCKER` (continuity_report verdict=fail + severity in {critical, moderate}), and `POV_ADVISORY` (advisory-only in v1). Quarantine-on-first-blocker policy: the run aborts, the offending scene lands at `<project>/quarantine/chNN_scMM/{prose.md, blockers.json, brief.json}`, and no partial chapters ship.

The saved file is the polished, continuity-checked prose. Scenes save as `saved_clean` (all gates green), `saved_with_advisory` (any gate fired advisory-level signal), or never save at all if the save-blocker fires. Every step emits typed events (with level: info/warn/error) to the RunLedger. Chapter-level word-count drift is tracked as telemetry at chapter close (±15% / ±15-30% / >30% thresholds); scene-level word count is no longer enforced at any gate.

Depending on the pipeline depth selected (`--phase 1..5`), additional layers activate after the scene is saved:

| Pipeline depth | Adds |
|----------------|------|
| 1 | Per-scene relay only (PlotArchitect → ProseStylist → [LineWriter] → GateCritic → QualityMetrics → QualityPolish → compression advisory → FinalGate → Continuity Editor → Save-Blocker → save) |
| 2 | Summarizer + StateDiff + ContradictionScanner (chapter memory, SQLite story state, ChromaDB, canon RAG) |
| 3 | CharacterSpecialist (OOC detection) + MilestoneGates (structural checkpoints at 25/50/75%) |
| 4 | PhysicsEnforcer (pre/post validation) + PipelineSession (save/resume) + optional LLM judge (`--judge`) |
| 5 | Chapter blueprint generation + ChapterGateCritic (advisory by default) + chapter word-count telemetry |

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
