"""Project-scoped path resolver with franchise, series, and run scoping.

Directory hierarchy:
    data/franchises/<franchise>/              # Franchise-level shared resources
        canon_db/                             # ChromaDB canon/lore (shared)
        worldbuilding.db                      # SQLite worldbuilding (shared)
        worldbuilding_vectors/                # ChromaDB lore embeddings (shared)
        books/
            <book>/                           # Book-level inputs
                concept_seed.json
                scene_cards/

    output/<franchise>/<book>/                # Book-level output
        state/                                # Accumulated state (or series-level)
            story_state.db
            chapter_memory/
            run_ledger.db
        runs/
            <run_id>/                         # Per-run isolation
                chapters/
                config_snapshot.yaml
                session.json
        export/

    output/<franchise>/<series>/state/        # Series-level shared state
        story_state.db                        # (when series_slug is set)
        chapter_memory/
        run_ledger.db

Backward compatibility:
    Projects at ``data/projects/<slug>/`` without a franchise parent
    continue to work.  The franchise_slug is optional.
"""

import json
import re
from datetime import datetime
from pathlib import Path


def slugify_title(title: str) -> str:
    """Convert a project title to a kebab-case directory slug.

    'The Ruusan Atonement' -> 'the-ruusan-atonement'
    """
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s_-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def _slugify_franchise(franchise: str) -> str:
    """Convert a franchise name to a kebab-case slug.

    'Star Wars (Legends EU)' -> 'star-wars-legends-eu'
    """
    slug = franchise.lower().strip()
    slug = re.sub(r"[^a-z0-9\s_-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def generate_run_id() -> str:
    """Generate a timestamped run ID."""
    return datetime.now().strftime("%Y-%m-%dT%H-%M")


class ProjectPaths:
    """Resolves all file paths for a given project.

    Usage:
        # Flat (backward-compat):
        paths = ProjectPaths("the-ruusan-atonement")

        # Franchise-scoped:
        paths = ProjectPaths("the-ruusan-atonement",
                             franchise_slug="star-wars-legends")

        # With series linkage (shared state):
        paths = ProjectPaths("the-ruusan-atonement",
                             franchise_slug="star-wars-legends",
                             series_slug="ruusan-verse")

        # With run isolation:
        paths = ProjectPaths("the-ruusan-atonement",
                             franchise_slug="star-wars-legends",
                             run_id="2026-04-12T14-30")

        # Auto-detect from concept seed:
        paths = ProjectPaths.from_concept_seed(concept_seed)
    """

    def __init__(
        self,
        project_slug: str,
        base_dir: str = ".",
        franchise_slug: str | None = None,
        series_slug: str | None = None,
        cosmology_slug: str | None = None,
        run_id: str | None = None,
    ):
        self.project_slug = project_slug
        self.franchise_slug = franchise_slug
        self.series_slug = series_slug
        self.cosmology_slug = cosmology_slug
        self.run_id = run_id
        self.base = Path(base_dir)

    # Backward-compat alias
    @property
    def universe_slug(self) -> str | None:
        return self.franchise_slug

    @classmethod
    def from_concept_seed(
        cls,
        concept_seed: dict,
        base_dir: str = ".",
        run_id: str | None = None,
    ) -> "ProjectPaths":
        """Create ProjectPaths from a concept seed's meta fields.

        Derives franchise_slug from meta.franchise (slugified).
        Derives series_slug from meta.series_id (slugified) if present.
        Derives cosmology_slug from meta.cosmology_id (slugified) if present.
        """
        meta = concept_seed.get("meta", {})
        title = meta.get("project_title", "untitled")
        franchise = meta.get("franchise", "")
        franchise_slug = _slugify_franchise(franchise) if franchise else None
        # series_id can be at meta.series_id or meta.series.series_id
        series_id = meta.get("series_id", "")
        if not series_id:
            series_id = meta.get("series", {}).get("series_id", "")
        series_slug = slugify_title(series_id) if series_id else None
        cosmology_id = meta.get("cosmology_id", "")
        cosmology_slug = slugify_title(cosmology_id) if cosmology_id else None
        return cls(
            slugify_title(title),
            base_dir,
            franchise_slug=franchise_slug,
            series_slug=series_slug,
            cosmology_slug=cosmology_slug,
            run_id=run_id,
        )

    @classmethod
    def from_concept_seed_path(
        cls, path: str, base_dir: str = ".", run_id: str | None = None,
    ) -> "ProjectPaths":
        """Infer project slug from the concept seed file's parent directory.

        Supports:
        - New: data/franchises/<franchise>/books/<slug>/concept_seed.json
        - Old: data/projects/<universe>/<slug>/concept_seed.json
        - Flat: data/projects/<slug>/concept_seed.json
        """
        p = Path(path)

        # New franchise structure: data/franchises/<franchise>/books/<slug>/concept_seed.json
        if (
            p.parent.parent.name == "books"
            and p.parent.parent.parent.parent.name == "franchises"
        ):
            franchise_slug = p.parent.parent.parent.name
            project_slug = p.parent.name
            # Read series_id and cosmology_id from the seed if present
            series_slug = None
            cosmology_slug = None
            try:
                with open(path, encoding="utf-8") as f:
                    seed = json.load(f)
                series_id = seed.get("meta", {}).get("series_id", "")
                series_slug = slugify_title(series_id) if series_id else None
                cosmology_id = seed.get("meta", {}).get("cosmology_id", "")
                cosmology_slug = slugify_title(cosmology_id) if cosmology_id else None
            except (json.JSONDecodeError, FileNotFoundError):
                pass
            return cls(
                project_slug, base_dir,
                franchise_slug=franchise_slug,
                series_slug=series_slug,
                cosmology_slug=cosmology_slug,
                run_id=run_id,
            )

        # Old universe-scoped: data/projects/<universe>/<slug>/concept_seed.json
        if (
            p.parent.parent.parent.name == "projects"
            and p.parent.parent.parent.parent.name == "data"
        ):
            return cls(
                p.parent.name, base_dir,
                franchise_slug=p.parent.parent.name,
                run_id=run_id,
            )

        # Flat: data/projects/<slug>/concept_seed.json
        if p.parent.parent.name == "projects":
            try:
                with open(path, encoding="utf-8") as f:
                    seed = json.load(f)
                franchise = seed.get("meta", {}).get("franchise", "")
                franchise_slug = _slugify_franchise(franchise) if franchise else None
                series_id = seed.get("meta", {}).get("series_id", "")
                series_slug = slugify_title(series_id) if series_id else None
                cosmology_id = seed.get("meta", {}).get("cosmology_id", "")
                cosmology_slug = slugify_title(cosmology_id) if cosmology_id else None
            except (json.JSONDecodeError, FileNotFoundError, KeyError):
                franchise_slug = None
                series_slug = None
                cosmology_slug = None
            return cls(
                p.parent.name, base_dir,
                franchise_slug=franchise_slug,
                series_slug=series_slug,
                cosmology_slug=cosmology_slug,
                run_id=run_id,
            )

        # Fallback: read the file
        with open(path, encoding="utf-8") as f:
            seed = json.load(f)
        return cls.from_concept_seed(seed, base_dir, run_id=run_id)

    # --- Cosmology-level paths (optional meta-universe layer) ---

    @property
    def cosmology_dir(self) -> Path | None:
        """Optional top-level cosmology directory (shared meta-universe).

        Sibling of ``franchises/`` in the data layout, not a parent. Multiple
        franchises reference a cosmology by id via ``universe_meta.cosmology_id``
        and via ``concept_seed.meta.cosmology_id``; this directory hosts the
        cosmology_meta.json registry.

        Returns ``None`` when this project has no cosmology_slug, so callers
        can treat cosmology as lazy/optional.
        """
        if self.cosmology_slug:
            return self.base / "data" / "cosmologies" / self.cosmology_slug
        return None

    @property
    def cosmology_meta_path(self) -> Path | None:
        d = self.cosmology_dir
        return d / "cosmology_meta.json" if d else None

    # --- Franchise-level paths ---

    @property
    def franchise_dir(self) -> Path | None:
        """Top-level franchise directory (shared canon, worldbuilding)."""
        if self.franchise_slug:
            return self.base / "data" / "franchises" / self.franchise_slug
        return None

    # --- Book-level input paths ---

    @property
    def book_dir(self) -> Path:
        """Book directory containing concept seed and scene cards (inputs only)."""
        if self.franchise_slug:
            return self.base / "data" / "franchises" / self.franchise_slug / "books" / self.project_slug
        return self.base / "data" / "projects" / self.project_slug

    # Backward-compat alias
    @property
    def project_root(self) -> Path:
        return self.book_dir

    @property
    def concept_seed_path(self) -> Path:
        return self.book_dir / "concept_seed.json"

    @property
    def scene_cards_dir(self) -> Path:
        return self.book_dir / "scene_cards"

    # --- Output base paths ---

    @property
    def _output_base(self) -> Path:
        """Base output directory for this book."""
        if self.franchise_slug:
            return self.base / "output" / self.franchise_slug / self.project_slug
        return self.base / "output" / self.project_slug

    # --- State paths (book-level or series-level) ---

    @property
    def state_dir(self) -> Path:
        """Accumulated state directory.

        When series_slug is set, state is shared at the series level.
        Otherwise, state is per-book.
        """
        if self.series_slug and self.franchise_slug:
            return self.base / "output" / self.franchise_slug / self.series_slug / "state"
        return self._output_base / "state"

    @property
    def story_state_db(self) -> Path:
        return self.state_dir / "story_state.db"

    @property
    def chapter_memory_dir(self) -> Path:
        return self.state_dir / "chapter_memory"

    @property
    def run_ledger_db(self) -> Path:
        return self.state_dir / "run_ledger.db"

    # --- Run-level paths ---

    @property
    def run_dir(self) -> Path | None:
        """Per-run output directory (chapters, config snapshot, session)."""
        if self.run_id:
            return self._output_base / "runs" / self.run_id
        return None

    @property
    def manuscripts_dir(self) -> Path:
        """Generated chapter prose directory.

        If a run_id is set, chapters go into the run directory.
        Otherwise, falls back to book-level chapters directory.
        """
        if self.run_id:
            return self._output_base / "runs" / self.run_id / "chapters"
        return self._output_base / "chapters"

    @property
    def config_snapshot_path(self) -> Path | None:
        """Config snapshot for this run (fully resolved settings)."""
        run = self.run_dir
        return run / "config_snapshot.yaml" if run else None

    @property
    def sessions_dir(self) -> Path:
        """Session checkpoint directory.

        If run_id is set, session lives in the run directory.
        Otherwise, falls back to state directory.
        """
        if self.run_id:
            return self._output_base / "runs" / self.run_id
        return self.state_dir / "sessions"

    @property
    def export_dir(self) -> Path:
        return self._output_base / "export"

    # --- Franchise-scoped shared resources ---

    @property
    def canon_dbs_dir(self) -> Path:
        if self.franchise_slug:
            return self.base / "data" / "franchises" / self.franchise_slug / "canon_db"
        return self.base / "data" / "canon_dbs"

    @property
    def worldbuilding_db(self) -> Path:
        if self.franchise_slug:
            return self.base / "data" / "franchises" / self.franchise_slug / "worldbuilding.db"
        return self.base / "data" / "franchises" / "worldbuilding.db"

    @property
    def worldbuilding_vectors_dir(self) -> Path:
        if self.franchise_slug:
            return self.base / "data" / "franchises" / self.franchise_slug / "worldbuilding_vectors"
        return self.base / "data" / "franchises" / "worldbuilding_vectors"

    # Legacy aliases for universe-scoped properties
    @property
    def universe_root(self) -> Path | None:
        return self.franchise_dir

    @property
    def universe_meta_path(self) -> Path | None:
        d = self.franchise_dir
        return d / "franchise_meta.json" if d else None

    @property
    def universe_canon_db(self) -> Path | None:
        d = self.franchise_dir
        return d / "canon_db" if d else None

    @property
    def universe_worldbuilding_db(self) -> Path | None:
        d = self.franchise_dir
        return d / "worldbuilding.db" if d else None

    @property
    def universe_worldbuilding_vectors(self) -> Path | None:
        d = self.franchise_dir
        return d / "worldbuilding_vectors" if d else None

    # --- Shared paths ---

    @property
    def eval_corpus_dir(self) -> Path:
        return self.base / "data" / "eval_corpus"

    @property
    def display_name(self) -> str:
        """Human-readable project identifier for log lines."""
        parts = []
        if self.cosmology_slug:
            parts.append(f"({self.cosmology_slug})")
        if self.franchise_slug:
            parts.append(self.franchise_slug)
        if self.series_slug:
            parts.append(f"[{self.series_slug}]")
        parts.append(self.project_slug)
        if self.run_id:
            parts.append(f"@{self.run_id}")
        return "/".join(parts)

    # --- Directory management ---

    def ensure_dirs(self) -> None:
        """Create all project directories if they don't exist."""
        dirs = [
            self.state_dir,
            self.chapter_memory_dir,
            self.scene_cards_dir,
            self.manuscripts_dir,
            self.export_dir,
        ]
        if self.franchise_dir:
            dirs.append(self.franchise_dir)
            dirs.append(self.worldbuilding_db.parent)
            dirs.append(self.worldbuilding_vectors_dir)
        if self.cosmology_dir:
            dirs.append(self.cosmology_dir)
        if self.run_dir:
            dirs.append(self.run_dir)
        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)

    def ensure_franchise_meta(self, concept_seed: dict | None = None) -> None:
        """Create franchise_meta.json if it doesn't exist yet."""
        meta_path = self.universe_meta_path
        if meta_path is None or meta_path.exists():
            return
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "franchise_name": self.franchise_slug or "default",
            "franchise": self.franchise_slug or "unknown",
            "canon_status": "original",
            "notes": "",
        }
        if concept_seed:
            cs_meta = concept_seed.get("meta", {})
            meta["franchise"] = cs_meta.get("franchise", meta["franchise"])
            meta["canon_status"] = cs_meta.get("canon_status", meta["canon_status"])
            canon = concept_seed.get("canon_constraints", {})
            meta["notes"] = canon.get("continuity", "")
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    # Backward-compat alias
    def ensure_universe_meta(self, concept_seed: dict | None = None) -> None:
        return self.ensure_franchise_meta(concept_seed)

    def ensure_cosmology_meta(
        self,
        cosmology_name: str | None = None,
        description: str | None = None,
    ) -> None:
        """Create cosmology_meta.json if it doesn't exist yet.

        No-op when this project has no cosmology_slug. Consumed lazily —
        the presence of cosmology_meta.json does not change engine behaviour
        in Phase 2; it provides a registry file for cross-universe shared
        lore and rules.
        """
        meta_path = self.cosmology_meta_path
        if meta_path is None or meta_path.exists():
            return
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "cosmology_id": self.cosmology_slug,
            "cosmology_name": cosmology_name or self.cosmology_slug or "unnamed",
        }
        if description:
            meta["description"] = description
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
