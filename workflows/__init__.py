"""Workflow kit — six concept-authoring surfaces, three ingress modes each.

Each surface package (universe_builder, canon_drafter, voice_discovery,
character_forge, outline_planner, scene_card_authoring) exposes:
    schema.json   - canonical output contract
    SKILL.md      - ingress 1: interactive chat session
    api.py        - ingress 2: programmatic / headless
    importers/    - ingress 3: external format normalizers
    validate.py   - schema + completeness checks
    compile.py    - emit this surface's slice for the bundle compiler

The single entry point a pipeline consumes is the bundle compiler at
``scripts/compile_bundle.py``, which merges all surface artifacts into the
canonical ``concept_seed.json`` and ``scene_cards/`` tree.
"""
