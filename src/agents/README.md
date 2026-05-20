# Agent Catalog

This directory mixes three different kinds of agents. They are not all part of
the live per-scene generation path.

## 1. Live Scene Pipeline

These are the agents that run for a normal scene. The lean pipeline is a single
forward pass — no gates, no save-blockers, no retries:

```
PlotArchitect → ProseStylist → [LineWriter] → [RhythmEditor] → save
```

- `plot_architect.py`
  Generates the typed generation brief from the scene card.
- `prose_stylist.py`
  Primary drafter. Drafts the scene against the chapter packet.
- `line_writer.py`
  Single post-draft line-edit pass. Default-on in the lean path
  (`runtime.lean_prose_only.line_edit.enabled`). Takes an explicitly wired
  context dict — does not reach into the ambient `ContextAssembler`. Collapsed
  or crashed output falls back to drafter prose with a warn event.
- `rhythm_editor.py`
  Default-off (`runtime.rhythm_editor.enabled`). Bounded literal-edit pass that
  fixes rhythm issues flagged by `RhythmValidator`
  (`src/quality/rhythm_validator.py`). Exact-span replacements only; safety
  caps enforced by `apply_rhythm_edits`.

Post-save (still load-bearing, but after the scene is written):

- `summarizer.py`
  Produces the scene summary + state diff that feed chapter memory, story
  state, and the contradiction scan. Wrapped in a broad error guard — a
  crash never aborts a saved scene.

## 2. Active Non-Scene Utilities

These are still real code, but they belong to other workflows:

- `seed_builder.py`
  Import/planning utility used when converting a planning manuscript into a
  concept seed (`src/main.py` build-seed path).
- `editorial_consultant.py`
  Compile-time editorial review used by `scripts/compile_bundle.py`.
- `canon_scout.py`
  Pre-run canon-guidance authoring agent. Used by `scripts/canon_scout.py`
  and `src/pipeline/canon_guidance.py` to populate franchise canon tips
  the chapter packet then surfaces to the drafter.
- `literary_polish.py`
  Post-production literary-polish pass. Used by
  `scripts/final_copy_existing.py` and `scripts/bench_prose_models.py`.
  Not part of the per-scene pipeline; intended for the final pre-publication
  sweep.
- `manuscript_reviewer.py`
  Full-manuscript developmental review. **No CLI wrapper** — invoked
  manually from a Python REPL when a review is wanted. Routing config,
  prompt, and tests exist; the agent is kept as a buildable utility for the
  manuscript-production lifecycle.

## 3. Base Class

- `base_agent.py`
  Shared wrapper for prompt loading and router calls.

## What To Treat As Stale

The stale concepts are mostly architectural terms:

- The old multi-band revision pipeline is gone.
- The forward-only relay with gates, save-blockers, and quarantine is gone —
  the pipeline is a single lean forward pass.
- `--no-revision` survives only as a hidden, no-op compatibility flag.

If you are simplifying the scene pipeline, focus on the files listed under
"Live Scene Pipeline" first. Do not assume everything under `src/agents/` is
part of the per-scene hot path.
