"""Forward migration helper: split a finalized concept_seed.json (and the
companion workshop_state.json, when present) into the six surface
artifacts the workflow kit consumes.

Use when you have a project that ran through the legacy
``src.concept_workshop.workshop_runner`` and want to roll it forward
into the workflow kit without re-authoring content. After this script
runs, ``scripts/compile_bundle.py`` should produce a bundle equivalent
to the legacy installer output.

Usage:
    python scripts/migrate_workshop.py --franchise <slug> --book <slug> [--base-dir .]

The script is idempotent: re-running on a project that already has
``workflows/*.json`` artifacts overwrites them with the values derived
from the current ``concept_seed.json`` + ``scene_cards/`` tree.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.project_paths import ProjectPaths  # noqa: E402
from workflows._shared.io import write_artifact  # noqa: E402
from workflows._shared.legacy_seed_loader import load_seed  # noqa: E402
from workflows.canon_drafter.importers.legacy_seed import (  # noqa: E402
    import_from_seed as cd_import,
)
from workflows.canon_drafter.validate import validate as v_cd  # noqa: E402
from workflows.character_forge.importers.legacy_seed import (  # noqa: E402
    import_from_seed as cf_import,
)
from workflows.character_forge.validate import validate as v_cf  # noqa: E402
from workflows.outline_planner.importers.legacy_seed import (  # noqa: E402
    import_from_seed as op_import,
)
from workflows.outline_planner.validate import validate as v_op  # noqa: E402
from workflows.scene_card_authoring.importers.legacy_seed import (  # noqa: E402
    import_from_seed as sca_import,
)
from workflows.scene_card_authoring.validate import validate as v_sca  # noqa: E402
from workflows.universe_builder.importers.legacy_seed import (  # noqa: E402
    import_from_seed as ub_import,
)
from workflows.universe_builder.validate import validate as v_ub  # noqa: E402
from workflows.voice_discovery.importers.legacy_seed import (  # noqa: E402
    import_from_seed as vd_import,
)
from workflows.voice_discovery.validate import validate as v_vd  # noqa: E402


def migrate(
    *,
    franchise_slug: str,
    book_slug: str,
    base_dir: str = ".",
) -> list[Path]:
    """Migrate a project's concept_seed.json into six surface artifacts.

    Returns the list of artifact paths written. Raises FileNotFoundError
    when the project's concept_seed.json is missing.
    """
    paths = ProjectPaths(book_slug, base_dir=base_dir, franchise_slug=franchise_slug)
    seed_path = paths.concept_seed_path
    if not seed_path.exists():
        raise FileNotFoundError(
            f"concept_seed.json not found at {seed_path}; nothing to migrate"
        )
    paths.workflows_dir.mkdir(parents=True, exist_ok=True)

    franchise_meta_path = (
        paths.universe_meta_path if paths.universe_meta_path else None
    )
    seed = load_seed(seed_path)
    sc_dir = paths.scene_cards_dir if paths.scene_cards_dir.exists() else None

    written: list[Path] = []
    written.append(write_artifact(
        paths.workflows_dir / "universe.json",
        ub_import(seed, franchise_meta_path=franchise_meta_path),
        surface="universe-builder", validator=v_ub,
    ))
    written.append(write_artifact(
        paths.workflows_dir / "canon.json",
        cd_import(seed),
        surface="canon-drafter", validator=v_cd,
    ))
    written.append(write_artifact(
        paths.workflows_dir / "voice.json",
        vd_import(seed),
        surface="voice-discovery", validator=v_vd,
    ))
    written.append(write_artifact(
        paths.workflows_dir / "characters.json",
        cf_import(seed),
        surface="character-forge", validator=v_cf,
    ))
    written.append(write_artifact(
        paths.workflows_dir / "outline.json",
        op_import(seed, extracted_scene_cards_dir=sc_dir),
        surface="outline-planner", validator=v_op,
    ))
    written.append(write_artifact(
        paths.workflows_dir / "scene_cards.json",
        sca_import(seed, extracted_scene_cards_dir=sc_dir),
        surface="scene-card-authoring", validator=v_sca,
    ))
    return written


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate a legacy concept_seed.json into the six workflow "
            "surface artifacts so scripts/compile_bundle.py can rebuild "
            "the canonical bundle."
        ),
    )
    parser.add_argument("--franchise", required=True, help="Franchise slug")
    parser.add_argument("--book", required=True, help="Book slug")
    parser.add_argument("--base-dir", default=".", help="Repository root")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        written = migrate(
            franchise_slug=args.franchise,
            book_slug=args.book,
            base_dir=args.base_dir,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Migrated {args.franchise}/{args.book} into {len(written)} surface artifacts:")
    for path in written:
        print(f"  {path}")
    print()
    print("Next step:")
    print(f"  python scripts/compile_bundle.py --franchise {args.franchise} --book {args.book}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
