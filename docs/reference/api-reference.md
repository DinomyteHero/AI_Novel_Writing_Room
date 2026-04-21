# API Reference

The web interface exposes a REST API at `/api/` and a WebSocket endpoint for real-time events. The backend is built with FastAPI (`src/ui/app.py`).

## ProjectPaths

`src/project_paths.py` resolves all file paths for a project. Construct via `ProjectPaths.from_concept_seed(seed, run_id=...)` or `ProjectPaths.from_concept_seed_path(path, run_id=...)`. Key slugs and properties (full list in [src/project_paths.py](../../src/project_paths.py)):

### Slugs (constructor arguments)

| Slug | Description |
|------|-------------|
| `project_slug` | Book identifier (kebab-case). Resolves the book directory at `data/franchises/<franchise>/books/<project_slug>/`. The `--book` CLI flag (and `book` API field) set this. |
| `franchise_slug` | Franchise namespace (e.g., `star-wars-legends-eu`). Resolves to `data/franchises/<franchise_slug>/`. |
| `series_slug` | Optional series identifier. When set, state is shared at `output/<franchise>/<series>/state/`. |
| `cosmology_slug` | Optional meta-universe slug. Resolves to `data/cosmologies/<cosmology_slug>/`. |
| `run_id` | Per-run identifier (auto-timestamped, or custom via `--run-name`). |

### Path properties

| Property | Description |
|----------|-------------|
| `book_dir` | Book input directory (`data/franchises/<franchise>/books/<project_slug>/`). |
| `concept_seed_path` | `<book_dir>/concept_seed.json`. |
| `scene_cards_dir` | `<book_dir>/scene_cards/`. |
| `workflows_dir` | `<book_dir>/workflows/` — per-surface artifact directory (workflow kit). |
| `state_dir` | Accumulated state (book-level, or series-level when `series_slug` is set). |
| `story_state_db`, `chapter_memory_dir`, `run_ledger_db` | State-scoped SQLite/ChromaDB paths. |
| `run_dir` | Per-run output directory (`output/<franchise>/<book>/runs/<run_id>/`) — `None` when no `run_id`. |
| `manuscripts_dir` | Generated chapter prose. With a `run_id`: `<run_dir>/chapters/`; otherwise falls back to `<book_output>/chapters/`. |
| `config_snapshot_path` | `<run_dir>/config_snapshot.yaml` — frozen settings for this run. |
| `sessions_dir` | Session checkpoint directory (under `run_dir` when a run is active). |
| `export_dir` | `<book_output>/export/`. |
| `franchise_dir` | Top-level franchise directory. |
| `canon_dbs_dir` | Franchise-level canon ChromaDB root. |
| `worldbuilding_db` | Franchise-level worldbuilding SQLite path. |
| `worldbuilding_vectors_dir` | Franchise-level worldbuilding vectors directory. |

The `universe_*` and `project_root` properties are backward-compat aliases for the franchise-scoped and `book_dir` properties respectively. `display_name` returns a human-readable `franchise/[series]/book@run_id` identifier for log lines.

### CLI Flags

| Flag | Description |
|------|-------------|
| `--franchise` | Franchise namespace (replaces deprecated `--universe-id`) |
| `--book` | Book identifier (replaces deprecated `--project-id`) |
| `--series` | Series identifier for cross-book shared state |
| `--run-name` | Custom run ID (default: auto-timestamped) |

The deprecated `--universe-id` and `--project-id` flags still work but emit a deprecation warning.

## Health Check

```
GET /api/health
```

Returns deployment mode, pipeline phase, and current pipeline state.

---

## Pipeline Control

### Start Pipeline

```
POST /api/pipeline/start
```

Start a pipeline run as a background task.

**Request body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| concept_seed_path | string? | null | Override concept seed path |
| scene_cards_dir | string? | null | Override scene cards directory |
| phase | int | 4 | Pipeline phase (1–5). Phases 6–7 are runtime-orthogonal and activate via other fields / `--runtime-flag` overrides. |
| raw_draft | bool | false | Skip Quality Polish + Final Gate; save the Scene-Gate-passed draft |
| no_milestones | bool | false | Skip milestone gates |
| judge | bool | false | Run LLM judge evaluation |
| chapter | int? | null | Generate only this chapter |
| franchise | string? | null | Franchise namespace |
| book | string? | null | Book identifier |
| series | string? | null | Series identifier for shared state |
| run_name | string? | null | Custom run ID (default: auto-timestamped) |
| generate_blueprints | bool | true | Phase 5: auto-generate missing chapter blueprints when `phase >= 5`. Set `false` to skip generation and only use hand-authored blueprints. |
| regenerate_blueprints | bool | false | Phase 5: overwrite existing blueprints. Default preserves hand-authored files. |
| strict_lore | bool | false | Phase 7.2: promote high-severity `LoreConflictDetector` flags to blocking. Advisory by default — flags land in the run ledger but don't fail the scene. |
| universe_id | string? | null | Deprecated alias for `franchise`. Kept for existing frontend clients; new callers should send `franchise`. |
| project_id | string? | null | Deprecated alias for `book`. Kept for existing frontend clients; new callers should send `book`. |

**Response:** `{ session_id, status, total_chapters }`

### Get Pipeline Status

```
GET /api/pipeline/status
```

**Response:** `{ state, session_id, current_chapter, total_chapters, completed_chapters, error, milestone_info }`

Pipeline states: `idle`, `running`, `paused`, `milestone_pending`, `completed`, `failed`

### Pause Pipeline

```
POST /api/pipeline/pause
```

Pauses after the current chapter completes.

### Resume Pipeline

```
POST /api/pipeline/resume
```

Resumes a paused pipeline.

### Get Pipeline Results

```
GET /api/pipeline/results
```

Returns all chapter results from the current/most recent run.

### Approve Milestone

```
POST /api/pipeline/milestone/approve
```

**Request body:** `{ should_continue: bool }`

Approve or reject a milestone gate.

---

## Chapters

### List Chapters

```
GET /api/chapters
```

Returns all generated chapters with metadata (word count, quality scores).

### Get Chapter Text

```
GET /api/chapters/{chapter_num}/{scene_num}
```

Returns full prose for a chapter/scene.

**Response:** `{ chapter_number, scene_number, prose, word_count }`

### Get Chapter Metrics

```
GET /api/chapters/{chapter_num}/{scene_num}/metrics
```

Returns quality metrics from the chapter log.

### Get Chapter Evaluation

```
GET /api/chapters/{chapter_num}/{scene_num}/evaluation
```

Returns gate critic and LLM judge evaluations.

**Response:** `{ chapter_number, scene_number, gate_evaluation, judge_evaluation }`

### Get Manuscript Summary

```
GET /api/manuscript/summary
```

**Response:** `{ total_word_count, chapter_count, chapters: [...] }`

### Export Manuscript

```
POST /api/export
```

**Request body:** `{ formats: ["md", "docx", "epub"], output_dir: "data/export" }`

**Response:** `{ exports: { md: "path", docx: "path", epub: "path" } }`

### Download Export

```
GET /api/export/download/{fmt}
```

Download an exported file. `fmt` is one of: `md`, `docx`, `epub`.

---

## Story State (Phase 2+)

All story state endpoints return 503 if Phase 2 components aren't initialized.

### Get Characters

```
GET /api/state/characters
```

### Get Character Detail

```
GET /api/state/characters/{character_id}
```

Returns character data with relationships and knowledge arrays.

### Get Plot Threads

```
GET /api/state/plot-threads
```

### Get Timeline

```
GET /api/state/timeline?chapter=N
```

Optional `chapter` query parameter filters entries.

### Get Chekhov's Guns

```
GET /api/state/chekhov-guns
```

Returns all unfired Chekhov's guns.

### Get Character Knowledge

```
GET /api/state/knowledge/{character_id}?layer=truth
```

Optional `layer` parameter: `truth`, `belief`, `narrative_exposure`.

### Get Dramatic Irony

```
GET /api/state/dramatic-irony?chapter=1
```

Returns situations where the reader knows things characters don't.

---

## Scene Cards

### List Scene Cards

```
GET /api/scene-cards
```

### Get Scene Card

```
GET /api/scene-cards/{chapter_num}/{scene_num}
```

### Generate Scene Cards

```
POST /api/scene-cards/generate
```

Generates scene cards from the loaded concept seed and saves them.

**Response:** `{ scene_cards: [...], count: int }`

### Get Concept Seed

```
GET /api/concept-seed
```

---

## Run Ledger

### Query Events

```
GET /api/ledger/events?event_type=gate_pass&chapter=1&agent_role=gate_critic&limit=50
```

All query parameters are optional. `limit` range: 1-500, default: 50.

### Get Latest Events

```
GET /api/ledger/events/latest?limit=20
```

`limit` range: 1-100, default: 20.

### Get Ledger Summary

```
GET /api/ledger/summary
```

**Response:** `{ total_events, events_by_type, gate_pass_count, gate_fail_count, gate_pass_rate }`

---

## Sessions

### List Sessions

```
GET /api/sessions
```

### Get Session

```
GET /api/sessions/{session_id}
```

### Delete Session

```
DELETE /api/sessions/{session_id}
```

---

## WebSocket

### Pipeline Event Stream

```
WebSocket ws://localhost:8000/ws/pipeline
```

Streams pipeline events in real-time. Events are JSON objects:

```json
{
  "event_type": "agent_complete",
  "chapter_number": 1,
  "scene_number": 1,
  "agent_role": "prose_stylist",
  "payload": { ... },
  "timestamp": "2026-04-08T10:30:00"
}
```

Event types match those logged to the RunLedger (see [Agent Pipeline](../architecture/agent-pipeline.md#event-logging)).

---

## Worldbuilding

All worldbuilding endpoints are prefixed with `/api/worldbuilding/` and return 503 if the worldbuilding service isn't initialized.

### Universes

```
POST   /api/worldbuilding/universes                    # Create universe
GET    /api/worldbuilding/universes                    # List all (with entry counts)
GET    /api/worldbuilding/universes/{id}               # Get detail + inheritance chain
DELETE /api/worldbuilding/universes/{id}               # Delete (cascade)
```

### Lore Entries

```
GET    /api/worldbuilding/universes/{id}/lore          # List/search (?category=&status=&search=)
POST   /api/worldbuilding/universes/{id}/lore          # Create entry
GET    /api/worldbuilding/lore/{entry_id}              # Get entry + relations
PUT    /api/worldbuilding/lore/{entry_id}              # Update entry
DELETE /api/worldbuilding/lore/{entry_id}              # Delete entry
POST   /api/worldbuilding/lore/{entry_id}/promote      # Promote provisional -> canonical
POST   /api/worldbuilding/lore/{entry_id}/deprecate    # Mark deprecated
POST   /api/worldbuilding/lore/bulk-promote            # Promote multiple (body: {entry_ids: [...]})
```

### Relations

```
POST   /api/worldbuilding/lore/relations                                   # Create relation
GET    /api/worldbuilding/lore/{entry_id}/relations                        # Get relations
DELETE /api/worldbuilding/lore/relations/{source_id}/{target_id}/{type}    # Delete relation
```

### Character Affiliations

```
POST   /api/worldbuilding/lore/affiliations                          # Create affiliation
GET    /api/worldbuilding/lore/affiliations/{character_id}           # Get affiliations
DELETE /api/worldbuilding/lore/affiliations/{character_id}/{entry_id} # Remove affiliation
```

### Terminology

```
GET    /api/worldbuilding/universes/{id}/terminology   # Full glossary (walks parent chain)
```

### Project Binding

```
POST   /api/worldbuilding/projects/{project_id}/bind-universe  # Bind project to universe
GET    /api/worldbuilding/projects/{project_id}/universe        # Get bound universe
```

### Import & Extraction

```
POST   /api/worldbuilding/universes/{id}/import-seed       # LLM-assisted concept seed import
POST   /api/worldbuilding/universes/{id}/extract-chapter   # LLM-assisted chapter extraction
GET    /api/worldbuilding/universes/{id}/pending            # List provisional entries for review
```

### Maintenance

```
POST   /api/worldbuilding/admin/reconcile?universe_id=     # Trigger orphan reconciliation
```

---

## CORS

The server allows requests from:
- `http://localhost:5173` (Vite dev server)
- `http://localhost:3000`
- `http://127.0.0.1:5173`
- `http://127.0.0.1:3000`
