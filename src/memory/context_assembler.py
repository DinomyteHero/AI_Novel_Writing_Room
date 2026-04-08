"""Context Assembler — builds per-scene prompt payloads.

Phase 1: Simple concatenation of story bible, scene card, and previous chapter text.
Phase 2: Full four-tier memory system with ChromaDB, SQLite, knowledge layers, and canon RAG.

When Phase 2 dependencies are not provided (None), falls back to Phase 1 behavior.
"""

import json
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.memory.chapter_memory import ChapterMemory
    from src.memory.knowledge_layers import KnowledgeLayers
    from src.memory.story_state import StoryState
    from src.rag.canon_db import CanonDB


# Token budget per tier (approximate: 1 token ~ 0.75 words)
TOKEN_BUDGETS = {
    "bible_summary": 2000,
    "act_summary": 500,
    "chapter_summaries": 1200,
    "canon_rag": 1000,
    "character_voices": 1000,
    "character_knowledge": 500,
    "recent_prose": 3500,
    "scene_card": 500,
    "negative_constraints": 400,
    # Phase 5 tiers
    "voice_rules": 300,
    "hook_agenda": 400,
    "arc_context": 300,
    "subplot_context": 300,
    "terminology": 200,
}


class ContextAssembler:
    """Builds the prompt payload for each generation call.

    Phase 1 (default): Simple concatenation of story bible, scene card,
    and previous chapter text with basic truncation.

    Phase 2 (when dependencies provided): Full four-tier memory:
      Tier 1: Story bible essentials (static)
      Tier 2: Act summary (updated at milestones)
      Tier 3: ChromaDB chapter summaries (rolling window)
      Tier 4: Recent prose context
      Plus: Canon RAG, character knowledge, voice sheets
    """

    def __init__(
        self,
        concept_seed_path: str,
        negative_constraints_path: str = "config/negative_constraints.yaml",
        manuscripts_dir: str = "data/manuscripts",
        # Phase 2 optional dependencies:
        story_state: Optional["StoryState"] = None,
        knowledge_layers: Optional["KnowledgeLayers"] = None,
        chapter_memory: Optional["ChapterMemory"] = None,
        canon_db: Optional["CanonDB"] = None,
    ):
        self.concept_seed = self._load_json(concept_seed_path)
        self.negative_constraints = self._load_constraints(negative_constraints_path)
        self.manuscripts_dir = Path(manuscripts_dir)

        # Phase 2 dependencies (None = Phase 1 fallback)
        self.story_state = story_state
        self.knowledge_layers = knowledge_layers
        self.chapter_memory = chapter_memory
        self.canon_db = canon_db

    @property
    def _phase2_enabled(self) -> bool:
        """Check if any Phase 2 dependencies are available."""
        return any([
            self.story_state,
            self.knowledge_layers,
            self.chapter_memory,
            self.canon_db,
        ])

    def _load_json(self, path: str) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def _load_constraints(self, path: str) -> str:
        import yaml

        with open(path, encoding="utf-8") as f:
            constraints = yaml.safe_load(f)

        lines = []
        for category, phrases in constraints.get("banned_phrases", {}).items():
            lines.append(f"### {category}")
            for phrase in phrases:
                lines.append(f"- AVOID: {phrase}")

        rules = constraints.get("structural_rules", {})
        if rules:
            lines.append("\n### Structural Rules")
            for key, value in rules.items():
                lines.append(f"- {key}: {value}")

        return "\n".join(lines)

    def get_bible_summary(self) -> str:
        """Extract a concise story bible summary from the concept seed."""
        seed = self.concept_seed
        meta = seed.get("meta", {})
        premise = seed.get("premise", {})
        conflict = seed.get("conflict", {})
        theme = seed.get("theme", {})

        parts = [
            f"# {meta.get('project_title', 'Untitled')}",
            f"**Franchise**: {meta.get('franchise', 'Unknown')}",
            f"**Era**: {meta.get('era', 'Unknown')}",
            f"**Tone**: {meta.get('tone', 'Unknown')}",
            f"**POV**: {meta.get('pov_structure', 'Unknown')}",
            "",
            f"## Premise",
            f"**What If**: {premise.get('what_if', '')}",
            f"**CDQ**: {premise.get('central_dramatic_question', '')}",
            "",
            f"## Conflict",
            f"**Antagonist**: {conflict.get('primary_antagonistic_force', {}).get('identity', '')}",
            f"**Motivation**: {conflict.get('primary_antagonistic_force', {}).get('motivation', '')}",
            f"**Lock-in**: {conflict.get('lock_in_mechanism', '')}",
            "",
            f"## Theme",
            f"**Premise**: {theme.get('thematic_premise', '')}",
        ]

        # Add cast summaries
        cast = seed.get("ensemble_cast", [])
        if cast:
            parts.append("\n## Cast")
            for char in cast:
                parts.append(
                    f"- **{char['name']}** ({char['role']}): "
                    f"{char.get('voice_notes', '')}"
                )

        # Add force mechanics if present
        mechanics = seed.get("force_mechanics", {})
        if mechanics:
            parts.append(f"\n## Special Mechanics")
            parts.append(f"**Rule**: {mechanics.get('primary_rule', '')}")

        # Add canon constraints
        canon = seed.get("canon_constraints", {})
        if canon.get("style_constraints"):
            parts.append("\n## Style Constraints")
            for constraint in canon["style_constraints"]:
                parts.append(f"- {constraint}")

        return "\n".join(parts)

    def get_character_voices(self, characters: list[str]) -> str:
        """Get voice notes for specific characters."""
        cast = self.concept_seed.get("ensemble_cast", [])
        voices = []
        for char in cast:
            if char["name"] in characters or any(
                name_part.lower() in char["name"].lower()
                for name_part in characters
            ):
                voices.append(
                    f"### {char['name']}\n"
                    f"**Role**: {char['role']}\n"
                    f"**Voice**: {char.get('voice_notes', '')}\n"
                    f"**Surface**: {char['three_dimensions']['surface']}\n"
                    f"**Under Pressure**: {char['three_dimensions']['action_under_pressure']}"
                )
        return "\n\n".join(voices)

    def get_previous_chapter(self, chapter_number: int) -> Optional[str]:
        """Load the previous chapter's text for context."""
        prev_chapter = chapter_number - 1
        if prev_chapter < 1:
            return None

        # Look for the chapter file
        pattern = f"chapter_{prev_chapter:02d}*.md"
        matches = list(self.manuscripts_dir.glob(pattern))
        if matches:
            return matches[0].read_text(encoding="utf-8")
        return None

    def assemble(self, scene_card: dict) -> str:
        """Assemble the full context for a scene generation call.

        Uses four-tier memory when Phase 2 dependencies are available,
        falls back to Phase 1 concatenation otherwise.
        """
        if self._phase2_enabled:
            return self._assemble_phase2(scene_card)
        return self._assemble_phase1(scene_card)

    def _assemble_phase1(self, scene_card: dict) -> str:
        """Phase 1: Simple concatenation (original behavior)."""
        components = []

        # Story bible essentials
        components.append(self.get_bible_summary())

        # Character voices for present characters
        characters_present = scene_card.get("characters_present", [])
        if characters_present:
            voices = self.get_character_voices(characters_present)
            if voices:
                components.append(f"## Character Voices\n{voices}")

        # Previous chapter context
        chapter_num = scene_card.get("chapter_number", 1)
        prev_chapter = self.get_previous_chapter(chapter_num)
        if prev_chapter:
            # Truncate to last ~3000 chars for Phase 1
            if len(prev_chapter) > 3000:
                prev_chapter = "...\n" + prev_chapter[-3000:]
            components.append(f"## Previous Chapter (ending)\n{prev_chapter}")

        # Scene card
        components.append(
            f"## Scene Card\n```json\n{json.dumps(scene_card, indent=2)}\n```"
        )

        # Negative constraints
        components.append(f"## Writing Constraints\n{self.negative_constraints}")

        return "\n\n".join(components)

    def _assemble_phase2(self, scene_card: dict) -> str:
        """Phase 2: Four-tier memory with token budgets."""
        components = []

        # Tier 1: Story bible essentials
        bible = self.get_bible_summary()
        components.append(
            _truncate_to_budget(bible, TOKEN_BUDGETS["bible_summary"])
        )

        # Tier 2: Act summary (from chapter memory if available)
        act_summary = self._get_act_summary(scene_card)
        if act_summary:
            components.append(
                f"## Current Act Summary\n"
                + _truncate_to_budget(act_summary, TOKEN_BUDGETS["act_summary"])
            )

        # Tier 3: Recent chapter summaries (ChromaDB)
        if self.chapter_memory:
            recent = self.chapter_memory.get_recent_summaries(n=3)
            if recent and "No previous" not in recent:
                components.append(
                    f"## Recent Chapters\n"
                    + _truncate_to_budget(
                        recent, TOKEN_BUDGETS["chapter_summaries"]
                    )
                )

        # Canon RAG results
        canon_context = self._get_canon_context(scene_card)
        if canon_context:
            components.append(
                f"## Canon Reference\n"
                + _truncate_to_budget(canon_context, TOKEN_BUDGETS["canon_rag"])
            )

        # Character voice sheets
        characters_present = scene_card.get("characters_present", [])
        if characters_present:
            voices = self.get_character_voices(characters_present)
            if voices:
                components.append(
                    f"## Character Voices\n"
                    + _truncate_to_budget(
                        voices, TOKEN_BUDGETS["character_voices"]
                    )
                )

        # Character knowledge state (belief layer)
        if self.knowledge_layers and characters_present:
            knowledge = self.knowledge_layers.get_beliefs_for_characters(
                characters_present
            )
            if knowledge and "No character beliefs" not in knowledge:
                components.append(
                    f"## Character Knowledge States\n"
                    + _truncate_to_budget(
                        knowledge, TOKEN_BUDGETS["character_knowledge"]
                    )
                )

        # Tier 4: Recent prose context
        chapter_num = scene_card.get("chapter_number", 1)
        prev_chapter = self.get_previous_chapter(chapter_num)
        if prev_chapter:
            budget_chars = int(TOKEN_BUDGETS["recent_prose"] / 0.75)
            if len(prev_chapter) > budget_chars:
                prev_chapter = "...\n" + prev_chapter[-budget_chars:]
            components.append(f"## Recent Prose\n{prev_chapter}")

        # Scene card
        scene_text = json.dumps(scene_card, indent=2)
        components.append(f"## Scene Card\n```json\n{scene_text}\n```")

        # Phase 5: Voice rules (anti-slop + anti-patterns)
        voice_rules = self._assemble_voice_rules()
        if voice_rules:
            components.append(
                _truncate_to_budget(voice_rules, TOKEN_BUDGETS["voice_rules"])
            )

        # Phase 5: Hook agenda
        if self.story_state:
            chapter_num = scene_card.get("chapter_number", 1)
            hook_agenda = self._assemble_hook_agenda(chapter_num)
            if hook_agenda:
                components.append(
                    _truncate_to_budget(hook_agenda, TOKEN_BUDGETS["hook_agenda"])
                )

        # Phase 5: Arc context for POV character
        if self.story_state:
            pov = scene_card.get("pov_character", "")
            arc_context = self._assemble_arc_context(pov)
            if arc_context:
                components.append(
                    _truncate_to_budget(arc_context, TOKEN_BUDGETS["arc_context"])
                )

        # Phase 5: Active subplots
        if self.story_state:
            subplot_context = self._assemble_subplot_context(scene_card)
            if subplot_context:
                components.append(
                    _truncate_to_budget(subplot_context, TOKEN_BUDGETS["subplot_context"])
                )

        # Phase 5: Terminology
        if self.story_state:
            term_context = self._assemble_terminology()
            if term_context:
                components.append(
                    _truncate_to_budget(term_context, TOKEN_BUDGETS["terminology"])
                )

        # Negative constraints
        components.append(f"## Writing Constraints\n{self.negative_constraints}")

        return "\n\n".join(components)

    # ------------------------------------------------------------------
    # Phase 5 context methods
    # ------------------------------------------------------------------

    def _assemble_voice_rules(self) -> str:
        """Extract voice definition from concept seed and format for injection."""
        voice_def = self.concept_seed.get("voice_definition")
        if not voice_def:
            return ""

        lines = ["## Voice Rules (MANDATORY)"]

        anti_slop = voice_def.get("anti_slop", {})
        banned_words = anti_slop.get("banned_words", [])
        if banned_words:
            lines.append("\n### Banned Words — Do NOT use these words:")
            lines.append(", ".join(banned_words))

        banned_phrases = anti_slop.get("banned_phrases", [])
        if banned_phrases:
            lines.append("\n### Banned Phrases — Do NOT use these phrases:")
            for phrase in banned_phrases:
                lines.append(f"- {phrase}")

        anti_patterns = voice_def.get("anti_patterns", [])
        if anti_patterns:
            lines.append("\n### Banned Structural Patterns:")
            for pattern in anti_patterns:
                lines.append(f"- {pattern}")

        if voice_def.get("narrative_voice_notes"):
            lines.append(f"\n### Narrative Voice:\n{voice_def['narrative_voice_notes']}")
        if voice_def.get("pov_approach"):
            lines.append(f"**POV**: {voice_def['pov_approach']}")
        if voice_def.get("prose_register"):
            lines.append(f"**Register**: {voice_def['prose_register']}")

        return "\n".join(lines)

    def _assemble_hook_agenda(self, chapter_number: int) -> str:
        """Query story state for the hook agenda for this chapter."""
        if not self.story_state:
            return ""
        try:
            agenda = self.story_state.get_chapter_hook_agenda(chapter_number)
        except Exception:
            return ""

        if not any(agenda.values()):
            return ""

        lines = ["## Hook Agenda for This Chapter"]
        if agenda["to_plant"]:
            lines.append("\n**Hooks to PLANT:**")
            for h in agenda["to_plant"]:
                lines.append(f"- [{h['hook_id']}] {h['description']} (priority: {h['priority']})")
        if agenda["to_advance"]:
            lines.append("\n**Hooks to ADVANCE (not just mention — real progress):**")
            for h in agenda["to_advance"]:
                lines.append(f"- [{h['hook_id']}] {h['description']}")
        if agenda["to_resolve"]:
            lines.append("\n**Hooks to RESOLVE:**")
            for h in agenda["to_resolve"]:
                lines.append(f"- [{h['hook_id']}] {h['description']}")

        return "\n".join(lines)

    def _assemble_arc_context(self, pov_character: str) -> str:
        """Get the POV character's Weiland arc state."""
        if not self.story_state or not pov_character:
            return ""

        from src.memory.story_state import _slugify
        char_id = _slugify(pov_character)
        try:
            arc = self.story_state.get_character_arc(char_id)
        except Exception:
            return ""

        if not arc:
            return ""

        lines = [
            f"## POV Character Arc — {pov_character}",
            f"**Lie Believed**: {arc.get('lie_believed', 'N/A')}",
            f"**Want**: {arc.get('want', 'N/A')}",
            f"**Need (Truth)**: {arc.get('need', 'N/A')}",
            f"**Arc Type**: {arc.get('arc_type', 'N/A')}",
            f"**Current Phase**: {arc.get('current_phase', 'N/A')}",
        ]

        targets = arc.get("arc_phase_targets")
        if targets:
            lines.append(f"**Phase Targets**: {json.dumps(targets)}")

        return "\n".join(lines)

    def _assemble_subplot_context(self, scene_card: dict) -> str:
        """Get active subplots relevant to this scene."""
        if not self.story_state:
            return ""

        try:
            active = self.story_state.get_active_subplots()
        except Exception:
            return ""

        if not active:
            return ""

        # Filter to subplots referenced by scene card, or show all active if none specified
        referenced = set(scene_card.get("active_subplots", []))
        if referenced:
            active = [s for s in active if s["subplot_id"] in referenced]

        lines = ["## Active Subplots"]
        for sub in active[:5]:  # Limit to top 5
            lines.append(
                f"- **{sub['subplot_name']}** [{sub['line_type']}-line] — "
                f"{sub.get('structural_purpose', '')} (status: {sub['current_status']})"
            )

        return "\n".join(lines)

    def _assemble_terminology(self) -> str:
        """Format terminology registry for context injection."""
        if not self.story_state:
            return ""

        try:
            terms = self.story_state.get_all_terms()
        except Exception:
            return ""

        if not terms:
            return ""

        lines = ["## Terminology Registry — Use EXACT spellings:"]
        for t in terms[:20]:  # Limit to 20 most relevant
            aliases = t.get("aliases", [])
            alias_str = f" (also: {', '.join(aliases)})" if aliases else ""
            lines.append(f"- **{t['term']}**{alias_str}: {t.get('definition', '')}")

        return "\n".join(lines)

    def _get_act_summary(self, scene_card: dict) -> str:
        """Get a summary of the current act from chapter memory."""
        if not self.chapter_memory:
            return ""

        # Search chapter memory for summaries relevant to the current structural phase
        phase = scene_card.get("structural_phase", "setup")
        results = self.chapter_memory.search_summaries(
            f"structural phase {phase}", k=2
        )
        if results:
            return "\n".join(r["summary"] for r in results)
        return ""

    def _get_canon_context(self, scene_card: dict) -> str:
        """Retrieve relevant canon evidence for the scene."""
        if not self.canon_db:
            return ""

        canon_elements = scene_card.get("canon_elements_needed", [])
        if not canon_elements:
            return ""

        all_results = []
        for element in canon_elements:
            results = self.canon_db.search(element, k=2)
            all_results.extend(results)

        if not all_results:
            return "No canon matches found."

        # Format results with metadata
        lines = []
        seen = set()
        for r in sorted(all_results, key=lambda x: x.get("distance", 1)):
            rid = r.get("id", "")
            if rid in seen:
                continue
            seen.add(rid)
            meta = r.get("metadata", {})
            source_class = meta.get("source_class", "unknown")
            lines.append(f"[{source_class}] {r.get('text', '')[:300]}")

        return "\n".join(lines[:10])

    def get_negative_constraints(self) -> str:
        """Return the negative constraints text."""
        return self.negative_constraints


def _truncate_to_budget(text: str, max_tokens: int) -> str:
    """Truncate text to fit within a token budget.

    Uses word-count approximation: 1 token ~ 0.75 words.
    """
    max_words = int(max_tokens * 0.75)
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "\n[...truncated]"
