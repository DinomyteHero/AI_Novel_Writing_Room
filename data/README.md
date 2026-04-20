# `data/` — Canonical Inputs

This directory holds **tracked, canonical inputs** for the pipeline: story concept seeds, scene cards, chapter blueprints, and evaluation references.

Runtime output lives under `output/`, which has a deliberately mixed status:

- **Gitignored** (per-user runtime state): `output/*/*/state/` and `output/_fallback/`.
- **Tracked by default** (canonical reference material): `output/<franchise>/<book>/runs/bench-*/` bench runs plus their `BENCH_*.md` summary analyses, `runs/_archive/` historical bench captures, and any user-named run directory under `runs/` unless you ignore it locally. These are intentional — the bench comparisons that drove routing decisions in `config/settings.yaml` live here (see [`docs/development/benchmarking.md`](../docs/development/benchmarking.md)) and are read as canonical examples.
- **Unmanaged** (neither ignored nor heavily tracked): `output/<franchise>/<book>/quarantine/` and `output/<franchise>/<book>/export/`. These are almost always per-user runtime state; add them to a personal `.git/info/exclude` if your workflow produces them regularly.

If you're looking for "where does my run's output go?" — it's `output/{franchise}/{book}/runs/{run_id}/`, not here. If you don't want that run in git, name it something other than `bench-*` and ignore the path locally.

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
| Per-run manuscripts, config snapshot, prompt snapshot | `output/{franchise}/{book}/runs/{run_id}/` | Tracked by default — intentional for `bench-*` and `_archive/`, opt-in for personal named runs |
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

# Per-user personal runs under output/<franchise>/<book>/runs/.
# Keeps bench-* runs and _archive/ (canonical reference), removes the rest.
find output -type d -path 'output/*/*/runs/*' \
    ! -name 'bench-*' ! -name '_archive' ! -path '*/_archive/*' \
    -maxdepth 4 -exec rm -rf {} +

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
