#!/usr/bin/env python3
"""Repair placeholder / malformed fields in a book's scene cards.

Fills gaps WITHOUT clobbering authored content (every field is filled only when
it is blank or a placeholder):

- stakes.personal       <- POV character's Fear / Private wound from the voice
                           profile
- stakes.interpersonal  <- a relationship-dynamics prompt
- sensory_details       <- a sensory-focus prompt
- pov_arc_phase         <- "<Character>:<phase>" derived from the Weiland
                           arc_phase_map for the scene's chapter
- turning_point / closing_hook  <- strip trailing "# Act ..." planning leakage
                           (always applied; only acts when the marker is present)

Multi-POV cards ("Ben / Talon", "Aevyn or Ben") resolve to the primary
(first-named) POV. A card that can't be resolved or is missing fields is
skipped with a note, never crashed on. Use --dry-run to preview.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_PLACEHOLDER_RE = re.compile(r"EDIT_ME|TODO|per concept_seed|placeholder", re.IGNORECASE)

_INTERPERSONAL_DEFAULT = (
    "Maintain the relationship dynamics, power imbalances, and interaction "
    "rules defined in the character profiles."
)
_SENSORY_DEFAULT = (
    "Focus on immediate environmental pressures, spatial constraints, exits, "
    "and the POV character's specific sensory focus (what they notice first)."
)


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")


def _primary_pov(pov: str) -> str:
    """Reduce a multi-POV label to its primary (first-named) character."""
    parts = re.split(r"\s*(?:/|&|,|\bor\b|\band\b)\s*", (pov or "").strip(), flags=re.IGNORECASE)
    return next((p.strip() for p in parts if p.strip()), (pov or "").strip())


def _resolve(pov_token: str, candidates: list[str]) -> str | None:
    """Match a POV token to a cast name / voice-profile id by normalized form
    or first-name prefix ("Ben" -> "Ben Skywalker")."""
    nt = _norm(pov_token)
    if not nt:
        return None
    for cand in candidates:
        nc = _norm(cand)
        if nc == nt or nc.startswith(nt + "_") or nc.split("_")[0] == nt:
            return cand
    return None


def _is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or bool(_PLACEHOLDER_RE.search(value))
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def parse_arc_phases(arc_phase_map: dict) -> dict[int, str]:
    """Parse a Weiland arc phase map (phase -> 'Ch X (Name)...') into
    {chapter_number: phase}."""
    chapter_to_phase: dict[int, str] = {}
    for phase, description in (arc_phase_map or {}).items():
        m = re.search(r"Ch\s*(\d+)", str(description))
        if m:
            chapter_to_phase[int(m.group(1))] = phase
    return chapter_to_phase


def get_active_phase(chapter, chapter_to_phase: dict[int, str]) -> str | None:
    """Active phase for a chapter: the latest defined phase at or before it."""
    if not chapter_to_phase or chapter is None:
        return None
    past = [ch for ch in chapter_to_phase if ch <= chapter]
    return chapter_to_phase[max(past)] if past else chapter_to_phase[min(chapter_to_phase)]


def repair_cards(book_dir: Path, *, dry_run: bool = False) -> int:
    scene_cards_dir = book_dir / "scene_cards"
    voice_dir = book_dir / "voice_profiles"
    concept_seed_path = book_dir / "concept_seed.json"

    if not concept_seed_path.exists():
        print(f"Error: {concept_seed_path} not found.")
        return 0
    if not scene_cards_dir.is_dir():
        print(f"Error: {scene_cards_dir} not found.")
        return 0

    seed = json.loads(concept_seed_path.read_text(encoding="utf-8"))
    ensemble_cast = seed.get("ensemble_cast", []) or []

    voice_profiles: dict[str, dict] = {}
    if voice_dir.is_dir():
        for vp_path in voice_dir.glob("*.json"):
            try:
                vp = json.loads(vp_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(vp, dict) and vp.get("id"):
                voice_profiles[vp["id"]] = vp

    arc_maps: dict[str, dict[int, str]] = {}
    for char in ensemble_cast:
        if not isinstance(char, dict) or not char.get("name"):
            continue
        arc_maps[char["name"]] = parse_arc_phases(
            (char.get("weiland_arc") or {}).get("arc_phase_map", {})
        )

    cast_names = list(arc_maps.keys())
    vp_ids = list(voice_profiles.keys())

    changed = 0
    skipped = 0
    for card_path in sorted(scene_cards_dir.glob("chapter_*_scene_*.json")):
        try:
            card = json.loads(card_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  skip {card_path.name}: unreadable ({exc})")
            skipped += 1
            continue

        before = json.dumps(card, sort_keys=True, ensure_ascii=False)
        pov_token = _primary_pov(card.get("pov_character", ""))
        ch_num = card.get("chapter_number")

        if pov_token:
            vp_id = _resolve(pov_token, vp_ids)
            vp = voice_profiles.get(vp_id) if vp_id else None

            stakes = card.get("stakes")
            if not isinstance(stakes, dict):
                stakes = {}
            if vp and _is_blank(stakes.get("personal")):
                fields = vp.get("fields", {}) or {}
                bits = []
                if fields.get("Fear"):
                    bits.append(f"Fear: {fields['Fear']}")
                if fields.get("Private wound"):
                    bits.append(f"Wound: {fields['Private wound']}")
                if bits:
                    stakes["personal"] = " ".join(bits)
            if _is_blank(stakes.get("interpersonal")):
                stakes["interpersonal"] = _INTERPERSONAL_DEFAULT
            if stakes:
                card["stakes"] = stakes

            if _is_blank(card.get("sensory_details")):
                card["sensory_details"] = _SENSORY_DEFAULT

            cast_name = _resolve(pov_token, cast_names)
            phase_map = arc_maps.get(cast_name) if cast_name else None
            if phase_map and _is_blank(card.get("pov_arc_phase")):
                active = get_active_phase(ch_num, phase_map)
                if active:
                    phase_str = f"{cast_name}:{active}"
                    card["pov_arc_phase"] = phase_str
                    svp = card.get("scene_voice_permissions")
                    if isinstance(svp, dict):
                        svp["pov_arc_phase"] = phase_str

        for field in ("turning_point", "closing_hook"):
            val = card.get(field)
            if isinstance(val, str) and "# Act" in val:
                card[field] = val.split("# Act")[0].strip()

        if json.dumps(card, sort_keys=True, ensure_ascii=False) == before:
            continue
        changed += 1
        if dry_run:
            print(f"  would repair {card_path.name}")
        else:
            card_path.write_text(
                json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )

    verb = "Would repair" if dry_run else "Repaired"
    print(f"{verb} {changed} scene card(s) in {book_dir.name} ({skipped} skipped).")
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Repair placeholder/malformed scene-card fields (non-destructive)."
    )
    parser.add_argument("--book-dir", required=True, help="Path to the book directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()
    repair_cards(Path(args.book_dir), dry_run=args.dry_run)
