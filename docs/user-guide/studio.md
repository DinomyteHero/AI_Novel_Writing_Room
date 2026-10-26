# Studio: Write a Book in Conversation

The studio is the simplest way to make a book here. You plan in plain
conversation, the plan lives in a few Markdown files you can edit any time,
and each chapter is drafted by a model that reads the whole book so far.

There are no schemas to fill in and no compile step. Your book is one folder:

```text
story/
  story_bible.md     premise, feel, world, how it's told, things to keep true
  characters.md      a sheet per character: wants, obstacles, how they talk
  outline.md         one "## Chapter N" section per chapter
  chapters/          chapter_01.md, chapter_02.md, ... (earlier versions in .history/)
  notes/             reader reviews
  export/            the stitched manuscript
```

An original book's folder is `data/projects/<title-slug>/story/`, which git
ignores, so it stays private to your machine. A fanfiction book's folder is
`data/franchises/<franchise-slug>/books/<title-slug>/story/`.

## 1. Plan in conversation

In Claude Code, start the **story-session** skill and tell it what you have:
a one-line idea, a few characters, a rough outline, or a document to paste
in. It files what you bring into the story bible, character sheets and
outline in your own words, then helps you flesh it out with options and
questions. In Codex, point it at `.claude/skills/story-session/SKILL.md` (see
`AGENTS.md`).

The files keep up with the conversation, and you can edit them yourself at
any point. The session re-reads them before every change, so your edits win.

You don't need a finished plan before drafting. A premise, a main character
and a first few chapters is plenty; the rest can be discovered.

## 2. Or plan by hand

```bash
python scripts/studio.py new --title "My Novel"
# fanfiction:
python scripts/studio.py new --title "My Fic" --franchise "Star Wars (Legends EU)"
```

This creates the folder with a starter `story_bible.md`, `characters.md` and
`outline.md`. Fill them in however suits you. The only format rule is that
each chapter in the outline starts with a `## Chapter N` heading (a title
after it is optional).

In `characters.md`, each character gets a `## Name` section. The suggested
lines (wants, what's in the way, how they talk, and so on) are prompts, not
required fields. The most useful one is **How they talk**: two or three
sample lines of dialogue help the co-writer keep each character sounding
like themselves. Walk-on characters get one line each under "Minor
characters". For a book made before `characters.md` existed, run `new` again
to add it; existing files are never overwritten.

## 3. Draft, revise, review

Set `OPENROUTER_API_KEY` first. Then:

```bash
python scripts/studio.py draft next --title "My Novel"          # the next undrafted chapter
python scripts/studio.py draft 4 --title "My Novel" --words 3000 --note "open in the rain"
python scripts/studio.py revise 4 --title "My Novel" --note "more banter, less brooding"
python scripts/studio.py polish 4 --title "My Novel"            # light line edit
python scripts/studio.py review --title "My Novel"              # whole-book reader notes
python scripts/studio.py status --title "My Novel"
python scripts/studio.py export --title "My Novel"
```

- **draft** refuses to overwrite an existing chapter unless you pass
  `--force`. Use **revise** to change one.
- Every redraft, revision and polish keeps the previous version in
  `chapters/.history/`.
- You can edit chapter files by hand. Later chapters will see your version.

## How it works

Every call sends the whole book: the story bible, the character sheets, the
outline and every chapter written so far, in full. Nothing is summarised or
looked up, so continuity comes from the model seeing everything. A finished 80,000-word
novel plus its notes is roughly 150–200K tokens, well inside the ~1M-token
windows of the default models. The tool refuses to send more than 900K
tokens in one call.

Models are set in `config/settings.yaml`:

- `agent_routing.studio_writer` drafts, revises and polishes (DeepSeek V4 Pro
  by default).
- `agent_routing.studio_reader` writes reviews (Gemini 3.1 Pro by default).

Craft guidance is deliberately loose: `prompts/studio/craft_guide.md` holds a
handful of lenses, not rules, that the planning chat, the drafter and the
reviewer all share. It's short and written for writers, so it's worth a read.
Your own notes in the story bible always win over it.

Things to know:

- **Models attend less to the middle of very long prompts.** Keep each
  chapter's outline notes clear; they're placed last in every prompt for
  this reason.
- **Models copy their own habits.** With the whole book in view, a phrase a
  model likes can spread. The reader review counts repeated habits so you
  can catch them.
- **Drafts often come in short.** Ask for a length with `--words`, and
  expect to ask high: DeepSeek V4 Pro has delivered well under the requested
  length in past benchmarks.
- **Cost grows as the book grows**, because every call sends more of the
  book. Providers that cache repeated prompt prefixes make this much cheaper.
