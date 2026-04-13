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
VIOLATION_CATEGORIES = (
    "cross_continuity",
    "anachronism",
    "meta_reference",
    "era_accuracy",
    "franchise_voice",
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
        canon_profile = concept_seed.get("canon_profile")

        if canon_profile is None:
            logger.warning(
                "No canon_profile in concept seed; running generic checks only."
            )

        prompt = self._build_evaluation_prompt(prose, concept_seed)

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
        prose = context.get("prose", "")
        if not prose:
            scene_card = context.get("scene_card", {})
            prose = scene_card.get("draft_prose", "") or scene_card.get(
                "scene_description", ""
            )
        concept_seed = context.get("concept_seed", {})

        prompt = self._build_evaluation_prompt(prose, concept_seed)
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

    def _build_evaluation_prompt(self, prose: str, concept_seed: dict) -> str:
        """Dynamically construct the evaluation prompt from the canon profile.

        Builds five check sections using ONLY data drawn from the
        canon_profile.  When no canon_profile exists, falls back to
        generic internal-consistency checks.
        """
        canon_profile = concept_seed.get("canon_profile")
        sections: list[str] = []

        # Header with franchise/continuity context (if available)
        sections.append(self._section_header(canon_profile))

        # --- Check 1: Cross-continuity contamination ---
        sections.append(
            self._section_cross_continuity(canon_profile)
        )

        # --- Check 2: Anachronistic terms ---
        sections.append(self._section_anachronistic_terms(canon_profile))

        # --- Check 3: Meta-reference leakage ---
        sections.append(self._section_meta_references(canon_profile))

        # --- Check 4: Era accuracy ---
        sections.append(self._section_era_accuracy(canon_profile))

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

    def _section_cross_continuity(self, canon_profile: Optional[dict]) -> str:
        heading = "### Check 1 -- Cross-Continuity Contamination"
        if canon_profile is None:
            return (
                f"{heading}\n"
                "Flag any references that contradict facts established "
                "earlier in the same text."
            )
        violations_list = canon_profile.get("cross_continuity_violations", [])
        if not violations_list:
            return (
                f"{heading}\n"
                "No explicit cross-continuity violations were listed in "
                "the canon profile. Check for any references that clearly "
                "belong to a different continuity or timeline than the one "
                "specified above."
            )
        items = "\n".join(f"- {v}" for v in violations_list)
        return (
            f"{heading}\n"
            f"The following elements are OFF-LIMITS for this continuity. "
            f"Flag any occurrence as a cross-continuity violation:\n{items}"
        )

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

    def _section_era_accuracy(self, canon_profile: Optional[dict]) -> str:
        heading = "### Check 4 -- Era Accuracy"
        if canon_profile is None:
            return (
                f"{heading}\n"
                "Check that all events, technology, and cultural details "
                "are internally consistent with the time period "
                "established in the text."
            )
        era = canon_profile.get("era_description", "")
        if not era:
            return (
                f"{heading}\n"
                "No era description was provided. Check that technology, "
                "events, and cultural details are consistent with what "
                "has been established in the continuity."
            )
        return (
            f"{heading}\n"
            f"The story is set in the following era:\n{era}\n\n"
            f"Flag any technology, events, organizations, or cultural "
            f"details that belong to a different era within this "
            f"franchise's timeline."
        )

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
            "meta_reference, era_accuracy, franchise_voice\n"
            "  - severity: one of critical, moderate, minor\n"
            "  - text: the offending phrase from the prose\n"
            "  - explanation: why this is a violation\n"
            "  - suggestion: a suggested fix\n"
            "- **verdict**: \"pass\" if no critical or moderate violations, "
            "\"fail\" otherwise\n"
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

    @staticmethod
    def _normalize_output(parsed: dict) -> dict:
        """Ensure the parsed dict conforms to the expected schema."""
        violations = parsed.get("violations", [])
        normalized_violations = []
        for v in violations:
            if not isinstance(v, dict):
                continue
            normalized_violations.append(
                {
                    "category": v.get("category", "franchise_voice"),
                    "severity": v.get("severity", "minor"),
                    "text": v.get("text", ""),
                    "explanation": v.get("explanation", ""),
                    "suggestion": v.get("suggestion", ""),
                }
            )

        verdict = parsed.get("verdict", "pass")
        if verdict not in VERDICT_VALUES:
            # Derive verdict from violations
            severities = {v["severity"] for v in normalized_violations}
            verdict = (
                "fail"
                if severities & {"critical", "moderate"}
                else "pass"
            )

        result = {
            "violations": normalized_violations,
            "verdict": verdict,
            "summary": parsed.get("summary", ""),
        }

        if verdict == "fail" and "corrected_prose" in parsed:
            result["corrected_prose"] = parsed["corrected_prose"]

        return result
