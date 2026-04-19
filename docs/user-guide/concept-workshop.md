# Concept Workshop — REMOVED

The interactive concept-workshop CLI (`src.concept_workshop.workshop_runner`) has been removed.

Start new projects through the **workflow kit** instead:

- Per-surface skills under `.claude/skills/<surface>/` and `workflows/<surface>/SKILL.md`.
- Compile the per-surface outputs into a single `concept_seed.json` with `python scripts/compile_bundle.py`.

See [Workflow Kit](workflow-kit.md) for the current end-to-end workflow.

## Why this was removed

The workshop runner's system prompt was silently dropped after context-window summarization, making long sessions drift out of the 11-step protocol exactly when context pressure was highest. Rather than preserve a bug-prone CLI with a limited user base, the project standardized on the workflow-kit path, which is the current and supported entry point.

## If you have an in-flight workshop session

- Any concept_seed.json already produced is untouched — proceed straight to scene-card authoring via the workflow kit.
- Raw transcripts and `workshop_state.json` files under `data/projects/<NAME>/workshop_sessions/` remain readable but are no longer executed by any tooling. Keep them for historical reference or delete them.
