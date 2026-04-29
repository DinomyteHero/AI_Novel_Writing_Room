#!/usr/bin/env python3
"""Migrate a project from flat data/projects/ layout to franchise/book/run layout.

Usage:
    python scripts/migrations/migrate_to_franchise_layout.py \\
        --project the-ruusan-atonement \\
        --franchise star-wars-legends-eu

This script:
1. Copies inputs (concept_seed, scene_cards) to data/franchises/<franchise>/books/<project>/
2. Moves state (story_state.db, run_ledger.db, chapter_memory) to output/<franchise>/<project>/state/
3. Wraps existing output chapters in a 'legacy' run directory
4. Does NOT delete the old directories (safe, idempotent)
"""

import argparse
import shutil
from pathlib import Path


def migrate(project_slug: str, franchise_slug: str, base_dir: str = ".") -> None:
    base = Path(base_dir)
    old_project = base / "data" / "projects" / project_slug
    new_book = base / "data" / "franchises" / franchise_slug / "books" / project_slug
    new_state = base / "output" / franchise_slug / project_slug / "state"
    new_legacy_run = base / "output" / franchise_slug / project_slug / "runs" / "legacy"
    old_output = base / "output" / project_slug

    if not old_project.exists():
        print(f"Source project not found: {old_project}")
        return

    # Step 1: Copy inputs to franchise structure
    if not new_book.exists():
        new_book.mkdir(parents=True, exist_ok=True)
        for item in ("concept_seed.json", "scene_cards"):
            src = old_project / item
            dst = new_book / item
            if src.exists() and not dst.exists():
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                print(f"  Copied: {src} -> {dst}")
    else:
        print(f"  Book directory already exists: {new_book}")

    # Step 2: Move state to output
    old_state = old_project / "state"
    if old_state.exists():
        new_state.mkdir(parents=True, exist_ok=True)
        for item in old_state.iterdir():
            dst = new_state / item.name
            if not dst.exists():
                if item.is_dir():
                    shutil.copytree(item, dst)
                else:
                    shutil.copy2(item, dst)
                print(f"  State: {item} -> {dst}")
    else:
        print(f"  No state directory found at: {old_state}")

    # Step 3: Wrap existing output in legacy run
    old_chapters = old_output / "chapters"
    if old_chapters.exists():
        new_legacy_chapters = new_legacy_run / "chapters"
        if not new_legacy_chapters.exists():
            new_legacy_chapters.mkdir(parents=True, exist_ok=True)
            for item in old_chapters.iterdir():
                dst = new_legacy_chapters / item.name
                if not dst.exists():
                    shutil.copy2(item, dst)
            print(f"  Legacy run: {old_chapters} -> {new_legacy_chapters}")
    else:
        print(f"  No existing output chapters at: {old_chapters}")

    print(f"\nMigration complete for {project_slug} -> {franchise_slug}")
    print(f"  Inputs: {new_book}")
    print(f"  State:  {new_state}")
    print(f"  Legacy: {new_legacy_run}")
    print(f"\nOld directories were NOT deleted. Remove manually when satisfied:")
    print(f"  rm -rf {old_project}")
    print(f"  rm -rf {old_output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate project to franchise layout")
    parser.add_argument("--project", required=True, help="Project slug")
    parser.add_argument("--franchise", required=True, help="Franchise slug")
    parser.add_argument("--base-dir", default=".", help="Base directory")
    args = parser.parse_args()
    migrate(args.project, args.franchise, args.base_dir)
