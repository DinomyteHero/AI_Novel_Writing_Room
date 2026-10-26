# Read-Only Web Console

The web app is a **read-only review console**, not a pipeline controller.
Drafting, review actions, and export run through the CLI. The server exposes
saved chapter prose and run-ledger events only.

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
| `--phase` | `1` | Informational; the console is phase-independent |
| `--dev` | off | Enable auto-reload for development |

Alternatively:

```bash
python -m src.main <concept_seed> <scene_cards_dir> --server
```

The server binds to loopback by default and has no authentication. Do not
expose it with `--host 0.0.0.0`.

## Pages

The console has two views:

- **Book** — saved scenes, word counts, and links to the reader.
- **Reader** — one chapter/scene of prose.

There is no pipeline control, quality dashboard, raw story-state browser,
worldbuilding CMS, scene-card editor, or export page. Those were removed so the
web app does not duplicate the CLI or expose internals.

## API

The read-only API lives at `/api/`:

```text
GET /api/health
GET /api/chapters
GET /api/chapters/{chapter}/{scene}
GET /api/manuscript/summary
GET /api/ledger/events
GET /api/ledger/events/latest
```

See the [API Reference](../reference/api-reference.md).
