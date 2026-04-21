#!/usr/bin/env python3
"""Slice 6 patch-workflow CLI.

Human-gated path for manuscript-level mutations. Bridges the forward-only
scene runtime with coherent manuscript edits. Every subcommand emits
``gap_note_resolved`` / ``revision_debt_updated`` events through the run
ledger where applicable. See
``docs/architecture/manuscript_lifecycle_design.md``.

Subcommands:

    accept-isolated <scene_id>
        Promote a quarantined scene at <project>/quarantine/chNN_scMM/prose.md
        to a trusted saved scene in the run manuscripts dir. Resolves every
        open gap whose isolated_scene matches; marks downstream overlays
        stale; re-applies the scene card's declarative state.

    replace <scene_id> --from <path> [--gap <gap_id>] [--notes <text>]
        Overwrite a saved scene with new prose. Optionally resolves a
        specific gap. Re-applies declarative state.

    overrule <gap_id> [--notes <text>]
        Mark a gap resolved without changing prose. Records the overrule
        rationale.

    apply-manuscript-patch <patch_path>
        JSON matching schemas/manuscript_patch.json \u2014 each entry dispatches
        through the matching subcommand.

All subcommands require --seed <concept_seed.json> + --run-dir <path>
(so ProjectPaths can resolve franchise / book / state / quarantine layout).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).parent.parent))


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _parse_scene_id(scene_id: str) -> tuple[int, int] | None:
    import re
    m = re.match(r"^ch(\d{2})_sc(\d{2})$", scene_id or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _scene_id(chapter: int, scene: int) -> str:
    return f"ch{chapter:02d}_sc{scene:02d}"


def _load_scene_card(book_dir: Path, scene_id: str) -> dict | None:
    parsed = _parse_scene_id(scene_id)
    if parsed is None:
        return None
    chapter, scene = parsed
    filename = f"chapter_{chapter:02d}_scene_{scene:02d}.json"
    path = book_dir / "scene_cards" / filename
    if not path.exists():
        return None
    data = _load_json(path)
    if isinstance(data, dict):
        return data
    return None


# --------------------------------------------------------------------------- #
# Environment resolver                                                        #
# --------------------------------------------------------------------------- #


class _PatchEnv:
    """Bundle of the handles each subcommand needs. Built once per CLI
    invocation so subcommands can pass it around without re-opening SQLite.
    """

    def __init__(
        self, *, seed_path: Path, run_dir: Path, ledger_dry_run: bool,
        base_dir: Path | str = ".",
    ):
        from src.memory.story_state import StoryState
        from src.project_paths import ProjectPaths
        from src.run_ledger import RunLedger

        self.seed_path = seed_path
        self.run_dir = run_dir.resolve()
        self.manuscripts_dir = self.run_dir / "chapters"
        self.quarantine_dir = self.run_dir / "quarantine"
        self.packets_dir = self.run_dir / "chapter_packets"
        self.concept_seed = _load_json(seed_path)
        self.paths = ProjectPaths.from_concept_seed_path(
            str(seed_path), base_dir=str(base_dir),
        )
        self.book_dir = seed_path.parent
        self.story_state = StoryState(db_path=str(self.paths.story_state_db))
        ledger_path = self.paths.state_dir / "run_ledger.db"
        self.ledger = RunLedger(db_path=str(ledger_path), run_id=f"patch_{_iso_now()}") if not ledger_dry_run else None

    def close(self) -> None:
        try:
            self.story_state.close()
        except Exception:  # noqa: BLE001
            pass

    # -------------------------------------------------- optional stores

    def open_promise_ledger(self):
        from src.memory.promise_ledger import PromiseLedger
        return PromiseLedger(db_path=str(self.paths.state_dir / "promise_ledger.db"))

    def open_sociogram(self):
        from src.memory.sociogram import Sociogram
        return Sociogram(db_path=str(self.paths.state_dir / "sociogram.db"))


# --------------------------------------------------------------------------- #
# Replay                                                                      #
# --------------------------------------------------------------------------- #


def _replay_declarative_state(env: _PatchEnv, *, scene_id: str) -> dict:
    """Replay scene-card-declared promise + sociogram state. Returns a
    summary dict the caller uses for logging."""
    card = _load_scene_card(env.book_dir, scene_id)
    summary = {"scene_id": scene_id, "promise_updates": 0, "sociogram_updates": 0,
               "scene_card_found": card is not None}
    if card is None:
        return summary

    # Promise ledger replay \u2014 best effort. Missing DB = no replay.
    ledger_path = env.paths.state_dir / "promise_ledger.db"
    if ledger_path.exists():
        pl = env.open_promise_ledger()
        try:
            for pid in card.get("promises_progressed") or []:
                try:
                    pl.record_progression(
                        promise_id=pid, scene_id=scene_id,
                        source="scene_card", note="patch_workflow replay",
                    )
                    summary["promise_updates"] += 1
                except KeyError:
                    continue
            for pid in card.get("promises_paid") or []:
                try:
                    pl.record_payoff(promise_id=pid, scene_id=scene_id)
                    summary["promise_updates"] += 1
                except KeyError:
                    continue
        finally:
            pl.close()

    # Sociogram replay.
    socio_path = env.paths.state_dir / "sociogram.db"
    if socio_path.exists():
        graph = env.open_sociogram()
        try:
            updates = graph.apply_scene_deltas(scene_card=card)
            summary["sociogram_updates"] = len(updates)
        finally:
            graph.close()
    return summary


def _mark_overlays_stale(env: _PatchEnv, scene_ids: list[str]) -> int:
    """Write empty ``.STALE`` marker files so the next drafting run rebuilds
    the overlay instead of reusing the cached per-scene JSON."""
    if not scene_ids:
        return 0
    env.packets_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for sid in scene_ids:
        parsed = _parse_scene_id(sid)
        if parsed is None:
            continue
        chapter, scene = parsed
        marker = env.packets_dir / f"chapter_{chapter:02d}_sc_{scene:02d}_overlay.STALE"
        marker.write_text(_iso_now(), encoding="utf-8")
        count += 1
    return count


def _affected_scene_ids(env: _PatchEnv, scene_id: str) -> list[str]:
    """Collect every downstream scene id touched by open gaps for this
    scene (spec \u00a710.3 step 4)."""
    out: list[str] = []
    for gap in env.story_state.list_gaps_affecting(scene_id):
        out.extend(gap.get("affected_scenes") or [])
    # dedupe while preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for sid in out:
        if sid not in seen and sid != scene_id:
            seen.add(sid)
            ordered.append(sid)
    return ordered


# --------------------------------------------------------------------------- #
# Subcommands                                                                 #
# --------------------------------------------------------------------------- #


def cmd_accept_isolated(env: _PatchEnv, scene_id: str, *, notes: str) -> int:
    parsed = _parse_scene_id(scene_id)
    if parsed is None:
        print(f"accept-isolated: scene_id {scene_id!r} must match chNN_scMM")
        return 2
    chapter, scene = parsed
    q_dir = env.quarantine_dir / f"ch{chapter:02d}_sc{scene:02d}"
    prose_src = q_dir / "prose.md"
    if not prose_src.exists():
        print(f"accept-isolated: no quarantine prose at {prose_src}")
        return 2

    env.manuscripts_dir.mkdir(parents=True, exist_ok=True)
    dest = env.manuscripts_dir / f"chapter_{chapter:02d}_scene_{scene:02d}.md"
    dest.write_text(prose_src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"accept-isolated: promoted {prose_src} -> {dest}")

    # Resolve matching gaps and mark downstream overlays stale.
    gaps_resolved = 0
    affected: list[str] = []
    for gap in env.story_state.list_open_gaps():
        if gap["isolated_scene"] != scene_id:
            continue
        gap_id = gap["gap_id"]
        env.story_state.resolve_gap(
            gap_id, resolved_by="human_patch_accept", notes=notes,
        )
        gaps_resolved += 1
        affected.extend(gap.get("affected_scenes") or [])
        if env.ledger is not None:
            env.ledger.emit_info(
                "gap_note_resolved",
                chapter_number=chapter, scene_number=scene,
                payload={
                    "gap_id": gap_id, "resolved_by": "human_patch_accept",
                    "scene_id": scene_id,
                },
            )

    stale_written = _mark_overlays_stale(env, affected)
    replay = _replay_declarative_state(env, scene_id=scene_id)

    print(
        f"accept-isolated: gaps_resolved={gaps_resolved} "
        f"stale_markers={stale_written} "
        f"promise_updates={replay['promise_updates']} "
        f"sociogram_updates={replay['sociogram_updates']}"
    )
    return 0


def cmd_replace(
    env: _PatchEnv, scene_id: str, *, prose_path: Path, gap_id: str | None,
    notes: str,
) -> int:
    parsed = _parse_scene_id(scene_id)
    if parsed is None:
        print(f"replace: scene_id {scene_id!r} must match chNN_scMM")
        return 2
    if not prose_path.exists():
        print(f"replace: prose source not found at {prose_path}")
        return 2
    chapter, scene = parsed
    env.manuscripts_dir.mkdir(parents=True, exist_ok=True)
    dest = env.manuscripts_dir / f"chapter_{chapter:02d}_scene_{scene:02d}.md"
    dest.write_text(prose_path.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"replace: wrote {dest}")

    affected = _affected_scene_ids(env, scene_id)
    stale_written = _mark_overlays_stale(env, affected)

    if gap_id:
        env.story_state.resolve_gap(
            gap_id, resolved_by="human_replace", notes=notes,
        )
        if env.ledger is not None:
            env.ledger.emit_info(
                "gap_note_resolved",
                chapter_number=chapter, scene_number=scene,
                payload={
                    "gap_id": gap_id, "resolved_by": "human_replace",
                    "scene_id": scene_id,
                },
            )

    replay = _replay_declarative_state(env, scene_id=scene_id)
    print(
        f"replace: stale_markers={stale_written} "
        f"promise_updates={replay['promise_updates']} "
        f"sociogram_updates={replay['sociogram_updates']}"
    )
    return 0


def cmd_overrule(env: _PatchEnv, gap_id: str, *, notes: str) -> int:
    try:
        env.story_state.resolve_gap(gap_id, resolved_by="overrule", notes=notes)
    except KeyError:
        print(f"overrule: no gap with gap_id={gap_id!r}")
        return 2
    if env.ledger is not None:
        env.ledger.emit_info(
            "gap_note_resolved",
            payload={"gap_id": gap_id, "resolved_by": "overrule", "notes": notes},
        )
    print(f"overrule: resolved gap {gap_id}")
    return 0


def cmd_apply_manuscript_patch(env: _PatchEnv, patch_path: Path) -> int:
    if not patch_path.exists():
        print(f"apply-manuscript-patch: {patch_path} not found")
        return 2
    patch = _load_json(patch_path)
    if not isinstance(patch, dict) or "entries" not in patch:
        print("apply-manuscript-patch: patch must be a dict with an 'entries' list")
        return 2

    # Validate no duplicate replace entries for the same scene.
    seen_replace: set[str] = set()
    for entry in patch.get("entries", []):
        if entry.get("action") == "replace":
            sid = entry.get("scene_id")
            if not sid:
                continue
            if sid in seen_replace:
                print(f"apply-manuscript-patch: duplicate replace for {sid}")
                return 2
            seen_replace.add(sid)

    rc = 0
    for entry in patch.get("entries", []):
        action = entry.get("action")
        notes = str(entry.get("notes", "") or "")
        if action == "accept-isolated":
            rc |= cmd_accept_isolated(env, entry.get("scene_id", ""), notes=notes)
        elif action == "replace":
            prose_path = Path(entry.get("prose_path") or "")
            rc |= cmd_replace(
                env, entry.get("scene_id", ""),
                prose_path=prose_path, gap_id=entry.get("gap_id"), notes=notes,
            )
        elif action == "overrule":
            rc |= cmd_overrule(env, entry.get("gap_id", ""), notes=notes)
        else:
            print(f"apply-manuscript-patch: unknown action {action!r}")
            rc |= 2
    return rc


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed", required=True, help="Path to concept_seed.json")
    parser.add_argument("--run-dir", required=True, help="Run directory (parent of chapters/)")
    parser.add_argument(
        "--base-dir", default=".",
        help="Repo root used by ProjectPaths to resolve output/ state. "
             "Defaults to cwd; tests override to a tmp directory.",
    )
    parser.add_argument(
        "--no-ledger", action="store_true",
        help="Skip ledger emission (test/dry-run mode).",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_accept = sub.add_parser("accept-isolated", help="Promote a quarantined scene.")
    _add_common(p_accept)
    p_accept.add_argument("scene_id")
    p_accept.add_argument("--notes", default="")

    p_replace = sub.add_parser("replace", help="Overwrite prose with a human-edited file.")
    _add_common(p_replace)
    p_replace.add_argument("scene_id")
    p_replace.add_argument("--from", dest="from_path", required=True)
    p_replace.add_argument("--gap", dest="gap_id")
    p_replace.add_argument("--notes", default="")

    p_over = sub.add_parser("overrule", help="Resolve a gap without changing prose.")
    _add_common(p_over)
    p_over.add_argument("gap_id")
    p_over.add_argument("--notes", default="")

    p_patch = sub.add_parser("apply-manuscript-patch", help="Apply a JSON patch bundle.")
    _add_common(p_patch)
    p_patch.add_argument("patch_path")

    args = parser.parse_args(argv)
    env = _PatchEnv(
        seed_path=Path(args.seed),
        run_dir=Path(args.run_dir),
        ledger_dry_run=bool(getattr(args, "no_ledger", False)),
        base_dir=getattr(args, "base_dir", "."),
    )
    try:
        if args.cmd == "accept-isolated":
            return cmd_accept_isolated(env, args.scene_id, notes=args.notes)
        if args.cmd == "replace":
            return cmd_replace(
                env, args.scene_id,
                prose_path=Path(args.from_path),
                gap_id=args.gap_id, notes=args.notes,
            )
        if args.cmd == "overrule":
            return cmd_overrule(env, args.gap_id, notes=args.notes)
        if args.cmd == "apply-manuscript-patch":
            return cmd_apply_manuscript_patch(env, Path(args.patch_path))
        parser.error(f"unknown command {args.cmd!r}")
        return 2
    finally:
        env.close()


if __name__ == "__main__":
    raise SystemExit(main())
