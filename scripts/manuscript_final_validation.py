#!/usr/bin/env python3
"""Deterministic validation for a stitched manuscript before final export."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


CHAPTER_RE = re.compile(r"^# Chapter\s+(\d+)\b", re.MULTILINE)
SCENE_RE = re.compile(r"^## Scene\s+(\d{2})\.(\d{2})\b", re.MULTILINE)
WORD_RE = re.compile(r"\b[\w']+\b")

HARD_ARTIFACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("markdown_fence", re.compile(r"```")),
    ("ai_disclaimer", re.compile(r"\b(as an ai|i cannot assist|i can't assist|i am unable)\b", re.I)),
    ("chat_role_label", re.compile(r"^\s*(assistant|user|system)\s*:", re.I)),
    ("merge_conflict", re.compile(r"^\s*(<<<<<<<|=======|>>>>>>>)")),
    ("patch_marker", re.compile(r"^\s*(\*\*\* Begin Patch|\*\*\* End Patch)")),
)

META_LANGUAGE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("scene_did_not_tell", re.compile(r"\bthe scene did(?:n't| not) tell\b", re.I)),
    ("chapter_did_not_tell", re.compile(r"\bthe chapter did(?:n't| not) tell\b", re.I)),
    ("book_did_not_tell", re.compile(r"\bthe book did(?:n't| not) tell\b", re.I)),
    ("not_narrating", re.compile(r"\bnot narrating the thing to death\b", re.I)),
    ("chapter_reference", re.compile(r"\bChapter\s+\d+\b")),
    ("from_chapter", re.compile(r"\bfrom Chapter\s+\d+\b")),
    ("short_chapter_reference", re.compile(r"\bCh\d{1,2}\b")),
    ("scene_before", re.compile(r"\bscene before\b", re.I)),
    ("previous_scene", re.compile(r"\bprevious scene\b", re.I)),
    ("whole_book", re.compile(r"\bwhole book\b", re.I)),
    ("twenty_chapters", re.compile(r"\btwenty chapters\b", re.I)),
    (
        "process_terms",
        re.compile(
            r"\b(the manuscript|this manuscript|scene card|the prompt|this prompt|"
            r"revision pass|targeted cleanup|literary polish)\b",
            re.I,
        ),
    ),
)

MOTIF_TERMS: tuple[str, ...] = (
    "wound",
    "wounded",
    "seal",
    "sealed",
    "chord",
    "note",
    "silence",
    "wrongness",
    "hum",
    "hummed",
    "resonance",
    "resonant",
    "weight",
    "stillness",
)


def _line_hits(
    text: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    *,
    skip_headings: bool = False,
) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if skip_headings and stripped.startswith("#"):
            continue
        for pattern_id, pattern in patterns:
            if pattern.search(line):
                hits.append(
                    {
                        "id": pattern_id,
                        "line": line_no,
                        "excerpt": stripped[:220],
                    }
                )
    return hits


def _word_count(text: str) -> int:
    return len(text.split())


def validate_manuscript(
    manuscript_path: Path,
    *,
    expected_chapters: int | None = None,
    expected_scenes: int | None = None,
) -> dict[str, object]:
    text = manuscript_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    prose_text = "\n".join(line for line in lines if not line.lstrip().startswith("#"))

    chapter_matches = CHAPTER_RE.findall(text)
    scene_matches = SCENE_RE.findall(text)
    artifact_hits = _line_hits(text, HARD_ARTIFACT_PATTERNS)
    meta_hits = _line_hits(text, META_LANGUAGE_PATTERNS, skip_headings=True)

    motif_counter: Counter[str] = Counter()
    lowered_words = [word.lower() for word in WORD_RE.findall(prose_text)]
    for word in lowered_words:
        if word in MOTIF_TERMS:
            motif_counter[word] += 1

    count_failures: list[str] = []
    if expected_chapters is not None and len(chapter_matches) != expected_chapters:
        count_failures.append(
            f"expected {expected_chapters} chapters, found {len(chapter_matches)}"
        )
    if expected_scenes is not None and len(scene_matches) != expected_scenes:
        count_failures.append(
            f"expected {expected_scenes} scenes, found {len(scene_matches)}"
        )

    passed = not artifact_hits and not meta_hits and not count_failures
    return {
        "manuscript": str(manuscript_path),
        "passed": passed,
        "counts": {
            "chapters": len(chapter_matches),
            "scenes": len(scene_matches),
            "words_with_headings": _word_count(text),
            "words_prose_only": _word_count(prose_text),
        },
        "expected": {
            "chapters": expected_chapters,
            "scenes": expected_scenes,
        },
        "count_failures": count_failures,
        "artifact_hits": artifact_hits,
        "meta_hits": meta_hits,
        "motif_counts": dict(sorted(motif_counter.items())),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manuscript", required=True, help="Path to stitched manuscript.md.")
    parser.add_argument("--expected-chapters", type=int, default=None)
    parser.add_argument("--expected-scenes", type=int, default=None)
    parser.add_argument("--out", default=None, help="Optional path to write the JSON report.")
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0, even when validation finds blocking issues.",
    )
    args = parser.parse_args(argv)

    report = validate_manuscript(
        Path(args.manuscript),
        expected_chapters=args.expected_chapters,
        expected_scenes=args.expected_scenes,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(rendered + "\n", encoding="utf-8")

    status = "PASS" if report["passed"] else "FAIL"
    counts = report["counts"]
    print(
        f"[{status}] {Path(args.manuscript).name}: "
        f"{counts['chapters']} chapters, {counts['scenes']} scenes, "
        f"{counts['words_prose_only']:,} prose words"
    )
    if report["count_failures"]:
        for failure in report["count_failures"]:
            print(f"- COUNT: {failure}")
    for label, key in (("ARTIFACT", "artifact_hits"), ("META", "meta_hits")):
        for hit in report[key]:
            print(f"- {label} {hit['id']} line {hit['line']}: {hit['excerpt']}")

    if not args.no_fail and not report["passed"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
