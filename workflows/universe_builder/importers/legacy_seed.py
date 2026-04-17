"""Extract a universe-builder artifact from a legacy concept_seed.json.

A legacy seed carries the project meta block in-place; this importer
copies the meta fields the surface schema knows about and assembles a
matching universe_meta block from the same source. Optional companions
``franchise_meta.json`` (or the legacy ``universe_meta.json``) are merged
on top when present so existing notes/branch_point/commercial_intent
survive the import.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from workflows._shared.legacy_seed_loader import pick

# Top-level seed sections the universe-builder surface absorbs alongside
# meta + universe_meta. premise/conflict/theme/protagonist_arc_type are the
# Step-2/Step-3 concept-foundation content; stress_test_scores / quality_overrides
# / extended_metadata are project-level metadata produced by Step-10 and
# the workshop runner.
_TOP_LEVEL_SECTIONS = (
    "premise",
    "conflict",
    "theme",
    "protagonist_arc_type",
    "stress_test_scores",
    "quality_overrides",
    "extended_metadata",
)

# meta fields the universe-builder surface owns (subset of concept_seed.meta).
_META_FIELDS = (
    "project_title",
    "franchise",
    "canon_status",
    "canon_status_description",
    "era",
    "tone",
    "tone_description",
    "target_word_count",
    "target_chapters",
    "pov_structure",
    "project_scope",
    "series",
    "book_number",
    "series_id",
    "cosmology_id",
)


def import_from_seed(
    seed: dict,
    *,
    franchise_meta_path: str | Path | None = None,
) -> dict:
    """Return a universe-builder artifact dict extracted from ``seed``.

    When ``franchise_meta_path`` is supplied and the file exists, fields
    from that JSON are merged into ``universe_meta`` so existing notes,
    branch_point, and commercial_intent overrides are preserved.
    """
    seed_meta = seed.get("meta", {}) or {}
    meta: dict = {}
    for field in _META_FIELDS:
        if field in seed_meta and seed_meta[field] not in (None, ""):
            meta[field] = copy.deepcopy(seed_meta[field])

    universe_meta: dict = {
        "universe_name": meta.get("franchise", ""),
        "franchise": meta.get("franchise", ""),
    }
    if "canon_status" in meta:
        universe_meta["canon_status"] = meta["canon_status"]
    if "cosmology_id" in meta:
        universe_meta["cosmology_id"] = meta["cosmology_id"]

    if franchise_meta_path is not None:
        fmp = Path(franchise_meta_path)
        if fmp.exists():
            existing = json.loads(fmp.read_text(encoding="utf-8"))
            for key, value in existing.items():
                # Don't let the existing file override the seed-derived
                # universe_name/franchise — those are load-bearing.
                if key in ("universe_name", "franchise"):
                    if not universe_meta.get(key):
                        universe_meta[key] = value
                else:
                    universe_meta[key] = value

    artifact: dict = {
        "surface": "universe-builder",
        "schema_version": "1.0",
        "meta": meta,
        "universe_meta": universe_meta,
    }
    for section in _TOP_LEVEL_SECTIONS:
        value = pick(seed, section)
        if value is not None:
            artifact[section] = value
    return artifact
