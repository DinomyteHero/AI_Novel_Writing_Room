# Agent Catalog

This directory mixes three different kinds of agents. They are not all part of
the live per-scene generation path.

## 1. Live Scene Pipeline

These are the agents that matter when you ask "what runs for a normal scene?"

Core hot path:
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
  Default-off. Extra line-edit pass between drafter and gate.
- `micro_repair.py`
  Default-off. Exact-span post-check patch stage for presence findings.
- `character_specialist.py`
  Supplementary post-save analysis, not a save-path blocker.
- `chapter_gate_critic.py`
  Chapter-level evaluation, not a per-scene hot-path agent.

## 2. Active Non-Scene Utilities

These are still real code, but they belong to other workflows:

- `seed_builder.py`
  Import/planning utility used when converting a planning manuscript into a
  concept seed.
- `editorial_consultant.py`
  Compile-time editorial review used by `scripts/compile_bundle.py`.
- `continuity_extractor.py`
  Post-save continuity event extraction used by the continuity log slice.
- `manuscript_reviewer.py`
  Full-manuscript review utility, not part of scene drafting.

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
