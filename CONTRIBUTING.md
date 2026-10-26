# Contributing

Thanks for considering a contribution.

```bash
git clone https://github.com/DinomyteHero/AI_Novel_Writing_Room.git
cd AI_Novel_Writing_Room
pip install -r requirements.txt
cp .env.example .env            # then fill in OPENROUTER_API_KEY
pytest -q
ruff check .
```

## Before you open a PR

- **Read [CLAUDE.md](CLAUDE.md) first.** The project is deliberately small: plain
  Markdown files, whole-book context, one model call per step. Please don't
  re-introduce summarisers, retrieval, state databases or rigid craft schemas.
  If the model can read the whole book, it doesn't need them.
- **Keep craft guidance loose.** `prompts/studio/craft_guide.md` offers lenses,
  not rules. Changes there should make it friendlier for new writers, not
  stricter.
- **Add tests** for new behaviour. Tests must not call real models; use a fake
  router like the one in `tests/test_studio.py`.

## Bugs and questions

Open an [issue](https://github.com/DinomyteHero/AI_Novel_Writing_Room/issues)
for bug reports, design questions or feature ideas. Security issues go
through [SECURITY.md](SECURITY.md), not the public issue tracker.
