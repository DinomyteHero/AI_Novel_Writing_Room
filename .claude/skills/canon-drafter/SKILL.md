---
name: canon-drafter
description: Workflow-kit surface for authoring canon constraints, canon_profile, force/magic mechanics, and the canonical-terminology registry that govern what canon_expert flags and how franchise-specific terms are used consistently. Use when establishing or revising the project's canon rules and terminology, or when canon_expert flags terminology drift. Produces workflows/canon.json.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

This is the Claude Code wrapper for the **canon-drafter** workflow
surface. The authoritative SKILL content lives at:

@workflows/canon_drafter/SKILL.md

Read it before answering any question about this surface. The shared
preamble at `workflows/_shared/SKILL_preamble.md` describes the protocol
every surface follows; read that first if you haven't already.

The api.py entry point is `workflows.canon_drafter.api.CanonDrafter`;
importers live at `workflows/canon_drafter/importers/`. Five canon_profile
templates ship in `templates/canon_profile/` — start by applying one with
`CanonDrafter.apply_template()` rather than authoring from scratch.
