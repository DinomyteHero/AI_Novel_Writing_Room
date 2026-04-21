"""Tests for src/pipeline/phase0_capture.py — the live-run prompt snapshot."""

from pathlib import Path

import pytest

from src.pipeline.phase0_capture import Phase0PromptSnapshot, STAGE_ORDER


def test_start_scene_creates_nested_directory(tmp_path):
    snap = Phase0PromptSnapshot(run_dir=tmp_path)
    scene_dir = snap.start_scene(chapter=3, scene=7)
    assert scene_dir == tmp_path / "phase0_debug" / "ch03_sc07"
    assert scene_dir.exists() and scene_dir.is_dir()


def test_dump_before_start_scene_is_no_op(tmp_path):
    snap = Phase0PromptSnapshot(run_dir=tmp_path)
    snap.dump("prose_stylist", [{"role": "user", "content": "hello"}])
    # Nothing should have been written anywhere under phase0_debug/.
    for _ in (tmp_path / "phase0_debug").rglob("*.txt"):
        pytest.fail("dump() should be a no-op when start_scene has not been called")


def test_dump_writes_user_and_system_files(tmp_path):
    snap = Phase0PromptSnapshot(run_dir=tmp_path)
    snap.start_scene(chapter=1, scene=1)
    snap.dump(
        "prose_stylist",
        [
            {"role": "system", "content": "You are the prose stylist."},
            {"role": "user", "content": "## Scene Objective\nDo the thing."},
        ],
    )
    scene_dir = tmp_path / "phase0_debug" / "ch01_sc01"
    prompt = scene_dir / "02_prose_stylist_prompt.txt"
    system = scene_dir / "02_prose_stylist_system.txt"
    assert prompt.exists()
    assert system.exists()
    assert "Scene Objective" in prompt.read_text(encoding="utf-8")
    assert "prose stylist" in system.read_text(encoding="utf-8")


def test_dump_uses_stage_order_for_filename_prefix(tmp_path):
    snap = Phase0PromptSnapshot(run_dir=tmp_path)
    snap.start_scene(chapter=1, scene=1)
    for role in ("plot_architect", "gate_critic", "canon_expert"):
        snap.dump(role, [{"role": "user", "content": f"from {role}"}])
    scene_dir = tmp_path / "phase0_debug" / "ch01_sc01"
    names = sorted(p.name for p in scene_dir.glob("*_prompt.txt"))
    assert names == [
        "01_plot_architect_prompt.txt",
        "04_gate_critic_prompt.txt",
        "07_canon_expert_prompt.txt",
    ]


def test_dump_unknown_role_uses_fallback_prefix(tmp_path):
    snap = Phase0PromptSnapshot(run_dir=tmp_path)
    snap.start_scene(chapter=1, scene=1)
    snap.dump("mystery_agent", [{"role": "user", "content": "???"}])
    files = list((tmp_path / "phase0_debug" / "ch01_sc01").glob("*_prompt.txt"))
    assert len(files) == 1
    assert files[0].name.startswith("99_")


def test_multiple_scenes_isolated(tmp_path):
    snap = Phase0PromptSnapshot(run_dir=tmp_path)
    snap.start_scene(chapter=1, scene=1)
    snap.dump("prose_stylist", [{"role": "user", "content": "scene 1"}])
    snap.start_scene(chapter=1, scene=2)
    snap.dump("prose_stylist", [{"role": "user", "content": "scene 2"}])
    s1 = (tmp_path / "phase0_debug" / "ch01_sc01" / "02_prose_stylist_prompt.txt")
    s2 = (tmp_path / "phase0_debug" / "ch01_sc02" / "02_prose_stylist_prompt.txt")
    assert s1.read_text(encoding="utf-8") == "scene 1"
    assert s2.read_text(encoding="utf-8") == "scene 2"


def test_write_scene_artifact(tmp_path):
    snap = Phase0PromptSnapshot(run_dir=tmp_path)
    snap.start_scene(chapter=1, scene=1)
    snap.write_scene_artifact("brief.json", '{"scene_objective": "X"}')
    artifact = tmp_path / "phase0_debug" / "ch01_sc01" / "brief.json"
    assert artifact.exists()
    assert '"scene_objective"' in artifact.read_text(encoding="utf-8")


def test_base_agent_dumps_messages_when_snapshot_attached(tmp_path):
    """BaseAgent.run() and run_structured() both route through the snapshot."""
    import asyncio
    from src.agents.base_agent import BaseAgent

    class _FakeRouter:
        async def complete(self, role, messages):
            return "response"

        async def complete_structured(self, role, messages):
            return {"result": "ok"}

    class _StubAgent(BaseAgent):
        def _format_context(self, context):
            return context.get("body", "")

        def _parse_response(self, response, context):
            return {"response": response}

    snap = Phase0PromptSnapshot(run_dir=tmp_path)
    snap.start_scene(chapter=2, scene=4)

    agent = _StubAgent(_FakeRouter(), "prose_stylist")
    agent.attach_phase0_snapshot(snap)

    asyncio.run(agent.run({"body": "hello world"}))
    asyncio.run(agent.run_structured({"body": "second call"}))

    prompt_path = (
        tmp_path / "phase0_debug" / "ch02_sc04" / "02_prose_stylist_prompt.txt"
    )
    # run_structured overwrites the first dump, which is fine — both calls
    # share the same stage index for this role.
    assert prompt_path.exists()
    assert "second call" in prompt_path.read_text(encoding="utf-8")


def test_dump_fires_for_agents_that_override_run(tmp_path):
    """Regression guard: ~9 real agents (gate_critic, plot_architect, final_gate,
    line_writer, canon_expert, summarizer, character_specialist, chapter_gate_critic,
    presence_checker) override BaseAgent.run() with their own flow. The dump
    must fire via _build_messages() — the one choke point they all go through —
    not via run()/run_structured(). An earlier version of this file hooked at
    the run() level and silently dropped 5 of 7 pipeline stages.
    """
    import asyncio
    from src.agents.base_agent import BaseAgent

    class _FakeRouter:
        async def complete_structured(self, role, messages):
            return {"result": "ok"}

    class _GateCriticLike(BaseAgent):
        """Mirror the gate_critic pattern: override run() to go straight to
        router.complete_structured, bypassing the inherited run()."""

        def _format_context(self, context):
            return "gate critic body"

        def _parse_response(self, response, context):
            return {}

        async def run(self, context):
            messages = self._build_messages(context)
            result = await self.router.complete_structured(self.role, messages)
            return {"result": result}

    snap = Phase0PromptSnapshot(run_dir=tmp_path)
    snap.start_scene(chapter=1, scene=1)

    agent = _GateCriticLike(_FakeRouter(), "gate_critic")
    agent.attach_phase0_snapshot(snap)

    asyncio.run(agent.run({}))

    prompt_path = tmp_path / "phase0_debug" / "ch01_sc01" / "04_gate_critic_prompt.txt"
    assert prompt_path.exists(), (
        "An agent that overrides run() must still dump via _build_messages(); "
        "otherwise stages like gate_critic, final_gate, plot_architect, etc. "
        "would be silently missing from phase0_debug/."
    )
    assert "gate critic body" in prompt_path.read_text(encoding="utf-8")


def test_stage_order_covers_core_agents():
    # Regression guard: if the pipeline adds a new core agent, the
    # dump filename would fall back to 99_ — surface that the map
    # needs to be extended.
    for role in (
        "plot_architect", "prose_stylist", "line_writer", "gate_critic",
        "quality_polish", "final_gate", "canon_expert",
    ):
        assert role in STAGE_ORDER, (
            f"{role} not in STAGE_ORDER — add a stage index to "
            "src/pipeline/phase0_capture.py"
        )
