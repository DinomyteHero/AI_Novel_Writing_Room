# Agent Catalog

This directory mixes three different kinds of agents. They are not all part of
the live per-scene generation path.

## 1. Live Scene Pipeline

These are the agents that matter when you ask "what runs for a normal scene?"

Core hot path (full forward-only relay; bypassed in the lean shipping
default `PlotArchitect → ProseStylist → LineWriter → save`):
- `plot_architect.py`
- `prose_stylist.py`
- `gate_critic.py`
- `quality_polish.py`
- `final_gate.py`
- `canon_expert.py`
- `presence_checker.py`
- `summarizer.py` (post-save but load-bearing for state/memory)

Optional scene-path agents:
- `line_writer.py`
  Default-on in lean mode. Extra line-edit pass between drafter and save.
- `commercial_rewrite.py`
  Flag-gated post-metrics rewrite slot in the non-lean relay
  (`_maybe_commercial_rewrite`, between QualityMetrics and QualityPolish).
- `micro_repair.py`
  Default-off. Exact-span post-check patch stage for presence findings.
- `character_specialist.py`
  Supplementary post-save analysis, not a save-path blocker.
- `chapter_gate_critic.py`
  Chapter-level evaluation, not a per-scene hot-path agent.
- `continuity_extractor.py`
  Default-off, threshold-gated. Post-save continuity-event extraction for
  the continuity log slice (Slice 4). Risky LLM-extracted slice — see
  `runtime.continuity_log.*` flags.

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
  Not part of the per-scene relay; intended for the final pre-publication
  sweep.
- `manuscript_reviewer.py`
  Full-manuscript developmental review. **No CLI wrapper** — invoked
  manually from a Python REPL when a review is wanted. Routing config,
  prompt, and tests exist; the agent is intentionally kept as a
  buildable utility for the manuscript-production lifecycle.

## 3. Base Class

- `base_agent.py`
  Shared wrapper for prompt loading and router calls.

## What To Treat As Stale

The stale concepts are mostly architectural terms, not these files:

- The old multi-band revision pipeline is gone.
- `--no-revision` survives only as a hidden compatibility flag.
- "Craft Editor" / "SceneReviewer" wording in comments or archived docs refers
  to historical pipeline shapes, not live runtime behavior.

If you are simplifying the scene pipeline, focus on the files listed under
"Live Scene Pipeline" first. Do not assume everything under `src/agents/` is
part of the per-scene hot path.
