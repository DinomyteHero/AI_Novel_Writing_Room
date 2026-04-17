---
name: scene-card-authoring
description: Workflow-kit surface for per-scene card authoring. Phase 4 ships api.py + importers; chat-led authoring is deferred to a follow-up phase. Use the headless SceneCardAuthoring.generate(seed) path or import from a legacy concept_seed.json or hand-written markdown. Produces workflows/scene_cards.json plus per-card files at workflows/scene_cards/.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

This is the Claude Code wrapper for the **scene-card-authoring** workflow
surface. The authoritative SKILL content lives at:

@workflows/scene_card_authoring/SKILL.md

Read it before answering any question about this surface. The shared
preamble at `workflows/_shared/SKILL_preamble.md` describes the protocol
every surface follows; read that first if you haven't already.

Scene-card-authoring's chat-led SKILL is intentionally minimal in
Phase 4 — the api.py
(`workflows.scene_card_authoring.api.SceneCardAuthoring`) and the two
importers are the supported paths. Direct the user to the headless
`generate()` flow or to one of the importers rather than hand-walking
per-scene authoring; that's a follow-up phase.
