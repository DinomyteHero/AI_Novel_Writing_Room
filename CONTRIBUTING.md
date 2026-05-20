# Contributing

Thanks for considering a contribution. The full developer guide lives at
[docs/development/contributing.md](docs/development/contributing.md) — start
there for environment setup, testing conventions, and code-style notes. This
file is just the orientation page.

## TL;DR

```bash
git clone https://github.com/DinomyteHero/AI_Novel_Writing_Room.git
cd AI_Novel_Writing_Room
pip install -r requirements.txt
cp .env.example .env            # then fill in OPENROUTER_API_KEY
pytest -q                       # full suite, ~2 minutes
```

## Before you open a PR

- **Read [CLAUDE.md](CLAUDE.md) first** if your change touches the agent
  pipeline, the chapter packet, runtime flags, or any of the trusted-state
  stores. The lean pipeline has hard rules — most importantly, **don't
  re-introduce gates, a save-blocker layer, or retry loops**. The per-scene
  pipeline is a single forward pass.
- **Tests matter.** Add tests for new behaviour. Run the full suite locally;
  CI will run it again.
- **Don't add comments explaining what the code does** — well-named
  identifiers handle that. Comments are for *why* something non-obvious is
  the way it is.
- **Don't add backwards-compatibility shims** unless there's a concrete
  external caller that would break. The codebase deliberately keeps a
  narrow surface area.

## Bugs and questions

Open an [issue](https://github.com/DinomyteHero/AI_Novel_Writing_Room/issues)
for bug reports, design questions, or feature ideas. Security issues go
through [SECURITY.md](SECURITY.md), not the public issue tracker.

## What kind of contribution is welcome

- **Bug fixes** — always.
- **New agents or pipeline stages** — please discuss in an issue first; the
  lean single-pass invariant constrains where new stages can live.
- **Documentation improvements** — always welcome, and a good first PR.
- **New franchise worked-examples** — welcome, but follow the IP posture in
  [DISCLAIMER.md](DISCLAIMER.md): non-commercial, transformative,
  rightsholder-takedown-on-request.
- **Performance / cost work** — welcome; please include before/after numbers
  from `scripts/bench_prose_models.py` for prose-model changes.
