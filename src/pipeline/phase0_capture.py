"""Per-stage prompt capture for Phase 0 audit (architecture upgrade Slice 1).

When ``runtime.phase0_audit.enabled: true``, the orchestrator constructs one
:class:`Phase0PromptSnapshot` instance for the run and attaches it to every
agent. As each agent runs, it dumps its rendered user/system messages into
``<run_dir>/phase0_debug/ch<NN>_sc<MM>/<stage_index>_<role>_{prompt,system}.txt``.

The dump surface is read by ``scripts/audit_phase0.py`` in ``--run-dir`` mode
so the six-criterion gate can be evaluated against *live* prompts instead of
the statically-rendered dry-run prompts. Dry-run remains the default because
it runs offline, but live capture is the authoritative check when a book's
pipeline path diverges from the default flow (e.g., Phase 2 + lore service
attached, which affects what actually reaches the drafter).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# Numeric stage ordering matches ``docs/architecture/architecture_upgrade_spec.md``
# §5.1.1 filename conventions (``01_plot_architect_prompt.txt`` etc.).
STAGE_ORDER: dict[str, int] = {
    "plot_architect": 1,
    "prose_stylist": 2,
    "line_writer": 3,
    "gate_critic": 4,
    "quality_polish": 5,
    "final_gate": 6,
    "canon_expert": 7,
    "presence_checker": 8,
    "chapter_gate_critic": 9,
    "character_specialist": 10,
    "summarizer": 11,
}


class Phase0PromptSnapshot:
    """Writes rendered prompts to disk, one file per agent invocation."""

    def __init__(self, *, run_dir: Path) -> None:
        self.root = Path(run_dir) / "phase0_debug"
        self.root.mkdir(parents=True, exist_ok=True)
        self._scene_dir: Optional[Path] = None

    def start_scene(self, *, chapter: int, scene: int) -> Path:
        """Open a per-scene directory and return its path.

        Idempotent — repeated calls with the same (chapter, scene) reuse the
        directory so a scene's prompts accumulate as each stage runs.
        """
        self._scene_dir = self.root / f"ch{chapter:02d}_sc{scene:02d}"
        self._scene_dir.mkdir(parents=True, exist_ok=True)
        return self._scene_dir

    def dump(self, role: str, messages: list[dict]) -> None:
        """Write rendered messages for one agent invocation."""
        if self._scene_dir is None:
            return
        stage = STAGE_ORDER.get(role, 99)
        user_parts = [
            m.get("content", "") for m in messages if m.get("role") == "user"
        ]
        system_parts = [
            m.get("content", "") for m in messages if m.get("role") == "system"
        ]
        user_text = "\n\n---\n\n".join(user_parts)
        system_text = "\n\n---\n\n".join(system_parts)
        (self._scene_dir / f"{stage:02d}_{role}_prompt.txt").write_text(
            user_text, encoding="utf-8",
        )
        (self._scene_dir / f"{stage:02d}_{role}_system.txt").write_text(
            system_text, encoding="utf-8",
        )

    def write_scene_artifact(self, name: str, content: str) -> None:
        """Write an auxiliary per-scene artifact (brief.json, prose drafts)."""
        if self._scene_dir is None:
            return
        (self._scene_dir / name).write_text(content, encoding="utf-8")
