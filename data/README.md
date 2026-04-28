# `data/` — Canonical Inputs

This directory holds **tracked, canonical inputs** for the pipeline: story concept seeds, scene cards, chapter blueprints, and evaluation references.

Runtime output lives under `output/`, which has a deliberately mixed status:

- **Gitignored** (per-user runtime state): `output/*/*/state/`, `output/*/*/runs/`, `output/_fallback/`, and `output/runs-logs/`. Pipeline runs and per-run state land here and are never committed by default. Copy any evidence worth sharing into `docs/` (e.g. `docs/editorial/<topic>.md`) before relying on it long-term.
- **Tracked when committed** (finalized manuscripts): `output/<franchise>/<book>/export/` holds publishable manuscript builds (`chapter_index.md` + per-chapter markdown). Commit only when a build is worth preserving as a reference output.
- **Unmanaged**: `output/<franchise>/<book>/quarantine/` is per-user save-blocker output. Add it to a personal `.git/info/exclude` if your workflow produces it regularly.

If you're looking for "where does my run's output go?" — it's `output/{franchise}/{book}/runs/{run_id}/`, gitignored by default. Bench captures and historical archives that used to live there have been pulled out of the tree as regenerable artifacts; rerun them from `scripts/bench_prose_models.py` if you need the comparisons.

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

## What lives outside `data/` and what's gitignored

| Kind | Location | Git status |
|---|---|---|
| Per-run manuscripts, config snapshot, prompt snapshot | `output/{franchise}/{book}/runs/{run_id}/` | **Gitignored** (`output/*/*/runs/`). Force-add only if you have a specific reason to commit a run — the default posture is regenerate-on-demand. |
| Accumulated story state, chapter memory, run ledger | `output/{franchise}/{book}/state/` (or `output/{franchise}/{series}/state/` if series-scoped) | **Gitignored** (`output/*/*/state/`) |
| Fallback for runs without a `ProjectPaths` context | `output/_fallback/` | **Gitignored** |
| Quarantined scenes (save-blocker aborts) | `output/{franchise}/{book}/quarantine/` | Tracked if committed — usually per-user, consider a local exclude |
| Exported manuscripts (md / docx / epub) | `output/{franchise}/{book}/export/` | Tracked if committed — usually per-user, consider a local exclude |
| Worldbuilding databases (SQLite + Chroma) | `data/franchises/{franchise}/worldbuilding.db`, `data/franchises/{franchise}/worldbuilding_vectors/` | **Gitignored** via config paths |
| Canon retrieval index (Chroma) | `data/franchises/{franchise}/canon_db/` | **Gitignored** |

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

## Cleaning local artifacts

Safe to run if you have no in-progress pipeline session that needs the local files:

```bash
# From the repo root.

# --- Legacy data/ dirs (pre-franchise layout) ---

# Empty / never-used dirs — safe
rm -rf data/manuscripts data/models data/universes data/export data/canon_dbs

# Runtime caches — regenerated on next run
rm -rf data/worldbuilding_vectors data/worldbuilding.db

# Session checkpoints — deleting forfeits resume ability for those sessions
rm -rf data/sessions

# Pre-franchise flat projects
rm -rf data/projects

# --- Runtime state + per-user run output ---

# Gitignored runtime state (safe; regenerated by the pipeline)
rm -rf output/*/*/state/ output/_fallback/

# Per-user runs (everything under runs/ is gitignored — safe to nuke).
rm -rf output/*/*/runs/

# Per-user export/quarantine artifacts
rm -rf output/*/*/export/ output/*/*/quarantine/

# --- Python + tooling caches ---

find . -type d -name __pycache__ -prune -exec rm -rf {} +
rm -rf .pytest_cache htmlcov .coverage coverage.xml

# --- Abandoned worktrees (Claude Code) ---

# Inspect first: git worktree list
# Then for each unwanted path:
#   git worktree remove .claude/worktrees/<name>
```

After cleanup, `data/` should contain only `franchises/`, `eval_corpus/`, and this `README.md`. `output/` should contain only tracked canonical bench material (plus whatever state/ the next run regenerates).

## Note on default paths

A number of fallback defaults in `src/` historically wrote to `data/X` when `ProjectPaths` was not supplied (tests, ad-hoc scripts, UI fallbacks). After the cleanup those defaults route to `output/_fallback/X` instead — so running `python -c "from src.pipeline_session import PipelineSession; PipelineSession()"` no longer creates a `data/sessions/` directory. If you rely on the old defaults, pass an explicit path or construct a `ProjectPaths` instance.
