# AI Writers' Room

A friendly tool for writing a novel with an AI co-writer: fanfiction or your
own original world. You bring the idea; it helps you shape it, then drafts
the book with you chapter by chapter. You don't need to know any writing
theory.

## How it works

1. **Plan in conversation.** In Claude Code, use the `story-session` skill and
   bring whatever you have: a one-line idea, some characters, a rough outline,
   or notes to paste in. The chat helps you flesh it out with ideas and
   questions, and keeps three plain files up to date as you talk:
   `story_bible.md`, `characters.md` and `outline.md`. Edit them yourself
   whenever you like; your edits always win.
2. **Draft chapter by chapter.** Each chapter is written by a model that reads
   your whole book so far (the story bible, character sheets, outline and
   every chapter in full), so it remembers everything.
3. **Revise and review.** Ask for changes in plain words ("more banter, less
   brooding"), get a light polish, or have the model read the whole book and
   write you friendly, specific notes.

Your book is one folder of Markdown files you can open in any editor:

```text
story/
  story_bible.md     premise, feel, world, how it's told, things to keep true
  characters.md      a sheet per character: wants, obstacles, how they talk
  outline.md         one "## Chapter N" section per chapter
  chapters/          chapter_01.md, chapter_02.md, ... (earlier versions in .history/)
  notes/             reader reviews
  export/            the whole book in one file
```

## Quick start

You need Python 3.10+ and an [OpenRouter](https://openrouter.ai/) API key.

```bash
git clone https://github.com/DinomyteHero/AI_Novel_Writing_Room.git
cd AI_Novel_Writing_Room
pip install -r requirements.txt
cp .env.example .env          # then paste your OPENROUTER_API_KEY into .env
```

Then:

```bash
python scripts/studio.py new --title "My Novel"
# fanfiction: add --franchise "Star Wars (Legends EU)"

python scripts/studio.py draft next --title "My Novel"
python scripts/studio.py revise 1 --title "My Novel" --note "more banter, less brooding"
python scripts/studio.py polish 1 --title "My Novel"
python scripts/studio.py review --title "My Novel"
python scripts/studio.py status --title "My Novel"
python scripts/studio.py export --title "My Novel"
```

See the [Studio guide](docs/user-guide/studio.md) for details.

## Craft, loosely

Craft guidance lives in one short file,
[`prompts/studio/craft_guide.md`](prompts/studio/craft_guide.md). It gives you
lenses, not rules: an eight-line "story spine", six questions worth answering
eventually, "but/therefore, not and then", promises that progress and pay
off, and wins that come with a catch. The planning chat and the drafter both
use it, and your own notes in the story bible always win over it.

## Models

Set in [`config/settings.yaml`](config/settings.yaml):

- `studio_writer` drafts, revises and polishes (DeepSeek V4 Pro by default).
- `studio_reader` writes reviews (Gemini 3.1 Pro by default).

Both have roughly 1M-token context windows, enough for a full novel and its
notes. The tool refuses to send more than 900K tokens in one call.

## License

Apache 2.0. See [LICENSE](LICENSE) and [DISCLAIMER.md](DISCLAIMER.md) for
notes on fanfiction and third-party material.
