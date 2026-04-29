#!/usr/bin/env python3
"""One-shot scene-card migration to the generic scene_voice_permissions block.

This script mirrors legacy scene-level voice metadata
(``notes``, ``anti_patterns``, ``pov_arc_phase``, ``primary_anchor``,
``supporting_anchor``, ``stover_permitted``) into the additive
``scene_voice_permissions`` object while leaving the legacy fields in place.

The migration is intentionally conservative:
- idempotent
- book-by-book friendly
- dry-run capable
- legacy aliases are preserved so runtime behavior stays unchanged

Usage:
    python scripts/migrations/migrate_scene_voice_permissions.py [--dry-run] [--root <path>]
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


DEFAULT_SEARCH_ROOTS = (
    Path("data/franchises"),
    Path("data/projects"),
)

_HEIGHTENED_INTERIORITY = "heightened_interiority"


def find_scene_cards(roots: list[Path]) -> list[Path]:
    """Return canonical scene-card paths under the supplied roots."""
    hits: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        hits.extend(sorted(root.rglob("chapter_*_scene_*.json")))
    return hits


def _normalize_string_values(raw: object) -> list[str]:
    if raw in (None, ""):
        return []
    if isinstance(raw, str):
        candidates = raw.split(",")
    elif isinstance(raw, (list, tuple)):
        candidates = raw
    else:
        candidates = [raw]

    values: list[str] = []
    for candidate in candidates:
        text = str(candidate).strip()
        if text and text not in values:
            values.append(text)
    return values


def build_scene_voice_permissions(card: dict) -> dict:
    """Return the migrated scene_voice_permissions block for one scene card.

    Existing generic fields are preserved. Legacy fields only fill gaps.
    Returns an empty dict when the card has no scene-level voice metadata to
    migrate.
    """
    existing = card.get("scene_voice_permissions")
    block = copy.deepcopy(existing) if isinstance(existing, dict) else {}

    if "notes" not in block and card.get("notes") not in (None, ""):
        block["notes"] = card["notes"]

    if "anti_patterns" not in block:
        anti_patterns = _normalize_string_values(card.get("anti_patterns"))
        if anti_patterns:
            block["anti_patterns"] = anti_patterns

    if "pov_arc_phase" not in block and card.get("pov_arc_phase") not in (None, ""):
        block["pov_arc_phase"] = card["pov_arc_phase"]

    anchor_profile = copy.deepcopy(block.get("anchor_profile", {}))
    if not isinstance(anchor_profile, dict):
        anchor_profile = {}

    if "primary" not in anchor_profile and card.get("primary_anchor") not in (None, ""):
        anchor_profile["primary"] = card["primary_anchor"]

    if "supporting" not in anchor_profile:
        supporting = _normalize_string_values(card.get("supporting_anchor"))
        if supporting:
            anchor_profile["supporting"] = supporting

    if anchor_profile:
        block["anchor_profile"] = anchor_profile

    has_generic_modes = (
        "authorized_modes" in block or "prohibited_modes" in block
    )
    if not has_generic_modes and isinstance(card.get("stover_permitted"), bool):
        if card["stover_permitted"]:
            block["authorized_modes"] = [_HEIGHTENED_INTERIORITY]
        else:
            block["prohibited_modes"] = [_HEIGHTENED_INTERIORITY]

    return block


def migrate_scene_card(card: dict) -> tuple[dict, bool]:
    """Return ``(migrated_card, changed)`` for a single scene card dict."""
    migrated = copy.deepcopy(card)
    block = build_scene_voice_permissions(card)
    if not block:
        return migrated, False

    if migrated.get("scene_voice_permissions") == block:
        return migrated, False

    migrated["scene_voice_permissions"] = block
    return migrated, True


def migrate_file(path: Path, dry_run: bool) -> dict:
    """Migrate one scene-card file on disk."""
    card = json.loads(path.read_text(encoding="utf-8"))
    migrated, changed = migrate_scene_card(card)
    if changed and not dry_run:
        path.write_text(
            json.dumps(migrated, indent=2) + "\n",
            encoding="utf-8",
        )
    return {"path": str(path), "changed": changed}


def run(roots: list[Path], dry_run: bool) -> int:
    cards = find_scene_cards(roots)
    if not cards:
        print(f"No scene cards found under: {[str(root) for root in roots]}")
        return 0

    changed = 0
    for path in cards:
        report = migrate_file(path, dry_run=dry_run)
        if report["changed"]:
            changed += 1
            print(f"{'[dry-run] ' if dry_run else ''}migrate: {path}")

    print(
        f"\nProcessed {len(cards)} scene card(s); "
        f"{changed} {'would be updated' if dry_run else 'updated'}."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report scene cards that would be updated without writing files.",
    )
    parser.add_argument(
        "--root",
        action="append",
        default=None,
        help=(
            "Search root for canonical scene cards. Repeat for multiple roots. "
            f"Defaults: {', '.join(str(root) for root in DEFAULT_SEARCH_ROOTS)}"
        ),
    )
    args = parser.parse_args()

    roots = [Path(root) for root in (args.root or DEFAULT_SEARCH_ROOTS)]
    return run(roots=roots, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
