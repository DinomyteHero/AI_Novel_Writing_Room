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
  a series). Each project page starts a new chat about the whole book; start
  another for a single question or a separate piece of work. Every file change
  shows as a card with **Undo**; **Book** opens the plan, your reference
  files, the manuscript and the build status, and you can edit any plan file
  there. **Build** at the top of a chat runs the Press.
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

A project's page is kept simple, like a project in Claude: a box that starts
a new chat, your recent chats, and a **Book** button that opens the plan,
reference, manuscript and notes. The same **Book** button in a chat opens it
beside the conversation. Start a new chat for each piece of work: a scene, a
review, a brainstorm. **Build** at the top of a chat opens the estimate card,
where you choose the next chapter or all remaining. Under the message box you
can see and change the chat model and its reasoning effort; each chat keeps
its own choice. The picker has a search bar and lists current models only;
older models are hidden. Open a chapter and
press **Read** for a wide, book-like reading view; highlight a passage and
press **Ask about this**, then type what you want. The theme is in
**Settings > Appearance**. On a phone, the menu button opens the sidebar.

The reply appears as it is written, with activity such as reading a file or
updating the outline. A small line under the reply shows what that turn cost:
the number of model calls and the tokens in and out. While the turn runs, a
work log shows what the Room is reading, checking, searching or changing; it
stays under the reply as a record. Open the Book panel's **What the book
sends** to see the token cost of each part. **Stop** cancels the current turn;
edits already made are kept and still have their change cards. You can then
send a different instruction. One planning turn runs per project at a time.

Selecting a passage puts its document and text into the message box, so you
can ask for a discussion, alternatives or a change in your own words. An
agreed passage edit preserves the rest of the document and the previous
version. If you say you are just exploring, the Room discusses without
changing files.

**Settings > Changes > Review changes before saving** stages planning edits,
passage edits and chapter revisions instead of saving them. Each one appears
as a card with **Use suggestion** and **Keep original**. If the file changed
after the suggestion was staged, it is marked stale and both versions are
kept. Once accepted, it becomes a normal change card with **Undo**.

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
the local app process to stay running. If it stops before a run writes its
report, the Book panel says the build was interrupted; finished chapters are
saved and starting a new build is safe.

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
doesn't run ahead of your plan. Optional `POV`, `Threads moved` and
`Emotional turn` lines help when a chapter needs them. For a chapter that
matters, the chat can help you break it into scenes: who wants what, what's in
the way, how it turns. Above the chapters, an optional
`## The threads` section lists the promises the book makes and the characters
who change, one line each, so every chapter is written with them in view.

In the story bible, **The reader's promise** names the experience the book
owes a reader (its genre or tradition, books it should sit beside, what would
feel like a betrayal). **What this book is doing on purpose** records the
choices a general craft rule would call mistakes: a slow opening, a static
character, an unreliable narrator, a stylised voice. The co-writer and critic
read both before the craft guide; they outrank it. A deliberate choice is
judged by whether its effect lands, not by whether it follows the rule.

In `characters.md`, each character gets a `## Name` section. The suggested
lines are prompts, not required fields. The most useful one is **How they
talk**: two or three sample lines help every model keep each character
sounding like themselves. Optional lines for what they want and need, what
they believe that isn't true, and what they're afraid of give the story
something to test.

### Renaming

```bash
python scripts/room.py rename "Mara" "Maren"            # shows every match, changes nothing
python scripts/room.py rename "Mara" "Maren" --apply    # makes the change
```

A rename covers the whole series: plans, reference notes, chapters and
story-so-far notes. It matches whole words only ("Mara's" changes, "Marathon"
doesn't) and leaves build runs and reviews as a record of what was. Every
changed file keeps its previous version in `.history/`, and the change card in
the app can undo the whole rename.

### The review gate (optional)

```bash
python scripts/room.py review
```

A different model reads everything (the plan and any chapters) and writes
numbered points to `notes/`, each with the passage it noticed, what it does to
a reader, why it matters for the book's promise, a suggested change, another
option and what to protect, plus a blank **Your call** line. In the
story-session chat, you go through the points one at a time; the chat records
your decision under each one and makes only the changes you agree to. The chat
offers a review once when you're ready to build; skipping it is fine. In the
app, just ask in a chat. The chat can give its own view, or call the review
tool to bring in a different model and save numbered points to `notes/`, then
walk you through them. For a reader's reaction rather than a plan check, ask
for a fresh-eyes read of one chapter: that model sees only the chapter, not
the plan or earlier chapters.

### Stuck? Fresh ideas

Tell the chat you're stuck and it picks the gap that matters most and offers
three directions. In the app, the selected chat model can do this itself, or
call its ideas tool for a different model's options. From the command line or
the Claude plugin, for a second mind:

```bash
python scripts/room.py ideas
```

A different model reads everything and writes two or three options for each
of the thinnest parts of your plan to `notes/`, with its pick and a blank
**Your call** line. The app opens these files on a point-by-point screen. Go
through them like a review: use the pick, skip it, or choose something else.
Nothing goes into your plan until you choose.

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

To turn a standalone into a series, ask the Room to add the next book (or
run `python scripts/room.py new "Book Two" --series "Book One's Title"`). The
project becomes a series: a `series_bible.md` appears, the books are
numbered, and the new book starts with a copy of the first book's
characters. Decide what the series is called (edit the heading in
`series_bible.md` if it differs from book one), then move the world, rules
and arc that both books share out of book one's story bible and into the
series bible. The Room can do that with you.

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

In the app, **Settings** (bottom left) connects providers, picks the models
for the Press and background reads, and sets the build options, appearance
and review preferences. The chat model and reasoning effort are chosen in
each chat, under its message box, and each chat keeps its own. Under
**Who does what**, each role is a dropdown; older models are hidden from
both lists. Settings saves
your keys in `.env` and your role choices in `config/settings.local.yaml`,
both private to your computer. The plugin asks for your key when you install
it.

Underneath, `config/settings.yaml` holds:

- **Providers.** OpenRouter (recommended: one key, every model), Anthropic,
  OpenAI, Google, and a model running on your own computer (Ollama or
  llama.cpp). Each needs only its key, named by `api_key_env`.
- **Roles.** `studio_chat` is the default for the app's chat, which can also
  search the web and read pages; each chat can pick a different model and
  reasoning effort. `studio_writer` drafts and revises at high reasoning
  effort (both Gemini 4 Argon); `studio_critic` critiques press drafts (Claude
  Sonnet 5.5, a different model from the writer); `studio_reader` writes
  reviews and ideas (also Sonnet 5.5; switch it to Opus, Kimi or GLM if you
  want a second opinion from a separate family); `studio_notes` writes
  story-so-far notes (DeepSeek V4.1 Flash 1017). Every call sends the whole
  book, so pick models with ~1M-token context windows. No role caps its output
  length. Web searches cost a little extra through OpenRouter (under a cent
  each).
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
