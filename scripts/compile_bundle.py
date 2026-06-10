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
                                     [--force-overwrite-newer]

``--strict`` makes warnings fail-exit; default is report-only on the
scene_cards-empty case (pipeline auto-generates downstream).

A hand-edit drift guard refuses to overwrite ``concept_seed.json`` /
``scene_cards/`` that were never produced by this compiler (no
``compile_report.json``) or were modified after the last compile while
the workflow surfaces went stale; ``--force-overwrite-newer`` overrides.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import jsonschema

if TYPE_CHECKING:
    from src.model_router import ModelRouter

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.concept_workshop.compliance_validator import validate_concept_seed  # noqa: E402
from src.planning.physics_enforcer import PhysicsEnforcer  # noqa: E402
from src.project_paths import ProjectPaths, _slugify_franchise  # noqa: E402
from src.quality.cross_chapter_validator import (  # noqa: E402
    validate_cross_chapter_continuity,
)
from src.runtime_flags import resolve_flag  # noqa: E402
from src.prompting.scene_voice_permissions import detect_legacy_voice_fields  # noqa: E402
from workflows._shared.scene_card_references import (  # noqa: E402
    validate_all_scene_card_references,
)
from workflows._shared.scene_card_translator import translate_scene_card  # noqa: E402
from workflows._shared.seed_transforms import (  # noqa: E402
    apply_arc_phase_maps,
    apply_branch_point,
    apply_canon_profile,
    apply_force_mechanics,
    apply_hooks,
    apply_promise_payoff_ledger,
    apply_quality_overrides,
    apply_referenced_characters,
    apply_relationship_arcs,
    apply_revelation_schedule,
    apply_subplots,
    apply_terminology_registry,
    apply_voice_definition,
    move_to_extended_metadata,
    normalize_enums,
)

CONCEPT_SEED_SCHEMA_PATH = REPO_ROOT / "schemas" / "concept_seed.json"
SCENE_CARD_SCHEMA_PATH = REPO_ROOT / "schemas" / "scene_card.json"

# Required surfaces. Missing any of these always fails (exit 1).
_REQUIRED_SURFACES = ("universe", "canon", "voice", "characters", "outline")

# Mtime slack for the hand-edit drift guard, covering coarse filesystem
# timestamp granularity and the seed/cards/report writes of a single
# compile landing a moment apart.
_DRIFT_MTIME_TOLERANCE_SECONDS = 2.0


@dataclass
class CompileReport:
    franchise: str
    book: str
    surfaces_present: dict = field(default_factory=dict)
    surfaces_missing: list[str] = field(default_factory=list)
    preflight_errors: list[str] = field(default_factory=list)
    compliance: dict = field(default_factory=dict)
    schema_errors: list[str] = field(default_factory=list)
    scene_card_count: int = 0
    scene_card_errors: list[str] = field(default_factory=list)
    physics: dict = field(default_factory=dict)
    editorial: dict = field(default_factory=dict)
    continuity: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "franchise": self.franchise,
            "book": self.book,
            "surfaces_present": self.surfaces_present,
            "surfaces_missing": self.surfaces_missing,
            "preflight_errors": self.preflight_errors,
            "compliance": self.compliance,
            "schema_errors": self.schema_errors,
            "scene_card_count": self.scene_card_count,
            "scene_card_errors": self.scene_card_errors,
            "physics": self.physics,
            "editorial": self.editorial,
            "continuity": self.continuity,
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
    # Translate + validate into memory FIRST; only mutate the on-disk tree once
    # we know we have cards to write. A translation failure on every card would
    # otherwise wipe a previously-compiled scene_cards/ tree (the live pipeline
    # input) and write nothing back.
    rendered: list[tuple[str, str]] = []
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

        legacy_voice = detect_legacy_voice_fields(translated)
        if legacy_voice:
            report.warnings.append(
                f"chapter_{ch:02d}_scene_{sn:02d}: legacy voice fields "
                f"{legacy_voice} \u2014 migrate into scene_voice_permissions "
                f"(see D1 in docs; readers still honor the legacy shape)"
            )
        filename = f"chapter_{ch:02d}_scene_{sn:02d}.json"
        rendered.append((
            filename,
            json.dumps(translated, indent=2, ensure_ascii=False) + "\n",
        ))

    if not rendered:
        report.warnings.append(
            "no scene cards translated successfully; leaving the existing "
            "scene_cards/ tree untouched"
        )
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    for stale in output_dir.glob("chapter_*_scene_*.json"):
        stale.unlink()
    for filename, content in rendered:
        (output_dir / filename).write_text(content, encoding="utf-8")
    return len(rendered)


def _check_hand_edit_drift(paths: ProjectPaths) -> str | None:
    """Return a refusal message when compiling would clobber hand edits.

    Pure mtime + existence checks. Two shapes block:

    - compiled artifacts exist but ``compile_report.json`` does not — the
      seed / cards were installed, ingested, or hand-authored, never
      produced by this compiler, so the workflow surfaces cannot be
      trusted to regenerate them;
    - the newest compiled artifact was modified after the last compile
      (newer than ``compile_report.json``) and is newer than every
      workflow surface — the live artifacts drifted while the surfaces
      went stale.

    Artifacts no newer than the last compile report are machine-written
    and never block, so recompiles stay idempotent. Workflow surfaces
    newer than the hand edits also pass: editing the surfaces signals
    intent to recompile.
    """
    # Declared provenance beats mtime forensics: a seed stamped
    # compile_metadata.managed_by='direct' is hand-maintained by design and
    # never recompiled without the explicit override.
    if paths.concept_seed_path.exists():
        try:
            seed = json.loads(paths.concept_seed_path.read_text(encoding="utf-8"))
            managed_by = (seed.get("compile_metadata") or {}).get("managed_by")
        except (OSError, json.JSONDecodeError):
            managed_by = None
        if managed_by == "direct":
            return (
                "hand-edit drift guard: concept_seed.json declares "
                "compile_metadata.managed_by='direct' — this book is "
                "maintained by editing the compiled artifacts directly, and "
                "recompiling from workflows/ would overwrite them. Remove the "
                "marker after reconciling workflows/*.json, or re-run with "
                "--force-overwrite-newer to overwrite."
            )

    artifacts: list[Path] = []
    if paths.concept_seed_path.exists():
        artifacts.append(paths.concept_seed_path)
    if paths.scene_cards_dir.exists():
        artifacts.extend(paths.scene_cards_dir.glob("chapter_*_scene_*.json"))
    if not artifacts:
        return None

    newest_artifact = max(artifacts, key=lambda p: p.stat().st_mtime)
    artifact_mtime = newest_artifact.stat().st_mtime

    sources: list[Path] = []
    if paths.workflows_dir.exists():
        sources.extend(paths.workflows_dir.glob("*.json"))
        per_card_dir = paths.workflows_dir / "scene_cards"
        if per_card_dir.exists():
            sources.extend(per_card_dir.glob("chapter_*_scene_*.json"))
    newest_source = (
        max(sources, key=lambda p: p.stat().st_mtime) if sources else None
    )

    def _stamp(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    comparison = (
        f"newest compiled artifact: {newest_artifact.name} "
        f"({_stamp(artifact_mtime)}); "
        + (
            f"newest workflow surface: {newest_source.name} "
            f"({_stamp(newest_source.stat().st_mtime)})"
            if newest_source is not None
            else "no workflow surface artifacts found"
        )
    )

    report_path = paths.book_dir / "compile_report.json"
    if not report_path.exists():
        return (
            "hand-edit drift guard: concept_seed.json / scene_cards/ already "
            f"exist under {paths.book_dir} but compile_bundle has never run "
            "here (no compile_report.json) — they were installed or "
            "hand-authored, and recompiling from workflows/ would overwrite "
            f"them. {comparison}. Reconcile workflows/*.json with the live "
            "artifacts first, or re-run with --force-overwrite-newer to "
            "overwrite."
        )

    if (
        artifact_mtime
        <= report_path.stat().st_mtime + _DRIFT_MTIME_TOLERANCE_SECONDS
    ):
        return None

    if (
        newest_source is None
        or artifact_mtime
        > newest_source.stat().st_mtime + _DRIFT_MTIME_TOLERANCE_SECONDS
    ):
        return (
            "hand-edit drift guard: compiled artifacts under "
            f"{paths.book_dir} were modified after the last compile and are "
            "newer than every workflow surface — recompiling would regress "
            f"those hand edits. {comparison}. Reconcile workflows/*.json "
            "with the live artifacts first, or re-run with "
            "--force-overwrite-newer to overwrite."
        )
    return None


def compile_bundle(
    *,
    franchise_slug: str,
    book_slug: str,
    base_dir: str = ".",
    strict: bool = False,
    validate_scene_cards: bool = True,
    editorial_router: "ModelRouter | None" = None,
    force_overwrite_newer: bool = False,
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

    if not force_overwrite_newer:
        drift = _check_hand_edit_drift(paths)
        if drift:
            report.preflight_errors.append(drift)
            # Deliberately no _write_report here: a report stamped by a
            # blocked run would satisfy the no-prior-compile check and let
            # the next invocation sail past the guard.
            return report

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

    # Preflight: the universe surface's declared franchise must slugify back
    # to the franchise_slug the caller passed (which is the input path). A
    # drift here routes outputs and scaffolds to a ghost directory, because
    # ProjectPaths.from_concept_seed(seed) slugifies meta.franchise at pipeline
    # run time (see Betrayal quirk: meta said "Star Wars" → slug "star-wars"
    # while inputs lived under "star-wars-legends-eu").
    declared_franchise = (
        (surfaces["universe"] or {}).get("meta", {}).get("franchise", "")
    )
    if declared_franchise:
        declared_slug = _slugify_franchise(declared_franchise)
        if declared_slug and declared_slug != franchise_slug:
            report.preflight_errors.append(
                f"franchise slug mismatch: input path uses "
                f"'{franchise_slug}' but workflows/universe.json declares "
                f"meta.franchise={declared_franchise!r} (slugifies to "
                f"'{declared_slug}'). Fix universe.json so the slug matches "
                f"the input path, or move the book to the correct franchise."
            )
            _write_report(paths, report)
            return report

    seed = _build_seed(
        universe=surfaces["universe"] or {},
        canon=surfaces["canon"] or {},
        voice=surfaces["voice"] or {},
        characters=surfaces["characters"] or {},
        outline=surfaces["outline"] or {},
    )

    # Phase 6.3b: copy branch_point from the on-disk universe_meta into the
    # seed's meta so it is readable at runtime from context alone. No-op when
    # the universe_meta file doesn't exist yet (fresh project) or has no
    # populated branch_point block (non-AU franchises).
    universe_meta_path = paths.universe_meta_path
    if universe_meta_path and universe_meta_path.exists():
        try:
            universe_meta = json.loads(
                universe_meta_path.read_text(encoding="utf-8")
            )
            apply_branch_point(seed, universe_meta)
        except (OSError, json.JSONDecodeError) as exc:
            report.warnings.append(
                f"branch_point copy from {universe_meta_path.name} skipped: {exc}"
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

    # Plan-time physics validation. Runs on the translated cards that were
    # just written to disk so the check reflects the exact artifacts the
    # pipeline will consume. Criticals always block exit; warnings only
    # block under --strict (mirrors compliance semantics).
    translated_cards: list[dict] = []
    for path in sorted(paths.scene_cards_dir.glob("chapter_*_scene_*.json")):
        try:
            translated_cards.append(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError) as exc:
            report.warnings.append(
                f"physics: could not read {path.name} for validation: {exc}"
            )

    # Tier 1 #4 \u2014 cross-surface reference validation.
    # Verify every character/promise/hook/subplot/revelation reference on
    # each scene card resolves in the compiled seed. Warnings land in
    # report.warnings (not scene_card_errors) so only --strict promotes
    # them to failure; legacy books with drift warnings can still compile.
    if translated_cards:
        reference_warnings = validate_all_scene_card_references(
            translated_cards, seed,
        )
        report.warnings.extend(reference_warnings)

    if translated_cards:
        enforcer = PhysicsEnforcer(seed, translated_cards)
        physics_result = enforcer.validate_plan(translated_cards)
        report.physics = {
            "passed": physics_result["passed"],
            "critical_count": physics_result["critical_count"],
            "warn_count": physics_result["warn_count"],
            "issues": physics_result["issues"],
            "by_category": physics_result["by_category"],
        }
        # Stamp the plan-validated marker so the pipeline can trust the
        # upstream check and skip its own pre-chapter physics pass.
        if physics_result["passed"]:
            seed.setdefault("compile_metadata", {})["physics_validated"] = True
        else:
            seed.setdefault("compile_metadata", {})["physics_validated"] = False
    else:
        report.physics = {
            "passed": True,
            "critical_count": 0,
            "warn_count": 0,
            "issues": [],
            "by_category": {},
            "skipped": "no scene cards on disk",
        }

    # Cross-chapter continuity (flag-gated: runtime.continuity_validator.enabled,
    # default off). Pure analysis over the ordered cards; declared
    # discontinuities surface in the report for the operator.
    if translated_cards and resolve_flag(
        "runtime.continuity_validator.enabled",
        concept_seed=seed, base_dir=base_dir, default=False,
    ):
        continuity_report = validate_cross_chapter_continuity(translated_cards)
        report.continuity = continuity_report.to_dict()
        high_breaks = [b for b in continuity_report.breaks if b.severity == "high"]
        if high_breaks:
            report.warnings.append(
                f"continuity: {len(high_breaks)} high-severity break(s) — "
                "see compile_report.continuity"
            )

    # Provenance: every compiler-written seed is workflow-kit-managed. Books
    # maintained by direct edits flip this to 'direct' by hand, which the
    # drift guard honors on later compiles.
    seed.setdefault("compile_metadata", {})["managed_by"] = "workflow_kit"

    # Persist seed (after physics stamping so the flag lands in the written file).
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

    # Editorial consultant — advisory qualitative review. Runs only when a
    # router is supplied (CLI: --editorial-review) and there are scene cards
    # to review. Writes the markdown report to the book tree; approval is a
    # separate explicit step via scripts/approve_plan.py.
    if editorial_router is not None and translated_cards:
        try:
            review = _run_editorial_review(
                router=editorial_router,
                paths=paths,
                seed=seed,
                translated_cards=translated_cards,
                physics_report=report.physics,
            )
            report.editorial = review
        except Exception as exc:  # noqa: BLE001 — surface, don't block
            report.editorial = {
                "skipped": f"editorial_review_failed: {type(exc).__name__}: {exc}",
            }

    _write_report(paths, report)
    return report


def _run_editorial_review(
    *,
    router: "ModelRouter",
    paths: ProjectPaths,
    seed: dict,
    translated_cards: list[dict],
    physics_report: dict,
) -> dict:
    """Invoke EditorialConsultant and persist the markdown report.

    Returns a summary dict suitable for ``report.editorial``.
    """
    from src.agents.editorial_consultant import EditorialConsultant

    # Load chapter blueprints if present in the book tree.
    blueprints: list[dict] = []
    blueprints_dir = paths.book_dir / "chapter_blueprints"
    if blueprints_dir.exists():
        for path in sorted(blueprints_dir.glob("chapter_*.json")):
            try:
                blueprints.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue

    agent = EditorialConsultant(router)
    context = {
        "concept_seed": seed,
        "chapter_blueprints": blueprints,
        "scene_cards": translated_cards,
        "physics_report": physics_report,
    }

    result = asyncio.run(agent.run(context))
    report_md: str = result.get("report_markdown", "")
    verdict: str = result.get("verdict", "unknown")

    # Persist review to the book tree.
    reviews_dir = paths.book_dir / "editorial_reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    review_path = reviews_dir / f"review_{ts}.md"
    review_path.write_text(report_md, encoding="utf-8")

    return {
        "verdict": verdict,
        "review_path": str(review_path.relative_to(paths.book_dir.parent.parent.parent)) if review_path.is_absolute() else str(review_path),
        "sections_found": sorted((result.get("sections") or {}).keys()),
        "blueprint_count": len(blueprints),
        "scene_card_count": len(translated_cards),
    }


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
    if report.preflight_errors:
        return True
    if report.schema_errors:
        return True
    if report.scene_card_errors:
        return True
    if not report.compliance.get("passed", True):
        return True
    if report.physics.get("critical_count", 0) > 0:
        return True
    if strict and report.physics.get("warn_count", 0) > 0:
        return True
    if strict and report.warnings:
        return True
    return False


def _format_summary(report: CompileReport) -> str:
    """Human-readable stdout summary mirroring ValidationReport.format()."""
    lines: list[str] = [
        f"Bundle compile: {report.franchise}/{report.book}",
        "  surfaces present: "
        + ", ".join(name for name, present in report.surfaces_present.items() if present),
    ]
    if report.surfaces_missing:
        lines.append(f"  surfaces MISSING: {report.surfaces_missing}")
    if report.preflight_errors:
        lines.append(f"  PREFLIGHT ERRORS ({len(report.preflight_errors)}):")
        for err in report.preflight_errors:
            lines.append(f"    - {err}")
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
    physics = report.physics
    if physics:
        crit = physics.get("critical_count", 0)
        warn = physics.get("warn_count", 0)
        passed = physics.get("passed", True)
        marker = "PASS" if passed else "FAIL"
        lines.append(
            f"  physics: {marker} ({crit} critical, {warn} warnings)"
        )
        for issue in (physics.get("issues") or [])[:5]:
            it = issue.get("issue_type", "?")
            desc = issue.get("description", "")
            lines.append(f"    - {it}: {desc}")
        total = len(physics.get("issues") or [])
        if total > 5:
            lines.append(f"    ... and {total - 5} more issues")
    editorial = report.editorial
    if editorial:
        if "skipped" in editorial:
            lines.append(f"  editorial: skipped ({editorial['skipped']})")
        else:
            verdict = editorial.get("verdict", "unknown")
            review_path = editorial.get("review_path", "?")
            lines.append(
                f"  editorial: verdict={verdict} (review: {review_path})"
            )
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
    parser.add_argument(
        "--editorial-review",
        action="store_true",
        help=(
            "Run the EditorialConsultant agent after physics validation. "
            "Writes an advisory markdown report to editorial_reviews/ in "
            "the book tree. Costs one LLM call per compile."
        ),
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="ModelRouter config path (only used with --editorial-review).",
    )
    parser.add_argument(
        "--force-overwrite-newer",
        action="store_true",
        help=(
            "Override the hand-edit drift guard: overwrite concept_seed.json "
            "and scene_cards/ even when they are newer than the workflow "
            "surfaces or were never produced by compile_bundle."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    editorial_router = None
    if args.editorial_review:
        from src.model_router import ModelRouter
        editorial_router = ModelRouter(args.config)
    report = compile_bundle(
        franchise_slug=args.franchise,
        book_slug=args.book,
        base_dir=args.base_dir,
        strict=args.strict,
        validate_scene_cards=not args.no_validate_scene_cards,
        editorial_router=editorial_router,
        force_overwrite_newer=args.force_overwrite_newer,
    )
    print(_format_summary(report))
    return 1 if report_has_failures(report, strict=args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
