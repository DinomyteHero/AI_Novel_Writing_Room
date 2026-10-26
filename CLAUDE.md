# CLAUDE.md — AI Writers' Room

Load-bearing notes for working on this codebase. Read before making changes.

## What this project is

A tool that helps writers, often new ones, plan and draft novels (fanfiction
or original) with a language model. The writer plans in conversation; the
plan lives in two plain Markdown files; each chapter is drafted by one model
call that sees the whole book.

This repository used to hold a large multi-agent pipeline (scene cards,
chapter packets, state databases, retrieval, ledgers, validators, a web
console). It was deleted in favour of this design; it's in git history if
something specific is ever needed.

## Design rules

- **Files are the book.** A book is a folder of Markdown the writer can open
  and edit: `story_bible.md`, `outline.md` (one `## Chapter N` heading per
  chapter, title optional), `chapters/chapter_NN.md`, `chapters/.history/`
  (every replaced version), `notes/` and `export/`. Original books live at
  `data/projects/<slug>/story/` (gitignored, so private to the machine);
  fanfiction at `data/franchises/<franchise-slug>/books/<slug>/story/`. Paths
  come from `src/studio/project.py::book_root`.
- **Whole-book context, nothing retrieved.** Every call sends the story
  bible, the outline and every drafted chapter in full
  (`src/studio/prompts.py`). Stable material comes first for prefix caching;
  the task comes last. **Do not add summarisers, retrieval, state stores,
  ledgers or validators.** If the model can read the whole book, it doesn't
  need them. `MAX_PROMPT_TOKENS` (900K) in `src/studio/writer.py` refuses
  oversized calls.
- **Loose craft framework.** `prompts/studio/craft_guide.md` offers lenses,
  not rules: Story Spine, six questions, but/therefore, promise/progress/
  payoff, "yes, but / no, and" outcomes, the "what changed by the end?"
  chapter test, and prose notes. The writer's story bible always wins over
  it. **Do not add required beats, percentages, arc fields or schemas.**
- **The conversation keeps the files.** The `story-session` skill
  (`.claude/skills/story-session/SKILL.md`, also the Codex contract via
  `AGENTS.md`) plans with the writer and edits the two files as decisions
  land. It re-reads before every edit (manual edits win) and only records
  what the writer agreed to.
- **Never lose the writer's work.** `draft` refuses to overwrite without
  `--force`; every replacement moves the old file into `.history/`; an empty
  model response saves nothing (`StudioError`).
- **Errors are for writers.** `StudioError` messages are shown directly to
  the writer, so phrase them in plain language with the fix included.

## Layout

| Concern | Path |
|---|---|
| Book folder model, outline parsing, paths | `src/studio/project.py` |
| Prompt assembly (whole-book messages) | `src/studio/prompts.py` |
| Draft / revise / polish / review / export | `src/studio/writer.py` |
| CLI | `scripts/studio.py` |
| Model prompts + craft guide | `prompts/studio/` |
| Starter files for a new book | `templates/story/` |
| Planning conversation skill | `.claude/skills/story-session/SKILL.md` |
| Model routing (YAML → OpenRouter / llama-server) | `src/model_router.py`, `config/settings.yaml` |
| User guide | `docs/user-guide/studio.md` |

Routing roles: `studio_writer` (draft, revise, polish) and `studio_reader`
(review). Both need ~1M-token context windows.

## Testing

- `pytest -q` and `ruff check .`. CI runs both.
- Tests never call real models; `tests/test_studio.py` has a `FakeRouter`
  that records the messages it receives.

## Conventions

- Prefer editing existing files to creating new ones.
- Comments only when the *why* is non-obvious. Put task history in commit
  messages, not code.
- Keep it small. Before adding a module, flag or file format, ask whether a
  sentence in a prompt or the craft guide would do the job.
