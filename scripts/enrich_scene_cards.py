"""One-shot scene-card enrichment migration.

Runs PlotArchitect against each scene card in a (franchise, book) pair and
writes the generated brief's structured fields back onto the scene card so
the card itself carries the planning data the drafter needs. After this
runs, the deterministic brief assembler (src/pipeline/brief_assembler.py)
can consume the card directly without re-invoking PlotArchitect at runtime.

Fields promoted from the brief onto the scene card:
- ``turning_point`` (object) \u2192 scene_card.turning_point_detail
- ``emotional_arc`` (object) \u2192 scene_card.emotional_arc
- ``key_beats`` (array)      \u2192 scene_card.key_beats
- ``opening_mode`` (enum)    \u2192 scene_card.opening_mode
- ``anti_patterns`` (array)  \u2192 scene_card.anti_patterns

Legacy string fields (``turning_point: str``, ``emotional_trajectory: str``)
are left in place \u2014 the dual-phase D2(c) migration keeps them valid until
a later cut. The brief assembler will prefer the enriched fields when
present and fall back to the legacy strings when absent.

Usage:
    python scripts/enrich_scene_cards.py \\
        --franchise star-wars-legends-eu \\
        --book legacy-of-the-force-betrayal \\
        [--base-dir .] \\
        [--config config/settings.yaml] \\
        [--card chapter_01_scene_01.json] \\
        [--force] [--dry-run]

By default, skips any card that already has ``key_beats`` AND
``turning_point_detail`` AND ``emotional_arc`` populated. ``--force``
re-runs PlotArchitect on all cards. ``--dry-run`` prints the diff but does
not write.

Expected cost: one PlotArchitect call per card, roughly equivalent to one
scene's planning overhead in a normal pipeline run. Check the configured
model for plot_architect in ``config/settings.yaml`` before running a
large migration.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from src.agents.plot_architect import PlotArchitect  # noqa: E402
from src.memory.context_assembler import ContextAssembler  # noqa: E402
from src.model_router import ModelRouter  # noqa: E402
from src.pipeline.brief_assembler import BriefAssembler  # noqa: E402
from src.project_paths import ProjectPaths  # noqa: E402


ENRICHED_FIELDS = ("turning_point_detail", "emotional_arc", "key_beats")
_VALID_OPENING_MODES = {
    "in_medias_res", "sensory_hook", "dialogue_hook", "contrast",
}


def _is_already_enriched(card: dict) -> bool:
    return all(card.get(field) for field in ENRICHED_FIELDS)


def _short_pov_name(card: dict) -> str:
    pov = str(card.get("pov_character") or "The POV character").strip()
    return pov.split(" (", 1)[0]


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _lower_sentence_start(text: str) -> str:
    text = _normalize_whitespace(text)
    if not text:
        return text
    return text[:1].lower() + text[1:]


def _split_sentences(text: str) -> list[str]:
    cleaned = _normalize_whitespace(text)
    if not cleaned:
        return []
    return [
        part.strip(" -")
        for part in re.split(r"(?<=[.!?])\s+", cleaned)
        if part.strip(" -")
    ]


def _parse_emotional_arc(card: dict) -> dict[str, str]:
    raw = _normalize_whitespace(str(card.get("emotional_trajectory") or ""))
    if not raw:
        fallback = "heightened pressure"
        return {"start": fallback, "shift": fallback, "end": fallback}

    parts = [
        part.strip(" .")
        for part in re.split(r"\s*(?:->|→)\s*", raw)
        if part.strip(" .")
    ]
    if len(parts) >= 3:
        return {
            "start": parts[0],
            "shift": parts[1],
            "end": parts[-1],
        }
    if len(parts) == 2:
        return {
            "start": parts[0],
            "shift": f"transition from {parts[0].lower()} to {parts[1].lower()}",
            "end": parts[1],
        }
    return {
        "start": parts[0],
        "shift": f"pressure turns around {parts[0].lower()}",
        "end": parts[0],
    }


def _derive_opening_mode(card: dict) -> str | None:
    opening_hook = _normalize_whitespace(str(card.get("opening_hook") or ""))
    if not opening_hook:
        return None

    lowered = opening_hook.lower()
    if (
        opening_hook.startswith(("\"", "'", "“"))
        or any(token in lowered for token in (
            " says ", " asks ", " replies ", " answered ", " shouts ",
            " whispers ",
        ))
    ):
        return "dialogue_hook"

    if any(token in lowered for token in (
        " while ", " but ", " yet ", " though ", " although ", " instead ",
        " contradict", " does not match ", " don't match", " does not fit ",
    )):
        return "contrast"

    if lowered.startswith((
        "inside ", "in the ", "on the ", "under ", "beneath ", "within ",
    )) or any(token in lowered for token in (
        "hum", "silence", "sound", "smell", "scent", "heat", "cold", "taste",
        "shadow", "glow", "void", "wind", "dust", "birds", "viewport",
        "floor", "air", "breath",
    )):
        return "sensory_hook"

    return "in_medias_res"


def _derive_turning_cost(card: dict, emotional_arc: dict[str, str]) -> str:
    pov = _short_pov_name(card)
    stakes = card.get("stakes") or {}
    personal = _normalize_whitespace(str(stakes.get("personal") or ""))
    interpersonal = _normalize_whitespace(str(stakes.get("interpersonal") or ""))
    external = _normalize_whitespace(str(stakes.get("external") or ""))
    end_state = _normalize_whitespace(emotional_arc.get("end", ""))

    fragments = [frag for frag in (personal, interpersonal, external) if frag]
    if fragments:
        primary = fragments[0].rstrip(".")
        if primary.lower().startswith(f"{pov.lower()}'s "):
            primary = primary[len(pov) + 2:]
        if len(fragments) > 1:
            secondary = fragments[1].rstrip(".")
            if secondary.lower().startswith(f"{pov.lower()}'s "):
                secondary = secondary[len(pov) + 2:]
            return f"The cost lands on {pov}: {primary}; it also strains {secondary.lower()}"
        return f"The cost lands on {pov}: {primary}"

    if end_state:
        return (
            f"The cost lands as {end_state.lower()}, forcing {pov} to carry the "
            "scene's new pressure instead of explaining it away"
        )

    mission = _normalize_whitespace(str(card.get("mission") or ""))
    if mission:
        return f"The turn commits {pov} more deeply to {mission.rstrip('.')}"
    return f"The turn forces {pov} to carry a sharper personal cost into the next beat"


def _derive_turning_point_detail(
    card: dict, emotional_arc: dict[str, str],
) -> dict[str, str]:
    existing = card.get("turning_point_detail")
    if isinstance(existing, dict) and all(
        isinstance(existing.get(key), str) and existing.get(key).strip()
        for key in ("trigger", "shift", "cost")
    ):
        return {
            "trigger": existing["trigger"].strip(),
            "shift": existing["shift"].strip(),
            "cost": existing["cost"].strip(),
        }

    turning_point = _normalize_whitespace(str(card.get("turning_point") or ""))
    sentences = _split_sentences(turning_point)
    if len(sentences) >= 2:
        trigger = sentences[0]
        shift = " ".join(sentences[1:])
    elif sentences:
        trigger = sentences[0]
        shift = (
            f"The scene dynamics pivot around {sentences[0].rstrip('.').lower()}, "
            f"turning the pressure toward {emotional_arc['shift'].lower()}"
        )
    else:
        trigger = "The scene reaches its planned turning point"
        shift = (
            f"The pressure pivots toward {emotional_arc['shift'].lower()} as the "
            "scene commits to its consequence"
        )

    return {
        "trigger": trigger.rstrip("."),
        "shift": shift.rstrip("."),
        "cost": _derive_turning_cost(card, emotional_arc).rstrip("."),
    }


def _state_change_for_beat(
    card: dict,
    idx: int,
    total: int,
    turning_detail: dict[str, str],
) -> str:
    mission = _normalize_whitespace(str(card.get("mission") or "the scene mission"))
    closing_hook = _normalize_whitespace(str(card.get("closing_hook") or ""))
    role = str(card.get("scene_role") or "").strip().lower()

    if idx == 0:
        return "The opening pressure becomes concrete instead of abstract."
    if idx == total - 1 and closing_hook:
        if role == "decision":
            return f"A decision locks in and hands off its consequence: {closing_hook.rstrip('.')}"
        if role == "reveal":
            return f"The scene closes on new information that changes the operating picture: {closing_hook.rstrip('.')}"
        return f"The next-scene pressure locks in at the boundary: {closing_hook.rstrip('.')}"
    if idx == total - 2:
        return f"The scene pivots: {turning_detail['shift'].rstrip('.')}"
    return f"Pressure escalates and advances the mission: {mission.rstrip('.')}"


def _pov_reaction_for_beat(
    card: dict, idx: int, total: int, emotional_arc: dict[str, str],
) -> str:
    pov = _short_pov_name(card)
    if idx == 0:
        return (
            f"{pov} feels {_lower_sentence_start(emotional_arc['start'])}, and instinct pushes the "
            "response toward action rather than explanation"
        )
    if idx == total - 1:
        return (
            f"The beat lands as {_lower_sentence_start(emotional_arc['end'])}, leaving {pov} braced "
            "for the scene's handoff pressure"
        )
    return (
        f"The pressure turns toward {_lower_sentence_start(emotional_arc['shift'])}, tightening "
        f"{pov}'s focus on what just changed"
    )


def _derive_key_beats(
    card: dict,
    emotional_arc: dict[str, str],
    turning_detail: dict[str, str],
) -> list[dict[str, str]]:
    existing = card.get("key_beats")
    if isinstance(existing, list) and len(existing) >= 3:
        cleaned: list[dict[str, str]] = []
        for beat in existing[:5]:
            if not isinstance(beat, dict):
                continue
            if all(
                isinstance(beat.get(key), str) and beat.get(key).strip()
                for key in ("beat_description", "state_change", "pov_reaction")
            ):
                cleaned.append({
                    "beat_description": beat["beat_description"].strip(),
                    "state_change": beat["state_change"].strip(),
                    "pov_reaction": beat["pov_reaction"].strip(),
                })
        if len(cleaned) >= 3:
            return cleaned

    beats = [
        _normalize_whitespace(str(beat))
        for beat in (card.get("action_beats") or [])
        if _normalize_whitespace(str(beat))
    ]
    if len(beats) < 3:
        for fallback in (
            card.get("opening_hook"),
            card.get("turning_point"),
            card.get("closing_hook"),
        ):
            text = _normalize_whitespace(str(fallback or ""))
            if text and text not in beats:
                beats.append(text)
            if len(beats) >= 3:
                break

    beats = beats[:5]
    total = len(beats)
    return [
        {
            "beat_description": beat.rstrip("."),
            "state_change": _state_change_for_beat(card, idx, total, turning_detail),
            "pov_reaction": _pov_reaction_for_beat(card, idx, total, emotional_arc),
        }
        for idx, beat in enumerate(beats)
    ]


def _extract_anti_patterns_from_notes(notes: str) -> list[str]:
    if not notes:
        return []

    candidates: list[str] = []
    for sentence in _split_sentences(notes):
        lowered = sentence.lower()
        if not (
            lowered.startswith(("anti-pattern", "anti pattern", "diagnostic-voice trap"))
            or re.search(r"\b(do not|should not|avoid|too composed|cut it)\b", lowered)
            or lowered.startswith("no ")
            or " absolutely no " in f" {lowered} "
        ):
            continue
        extracted = sentence.strip()
        for prefix in (
            "anti-pattern:", "anti-pattern (chapter-level):", "anti pattern:",
            "diagnostic-voice trap —", "diagnostic-voice trap -",
            "diagnostic-voice trap:", "voice trap —", "voice trap:",
        ):
            if lowered.startswith(prefix):
                extracted = sentence[len(prefix):].strip()
                break
        extracted = extracted.rstrip(".")
        if extracted and extracted not in candidates:
            candidates.append(extracted)
    return candidates


def _build_offline_brief(card: dict) -> dict[str, Any]:
    emotional_arc = _parse_emotional_arc(card)
    turning_detail = _derive_turning_point_detail(card, emotional_arc)
    key_beats = _derive_key_beats(card, emotional_arc, turning_detail)

    assembled = BriefAssembler().assemble(card)
    brief = dict(assembled.brief)
    brief["turning_point"] = turning_detail
    brief["emotional_arc"] = emotional_arc

    opening_mode = _derive_opening_mode(card)
    if opening_mode in _VALID_OPENING_MODES:
        brief["opening_mode"] = opening_mode

    if len(key_beats) >= 3:
        brief["key_beats"] = key_beats

    anti_patterns = list(card.get("anti_patterns") or [])
    for item in _extract_anti_patterns_from_notes(str(card.get("notes") or "")):
        if item not in anti_patterns:
            anti_patterns.append(item)
    if anti_patterns:
        brief["anti_patterns"] = anti_patterns

    return brief


def _apply_brief_to_card(card: dict, brief: dict) -> dict:
    """Return a new card dict with brief fields merged onto it.

    The brief's ``turning_point`` object is stored under the card's
    ``turning_point_detail`` key so the legacy string ``turning_point``
    remains valid. Same pattern for ``emotional_arc`` vs. the legacy
    string ``emotional_trajectory``.

    Scene-card field preservation: every key already on the card is kept
    as-is unless the brief supplies a strictly-richer replacement.
    Anti-patterns from the brief are *merged* with any existing card
    anti_patterns rather than replaced, since authors may have added
    hand-written ones the LLM would not recover.
    """
    enriched = dict(card)

    tp_brief = brief.get("turning_point")
    if isinstance(tp_brief, dict) and all(
        k in tp_brief for k in ("trigger", "shift", "cost")
    ):
        enriched["turning_point_detail"] = {
            "trigger": str(tp_brief["trigger"]),
            "shift": str(tp_brief["shift"]),
            "cost": str(tp_brief["cost"]),
        }

    emo_brief = brief.get("emotional_arc")
    if isinstance(emo_brief, dict) and all(
        k in emo_brief for k in ("start", "shift", "end")
    ):
        enriched["emotional_arc"] = {
            "start": str(emo_brief["start"]),
            "shift": str(emo_brief["shift"]),
            "end": str(emo_brief["end"]),
        }

    key_beats = brief.get("key_beats")
    if isinstance(key_beats, list) and len(key_beats) >= 3:
        cleaned: list[dict[str, str]] = []
        for beat in key_beats[:5]:
            if not isinstance(beat, dict):
                continue
            if all(
                isinstance(beat.get(k), str) and beat.get(k)
                for k in ("beat_description", "state_change", "pov_reaction")
            ):
                cleaned.append({
                    "beat_description": beat["beat_description"],
                    "state_change": beat["state_change"],
                    "pov_reaction": beat["pov_reaction"],
                })
        if len(cleaned) >= 3:
            enriched["key_beats"] = cleaned

    opening_mode = brief.get("opening_mode")
    valid_modes = {
        "in_medias_res", "sensory_hook", "dialogue_hook", "contrast",
    }
    if isinstance(opening_mode, str) and opening_mode in valid_modes:
        enriched["opening_mode"] = opening_mode

    anti_from_brief = brief.get("anti_patterns")
    if isinstance(anti_from_brief, list) and anti_from_brief:
        existing = list(enriched.get("anti_patterns") or [])
        merged = list(existing)
        for item in anti_from_brief:
            if isinstance(item, str) and item and item not in merged:
                merged.append(item)
        enriched["anti_patterns"] = merged

    return enriched


async def _enrich_one(
    card_path: Path,
    *,
    plot_architect: PlotArchitect | None,
    assembler: ContextAssembler | None,
    force: bool,
    dry_run: bool,
    offline: bool,
) -> dict[str, Any]:
    """Enrich a single card file. Returns a result summary dict."""
    result: dict[str, Any] = {
        "card": card_path.name,
        "status": "pending",
    }

    try:
        card = json.loads(card_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result["status"] = "error"
        result["error"] = f"could not read card: {type(exc).__name__}: {exc}"
        return result

    if not force and _is_already_enriched(card):
        result["status"] = "skipped_already_enriched"
        return result

    if offline:
        brief = _build_offline_brief(card)
    else:
        try:
            pa_context = {
                "scene_card": card,
                "bible_summary": assembler.get_bible_summary(),
                "franchise_profile_text": assembler.get_franchise_profile_text(),
            }
            pa_result = await plot_architect.run(pa_context)
        except Exception as exc:  # noqa: BLE001
            result["status"] = "error"
            result["error"] = f"plot_architect failed: {type(exc).__name__}: {exc}"
            return result

        brief = pa_result.get("generation_brief") or {}
    enriched = _apply_brief_to_card(card, brief)

    if enriched == card:
        result["status"] = "no_new_fields"
        return result

    new_fields = sorted(set(enriched.keys()) - set(card.keys()))
    overwritten_fields = [
        k for k in enriched.keys() & card.keys()
        if enriched[k] != card[k] and k in {
            "turning_point_detail",
            "emotional_arc",
            "key_beats",
            "opening_mode",
            "anti_patterns",
        }
    ]
    result["new_fields"] = new_fields
    result["overwritten_fields"] = overwritten_fields

    if dry_run:
        result["status"] = "dry_run"
        return result

    card_path.write_text(
        json.dumps(enriched, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    result["status"] = "enriched"
    return result


async def enrich_bundle(
    *,
    franchise_slug: str,
    book_slug: str,
    base_dir: str = ".",
    config_path: str = "config/settings.yaml",
    only_card: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    offline: bool = False,
) -> list[dict[str, Any]]:
    """Enrich every scene card (or a single ``only_card``) in a book."""
    paths = ProjectPaths(
        book_slug, base_dir=base_dir, franchise_slug=franchise_slug,
    )
    scene_cards_dir = paths.scene_cards_dir
    if not scene_cards_dir.exists():
        print(f"[FATAL] no scene_cards dir at {scene_cards_dir}")
        return []

    concept_seed_path = paths.concept_seed_path
    if not concept_seed_path.exists():
        print(f"[FATAL] no concept_seed.json at {concept_seed_path}")
        return []

    router: ModelRouter | None = None
    try:
        assembler: ContextAssembler | None = None
        plot_architect: PlotArchitect | None = None
        if offline:
            print("[offline] using deterministic PlotArchitect fallback")
        else:
            router = ModelRouter(config_path)
            ok, msg = await router.health_check()
            if not ok:
                print(f"[FATAL] model router health check failed: {msg}")
                return []
            print(f"[ok] {msg}")

            assembler = ContextAssembler(
                concept_seed_path=str(concept_seed_path),
            )
            plot_architect = PlotArchitect(router)

        card_files: list[Path]
        if only_card:
            target = scene_cards_dir / only_card
            if not target.exists():
                print(f"[FATAL] --card {only_card} not found at {target}")
                return []
            card_files = [target]
        else:
            card_files = sorted(
                scene_cards_dir.glob("chapter_*_scene_*.json")
            )

        print(
            f"[enrich] {franchise_slug}/{book_slug}: "
            f"{len(card_files)} card(s); force={force} dry_run={dry_run} "
            f"offline={offline}"
        )
        results: list[dict[str, Any]] = []
        for path in card_files:
            print(f"  - {path.name} ...", end=" ", flush=True)
            result = await _enrich_one(
                path,
                plot_architect=plot_architect,
                assembler=assembler,
                force=force,
                dry_run=dry_run,
                offline=offline,
            )
            print(result["status"])
            if result.get("error"):
                print(f"    error: {result['error']}")
            if result.get("new_fields"):
                print(f"    new fields: {result['new_fields']}")
            if result.get("overwritten_fields"):
                print(f"    overwritten: {result['overwritten_fields']}")
            results.append(result)
        return results
    finally:
        if router is not None:
            await router.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--franchise", required=True)
    parser.add_argument("--book", required=True)
    parser.add_argument("--base-dir", default=".")
    parser.add_argument("--config", default="config/settings.yaml")
    parser.add_argument(
        "--card",
        default=None,
        help="Enrich only this scene card filename (e.g. chapter_01_scene_01.json).",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--offline",
        action="store_true",
        help=(
            "Skip the live PlotArchitect model call and derive the enriched "
            "brief deterministically from the existing scene card."
        ),
    )
    args = parser.parse_args()

    results = asyncio.run(enrich_bundle(
        franchise_slug=args.franchise,
        book_slug=args.book,
        base_dir=args.base_dir,
        config_path=args.config,
        only_card=args.card,
        force=args.force,
        dry_run=args.dry_run,
        offline=args.offline,
    ))

    enriched = sum(1 for r in results if r["status"] == "enriched")
    dry = sum(1 for r in results if r["status"] == "dry_run")
    skipped = sum(
        1 for r in results if r["status"] == "skipped_already_enriched"
    )
    errors = sum(1 for r in results if r["status"] == "error")
    print(
        f"\n[done] enriched={enriched} dry_run={dry} "
        f"skipped={skipped} errors={errors}"
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
