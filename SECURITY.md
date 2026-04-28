# Security Policy

## Reporting a vulnerability

If you believe you've found a security issue in this project, **please do not
open a public issue**. Instead, use one of the following channels:

1. **GitHub private vulnerability reporting** — preferred. Open the
   repository's **Security** tab and click *"Report a vulnerability"*. This
   routes the report privately to the maintainer.
2. **Direct contact** — if private reporting is unavailable, message the
   maintainer through their GitHub profile (`@DinomyteHero`) and we'll
   coordinate a private channel from there.

When reporting, please include:

- A description of the issue and its potential impact.
- Reproduction steps or a minimal example, if you have one.
- The commit hash or release tag you observed the issue on.
- Whether you've shared the report with anyone else.

We aim to acknowledge reports within seven days, and to either ship a fix or
provide a clear timeline within thirty days for non-trivial issues.

## Out of scope

- **Automated vulnerability scanners against deployed instances.** This is a
  research project run on personal infrastructure; please don't run scanners
  against any URL associated with this codebase. Static analysis of the
  source tree is welcome.
- **Trademark or copyright concerns** about third-party franchise material
  the pipeline operates on. Those belong in [DISCLAIMER.md](DISCLAIMER.md);
  open a regular issue or contact the maintainer for takedown requests.
- **Issues in upstream dependencies** (FastAPI, ChromaDB, llama.cpp, etc.).
  Please report those to the relevant project. If a dependency vulnerability
  affects how this project uses it, that part is in scope.

## Disclosure

We prefer coordinated disclosure: please give us a reasonable window to ship a
fix before going public. We're happy to credit reporters in the release notes
unless you'd rather stay anonymous.
