# test-bench franchise

Low-stakes scratch franchise for flag-flip smoke tests. New `runtime.*` flags
are exercised here before they are enabled on a shipping book — this directory
is the canonical place to verify a flag works end-to-end without risking
production book quality. Ruusan and Betrayal never get a `runtime_overrides.yaml`
until their per-book parity test signs off (the guard tests live in
`tests/test_runtime_flags.py`).

## Current book(s)

None. Add a smoke-test book when you need to exercise a new flag.

## Adding a new smoke-test book

1. Create `books/<slug>/concept_seed.json` with at minimum
   `meta.project_title`, `meta.franchise: "test-bench"`, and
   `compile_metadata.plan_approved: false` — test-bench seeds are scratch, never
   approve them. A full pipeline run additionally needs `ensemble_cast`,
   `voice_definition`, a `scene_cards/` directory, etc. — see the Ruusan seed
   for the full shape.
2. Create `books/<slug>/runtime_overrides.yaml` with the flag(s) you want to
   flip on, e.g.:
   ```yaml
   runtime:
     rhythm_validator:
       enabled: true
   ```
   Standby flags worth smoke-testing: `rhythm_validator`, `rhythm_editor`,
   `revision_debt`, `promise_ledger`, `continuity_validator`.
3. Confirm the flag resolves as expected:
   ```
   py -3 -c "from src.runtime_flags import resolve_flag; \
     import json; \
     seed = json.load(open('data/franchises/test-bench/books/<slug>/concept_seed.json')); \
     print(resolve_flag('runtime.<your>.<flag>', concept_seed=seed))"
   ```

Flag-resolution precedence (first match wins, highest priority last):
`config/settings.yaml` < franchise `runtime_overrides.yaml` < book
`runtime_overrides.yaml` < CLI `--runtime-flag`.
