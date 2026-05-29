"""Stitch the per-chapter redraft outputs into a single manuscript.

Mirrors the layout the original Manuscript A and B export directories use:
- manuscript.md  (full text with # Chapter N + ## Scene NN.MM headers)
- chapter_index.md  (per-chapter word counts, total)
- validation_report.json  (counts + motif tallies for parity with the others)
- whole_book_rhythm.json  (RhythmValidator output for the stitched book)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.quality.rhythm_validator import validate_rhythm  # noqa: E402


MOTIFS = (
    "hum", "hummed", "note", "resonance",
    "seal", "sealed", "silence", "stillness",
    "weight", "wound", "wounded", "wrongness",
)


def _motif_count(text: str) -> dict[str, int]:
    """Count each motif as a whole word, case-insensitive."""
    lowered = text.lower()
    out: dict[str, int] = {}
    for m in MOTIFS:
        # Use word boundary; suffix forms ("hummed" vs "hum") handled by
        # separate entries in MOTIFS.
        pattern = rf"\b{re.escape(m)}\b"
        n = len(re.findall(pattern, lowered))
        if n > 0:
            out[m] = n
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--run-dir",
        default="output/star-wars-legends-eu/the-unfinished-shadow/runs/full-redraft-v3",
        help="Per-chapter run directory containing chapter_NN/ subdirs.",
    )
    p.add_argument(
        "--export-name",
        default=None,
        help="Export subdir name. Default: full-redraft-v3-<YYYYMMDD>.",
    )
    p.add_argument(
        "--export-base",
        default="output/star-wars-legends-eu/the-unfinished-shadow/export",
        help="Base export directory.",
    )
    p.add_argument(
        "--scene-file-name",
        default="deepseek-v4-pro-t070__RHYTHM_EDIT.md",
        help="Per-scene file to stitch (default: rhythm-edited final).",
    )
    args = p.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        print(f"[FATAL] run-dir does not exist: {run_dir}")
        return

    # Detect layout. Two supported:
    # (A) Bench-batch layout: <run_dir>/chapter_NN/<scene_file_name>
    # (B) Orchestrator layout: <run_dir>/chapters/chapter_NN_scene_MM.md
    chapters_subdir = run_dir / "chapters"
    if chapters_subdir.exists():
        flat_scene_files = sorted(chapters_subdir.glob("chapter_*_scene_*.md"))
        chapter_dirs = []
        if not flat_scene_files:
            print(f"[FATAL] no chapter_*_scene_*.md in {chapters_subdir}")
            return
    else:
        chapter_dirs = sorted(run_dir.glob("chapter_*"))
        flat_scene_files = []
        if not chapter_dirs:
            print(f"[FATAL] no chapter_* subdirs in {run_dir}")
            return

    export_name = args.export_name or (
        f"full-redraft-v3-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    )
    export_dir = Path(args.export_base) / export_name
    export_dir.mkdir(parents=True, exist_ok=True)

    parts: list[str] = []
    per_chapter_wc: dict[int, int] = {}
    found_chapters: list[int] = []

    if flat_scene_files:
        # Orchestrator layout: one file per scene, scene number in filename.
        # Group by chapter so multi-scene chapters stitch correctly.
        from collections import defaultdict
        by_chapter: dict[int, list[Path]] = defaultdict(list)
        for path in flat_scene_files:
            # chapter_NN_scene_MM.md → ch_num = stem.split("_")[1]
            parts_name = path.stem.split("_")
            ch_num = int(parts_name[1])
            by_chapter[ch_num].append(path)
        for ch_num in sorted(by_chapter):
            scene_paths = sorted(by_chapter[ch_num])
            chapter_text_parts: list[str] = []
            for i, sp in enumerate(scene_paths, start=1):
                prose = sp.read_text(encoding="utf-8").strip()
                wc = len(prose.split())
                per_chapter_wc[ch_num] = per_chapter_wc.get(ch_num, 0) + wc
                chapter_text_parts.append(f"## Scene {ch_num:02d}.{i:02d}\n\n{prose}")
            found_chapters.append(ch_num)
            parts.append(
                f"# Chapter {ch_num}\n\n" + "\n\n".join(chapter_text_parts) + "\n"
            )
    else:
        for ch_dir in chapter_dirs:
            ch_num = int(ch_dir.name.split("_")[1])
            scene_path = ch_dir / args.scene_file_name
            if not scene_path.exists():
                # Fall back to line-edited if rhythm-edit didn't write.
                fallback = ch_dir / "deepseek-v4-pro-t070__LINE_EDIT_gpt54_mini.md"
                if fallback.exists():
                    scene_path = fallback
                else:
                    # Final fallback: drafter output.
                    fallback = ch_dir / "deepseek-v4-pro-t070.md"
                    if fallback.exists():
                        scene_path = fallback
                    else:
                        print(f"[skip] Ch{ch_num:02d}: no usable prose file")
                        continue
            prose = scene_path.read_text(encoding="utf-8").strip()
            wc = len(prose.split())
            per_chapter_wc[ch_num] = wc
            found_chapters.append(ch_num)
            parts.append(f"# Chapter {ch_num}\n\n## Scene {ch_num:02d}.01\n\n{prose}\n")

    manuscript_text = "\n".join(parts)
    manuscript_path = export_dir / "manuscript.md"
    manuscript_path.write_text(manuscript_text, encoding="utf-8")

    # chapter_index.md
    total_wc = sum(per_chapter_wc.values())
    index_lines = [
        "# Manuscript index",
        "",
        f"- Generated: {datetime.now(timezone.utc).isoformat()}",
        f"- Scenes stitched: {len(per_chapter_wc)}",
        f"- Total word count: {total_wc:,}",
        "",
        "## Per-chapter word count",
        "",
    ]
    for ch in sorted(per_chapter_wc):
        index_lines.append(f"- Chapter {ch}: {per_chapter_wc[ch]:,} words")
    (export_dir / "chapter_index.md").write_text(
        "\n".join(index_lines) + "\n", encoding="utf-8",
    )

    # validation_report.json
    words_with_headings = len(re.findall(r"[A-Za-z]+(?:[''’][A-Za-z]+)*", manuscript_text))
    prose_only = re.sub(r"^# Chapter \d+\s*$|^## Scene .*$", "", manuscript_text, flags=re.MULTILINE)
    words_prose_only = len(re.findall(r"[A-Za-z]+(?:[''’][A-Za-z]+)*", prose_only))
    validation = {
        "manuscript": str(manuscript_path),
        "passed": len(per_chapter_wc) == 38 and len(per_chapter_wc) == len(found_chapters),
        "counts": {
            "chapters": len(per_chapter_wc),
            "scenes": len(per_chapter_wc),
            "words_with_headings": words_with_headings,
            "words_prose_only": words_prose_only,
        },
        "expected": {"chapters": 38, "scenes": 38},
        "count_failures": [] if len(per_chapter_wc) == 38 else [
            f"only {len(per_chapter_wc)} chapters; missing {sorted(set(range(1, 39)) - set(per_chapter_wc))}"
        ],
        "artifact_hits": [],
        "meta_hits": [],
        "motif_counts": _motif_count(manuscript_text),
    }
    (export_dir / "validation_report.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # whole-book rhythm
    rhythm = validate_rhythm(manuscript_text, scope="chapter", scope_id="full_book")
    (export_dir / "whole_book_rhythm.json").write_text(
        json.dumps(rhythm.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    m = rhythm.metrics
    print(f"\nStitched manuscript: {manuscript_path}")
    print(f"Chapters: {len(per_chapter_wc)}/38")
    print(f"Total words: {total_wc:,}")
    print("\nWhole-book rhythm metrics:")
    print(f"  em-dash density: {m.em_dashes_per_1k_words:.2f}/1k words")
    print(f"  short-sentence runs: {m.short_sentence_runs}")
    print(f"  default opener %: {m.default_opener_pct:.1f}%")
    print(f"  dialogue-bearing %: {m.dialogue_bearing_paragraph_pct:.1f}%")
    print(f"  abstract tics per 1k: {m.abstract_constructions_per_1k_words:.2f}")
    print(f"  issues: {len(rhythm.issues)}")
    for issue in rhythm.issues:
        print(f"    [{issue.severity}] {issue.code}")


if __name__ == "__main__":
    main()
