"""Project-scoped path resolver with optional universe scoping.

All per-project file paths are derived from a project slug and an
optional universe slug.  When a universe slug is provided, project
data lives under ``data/projects/<universe>/<book>/`` and shared
universe resources (canon DB, worldbuilding) live under
``data/universes/<universe>/``.

Backward compatibility: projects at ``data/projects/<slug>/`` without
a universe parent continue to work.  The universe slug is optional.
"""

import json
import re
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


class ProjectPaths:
    """Resolves all file paths for a given project.

    Usage:
        # Flat (backward-compat):
        paths = ProjectPaths("the-ruusan-atonement")

        # Universe-scoped:
        paths = ProjectPaths("the-ruusan-atonement", universe_slug="star-wars-legends")

        # Auto-detect from concept seed:
        paths = ProjectPaths.from_concept_seed(concept_seed)
    """

    def __init__(
        self,
        project_slug: str,
        base_dir: str = ".",
        universe_slug: str | None = None,
    ):
        self.project_slug = project_slug
        self.universe_slug = universe_slug
        self.base = Path(base_dir)

    @classmethod
    def from_concept_seed(cls, concept_seed: dict, base_dir: str = ".") -> "ProjectPaths":
        """Create ProjectPaths from a concept seed's meta fields.

        Derives universe_slug from meta.franchise (slugified).
        """
        meta = concept_seed.get("meta", {})
        title = meta.get("project_title", "untitled")
        franchise = meta.get("franchise", "")
        universe_slug = _slugify_franchise(franchise) if franchise else None
        return cls(slugify_title(title), base_dir, universe_slug=universe_slug)

    @classmethod
    def from_concept_seed_path(cls, path: str, base_dir: str = ".") -> "ProjectPaths":
        """Infer project slug from the concept seed file's parent directory.

        Supports both flat (data/projects/<slug>/concept_seed.json) and
        universe-scoped (data/projects/<universe>/<slug>/concept_seed.json).
        """
        p = Path(path)
        # Check for universe-scoped structure: data/projects/<universe>/<slug>/concept_seed.json
        if (
            p.parent.parent.parent.name == "projects"
            and p.parent.parent.parent.parent.name == "data"
        ):
            return cls(
                p.parent.name,
                base_dir,
                universe_slug=p.parent.parent.name,
            )
        # Flat structure: data/projects/<slug>/concept_seed.json
        if p.parent.parent.name == "projects":
            # Try to read franchise from the seed to derive universe_slug
            try:
                with open(path, encoding="utf-8") as f:
                    seed = json.load(f)
                franchise = seed.get("meta", {}).get("franchise", "")
                universe_slug = _slugify_franchise(franchise) if franchise else None
            except (json.JSONDecodeError, FileNotFoundError, KeyError):
                universe_slug = None
            return cls(p.parent.name, base_dir, universe_slug=universe_slug)
        # Fallback: read the file
        with open(path, encoding="utf-8") as f:
            seed = json.load(f)
        return cls.from_concept_seed(seed, base_dir)

    # --- Per-project state paths ---

    @property
    def project_root(self) -> Path:
        if self.universe_slug:
            return self.base / "data" / "projects" / self.universe_slug / self.project_slug
        return self.base / "data" / "projects" / self.project_slug

    @property
    def story_state_db(self) -> Path:
        return self.project_root / "state" / "story_state.db"

    @property
    def chapter_memory_dir(self) -> Path:
        return self.project_root / "state" / "chapter_memory"

    @property
    def run_ledger_db(self) -> Path:
        return self.project_root / "state" / "run_ledger.db"

    @property
    def sessions_dir(self) -> Path:
        return self.project_root / "state" / "sessions"

    # --- Per-project content paths ---

    @property
    def concept_seed_path(self) -> Path:
        return self.project_root / "concept_seed.json"

    @property
    def scene_cards_dir(self) -> Path:
        return self.project_root / "scene_cards"

    @property
    def manuscripts_dir(self) -> Path:
        if self.universe_slug:
            return self.base / "output" / self.universe_slug / self.project_slug / "chapters"
        return self.base / "output" / self.project_slug / "chapters"

    @property
    def export_dir(self) -> Path:
        if self.universe_slug:
            return self.base / "output" / self.universe_slug / self.project_slug / "export"
        return self.base / "output" / self.project_slug / "export"

    # --- Universe-scoped paths ---

    @property
    def universe_root(self) -> Path | None:
        if self.universe_slug:
            return self.base / "data" / "universes" / self.universe_slug
        return None

    @property
    def universe_meta_path(self) -> Path | None:
        root = self.universe_root
        return root / "universe_meta.json" if root else None

    @property
    def universe_canon_db(self) -> Path | None:
        root = self.universe_root
        return root / "canon_db" if root else None

    @property
    def universe_worldbuilding_db(self) -> Path | None:
        root = self.universe_root
        return root / "worldbuilding.db" if root else None

    @property
    def universe_worldbuilding_vectors(self) -> Path | None:
        root = self.universe_root
        return root / "worldbuilding_vectors" if root else None

    # --- Shared paths (fallback when not universe-scoped) ---

    @property
    def worldbuilding_db(self) -> Path:
        if self.universe_slug:
            return self.base / "data" / "universes" / self.universe_slug / "worldbuilding.db"
        return self.base / "data" / "universes" / "worldbuilding.db"

    @property
    def worldbuilding_vectors_dir(self) -> Path:
        if self.universe_slug:
            return self.base / "data" / "universes" / self.universe_slug / "worldbuilding_vectors"
        return self.base / "data" / "universes" / "worldbuilding_vectors"

    @property
    def canon_dbs_dir(self) -> Path:
        if self.universe_slug:
            return self.base / "data" / "universes" / self.universe_slug / "canon_db"
        return self.base / "data" / "canon_dbs"

    @property
    def eval_corpus_dir(self) -> Path:
        return self.base / "data" / "eval_corpus"

    @property
    def display_name(self) -> str:
        """Human-readable project identifier for log lines."""
        if self.universe_slug:
            return f"{self.universe_slug}/{self.project_slug}"
        return self.project_slug

    def ensure_dirs(self) -> None:
        """Create all project directories if they don't exist."""
        dirs = [
            self.story_state_db.parent,
            self.chapter_memory_dir,
            self.sessions_dir,
            self.scene_cards_dir,
            self.manuscripts_dir,
            self.export_dir,
            self.worldbuilding_db.parent,
            self.worldbuilding_vectors_dir,
        ]
        if self.universe_root:
            dirs.append(self.universe_root)
        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)

    def ensure_universe_meta(self, concept_seed: dict | None = None) -> None:
        """Create universe_meta.json if it doesn't exist yet."""
        meta_path = self.universe_meta_path
        if meta_path is None or meta_path.exists():
            return
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "universe_name": self.universe_slug or "default",
            "franchise": self.universe_slug or "unknown",
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
