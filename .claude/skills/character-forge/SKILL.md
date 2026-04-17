---
name: character-forge
description: Workflow-kit surface for building the ensemble cast — 2-6 characters with three-dimensional profiles and Weiland arc structure (lie/ghost/want/need plus arc_type and arc_phase_map) — plus optional referenced characters and dyad-level relationship arcs. Use when authoring a new project's cast or expanding/revising existing character architecture. Produces workflows/characters.json.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

This is the Claude Code wrapper for the **character-forge** workflow
surface. The authoritative SKILL content lives at:

@workflows/character_forge/SKILL.md

Read it before answering any question about this surface. The shared
preamble at `workflows/_shared/SKILL_preamble.md` describes the protocol
every surface follows; read that first if you haven't already.

The api.py entry point is `workflows.character_forge.api.CharacterForge`;
importers live at `workflows/character_forge/importers/`. The
character-forge validator cross-checks `arc_phase_map` keys against the
canonical phase vocabulary for each `arc_type` — let it catch mismatches
rather than guessing.
