# System Overview

The AI Writers' Room is a multi-agent fiction generation system organized around a two-phase workflow.

## Two-Phase Workflow

### Phase A: Human Collaboration (Workflow Kit)

Story authoring happens through the **workflow kit** — seven per-surface skills that each own one slice of the concept:

1. `idea-session-capture` — front-door planning chat; captures north-star intent, decisions, open questions, and per-surface handoff notes
2. `universe-builder` — meta + premise + conflict + theme
3. `canon-drafter` — canon profile, canon constraints, terminology
4. `voice-discovery` — POV, register, anti-slop rules, character voices
5. `character-forge` — ensemble cast with Weiland arcs, referenced characters, relationship arcs
6. `outline-planner` — structural outline (Brooks four-part beat map), subplots, hooks, revelations, promises
7. `scene-card-authoring` — per-scene cards

`idea-session-capture` is the optional front door: it stores a loose planning chat under `workflows/idea_session/` and pre-seeds the six structural surfaces. Each structural surface writes a JSON artifact under `workflows/<surface>/`. `scripts/compile_bundle.py` merges those artifacts into the canonical **concept seed** (`concept_seed.json`) and **scene cards** (one JSON per chapter/scene) that the pipeline consumes.

The older monolithic `workshop_runner.py` CLI has been removed; see [workflow-kit.md](../user-guide/workflow-kit.md) for the supported authoring path.

### Phase B: Autonomous Pipeline

The pipeline processes each scene card through a **single lean forward pass** — no gates, no save-blocker layer, no quarantine, no retries:

```
Scene Card
    |
    v
PlotArchitect (scene card -> typed generation brief)
    |
    v
ProseStylist (generation brief + chapter packet -> draft prose)
    |
    v
LineWriter (optional single line-edit pass; preserves beats, POV, characters_present, canon)
    |
    v
RhythmValidator -> RhythmEditor (optional, flag-gated, advisory only)
    |
    v
Save (saved_clean / saved_with_advisory)
    |
    v
Post-save memory: Summarizer -> ChromaDB chapter memory -> state diff
                  -> contradiction scan -> worldbuilding extraction
```

`[...]` steps are optional. `LineWriter` runs when `runtime.lean_prose_only.line_edit.enabled` is true and an `agent_routing.line_writer` entry is configured (the shipping default). The rhythm stages are flag-gated and default-off. The drafter is expected to land the scene contract on the first pass — quality is enforced *upstream*, at planning and scene-card validation time, not by a save-time editorial gate.

Post-save stages are wrapped in broad error guards: a crash in any of them emits a warn-level event but never aborts a saved scene. Not all post-save steps are active at every phase level — the pipeline degrades gracefully when an optional dependency is `None`.

A saved scene is `saved_clean` (the normal outcome) or `saved_with_advisory` (an advisory-level signal fired). There is no failure path that prevents a scene from saving. The `quarantined` value survives in the database enum for migration compatibility but the lean pipeline never produces it.

After a manuscript is drafted, production continues through the [Manuscript Production Lifecycle](manuscript-production-lifecycle.md): export, GPT-5.4 full-manuscript review, targeted revision, targeted cleanup, optional literary donor comparison, and deterministic validation. Those passes run *after* drafting and never rewrite prose in place during a drafting run.

## Directory Structure

```
ai-writers-room/
├── README.md
├── requirements.txt
├── config/
│   ├── settings.yaml              # Deployment mode, model routing, runtime flags
│   ├── negative_constraints.yaml  # Banned phrases, AI-tell detection rules
│   └── bench/                     # Frozen routing snapshots for benchmarking
├── src/
│   ├── main.py                    # CLI entry point
│   ├── model_router.py            # Routes agent calls to local/cloud backends
│   ├── orchestrator.py            # Lean per-scene pipeline
│   ├── runtime_flags.py           # Runtime-flag merge + CLI override resolution
│   ├── run_ledger.py              # Append-only SQLite event log
│   ├── pipeline_session.py        # JSON-based session save/resume
│   ├── project_paths.py           # Franchise/book/series/run path resolution
│   ├── agents/                    # Scene-path agents plus auxiliary editorial/import utilities (see src/agents/README.md)
│   ├── pipeline/                  # Chapter packet, revision-debt store, canon guidance, preflight, final copy
│   ├── memory/                    # State management (SQLite, ChromaDB, context assembly, promise ledger)
│   ├── worldbuilding/             # Cross-project universe & lore persistence (SQLite + ChromaDB)
│   ├── rag/                       # Canon knowledge retrieval (vector DB, hybrid search)
│   ├── quality/                   # Rhythm validator, cross-chapter continuity, scene-contract checks
│   ├── planning/                  # Story physics, scene cards, chapter blueprint generator
│   ├── export/                    # Markdown, DOCX, EPUB export
│   ├── concept_workshop/          # compliance_validator, series_manager, stress_test (canonical — workshop runner removed)
│   └── ui/                        # FastAPI backend + React frontend
├── workflows/                     # Seven-surface workflow kit
│   ├── _shared/                   # Shared helpers: seed_transforms, scene_card_translator, etc.
│   ├── idea_session_capture/      # Front-door planning chat capture
│   ├── universe_builder/          # meta + universe_meta + premise + conflict + theme
│   ├── canon_drafter/             # canon_profile + canon_constraints + force_mechanics + terminology
│   ├── voice_discovery/           # voice_definition
│   ├── character_forge/           # ensemble_cast + relationship_arcs + referenced_characters
│   ├── outline_planner/           # structural_notes + outline + subplots + hooks + revelations
│   └── scene_card_authoring/      # per-scene cards
├── tests/                         # pytest suite (pipeline, workflow, UI, migration, memory)
├── prompts/                       # Per-agent system prompts + templates
├── schemas/                       # JSON schema definitions
├── templates/                     # canon_profile and voice_definition scaffolds (init_project.py)
├── data/
│   ├── franchises/                # Franchise-scoped projects and shared resources
│   │   └── <franchise>/
│   │       ├── canon_db/          # Franchise RAG database (shared across books)
│   │       ├── worldbuilding.db   # Universe/lore persistence (shared across books)
│   │       ├── worldbuilding_vectors/
│   │       ├── canon_guidance.json
│   │       └── books/
│   │           └── <book>/
│   │               ├── concept_seed.json
│   │               ├── scene_cards/
│   │               ├── chapter_blueprints/
│   │               └── workflows/
│   └── eval_corpus/               # Reference chapters for quality calibration
├── output/
│   └── <franchise>/
│       └── <book>/
│           ├── runs/              # Per-run isolation
│           │   └── <run_id>/
│           │       ├── config_snapshot.yaml  # Frozen settings for reproducibility
│           │       ├── invocation.json       # CLI args + git SHA + timestamp
│           │       ├── prompts_snapshot/     # Frozen prompts for this run
│           │       ├── chapter_packets/      # Compiled chapter packets (base + overlays)
│           │       └── chapters/             # Generated chapter prose
│           ├── state/             # story_state.db, chapter_memory/, run_ledger.db, revision_debt.db, sessions/
│           └── export/            # Exported manuscripts
│       └── <series>/              # Series-level shared state (when `--series` is set)
│           └── state/             # Shared state across books in the same series
└── docs/                          # Documentation
```

> **Note — legacy flat layout.** `src/project_paths.py` still resolves flat `data/projects/<slug>/` directories for ad-hoc projects and backward compatibility. No data currently ships under `data/projects/`; the shipped worked example lives under `data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/`.

### Franchise and Series Concepts

**Franchise scoping** organizes projects under a franchise namespace. Shared resources (canon databases, worldbuilding) live at the franchise level and are shared across all books within that franchise. Book-specific inputs (concept seed, scene cards) live under `data/franchises/<franchise>/books/<book>/`.

**Series linkage** allows multiple books with the same `series_id` in their concept seed metadata to share state at `output/<franchise>/<series>/state/`. This enables cross-book continuity (e.g., character arcs spanning a trilogy).

**Per-run isolation** ensures each pipeline execution gets its own output directory at `output/<franchise>/<book>/runs/<run_id>/chapters/`. A frozen config snapshot, an invocation record, and a prompts snapshot are saved alongside run output for reproducibility. The `--run-name` CLI flag allows custom run IDs; the default is auto-timestamped.

**Backward compatibility**: The CLI still resolves the flat `data/projects/<slug>/` layout for ad-hoc projects. `src/project_paths.py` detects whether `--franchise` was passed and adapts path resolution accordingly. No data currently ships under `data/projects/`.

## Key Abstractions

### ModelRouter (`src/model_router.py`)

All agent code communicates through the ModelRouter, which reads `config/settings.yaml` to determine which backend handles each agent's requests:

- **Local backend**: llama-server via OpenAI-compatible API
- **Cloud backend**: OpenRouter API (Claude, Gemini, DeepSeek, etc.)

The `agent_routing` section in settings.yaml maps each agent role to a backend, model tier, and parameter overrides.

### Orchestrator (`src/orchestrator.py`)

The lean per-scene pipeline controller. Runs `PlotArchitect → ProseStylist → [LineWriter] → [rhythm stages] → save`, then the post-save memory chain. All post-save and worldbuilding dependencies are optional with `None` defaults; the orchestrator degrades gracefully when they are absent.

### RunLedger (`src/run_ledger.py`)

An append-only SQLite event log. Every pipeline action emits a typed event with chapter/scene context, a `level` (`info` / `warn` / `error`), and a JSON payload. The ledger drives the web dashboard's real-time event stream.

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
| Persistent State | SQLite (story state, run ledger, revision debt, promise ledger, worldbuilding) |
| Vector Memory | ChromaDB (chapter summaries, canon DB, worldbuilding lore) |
| Export | python-docx, ebooklib |
| Web Backend | FastAPI, uvicorn, WebSockets |
| Web Frontend | React, Vite, TypeScript, TailwindCSS, Recharts |
