# Documentation

This directory contains all project documentation, organized by purpose.

## Structure

```
docs/
├── README.md                 # This file
├── getting-started.md        # Installation, configuration, first run
├── scene-card-template.md    # Scene-card field reference for external authoring
├── workshop-summary-template.md  # Planning-manuscript template for --import-summary
├── user-guide/
│   ├── cli-usage.md          # CLI commands and flags
│   ├── new-manuscript-workflow.md  # End-to-end operator path
│   ├── idea-session-capture.md     # Front-door planning chat
│   ├── workflow-kit.md       # Six-surface concept authoring
│   ├── final-copy-pipeline.md      # Post-draft literary-copy lane
│   ├── web-interface.md      # Web dashboard walkthrough
│   └── concept-workshop.md   # Removed-subsystem redirect to the workflow kit
├── architecture/
│   ├── system-overview.md    # Components, data flow, directory layout
│   ├── agent-pipeline.md     # The lean multi-agent generation loop
│   ├── manuscript-production-lifecycle.md  # Lean production + post-draft editorial
│   ├── manuscript_lifecycle_design.md      # Patch-workflow design reference (Slice 6)
│   ├── memory-and-state.md   # SQLite state, ChromaDB, knowledge layers
│   └── quality-and-revision.md  # The lean quality model
├── reference/
│   ├── api-reference.md      # FastAPI endpoints and WebSocket events
│   ├── configuration.md      # YAML configuration and runtime flags
│   └── schemas.md            # JSON schema definitions
├── development/
│   ├── contributing.md       # Dev setup, testing, code conventions
│   ├── adding-agents.md      # How to create new agents
│   └── benchmarking.md       # Prose-model bench, bench configs, A/B methodology
├── archive/                  # Historical implementation briefs + superseded design docs
├── audits/                   # Point-in-time audit reports
└── editorial/                # Point-in-time editorial notes and bench summaries
```

## Categories

- **Getting Started** — Installation and your first pipeline run
- **User Guides** — Task-oriented guides for each interface (CLI, web, workflow kit)
- **Architecture** — How the lean system is designed and why
- **Reference** — Lookup material (API endpoints, config options, schemas)
- **Development** — How to contribute, extend, and evaluate the system
- **Archive / Audits / Editorial** — Historical implementation briefs, superseded design docs, and point-in-time reports (not current documentation)
