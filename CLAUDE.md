# CLAUDE.md — AI Writers' Room

Load-bearing notes for working on this codebase. Read before making changes.

## What this project is

A tool that helps writers, often new ones, plan and write novels and series
(fanfiction or original) with language models. It has two halves:

- **The Room** (interactive): the writer plans in conversation through the
  `story-session` skill; the plan lives in living Markdown files the chat
  updates as decisions land and the writer can edit by hand. Room commands
  (`scripts/room.py`): `new`, `books`, `status`, `review`, `ideas`, `revise`,
  `polish`, `rename`, `check`.
- **The Press** (automated): builds chapters from the plan with no one
  present. Per chapter: draft (writer model) → critique (a different model)
  → revise → save. Press commands (`scripts/press.py`): `build next|all|N`,
  `story-so-far`, `export`.

Writers reach both halves three ways, all over the same files and code:

- **The app** (`scripts/app.py`): a local web app in the browser, laid out
  like Claude (books, chats, a Book panel, Settings for providers). A
  chat model from the writer's own provider (`studio_chat`) follows the same
  `story-session` skill through tools (`src/studio/chat.py`).
- **The Claude plugin** (`.claude-plugin/`): for Cowork and Claude Code.
  Claude follows the skill and edits files itself; a stdio MCP server
  (`scripts/mcp_server.py` → `src/studio/mcp.py`) adds books, reviews,
  renames and background builds.
- **The command line** (`scripts/room.py`, `scripts/press.py`).

The files are the only contract between the halves. This repository used to
hold a large multi-agent pipeline (scene cards, chapter packets, state
databases, retrieval, ledgers, validators, a web console); it was deleted in
favour of this design and is in git history if something specific is needed.

## Design rules

- **Files are the book.** Books live in `library/` (gitignored: private by
  default). `locate_library` in `src/studio/project.py` is the one resolver
  for the app, CLI and plugin: `--library`, then `WRITERS_ROOM_LIBRARY`, then
  `library:` in `config/settings.local.yaml` (Settings > Library folder), then
  `./library`. A
  standalone book is a series of one; `series_bible.md` appears when a
  second book is added. Each book folder
  (`books/NN-<slug>/`) holds `story_bible.md`, `characters.md`, `outline.md`
  (one `## Chapter N` heading per chapter, optional `Words: N` line),
  `manuscript/` (+ `.history/`, `.provenance.json`), `notes/`, `runs/`,
  optional `story_so_far.md`, optional `reference/`, and `export/`. A series
  may have its own `reference/` too. The app keeps chats in `<series>/chats/`. The model is in
  `src/studio/project.py` (`Library`, `Series`, `Book`, `Plan`).
- **Each thing lives in one place.** Characters only in a book's
  `characters.md`, never in a bible; shared series material only in
  `series_bible.md`. Characters and outlines always belong to a book: a new
  book in a series starts with a copy of the previous book's `characters.md`
  (`Book.create(previous=...)`), so nobody is lost and each book shows who
  its people are by then. That copy is the one deliberate overlap; earlier
  books are settled history, sent in full or as `story_so_far.md`.
- **Whole-book context, nothing retrieved.** Every call sends the series
  bible, reference notes (`.md`/`.txt` in `reference/`, read in full), earlier books (in full, or their `story_so_far.md` when present),
  this book's plan, and the relevant chapters in full
  (`src/studio/prompts.py`). Stable material first for prefix caching; the
  task last. The user message also carries its sections as `parts` (each
  chapter its own) so the router can put Claude's cache marker just before
  the task. **Do not add summarisers, retrieval, state stores, ledgers or
  validators.** `story_so_far.md` is the one exception, and it's an ordinary
  file the writer can read and edit. `MAX_PROMPT_TOKENS` (900K) in
  `src/studio/llm.py` refuses oversized calls, a provider's own "too long"
  error is explained the same way, and the build estimate warns above
  `LONG_PROMPT_TOKENS` (500K).
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
  `room.py ideas` uses the same shape for options where the plan is thin;
  a model never fills in the plan unasked. In the app there are no review or
  ideas buttons: the writer asks in a chat, and the chat can do either in the
  conversation or call its `review`/`ideas` tools to bring in the
  `studio_reader` model and save numbered notes; `fresh_eyes` gives a reader
  pass on one chapter without the plan. The project page starts a new chat for
  each piece of work.
- **Loose craft framework.** `prompts/studio/craft_guide.md` is the single
  home for craft guidance (lenses, not rules); prompts, the skill and docs
  point at it rather than restating it. The writer's bible always wins, and
  the bible's "The reader's promise" and "What this book is doing on purpose"
  outrank the guide. **Do not add required beats, percentages, arc fields or
  schemas.**
- **Never lose the writer's work.** Every replacement goes to `.history/`;
  rebuilding an existing chapter asks first (`--yes` skips); an empty model
  response saves nothing; renames preview before `--apply`, keep the previous
  text and can be undone; removing a reference moves it to `reference/.history`
  instead of deleting it.
- **Suggestions are proposals.** "Edits from the chat: Show me first" in
  Settings > Preferences makes `edit_file`, `write_file`, `edit_passage` and `revise_chapter` stage a
  `proposal` item instead of saving; the writer accepts or keeps it. Acceptance
  compares the current text with the proposal's `before`, marks it stale rather
  than overwriting a newer edit, and turns the accepted item into a normal
  activity with Undo. Builds remain their own operation.
- **Buttons are for consent, not capability.** The app's chat is the command
  surface: if a sentence can do it, don't give it a button. Visible controls
  are navigation, Send/Stop/Attach, Build (which spends money), Use
  suggestion/Keep original, Undo, Save, and Settings. One Build entry point
  opens the estimate card; one Book panel holds the plan, reference,
  manuscript, notes and context. Do not add feature buttons for review, ideas,
  explore or modes; the model calls its tools, and preferences live in
  Settings.
- **The chat model is per chat.** Each chat stores its own `model` and
  `effort` in the chat JSON; the selector under the composer writes them. The
  configured `studio_chat` routing is only the default for a chat with no
  choice. Press and background roles stay in Settings; do not move them into
  the chat selector. Models marked `hidden: true` stay for chats that already
  chose them but are not offered in either list.
- **No output caps by default.** Roles in `config/settings.yaml` set no
  `max_tokens`; `tests/test_library.py::test_default_settings_have_no_output_caps`
  guards this.
- **Errors are for writers.** `StudioError` messages are shown as-is, in
  plain language with the fix included. Missing API keys and network
  failures are caught in `src/studio/cli.py`, `src/app/server.py` and
  `src/studio/mcp.py` and explained, never shown as tracebacks.
- **One skill, three front ends.** `.claude/skills/story-session/SKILL.md` is
  the only conversation guide. The app's `prompts/studio/room_chat.md` and the
  plugin's tools map its commands; don't fork the guide per front end.
- **Append-only chat turns.** The app sends earlier turns as plain text and
  the current files only with the newest message, never editing what was sent
  (prompt caching, and Claude's thinking-block binding, depend on it).
- **Planning progress is recoverable.** `/api/send/stream` emits text and tool
  activity as newline-delimited JSON. The existing chat JSON saves completed
  actions during the turn and marks interrupted turns on reopening. Stop
  cancels pending model work; completed edits remain. No separate job store.
  Retained chat attachments live beside the chat in `<id>-files/`; only book
  and series references reach the Press. The API still accepts read-only
  `explore` turns; the app has no explore toggle, and the chat treats "just
  exploring" as read-only by instruction. Selected-passage edits preserve
  chapter history, and manual saves check the document version before
  replacing it.
- **Providers are backends.** Each entry under `models` in
  `config/settings.yaml` is a backend; `api: anthropic` uses the Anthropic SDK,
  the rest the OpenAI-compatible API. The app writes the writer's choices to
  the gitignored `config/settings.local.yaml` and keys to `.env`. When
  Settings or the chat's model picker opens and OpenRouter is connected, the
  app refreshes OpenRouter's public catalog if the cache
  (`config/openrouter_models.json`, gitignored) is over a day old
  (`src/model_catalog.py`). It doesn't poll, nothing waits on the refresh, and
  a failure keeps the cached or curated list. `load_config` adds catalog prices
  and context sizes to the curated `models.cloud.models`. It also adds the
  newest model of each recent family from the main makers, keyed by OpenRouter
  id and marked `discovered`. Older catalog models are kept `hidden: true`, so
  chats and roles that chose them keep working. Automatic routing never picks
  a discovered model.
- **Roles are automatic until chosen.** A role with no entry in the overlay
  whose provider has no key moves, in `load_config`
  (`automatic_routing`), to the first visible ~1M-context model on a
  connected provider; critic and reviewer prefer a model other than the
  writer's. Nothing connected leaves the shipped routing so the missing key
  is explained. Settings shows the resolved models and hides the dropdowns
  behind "Choose models myself"; build options live on the Build card.

## Layout

| Concern | Path |
|---|---|
| Library, series, book, plan, provenance | `src/studio/project.py` |
| Prompt assembly (whole-book messages) | `src/studio/prompts.py` |
| Model calls, roles, size limit, usage | `src/studio/llm.py` |
| Room operations | `src/studio/room.py` |
| Press: build loop, estimate, story-so-far, export | `src/studio/press.py` |
| Command-line front ends | `src/studio/cli.py`, `scripts/room.py`, `scripts/press.py` |
| The app's room chat (tools, undo, review calls) | `src/studio/chat.py`, `prompts/studio/room_chat.md` |
| Background builds (app and plugin) | `src/studio/jobs.py` |
| The app: backend, local server, page | `src/app/api.py`, `src/app/server.py`, `src/app/static/`, `scripts/app.py` |
| The Claude plugin: manifest, marketplace, commands, MCP tools | `.claude-plugin/`, `commands/`, `src/studio/mcp.py`, `scripts/mcp_server.py` |
| Model prompts + craft guide | `prompts/studio/` |
| Starter files | `templates/story/` |
| The Room's conversation | `.claude/skills/story-session/SKILL.md` |
| Model routing (providers, overlay, tool calls), usage log, key check | `src/model_router.py`, `config/settings.yaml` |
| OpenRouter's catalog (daily cache, newer models, prices) | `src/model_catalog.py` |
| Writer-facing guide | `docs/guide.md` |

Routing roles: `studio_chat` (the app's default chat model; a chat can
override it), `studio_writer` (draft, revise, polish), `studio_critic` (press
critique), `studio_reader` (review), `studio_notes` (story-so-far). All need
~1M-token context windows. A role's `params.tools` adds OpenRouter server tools
(web search, web fetch) to the chat's own.

## Testing

- `pytest -q` and `ruff check .`. CI runs both.
- Tests never call real models: `tests/fakes.py::FakeRouter` returns scripted
  replies per role (including `chat()` tool calls) and records every call and
  its usage. CLI tests swap it in for `cli._router`; app and MCP tests pass it
  as the router factory.

## Conventions

- Prefer editing existing files to creating new ones.
- Comments only when the *why* is non-obvious. Put task history in commit
  messages, not code.
- Keep it small. Before adding a module, flag or file format, ask whether a
  sentence in a prompt or the craft guide would do the job.
