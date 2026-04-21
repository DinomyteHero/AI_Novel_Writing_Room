#!/usr/bin/env python3
"""Slice 6 manuscript export stitcher.

Concatenates saved ``chapter_XX_scene_YY.md`` files from a run directory
into a single ``manuscript.md`` under ``<project_root>/export/``, plus a
``chapter_index.md`` with per-chapter word counts. Deliberately simple \u2014
later slices wrap this with EPUB / PDF rendering; the source markdown is
always the unit of truth.

Usage:
    py -3 scripts/manuscript_export.py \\
        --seed data/franchises/<franchise>/books/<book>/concept_seed.json \\
        --run-dir output/<franchise>/<book>/runs/<run_id>
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


_FILE_RE = re.compile(r"^chapter_(\d{2})_scene_(\d{2})\.md$")


def _discover_scenes(chapters_dir: Path) -> list[tuple[int, int, Path]]:
    if not chapters_dir.exists():
        return []
    out: list[tuple[int, int, Path]] = []
    for path in sorted(chapters_dir.iterdir()):
        if not path.is_file():
            continue
        m = _FILE_RE.match(path.name)
        if not m:
            continue
        out.append((int(m.group(1)), int(m.group(2)), path))
    out.sort(key=lambda t: (t[0], t[1]))
    return out


def stitch(*, run_dir: Path, export_dir: Path) -> tuple[Path, Path, int]:
    """Concatenate scenes into a manuscript + word-count index.

    Returns (manuscript_path, index_path, total_word_count).
    """
    chapters_dir = run_dir / "chapters"
    scenes = _discover_scenes(chapters_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    manuscript_path = export_dir / "manuscript.md"
    index_path = export_dir / "chapter_index.md"

    parts: list[str] = []
    per_chapter_counts: dict[int, int] = {}
    total_words = 0

    current_chapter: int | None = None
    for chapter, scene, path in scenes:
        text = path.read_text(encoding="utf-8")
        word_count = len(text.split())
        per_chapter_counts[chapter] = per_chapter_counts.get(chapter, 0) + word_count
        total_words += word_count
        if chapter != current_chapter:
            parts.append(f"# Chapter {chapter}\n")
            current_chapter = chapter
        parts.append(f"## Scene {chapter:02d}.{scene:02d}\n")
        parts.append(text.rstrip() + "\n")

    manuscript_path.write_text("\n".join(parts), encoding="utf-8")

    index_lines = [
        "# Manuscript index",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Scenes stitched: {len(scenes)}",
        f"- Total word count: {total_words:,}",
        "",
        "## Per-chapter word count",
        "",
    ]
    for chapter in sorted(per_chapter_counts):
        index_lines.append(f"- Chapter {chapter}: {per_chapter_counts[chapter]:,} words")
    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    return manuscript_path, index_path, total_words


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True, help="Path to concept_seed.json")
    parser.add_argument("--run-dir", required=True, help="Run directory (parent of chapters/).")
    parser.add_argument(
        "--export-dir", default=None,
        help="Optional explicit export dir; defaults to <project_root>/export/.",
    )
    args = parser.parse_args(argv)

    from src.project_paths import ProjectPaths
    paths = ProjectPaths.from_concept_seed_path(Path(args.seed))
    run_dir = Path(args.run_dir).resolve()
    export_dir = Path(args.export_dir) if args.export_dir else paths.export_dir
    manuscript_path, index_path, total = stitch(run_dir=run_dir, export_dir=export_dir)
    print(f"Wrote {manuscript_path}")
    print(f"Wrote {index_path}")
    print(f"Total words: {total:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
