"""Generic concept-seed installer — the franchise-agnostic replacement for
install_ruusan_seed.py.

Loads a raw concept seed, applies an optional ``workshop_patch.json``
through the seed_transforms / scene_card_translator primitives, extracts
embedded scene cards into per-file JSON under
``data/franchises/<slug>/books/<slug>/scene_cards/``, and writes the
enriched seed to ``data/franchises/<slug>/books/<slug>/concept_seed.json``.

The workshop_patch.json format is a named-section dict:

    {
      "voice_definition":        { ... },               optional
      "arc_phase_maps":          { "<name>": { ... } }, optional
      "promise_payoff_ledger":   [ ... ],               optional
      "subplots":                [ ... ],               optional
      "hooks":                   [ ... ],               optional
      "revelation_schedule":     [ ... ],               optional
      "terminology_registry":    [ ... ],               optional
      "relationship_arcs":       [ ... ],               optional
      "canon_profile":           { ... },               optional
      "force_mechanics":         { ... },               optional
      "canon_constraints":       { ... },               optional
      "referenced_characters":   [ ... ],               optional
      "quality_overrides":       { ... },               optional
      "workshop_origin":         { ... },               optional
      "stress_test_scores":      { ... },               optional
      "extended_metadata_fields": [ "field_a", ... ],   optional
      "structural_overrides":    { "26": "climax" },    optional
      "arc_type_map":            { "<name>": "enum" },  optional
      "tone_fallback":           "<enum>",              optional
      "canon_status_fallback":   "<enum>"               optional
    }

Every section is optional — a patch that supplies only ``voice_definition``
adds voice and leaves the rest of the seed untouched.

Order of transform application is fixed (see _apply_workshop_patch). Scene
cards are then extracted and written via translate_scene_card with the
patch's structural_overrides.

Path resolution uses ``ProjectPaths.from_concept_seed``; the target
directory is derived from the seed's ``meta.franchise`` and
``meta.project_title``. The ``base_dir`` argument lets tests install
into tmp paths without touching the committed tree.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.concept_workshop.scene_card_translator import translate_scene_card  # noqa: E402
from src.concept_workshop.seed_transforms import (  # noqa: E402
    apply_arc_phase_maps,
    apply_branch_point,
    apply_canon_constraints,
    apply_canon_profile,
    apply_force_mechanics,
    apply_hooks,
    apply_promise_payoff_ledger,
    apply_quality_overrides,
    apply_referenced_characters,
    apply_relationship_arcs,
    apply_revelation_schedule,
    apply_stress_test_scores,
    apply_subplots,
    apply_terminology_registry,
    apply_voice_definition,
    apply_workshop_origin,
    move_to_extended_metadata,
    normalize_enums,
)
from src.project_paths import ProjectPaths  # noqa: E402

CONCEPT_SEED_SCHEMA_PATH = REPO_ROOT / "schemas" / "concept_seed.json"
SCENE_CARD_SCHEMA_PATH = REPO_ROOT / "schemas" / "scene_card.json"


@dataclass
class InstallResult:
    seed_path: Path
    scene_card_paths: list[Path] = field(default_factory=list)
    character_count: int = 0
    scene_card_count: int = 0
    warnings: list[str] = field(default_factory=list)


def _apply_workshop_patch(seed: dict, patch: dict) -> None:
    """Apply a workshop_patch dict's named sections to the seed in fixed order.

    Ordering: enum normalization first (so downstream transforms see
    canonical values), then structural injections (arc maps, promises,
    subplots, hooks, revelations, terminology, relationship_arcs),
    then franchise profile (canon_profile, force_mechanics, canon_constraints),
    then peripheral (referenced_characters, quality_overrides, workshop_origin,
    stress_test_scores). move_to_extended_metadata runs last so any top-level
    fields targeted for relocation are captured after the injection phase.
    """
    apply_voice_definition(seed, patch.get("voice_definition"))
    normalize_enums(
        seed,
        tone_fallback=patch.get("tone_fallback", "heroic_with_weight"),
        canon_status_fallback=patch.get("canon_status_fallback", "AU"),
        arc_type_map=patch.get("arc_type_map"),
    )
    apply_arc_phase_maps(seed, patch.get("arc_phase_maps"))
    apply_promise_payoff_ledger(seed, patch.get("promise_payoff_ledger"))
    apply_subplots(seed, patch.get("subplots"))
    apply_hooks(seed, patch.get("hooks"))
    apply_revelation_schedule(seed, patch.get("revelation_schedule"))
    apply_terminology_registry(seed, patch.get("terminology_registry"))
    apply_relationship_arcs(seed, patch.get("relationship_arcs"))
    apply_canon_profile(seed, patch.get("canon_profile"))
    apply_force_mechanics(seed, patch.get("force_mechanics"))
    apply_canon_constraints(seed, patch.get("canon_constraints"))
    apply_referenced_characters(seed, patch.get("referenced_characters"))
    apply_quality_overrides(seed, patch.get("quality_overrides"))
    apply_workshop_origin(seed, patch.get("workshop_origin"))
    apply_stress_test_scores(seed, patch.get("stress_test_scores"))
    move_to_extended_metadata(seed, patch.get("extended_metadata_fields"))


def install_seed(
    input_path: Path | str,
    *,
    workshop_patch_path: Path | str | None = None,
    base_dir: str = ".",
    validate_seed: bool = True,
    validate_scene_cards: bool = True,
) -> InstallResult:
    """Install a raw concept seed into the franchise-scoped directory tree.

    Args:
        input_path: Path to the raw concept_seed.json to enrich.
        workshop_patch_path: Optional path to a workshop_patch.json.
        base_dir: Repository root to install under. Defaults to CWD; tests
            pass tmp_path to isolate the installation.
        validate_seed: Run jsonschema.validate on the enriched seed.
        validate_scene_cards: Run jsonschema.validate on each extracted
            scene card. Disable when the translator's partial output does
            not satisfy the schema's minLength constraints (as is the
            case for the raw Ruusan workshop format).

    Returns an InstallResult summarizing what was written.
    """
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"input seed not found: {input_path}")

    seed = json.loads(input_path.read_text(encoding="utf-8"))

    patch: dict = {}
    if workshop_patch_path is not None:
        workshop_patch_path = Path(workshop_patch_path)
        if not workshop_patch_path.exists():
            raise FileNotFoundError(
                f"workshop patch not found: {workshop_patch_path}"
            )
        patch = json.loads(workshop_patch_path.read_text(encoding="utf-8"))
        _apply_workshop_patch(seed, patch)

    paths = ProjectPaths.from_concept_seed(seed, base_dir=base_dir)
    paths.ensure_dirs()
    paths.ensure_franchise_meta(seed)

    # Phase 6.3b: copy branch_point from universe_meta into the seed so
    # canon_expert can read it from context at runtime (see D4 in the Phase
    # 6/7 plan). Runs AFTER ensure_franchise_meta so that a freshly-written
    # meta file still reflects any universe the user pre-populated. No-op
    # when no branch_point is declared — back-compat safe.
    universe_meta_path = paths.universe_meta_path
    if universe_meta_path and universe_meta_path.exists():
        try:
            universe_meta = json.loads(
                universe_meta_path.read_text(encoding="utf-8")
            )
            apply_branch_point(seed, universe_meta)
        except (OSError, json.JSONDecodeError):
            # Non-fatal: installer continues without divergence context.
            pass

    structural_overrides = patch.get("structural_overrides") or None

    # Extract embedded scene cards first (write to per-file JSON), then
    # the enriched seed — so if extraction fails the seed doesn't get
    # written with an inconsistent on-disk scene_cards/ directory.
    scene_card_schema = None
    if validate_scene_cards:
        scene_card_schema = json.loads(
            SCENE_CARD_SCHEMA_PATH.read_text(encoding="utf-8")
        )
    scene_card_paths: list[Path] = []
    warnings: list[str] = []
    for card in seed.get("scene_cards", []) or []:
        translated = translate_scene_card(
            card, structural_overrides=structural_overrides
        )
        ch = translated["chapter_number"]
        sn = translated["scene_number"]
        filename = f"chapter_{ch:02d}_scene_{sn:02d}.json"
        path = paths.scene_cards_dir / filename
        path.write_text(
            json.dumps(translated, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        scene_card_paths.append(path)
        if scene_card_schema is not None:
            try:
                jsonschema.validate(translated, scene_card_schema)
            except jsonschema.ValidationError as exc:
                warnings.append(
                    f"scene card {filename} fails schema: {exc.message}"
                )

    # Clear the embedded scene_cards array in the final seed — per the
    # workshop protocol documented in schemas/concept_seed.json:395, embedded
    # scene_cards are a workshop-only intermediate. The drafting pipeline
    # MUST NOT read them; canonical scene cards live at the per-file path
    # we just populated above. Emitting an empty list signals "embedded
    # cards consumed, extracted to files."
    if "scene_cards" in seed:
        seed["scene_cards"] = []

    paths.concept_seed_path.write_text(
        json.dumps(seed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if validate_seed:
        schema = json.loads(CONCEPT_SEED_SCHEMA_PATH.read_text(encoding="utf-8"))
        try:
            jsonschema.validate(seed, schema)
        except jsonschema.ValidationError as exc:
            warnings.append(
                f"enriched seed fails concept_seed schema: {exc.message}"
            )

    return InstallResult(
        seed_path=paths.concept_seed_path,
        scene_card_paths=scene_card_paths,
        character_count=len(seed.get("ensemble_cast", [])),
        scene_card_count=len(scene_card_paths),
        warnings=warnings,
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generic concept-seed installer. Loads a raw seed, applies an "
            "optional workshop_patch, extracts scene cards, and writes the "
            "enriched seed to its franchise-scoped location."
        ),
    )
    parser.add_argument("--input", required=True, help="Path to raw concept_seed.json")
    parser.add_argument(
        "--workshop-patch",
        default=None,
        help="Optional path to a workshop_patch.json",
    )
    parser.add_argument(
        "--base-dir",
        default=".",
        help="Repository root to install under (default: CWD)",
    )
    parser.add_argument(
        "--no-validate-seed",
        action="store_true",
        help="Skip jsonschema.validate on the enriched seed",
    )
    parser.add_argument(
        "--no-validate-scene-cards",
        action="store_true",
        help="Skip jsonschema.validate on extracted scene cards",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        result = install_seed(
            input_path=args.input,
            workshop_patch_path=args.workshop_patch,
            base_dir=args.base_dir,
            validate_seed=not args.no_validate_seed,
            validate_scene_cards=not args.no_validate_scene_cards,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote enriched seed to {result.seed_path}")
    print(f"Extracted {result.scene_card_count} scene card(s) "
          f"to {result.seed_path.parent / 'scene_cards'}")
    print(f"  characters: {result.character_count}")
    if result.warnings:
        print(f"  {len(result.warnings)} warning(s):")
        for w in result.warnings:
            print(f"    - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
