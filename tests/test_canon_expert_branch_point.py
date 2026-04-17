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

    def test_explicit_fail_verdict_is_preserved(self):
        """The LLM's own explicit verdict wins when it's a valid enum value —
        we don't override to pass just because the violations are drift."""
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
        assert result["verdict"] == "fail"
        assert result["corrected_prose"] == "corrected version"
