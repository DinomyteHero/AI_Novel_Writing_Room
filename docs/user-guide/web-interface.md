# Web Interface

The AI Writers' Room includes a web dashboard built with FastAPI (backend) and React (frontend) for real-time pipeline monitoring and control.

## Starting the Server

```bash
python -m src.ui.server <concept_seed> [options]
```

| Flag | Default | Description |
|------|---------|-------------|
| `concept_seed` | required | Path to concept seed JSON |
| `--config` | `config/settings.yaml` | Configuration file path |
| `--host` | `127.0.0.1` | Server host |
| `--port` | `8000` | Server port |
| `--phase {1,2,3,4,5}` | `4` | Pipeline phase |
| `--dev` | off | Enable auto-reload for development |

> **Preview mode.** The web UI is a preview surface. Consecutive runs through the dashboard are **not** run-isolated and can overwrite chapter output; the dashboard shows an amber banner to this effect. Some endpoints predate the 2026-05-19 lean teardown and still expose fields for removed subsystems (see [API Reference](../reference/api-reference.md)). For production-quality output use the CLI (`python -m src.main`) with `--run-name`, which writes to a per-run directory under `output/<franchise>/<book>/runs/<run_id>/`.

Alternatively, use the main CLI with `--server`:

```bash
python -m src.main <concept_seed> <scene_cards_dir> --server
```

## Dashboard Pages

The React frontend provides these pages:

### Pipeline Control

Start, pause, and resume pipeline runs. The form exposes a small, fixed surface:
- Concept seed path (optional override)
- Scene cards directory (optional override)
- Phase selection (1–5)

The REST API (`POST /api/pipeline/start`) accepts additional fields (`chapter` filter, blueprint controls, franchise/book/series scoping) that the form does not surface; use the CLI or hit the API directly for those. See the [API Reference](../reference/api-reference.md).

### Event Log

Real-time event stream showing every pipeline action as it happens. Events are delivered via WebSocket and carry a `level` (`info` / `warn` / `error`). They include:
- Agent start/complete events (PlotArchitect, ProseStylist, LineWriter)
- Scene-save events (`lean_prose_only_saved`)
- Chapter-packet compile events
- Post-save memory events (summarizer, state diff, contradiction scan)

### Chapter Viewer

Browse generated chapters with formatted prose. View the full chapter text and per-scene word count.

### Story State

Explore the SQLite story state (Phase 2+):
- Characters with locations, emotional states, and arcs
- Character relationships
- Knowledge layers (truth, belief, narrative exposure)
- Plot thread status and urgency
- Timeline entries
- Chekhov's guns (unfired items)

## WebSocket Events

The dashboard connects to `ws://localhost:8000/ws/pipeline` for real-time events. Events are JSON objects matching the RunLedger format:

```json
{
  "event_type": "agent_complete",
  "chapter_number": 1,
  "scene_number": 1,
  "agent_role": "prose_stylist",
  "payload": { "level": "info" },
  "timestamp": "2026-05-19T10:30:00"
}
```

## API Access

All dashboard data is available via REST API at `/api/`. See the [API Reference](../reference/api-reference.md) for the full endpoint list.
