"""One-shot installer for the Ruusan Atonement concept seed.

DEPRECATED: for new projects, use ``scripts/install_seed.py`` directly
with your own ``workshop_patch.json``. This wrapper exists only for
backward compatibility with external automation that invokes the
Ruusan-specific script by name.

Delegates to ``scripts/install_seed.install_seed`` with the two committed
inputs:

    data/franchises/star-wars-legends-eu/books/the-ruusan-atonement/install/
        concept_seed_raw.json   — pre-enrichment raw workshop output
        workshop_patch.json     — Ruusan-specific enrichment data
                                  (voice_definition, arc_phase_maps,
                                  promise_payoff_ledger, canon_constraints,
                                  workshop_origin, extended_metadata_fields,
                                  structural_overrides, arc_type_map)

Run from the repo root:
    python scripts/install_ruusan_seed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.install_seed import install_seed  # noqa: E402

RUUSAN_INSTALL_DIR = (
    REPO_ROOT
    / "data"
    / "franchises"
    / "star-wars-legends-eu"
    / "books"
    / "the-ruusan-atonement"
    / "install"
)
RAW_SEED = RUUSAN_INSTALL_DIR / "concept_seed_raw.json"
WORKSHOP_PATCH = RUUSAN_INSTALL_DIR / "workshop_patch.json"


def main() -> int:
    if not RAW_SEED.exists():
        print(f"ERROR: raw Ruusan seed not found at {RAW_SEED}", file=sys.stderr)
        return 1
    if not WORKSHOP_PATCH.exists():
        print(
            f"ERROR: Ruusan workshop patch not found at {WORKSHOP_PATCH}",
            file=sys.stderr,
        )
        return 1

    print("NOTE: scripts/install_ruusan_seed.py is deprecated.")
    print("      New projects should use scripts/install_seed.py directly with")
    print("      their own workshop_patch.json. This wrapper remains as a")
    print("      backward-compatible entry point for the Ruusan reinstall path.\n")

    result = install_seed(
        input_path=RAW_SEED,
        workshop_patch_path=WORKSHOP_PATCH,
        base_dir=str(REPO_ROOT),
        # Scene card translator output is partial by design (empty
        # why_now / turning_point for post-enrichment). Skip per-card
        # schema validation so the installer's summary is not buried
        # in warnings.
        validate_scene_cards=False,
    )

    print(f"Wrote enriched seed to {result.seed_path}")
    print(f"Extracted {result.scene_card_count} scene card(s)")
    print(f"  characters: {result.character_count}")
    if result.warnings:
        print(f"  {len(result.warnings)} warning(s):")
        for w in result.warnings:
            print(f"    - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
