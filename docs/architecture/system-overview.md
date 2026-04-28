# System Overview

The AI Writers' Room is a multi-agent fiction generation system organized around a two-phase workflow.

## Two-Phase Workflow

### Phase A: Human Collaboration (Workflow Kit)

Story authoring happens through the **workflow kit** — six independent per-surface skills that each own one slice of the concept:

An optional **Idea Session Capture** step can run before these surfaces. It stores a loose planning chat, north-star decisions, open questions, and per-surface handoff notes under `workflows/idea_session/`; the six surfaces remain the compiler inputs.

1. `universe-builder` — meta + premise + conflict + theme
2. `canon-drafter` — canon profile, canon constraints, terminology
3. `voice-discovery` — POV, register, anti-slop rules, character voices
4. `character-forge` — ensemble cast with Weiland arcs, referenced characters, relationship arcs
5. `outline-planner` — structural outline (Brooks four-part beat map), subplots, hooks, revelations, promises
6. `scene-card-authoring` — per-scene cards

Each surface writes a JSON artifact under `workflows/<surface>/`. `scripts/compile_bundle.py` merges those artifacts into the canonical **concept seed** (`concept_seed.json`) and **scene cards** (one JSON per chapter/scene) that the pipeline consumes.

The older monolithic `workshop_runner.py` CLI has been removed; see [workflow-kit.md](../user-guide/workflow-kit.md) for the supported authoring path.

### Current Production Default

Production now runs lean by default: `PlotArchitect -> ProseStylist -> LineWriter -> save`. The fuller relay remains available for diagnostics, benchmarks, and opt-in non-lean runs.

After a manuscript is exported, production continues through the [Manuscript Production Lifecycle](manuscript-production-lifecycle.md): GPT-5.4 full review, targeted revision, targeted cleanup, optional full-literary donor comparison, final docket pass, and deterministic validation.

### Phase B: Autonomous Pipeline

When lean mode is disabled, the pipeline processes each scene card through a **forward-only relay** (post-Stage-3 refactor — no retry loops; gates are telemetry; the save-blocker layer is the only hard-failure path):

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
LineWriter (optional line-editing pass; preserves beats, POV, characters_present, canon)
    |
    v
GateCritic (pass/fail with failure codes; advisory only, no retries)
    |
    v
QualityMetrics (code-based flags feeding polish)
    |
    v
QualityPolish (bounded expression-level polish; cannot change beats/characters)
    |
    v
Compression guard (reverts to gate-passed draft if polish < 60% of pre-polish word count)
    |
    v
FinalGate (contract check on current text; advisory_only=True, no retry)
    |
    v
CanonExpert (franchise lore validation; runs as the final continuity-editor on the current text)
    |
    v
Save-blocker layer (CHARACTER_PRESENCE_BLOCKER, CANON_BLOCKER critical/moderate, POV advisory)
    |
    +-- no blockers -> Save
    +-- blockers fire -> Quarantine (<project>/quarantine/chNN_scMM/) + abort run
    |
    v
Save -> Summarizer -> StateDiff -> ContradictionScanner -> WorldbuildingExtraction
    |
    v
CharacterSpecialist -> MilestoneGate -> ChapterGateCritic (optional)
```

Not all steps are active at every phase level. The pipeline gracefully degrades when optional components are `None`. Scenes save as `saved_clean` (no advisories fired), `saved_with_advisory` (any gate fired an advisory signal), or never save at all when a save-blocker fires and the scene is quarantined.

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
│   ├── project_paths.py           # Franchise/book/series/run path resolution
│   ├── agents/                    # Scene-path agents plus auxiliary editorial/import utilities (see src/agents/README.md)
│   ├── memory/                    # State management (SQLite, ChromaDB, context assembly)
│   ├── worldbuilding/             # Cross-project universe & lore persistence (SQLite + ChromaDB)
│   ├── rag/                       # Canon knowledge retrieval (vector DB, hybrid search)
│   ├── quality/                   # Quality metrics, milestone gates, style fingerprinting, LLM judge
│   ├── planning/                  # Story physics, scene cards, chapter blueprint generator
│   ├── export/                    # Markdown, DOCX, EPUB export
│   ├── concept_workshop/          # compliance_validator, series_manager, stress_test (canonical — workshop runner removed)
│   └── ui/                        # FastAPI backend + React frontend
├── workflows/                     # Six-surface workflow kit
│   ├── _shared/                   # Shared helpers: seed_transforms, scene_card_translator, etc.
│   ├── universe_builder/          # meta + universe_meta + premise + conflict + theme
│   ├── canon_drafter/             # canon_profile + canon_constraints + force_mechanics + terminology
│   ├── voice_discovery/           # voice_definition
│   ├── character_forge/           # ensemble_cast + relationship_arcs + referenced_characters
│   ├── outline_planner/           # structural_notes + outline + subplots + hooks + revelations
│   └── scene_card_authoring/      # per-scene cards
├── tests/                         # ~1,950 tests across 140 files
├── prompts/
│   ├── concept_workshop.md        # Legacy workshop facilitator system prompt
│   ├── stress_test_prompt.md      # Adversarial stress-test harness
│   ├── voice_definition_template.md
│   └── agent_system_prompts/      # Per-agent system prompts
├── schemas/                       # JSON schema definitions
├── templates/                     # canon_profile and voice_definition scaffolds (init_project.py)
├── data/
│   ├── franchises/                # Franchise-scoped projects and shared resources (active)
│   │   └── <franchise>/
│   │       ├── canon_db/          # Franchise RAG database (shared across books)
│   │       ├── worldbuilding.db   # Universe/lore persistence (shared across books)
│   │       ├── worldbuilding_vectors/
│   │       └── books/
│   │           └── <book>/
│   │               ├── concept_seed.json
│   │               ├── scene_cards/
│   │               └── chapter_blueprints/
│   └── eval_corpus/               # Reference chapters for quality calibration
├── output/
│   └── <franchise>/
│       └── <book>/
│           ├── runs/              # Per-run isolation
│           │   └── <run_id>/
│           │       ├── config_snapshot.yaml  # Frozen settings for reproducibility
│           │       ├── invocation.json       # CLI args + git SHA + timestamp
│           │       ├── prompts_snapshot/     # Frozen prompts for this run
│           │       └── chapters/             # Generated chapter prose
│           ├── state/             # story_state.db, chapter_memory/, run_ledger.db, sessions/
│           └── export/            # Exported manuscripts
│       └── <series>/              # Series-level shared state (when `--series` is set)
│           └── state/             # Shared state across books in the same series
└── docs/                          # Documentation
```

> **Note — legacy flat layout.** The code path in `src/project_paths.py` still resolves flat `data/projects/<slug>/` directories for ad-hoc projects and backward compatibility. No data currently ships under `data/projects/`; the shipped worked example lives under `data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/`.

### Franchise and Series Concepts

**Franchise scoping** organizes projects under a franchise namespace. Shared resources (canon databases, worldbuilding) live at the franchise level and are shared across all books within that franchise. Book-specific inputs (concept seed, scene cards) live under `data/franchises/<franchise>/books/<book>/`.

**Series linkage** allows multiple books with the same `series_id` in their concept seed metadata to share state at `output/<franchise>/<series>/state/`. This enables cross-book continuity (e.g., character arcs spanning a trilogy).

**Per-run isolation** ensures each pipeline execution gets its own output directory at `output/<franchise>/<book>/runs/<run_id>/chapters/`. A frozen config snapshot is saved alongside run output for reproducibility. The `--run-name` CLI flag allows custom run IDs; the default is auto-timestamped.

**Backward compatibility**: The CLI still resolves the flat `data/projects/<slug>/` layout for ad-hoc projects. `src/project_paths.py` detects whether `--franchise` was passed and adapts path resolution accordingly. No data currently ships under `data/projects/`.

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
