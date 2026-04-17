---
name: outline-planner
description: Workflow-kit surface for building the planner-level structural outline (Brooks four-part beat map, per-chapter synopsis + POV + structural phase) and the subplot/hook/revelation/promise/arc-phase-map skeletons. Use when authoring a new project's chapter outline or revising structural planning. Produces workflows/outline.json. Per-scene cards live in scene-card-authoring.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

This is the Claude Code wrapper for the **outline-planner** workflow
surface. The authoritative SKILL content lives at:

@workflows/outline_planner/SKILL.md

Read it before answering any question about this surface. The shared
preamble at `workflows/_shared/SKILL_preamble.md` describes the protocol
every surface follows; read that first if you haven't already.

The api.py entry point is
`workflows.outline_planner.api.OutlinePlannerSurface`; importers live at
`workflows/outline_planner/importers/`. With a router supplied,
`OutlinePlannerSurface.generate(seed)` produces an LLM-drafted outline
you can refine — useful when starting blank.
