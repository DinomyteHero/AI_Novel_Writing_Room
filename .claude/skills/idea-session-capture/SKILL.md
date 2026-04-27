---
name: idea-session-capture
description: Workflow-kit front door for the first author-led planning chat. Run a four-pass session (Spark → Foundation → Deepening → Production Handoff) and preserve decisions, open questions, and per-surface handoff briefs that the six downstream surfaces (universe, canon, voice, characters, outline, scene_cards) consume. Use when starting a new project from a fuzzy idea, or when revisiting north-star intent before re-authoring surfaces. Produces workflows/idea_session/capture.json + session.md + surface_handoffs/*.md.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash
---

This is the Claude Code wrapper for the **idea-session-capture** workflow
surface. The authoritative SKILL content lives at:

@workflows/idea_session_capture/SKILL.md

Read it before answering any question about this surface. The shared
preamble at `workflows/_shared/SKILL_preamble.md` describes the protocol
every surface follows; read that first if you haven't already.

The api.py entry point is
`workflows.idea_session_capture.api.IdeaSessionCapture`. With a capture
already populated, `IdeaSessionCapture.expand_to_surface_drafts()` pre-seeds
`workflows/{universe,canon,voice,characters,outline}.json` skeletons from
the capture so the downstream surface authors open a partly-filled draft
instead of a blank file.

This surface is the **only** surface that is portable Claude Code ↔ Codex:
the conversation lives in `workflows/idea_session_capture/SKILL.md` (a plain
markdown spec). Codex users invoke it via the repo-root `AGENTS.md`. Both
tools call the same headless api.py for scaffolding, status checks, and
expansion.
