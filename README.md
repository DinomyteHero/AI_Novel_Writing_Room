# AI Writers' Room

A friendly tool for writing novels with AI: fanfiction or your own world, one
book or a whole series. You bring the idea and make the choices; the tool
helps you shape it, then builds the chapters. You don't need to know any
writing theory.

## Two halves: the Room and the Press

**The Room** is where you think. You talk with a planning chat (in the app,
or Claude with the Writers Room plugin). Bring whatever you have: a one-line
idea, some characters, a rough outline. The chat helps you flesh it out with
ideas and questions, and keeps your book's files up to date as you talk:
the story bible, the character sheets and the outline. Edit them yourself
whenever you like; your edits always win. Rename a character and it changes
everywhere. A standalone book is a series of one: when you're ready for a
sequel, ask the Room to add the next book, and it becomes a series. When
you're ready, ask for an optional second opinion: a fresh model can review
everything, and you go through its points together, keeping what you agree
with. If you'd rather see a change before it lands, turn on **Review changes
before saving** in Settings: the Room stages the edit, and you choose **Use
suggestion** or **Keep original**.

**The Press** is where chapters get made, without you sitting there. Build
one chapter at a time to find the voice, or the whole book at once. For each
chapter, one model drafts, a different model critiques the draft against your
plan, and the first revises it. Every model call reads your whole plan and
every chapter before it, so the book remembers everything. Each build leaves
a report of what it did.

```text
  The Room (you + chat)                          The Press (automatic)
  ─────────────────────                          ─────────────────────
  ideas ─▶ story bible, characters, outline ─▶ [optional review] ─▶ build:
           (living files you can edit)                          draft ─▶ critique ─▶ revise
                       ▲                                                   │
                       └──────── react, revise, change the plan ◀─────────┘
```

## Three ways to use it

All three work on the same files, so you can switch between them.

### The app

A writing app in your browser, laid out like Claude: books, chats, and a
**Book** panel that opens beside the conversation. You need Python 3.10+ and
an API key from [OpenRouter](https://openrouter.ai/keys) (one key reaches
every model; Anthropic, OpenAI, Google or a model on your own computer also
work).

```bash
git clone https://github.com/DinomyteHero/AI_Novel_Writing_Room.git
cd AI_Novel_Writing_Room
pip install -r requirements.txt
python scripts/app.py             # opens http://127.0.0.1:8765/
```

Add your key in **Settings** (bottom left), then type an idea on the home
page. The **+** under the box starts a new book or a series. Each project
page starts a new chat about the book; **Build** at the top of a chat runs
the Press, after showing its estimate.

### The Claude plugin (Cowork and Claude Code)

Claude itself becomes the Room: it plans with you and edits the files, and
the plugin's tools add second opinions, renames and the Press. In Cowork, go
to **Customize > Plugins > Add > Add marketplace**, choose **Add from a
repository**, enter `DinomyteHero/AI_Novel_Writing_Room`, then install
**Writers Room** and add your OpenRouter key in its settings. In Claude Code:

```bash
claude plugin marketplace add DinomyteHero/AI_Novel_Writing_Room
claude plugin install writers-room@writers-room
```

Then say what you're writing, or use `/writers-room:start`,
`/writers-room:review` and `/writers-room:build`. The plugin's tools need
Python 3.10+ on your computer; they install what else they need on first run.

### The command line

```bash
cp .env.example .env              # then paste your OPENROUTER_API_KEY into .env
python scripts/room.py check      # confirms the key works
python scripts/room.py new "My Novel"           # or add --series "My Series"
python scripts/room.py review                   # optional second opinion
python scripts/press.py build next              # one chapter, then read it
python scripts/press.py build all               # the rest, unattended
python scripts/room.py status
python scripts/press.py export
```

Your books live in `library/`, which git ignores, so they stay private to
your machine. See the [guide](docs/guide.md) for everything else.

## Craft, loosely

Craft guidance lives in one short file,
[`prompts/studio/craft_guide.md`](prompts/studio/craft_guide.md): a handful
of friendly lenses, not rules, that the planning chat and every model share.
Your own notes in the story bible always win over it.

## Models

Set in [`config/settings.yaml`](config/settings.yaml), or in the app's
Settings: Gemini 4 Argon is the app's planning chat (with web search), and
writes and revises chapters; Claude Sonnet 5.5 critiques each draft and gives
reviews and ideas, so a different model reads the book; and DeepSeek V4.1 Flash
1017 writes story-so-far notes, all through OpenRouter by default.
Each has a roughly 1M-token context window, enough for a full novel and its
plan in every call.

## License

Apache 2.0. See [LICENSE](LICENSE) and [DISCLAIMER.md](DISCLAIMER.md) for
notes on fanfiction and third-party material.
