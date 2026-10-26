# CLAUDE.md — AI Writers' Room

Load-bearing notes for working on this codebase. Read before making changes.

## What this project is

A tool that helps writers, often new ones, plan and write novels and series
(fanfiction or original) with language models. It has two halves:

- **The Room** (interactive): the writer plans in conversation through the
  `story-session` skill; the plan lives in living Markdown files the chat
  updates as decisions land and the writer can edit by hand. Room commands
  (`scripts/room.py`): `new`, `books`, `status`, `review`, `revise`, `polish`,
  `rename`, `check`.
- **The Press** (automated): builds chapters from the plan with no one
  present. Per chapter: draft (writer model) → critique (a different model)
  → revise → save. Press commands (`scripts/press.py`): `build next|all|N`,
  `story-so-far`, `export`.

The files are the only contract between the halves. This repository used to
hold a large multi-agent pipeline (scene cards, chapter packets, state
databases, retrieval, ledgers, validators, a web console); it was deleted in
favour of this design and is in git history if something specific is needed.

## Design rules

- **Files are the book.** Books live in `library/` (gitignored: private by
  default; `--library` or `WRITERS_ROOM_LIBRARY` points elsewhere). A
  standalone book is a series of one; `series_bible.md` appears when a
  second book is added. Each book folder
  (`books/NN-<slug>/`) holds `story_bible.md`, `characters.md`, `outline.md`
  (one `## Chapter N` heading per chapter, optional `Words: N` line),
  `manuscript/` (+ `.history/`, `.provenance.json`), `notes/`, `runs/`,
  optional `story_so_far.md`, and `export/`. The model is in
  `src/studio/project.py` (`Library`, `Series`, `Book`, `Plan`).
- **Each thing lives in one place.** Characters only in a book's
  `characters.md`, never in a bible; shared series material only in
  `series_bible.md`. Characters and outlines always belong to a book: a new
  book in a series starts with a copy of the previous book's `characters.md`
  (`Book.create(previous=...)`), so nobody is lost and each book shows who
  its people are by then. That copy is the one deliberate overlap; earlier
  books are settled history, sent in full or as `story_so_far.md`.
- **Whole-book context, nothing retrieved.** Every call sends the series
  bible, earlier books (in full, or their `story_so_far.md` when present),
  this book's plan, and the relevant chapters in full
  (`src/studio/prompts.py`). Stable material first for prefix caching; the
  task last. **Do not add summarisers, retrieval, state stores, ledgers or
  validators.** `story_so_far.md` is the one exception, and it's an ordinary
  file the writer can read and edit. `MAX_PROMPT_TOKENS` (900K) in
  `src/studio/llm.py` refuses oversized calls.
- **The press builds on a frozen plan.** `build` reads the `Plan` once and
  snapshots it into `runs/<id>/plan/`, so room edits mid-build can't split a
  book across two plans. Chapters build in order, each reading the finished
  ones before it.
- **One bounded automatic revision.** `press.revision_rounds` defaults to 1.
  "No changes needed" from the critic skips the revision; a revision shorter
  than `min_revision_ratio` of its input is discarded. Do not stack more
  automated passes by default; extra rounds flatten voice and lose length.
- **Provenance, not gates.** `.provenance.json` records the outline and
  background fingerprints each chapter was built from. `chapter_state` reports
  `outline changed` (actionable) or `plan changed` (informational). Nothing
  blocks on it; the writer decides.
- **The review is an optional gate.** `room.py review` writes numbered points
  with a blank `**Your call:**` line; the skill walks the writer through
  them and applies only agreed edits. Never make review mandatory.
- **Loose craft framework.** `prompts/studio/craft_guide.md` is the single
  home for craft guidance (lenses, not rules); prompts, the skill and docs
  point at it rather than restating it. The writer's bible always wins. **Do
  not add required beats, percentages, arc fields or schemas.**
- **Never lose the writer's work.** Every replacement goes to `.history/`;
  rebuilding an existing chapter asks first (`--yes` skips); an empty model
  response saves nothing; renames preview before `--apply`.
- **No output caps by default.** Roles in `config/settings.yaml` set no
  `max_tokens`; `tests/test_library.py::test_default_settings_have_no_output_caps`
  guards this.
- **Errors are for writers.** `StudioError` messages are shown as-is, in
  plain language with the fix included. Missing API keys and network
  failures are caught in `src/studio/cli.py` and explained, never shown as
  tracebacks.

## Layout

| Concern | Path |
|---|---|
| Library, series, book, plan, provenance | `src/studio/project.py` |
| Prompt assembly (whole-book messages) | `src/studio/prompts.py` |
| Model calls, roles, size limit, usage | `src/studio/llm.py` |
| Room operations | `src/studio/room.py` |
| Press: build loop, estimate, story-so-far, export | `src/studio/press.py` |
| Command-line front ends | `src/studio/cli.py`, `scripts/room.py`, `scripts/press.py` |
| Model prompts + craft guide | `prompts/studio/` |
| Starter files | `templates/story/` |
| The Room's conversation | `.claude/skills/story-session/SKILL.md` |
| Model routing (OpenRouter / llama-server), usage log, key check | `src/model_router.py`, `config/settings.yaml` |
| Writer-facing guide | `docs/guide.md` |

Routing roles: `studio_writer` (draft, revise, polish), `studio_critic` (press
critique), `studio_reader` (review, story-so-far). All need ~1M-token context
windows.

## Testing

- `pytest -q` and `ruff check .`. CI runs both.
- Tests never call real models: `tests/fakes.py::FakeRouter` returns scripted
  replies per role and records every call and its usage. CLI tests swap it in
  for `cli._router`.

## Conventions

- Prefer editing existing files to creating new ones.
- Comments only when the *why* is non-obvious. Put task history in commit
  messages, not code.
- Keep it small. Before adding a module, flag or file format, ask whether a
  sentence in a prompt or the craft guide would do the job.
