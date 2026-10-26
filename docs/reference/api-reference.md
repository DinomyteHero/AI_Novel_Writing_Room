# API Reference

The web app is a read-only viewer. The API exposes saved prose and ledger
events; it does not start pipelines, edit state, or export manuscripts.

Base URL: `http://127.0.0.1:8000/api`

## Health

`GET /health`

```json
{
  "status": "ok",
  "deployment_mode": "cloud",
  "phase": 1,
  "pipeline_state": "read_only"
}
```

## Chapters

`GET /chapters`

Returns saved scene files from the active manuscripts directory.

```json
{
  "chapters": [
    {
      "chapter_number": 1,
      "scene_number": 1,
      "word_count": 3419,
      "path": "output/.../chapters/chapter_01_scene_01.md"
    }
  ]
}
```

`GET /chapters/{chapter}/{scene}`

Returns the full prose for one scene.

`GET /manuscript/summary`

Returns total words, chapter count, and per-scene word counts.

## Ledger

`GET /ledger/events?event_type=&chapter=&agent_role=&limit=`

`GET /ledger/events/latest?limit=`

Events use the `RunLedger` shape:

```json
{
  "id": 1,
  "event_type": "lean_prose_only_saved",
  "chapter_number": 1,
  "scene_number": 1,
  "agent_role": null,
  "payload": { "word_count": 3419, "level": "info" },
  "timestamp": "2026-10-26T11:00:00+00:00"
}
```

## Removed Endpoints

The former pipeline-control, worldbuilding-CRUD, story-state, scene-card,
session, export, and WebSocket endpoints were removed. Use the CLI:

```bash
python -m src.main <concept_seed> <scene_cards_dir> [options]
python scripts/preflight_run.py --franchise <fr> --book <bk>
python scripts/manuscript_export.py --seed <seed> --run-dir <run>
```
