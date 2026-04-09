# Documentation

This directory contains all project documentation, organized by purpose.

## Structure

```
docs/
├── README.md                 # This file
├── getting-started.md        # Installation, configuration, first run
├── user-guide/
│   ├── cli-usage.md          # CLI commands and flags
│   ├── web-interface.md      # Web dashboard walkthrough
│   └── concept-workshop.md   # Interactive story planning guide
├── architecture/
│   ├── system-overview.md    # Components, data flow, directory layout
│   ├── agent-pipeline.md     # Multi-agent generation loop
│   ├── memory-and-state.md   # SQLite state, ChromaDB, knowledge layers
│   └── quality-and-revision.md # Metrics, revision bands, milestone gates
├── reference/
│   ├── api-reference.md      # FastAPI endpoints and WebSocket events
│   ├── configuration.md      # YAML configuration files
│   └── schemas.md            # JSON schema definitions
├── development/
│   ├── contributing.md       # Dev setup, testing, code conventions
│   ├── adding-agents.md      # How to create new agents
│   └── future-work.md        # Deferred items / known follow-ups backlog
└── archive/
    └── ...                   # Historical implementation briefs
```

## Categories

- **Getting Started** -- Installation and your first pipeline run
- **User Guides** -- Task-oriented guides for each interface (CLI, web, workshop)
- **Architecture** -- How the system is designed and why
- **Reference** -- Lookup material (API endpoints, config options, schemas)
- **Development** -- How to contribute and extend the system
- **Archive** -- Historical implementation briefs from the build phases (not current documentation)
