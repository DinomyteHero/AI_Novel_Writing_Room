"""Migrate legacy character sheets and voice profiles into a Story Brief.

The legacy book-local artifacts were:

- ``character_sheets/*.json``
- ``voice_profiles.json``

Both are superseded by ``workflows/idea_session/story_brief.json`` plus the
reviewable Markdown sheets under ``workflows/idea_session/sheets/``. This
migration is additive: existing claims are preserved unless ``--force`` is
passed, and legacy files are only removed with ``--remove-legacy``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.planning import story_brief as sb  # noqa: E402

_LEGACY_CHARACTER_DIR = "character_sheets"
_LEGACY_VOICE_FILE = "voice_profiles.json"
_LEGACY_VOICE_DIR = "voice_profiles"


def _add(
    brief: dict[str, Any],
    *,
    entity_type: str,
    field: str,
    value: Any,
    entity_id: str,
    source: str,
    force: bool,
) -> bool:
    if value in (None, "", [], {}):
        return False
    if not force and sb.resolve_claim(brief, entity_type, entity_id, field):
        return False
    sb.add_claim(
        brief,
        entity_type=entity_type,
        entity_id=entity_id,
        field=field,
        value=value,
        origin="import",
        status="confirmed",
        confidence="explicit",
        source_quote=source,
    )
    return True


def _seed_claims(brief: dict[str, Any], seed: dict[str, Any], capture: dict[str, Any], *, force: bool) -> int:
    added = 0

    def add(entity_type: str, field: str, value: Any, entity_id: str, source: str) -> None:
        nonlocal added
        if _add(
            brief,
            entity_type=entity_type,
            field=field,
            value=value,
            entity_id=entity_id,
            source=source,
            force=force,
        ):
            added += 1

    north = (capture.get("north_star") or {}) if isinstance(capture, dict) else {}
    for field in ("one_sentence_pitch", "reader_promise", "emotional_core", "author_intent"):
        add("intent", field, north.get(field), "book", "imported from idea_session/capture.json")
    add("intent", "non_negotiables", north.get("non_negotiables"), "book", "imported from capture.json")
    add("intent", "avoid", north.get("avoid"), "book", "imported from capture.json")

    premise = seed.get("premise") or {}
    add("plot", "premise", premise.get("what_if"), "main", "imported from concept_seed.premise.what_if")
    add("plot", "logline", premise.get("logline"), "main", "imported from concept_seed.premise.logline")
    conflict = seed.get("conflict") or {}
    add(
        "plot",
        "central_conflict",
        conflict.get("central_conflict")
        or conflict.get("primary_antagonistic_force")
        or conflict.get("description"),
        "main",
        "imported from concept_seed.conflict",
    )
    structural = (seed.get("structural_notes") or {}).get("brooks_alignment") or {}
    for field in ("inciting_incident", "midpoint", "climax", "resolution"):
        add("plot", field, structural.get(field), "main", "imported from concept_seed.structural_notes")
    ledger = seed.get("promise_payoff_ledger") or []
    if ledger:
        add("plot", "promises", ledger, "main", "imported from concept_seed.promise_payoff_ledger")

    theme = seed.get("theme") or {}
    question = north.get("emotional_core")
    if isinstance(question, str) and question.strip().endswith("?"):
        add("theme", "question", question, "main", "imported from capture.json emotional_core")
    add("theme", "answers", theme.get("how_each_arc_tests_theme"), "main", "imported from concept_seed.theme")
    add("theme", "thematic_premise", theme.get("thematic_premise"), "main", "imported from concept_seed.theme")

    voice = seed.get("voice_definition") or {}
    add("voice", "pov", voice.get("pov_approach"), "book", "imported from concept_seed.voice_definition")
    add("voice", "register", voice.get("prose_register"), "book", "imported from concept_seed.voice_definition")
    add("voice", "comps", voice.get("reference_authors"), "book", "imported from concept_seed.voice_definition")
    add("voice", "anti_patterns", voice.get("anti_patterns"), "book", "imported from concept_seed.voice_definition")

    canon = seed.get("canon_constraints") or {}
    add("world", "history", canon.get("continuity"), "world", "imported from concept_seed.canon_constraints")
    add("world", "divergence", canon.get("divergence_point"), "world", "imported from concept_seed.canon_constraints")
    return added


def _character_claims(
    brief: dict[str, Any],
    seed: dict[str, Any],
    sheets: dict[str, dict[str, Any]],
    voices: dict[str, dict[str, Any]],
    *,
    force: bool,
) -> int:
    added = 0
    cast = {
        sb._slug(str(char.get("name") or "")): char
        for char in (seed.get("ensemble_cast") or [])
        if isinstance(char, dict) and char.get("name")
    }

    ids = sorted(set(sheets) | set(voices) | set(cast))
    for char_id in ids:
        sheet = sheets.get(char_id, {})
        voice = voices.get(char_id, {})
        cast_item = cast.get(char_id, {})
        fields = voice.get("fields") or {}
        three = sheet.get("three_dimensions") or {}
        name = sheet.get("name") or voice.get("name") or cast_item.get("name") or char_id.replace("_", " ").title()
        source = f"imported from legacy sheets for {name}"

        def add(field: str, value: Any) -> None:
            nonlocal added
            if _add(
                brief,
                entity_type="character",
                entity_id=char_id,
                field=field,
                value=value,
                source=source,
                force=force,
            ):
                added += 1

        add("name", name)
        add("tier", "principal" if cast_item or "protagonist" in str(sheet.get("role", "")).lower() else "supporting")
        add("role", sheet.get("role") or cast_item.get("role"))
        add("age", sheet.get("age") or cast_item.get("age"))
        add("force_status", sheet.get("force_status") or cast_item.get("force_status"))
        add("surface", three.get("surface") or cast_item.get("three_dimensions", {}).get("surface"))
        add("ghost", three.get("backstory_inner_demons") or fields.get("Private wound"))
        add("action_under_pressure", three.get("action_under_pressure"))
        add("arc_type", sheet.get("arc_type") or (cast_item.get("weiland_arc") or {}).get("arc_type"))
        add("thematic_role", sheet.get("thematic_role"))
        add("avoid_list", sheet.get("avoid_list"))
        add("voice", sheet.get("voice_notes") or fields.get("Voice"))
        add("want", fields.get("Surface want"))
        add("need", fields.get("Deeper want"))
        add("fear", fields.get("Fear"))
        add("private_wound", fields.get("Private wound"))
        add("humor", fields.get("Humor"))
        add("social_behavior", fields.get("Social behavior"))
        add("avoidance_habits", fields.get("Avoidance habits"))
        add("notices_first", fields.get("What he notices first") or fields.get("What she notices first"))
        add("anger", fields.get("What makes him angry") or fields.get("What makes her angry"))
        add("vulnerability", fields.get("What makes him vulnerable") or fields.get("What makes her vulnerable"))
        add("dialogue_examples", fields.get("Dialogue examples"))
        add("character_danger", fields.get("Character danger"))
        arc_phase_map = (cast_item.get("weiland_arc") or {}).get("arc_phase_map")
        if arc_phase_map:
            add("arc_phase_map", arc_phase_map)
    return added


def migrate(
    book_dir: str | Path,
    *,
    force: bool = False,
    dry_run: bool = False,
    remove_legacy: bool = False,
) -> dict[str, Any]:
    book = Path(book_dir)
    seed_path = book / "concept_seed.json"
    if not seed_path.exists():
        raise FileNotFoundError(f"concept_seed.json not found under {book}")
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    capture_path = book / "workflows" / "idea_session" / "capture.json"
    capture = (
        json.loads(capture_path.read_text(encoding="utf-8"))
        if capture_path.exists() else {}
    )
    sheet_dir = book / _LEGACY_CHARACTER_DIR
    sheets: dict[str, dict[str, Any]] = {}
    if sheet_dir.is_dir():
        for path in sorted(sheet_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                sheets[sb._slug(str(data.get("id") or path.stem))] = data

    voice_path = book / _LEGACY_VOICE_FILE
    voices: dict[str, dict[str, Any]] = {}
    if voice_path.exists():
        data = json.loads(voice_path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("id"):
                    voices[sb._slug(str(item["id"]))] = item

    brief_path = book / "workflows" / "idea_session" / "story_brief.json"
    brief = sb.load_brief(brief_path) if brief_path.exists() else sb.new_brief(
        str((seed.get("meta") or {}).get("project_title") or book.name),
        str((seed.get("meta") or {}).get("franchise") or book.parent.parent.name),
    )
    added = _seed_claims(brief, seed, capture, force=force)
    added += _character_claims(brief, seed, sheets, voices, force=force)
    report = {
        "book_dir": str(book),
        "brief_path": str(brief_path),
        "claims_added": added,
        "characters": len(set(sheets) | set(voices)),
        "dry_run": dry_run,
        "legacy_removed": [],
    }
    if dry_run:
        return report

    sb.save_brief(brief_path, brief)
    sheets_dir = brief_path.parent / "sheets"
    written = sb.write_sheets(brief, sheets_dir)
    report["sheets_written"] = [str(p) for p in written]

    if remove_legacy:
        for path in (sheet_dir, voice_path, book / _LEGACY_VOICE_DIR):
            if path.is_dir():
                shutil.rmtree(path)
                report["legacy_removed"].append(str(path))
            elif path.exists():
                path.unlink()
                report["legacy_removed"].append(str(path))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book-dir", required=True, help="Book directory containing concept_seed.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="Supersede existing claims")
    parser.add_argument(
        "--remove-legacy",
        action="store_true",
        help="Delete character_sheets/ and voice_profiles.json after writing the brief",
    )
    args = parser.parse_args(argv)
    report = migrate(
        args.book_dir,
        force=args.force,
        dry_run=args.dry_run,
        remove_legacy=args.remove_legacy,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
