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
│   └── quality-and-revision.md # Metrics, QualityPolish, and milestone gates (historical filename)
├── reference/
│   ├── api-reference.md      # FastAPI endpoints and WebSocket events
│   ├── configuration.md      # YAML configuration files
│   └── schemas.md            # JSON schema definitions
├── development/
│   ├── contributing.md          # Dev setup, testing, code conventions
│   ├── adding-agents.md         # How to create new agents
│   └── benchmarking.md          # Prose-model bench, bench configs, A/B methodology
└── archive/
    ├── implementation-roadmap.md # Historical phase-by-phase rebuild roadmap
    ├── future-work.md            # Historical deferred-items backlog
    ├── deferred-work.md          # Historical deferred-work log (craft_editor era)
    └── ...                       # Historical implementation briefs + drift reports
```

## Categories

- **Getting Started** — Installation and your first pipeline run
- **User Guides** — Task-oriented guides for each interface (CLI, web, workshop, workflow kit)
- **Architecture** — How the system is designed and why
- **Reference** — Lookup material (API endpoints, config options, schemas)
- **Development** — How to contribute, extend, and evaluate the system (including benchmarking)
- **Archive** — Historical implementation briefs and point-in-time drift reports (not current documentation)
