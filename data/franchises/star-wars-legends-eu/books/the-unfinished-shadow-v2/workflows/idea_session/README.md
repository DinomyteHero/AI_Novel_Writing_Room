# Idea Session Capture

This folder is the author-facing front door for planning. It is
not read by `compile_bundle.py`. Use it to hold chat notes,
settled decisions, open questions, and handoffs into the six
workflow-kit surfaces.

## Files

- `capture.json` — machine-readable session state (mutated by
  both Claude Code and Codex through `IdeaSessionCapture`).
- `session.md` — live planning notes; free-form.
- `raw_transcript.md` — optional pasted/exported chat transcript.
- `surface_handoffs/*.md` — per-surface notes the downstream
  surface session inherits.

## Workflow

1. Run a planning chat (Claude Code skill `idea-session-capture`,
   or Codex via `AGENTS.md`).
2. Mutate state through `IdeaSessionCapture` calls; the agent
   does the conversation, the api does the writes.
3. When north-star is settled and you have at least a few
   decisions, run:
   ```bash
   python scripts/idea_session_capture.py expand --title "<title>" --franchise "<franchise>"
   ```
   This pre-seeds the six workflow-kit surface artifacts.
4. Author each surface from its seeded draft.
5. Compile with `python scripts/compile_bundle.py`.
