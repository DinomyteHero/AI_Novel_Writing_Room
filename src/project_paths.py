"""Project-scoped path resolver.

All per-project file paths are derived from a single project slug.
This replaces hardcoded paths scattered across the codebase.
"""

import re
from pathlib import Path


def slugify_title(title: str) -> str:
    """Convert a project title to a kebab-case directory slug.

    Matches the existing _slugify_title logic in main.py.
    'The Ruusan Atonement' -> 'the-ruusan-atonement'
    """
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9\s_-]", "", slug)  # keep underscores temporarily
    slug = re.sub(r"[\s_]+", "-", slug)  # convert spaces and underscores to dashes
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


class ProjectPaths:
    """Resolves all file paths for a given project.

    Usage:
        paths = ProjectPaths("the-ruusan-atonement")
        # or
        paths = ProjectPaths.from_concept_seed(concept_seed)

        state = StoryState(db_path=str(paths.story_state_db))
        chapter_memory = ChapterMemory(persist_directory=str(paths.chapter_memory_dir))
    """

    def __init__(self, project_slug: str, base_dir: str = "."):
        self.project_slug = project_slug
        self.base = Path(base_dir)

    @classmethod
    def from_concept_seed(cls, concept_seed: dict, base_dir: str = ".") -> "ProjectPaths":
        """Create ProjectPaths from a concept seed's meta.project_title."""
        title = concept_seed.get("meta", {}).get("project_title", "untitled")
        return cls(slugify_title(title), base_dir)

    @classmethod
    def from_concept_seed_path(cls, path: str, base_dir: str = ".") -> "ProjectPaths":
        """Infer project slug from the concept seed file's parent directory.

        If the path is data/projects/<slug>/concept_seed.json, use <slug>.
        Otherwise fall back to loading the JSON and reading project_title.
        """
        p = Path(path)
        # Check if already in new project structure
        if p.parent.parent.name == "projects":
            return cls(p.parent.name, base_dir)
        # Fallback: read the file
        import json
        with open(path, encoding="utf-8") as f:
            seed = json.load(f)
        return cls.from_concept_seed(seed, base_dir)

    # --- Per-project state paths (under data/projects/<slug>/) ---

    @property
    def project_root(self) -> Path:
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
        return self.base / "output" / self.project_slug / "chapters"

    @property
    def export_dir(self) -> Path:
        return self.base / "output" / self.project_slug / "export"

    # --- Shared paths (not project-scoped) ---

    @property
    def worldbuilding_db(self) -> Path:
        return self.base / "data" / "universes" / "worldbuilding.db"

    @property
    def worldbuilding_vectors_dir(self) -> Path:
        return self.base / "data" / "universes" / "worldbuilding_vectors"

    @property
    def canon_dbs_dir(self) -> Path:
        return self.base / "data" / "canon_dbs"

    @property
    def eval_corpus_dir(self) -> Path:
        return self.base / "data" / "eval_corpus"

    def ensure_dirs(self) -> None:
        """Create all project directories if they don't exist."""
        for dir_path in [
            self.story_state_db.parent,
            self.chapter_memory_dir,
            self.sessions_dir,
            self.scene_cards_dir,
            self.manuscripts_dir,
            self.export_dir,
            self.worldbuilding_db.parent,
            self.worldbuilding_vectors_dir,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)
