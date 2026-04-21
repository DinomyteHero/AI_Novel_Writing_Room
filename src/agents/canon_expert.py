"""Canon Expert agent -- franchise-agnostic, template-driven canon validation.

Validates prose against a canon_profile supplied via the concept seed.
All franchise-specific knowledge (terminology, era constraints, continuity
boundaries, anachronistic terms) is injected at runtime from the concept
seed's canon_profile section.  The agent code itself contains zero
franchise-specific strings.

When a CanonEvidenceRanker is provided, retrieved evidence supplements
the evaluation.  When the concept seed has no canon_profile, the agent
falls back to generic internal-consistency checks.
"""

import json
import logging
import re
from typing import Optional

from src.agents.base_agent import BaseAgent
from src.rag.canon_evidence import CanonEvidenceRanker

logger = logging.getLogger(__name__)

# Categories used in structured violation output.
# ``post_divergence_drift`` is the Phase 6 AU-aware category: a violation that
# WOULD have been ``cross_continuity`` or ``era_accuracy`` but refers to a fact
# that falls past the universe's declared ``branch_point.divergence_point``.
# These are emitted with reduced severity (see _normalize_output).
VIOLATION_CATEGORIES = (
    "cross_continuity",
    "anachronism",
    "meta_reference",
    "era_accuracy",
    "franchise_voice",
    "post_divergence_drift",
)

SEVERITY_LEVELS = ("critical", "moderate", "minor")
VERDICT_VALUES = ("pass", "fail")


class CanonExpert(BaseAgent):
    """Franchise-agnostic canon validation agent.

    Primary interface
    -----------------
    evaluate(prose, context)  -- validates *prose* using the canon_profile
                                 found in context["concept_seed"].

    Legacy interface
    ----------------
    run(context)              -- backward-compatible path; extracts prose
                                 from the scene card and delegates to
                                 evaluate().
    """

    def __init__(
        self,
        router,
        canon_evidence: Optional[CanonEvidenceRanker] = None,
        role: str = "canon_expert",
    ):
        self.canon_evidence = canon_evidence
        super().__init__(router, role)

    # ------------------------------------------------------------------
    # Primary interface
    # ------------------------------------------------------------------

    async def evaluate(self, prose: str, context: dict) -> dict:
        """Evaluate *prose* against the canon profile in the concept seed.

        Returns a dict with keys: violations, verdict, summary, and
        (when verdict is fail) corrected_prose.
        """
        concept_seed = context.get("concept_seed", {})
        scene_card = context.get("scene_card") or {}
        canon_profile = concept_seed.get("canon_profile")

        if canon_profile is None:
            logger.warning(
                "No canon_profile in concept seed; running generic checks only."
            )

        prompt = self._build_evaluation_prompt(prose, concept_seed, scene_card)

        # Optionally enrich with RAG evidence
        evidence_block = self._retrieve_evidence_block(context)

        messages = self._build_evaluation_messages(prompt, evidence_block)
        raw_response = await self.router.complete(self.role, messages)
        return self._extract_structured_output(raw_response)

    # ------------------------------------------------------------------
    # Legacy interface (backward compatibility with BaseAgent.run)
    # ------------------------------------------------------------------

    def _format_context(self, context: dict) -> str:
        """Build the user prompt for the legacy run() path.

        Checks for prose passed directly (from orchestrator), then falls
        back to extracting from the scene card's draft_prose or
        scene_description.
        """
        scene_card = context.get("scene_card", {}) or {}
        prose = context.get("prose", "")
        if not prose:
            prose = scene_card.get("draft_prose", "") or scene_card.get(
                "scene_description", ""
            )
        concept_seed = context.get("concept_seed", {})

        prompt = self._build_evaluation_prompt(prose, concept_seed, scene_card)
        evidence_block = self._retrieve_evidence_block(context)
        if evidence_block:
            prompt = f"{prompt}\n\n## Retrieved Canon Evidence\n{evidence_block}"
        return prompt

    def _parse_response(self, response: str, context: dict) -> dict:
        """Parse the raw LLM response into the structured output dict.

        Maintained for backward compatibility with BaseAgent.run().
        Also returns the legacy canon_notes key so downstream consumers
        that depend on the old format continue to work.
        """
        result = self._extract_structured_output(response)
        # Legacy keys for backward compatibility
        result.setdefault("canon_notes", result.get("summary", response))
        result.setdefault(
            "canon_elements_needed",
            context.get("scene_card", {}).get("canon_elements_needed", []),
        )
        return result

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_evaluation_prompt(
        self,
        prose: str,
        concept_seed: dict,
        scene_card: Optional[dict] = None,
    ) -> str:
        """Dynamically construct the evaluation prompt from the canon profile.

        Builds five check sections using data drawn from the ``canon_profile``,
        plus a scene-level permissions section drawn from ``scene_card`` when
        one is provided. When no canon_profile exists, falls back to generic
        internal-consistency checks.
        """
        canon_profile = concept_seed.get("canon_profile")
        branch_point = (concept_seed.get("meta") or {}).get("branch_point")
        sections: list[str] = []

        # Header with franchise/continuity context (if available)
        sections.append(self._section_header(canon_profile))

        # Optional AU divergence context — when present, cross-continuity and
        # era-accuracy checks downstream should reclassify post-divergence
        # facts as post_divergence_drift rather than critical violations.
        branch_section = self._section_branch_point(branch_point)
        if branch_section:
            sections.append(branch_section)

        # Scene-level voice permissions. When a scene card pre-authorizes a
        # specific metaphor or register (e.g. "use the half-beat lag in the
        # ambient field" or ``stover_permitted: true``), it overrides the
        # franchise-wide register rule for this evaluation only. Without this
        # section, canon_expert flags the drafter's faithful use of the
        # authorized metaphor as franchise_voice drift.
        permissions_section = self._section_scene_card_voice_permissions(scene_card)
        if permissions_section:
            sections.append(permissions_section)

        # --- Check 1: Cross-continuity contamination ---
        sections.append(
            self._section_cross_continuity(canon_profile, branch_point)
        )

        # --- Check 2: Anachronistic terms ---
        sections.append(self._section_anachronistic_terms(canon_profile))

        # --- Check 3: Meta-reference leakage ---
        sections.append(self._section_meta_references(canon_profile))

        # --- Check 4: Era accuracy ---
        sections.append(self._section_era_accuracy(canon_profile, branch_point))

        # --- Check 5: Franchise voice ---
        sections.append(self._section_franchise_voice(canon_profile))

        # Output format instructions
        sections.append(self._section_output_format())

        # The prose to evaluate
        sections.append(f"## Prose to Evaluate\n\n{prose}")

        return "\n\n".join(sections)

    # -- Section builders -----------------------------------------------

    def _section_header(self, canon_profile: Optional[dict]) -> str:
        if canon_profile is None:
            return (
                "## Canon Evaluation (Generic Mode)\n"
                "No franchise-specific canon profile was provided. "
                "Perform generic internal-consistency checks on the prose."
            )
        parts = ["## Canon Evaluation"]
        if canon_profile.get("franchise"):
            parts.append(f"Franchise: {canon_profile['franchise']}")
        if canon_profile.get("continuity"):
            parts.append(f"Continuity: {canon_profile['continuity']}")
        if canon_profile.get("continuity_description"):
            parts.append(
                f"Continuity Description: {canon_profile['continuity_description']}"
            )
        if canon_profile.get("era_description"):
            parts.append(f"Era: {canon_profile['era_description']}")
        if canon_profile.get("narrative_register"):
            parts.append(
                f"Narrative Register: {canon_profile['narrative_register']}"
            )
        return "\n".join(parts)

    def _section_scene_card_voice_permissions(
        self, scene_card: Optional[dict]
    ) -> str:
        """Surface scene-level voice permissions that override franchise rules.

        The drafter sees ``scene_card.notes`` via the Scene Voice Contract
        block in its prompt, and the scene card may authorize specific
        metaphors or register intensities for this scene (e.g. Ruusan Ch 01
        Sc 01 authorizes "the half-beat lag in the ambient field" as the
        scene's one consistent metaphor; Ch 13/25/26 set ``stover_permitted``
        to unlock Stover-style intensity). Canon_expert has to see the same
        authorization or it flags the drafter's faithful use as franchise_voice
        drift.
        """
        if not scene_card:
            return ""
        notes = (scene_card.get("notes") or "").strip()
        stover_permitted = bool(scene_card.get("stover_permitted"))
        anti_patterns = scene_card.get("anti_patterns") or []
        if not notes and not stover_permitted and not anti_patterns:
            return ""
        parts = [
            "## Scene-Level Voice Permissions (READ BEFORE FLAGGING FRANCHISE_VOICE)",
            "The following scene-level authorizations override franchise-wide voice "
            "rules for THIS scene only. A phrase or metaphor permitted here is NOT "
            "a franchise_voice violation; treating it as one is a false positive.",
        ]
        if notes:
            parts.append("\n### Scene-card notes (verbatim)")
            parts.append(notes)
        if stover_permitted:
            parts.append(
                "\n### stover_permitted: true"
            )
            parts.append(
                "This scene permits Stover-style prose intensity — heightened "
                "physicality, metaphysical direct address, sharper abstraction. "
                "Do not flag such moves as franchise_voice drift."
            )
        if anti_patterns:
            parts.append("\n### Scene-card anti-patterns (for context only)")
            for p in anti_patterns:
                parts.append(f"- {p}")
        return "\n".join(parts)

    def _section_branch_point(self, branch_point: Optional[dict]) -> str:
        """Emit the AU divergence context block when a branch_point is declared.

        Returns an empty string when no branch_point is set so the caller can
        skip the section entirely.
        """
        if not branch_point:
            return ""
        parts = ["## Branch Point (AU Divergence)"]
        source_canon = branch_point.get("source_canon")
        divergence_point = branch_point.get("divergence_point")
        divergence_description = branch_point.get("divergence_description")
        if source_canon:
            parts.append(f"Source canon: {source_canon}")
        if divergence_point:
            parts.append(f"Divergence point: {divergence_point}")
        if divergence_description:
            parts.append(f"Divergence description: {divergence_description}")
        parts.append(
            "This universe intentionally diverges from the source canon at "
            "the divergence point above. When a potential violation concerns "
            "a fact drawn from source canon that falls AFTER the divergence "
            "point, tag it with category \"post_divergence_drift\" and "
            "severity \"minor\" rather than \"cross_continuity\" / "
            "\"era_accuracy\" at higher severity. The flag stays visible for "
            "audit but does not hard-fail the scene."
        )
        return "\n".join(parts)

    def _section_cross_continuity(
        self,
        canon_profile: Optional[dict],
        branch_point: Optional[dict] = None,
    ) -> str:
        heading = "### Check 1 -- Cross-Continuity Contamination"
        if canon_profile is None:
            return (
                f"{heading}\n"
                "Flag any references that contradict facts established "
                "earlier in the same text."
            )
        violations_list = canon_profile.get("cross_continuity_violations", [])
        if not violations_list:
            base = (
                f"{heading}\n"
                "No explicit cross-continuity violations were listed in "
                "the canon profile. Check for any references that clearly "
                "belong to a different continuity or timeline than the one "
                "specified above."
            )
        else:
            items = "\n".join(f"- {v}" for v in violations_list)
            base = (
                f"{heading}\n"
                f"The following elements are OFF-LIMITS for this continuity. "
                f"Flag any occurrence as a cross-continuity violation:\n{items}"
            )
        if branch_point:
            base += (
                "\n\nNote: if a flagged element derives from source canon "
                "AFTER the declared divergence point, reclassify it as "
                "category \"post_divergence_drift\", severity \"minor\"."
            )
        return base

    def _section_anachronistic_terms(self, canon_profile: Optional[dict]) -> str:
        heading = "### Check 2 -- Anachronistic Terms"
        if canon_profile is None:
            return (
                f"{heading}\n"
                "Flag any modern Earth-specific terminology, brand names, "
                "or real-world cultural references that break immersion in "
                "the fictional setting."
            )
        term_map = canon_profile.get("anachronistic_terms", {})
        if not term_map:
            return (
                f"{heading}\n"
                "No specific anachronistic terms were listed. Flag any "
                "term that is clearly out of place for the franchise's "
                "setting and era."
            )
        lines = []
        for term, replacements in term_map.items():
            replacement_str = ", ".join(f'"{r}"' for r in replacements)
            lines.append(
                f'- "{term}" should be replaced with one of: {replacement_str}'
            )
        items = "\n".join(lines)
        return (
            f"{heading}\n"
            f"The following terms are anachronistic for this setting. "
            f"If found, suggest the listed replacements:\n{items}"
        )

    def _section_meta_references(self, canon_profile: Optional[dict]) -> str:
        heading = "### Check 3 -- Meta-Reference Leakage"
        if canon_profile is None:
            return (
                f"{heading}\n"
                "Flag any references where characters appear to have "
                "knowledge of being in a story, or where real-world "
                "production details leak into the narrative."
            )
        rules = canon_profile.get("meta_reference_rules", [])
        if not rules:
            return (
                f"{heading}\n"
                "No specific meta-reference rules were listed. Flag any "
                "instance where the prose breaks the fourth wall or "
                "references the franchise as a fictional property."
            )
        items = "\n".join(f"- {r}" for r in rules)
        return (
            f"{heading}\n"
            f"Apply the following meta-reference rules:\n{items}"
        )

    def _section_era_accuracy(
        self,
        canon_profile: Optional[dict],
        branch_point: Optional[dict] = None,
    ) -> str:
        heading = "### Check 4 -- Era Accuracy"
        if canon_profile is None:
            base = (
                f"{heading}\n"
                "Check that all events, technology, and cultural details "
                "are internally consistent with the time period "
                "established in the text."
            )
        else:
            era = canon_profile.get("era_description", "")
            if not era:
                base = (
                    f"{heading}\n"
                    "No era description was provided. Check that technology, "
                    "events, and cultural details are consistent with what "
                    "has been established in the continuity."
                )
            else:
                base = (
                    f"{heading}\n"
                    f"The story is set in the following era:\n{era}\n\n"
                    f"Flag any technology, events, organizations, or cultural "
                    f"details that belong to a different era within this "
                    f"franchise's timeline."
                )
        if branch_point:
            base += (
                "\n\nNote: era facts that belong to source canon AFTER the "
                "declared divergence point are intentional AU drift — "
                "reclassify as category \"post_divergence_drift\", "
                "severity \"minor\"."
            )
        return base

    def _section_franchise_voice(self, canon_profile: Optional[dict]) -> str:
        heading = "### Check 5 -- Franchise Voice"
        if canon_profile is None:
            return (
                f"{heading}\n"
                "Check that the tone and register are internally "
                "consistent throughout the prose."
            )
        parts = [heading]
        register = canon_profile.get("narrative_register", "")
        if register:
            parts.append(
                f"Expected narrative register: {register}\n"
                f"Flag any passages that deviate from this register."
            )
        terminology_notes = canon_profile.get("franchise_terminology_notes", "")
        if terminology_notes:
            parts.append(
                f"Franchise terminology notes:\n{terminology_notes}"
            )
        if len(parts) == 1:
            parts.append(
                "No specific voice guidelines were provided. Check that "
                "the prose maintains a consistent tone and avoids jarring "
                "register shifts."
            )
        return "\n".join(parts)

    def _section_output_format(self) -> str:
        return (
            "## Output Format\n"
            "Return your analysis as a single JSON object with these keys:\n"
            "- **violations**: a list of objects, each with:\n"
            "  - category: one of cross_continuity, anachronism, "
            "meta_reference, era_accuracy, franchise_voice, "
            "post_divergence_drift\n"
            "  - severity: one of critical, moderate, minor. "
            "post_divergence_drift entries MUST use severity \"minor\".\n"
            "  - text: the offending phrase from the prose\n"
            "  - explanation: why this is a violation\n"
            "  - suggestion: a suggested fix\n"
            "- **local_fixes**: OPTIONAL list of narrow literal-substitution "
            "fixes the runtime can apply without re-drafting. Only emit an "
            "entry when the fix is a safe exact-string swap (e.g. an "
            "anachronistic term has a canonical replacement). Skip for "
            "nuanced issues that need rewriting. Each entry has:\n"
            "  - category: one of the violation categories above\n"
            "  - pattern: the EXACT literal substring that appears in the "
            "prose (case-sensitive, no regex)\n"
            "  - replacement: the exact literal substring to substitute\n"
            "  - reason: one-sentence rationale\n"
            "- **verdict**: \"pass\" if no critical or moderate violations, "
            "\"fail\" otherwise. post_divergence_drift entries never cause "
            "a \"fail\" verdict on their own.\n"
            "- **summary**: one-sentence assessment\n"
            "- **corrected_prose**: the full prose with all violations "
            "fixed (include ONLY when verdict is \"fail\")\n\n"
            "Return ONLY the JSON object.  No markdown fences, no commentary."
        )

    # ------------------------------------------------------------------
    # RAG evidence retrieval
    # ------------------------------------------------------------------

    def _retrieve_evidence_block(self, context: dict) -> str:
        """Retrieve and format canon evidence when a ranker is available."""
        if self.canon_evidence is None:
            return ""

        scene_card = context.get("scene_card", {})
        canon_elements = scene_card.get("canon_elements_needed", [])
        if not canon_elements:
            return ""

        all_evidence: list[dict] = []
        for element in canon_elements:
            evidence = self.canon_evidence.get_evidence(element, k=3)
            all_evidence.extend(evidence)

        if not all_evidence:
            return ""

        return self.canon_evidence.format_evidence_for_context(all_evidence)

    # ------------------------------------------------------------------
    # Message construction
    # ------------------------------------------------------------------

    def _build_evaluation_messages(
        self, prompt: str, evidence_block: str
    ) -> list[dict]:
        """Build the messages list for the LLM call."""
        user_content = prompt
        if evidence_block:
            user_content = (
                f"{prompt}\n\n## Retrieved Canon Evidence\n{evidence_block}"
            )
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _extract_structured_output(self, raw_response: str) -> dict:
        """Extract and validate the JSON output from the LLM response.

        The model may return text before or after the JSON block, or
        wrap it in markdown fences.  This method extracts the first
        valid JSON object it finds and normalizes the structure.
        """
        parsed = self._extract_json(raw_response)
        if parsed is None:
            logger.warning(
                "Could not parse JSON from canon expert response; "
                "returning raw text as summary."
            )
            return {
                "violations": [],
                "verdict": "pass",
                "summary": raw_response.strip(),
            }

        # Normalize and validate
        return self._normalize_output(parsed)

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """Extract the first JSON object from *text*.

        Handles markdown fences (```json ... ```) and leading/trailing
        prose around the JSON block.
        """
        # Strip markdown code fences if present
        stripped = re.sub(r"```(?:json)?\s*\n?", "", text)
        stripped = stripped.strip()

        # Try parsing the whole thing first
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                return obj
        except (json.JSONDecodeError, ValueError):
            pass

        # Find the first { ... } block by scanning for balanced braces
        start = stripped.find("{")
        if start == -1:
            return None

        depth = 0
        for i in range(start, len(stripped)):
            if stripped[i] == "{":
                depth += 1
            elif stripped[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(stripped[start : i + 1])
                    except (json.JSONDecodeError, ValueError):
                        return None
        return None

    # Categories whose severity is clamped to ``minor`` regardless of what the
    # LLM emits, and which never cause a ``fail`` verdict on their own. These
    # are the surface-level / register-drift categories the system prompt
    # explicitly calibrates as advisory (see canon_expert.md §Severity
    # Calibration). Without the clamp, a model rating e.g. franchise_voice
    # at ``moderate`` would trip the save-blocker layer even though the
    # prompt's own policy is that franchise_voice is advisory.
    _ADVISORY_CATEGORIES = frozenset({"post_divergence_drift", "franchise_voice"})

    @classmethod
    def _normalize_output(cls, parsed: dict) -> dict:
        """Ensure the parsed dict conforms to the expected schema.

        Enforces two invariants for advisory-class categories
        (``post_divergence_drift``, ``franchise_voice``) — the prompt asks
        the LLM to honour these, but we do not trust the LLM:
        1. Severity is clamped to ``minor`` regardless of what the LLM emits.
        2. These flags never contribute to a ``fail`` verdict, even when the
           LLM explicitly stated ``verdict: fail``.
        """
        violations = parsed.get("violations", [])
        normalized_violations = []
        for v in violations:
            if not isinstance(v, dict):
                continue
            category = v.get("category", "franchise_voice")
            severity = v.get("severity", "minor")
            if category in cls._ADVISORY_CATEGORIES:
                severity = "minor"
            normalized_violations.append(
                {
                    "category": category,
                    "severity": severity,
                    "text": v.get("text", ""),
                    "explanation": v.get("explanation", ""),
                    "suggestion": v.get("suggestion", ""),
                }
            )

        # Always derive verdict from the normalized (advisory-clamped)
        # violations list. The LLM's stated verdict is advisory input only —
        # if clamping advisory categories to minor leaves no critical/moderate
        # violations, the scene must pass regardless of what the LLM said.
        blocking_severities = {
            v["severity"]
            for v in normalized_violations
            if v["category"] not in cls._ADVISORY_CATEGORIES
        }
        verdict = (
            "fail"
            if blocking_severities & {"critical", "moderate"}
            else "pass"
        )

        result = {
            "violations": normalized_violations,
            "verdict": verdict,
            "summary": parsed.get("summary", ""),
        }

        if verdict == "fail" and "corrected_prose" in parsed:
            result["corrected_prose"] = parsed["corrected_prose"]

        # Slice 11.1 (Forward Relay v4): narrow-repair local_fixes. Validated
        # to shape at this layer; whitelist gating + application happens in the
        # orchestrator so the agent stays franchise-agnostic.
        raw_fixes = parsed.get("local_fixes") or []
        local_fixes: list[dict] = []
        for fix in raw_fixes:
            if not isinstance(fix, dict):
                continue
            category = fix.get("category")
            pattern = fix.get("pattern")
            replacement = fix.get("replacement")
            if (
                not isinstance(category, str)
                or not isinstance(pattern, str)
                or not isinstance(replacement, str)
                or not pattern
            ):
                continue
            local_fixes.append(
                {
                    "category": category,
                    "pattern": pattern,
                    "replacement": replacement,
                    "reason": str(fix.get("reason", "")),
                }
            )
        if local_fixes:
            result["local_fixes"] = local_fixes

        return result
