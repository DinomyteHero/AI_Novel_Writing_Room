"""Phase 6.2 — spawn a Book N+1 project from a Book N transition snapshot.

Reads:
  - ``data/franchises/<fr>/books/<source>/concept_seed.json``
  - ``data/franchises/<fr>/books/<source>/book_<N>_transition.json``
    (as produced by ``SeriesManager.generate_transition_snapshot`` at the
    end of Book N's run)

Writes:
  - ``data/franchises/<fr>/books/<target>/concept_seed.json``
    — derived from the source seed, with ``meta.book_number`` bumped,
    project_scope set to ``continuation``, inherited hooks prepended, and
    an ``extended_metadata.book_transition`` audit block recording what
    carried over.
  - The series-scoped StoryState (at ``output/<fr>/<series>/state/...``
    when the seed declares a ``series_id``, otherwise per-book) is seeded
    with the snapshot's character end-states, arcs, threads, unresolved
    hooks, and unfired Chekhov guns via
    ``StoryState.initialize_from_transition``.

Does NOT:
  - Run the workflow-kit per-surface authoring. The spawned seed is a
    structural scaffold; Book N+1's human author still fills in the
    chapter outline, new scene cards, and revelation schedule. A future
    revision pass may invoke ``scripts/compile_bundle.py`` when workflow-
    surface artifacts exist under the target book's ``workflows/``.
  - Modify the source book's files.

Usage:
    python scripts/spawn_next_book.py \\
        --franchise star-wars-legends-eu \\
        --from-book the-ruusan-atonement \\
        --to-book the-ruusan-atonement-book-2 \\
        [--title "The Ruusan Atonement, Book 2"] \\
        [--base-dir .] \\
        [--dry-run]

``--dry-run`` prints the summary without writing anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.concept_workshop.series_manager import SeriesManager  # noqa: E402
from src.memory.story_state import StoryState  # noqa: E402
from src.project_paths import ProjectPaths, slugify_title  # noqa: E402


@dataclass
class SpawnResult:
    """Summary of what the spawn produced."""

    target_seed_path: Path | None = None
    target_story_state_path: Path | None = None
    source_book_number: int = 0
    target_book_number: int = 0
    inherited_hook_ids: list[str] = field(default_factory=list)
    carried_character_ids: list[str] = field(default_factory=list)
    initialization_counts: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict:
        return {
            "target_seed_path": (
                str(self.target_seed_path) if self.target_seed_path else None
            ),
            "target_story_state_path": (
                str(self.target_story_state_path)
                if self.target_story_state_path else None
            ),
            "source_book_number": self.source_book_number,
            "target_book_number": self.target_book_number,
            "inherited_hook_ids": self.inherited_hook_ids,
            "carried_character_ids": self.carried_character_ids,
            "initialization_counts": self.initialization_counts,
            "warnings": self.warnings,
            "dry_run": self.dry_run,
        }


def _find_latest_snapshot(
    book_dir: Path, explicit_book_number: int | None = None
) -> tuple[Path, int]:
    """Locate the source book's transition snapshot.

    When ``explicit_book_number`` is provided, checks that specific file.
    Otherwise returns the highest-numbered snapshot present in the dir.
    Raises FileNotFoundError when nothing matches.
    """
    if explicit_book_number is not None:
        path = book_dir / f"book_{explicit_book_number}_transition.json"
        if not path.exists():
            raise FileNotFoundError(
                f"transition snapshot not found: {path}"
            )
        return path, explicit_book_number

    candidates: list[tuple[int, Path]] = []
    for path in book_dir.glob("book_*_transition.json"):
        stem = path.stem  # book_N_transition
        parts = stem.split("_")
        try:
            n = int(parts[1])
        except (IndexError, ValueError):
            continue
        candidates.append((n, path))
    if not candidates:
        raise FileNotFoundError(
            f"no book_*_transition.json files in {book_dir}; "
            f"run the source book pipeline to completion first"
        )
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1][1], candidates[-1][0]


def _derive_target_seed(
    source_seed: dict,
    *,
    target_title: str | None,
    target_book_number: int,
) -> dict:
    """Return a deep copy of ``source_seed`` tailored for the target book.

    The caller is responsible for applying the transition snapshot
    afterward (via ``SeriesManager.apply_transition_to_seed``).
    """
    import copy as _copy

    seed = _copy.deepcopy(source_seed)
    meta = seed.setdefault("meta", {})
    if target_title:
        meta["project_title"] = target_title
    else:
        existing = meta.get("project_title", "Untitled")
        meta["project_title"] = f"{existing} (Book {target_book_number})"
    meta["book_number"] = target_book_number
    meta["project_scope"] = "continuation"
    # The source seed's scene_cards array is always empty post-install,
    # but clear it defensively — the target book has its own outline.
    seed["scene_cards"] = []
    # Drop source-book revelations/subplots/hooks that are purely
    # structural for Book N — the transition snapshot + human author
    # decide what carries. Keep the skeleton so schema validation stays
    # green; planner will repopulate.
    for key in ("revelation_schedule", "subplots"):
        seed.pop(key, None)
    seed["hooks"] = []
    return seed


def spawn_next_book(
    *,
    from_book: str,
    to_book: str,
    franchise: str,
    base_dir: str = ".",
    title: str | None = None,
    dry_run: bool = False,
    source_book_number: int | None = None,
) -> SpawnResult:
    """Spawn a Book N+1 project from the source book's transition snapshot.

    Returns a ``SpawnResult`` summarizing what was produced. When
    ``dry_run`` is True, nothing is written to disk.
    """
    result = SpawnResult(dry_run=dry_run)

    # Resolve source book.
    source_paths = ProjectPaths(
        from_book, base_dir=base_dir, franchise_slug=franchise
    )
    source_seed_path = source_paths.concept_seed_path
    if not source_seed_path.exists():
        raise FileNotFoundError(
            f"source concept seed not found: {source_seed_path}"
        )
    source_seed = json.loads(source_seed_path.read_text(encoding="utf-8"))

    # Locate the transition snapshot.
    snapshot_path, source_bn = _find_latest_snapshot(
        source_paths.book_dir, source_book_number
    )
    result.source_book_number = source_bn

    # Load + validate via SeriesManager (raises on missing required fields).
    mgr = SeriesManager(source_paths.book_dir)
    snapshot = mgr.import_transition_snapshot(snapshot_path)
    if snapshot.get("book_number") != source_bn:
        result.warnings.append(
            f"snapshot.book_number={snapshot.get('book_number')} does not "
            f"match filename book number {source_bn}; using filename value"
        )
        snapshot["book_number"] = source_bn

    target_bn = source_bn + 1
    result.target_book_number = target_bn

    # Build the target seed.
    target_seed = _derive_target_seed(
        source_seed, target_title=title, target_book_number=target_bn
    )
    SeriesManager.apply_transition_to_seed(target_seed, snapshot)
    result.inherited_hook_ids = list(
        target_seed.get("extended_metadata", {})
        .get("book_transition", {})
        .get("inherited_hook_ids", [])
    )
    result.carried_character_ids = list(
        target_seed.get("extended_metadata", {})
        .get("book_transition", {})
        .get("carried_character_ids", [])
    )

    # Resolve target paths.
    target_paths = ProjectPaths(
        slugify_title(to_book),
        base_dir=base_dir,
        franchise_slug=franchise,
        series_slug=source_paths.series_slug,
        cosmology_slug=source_paths.cosmology_slug,
    )
    result.target_seed_path = target_paths.concept_seed_path
    result.target_story_state_path = target_paths.story_state_db

    if dry_run:
        return result

    # Write target seed.
    target_paths.ensure_dirs()
    target_paths.concept_seed_path.write_text(
        json.dumps(target_seed, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    # Initialize target StoryState from the snapshot.
    state = StoryState(db_path=str(target_paths.story_state_db))
    try:
        counts = state.initialize_from_transition(
            snapshot, target_book_number=target_bn
        )
        result.initialization_counts = counts
    finally:
        state.close()

    return result


def _format_summary(result: SpawnResult) -> str:
    lines = [
        f"Spawn Book {result.target_book_number} "
        f"(from Book {result.source_book_number})",
    ]
    if result.dry_run:
        lines.append("  [DRY-RUN] no files written")
    if result.target_seed_path:
        lines.append(f"  target seed: {result.target_seed_path}")
    if result.target_story_state_path:
        lines.append(
            f"  target story state: {result.target_story_state_path}"
        )
    lines.append(
        f"  carried characters: {len(result.carried_character_ids)}"
    )
    lines.append(
        f"  inherited hooks: {len(result.inherited_hook_ids)}"
    )
    if result.initialization_counts:
        c = result.initialization_counts
        lines.append(
            "  state initialized: "
            f"{c.get('characters', 0)} characters, "
            f"{c.get('arcs', 0)} arcs, "
            f"{c.get('threads', 0)} threads, "
            f"{c.get('hooks', 0)} hooks, "
            f"{c.get('guns', 0)} unfired guns"
        )
    if result.warnings:
        lines.append(f"  warnings ({len(result.warnings)}):")
        for w in result.warnings:
            lines.append(f"    - {w}")
    return "\n".join(lines)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Spawn a Book N+1 project from a Book N transition snapshot."
        ),
    )
    parser.add_argument("--franchise", required=True, help="Franchise slug")
    parser.add_argument(
        "--from-book", required=True, help="Source book slug (the Book N)"
    )
    parser.add_argument(
        "--to-book", required=True, help="Target book slug (the Book N+1)"
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional human-readable title for the target book",
    )
    parser.add_argument("--base-dir", default=".", help="Repository root")
    parser.add_argument(
        "--source-book-number",
        type=int,
        default=None,
        help=(
            "Override the source book number (otherwise auto-detected "
            "from the latest book_*_transition.json in the source dir)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary without writing any files.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        result = spawn_next_book(
            from_book=args.from_book,
            to_book=args.to_book,
            franchise=args.franchise,
            base_dir=args.base_dir,
            title=args.title,
            dry_run=args.dry_run,
            source_book_number=args.source_book_number,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(_format_summary(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
