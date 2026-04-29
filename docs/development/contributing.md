# Contributing

This guide covers setting up a development environment, running tests, and the project's code conventions.

## Development Setup

```bash
git clone https://github.com/DinomyteHero/AI_Novel_Writing_Room.git
cd AI_Novel_Writing_Room
pip install -r requirements.txt
```

For frontend development:

```bash
cd src/ui/frontend
npm install
npm run dev    # Vite dev server on http://localhost:5173
```

## Running Tests

```bash
# All tests
pytest

# Verbose output
pytest -v

# Specific test file
pytest tests/test_orchestrator.py

# Tests matching a pattern
pytest -k "test_gate_critic"

# With output capture disabled (for debugging)
pytest -s
```

The test suite has roughly 150 test files covering the major pipeline, workflow, UI, migration, and memory surfaces. Tests use pytest with pytest-asyncio for async test support.

### Test Fixtures

Common fixtures are defined in `tests/conftest.py`:
- `sample_concept_seed` -- A test concept seed dict
- `sample_scene_card` -- A test scene card dict
- `temp_dir` -- Temporary directory (cleaned up after test)
- `mock_router` -- A ModelRouter mock that returns canned responses
- `settings_yaml` -- Path to a test settings file
- `story_state` -- An initialized StoryState with temp SQLite
- `knowledge_layers` -- KnowledgeLayers wrapping test StoryState
- `mock_embedding_function` -- A deterministic mock for ChromaDB
- `chapter_memory` -- ChapterMemory with mock embeddings

Phase 5 has additional fixtures in `tests/conftest_phase5.py` for FastAPI test client and WebSocket testing.

## Project Structure

```
src/
|-- main.py              # CLI entry point
|-- model_router.py      # LLM routing abstraction
|-- orchestrator.py      # Scene pipeline state machine
|-- project_paths.py     # Franchise/book/run path resolution
|-- runtime_flags.py     # Runtime flag merge and CLI override resolution
|-- run_ledger.py        # Event logging
|-- pipeline_session.py  # Session persistence
|-- agents/              # 21 agent implementations and utilities
|-- pipeline/            # Chapter packet, preflight, save blockers, final copy
|-- memory/              # Story state, chapter memory, ledgers, continuity, sociogram
|-- rag/                 # Canon retrieval
|-- quality/             # Quality metrics, scene-contract checks, literal repair
|-- planning/            # Story physics and planning helpers
|-- worldbuilding/       # Lore DB and vector helpers
|-- export/              # Export formats
|-- concept_workshop/    # Remaining canonical concept helpers
|-- prompting/           # Prompt rendering helpers
`-- ui/                  # FastAPI app, routes, WebSocket ledger, React frontend

scripts/
|-- migrations/          # One-shot and idempotent migration scripts
|-- compile_bundle.py    # Workflow artifacts -> concept_seed + scene cards
|-- patch_workflow.py    # Manuscript patch application
`-- manuscript_export.py # Run export stitcher

workflows/
|-- idea_session_capture/
|-- universe_builder/
|-- canon_drafter/
|-- voice_discovery/
|-- character_forge/
|-- outline_planner/
`-- scene_card_authoring/
```

## Code Conventions

### Agent Pattern

All agents extend `BaseAgent` (`src/agents/base_agent.py`). To understand the pattern, read that file first. Key requirements:
- Each agent has a single responsibility
- System prompts live in `prompts/agent_system_prompts/{role}.md`
- Communication goes through `ModelRouter` exclusively
- Output must be a structured dict

See [Adding Agents](adding-agents.md) for a detailed guide.

### Optional Dependencies

The project uses a pattern where higher-phase components are optional. The Orchestrator accepts `None` for any Phase 2/3/4 dependency and skips those steps. When adding new components:
- Use `Optional` type hints with `None` defaults
- Guard usage with `if component is not None:` checks
- Import expensive dependencies lazily (inside functions)

### Event Logging

All pipeline actions should emit events to the RunLedger. Use descriptive event types and include relevant chapter/scene/agent context.

### Error Handling

Failed LLM calls retry with backoff (handled by ModelRouter). Agent-level failures use structured failure codes, not exceptions. Pipeline-level errors are caught by the Orchestrator and logged.

## Git Workflow

The project uses GitHub with pull requests. Branch from `main` for new work.

## Key Files to Understand First

If you're new to the codebase, read these in order:
1. `src/agents/base_agent.py` -- The agent abstraction
2. `src/model_router.py` -- How LLM calls are routed
3. `src/orchestrator.py` -- The pipeline flow (read the docstring at the top)
4. `config/settings.yaml` -- Configuration structure
5. `config/failure_codes.yaml` -- The failure taxonomy
