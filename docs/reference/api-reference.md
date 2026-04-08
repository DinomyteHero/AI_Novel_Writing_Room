# API Reference

The web interface exposes a REST API at `/api/` and a WebSocket endpoint for real-time events. The backend is built with FastAPI (`src/ui/app.py`).

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
| phase | int | 4 | Pipeline phase (1-4) |
| no_revision | bool | false | Skip revision pipeline |
| no_milestones | bool | false | Skip milestone gates |
| judge | bool | false | Run LLM judge evaluation |
| chapter | int? | null | Generate only this chapter |

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

## CORS

The server allows requests from:
- `http://localhost:5173` (Vite dev server)
- `http://localhost:3000`
- `http://127.0.0.1:5173`
- `http://127.0.0.1:3000`
