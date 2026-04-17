---
name: voice-discovery
description: Workflow-kit surface for eliciting a project's narrative voice — POV approach, prose register, reference authors, character voices, anti-slop rules, and structural anti-patterns — into a single voice_definition artifact. Use when starting a new project's voice work or when revising voice rules. Produces workflows/voice.json.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

This is the Claude Code wrapper for the **voice-discovery** workflow
surface. The authoritative SKILL content lives at:

@workflows/voice_discovery/SKILL.md

Read it before answering any question about this surface. The shared
preamble at `workflows/_shared/SKILL_preamble.md` describes the protocol
every surface follows; read that first if you haven't already.

The api.py entry point is `workflows.voice_discovery.api.VoiceDiscovery`
plus the module-level `write_voice(paths, voice_def)` helper. Importers
live at `workflows/voice_discovery/importers/`. The default voice
template at `templates/voice_definition/default.json` is a useful
starting scaffold.
