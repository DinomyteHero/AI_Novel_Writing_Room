---
name: universe-builder
description: Workflow-kit surface for authoring a project's universe identity, foundational premise, conflict, and theme. Use when starting a new novel project (empty data/franchises tree) or when the meta / premise / conflict / theme sections of an existing project need work. Produces workflows/universe.json the bundle compiler consumes.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

This is the Claude Code wrapper for the **universe-builder** workflow
surface. The authoritative SKILL content lives at:

@workflows/universe_builder/SKILL.md

Read it before answering any question about this surface. The shared
preamble at `workflows/_shared/SKILL_preamble.md` describes the protocol
every surface follows; read that first if you haven't already.

The api.py entry point is `workflows.universe_builder.api.UniverseBuilder`;
importers live at `workflows/universe_builder/importers/`.
