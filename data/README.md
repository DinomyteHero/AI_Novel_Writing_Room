# `data/` — Canonical Inputs

This directory holds **tracked, canonical inputs** for the pipeline: story concept seeds, scene cards, chapter blueprints, and evaluation references. Runtime output (manuscripts, session state, worldbuilding databases, run ledgers) lives under `output/` and is gitignored.

If you're looking for "where does my run's output go?" — it's `output/{franchise}/{book}/runs/{run_id}/`, not here.

## Canonical layout (tracked)

```
data/
├── franchises/                                  # Story inputs, franchise-scoped
│   └── {franchise}/
│       ├── franchise_meta.json                  # Franchise display name, canon status
│       └── books/
│           └── {book}/
│               ├── concept_seed.json            # Story-wide truth (cast, arcs, hooks, …)
│               ├── scene_cards/                 # One JSON per scene (chapter_NN_scene_MM.json)
│               └── chapter_blueprints/          # Chapter-level plans (chapter_NN.json)
├── eval_corpus/                                 # Quality calibration reference
│   ├── chapter_0{1,2,3}_reference.md
│   └── eval_rubric.json
└── README.md                                    # This file
```

Authoritative path resolver: [`src/project_paths.py`](../src/project_paths.py). `ProjectPaths.from_concept_seed(...)` is the entry point — never construct these paths by string concatenation in new code.

## What's NOT in `data/` (runtime, gitignored)

| Kind | Location |
|---|---|
| Per-run manuscripts, config snapshot, prompt snapshot | `output/{franchise}/{book}/runs/{run_id}/` |
| Accumulated story state, chapter memory, run ledger | `output/{franchise}/{book}/state/` (or `output/{franchise}/{series}/state/` if series-scoped) |
| Fallback for runs without a `ProjectPaths` context | `output/_fallback/` |
| Worldbuilding databases (SQLite + Chroma) | `data/franchises/{franchise}/worldbuilding.db`, `data/franchises/{franchise}/worldbuilding_vectors/` |
| Canon retrieval index (Chroma) | `data/franchises/{franchise}/canon_db/` |

The worldbuilding and canon databases live under `data/franchises/` because they're franchise-scoped rather than per-run; they're still gitignored.

## Legacy paths — do not use

Earlier iterations of the codebase wrote runtime artifacts at the `data/` root. If your local checkout has any of these, they are safe to delete:

- `data/manuscripts/` — superseded by `output/{franchise}/{book}/runs/{run_id}/chapters/`
- `data/sessions/` — superseded by per-run session state under `output/`
- `data/worldbuilding_vectors/` — superseded by franchise-scoped `data/franchises/{franchise}/worldbuilding_vectors/`
- `data/worldbuilding.db` — superseded by franchise-scoped `data/franchises/{franchise}/worldbuilding.db`
- `data/universes/` — pre-"franchise" naming; no longer used
- `data/models/` — never populated; scheduled for removal
- `data/projects/{slug}/` — pre-franchise flat layout. `ProjectPaths.from_concept_seed_path()` still accepts it for backward compat, but new projects go under `franchises/`
- `data/export/` — superseded by `output/{franchise}/{book}/exports/`
- `data/canon_dbs/` — superseded by franchise-scoped path

## Cleaning legacy artifacts

Safe to run if you have no in-progress pipeline session that needs the local files:

```bash
cd "C:/Users/lbouw/OneDrive/Documents/Github Repos/AI_Novel_Writing_Room"

# Empty / never-used dirs — safe
rm -rf data/manuscripts data/models data/universes data/export data/canon_dbs

# Runtime caches — regenerated on next run
rm -rf data/worldbuilding_vectors data/worldbuilding.db

# Session checkpoints — deleting forfeits resume ability for those sessions
rm -rf data/sessions

# Legacy test fixtures (workshop runner creates them on demand)
rm -rf data/projects
```

After cleanup, `data/` should contain only `franchises/`, `eval_corpus/`, and this `README.md`.

## Note on default paths

A number of fallback defaults in `src/` historically wrote to `data/X` when `ProjectPaths` was not supplied (tests, ad-hoc scripts, UI fallbacks). After the cleanup those defaults route to `output/_fallback/X` instead — so running `python -c "from src.pipeline_session import PipelineSession; PipelineSession()"` no longer creates a `data/sessions/` directory. If you rely on the old defaults, pass an explicit path or construct a `ProjectPaths` instance.
