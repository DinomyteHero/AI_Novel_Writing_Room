# test-bench franchise

Low-stakes scratch franchise for flag-flip smoke tests. Per
`docs/architecture/architecture_upgrade_spec.md` §4.4, new runtime flags land
here before Ruusan or Betrayal — this directory is the canonical place to
verify a flag works end-to-end without risking production book quality.

## Current book(s)

- `books/classifier-smoke-test/` — enables
  `runtime.firewall.successor_classifier.enabled: true` to exercise the
  Slice 1 firewall's classifier-based soft-halt logic.

## Adding a new smoke-test book

1. Create `books/<slug>/concept_seed.json` with at minimum
   `meta.project_title` and `meta.franchise: "test-bench"`. Full pipeline
   runs additionally need `ensemble_cast`, `voice_definition`, a
   `scene_cards/` directory, etc. — see the Ruusan seed for the full shape.
2. Create `books/<slug>/runtime_overrides.yaml` with the flag(s) you want
   to flip on. Ruusan and Betrayal never get a runtime_overrides.yaml until
   their per-book parity test lands.
3. Confirm the flag resolves as expected:
   ```
   py -3 -c "from src.runtime_flags import resolve_flag; \
     import json; \
     seed = json.load(open('data/franchises/test-bench/books/<slug>/concept_seed.json')); \
     print(resolve_flag('runtime.<your>.<flag>', concept_seed=seed))"
   ```
