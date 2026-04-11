#!/usr/bin/env python3
"""Migrate flat data/ layout to project-scoped data/projects/<slug>/ layout.

This script moves per-project state files from the old flat layout into the
new project-scoped directory structure. Shared resources (eval_corpus,
canon_dbs) are left in place.

Usage:
    python scripts/migrate_to_project_dirs.py [--dry-run]
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.project_paths import ProjectPaths, slugify_title


def discover_projects(data_dir: Path) -> list[dict]:
    """Scan data/story_bibles/ for existing project directories."""
    story_bibles = data_dir / "story_bibles"
    if not story_bibles.exists():
        return []

    projects = []
    for proj_dir in sorted(story_bibles.iterdir()):
        if not proj_dir.is_dir():
            continue
        seed_path = proj_dir / "concept_seed.json"
        if seed_path.exists():
            with open(seed_path, encoding="utf-8") as f:
                seed = json.load(f)
            title = seed.get("meta", {}).get("project_title", proj_dir.name)
            projects.append({
                "dir_name": proj_dir.name,
                "title": title,
                "slug": slugify_title(title),
                "source_dir": proj_dir,
                "seed_path": seed_path,
            })
    return projects


def migrate_project(project: dict, data_dir: Path, dry_run: bool) -> list[str]:
    """Migrate a single project's files. Returns list of actions taken."""
    slug = project["slug"]
    paths = ProjectPaths(slug)
    actions = []

    # 1. Create target directory structure
    if not dry_run:
        paths.ensure_dirs()
    actions.append(f"  mkdir data/projects/{slug}/")

    # 2. Copy concept_seed.json
    src = project["seed_path"]
    dst = paths.project_root / "concept_seed.json"
    if src.exists() and not dst.exists():
        if not dry_run:
            shutil.copy2(src, dst)
        actions.append(f"  copy {src} -> {dst}")

    # 3. Copy scene_cards/
    src_cards = project["source_dir"] / "scene_cards"
    dst_cards = paths.scene_cards_dir
    dst_empty = not dst_cards.exists() or not any(dst_cards.iterdir())
    if src_cards.exists() and dst_empty:
        if not dry_run:
            if dst_cards.exists():
                shutil.rmtree(dst_cards)
            shutil.copytree(src_cards, dst_cards)
        actions.append(f"  copy {src_cards}/ -> {dst_cards}/")

    # 4. Copy series_seed.json if exists
    series_src = project["source_dir"] / "series_seed.json"
    series_dst = paths.project_root / "series_seed.json"
    if series_src.exists() and not series_dst.exists():
        if not dry_run:
            shutil.copy2(series_src, series_dst)
        actions.append(f"  copy {series_src} -> {series_dst}")

    return actions


def migrate_flat_state(data_dir: Path, slug: str, dry_run: bool) -> list[str]:
    """Migrate flat state files (story_state.db, chapter_memory, etc.) to a project."""
    paths = ProjectPaths(slug)
    actions = []

    flat_files = [
        (data_dir / "story_state.db", paths.story_state_db),
        (data_dir / "run_ledger.db", paths.run_ledger_db),
    ]
    for src, dst in flat_files:
        if src.exists() and not dst.exists():
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            actions.append(f"  copy {src} -> {dst}")

    flat_dirs = [
        (data_dir / "chapter_memory", paths.chapter_memory_dir),
        (data_dir / "sessions", paths.sessions_dir),
    ]
    for src, dst in flat_dirs:
        dst_empty = not dst.exists() or not any(dst.iterdir())
        if src.exists() and dst_empty:
            if not dry_run:
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            actions.append(f"  copy {src}/ -> {dst}/")

    return actions


def migrate_worldbuilding(data_dir: Path, dry_run: bool) -> list[str]:
    """Move worldbuilding files to data/universes/."""
    actions = []
    universes_dir = data_dir / "universes"

    src_db = data_dir / "worldbuilding.db"
    dst_db = universes_dir / "worldbuilding.db"
    if src_db.exists() and not dst_db.exists():
        if not dry_run:
            universes_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_db, dst_db)
        actions.append(f"  copy {src_db} -> {dst_db}")

    src_vectors = data_dir / "worldbuilding_vectors"
    dst_vectors = universes_dir / "worldbuilding_vectors"
    if src_vectors.exists() and not dst_vectors.exists():
        if not dry_run:
            universes_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(src_vectors, dst_vectors)
        actions.append(f"  copy {src_vectors}/ -> {dst_vectors}/")

    return actions


def main():
    parser = argparse.ArgumentParser(description="Migrate to project-scoped data layout")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without moving files")
    parser.add_argument("--data-dir", default="data", help="Path to data directory (default: data)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        print(f"Error: data directory not found: {data_dir}")
        sys.exit(1)

    if args.dry_run:
        print("=== DRY RUN (no files will be moved) ===\n")

    # Discover projects
    projects = discover_projects(data_dir)
    if not projects:
        print("No projects found in data/story_bibles/")
        print("Nothing to migrate.")
        return

    print(f"Found {len(projects)} project(s):\n")
    for p in projects:
        print(f"  {p['title']} -> data/projects/{p['slug']}/")

    # Migrate each project
    all_actions = []
    for p in projects:
        print(f"\nMigrating: {p['title']}")
        actions = migrate_project(p, data_dir, args.dry_run)
        all_actions.extend(actions)
        for a in actions:
            print(a)

    # Migrate flat state files (assign to first/only project if single-project)
    if len(projects) == 1:
        slug = projects[0]["slug"]
        print(f"\nMigrating flat state files to {slug}:")
        actions = migrate_flat_state(data_dir, slug, args.dry_run)
        all_actions.extend(actions)
        for a in actions:
            print(a)
        if not actions:
            print("  (no flat state files to migrate)")
    elif len(projects) > 1:
        flat_state = [
            data_dir / "story_state.db",
            data_dir / "chapter_memory",
            data_dir / "run_ledger.db",
            data_dir / "sessions",
        ]
        has_flat = [f for f in flat_state if f.exists()]
        if has_flat:
            print("\nWARNING: Multiple projects found with flat state files.")
            print("Cannot auto-assign these files to a project:")
            for f in has_flat:
                print(f"  {f}")
            print("Please move them manually to the appropriate data/projects/<slug>/state/ dir.")

    # Migrate worldbuilding
    print("\nMigrating worldbuilding files:")
    actions = migrate_worldbuilding(data_dir, args.dry_run)
    all_actions.extend(actions)
    for a in actions:
        print(a)
    if not actions:
        print("  (no worldbuilding files to migrate)")

    # Summary
    print(f"\n{'='*50}")
    if args.dry_run:
        print(f"DRY RUN: {len(all_actions)} action(s) would be taken.")
        print("Run without --dry-run to execute.")
    else:
        print(f"Migration complete: {len(all_actions)} action(s) taken.")
        print("\nOriginal files are preserved. Once you verify the new layout works,")
        print("you can remove the old files manually:")
        print("  - data/story_bibles/ (concept seeds and scene cards)")
        print("  - data/story_state.db, data/run_ledger.db")
        print("  - data/chapter_memory/, data/sessions/")
        print("  - data/worldbuilding.db, data/worldbuilding_vectors/")


if __name__ == "__main__":
    main()
