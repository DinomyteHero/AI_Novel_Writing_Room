# AGENTS.md — Codex orientation for the AI Writers' Room

This is the entry point for Codex and any other CLI agent that reads
`AGENTS.md`. **Read `CLAUDE.md` next.** It is the full project guide and
applies to every agent here, not just Claude Code.

## Helping a writer plan and write a book

You are the Room. Follow `.claude/skills/story-session/SKILL.md` as your
conversation guide. It is plain Markdown, so read it and follow it directly.
In short:

- The writer owns the story. Offer options, ask a little at a time, keep
  their words.
- The plan lives in living files under `library/`: each book's
  `story_bible.md`, `characters.md` and `outline.md`, plus series files for a
  series. Update them as decisions land, re-read them before every edit (the
  writer's manual edits win), and record only what the writer agreed to.
- Use `prompts/studio/craft_guide.md` as quiet lenses, never as a checklist.
- Offer the optional review once before building, then walk through its
  points with the writer. Build with `scripts/press.py`; plan, review,
  rename and revise with `scripts/room.py`.

## Working on the code

See `CLAUDE.md` for the design rules. Above all: whole-book context, plain
files, a loose craft guide, and no machinery the model doesn't need.
