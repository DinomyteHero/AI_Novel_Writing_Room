"""Prepaid run preflight for current canonical planning artifacts.

This validates the artifacts the drafter actually consumes: approved
``concept_seed.json``, extracted scene cards, chapter blueprints, static canon
guidance sidecars, and chapter-packet compilation. It does not rebuild from
workflow surfaces; use ``scripts/compile_bundle.py`` for that path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import jsonschema

from src.pipeline.canon_guidance import CanonGuidanceStore
from src.pipeline.chapter_packet import ChapterPacketCompiler
from src.project_paths import ProjectPaths


REPO_ROOT = Path(__file__).resolve().parents[2]
CONCEPT_SEED_SCHEMA_PATH = REPO_ROOT / "schemas" / "concept_seed.json"
SCENE_CARD_SCHEMA_PATH = REPO_ROOT / "schemas" / "scene_card.json"
PLANNING_ID_RE = re.compile(r"\b(?:R\d{2}[a-z]?|H\d{2}|PP\d{2}|SP-[A-Z]|SP\d+)\b")


@dataclass(frozen=True)
class PreflightIssue:
    severity: str
    category: str
    message: str
    path: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "path": self.path,
        }


@dataclass
class PreflightReport:
    franchise: str
    book: str
    scene_card_count: int = 0
    chapter_count: int = 0
    packet_count: int = 0
    canon_guidance: dict = field(default_factory=dict)
    errors: list[PreflightIssue] = field(default_factory=list)
    warnings: list[PreflightIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "franchise": self.franchise,
            "book": self.book,
            "passed": self.passed,
            "scene_card_count": self.scene_card_count,
            "chapter_count": self.chapter_count,
            "packet_count": self.packet_count,
            "canon_guidance": self.canon_guidance,
            "errors": [issue.to_dict() for issue in self.errors],
            "warnings": [issue.to_dict() for issue in self.warnings],
        }

    def add_error(self, category: str, message: str, path: Path | str = "") -> None:
        self.errors.append(
            PreflightIssue("error", category, message, str(path) if path else "")
        )

    def add_warning(self, category: str, message: str, path: Path | str = "") -> None:
        self.warnings.append(
            PreflightIssue("warning", category, message, str(path) if path else "")
        )


def validate_current_run(
    *,
    franchise_slug: str,
    book_slug: str,
    base_dir: str = ".",
    chapter: int | None = None,
    scene: int | None = None,
    require_plan_approval: bool = True,
    require_canon_guidance: bool | None = None,
) -> PreflightReport:
    """Validate current on-disk artifacts before spending drafting calls.

    ``require_canon_guidance=None`` means auto: require fresh sidecars when a
    canon contract exists, otherwise warn but do not fail.
    """
    paths = ProjectPaths(
        book_slug,
        base_dir=base_dir,
        franchise_slug=franchise_slug,
    )
    report = PreflightReport(franchise=franchise_slug, book=book_slug)

    concept_seed = _load_json(paths.concept_seed_path, report, "concept_seed")
    if not concept_seed:
        return report

    _validate_schema(
        payload=concept_seed,
        schema_path=CONCEPT_SEED_SCHEMA_PATH,
        report=report,
        category="concept_seed_schema",
        path=paths.concept_seed_path,
    )
    if require_plan_approval and not (
        (concept_seed.get("compile_metadata") or {}).get("plan_approved") is True
    ):
        report.add_error(
            "plan_approval",
            "concept_seed.compile_metadata.plan_approved is not true",
            paths.concept_seed_path,
        )

    scene_cards = _load_scene_cards(paths, report, chapter=chapter, scene=scene)
    report.scene_card_count = len(scene_cards)
    report.chapter_count = len({int(c.get("chapter_number") or 0) for c in scene_cards})
    if not scene_cards:
        report.add_error("scene_cards", "no scene cards selected", paths.scene_cards_dir)
        return report

    scene_schema = _load_json(SCENE_CARD_SCHEMA_PATH, report, "scene_card_schema")
    if scene_schema:
        for card in scene_cards:
            card_path = _scene_card_path(paths, card)
            _validate_schema(
                payload=card,
                schema_path=SCENE_CARD_SCHEMA_PATH,
                report=report,
                category="scene_card_schema",
                path=card_path,
                schema=scene_schema,
            )

    blueprints = _load_blueprints(paths, report)
    missing_blueprints = sorted(
        {
            int(card.get("chapter_number") or 0)
            for card in scene_cards
            if int(card.get("chapter_number") or 0) not in blueprints
        }
    )
    for chapter_number in missing_blueprints:
        report.add_error(
            "chapter_blueprints",
            f"missing chapter blueprint for chapter {chapter_number}",
            paths.chapter_blueprints_dir / f"chapter_{chapter_number:02d}.json",
        )

    _check_canon_guidance(
        paths=paths,
        concept_seed=concept_seed,
        blueprints=blueprints,
        scene_cards=scene_cards,
        report=report,
        require_canon_guidance=require_canon_guidance,
    )

    if not missing_blueprints:
        _check_packet_compilation(
            concept_seed=concept_seed,
            blueprints=blueprints,
            scene_cards=scene_cards,
            report=report,
        )

    return report


def _load_json(path: Path, report: PreflightReport, category: str) -> Any:
    if not path.exists():
        report.add_error(category, "required JSON file is missing", path)
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report.add_error(category, f"could not read JSON: {type(exc).__name__}: {exc}", path)
        return None


def _validate_schema(
    *,
    payload: Mapping[str, Any],
    schema_path: Path,
    report: PreflightReport,
    category: str,
    path: Path,
    schema: Mapping[str, Any] | None = None,
) -> None:
    schema_payload = schema or _load_json(schema_path, report, f"{category}_schema")
    if not schema_payload:
        return
    validator = jsonschema.Draft7Validator(schema_payload)
    for err in validator.iter_errors(payload):
        location = "/".join(str(part) for part in err.absolute_path) or "<root>"
        report.add_error(category, f"{location}: {err.message}", path)


def _load_scene_cards(
    paths: ProjectPaths,
    report: PreflightReport,
    *,
    chapter: int | None,
    scene: int | None,
) -> list[dict]:
    cards: list[dict] = []
    for path in sorted(paths.scene_cards_dir.glob("chapter_*_scene_*.json")):
        card = _load_json(path, report, "scene_card")
        if not isinstance(card, dict):
            continue
        if chapter is not None and int(card.get("chapter_number") or 0) != chapter:
            continue
        if scene is not None and int(card.get("scene_number") or 0) != scene:
            continue
        cards.append(card)
    return cards


def _load_blueprints(paths: ProjectPaths, report: PreflightReport) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for path in sorted(paths.chapter_blueprints_dir.glob("chapter_*.json")):
        try:
            chapter_number = int(path.stem.split("_")[1])
        except (IndexError, ValueError):
            report.add_warning("chapter_blueprints", "ignored nonstandard blueprint name", path)
            continue
        payload = _load_json(path, report, "chapter_blueprint")
        if isinstance(payload, dict):
            out[chapter_number] = payload
    return out


def _scene_card_path(paths: ProjectPaths, card: Mapping[str, Any]) -> Path:
    chapter_number = int(card.get("chapter_number") or 0)
    scene_number = int(card.get("scene_number") or 1)
    return paths.scene_cards_dir / f"chapter_{chapter_number:02d}_scene_{scene_number:02d}.json"


def _check_canon_guidance(
    *,
    paths: ProjectPaths,
    concept_seed: Mapping[str, Any],
    blueprints: Mapping[int, Mapping[str, Any]],
    scene_cards: list[Mapping[str, Any]],
    report: PreflightReport,
    require_canon_guidance: bool | None,
) -> None:
    store = CanonGuidanceStore(
        paths.canon_guidance_dir,
        canon_contract_path=paths.canon_contract_path,
    )
    coverage = store.coverage(
        concept_seed=concept_seed,
        blueprints=blueprints,
        scene_cards=scene_cards,
    )
    report.canon_guidance = coverage.to_dict()

    contract_exists = paths.canon_contract_path.exists()
    required = contract_exists if require_canon_guidance is None else require_canon_guidance
    if not contract_exists:
        report.add_warning(
            "canon_guidance",
            "canon_contract.md is missing; static canon guidance is not anchored",
            paths.canon_contract_path,
        )
    if not required:
        return
    for item in coverage.incomplete:
        report.add_error(
            "canon_guidance",
            f"{item.scene_id} canon guidance is {item.status}"
            + (f" ({item.reason})" if item.reason else ""),
            item.path,
        )


def _check_packet_compilation(
    *,
    concept_seed: Mapping[str, Any],
    blueprints: Mapping[int, Mapping[str, Any]],
    scene_cards: list[Mapping[str, Any]],
    report: PreflightReport,
) -> None:
    compiler = ChapterPacketCompiler(
        concept_seed=concept_seed,
        blueprints=blueprints,
    )
    bases: dict[int, Any] = {}
    for card in scene_cards:
        chapter_number = int(card.get("chapter_number") or 0)
        try:
            base = bases.get(chapter_number)
            if base is None:
                base = compiler.compile_base(chapter_number=chapter_number)
                bases[chapter_number] = base
            overlay = compiler.compile_overlay(base=base, scene_card=card)
            report.packet_count += 1
            ids = sorted(set(PLANNING_ID_RE.findall(overlay.rendered_markdown)))
            if ids:
                report.add_warning(
                    "packet_model_facing_ids",
                    f"packet still contains planning IDs: {', '.join(ids[:12])}",
                    _scene_label(card),
                )
        except Exception as exc:  # noqa: BLE001
            report.add_error(
                "chapter_packet",
                f"{_scene_label(card)} packet compile failed: {type(exc).__name__}: {exc}",
            )


def _scene_label(card: Mapping[str, Any]) -> str:
    return (
        f"ch{int(card.get('chapter_number') or 0):02d}_"
        f"sc{int(card.get('scene_number') or 0):02d}"
    )


def format_preflight_summary(report: PreflightReport) -> str:
    lines = [
        f"Run preflight: {report.franchise}/{report.book}",
        f"  passed: {report.passed}",
        f"  scene cards: {report.scene_card_count}",
        f"  chapters: {report.chapter_count}",
        f"  packets compiled: {report.packet_count}",
    ]
    if report.canon_guidance:
        cg = report.canon_guidance
        lines.append(
            "  canon guidance: "
            f"{cg.get('fresh', 0)}/{cg.get('total', 0)} fresh "
            f"(missing={cg.get('missing', 0)}, stale={cg.get('stale', 0)}, "
            f"invalid={cg.get('invalid', 0)})"
        )
    if report.errors:
        lines.append("  errors:")
        lines.extend(f"    - [{e.category}] {e.message}" for e in report.errors[:25])
        if len(report.errors) > 25:
            lines.append(f"    ... {len(report.errors) - 25} more")
    if report.warnings:
        lines.append("  warnings:")
        lines.extend(f"    - [{w.category}] {w.message}" for w in report.warnings[:25])
        if len(report.warnings) > 25:
            lines.append(f"    ... {len(report.warnings) - 25} more")
    return "\n".join(lines)


__all__ = [
    "PreflightIssue",
    "PreflightReport",
    "format_preflight_summary",
    "validate_current_run",
]
