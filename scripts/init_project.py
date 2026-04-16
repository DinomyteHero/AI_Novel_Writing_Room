"""Scaffold a fresh project tree: franchise_meta, optional cosmology_meta,
and a schema-valid (but concept-workshop-pending) concept_seed.json.

The emitted seed passes ``jsonschema.validate`` against
``schemas/concept_seed.json`` but intentionally does NOT pass
``validate_concept_seed`` — the compliance validator enforces minimum
lengths and per-character arc completeness that only real authored
content can satisfy. The scaffold prints an explicit "next step"
reminder so the author (or the concept workshop, when Phase 4 ships)
knows what still needs to be filled in.

The canon_profile template (one of the five locked profiles) and the
default voice_definition template are copied directly into the seed.
Placeholders (`<EDIT_ME>`) are deliberately visible so the author can
grep for them.

Usage:
    python scripts/init_project.py \\
        --title "My Novel" \\
        --franchise "My Franchise" \\
        --depth original_light \\
        [--cosmology <id>] [--series <id>] \\
        [--voice-template default] \\
        [--base-dir .]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_paths import ProjectPaths  # noqa: E402

TEMPLATES_DIR = REPO_ROOT / "templates"
CONCEPT_SEED_SCHEMA_PATH = REPO_ROOT / "schemas" / "concept_seed.json"

CANON_PROFILE_TEMPLATES = {
    "fanfic_elseworlds",
    "fanfic_compliant",
    "original_deep",
    "original_light",
    "realistic",
}

# Canon-status default per profile. Every profile can be overridden via
# --canon-status but the default matches how the template reads.
DEFAULT_CANON_STATUS = {
    "fanfic_elseworlds": "AU",
    "fanfic_compliant": "canon_compliant",
    "original_deep": "original",
    "original_light": "original",
    "realistic": "original",
}

PLACEHOLDER = "<EDIT_ME>"

# The concept_seed schema enforces minLength on most narrative fields (what_if:50,
# thematic_argument:100, motivation:50, escalation:100, three_dimensions.*:50,
# weiland_arc.lie_believed:30, etc.). A "schema-valid" scaffold therefore has to
# ship placeholder content longer than a bare "<EDIT_ME>". These padded hints
# are visible ('EDIT ME —' in ASCII) so authors can grep for them and replace.
_HINT_50 = (
    "EDIT ME — describe this field in at least fifty characters of real content."
)
_HINT_100 = (
    "EDIT ME — describe this field in at least one hundred characters of real "
    "content so the concept_seed schema validates through the scaffold stage."
)
_HINT_30 = (
    "EDIT ME — describe this field (minimum thirty characters)."
)
_HINT_20 = "EDIT ME — describe this field (min 20 chars)."


def _load_template(subdir: str, name: str) -> dict:
    """Load a template JSON file and strip its ``_template_notes`` metadata key."""
    path = TEMPLATES_DIR / subdir / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"template not found: {path} "
            f"(available in {subdir}/: "
            f"{sorted(p.stem for p in (TEMPLATES_DIR / subdir).glob('*.json'))})"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_template_notes", None)
    return data


def _build_placeholder_character(role_hint: str) -> dict:
    """Minimal character dict that satisfies the concept_seed schema.

    Schema requires ``name``, ``role``, and ``three_dimensions`` with
    surface / backstory_inner_demons / action_under_pressure each at
    minLength:50. Ships padded placeholders so the scaffold validates;
    author replaces them with real content.
    """
    return {
        "name": f"{PLACEHOLDER} {role_hint} name",
        "role": role_hint,
        "three_dimensions": {
            "surface": _HINT_50,
            "backstory_inner_demons": _HINT_50,
            "action_under_pressure": _HINT_50,
        },
    }


def _build_minimal_seed(
    *,
    title: str,
    franchise: str,
    depth: str,
    canon_status: str,
    tone: str,
    target_word_count: int,
    cosmology_id: str | None,
    series_id: str | None,
    canon_profile: dict,
    voice_definition: dict,
) -> dict:
    """Assemble the schema-valid (but concept-workshop-pending) seed dict."""
    meta = {
        "project_title": title,
        "franchise": franchise,
        "canon_status": canon_status,
        "era": PLACEHOLDER,
        "tone": tone,
        "target_word_count": target_word_count,
    }
    if cosmology_id:
        meta["cosmology_id"] = cosmology_id
    if series_id:
        meta["series_id"] = series_id

    seed: dict = {
        "meta": meta,
        "premise": {
            "what_if": _HINT_50,
            "central_dramatic_question": PLACEHOLDER,
            "logline": PLACEHOLDER,
        },
        "conflict": {
            "primary_antagonistic_force": {
                "type": PLACEHOLDER,
                "motivation": _HINT_50,
                "escalation": _HINT_100,
            },
            "secondary_pressures": [_HINT_30],
            "lock_in_mechanism": _HINT_30,
        },
        "theme": {
            "thematic_premise": PLACEHOLDER,
            "thematic_argument": _HINT_100,
            "how_each_arc_tests_theme": {},
        },
        "ensemble_cast": [
            _build_placeholder_character("protagonist"),
            _build_placeholder_character("antagonist"),
        ],
        "canon_constraints": {
            "continuity": PLACEHOLDER,
            "canon_preserved": [],
            "style_constraints": [],
        },
        "canon_profile": canon_profile,
        "voice_definition": voice_definition,
    }
    # Record the depth choice so downstream tools (and humans) can see
    # which template seeded this project.
    seed["extended_metadata"] = {
        "scaffold_origin": {
            "init_tool": "scripts/init_project.py",
            "canon_profile_template": depth,
            "voice_template": "default",
        }
    }
    return seed


def init_project(
    *,
    title: str,
    franchise: str,
    depth: str,
    cosmology_id: str | None = None,
    series_id: str | None = None,
    voice_template: str = "default",
    tone: str = "heroic_with_weight",
    target_word_count: int = 100000,
    base_dir: str = ".",
) -> ProjectPaths:
    """Scaffold a fresh project tree at ``base_dir``.

    Returns the ``ProjectPaths`` instance for the new project so callers
    (tests, higher-level tools) can find the artifacts without re-deriving.
    """
    if depth not in CANON_PROFILE_TEMPLATES:
        raise ValueError(
            f"unknown canon_profile template {depth!r}; "
            f"choose one of {sorted(CANON_PROFILE_TEMPLATES)}"
        )

    canon_profile = _load_template("canon_profile", depth)
    voice_definition = _load_template("voice_definition", voice_template)
    canon_status = DEFAULT_CANON_STATUS[depth]

    seed = _build_minimal_seed(
        title=title,
        franchise=franchise,
        depth=depth,
        canon_status=canon_status,
        tone=tone,
        target_word_count=target_word_count,
        cosmology_id=cosmology_id,
        series_id=series_id,
        canon_profile=canon_profile,
        voice_definition=voice_definition,
    )

    paths = ProjectPaths.from_concept_seed(seed, base_dir=base_dir)
    paths.ensure_dirs()
    paths.ensure_franchise_meta(seed)
    if cosmology_id:
        paths.ensure_cosmology_meta(cosmology_name=cosmology_id)

    # Structural validation: scaffold must pass jsonschema.validate even
    # though validate_concept_seed will report pending content.
    schema = json.loads(CONCEPT_SEED_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(instance=seed, schema=schema)

    paths.concept_seed_path.write_text(
        json.dumps(seed, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return paths


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Scaffold a fresh project tree under data/franchises/<slug>/"
            "books/<slug>/. Emits a schema-valid concept_seed.json with "
            "placeholder content that the concept workshop or author fills in."
        ),
    )
    parser.add_argument("--title", required=True, help="Project / book title")
    parser.add_argument(
        "--franchise",
        required=True,
        help="Franchise name (slugified via src.project_paths._slugify_franchise)",
    )
    parser.add_argument(
        "--depth",
        required=True,
        choices=sorted(CANON_PROFILE_TEMPLATES),
        help="Which canon_profile template to seed the book with",
    )
    parser.add_argument(
        "--cosmology",
        dest="cosmology_id",
        default=None,
        help="Optional cosmology_id for Sanderson-style shared cosmology projects",
    )
    parser.add_argument(
        "--series",
        dest="series_id",
        default=None,
        help="Optional series_id for multi-book projects",
    )
    parser.add_argument(
        "--voice-template",
        default="default",
        help="voice_definition template name (default: 'default')",
    )
    parser.add_argument(
        "--tone",
        default="heroic_with_weight",
        help="Tone enum value for meta.tone (default: heroic_with_weight)",
    )
    parser.add_argument(
        "--target-word-count",
        type=int,
        default=100000,
        help="Target novel word count (default: 100000)",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Repository root to scaffold under (default: current directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        paths = init_project(
            title=args.title,
            franchise=args.franchise,
            depth=args.depth,
            cosmology_id=args.cosmology_id,
            series_id=args.series_id,
            voice_template=args.voice_template,
            tone=args.tone,
            target_word_count=args.target_word_count,
            base_dir=args.base_dir,
        )
    except (FileNotFoundError, ValueError, jsonschema.ValidationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Scaffolded project: {paths.display_name}")
    print(f"  concept_seed:    {paths.concept_seed_path}")
    if paths.franchise_dir:
        print(f"  franchise_meta:  {paths.universe_meta_path}")
    if paths.cosmology_dir:
        print(f"  cosmology_meta:  {paths.cosmology_meta_path}")
    print(f"  scene_cards:     {paths.scene_cards_dir}")
    print()
    print("Next step: the concept seed is schema-valid but compliance-pending.")
    print("  - Hand-author meta.era, premise, conflict, theme, and ensemble_cast,")
    print("    or run the concept workshop (Phase 4) to populate them.")
    print("  - Look for '<EDIT_ME>' placeholders throughout the seed.")
    print(f"  - When ready, run: python -m src.concept_workshop.compliance_validator --seed {paths.concept_seed_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
