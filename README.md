# AI Writers' Room

A friendly tool for writing novels with AI: fanfiction or your own world, one
book or a whole series. You bring the idea and make the choices; the tool
helps you shape it, then builds the chapters. You don't need to know any
writing theory.

## Two halves: the Room and the Press

**The Room** is where you think. You talk with a planning chat (the
`story-session` skill in Claude Code). Bring whatever you have: a one-line
idea, some characters, a rough outline. The chat helps you flesh it out with
ideas and questions, and keeps your book's files up to date as you talk:
the story bible, the character sheets and the outline. Edit them yourself
whenever you like; your edits always win. Rename a character and it changes
everywhere. When you're ready, ask for an optional second opinion: a
different model reviews everything, and you go through its points together,
keeping what you agree with.

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

## Quick start

You need Python 3.10+ and an [OpenRouter](https://openrouter.ai/) API key.

```bash
git clone https://github.com/DinomyteHero/AI_Novel_Writing_Room.git
cd AI_Novel_Writing_Room
pip install -r requirements.txt
cp .env.example .env              # then paste your OPENROUTER_API_KEY into .env
python scripts/room.py check      # confirms the key works
```

Then plan in the `story-session` chat, or by hand:

```bash
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

Set in [`config/settings.yaml`](config/settings.yaml): DeepSeek V4 Pro writes
and revises; Gemini 3.1 Pro critiques and reviews. Both have roughly 1M-token
context windows, enough for a full novel and its plan in every call.

## License

Apache 2.0. See [LICENSE](LICENSE) and [DISCLAIMER.md](DISCLAIMER.md) for
notes on fanfiction and third-party material.
