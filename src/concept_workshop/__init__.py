"""Concept Workshop helpers.

The interactive workshop_runner CLI was retired in favour of the per-surface
workflow kit (see `workflows/` and `.claude/skills/`). The remaining modules
in this package are the canonical homes for three pieces of concept-seed
infrastructure that survived the migration:

- `compliance_validator` — schema + cross-surface validation for concept seeds.
- `series_manager` — series-level state and book-spawn helpers.
- `stress_test` — adversarial structural/character/hook/series stress tests.

These are not shims. The historical re-export shims at `seed_transforms.py`,
`scene_card_translator.py`, and `voice_discovery.py` were removed; their
canonical locations are under `workflows/_shared/` and `workflows/voice_discovery/`.
"""
