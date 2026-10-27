# The Writers' Room Guide

The tool has two halves. In **the Room** you plan in conversation and the plan
lives in a few Markdown files you can edit any time. **The Press** turns that
plan into chapters on its own: draft, critique, revise, save. Every model call
reads your whole plan and every chapter before the one it's working on.

You can work in three ways, all on the same files: **the app**
(`python scripts/app.py`, in your browser), **the Claude plugin** (in Cowork
or Claude Code), or **the command line**. The README shows how to install
each; this guide covers what they do.

## Your library

Books live in `library/`, which git ignores, so your work stays on your
machine. To keep it somewhere else (a synced folder, your own git repository),
pass `--library <folder>` or set `WRITERS_ROOM_LIBRARY`.

A standalone book is a series of one:

```text
library/my-novel/
  books/01-my-novel/
    story_bible.md       premise, feel, world, how it's told, things to keep true
    characters.md        a sheet per character: wants, obstacles, how they talk
    outline.md           the threads, then one "## Chapter N" section per chapter
    manuscript/          chapter_01.md, ... (earlier versions in .history/)
    notes/               reviews
    runs/                one folder per press build, with a report
    export/              the whole book in one file
```

A series adds one shared file and numbers its books:

```text
library/my-series/
  series_bible.md        the shared world, rules and the arc across books
  books/01-book-one/ ...
  books/02-book-two/ ...
```

Characters and outlines always belong to a book. A new book starts with a
copy of the previous book's `characters.md`, so the whole cast comes along and
you can update who they've become without touching the earlier book.

### Reference files

Canon notes, research, a fuller setting (`setting.md`, for a world that has
outgrown the bible) or a sample of the voice you want can go in a
`reference/` folder: a book's own (`books/01-my-novel/reference/`) or, in a
series, the series' (`library/my-series/reference/`), which every book reads.
Every model call reads these in full, so keep them to what matters; a large
file adds its size to every call. Only `.md` and `.txt` files are read (the
app converts `.docx` for you). Images can't be read by the writing models;
describe what matters in the bible instead.

When the library holds more than one book, name the one you mean with
`--title` (and `--series` if two series share a title).

## The Room: plan in conversation

Tell the chat what you have: a one-line idea, a few characters, a rough
outline, or a document to paste in. It files what you bring in your own
words, then helps you flesh it out with options and questions.

- **In the app**, type your idea on the home page (the **+** starts a book or
  a series). Each project page has an ongoing chat about the whole book, and
  you can open separate chats for single questions. Every file change shows
  as a card with **Undo**; the files panel on the right shows the plan, your
  reference files, the Build buttons and the manuscript, and you can edit any
  plan file there.
- **With the Claude plugin**, just say what you're writing, or use
  `/writers-room:start`. Claude follows the same conversation guide and edits
  the files itself.
- **In Claude Code in this repository**, use the **story-session** skill. In
  Codex, point it at `.claude/skills/story-session/SKILL.md` (see
  `AGENTS.md`).

The files keep up with the conversation, and you can edit them yourself at
any point. The chat re-reads them before every change, so your edits win.
You don't need a finished plan to start building; a premise, a main character
and the first few chapters are plenty.

### Working together in the app

The reply appears as it is written, with activity such as reading a file or
updating the outline. **Stop** cancels the current turn; edits already made
are kept and still have their change cards. You can then send a different
instruction. One planning turn runs per project at a time.

Open a document and highlight a passage to **Discuss**, **Suggest
alternatives**, or **Revise** it. These actions put the passage and its file
into the message box so you can add your instructions before sending.
An agreed passage edit preserves the rest of the document and the previous
version. **Just exploring** lets you discuss possibilities with file-changing
tools disabled; turn it off when you want to apply a decision.

Expand **Compare changes** on a change card to see the before and after text
with nearby context. **Undo** refuses to overwrite a newer edit. Manual
editing also checks whether the file changed after you opened it, keeping
your unsaved draft in the editor if it did.

When attaching a file, choose where it belongs:

- **This chat (planning only)** is the default. Its text remains available
  when you return to this conversation, including after restarting the app.
- **This message only** supplies it for one turn.
- **Book reference** makes it available to this book's chats and the Press.
- **Series reference** makes it available across the series.

**References in this chat** lists retained attachments. You can open them or
remove them from future context. Removal leaves the saved copy on disk.
Uploads with the same name get separate filenames instead of replacing one
another.

Completed planning actions are saved during the turn. If a connection or
model fails, the chat keeps those actions and any partial reply. After an
app restart, an unfinished turn is marked interrupted; send a follow-up to
continue without automatically repeating its edits. Builds still require
the local app process to stay running.

Or plan by hand:

```bash
python scripts/room.py new "My Novel"
python scripts/room.py new "Book One" --series "My Series"   # start a series
python scripts/room.py new "Book Two" --series "My Series"   # add the next book
python scripts/room.py books                                 # everything in the library
python scripts/room.py status                                # chapters, words, what's out of date
```

The only format rule: each chapter in the outline starts with a
`## Chapter N` heading (a title after it is optional). Add a line such as
`- Words: 3500` to set a chapter's length, and a line such as
`- Ends at: Kael says his brother's name` to say where it stops, so it
doesn't run ahead of your plan. For a chapter that matters, the chat can help
you break it into scenes: who wants what, what's in the way, how it turns.
Above the chapters, an optional
`## The threads` section lists the promises the book makes and the characters
who change, one line each, so every chapter is written with them in view.

In `characters.md`, each character gets a `## Name` section. The suggested
lines are prompts, not required fields. The most useful one is **How they
talk**: two or three sample lines help every model keep each character
sounding like themselves.

### Renaming

```bash
python scripts/room.py rename "Mara" "Maren"            # shows every match, changes nothing
python scripts/room.py rename "Mara" "Maren" --apply    # makes the change
```

A rename covers the whole series: plans, chapters and story-so-far notes. It
matches whole words only ("Mara's" changes, "Marathon" doesn't) and leaves
history, build runs and reviews as a record of what was.

### The review gate (optional)

```bash
python scripts/room.py review
```

A different model reads everything (the plan and any chapters) and writes
numbered points to `notes/`, each with what it noticed, why it matters and a
suggested change, plus a blank **Your call** line. In the story-session chat,
you go through the points one at a time; the chat records your decision under
each one and makes only the changes you agree to. The chat offers a review
once when you're ready to build; skipping it is fine.

## The Press: build chapters

```bash
python scripts/press.py build next      # the next unwritten chapter
python scripts/press.py build all       # every unwritten chapter, in order
python scripts/press.py build 4         # rebuild chapter 4 (old version kept)
python scripts/press.py build 4 --rounds 2
```

For each chapter:

1. **Draft.** The writer model drafts it from the plan and every earlier
   chapter.
2. **Critique.** A different model checks the draft against your outline
   notes, the bible, the character sheets, continuity and the craft guide,
   and lists what to fix, or says no changes are needed.
3. **Revise.** The writer model revises using the critique. If a revision
   comes back much shorter than what it revised, it's discarded and the
   earlier text is kept.
4. **Save.** The result goes into `manuscript/`.

Chapters build in order, so each one reads the finished chapters before it.
Before building, the Press prints a rough token estimate; `build all` and
rebuilding an existing chapter ask before going ahead (`--yes` skips the
question). Each build reads your plan once at the start, so editing in the
Room during a long build can't leave a book half on one plan and half on
another.

Every build makes `runs/<time>/` containing a copy of the plan it used, each
chapter's draft, critique and revision, and `report.md` with words, revisions
kept, token usage and cost. If chapters keep coming in short, raise
`press.length_calibration` in `config/settings.yaml`.

Suggested rhythm: build the first two or three chapters one at a time, read
them, adjust the plan, then `build all`.

### Out-of-date chapters

The Press records which plan each chapter was built from. If you later change
a chapter's own outline section, `status` marks it **out of date**: rebuild
it, revise it with a note, or keep it. Changes to the bible or character
sheets are noted more quietly, since they usually don't need a rebuild.

### Smaller changes

```bash
python scripts/room.py revise 4 --note "more banter, less brooding"
python scripts/room.py polish 4                                    # light line edit
```

You can also edit chapter files by hand; later chapters will read your
version. Every rebuild, revision and polish keeps the previous version in
`manuscript/.history/`.

### Series

When a book is finished, write notes for the books after it:

```bash
python scripts/press.py story-so-far --title "Book One"
```

Later books read each earlier book in full until it has `story_so_far.md`,
then read the notes instead. The build estimate warns once a single call
passes about 500K tokens, where models start to read less reliably, and a
call is refused above 900K tokens (or when the model says it's too long); the
message says to write story-so-far notes when a series gets that long.

### Export

```bash
python scripts/press.py export          # export/manuscript.md
```

## Settings

In the app, **Settings** (bottom left) connects providers, picks which model
plays each role and sets the build options. It saves your keys in `.env` and
your choices in `config/settings.local.yaml`, both private to your computer.
The plugin asks for your key when you install it.

Underneath, `config/settings.yaml` holds:

- **Providers.** OpenRouter (recommended: one key, every model), Anthropic,
  OpenAI, Google, and a model running on your own computer (Ollama or
  llama.cpp). Each needs only its key, named by `api_key_env`.
- **Roles.** `studio_chat` is the app's planning chat (Claude Opus 5.5);
  `studio_writer` drafts and revises (DeepSeek V4 Pro); `studio_critic`
  critiques press drafts and `studio_reader` writes reviews and story-so-far
  notes (both Gemini 3.1 Pro). Every call sends the whole book, so pick models
  with ~1M-token context windows. No role caps its output length.
- **Press options.** `revision_rounds` (1), `default_chapter_words` (3000),
  `length_calibration` (1.0) and `min_revision_ratio` (0.6).

Run `python scripts/room.py check` to confirm your API key works and see the
credits used so far.

## Things to know

- **Models attend less to the middle of very long prompts.** The current task
  always comes last, and the critique checks each chapter against its
  outline notes.
- **Models copy their own habits.** With the whole book in view, a phrase a
  model likes can spread. The critic and the review both look for repeats.
- **Cost grows as the book grows**, because every call sends more of it. The
  Press estimates tokens before a build and reports real usage after.
