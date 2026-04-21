"""Phase 6.3 — canon_expert consumes concept_seed.meta.branch_point.

Covers two behaviour classes:

1. **Prompt injection** — when a branch_point is present on the concept seed,
   the evaluation prompt includes a ``## Branch Point (AU Divergence)`` block
   plus reclassification guidance on the cross-continuity and era-accuracy
   checks. When absent, the prompt is unchanged from the pre-Phase-6 shape.

2. **Server-side invariants in ``_normalize_output``** — even if the LLM
   disobeys the prompt and emits ``post_divergence_drift`` flags at high
   severity, the normalizer clamps severity to ``minor`` and excludes them
   from the derived verdict. These are belt-and-braces checks; the prompt
   instruction is the first line of defence, the normalizer is the second.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from src.agents.canon_expert import CanonExpert, VIOLATION_CATEGORIES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def canon_expert() -> CanonExpert:
    """A CanonExpert with a mock router. System-prompt load is harmless."""
    router = MagicMock()
    return CanonExpert(router=router)


@pytest.fixture
def base_canon_profile() -> dict:
    """A minimal canon_profile with enough content to trigger every section."""
    return {
        "franchise": "Star Wars Legends",
        "continuity": "Legends EU",
        "continuity_description": "Pre-Disney Expanded Universe",
        "era_description": "Post-Ruusan reformation, ~1000 BBY",
        "narrative_register": "epic space opera with moral weight",
        "cross_continuity_violations": [
            "Disney canon terminology",
            "Knights of the Old Republic retcons",
        ],
        "anachronistic_terms": {"email": ["holomessage", "datapad comm"]},
        "meta_reference_rules": ["No references to the films as films."],
        "franchise_terminology_notes": "Force, lightsaber, hyperdrive are canonical.",
    }


@pytest.fixture
def branch_point() -> dict:
    return {
        "source_canon": "Star Wars Legends EU",
        "divergence_point": "post-Lost Tribe crisis, circa 44 ABY",
        "divergence_description": (
            "After the Lost Tribe crisis, the Jedi Order takes a Ruusan-style "
            "reformation path rather than the canonical Sword of the Jedi arc."
        ),
    }


# ---------------------------------------------------------------------------
# 1. Prompt-injection behaviour
# ---------------------------------------------------------------------------


class TestBranchPointPromptInjection:
    def test_no_branch_point_keeps_legacy_prompt_shape(
        self, canon_expert: CanonExpert, base_canon_profile: dict
    ):
        """With no branch_point, the prompt MUST NOT contain any divergence
        block or reclassification note.

        Note: ``post_divergence_drift`` still appears in the output-format
        enum listing because the category enum is declarative (the LLM needs
        to know it's legal). What the prompt MUST NOT contain is the
        divergence context block, the divergence-reclassification
        instructions on Check 1 / Check 4, or references to a
        ``divergence_point``.
        """
        concept_seed = {
            "meta": {"project_title": "Legacy run"},
            "canon_profile": base_canon_profile,
        }
        prompt = canon_expert._build_evaluation_prompt(
            prose="The Jedi walked the halls.", concept_seed=concept_seed
        )
        assert "Branch Point" not in prompt
        assert "divergence point" not in prompt.lower()
        # The Check 1 / Check 4 reclassification notes are gated on
        # branch_point presence — they must be absent in the legacy path.
        check1_start = prompt.index("### Check 1 -- Cross-Continuity")
        check2_start = prompt.index("### Check 2")
        assert "post_divergence_drift" not in prompt[check1_start:check2_start]
        check4_start = prompt.index("### Check 4")
        check5_start = prompt.index("### Check 5")
        assert "post_divergence_drift" not in prompt[check4_start:check5_start]

    def test_branch_point_injects_dedicated_section(
        self,
        canon_expert: CanonExpert,
        base_canon_profile: dict,
        branch_point: dict,
    ):
        """The divergence block must render with all three declarative fields
        and the reclassification instruction."""
        concept_seed = {
            "meta": {"project_title": "AU run", "branch_point": branch_point},
            "canon_profile": base_canon_profile,
        }
        prompt = canon_expert._build_evaluation_prompt(
            prose="The Jedi walked the halls.", concept_seed=concept_seed
        )
        assert "## Branch Point (AU Divergence)" in prompt
        assert "Source canon: Star Wars Legends EU" in prompt
        assert "post-Lost Tribe crisis" in prompt
        assert "Ruusan-style reformation path" in prompt
        # The AU guidance instructs the LLM on how to reclassify.
        assert "post_divergence_drift" in prompt
        assert "minor" in prompt

    def test_branch_point_propagates_to_cross_continuity_check(
        self,
        canon_expert: CanonExpert,
        base_canon_profile: dict,
        branch_point: dict,
    ):
        """The Check 1 (cross-continuity) block must carry the
        reclassification note when a branch_point is set."""
        concept_seed = {
            "meta": {"branch_point": branch_point},
            "canon_profile": base_canon_profile,
        }
        prompt = canon_expert._build_evaluation_prompt(
            prose="...", concept_seed=concept_seed
        )
        # Locate the Check 1 sub-block.
        check1_start = prompt.index("### Check 1 -- Cross-Continuity")
        check2_start = prompt.index("### Check 2")
        check1_block = prompt[check1_start:check2_start]
        assert "post_divergence_drift" in check1_block
        assert "after the declared divergence point" in check1_block.lower()

    def test_branch_point_propagates_to_era_accuracy_check(
        self,
        canon_expert: CanonExpert,
        base_canon_profile: dict,
        branch_point: dict,
    ):
        """The Check 4 (era accuracy) block must also carry the note."""
        concept_seed = {
            "meta": {"branch_point": branch_point},
            "canon_profile": base_canon_profile,
        }
        prompt = canon_expert._build_evaluation_prompt(
            prose="...", concept_seed=concept_seed
        )
        check4_start = prompt.index("### Check 4")
        check5_start = prompt.index("### Check 5")
        check4_block = prompt[check4_start:check5_start]
        assert "post_divergence_drift" in check4_block

    def test_empty_branch_point_dict_is_treated_as_absent(
        self, canon_expert: CanonExpert, base_canon_profile: dict
    ):
        """A ``branch_point: {}`` block (empty dict) MUST NOT emit the section.
        Only populated branch_points are considered declarative."""
        concept_seed = {
            "meta": {"branch_point": {}},
            "canon_profile": base_canon_profile,
        }
        prompt = canon_expert._build_evaluation_prompt(
            prose="...", concept_seed=concept_seed
        )
        assert "Branch Point" not in prompt

    def test_output_format_advertises_new_category(
        self, canon_expert: CanonExpert
    ):
        """Regardless of branch_point presence the output-format block must
        include post_divergence_drift so LLM output conforms to the enum."""
        section = canon_expert._section_output_format()
        assert "post_divergence_drift" in section
        assert "post_divergence_drift" in " ".join(VIOLATION_CATEGORIES)


# ---------------------------------------------------------------------------
# 2. Normalizer invariants
# ---------------------------------------------------------------------------


class TestNormalizeOutputInvariants:
    def test_post_divergence_drift_severity_clamped_to_minor(self):
        """Invariant 1: even if the LLM emits critical, the normalizer
        downgrades to minor."""
        raw = {
            "violations": [
                {
                    "category": "post_divergence_drift",
                    "severity": "critical",
                    "text": "Jacen Solo falls to the dark side",
                    "explanation": "LOTF is post-divergence source canon.",
                    "suggestion": "Remove or recontextualize.",
                }
            ],
            "verdict": "pass",
            "summary": "AU drift noted.",
        }
        result = CanonExpert._normalize_output(raw)
        assert len(result["violations"]) == 1
        assert result["violations"][0]["severity"] == "minor"

    def test_post_divergence_drift_does_not_force_fail_verdict(self):
        """Invariant 2: when verdict must be derived from violations, a
        high-severity post_divergence_drift flag does NOT cause a fail."""
        raw = {
            "violations": [
                {
                    "category": "post_divergence_drift",
                    "severity": "critical",  # clamped
                    "text": "x",
                    "explanation": "y",
                    "suggestion": "z",
                }
            ],
            "verdict": "BOGUS_VERDICT",  # forces derivation path
            "summary": "",
        }
        result = CanonExpert._normalize_output(raw)
        assert result["verdict"] == "pass"

    def test_real_cross_continuity_violation_still_fails(self):
        """Regression: an actual cross_continuity critical still fails."""
        raw = {
            "violations": [
                {
                    "category": "cross_continuity",
                    "severity": "critical",
                    "text": "x",
                    "explanation": "y",
                    "suggestion": "z",
                }
            ],
            "verdict": "NOT_A_VALID_VERDICT",  # forces derivation
            "summary": "",
        }
        result = CanonExpert._normalize_output(raw)
        assert result["verdict"] == "fail"

    def test_mixed_violations_derive_verdict_from_non_drift_only(self):
        """Verdict derivation uses only non-drift flags."""
        raw = {
            "violations": [
                {
                    "category": "post_divergence_drift",
                    "severity": "critical",
                    "text": "a",
                    "explanation": "",
                    "suggestion": "",
                },
                {
                    "category": "franchise_voice",
                    "severity": "minor",
                    "text": "b",
                    "explanation": "",
                    "suggestion": "",
                },
            ],
            "verdict": "not_pass_not_fail",  # force derivation
            "summary": "",
        }
        result = CanonExpert._normalize_output(raw)
        assert result["verdict"] == "pass"
        # Ensure both survived normalization.
        cats = [v["category"] for v in result["violations"]]
        assert "post_divergence_drift" in cats
        assert "franchise_voice" in cats

    def test_advisory_only_violations_always_clamp_to_pass(self):
        """Even if the LLM stated ``verdict: fail``, an advisory-only
        violations list (post_divergence_drift and/or franchise_voice) must
        clamp to ``pass`` — those categories are calibrated as advisory by
        the system prompt and cannot block a save on their own. The
        LLM's stated verdict is advisory input only; the runtime always
        derives verdict from the normalized violations list."""
        raw = {
            "violations": [
                {
                    "category": "post_divergence_drift",
                    "severity": "minor",
                    "text": "x",
                    "explanation": "",
                    "suggestion": "",
                }
            ],
            "verdict": "fail",
            "summary": "",
            "corrected_prose": "corrected version",
        }
        result = CanonExpert._normalize_output(raw)
        assert result["verdict"] == "pass"
        # When we clamp to pass, corrected_prose is intentionally dropped —
        # there is nothing for the scene to correct.
        assert "corrected_prose" not in result

    def test_blocking_violation_preserves_fail_verdict(self):
        """A critical or moderate violation in a non-advisory category
        (cross_continuity, anachronism, meta_reference, era_accuracy) still
        produces ``verdict: fail`` with ``corrected_prose`` preserved."""
        raw = {
            "violations": [
                {
                    "category": "cross_continuity",
                    "severity": "moderate",
                    "text": "Disney-era holocron reference in Legends scene",
                    "explanation": "",
                    "suggestion": "",
                }
            ],
            "verdict": "fail",
            "summary": "",
            "corrected_prose": "corrected version",
        }
        result = CanonExpert._normalize_output(raw)
        assert result["verdict"] == "fail"
        assert result["corrected_prose"] == "corrected version"


class TestFranchiseVoiceSeverityPolicy:
    """``franchise_voice`` is calibrated as advisory by the system prompt but
    a pre-fix ``_normalize_output`` only clamped ``post_divergence_drift``.
    The runtime must enforce the prompt's own policy: franchise_voice at any
    severity clamps to minor and never contributes to a fail verdict."""

    def test_franchise_voice_moderate_clamps_to_minor(self):
        raw = {
            "violations": [
                {
                    "category": "franchise_voice",
                    "severity": "moderate",
                    "text": "the ambient field had arrived late",
                    "explanation": "",
                    "suggestion": "",
                }
            ],
            "verdict": "fail",
            "summary": "",
        }
        result = CanonExpert._normalize_output(raw)
        assert result["violations"][0]["severity"] == "minor"

    def test_franchise_voice_only_does_not_block(self):
        """Even when the LLM rates franchise_voice at ``critical``, the scene
        still passes the save-blocker layer — franchise_voice by design is
        advisory register drift, not a canon contradiction."""
        raw = {
            "violations": [
                {
                    "category": "franchise_voice",
                    "severity": "critical",
                    "text": "clinical framing",
                    "explanation": "",
                    "suggestion": "",
                }
            ],
            "verdict": "fail",
            "summary": "",
        }
        result = CanonExpert._normalize_output(raw)
        assert result["verdict"] == "pass"
        assert result["violations"][0]["severity"] == "minor"


class TestSceneCardVoicePermissions:
    """The save-blocking canon_expert must see scene-level voice permissions
    (scene_card.notes, stover_permitted, anti_patterns) so drafter-faithful
    use of scene-authorized metaphors is not flagged as franchise_voice drift.
    This invariant is the load-bearing part of the scene-card/seed
    contradiction fix; without it the runtime silently diverges from the
    drafter's view of what the scene permits."""

    def test_prompt_surfaces_scene_card_notes(self, canon_expert, base_canon_profile):
        scene_card = {
            "notes": "Use one consistent metaphor for this scene (the half-beat lag in the ambient field). Keep it auditory and vibrational.",
        }
        concept_seed = {"canon_profile": base_canon_profile}
        prompt = canon_expert._build_evaluation_prompt(
            prose="sample prose",
            concept_seed=concept_seed,
            scene_card=scene_card,
        )
        assert "Scene-Level Voice Permissions" in prompt
        assert "half-beat lag in the ambient field" in prompt

    def test_prompt_surfaces_stover_permitted_flag(
        self, canon_expert, base_canon_profile
    ):
        scene_card = {"stover_permitted": True}
        concept_seed = {"canon_profile": base_canon_profile}
        prompt = canon_expert._build_evaluation_prompt(
            prose="sample prose",
            concept_seed=concept_seed,
            scene_card=scene_card,
        )
        assert "stover_permitted: true" in prompt
        assert "Stover-style" in prompt

    def test_prompt_omits_permissions_section_when_scene_card_empty(
        self, canon_expert, base_canon_profile
    ):
        concept_seed = {"canon_profile": base_canon_profile}
        prompt_without = canon_expert._build_evaluation_prompt(
            prose="sample prose",
            concept_seed=concept_seed,
            scene_card=None,
        )
        prompt_empty = canon_expert._build_evaluation_prompt(
            prose="sample prose",
            concept_seed=concept_seed,
            scene_card={},
        )
        assert "Scene-Level Voice Permissions" not in prompt_without
        assert "Scene-Level Voice Permissions" not in prompt_empty

    @pytest.mark.asyncio
    async def test_evaluate_passes_scene_card_to_prompt_builder(
        self, canon_expert, base_canon_profile, monkeypatch
    ):
        """End-to-end: the orchestrator passes scene_card in the context dict
        and evaluate() propagates it into _build_evaluation_prompt."""
        captured = {}

        original = canon_expert._build_evaluation_prompt

        def spy(prose, concept_seed, scene_card=None):
            captured["scene_card"] = scene_card
            return original(prose, concept_seed, scene_card)

        monkeypatch.setattr(canon_expert, "_build_evaluation_prompt", spy)

        async def fake_complete(role, messages):
            return '{"violations": [], "verdict": "pass", "summary": "ok"}'

        canon_expert.router.complete = fake_complete

        await canon_expert.evaluate(
            prose="sample",
            context={
                "concept_seed": {"canon_profile": base_canon_profile},
                "scene_card": {"notes": "authorized metaphor X"},
            },
        )
        assert captured["scene_card"] == {"notes": "authorized metaphor X"}
