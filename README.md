# AI Writers' Room

> **Status:** experimental research project. Active development; APIs and pipeline shape change between commits.

A multi-agent system that writes novel-length (60–80K word) fiction. A human plans the book through a series of guided chats; a coordinated pipeline of language-model agents then drafts, line-edits, and exports the manuscript — chapter by chapter, with full audit trails.

It works for franchise fanfiction (with optional canon-aware checking) or wholly original worlds, and is configured per-franchise / per-book.

## What makes this project interesting

If you want the engineering hook before the install instructions, this is it:

- **Lean forward-pass pipeline.** One drafting pass per scene — no gates, no retry loops, no save-blocker layer. Quality is enforced *upstream* at planning time, so the drafter lands the scene contract on the first pass.
- **A single chapter-packet contract.** The drafter sees a declarative, inspectable runtime packet compiled from the blueprint, seed, and scene card — not ambient context-soup. Trusted-state stores (a promise ledger, a revision-debt store) plug into the same packet.
- **Author-led, not LLM-led, planning.** Structured surfaces (idea session, universe, canon, voice, characters, outline, scene cards) are shaped by the human first; the pipeline only drafts what the author has already settled.
- **Per-run output isolation** with full prompt + ledger snapshots — every drafting run is reproducible from inputs.

For the architectural details, see [CLAUDE.md](CLAUDE.md) and [docs/architecture/](docs/architecture/).

## How a book gets made — A to Z

The workflow has three phases. **Phase 1 (planning) is human-driven.** **Phase 2 (production) is pipeline-driven.** **Phase 3 (review and polish) is a human/pipeline collaboration.**

```text
┌─────────────────────────────────────────────────────────────────────┐
│                      PHASE 1 — PLANNING (HUMAN)                     │
│                                                                     │
│  Idea Session ──▶ Six Workflow Surfaces ──▶ compile_bundle.py       │
│  (loose chat)     (universe, canon, voice,    (validates +          │
│                    characters, outline,        merges into           │
│                    scene cards)                concept_seed.json)    │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                  PHASE 2 — PRODUCTION (PIPELINE)                    │
│                                                                     │
│  preflight ──▶ Lean drafting run ──▶ manuscript export              │
│  (deterministic   (PlotArchitect ─▶     (stitches scenes into       │
│   checks)          ProseStylist ─▶       a single manuscript        │
│                    LineWriter ─▶          plus chapter index)       │
│                    save, per scene)                                 │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│             PHASE 3 — REVIEW & POLISH (HUMAN + PIPELINE)            │
│                                                                     │
│  GPT-5.4 manuscript review ──▶ Targeted revision ──▶                │
│  Targeted cleanup ──▶ Final validation ──▶ Final export             │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 1 — Planning (human-driven)

1. **Idea Session Capture.** A loose front-door planning chat. You describe the spark — a premise, an image, a character, a relationship pressure — and the session captures decisions, open questions, and per-surface handoff notes. It does *not* commit you to a full outline yet. See [Idea Session Capture](docs/user-guide/idea-session-capture.md).

   ```bash
   python scripts/idea_session_capture.py init --title "My Novel" --franchise "My Franchise"
   ```

   When the north star is clear enough, `expand_to_surface_drafts()` pre-seeds the six structural surfaces with `<EDIT_ME …>` skeletons — partly-filled, schema-valid drafts that downstream surface chats fill in.

2. **Six workflow surfaces.** Each surface is a focused authoring chat (a Claude Code Skill, with a headless API for scripting):

   | Surface | Owns |
   |---|---|
   | `universe` | premise, conflict, theme, setting, target shape |
   | `canon` | continuity rules, canon profile, terminology |
   | `voice` | POV, register, anti-slop rules, character voices |
   | `characters` | cast, K.M. Weiland arcs (lie / ghost / want / need), relationships |
   | `outline` | Brooks four-part beat map, chapters with scene counts sized to the beat |
   | `scene_cards` | per-scene production contract (mission, turning point, characters present, key beats) |

   The surfaces inherit from the idea-session handoff notes. They are validated independently and again at compile time.

3. **`compile_bundle.py`.** Cross-surface validation + merge. The output is a canonical `concept_seed.json` plus per-scene cards under `scene_cards/`:

   ```bash
   python scripts/compile_bundle.py --franchise <slug> --book <slug>
   ```

   Treat `compile_report.json` as the first quality gate. Fix any cross-surface gaps before drafting.

### Phase 2 — Production (pipeline-driven)

4. **Preflight.** Deterministic, offline checks before you spend any tokens — schema validity, cross-surface references, canon-guidance coverage. See [`scripts/preflight_run.py`](scripts/preflight_run.py).

5. **Lean drafting run.** The shipping default is the lean per-scene path:

   ```text
   PlotArchitect ─▶ ProseStylist (drafter) ─▶ LineWriter ─▶ save
   ```

   Every scene runs this single forward pass. There are no gates, no save-blocker layer, and no retries — quality is enforced upstream at planning time. See [How the per-scene pipeline works](#how-the-per-scene-pipeline-works).

   ```bash
   python -m src.main \
     data/franchises/<franchise>/books/<book>/concept_seed.json \
     data/franchises/<franchise>/books/<book>/scene_cards \
     --franchise <franchise> --book <book> \
     --run-name first-draft --phase 5
   ```

6. **Manuscript export.** Stitch the per-scene saves into a single manuscript:

   ```bash
   python scripts/manuscript_export.py \
     --seed data/franchises/<franchise>/books/<book>/concept_seed.json \
     --run-dir output/<franchise>/<book>/runs/<run-id> \
     --export-dir output/<franchise>/<book>/export/<export-name>
   ```

### Phase 3 — Review and polish (human + pipeline)

7. **Full manuscript review.** A GPT-5.4 read of the whole manuscript produces an editorial docket — pacing flags, motif over-use, voice drift, structural problems.
8. **Targeted revision.** The docket is converted into concrete per-chapter edits, applied as a narrow rewrite pass through `scripts/patch_workflow.py`.
9. **Targeted cleanup.** A line-level cleanup pass on the revised manuscript. **This is the production master** — a full literary rewrite is available as an optional donor / comparison branch but not the default. See [Manuscript Production Lifecycle](docs/architecture/manuscript-production-lifecycle.md).
10. **Final validation.** A deterministic check on chapter count, scene count, residual assistant artefacts, and meta/process language ([`scripts/manuscript_final_validation.py`](scripts/manuscript_final_validation.py)).
11. **Final export.** The validated manuscript ships as the artifact under `output/<franchise>/<book>/export/`.

For the full operator path, see [New Manuscript Workflow](docs/user-guide/new-manuscript-workflow.md).

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+ (for the optional web dashboard)
- An [OpenRouter](https://openrouter.ai/) API key (cloud / hybrid mode), or a local [llama-server](https://github.com/ggerganov/llama.cpp) instance (local mode)

### Installation

```bash
git clone https://github.com/DinomyteHero/AI_Novel_Writing_Room.git
cd AI_Novel_Writing_Room
pip install -r requirements.txt
```

Set your OpenRouter API key (cloud or hybrid mode):

```bash
export OPENROUTER_API_KEY=your_key_here
```

### Run the bundled example

A single end-to-end pipeline run is checked into the repo as a reference. To re-draft it from inputs:

```bash
python -m src.main \
  data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json \
  data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/scene_cards \
  --franchise star-wars-legends-eu --book the-ruusan-atonement \
  --run-name first-draft --phase 5
```

The flat `data/projects/<slug>/` layout is also supported for ad-hoc projects, but the franchise-scoped layout above is what the bundled example uses.

### Start a brand-new project

The conversational front door is the idea-session capture:

```bash
python scripts/idea_session_capture.py init --title "My Novel" --franchise "My Franchise"
```

That workspace captures the early chat, decisions, and open questions, then pre-seeds the six workflow surfaces. From there, follow [New Manuscript Workflow](docs/user-guide/new-manuscript-workflow.md) for the full A-to-Z path.

### Run the web interface (optional)

```bash
# Build the frontend (first time only)
cd src/ui/frontend && npm install && npm run build && cd ../../..

# Start the server
python -m src.ui.server \
  data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/concept_seed.json
```

Open http://localhost:8000 in your browser. Live pipeline control, event stream over WebSocket, chapter / state inspectors.

## How the per-scene pipeline works

Every scene runs a single **lean forward pass**:

```text
PlotArchitect ─▶ ProseStylist ─▶ [LineWriter] ─▶ save
```

1. **PlotArchitect** reads a scene card and produces a typed generation brief.
2. **ProseStylist (drafter)** drafts prose from the brief plus the **chapter packet** — a single inspectable runtime contract compiled from the blueprint, seed, and scene card.
3. **LineWriter** is an optional single line-edit pass that preserves beats, turning point, POV, characters present, and canon while rewriting sentence-level rhythm and voice texture.
4. The prose is **saved** directly. Two optional, flag-gated rhythm stages (RhythmValidator → RhythmEditor) can run before the save; both are advisory and default-off.

There is no save-time gate, no quality-polish pass, no save-blocker layer, no quarantine, and no retry loop. Quality is enforced *upstream* — at planning and scene-card validation time — so the drafter lands the scene contract on the first pass. Every saved scene is `saved_clean` (or `saved_with_advisory` if an advisory signal fired). Every step emits typed events (level: info / warn / error) to the RunLedger.

After the scene saves, a post-save memory chain runs (Phase 2+): Summarizer → ChromaDB chapter memory → state diff → contradiction scan → worldbuilding extraction. Each post-save stage is wrapped in an error guard — a crash there never aborts a saved scene.

Pipeline depth is selectable with `--phase 1..5`:

| Pipeline depth | Adds |
|----------------|------|
| 1 | Lean drafting: PlotArchitect → ProseStylist → [LineWriter] → save |
| 2 | Story state (SQLite), chapter memory (ChromaDB), canon RAG, and the post-save memory chain |
| 3 | No additional subsystems beyond Phase 2 |
| 4 | Session persistence (save / resume), export, scene-card generation |
| 5 | Chapter blueprint auto-generation |

Optional flag-gated tooling, off by default: the revision-debt store, the promise ledger, the rhythm validator / editor, and the cross-chapter continuity validator. Post-production passes (GPT-5.4 manuscript review, literary polish) run after a draft, not during it. See [Benchmarking](docs/development/benchmarking.md).

## Directory Structure

**Inputs (franchise-scoped):**
```
data/franchises/<franchise>/books/<book>/
├── concept_seed.json          # Story concept with canon_profile
├── scene_cards/               # Per-chapter scene cards
├── chapter_blueprints/        # Per-chapter planning artifacts
└── workflows/                 # Authored surface artifacts + idea session
```

**Inputs (flat, backward-compatible for ad-hoc projects):**
```
data/projects/<slug>/
├── concept_seed.json
└── scene_cards/
```

**Outputs (run-scoped):**
```
output/<franchise>/<book>/
├── runs/<run_id>/             # Per-scene saves, chapter packets, prompts snapshot, ledger
├── export/<export_name>/      # Stitched manuscripts
└── state/                     # SQLite + ChromaDB stores
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
| [New Manuscript Workflow](docs/user-guide/new-manuscript-workflow.md) | End-to-end path from idea chat to final validated export |
| [Idea Session Capture](docs/user-guide/idea-session-capture.md) | Guided planning chat capture before the six workflow surfaces |
| [Workflow Kit](docs/user-guide/workflow-kit.md) | Six-surface concept authoring (universe / canon / voice / characters / outline / scene cards) |
| [Final Copy Pipeline](docs/user-guide/final-copy-pipeline.md) | Scene-level literary-copy diagnostics and donor-polish lane |
| [Web Interface](docs/user-guide/web-interface.md) | Dashboard walkthrough |
| **Architecture** | |
| [System Overview](docs/architecture/system-overview.md) | Components, data flow, directory structure |
| [Agent Pipeline](docs/architecture/agent-pipeline.md) | The lean multi-agent generation loop |
| [Manuscript Production Lifecycle](docs/architecture/manuscript-production-lifecycle.md) | Lean production, full review, targeted cleanup, optional literary donor branch, final validation |
| [Memory & State](docs/architecture/memory-and-state.md) | SQLite, ChromaDB, knowledge layers |
| [Quality & Revision](docs/architecture/quality-and-revision.md) | The lean quality model: upstream enforcement, advisory telemetry, post-production review |
| **Reference** | |
| [API Reference](docs/reference/api-reference.md) | FastAPI endpoints and WebSocket events |
| [Configuration](docs/reference/configuration.md) | settings.yaml, runtime flags, constraints |
| [Schemas](docs/reference/schemas.md) | JSON schema definitions |
| **Development** | |
| [Contributing](docs/development/contributing.md) | Dev setup, testing, code style |
| [Adding Agents](docs/development/adding-agents.md) | How to extend the agent system |
| [Benchmarking](docs/development/benchmarking.md) | Prose-model bench, bench configs, A/B methodology |

Historical implementation briefs and superseded design docs are preserved in [docs/archive/](docs/archive/).

## Tests

```bash
pytest                              # Run the full suite
pytest -k "test_orchestrator"       # Run a subset
```

## A note on the bundled example output

The repo ships with one end-to-end pipeline run as a reference: **The Ruusan Atonement**, a fan-fiction concept set in the Star Wars Legends Expanded Universe (New Sith Wars era). The artifact at [`output/star-wars-legends-eu/the-ruusan-atonement/export/production-lean-full-20260425-010838-targeted-revision-1/`](output/star-wars-legends-eu/the-ruusan-atonement/export/production-lean-full-20260425-010838-targeted-revision-1/) is a 28-chapter, ~113,000-word manuscript produced by running the pipeline all the way through draft → GPT-5.4 review → targeted revision.

**It is a base test of the pipeline, not an example of polished storytelling.** The point of the bundled run is to demonstrate that the system can take guided author planning all the way through to a reviewed, validated long-form manuscript — not to ship a novel for reading. Treat it as a reference output, not an editorial benchmark.

The pipeline inputs that produced it are checked in at [`data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/`](data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/), so the run is reproducible from the inputs alone.

## License

Apache License 2.0 — see [LICENSE](LICENSE).

The license covers the pipeline software. It does not grant rights in any third-party franchise material that the bundled example or evaluation corpus happens to reference; see [DISCLAIMER](DISCLAIMER.md) for the non-commercial fan-content posture and rightsholder takedown contact.

## Connect

Built by **Louis Bouwer**. If this project is useful to you, or you'd like to chat about multi-agent fiction generation, language-model orchestration, or the engineering behind the lean pipeline, please feel free to say hi and connect on LinkedIn:

[LinkedIn Profile Link](https://www.linkedin.com/in/louisbouwer3/)
