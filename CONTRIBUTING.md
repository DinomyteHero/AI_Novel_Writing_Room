# Contributing

Thanks for considering a contribution. Bug reports and ideas from writers are
as welcome as code.

## Set up

```bash
git clone https://github.com/DinomyteHero/AI_Novel_Writing_Room.git
cd AI_Novel_Writing_Room
pip install -r requirements-dev.txt
pytest -q
ruff check .
```

The tests never call a real model, so they don't need an API key. To try your
change in the app, run `python scripts/app.py`.

## Before you open a pull request

- **Read [CLAUDE.md](CLAUDE.md) first.** It holds the design rules and a map of
  the code. The project is deliberately small: plain Markdown files, whole-book
  context, one model call per step. Please don't reintroduce summarisers,
  retrieval, state databases or rigid craft schemas. If the model can read the
  whole book, it doesn't need them.
- **Keep craft guidance loose.** `prompts/studio/craft_guide.md` offers lenses,
  not rules. Changes there should make it friendlier for new writers, not
  stricter.
- **Write errors for writers.** Messages say in plain language what happened
  and how to fix it, never a traceback.
- **Add tests** for new behaviour, using `tests/fakes.py::FakeRouter` in place
  of real models.

## Bugs and questions

Open an [issue](https://github.com/DinomyteHero/AI_Novel_Writing_Room/issues)
for bug reports, design questions or feature ideas. Security issues go through
[SECURITY.md](SECURITY.md), not the public issue tracker.
