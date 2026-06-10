"""Tests for ProseStylist consuming a typed generation brief.

Phase 2 hard cutover: `generation_brief` is a dict matching
schemas/generation_brief.json (not a free-text blob). These tests verify that
the dict's typed fields surface as labeled markdown sections in the user
prompt, and that optional fields render only when present.
"""

from unittest.mock import AsyncMock, MagicMock

from src.agents.prose_stylist import (
    ProseStylist,
    _render_brief,
    _scene_voice_contract,
)


def _minimal_brief() -> dict:
    """Brief with only required fields populated."""
    return {
        "scene_objective": "Establish Alex's solitary style.",
        "turning_point": {
            "trigger": "Alex opens the sealed file.",
            "shift": "Case becomes personal.",
            "cost": "Alex chooses transgression.",
        },
        "closing_beat": "Locked drawer; unknown text arrives.",
        "emotional_arc": {
            "start": "boredom",
            "shift": "recognition",
            "end": "transgression",
        },
        "target_word_count": 1250,
    }


def _full_brief() -> dict:
    """Brief with every field populated."""
    brief = _minimal_brief()
    brief.update({
        "opening_mode": "sensory_hook",
        "key_beats": [
            {
                "beat_description": "Alex enters the office after hours",
                "state_change": "Solitude established",
                "pov_reaction": "Familiar comfort, edged with procedural fatigue",
            },
            {
                "beat_description": "Sealed file appears in the evidence tray",
                "state_change": "Curiosity overrides caution",
                "pov_reaction": "A name recognised — stomach tightens",
            },
        ],
        "voice_guidance": "Zahn efficient dialogue; clipped internal observations.",
        "delivery_preferences": {
            "reveal_mode": "gradual",
            "exposition_budget": "concise",
            "register_override": None,
        },
        "required_hooks": ["H01_alex_personal_tie", "H02_watcher"],
        "required_subplots": ["SP-A_case_kickoff"],
        "required_revelations": ["R01_sealed_file_matters"],
        "forbidden_moves": ["Do not introduce Jordan", "No supervisor dialogue"],
        "anti_patterns": ["Do not open with a flashback", "No exposition dump"],
    })
    return brief


def _make_context(brief: dict, scene_card: dict | None = None) -> dict:
    return {
        "generation_brief": brief,
        "scene_card": scene_card or {
            "chapter_number": 1,
            "scene_number": 1,
            "target_word_count": 1250,
            "closing_hook": "An unknown number pings.",
            "characters_present": ["Alex Reyes"],
        },
    }


async def _run_stylist(context: dict, response: str = "Prose.") -> tuple[dict, MagicMock]:
    router = MagicMock()
    router.complete = AsyncMock(return_value=response)
    agent = ProseStylist(router)
    result = await agent.run(context)
    return result, router


class TestRenderBriefRequiredFields:
    def test_minimal_brief_renders_required_sections(self):
        output = _render_brief(_minimal_brief())
        assert "## Scene Objective" in output
        assert "## Turning Point" in output
        assert "## Closing Beat" in output
        assert "## Emotional Arc" in output

    def test_turning_point_shows_trigger_shift_cost(self):
        output = _render_brief(_minimal_brief())
        assert "Trigger: Alex opens the sealed file." in output
        assert "Shift: Case becomes personal." in output
        assert "Cost: Alex chooses transgression." in output

    def test_emotional_arc_renders_as_arrow_chain(self):
        output = _render_brief(_minimal_brief())
        assert "boredom -> recognition -> transgression" in output


class TestRenderBriefOptionalFields:
    def test_optional_fields_omitted_from_minimal_brief(self):
        """Sections for optional fields should not appear when fields are missing."""
        output = _render_brief(_minimal_brief())
        assert "## Opening Mode" not in output
        assert "## Key Beats" not in output
        assert "## Voice Guidance" not in output
        assert "## Delivery Preferences" not in output
        assert "## Required Hooks" not in output
        assert "## Forbidden Moves" not in output
        assert "## Anti-Patterns" not in output

    def test_all_optional_sections_render_when_present(self):
        output = _render_brief(_full_brief())
        assert "## Opening Mode" in output
        assert "sensory_hook" in output
        assert "## Key Beats" in output
        assert "Alex enters the office after hours" in output
        assert "## Voice Guidance" in output
        assert "Zahn efficient dialogue" in output
        assert "## Delivery Preferences" in output
        assert "Reveal mode: gradual" in output
        assert "## Required Hooks" in output
        assert "H01_alex_personal_tie" in output
        assert "## Required Subplots" in output
        assert "## Required Revelations" in output
        assert "## Forbidden Moves (do not write)" in output
        assert "Do not introduce Jordan" in output
        assert "## Anti-Patterns" in output
        assert "Do not open with a flashback" in output

    def test_key_beats_render_state_change_and_pov_reaction(self):
        output = _render_brief(_full_brief())
        assert "State change: Solitude established" in output
        assert "POV reaction: A name recognised" in output


class TestGracefulDegradation:
    def test_empty_brief_does_not_crash(self):
        """Completely empty brief renders with (unspecified) placeholders."""
        output = _render_brief({})
        assert "## Scene Objective" in output
        assert "(unspecified)" in output

    def test_missing_turning_point_fields_render_placeholders(self):
        """If turning_point is partial, missing sub-fields show (unspecified)."""
        brief = _minimal_brief()
        brief["turning_point"] = {"trigger": "Only trigger present"}
        output = _render_brief(brief)
        assert "Trigger: Only trigger present" in output
        assert "Shift: (unspecified)" in output
        assert "Cost: (unspecified)" in output

    def test_delivery_preferences_with_null_register_override(self):
        """register_override = None should not render the section line."""
        brief = _minimal_brief()
        brief["delivery_preferences"] = {
            "reveal_mode": "direct",
            "exposition_budget": "none",
            "register_override": None,
        }
        output = _render_brief(brief)
        assert "Reveal mode: direct" in output
        assert "Register override:" not in output  # null -> omitted


class TestSceneVoiceContractStructuredFields:
    def test_anchor_profile_surfaces_without_free_text_notes(self):
        output = _scene_voice_contract({
            "primary_anchor": "Zahn",
            "supporting_anchor": "Luceno, Bujold",
        })
        assert "## Scene Voice Contract" in output
        assert "### Scene Anchor Profile" in output
        assert "Primary anchor: Zahn" in output
        assert "Supporting anchors: Luceno, Bujold" in output

    def test_stover_permission_true_surfaces_structurally(self):
        output = _scene_voice_contract({"stover_permitted": True})
        assert "### Stover Permission" in output
        assert "is permitted in this scene" in output

    def test_stover_permission_false_surfaces_structurally(self):
        output = _scene_voice_contract({"stover_permitted": False})
        assert "### Stover Permission" in output
        assert "is not permitted in this scene" in output

    def test_generic_permission_surfaces_without_author_name(self):
        output = _scene_voice_contract({
            "scene_voice_permissions": {
                "anchor_profile": {"primary": "Bujold"},
                "authorized_modes": ["heightened_interiority"],
            }
        })
        assert "### Heightened Interiority Permission" in output
        assert "Heightened interior density is permitted in this scene" in output
        assert "Stover" not in output


class TestAgentIntegration:
    async def test_full_prompt_includes_brief_sections(self):
        context = _make_context(_full_brief())
        _, router = await _run_stylist(context)

        user_content = router.complete.await_args.args[1][-1]["content"]
        assert "## Generation Brief" in user_content
        assert "## Scene Objective" in user_content
        assert "## Turning Point" in user_content

    async def test_target_word_count_prefers_scene_card_over_brief(self):
        """scene_card.target_word_count takes precedence over the brief's echo,
        so a mismatch surfaces the scene_card (the canonical source)."""
        brief = _minimal_brief()
        brief["target_word_count"] = 999  # deliberate mismatch
        scene_card = {
            "chapter_number": 1,
            "scene_number": 1,
            "target_word_count": 1250,
        }
        context = _make_context(brief, scene_card)
        _, router = await _run_stylist(context)

        user_content = router.complete.await_args.args[1][-1]["content"]
        assert "1250" in user_content

    async def test_target_word_count_falls_back_to_brief_when_scene_card_missing(self):
        """If scene_card lacks target_word_count, fall back to the brief."""
        brief = _minimal_brief()
        scene_card = {"chapter_number": 1, "scene_number": 1}  # no target
        context = _make_context(brief, scene_card)
        _, router = await _run_stylist(context)

        user_content = router.complete.await_args.args[1][-1]["content"]
        assert "1250" in user_content

    async def test_closing_hook_boundary_still_enforced(self):
        context = _make_context(_minimal_brief())
        _, router = await _run_stylist(context)
        user_content = router.complete.await_args.args[1][-1]["content"]
        assert "SCENE BOUNDARY" in user_content
        assert "An unknown number pings." in user_content

    async def test_returns_prose_and_scene_card(self):
        context = _make_context(_minimal_brief())
        result, _ = await _run_stylist(context, response="Drafted prose.")
        assert result["prose"] == "Drafted prose."
        assert result["scene_card"] is context["scene_card"]

    async def test_prompt_includes_structured_scene_voice_fields(self):
        context = _make_context(
            _minimal_brief(),
            {
                "chapter_number": 1,
                "scene_number": 1,
                "target_word_count": 1250,
                "closing_hook": "An unknown number pings.",
                "characters_present": ["Alex Reyes"],
                "primary_anchor": "Zahn",
                "supporting_anchor": "Luceno, Bujold",
                "stover_permitted": False,
            },
        )
        _, router = await _run_stylist(context)

        user_content = router.complete.await_args.args[1][-1]["content"]
        assert "### Scene Anchor Profile" in user_content
        assert "Primary anchor: Zahn" in user_content
        assert "Supporting anchors: Luceno, Bujold" in user_content
        assert "### Stover Permission" in user_content
        assert "is not permitted in this scene" in user_content

    async def test_prompt_includes_generic_scene_voice_permissions(self):
        context = _make_context(
            _minimal_brief(),
            {
                "chapter_number": 1,
                "scene_number": 1,
                "target_word_count": 1250,
                "closing_hook": "An unknown number pings.",
                "characters_present": ["Alex Reyes"],
                "scene_voice_permissions": {
                    "anchor_profile": {
                        "primary": "Bujold",
                        "supporting": ["Cherryh"],
                    },
                    "authorized_modes": ["heightened_interiority"],
                },
            },
        )
        _, router = await _run_stylist(context)

        user_content = router.complete.await_args.args[1][-1]["content"]
        assert "### Scene Anchor Profile" in user_content
        assert "Primary anchor: Bujold" in user_content
        assert "Supporting anchors: Cherryh" in user_content
        assert "### Heightened Interiority Permission" in user_content
        assert "Heightened interior density is permitted in this scene" in user_content
        assert "Stover" not in user_content


def test_length_calibration_inflates_rendered_ask_only():
    """length_calibration multiplies the rendered word-count ask; the scene
    card's target stays the planning truth telemetry measures against."""
    ps = ProseStylist(MagicMock())
    context = {
        "generation_brief": _minimal_brief(),
        "assembled_context": "ctx",
        "scene_card": {
            "chapter_number": 1, "scene_number": 1,
            "pov_character": "Alex", "mission": "m", "conflict": "c",
            "turning_point": "t", "target_word_count": 2300,
        },
        "length_calibration": 1.8,
    }
    messages = ps._build_messages(context)
    user_text = "\n".join(m["content"] for m in messages if m["role"] == "user")
    assert "4140" in user_text
    assert "2300" not in user_text.split("TARGET LENGTH", 1)[1][:300]


def test_length_calibration_defaults_to_identity():
    ps = ProseStylist(MagicMock())
    context = {
        "generation_brief": _minimal_brief(),
        "assembled_context": "ctx",
        "scene_card": {
            "chapter_number": 1, "scene_number": 1,
            "pov_character": "Alex", "mission": "m", "conflict": "c",
            "turning_point": "t", "target_word_count": 2300,
        },
    }
    messages = ps._build_messages(context)
    user_text = "\n".join(m["content"] for m in messages if m["role"] == "user")
    assert "TARGET LENGTH (HARD CONTRACT): 2300 words" in user_text
