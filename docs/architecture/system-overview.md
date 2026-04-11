# System Overview

The AI Writers' Room is a multi-agent fiction generation system organized around a two-phase workflow.

## Two-Phase Workflow

### Phase A: Human Collaboration

An interactive Concept Workshop guides the user through structured story development:

1. Choose franchise, era, tone, and cast type
2. Generate and select premise seeds
3. Develop characters with detailed profiles
4. Map story structure (Larry Brooks's four-part framework)
5. Validate story physics (causality, revelations, promises)
6. Generate scene cards

The output is a **concept seed** (`concept_seed.json`) and a set of **scene cards** -- one per chapter/scene.

### Phase B: Autonomous Pipeline

The pipeline processes each scene card through a multi-agent loop:

```
Scene Card
    |
    v
PlotArchitect (scene card -> generation brief)
    |
    v
ProseStylist (generation brief + context -> draft prose)
    |
    v
GateCritic (pass/fail with 19 failure codes)
    |
    +-- fail_structural -> ProseStylist (full rewrite)
    +-- fail_voice -> ProseStylist (targeted revision)
    +-- fail_polish -> CraftEditor (non-blocking)
    +-- pass -> CraftEditor
    |
    v
CraftEditor (voice/polish improvements)
    |
    v
RevisionPipeline (up to 5 bands)
    |
    v
Save -> Summarizer -> StateDiff -> ContradictionScanner -> WorldbuildingExtraction
    |
    v
QualityMetrics -> CharacterSpecialist -> MilestoneGate
```

Not all steps are active at every phase level. The pipeline gracefully degrades when optional components are `None`.

## Directory Structure

```
ai-writers-room/
├── README.md
├── requirements.txt
├── config/
│   ├── settings.yaml              # Deployment mode, model routing, pipeline settings
│   ├── failure_codes.yaml         # 19 failure codes across 3 categories
│   ├── negative_constraints.yaml  # Banned phrases, AI-tell detection rules
│   └── eval_rubric.yaml           # LLM judge evaluation dimensions
├── src/
│   ├── main.py                    # CLI entry point
│   ├── model_router.py            # Routes agent calls to local/cloud backends
│   ├── orchestrator.py            # Event-driven pipeline state machine
│   ├── run_ledger.py              # Append-only SQLite event log
│   ├── pipeline_session.py        # JSON-based session save/resume
│   ├── agents/                    # Agent implementations (base + 8 specialized)
│   ├── memory/                    # State management (SQLite, ChromaDB, context assembly)
│   ├── worldbuilding/             # Cross-project universe & lore persistence (SQLite + ChromaDB)
│   ├── rag/                       # Canon knowledge retrieval (vector DB, hybrid search)
│   ├── quality/                   # Quality metrics and milestone gates
│   ├── revision/                  # Multi-band revision pipeline
│   ├── planning/                  # Story physics and scene card generation
│   ├── export/                    # Markdown, DOCX, EPUB export
│   ├── concept_workshop/          # Interactive concept development
│   └── ui/                        # FastAPI backend + React frontend
├── tests/                         # ~677 tests across 62+ files
├── prompts/
│   ├── concept_workshop.md        # Workshop facilitator system prompt
│   ├── agent_system_prompts/      # Per-agent system prompts (10 files)
│   └── revision_prompts/          # Per-band revision prompts (5 files)
├── schemas/                       # JSON schema definitions (9 schemas)
├── data/
│   ├── projects/                  # Per-project state (project-scoped)
│   │   └── <project-slug>/
│   │       ├── concept_seed.json
│   │       ├── scene_cards/
│   │       └── state/             # story_state.db, chapter_memory/, run_ledger.db, sessions/
│   ├── universes/                 # Cross-project worldbuilding
│   │   ├── worldbuilding.db
│   │   └── worldbuilding_vectors/
│   ├── canon_dbs/                 # Franchise RAG databases (shared)
│   └── eval_corpus/               # Reference chapters for quality calibration
├── output/
│   └── <project-slug>/
│       ├── chapters/              # Generated chapter prose
│       └── export/                # Exported manuscripts
└── docs/                          # Documentation
```

## Key Abstractions

### ModelRouter (`src/model_router.py`)

All agent code communicates through the ModelRouter, which reads `config/settings.yaml` to determine which backend handles each agent's requests:

- **Local backend**: llama-server via OpenAI-compatible API
- **Cloud backend**: OpenRouter API (Claude, Gemini, Deepseek, etc.)

The `agent_routing` section in settings.yaml maps each agent role to a backend, model tier, and parameter overrides.

### Orchestrator (`src/orchestrator.py`)

The event-driven pipeline controller. Manages the per-chapter generation loop and coordinates all optional subsystems. All Phase 2/3/4 dependencies are optional with `None` defaults for backward compatibility.

### RunLedger (`src/run_ledger.py`)

An append-only SQLite event log. Every pipeline action emits a typed event with chapter/scene context and a JSON payload. The ledger drives the web dashboard's real-time event stream.

## Deployment Modes

| Mode | Local LLM | Cloud LLM | Typical Use |
|------|-----------|-----------|-------------|
| `local` | All agents | None | Offline, GPU-equipped machine |
| `cloud` | None | All agents | No local GPU, API access only |
| `hybrid` | Drafting agents | Critique/judge | Cost optimization |

Set via `deployment_mode` in `config/settings.yaml`.

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Core | Python 3.10+ |
| LLM Integration | httpx -> llama-server / OpenRouter |
| Persistent State | SQLite (story state, run ledger, worldbuilding) |
| Vector Memory | ChromaDB (chapter summaries, canon DB, worldbuilding lore) |
| Quality Metrics | NLTK, scikit-learn (pure Python) |
| Export | python-docx, ebooklib |
| Web Backend | FastAPI, uvicorn, WebSockets |
| Web Frontend | React, Vite, TypeScript, TailwindCSS, Recharts |
