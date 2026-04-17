"""Bundle compiler — single entry point that turns six surface artifacts
into the canonical ``concept_seed.json`` + ``scene_cards/`` tree the
pipeline consumes.

Reads ``data/franchises/<fr>/books/<bk>/workflows/{universe,canon,voice,
characters,outline}.json`` plus ``workflows/scene_cards.json`` (and/or
``workflows/scene_cards/*.json``), applies the seed_transforms in the
same fixed order as ``scripts/install_seed.py::_apply_workshop_patch``,
validates via ``compliance_validator.validate_concept_seed`` and per-card
``schemas/scene_card.json``, then writes:

    data/franchises/<fr>/books/<bk>/concept_seed.json
    data/franchises/<fr>/books/<bk>/scene_cards/chapter_NN_scene_NN.json
    data/franchises/<fr>/books/<bk>/compile_report.json

The compiler is idempotent: re-running with unchanged surface artifacts
produces byte-identical seed and per-card output (timestamps live only in
compile_report.json).

Usage:
    python scripts/compile_bundle.py --franchise <slug> --book <slug>
                                     [--base-dir .] [--strict]

``--strict`` makes warnings fail-exit; default is report-only on the
scene_cards-empty case (pipeline auto-generates downstream).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.concept_workshop.compliance_validator import validate_concept_seed  # noqa: E402
from src.project_paths import ProjectPaths  # noqa: E402
from workflows._shared.scene_card_translator import translate_scene_card  # noqa: E402
from workflows._shared.seed_transforms import (  # noqa: E402
    apply_arc_phase_maps,
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

CONCEPT_SEED_SCHEMA_PATH = REPO_ROOT / "schemas" / "concept_seed.json"
SCENE_CARD_SCHEMA_PATH = REPO_ROOT / "schemas" / "scene_card.json"

# Required surfaces. Missing any of these always fails (exit 1).
_REQUIRED_SURFACES = ("universe", "canon", "voice", "characters", "outline")


@dataclass
class CompileReport:
    franchise: str
    book: str
    surfaces_present: dict = field(default_factory=dict)
    surfaces_missing: list[str] = field(default_factory=list)
    compliance: dict = field(default_factory=dict)
    schema_errors: list[str] = field(default_factory=list)
    scene_card_count: int = 0
    scene_card_errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "franchise": self.franchise,
            "book": self.book,
            "surfaces_present": self.surfaces_present,
            "surfaces_missing": self.surfaces_missing,
            "compliance": self.compliance,
            "schema_errors": self.schema_errors,
            "scene_card_count": self.scene_card_count,
            "scene_card_errors": self.scene_card_errors,
            "warnings": self.warnings,
            "generated_at": self.generated_at,
        }


def _load_surface(path: Path) -> dict | None:
    """Load a surface artifact JSON, returning None when absent."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _load_scene_cards(workflows_dir: Path) -> list[dict]:
    """Read scene cards from the surface envelope or per-card directory.

    Prefers ``workflows/scene_cards/`` (per-card files) when present;
    falls back to ``workflows/scene_cards.json`` envelope.
    """
    per_card_dir = workflows_dir / "scene_cards"
    if per_card_dir.exists():
        cards: list[dict] = []
        for path in sorted(per_card_dir.glob("chapter_*_scene_*.json")):
            cards.append(json.loads(path.read_text(encoding="utf-8")))
        if cards:
            return cards

    envelope_path = workflows_dir / "scene_cards.json"
    if envelope_path.exists():
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        return list(envelope.get("scene_cards") or [])

    return []


def _build_seed(
    universe: dict,
    canon: dict,
    voice: dict,
    characters: dict,
    outline: dict,
) -> dict:
    """Assemble the merged concept_seed dict from surface artifacts.

    Mirrors ``scripts/install_seed.py::_apply_workshop_patch`` ordering so
    validation semantics stay identical to the legacy installer path.
    """
    seed: dict = {}

    # universe-builder: meta block goes in first so subsequent transforms
    # can read meta.tone, meta.canon_status, etc. via normalize_enums.
    seed["meta"] = dict(universe.get("meta") or {})

    # canon-drafter: canon_constraints is required; compliance validator
    # cares about this section's continuity field.
    seed["canon_constraints"] = dict(canon.get("canon_constraints") or {})

    # Apply transforms in the legacy installer's fixed order.
    apply_voice_definition(seed, voice.get("voice_definition"))
    normalize_enums(
        seed,
        # Use the universe's existing canonical values; no fallback munging.
        # The surfaces are responsible for emitting canonical enums.
    )
    apply_arc_phase_maps(seed, outline.get("arc_phase_maps"))

    # Outline-planner skeletons.
    apply_promise_payoff_ledger(seed, outline.get("promise_payoff_ledger"))
    apply_subplots(seed, outline.get("subplots"))
    apply_hooks(seed, outline.get("hooks"))
    apply_revelation_schedule(seed, outline.get("revelation_schedule"))
    if outline.get("structural_notes"):
        seed["structural_notes"] = outline["structural_notes"]

    # Canon-drafter remaining slices.
    apply_terminology_registry(seed, canon.get("terminology_registry"))
    apply_canon_profile(seed, canon.get("canon_profile"))
    apply_force_mechanics(seed, canon.get("force_mechanics"))

    # Character-forge.
    seed["ensemble_cast"] = list(characters.get("ensemble_cast") or [])
    apply_relationship_arcs(seed, characters.get("relationship_arcs"))
    apply_referenced_characters(seed, characters.get("referenced_characters"))

    # arc_phase_maps from outline-planner are applied AFTER ensemble_cast
    # is in place so the per-character lookup works. Re-apply now since the
    # earlier call ran before ensemble_cast was set.
    apply_arc_phase_maps(seed, outline.get("arc_phase_maps"))

    # Always run extended_metadata pass last to capture anything destined
    # there (workshop_origin etc. would arrive via importers in a future
    # workflow round; the field-mover handles the no-op case gracefully).
    move_to_extended_metadata(seed, [])

    # Universe-builder absorbs the project's foundational content (premise,
    # conflict, theme, arc-type) plus the Step-10 stress test scores and
    # any quality_overrides / extended_metadata. Copy verbatim — these
    # fields don't pass through transforms.
    for key in (
        "premise",
        "conflict",
        "theme",
        "protagonist_arc_type",
        "stress_test_scores",
    ):
        if key in universe:
            seed[key] = universe[key]
    if "quality_overrides" in universe:
        apply_quality_overrides(seed, universe["quality_overrides"])
    if "extended_metadata" in universe:
        # Merge into any extended_metadata that earlier transforms set.
        existing = seed.setdefault("extended_metadata", {})
        for k, v in universe["extended_metadata"].items():
            existing.setdefault(k, v)

    # Workshop-only convention: scene_cards lives at the seed only as an
    # empty marker post-extraction. The on-disk per-file tree at
    # data/franchises/<fr>/books/<bk>/scene_cards/ is canonical.
    seed["scene_cards"] = []

    return seed


def _write_scene_cards(
    cards: list[dict],
    *,
    output_dir: Path,
    structural_overrides: dict | None,
    schema: dict | None,
    report: CompileReport,
) -> int:
    """Translate, validate, and write each scene card to ``output_dir``.

    Wipes existing chapter_*_scene_*.json files first so removed cards
    don't linger from a previous compile.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("chapter_*_scene_*.json"):
        stale.unlink()

    written = 0
    for card in cards:
        try:
            translated = translate_scene_card(
                card, structural_overrides=structural_overrides
            )
        except KeyError as exc:
            report.scene_card_errors.append(
                f"card missing required field {exc.args[0]!r}: {card!r}"
            )
            continue
        ch = translated["chapter_number"]
        sn = translated["scene_number"]
        if schema is not None:
            try:
                jsonschema.validate(instance=translated, schema=schema)
            except jsonschema.ValidationError as err:
                report.scene_card_errors.append(
                    f"chapter_{ch:02d}_scene_{sn:02d}: {err.message}"
                )
        filename = f"chapter_{ch:02d}_scene_{sn:02d}.json"
        path = output_dir / filename
        path.write_text(
            json.dumps(translated, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written += 1
    return written


def compile_bundle(
    *,
    franchise_slug: str,
    book_slug: str,
    base_dir: str = ".",
    strict: bool = False,
    validate_scene_cards: bool = True,
) -> CompileReport:
    """Compile the bundle for one (franchise, book) pair.

    Returns a populated ``CompileReport``. Exit code is the caller's
    responsibility: ``0`` when ``not report.has_failures(strict)``.
    """
    paths = ProjectPaths(
        book_slug, base_dir=base_dir, franchise_slug=franchise_slug,
    )
    paths.ensure_dirs()

    workflows_dir = paths.workflows_dir
    report = CompileReport(
        franchise=franchise_slug,
        book=book_slug,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    # Load surfaces.
    surfaces: dict[str, dict | None] = {
        "universe": _load_surface(workflows_dir / "universe.json"),
        "canon": _load_surface(workflows_dir / "canon.json"),
        "voice": _load_surface(workflows_dir / "voice.json"),
        "characters": _load_surface(workflows_dir / "characters.json"),
        "outline": _load_surface(workflows_dir / "outline.json"),
    }
    report.surfaces_present = {name: art is not None for name, art in surfaces.items()}
    report.surfaces_missing = [
        name for name in _REQUIRED_SURFACES if surfaces.get(name) is None
    ]

    if report.surfaces_missing:
        report.warnings.append(
            f"required surfaces missing: {report.surfaces_missing}; "
            "cannot build seed"
        )
        # Persist the report and return — nothing else to do.
        _write_report(paths, report)
        return report

    seed = _build_seed(
        universe=surfaces["universe"] or {},
        canon=surfaces["canon"] or {},
        voice=surfaces["voice"] or {},
        characters=surfaces["characters"] or {},
        outline=surfaces["outline"] or {},
    )

    # Schema validation — collect all errors rather than raising on first.
    seed_schema = json.loads(CONCEPT_SEED_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft7Validator(seed_schema)
    for err in validator.iter_errors(seed):
        path = "/".join(str(p) for p in err.absolute_path) or "<root>"
        report.schema_errors.append(f"{path}: {err.message}")

    # Scene-card extraction: from workflows/scene_cards.json or per-card dir.
    raw_cards = _load_scene_cards(workflows_dir)
    scene_card_envelope = _load_surface(workflows_dir / "scene_cards.json") or {}
    structural_overrides = scene_card_envelope.get("structural_overrides")

    if not raw_cards:
        report.warnings.append(
            "no scene cards present in workflows/; pipeline will auto-generate "
            "via SceneCardGenerator at run time"
        )
    scene_card_schema = (
        json.loads(SCENE_CARD_SCHEMA_PATH.read_text(encoding="utf-8"))
        if validate_scene_cards
        else None
    )
    report.scene_card_count = _write_scene_cards(
        raw_cards,
        output_dir=paths.scene_cards_dir,
        structural_overrides=structural_overrides,
        schema=scene_card_schema,
        report=report,
    )

    # Persist seed.
    paths.concept_seed_path.write_text(
        json.dumps(seed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    paths.ensure_franchise_meta(seed)

    # Compliance validation.
    compliance = validate_concept_seed(
        seed, franchise_slug=franchise_slug, book_slug=book_slug, base_dir=base_dir,
    )
    report.compliance = {
        "passed": compliance.passed,
        "critical_failures": list(compliance.critical_failures),
        "warnings": list(compliance.warnings),
    }

    _write_report(paths, report)
    return report


def _write_report(paths: ProjectPaths, report: CompileReport) -> Path:
    """Write the compile_report.json next to the seed."""
    path = paths.book_dir / "compile_report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def report_has_failures(report: CompileReport, *, strict: bool) -> bool:
    """Return True when the compile should exit non-zero."""
    if report.surfaces_missing:
        return True
    if report.schema_errors:
        return True
    if report.scene_card_errors:
        return True
    if not report.compliance.get("passed", True):
        return True
    if strict and report.warnings:
        return True
    return False


def _format_summary(report: CompileReport) -> str:
    """Human-readable stdout summary mirroring ValidationReport.format()."""
    lines: list[str] = [
        f"Bundle compile: {report.franchise}/{report.book}",
        f"  surfaces present: "
        + ", ".join(name for name, present in report.surfaces_present.items() if present),
    ]
    if report.surfaces_missing:
        lines.append(f"  surfaces MISSING: {report.surfaces_missing}")
    lines.append(f"  scene cards written: {report.scene_card_count}")
    if report.schema_errors:
        lines.append(f"  SCHEMA ERRORS ({len(report.schema_errors)}):")
        for err in report.schema_errors[:5]:
            lines.append(f"    - {err}")
        if len(report.schema_errors) > 5:
            lines.append(f"    ... and {len(report.schema_errors) - 5} more")
    compliance = report.compliance
    if compliance:
        passed = compliance.get("passed")
        marker = "PASS" if passed else "FAIL"
        crit = compliance.get("critical_failures") or []
        warns = compliance.get("warnings") or []
        lines.append(
            f"  compliance: {marker} ({len(crit)} critical, {len(warns)} warnings)"
        )
        for failure in crit[:5]:
            lines.append(f"    - critical: {failure}")
        if len(crit) > 5:
            lines.append(f"    ... and {len(crit) - 5} more critical failures")
    if report.warnings:
        lines.append(f"  warnings ({len(report.warnings)}):")
        for w in report.warnings:
            lines.append(f"    - {w}")
    return "\n".join(lines)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile workflow surface artifacts into the canonical concept_seed bundle.",
    )
    parser.add_argument("--franchise", required=True, help="Franchise slug")
    parser.add_argument("--book", required=True, help="Book slug")
    parser.add_argument("--base-dir", default=".", help="Repository root")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings as failures (exit non-zero on any warning).",
    )
    parser.add_argument(
        "--no-validate-scene-cards",
        action="store_true",
        help="Skip per-card jsonschema.validate (matches install_seed --no-validate-scene-cards).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    report = compile_bundle(
        franchise_slug=args.franchise,
        book_slug=args.book,
        base_dir=args.base_dir,
        strict=args.strict,
        validate_scene_cards=not args.no_validate_scene_cards,
    )
    print(_format_summary(report))
    return 1 if report_has_failures(report, strict=args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
