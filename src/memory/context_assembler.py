"""Context Assembler — builds per-scene prompt payloads.

Phase 1: Simple concatenation of story bible, scene card, and previous chapter text.
Phase 2: Full four-tier memory system with ChromaDB, SQLite, knowledge layers, and canon RAG.

When Phase 2 dependencies are not provided (None), falls back to Phase 1 behavior.
"""

import json
import logging
from pathlib import Path
from typing import Optional, TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from src.memory.chapter_memory import ChapterMemory
    from src.memory.knowledge_layers import KnowledgeLayers
    from src.memory.story_state import StoryState
    from src.rag.canon_db import CanonDB
    from src.worldbuilding.lore_service import LoreService


# Token budget per tier (approximate: 1 token ~ 0.75 words)
TOKEN_BUDGETS = {
    "bible_summary": 2000,
    "act_summary": 500,
    "chapter_summaries": 1200,
    "canon_rag": 1000,
    "character_voices": 1000,
    "character_knowledge": 500,
    "recent_prose": 8000,
    "scene_card": 500,
    "negative_constraints": 400,
    # Phase 5 tiers
    "voice_rules": 300,
    "hook_agenda": 400,
    "arc_context": 300,
    "subplot_context": 300,
    "terminology": 200,
    # Worldbuilding tiers
    "worldbuilding_lore": 800,
    "worldbuilding_terminology": 300,
    "worldbuilding_dialogue": 300,
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
        manuscripts_dir: str = "output/_fallback/manuscripts",
        # Phase 2 optional dependencies:
        story_state: Optional["StoryState"] = None,
        knowledge_layers: Optional["KnowledgeLayers"] = None,
        chapter_memory: Optional["ChapterMemory"] = None,
        canon_db: Optional["CanonDB"] = None,
        # Worldbuilding dependency:
        lore_service: Optional["LoreService"] = None,
        universe_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ):
        self.concept_seed = self._load_json(concept_seed_path)
        self.negative_constraints = self._load_constraints(negative_constraints_path)
        self.manuscripts_dir = Path(manuscripts_dir)

        # Phase 2 dependencies (None = Phase 1 fallback)
        self.story_state = story_state
        self.knowledge_layers = knowledge_layers
        self.chapter_memory = chapter_memory
        self.canon_db = canon_db

        # Worldbuilding dependencies (None = skip worldbuilding tier)
        self.lore_service = lore_service
        self.universe_id = universe_id
        self.project_id = project_id

    @property
    def _phase2_enabled(self) -> bool:
        """Check if any Phase 2 dependencies are available."""
        return any([
            self.story_state,
            self.knowledge_layers,
            self.chapter_memory,
            self.canon_db,
            self.lore_service,
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

    def get_pov_approach(self) -> str:
        """Return the narrative POV declared in voice_definition, or a sensible default.

        Default is "third-person limited" because that is the register the prior
        scene_cards were planned against. Projects configured for other POVs
        (first-person, rotating limited, deep POV, omniscient) surface whatever
        they declared in concept_seed.voice_definition.pov_approach.
        """
        voice_def = self.concept_seed.get("voice_definition") or {}
        return voice_def.get("pov_approach") or "third-person limited"

    def get_franchise_profile_text(self) -> str:
        """Load the franchise-profile markdown file declared in concept_seed.meta.franchise_profile.

        Returns empty string when no profile is declared (original-fiction
        projects, or projects that predate the franchise-profile system).
        The loaded text is injected as a second system message by BaseAgent.
        """
        meta = self.concept_seed.get("meta") or {}
        slug = meta.get("franchise_profile")
        if not slug:
            return ""
        profile_path = Path(f"prompts/franchise_profiles/{slug}.md")
        if not profile_path.exists():
            return ""
        return profile_path.read_text(encoding="utf-8")

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
        """Load the previous chapter's text for context.

        .. deprecated:: Use :meth:`get_previous_scene` instead.
        """
        import warnings
        warnings.warn(
            "get_previous_chapter is deprecated. Use get_previous_scene instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_previous_scene(chapter_number, 1)

    def get_previous_scene(self, chapter_number: int, scene_number: int) -> Optional[str]:
        """Get the prose from the immediately preceding scene.

        Within-chapter: ch N scene (M-1).
        Cross-chapter: last scene file of chapter (N-1).
        """
        if scene_number > 1:
            path = self.manuscripts_dir / f"chapter_{chapter_number:02d}_scene_{scene_number - 1:02d}.md"
            if path.exists():
                return path.read_text(encoding="utf-8")
            return None

        if chapter_number <= 1:
            return None

        # First scene of a new chapter: find the LAST scene of the previous chapter
        prev_chapter = chapter_number - 1
        pattern = f"chapter_{prev_chapter:02d}_scene_*.md"
        matches = sorted(self.manuscripts_dir.glob(pattern))
        if matches:
            return matches[-1].read_text(encoding="utf-8")
        return None

    def _load_prior_scenes(self, chapter_number: int, scene_number: int, n: int = 3) -> list[str]:
        """Load the last N scene files before the current (chapter, scene)."""
        all_files = sorted(self.manuscripts_dir.glob("chapter_*_scene_*.md"))

        current_key = (chapter_number, scene_number)
        prior_files = []
        for f in all_files:
            parts = f.stem.split("_")  # chapter_01_scene_02 -> ["chapter", "01", "scene", "02"]
            try:
                ch = int(parts[1])
                sc = int(parts[3])
            except (IndexError, ValueError):
                continue
            if (ch, sc) < current_key:
                prior_files.append(f)

        recent = prior_files[-n:]
        return [f.read_text(encoding="utf-8") for f in recent]

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

        # Previous scene context
        chapter_num = scene_card.get("chapter_number", 1)
        scene_num = scene_card.get("scene_number", 1)
        prev_prose = self.get_previous_scene(chapter_num, scene_num)
        if prev_prose:
            budget_chars = int(TOKEN_BUDGETS["recent_prose"] / 0.75)
            if len(prev_prose) > budget_chars:
                prev_prose = "...\n" + prev_prose[-budget_chars:]
            components.append(f"## Previous Scene (ending)\n{prev_prose}")

        # Scene card
        components.append(
            f"## Scene Card\n```json\n{json.dumps(scene_card, indent=2)}\n```"
        )

        # Voice rules (reads from concept_seed only — no Phase 2 dependencies)
        voice_rules = self._assemble_voice_rules()
        if voice_rules:
            components.append(
                _truncate_to_budget(voice_rules, TOKEN_BUDGETS["voice_rules"])
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

            # Tier 3b: Established concepts from recent summaries
            concepts_text = self._get_established_concepts()
            if concepts_text:
                components.append(concepts_text)

        # Canon RAG results (with worldbuilding override resolution)
        canon_context = self._get_canon_context(scene_card)
        if canon_context:
            components.append(
                f"## Canon Reference\n"
                + _truncate_to_budget(canon_context, TOKEN_BUDGETS["canon_rag"])
            )

        # Worldbuilding lore (semantic retrieval from universe chain)
        if self.lore_service and self.universe_id:
            wb_lore = self._assemble_worldbuilding_lore(scene_card)
            if wb_lore:
                components.append(
                    f"## Worldbuilding Lore\n"
                    + _truncate_to_budget(
                        wb_lore, TOKEN_BUDGETS["worldbuilding_lore"]
                    )
                )

        # Worldbuilding terminology glossary (always-include)
        if self.lore_service and self.universe_id:
            wb_terms = self._assemble_worldbuilding_terminology()
            if wb_terms:
                components.append(
                    _truncate_to_budget(
                        wb_terms, TOKEN_BUDGETS["worldbuilding_terminology"]
                    )
                )

        # Worldbuilding dialogue context (speech patterns)
        if self.lore_service and self.universe_id:
            wb_dialogue = self._assemble_worldbuilding_dialogue(
                scene_card.get("characters_present", [])
            )
            if wb_dialogue:
                components.append(
                    _truncate_to_budget(
                        wb_dialogue, TOKEN_BUDGETS["worldbuilding_dialogue"]
                    )
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
        scene_num = scene_card.get("scene_number", 1)
        prev_prose = self.get_previous_scene(chapter_num, scene_num)
        if prev_prose:
            budget_chars = int(TOKEN_BUDGETS["recent_prose"] / 0.75)
            if len(prev_prose) > budget_chars:
                prev_prose = "...\n" + prev_prose[-budget_chars:]
            components.append(f"## Recent Prose\n{prev_prose}")

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
        """Extract voice definition from concept seed and format for injection.

        Accepts both the legacy nested structure
        (voice_definition.anti_slop.{banned_words, banned_phrases}) and
        the post-Phase-5 flat structure (voice_definition.anti_slop_rules),
        plus the new fields: character_voices, force_description_guidelines,
        and reference_authors as objects.
        """
        voice_def = self.concept_seed.get("voice_definition")
        if not voice_def:
            return ""

        lines = ["## Voice Rules (MANDATORY)"]

        # New flat anti_slop_rules (post-Phase-5)
        anti_slop_rules = voice_def.get("anti_slop_rules")
        if anti_slop_rules:
            lines.append("\n### Anti-Slop Rules — Do NOT violate these rules:")
            for rule in anti_slop_rules:
                lines.append(f"- {rule}")
        else:
            # Legacy nested anti_slop (banned_words + banned_phrases)
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

        # Per-character voice guidance (post-Phase-5)
        character_voices = voice_def.get("character_voices", {})
        if character_voices:
            lines.append("\n### Character Voices — how each character speaks and thinks:")
            for char_name, guidance in character_voices.items():
                lines.append(f"- **{char_name}**: {guidance}")

        # Force / magic description guidelines (post-Phase-5, optional)
        force_guide = voice_def.get("force_description_guidelines", "")
        if force_guide:
            lines.append("\n### Magic / Force Description Guidelines:")
            lines.append(force_guide)

        # Reference authors (legacy = list of strings; post-Phase-5 = list of objects)
        ref_authors = voice_def.get("reference_authors", [])
        if ref_authors:
            lines.append("\n### Reference Authors:")
            for entry in ref_authors:
                if isinstance(entry, dict):
                    author = entry.get("author", "unknown")
                    emulate = entry.get("what_to_emulate", "")
                    avoid = entry.get("what_to_avoid", "")
                    lines.append(f"- **{author}**")
                    if emulate:
                        lines.append(f"  - Emulate: {emulate}")
                    if avoid:
                        lines.append(f"  - Avoid: {avoid}")
                else:
                    lines.append(f"- {entry}")

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
        except Exception as e:
            logger.warning(
                "context_assembler._assemble_hook_agenda failed (chapter=%s): %s",
                chapter_number, e,
            )
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
        except Exception as e:
            logger.warning(
                "context_assembler._assemble_arc_context failed (char=%s): %s",
                char_id, e,
            )
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
        except Exception as e:
            logger.warning(
                "context_assembler._assemble_subplot_context failed: %s", e
            )
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
        except Exception as e:
            logger.warning(
                "context_assembler._assemble_terminology failed: %s", e
            )
            return ""

        if not terms:
            return ""

        lines = ["## Terminology Registry — Use EXACT spellings:"]
        for t in terms[:20]:  # Limit to 20 most relevant
            aliases = t.get("aliases", [])
            alias_str = f" (also: {', '.join(aliases)})" if aliases else ""
            lines.append(f"- **{t['term']}**{alias_str}: {t.get('definition', '')}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Worldbuilding context methods
    # ------------------------------------------------------------------

    def _assemble_worldbuilding_lore(self, scene_card: dict) -> str:
        """Retrieve relevant worldbuilding lore for this scene."""
        if not self.lore_service or not self.universe_id:
            return ""

        # Build query from scene card context
        query_parts = []
        if scene_card.get("location"):
            query_parts.append(scene_card["location"])
        if scene_card.get("title"):
            query_parts.append(scene_card["title"])
        characters = scene_card.get("characters_present", [])
        if characters:
            query_parts.extend(characters[:3])
        if scene_card.get("task"):
            query_parts.append(scene_card["task"])

        if not query_parts:
            return ""

        query_text = " ".join(query_parts)

        try:
            # Get project reading order for spoiler isolation
            project_reading_order = None
            if self.project_id:
                project_reading_order = self.lore_service.db.get_project_reading_order(
                    self.project_id
                )

            results = self.lore_service.get_lore_for_context(
                universe_id=self.universe_id,
                query_text=query_text,
                top_k=5,
                project_reading_order=project_reading_order,
            )
        except Exception as e:
            logger.warning(
                "context_assembler._assemble_worldbuilding_lore failed (universe=%s): %s",
                self.universe_id, e,
            )
            return ""

        if not results:
            return ""

        lines = []
        for r in results:
            meta = r.get("metadata", {})
            title = meta.get("title", "Unknown")
            category = meta.get("category", "")
            status = meta.get("status", "")
            text = r.get("text", "")[:400]

            status_tag = ""
            if status == "provisional":
                status_tag = " [PROVISIONAL — not yet author-confirmed]"

            lines.append(f"### {title} ({category}){status_tag}\n{text}")

        return "\n\n".join(lines)

    def _assemble_worldbuilding_terminology(self) -> str:
        """Get worldbuilding terminology glossary (always-include)."""
        if not self.lore_service or not self.universe_id:
            return ""

        try:
            terms = self.lore_service.get_terminology(self.universe_id)
        except Exception as e:
            logger.warning(
                "context_assembler._assemble_worldbuilding_terminology failed (universe=%s): %s",
                self.universe_id, e,
            )
            return ""

        if not terms:
            return ""

        lines = ["## Worldbuilding Terminology — Use EXACT terms:"]
        for t in terms:
            tags = t.get("tags", [])
            tag_str = f" [{', '.join(tags)}]" if tags and isinstance(tags, list) else ""
            lines.append(f"- **{t['title']}**{tag_str}: {t['content'][:200]}")

        return "\n".join(lines)

    def _assemble_worldbuilding_dialogue(self, characters_present: list[str]) -> str:
        """Get knowledge-gated speech patterns and dialogue implications."""
        if not self.lore_service or not self.universe_id:
            return ""

        try:
            context = self.lore_service.get_dialogue_context(
                self.universe_id,
                character_ids=characters_present or None,
                knowledge_layers=self.knowledge_layers,
            )
        except Exception as e:
            logger.warning(
                "context_assembler._assemble_worldbuilding_dialogue failed (universe=%s): %s",
                self.universe_id, e,
            )
            return ""

        speech = context.get("speech_patterns", [])
        implications = context.get("dialogue_implications", [])

        if not speech and not implications:
            return ""

        lines = ["## Worldbuilding Dialogue Context"]

        if speech:
            lines.append("\n### Speech Patterns:")
            for s in speech:
                lines.append(
                    f"- **{s['title']}** ({s['category']}): {s['speech_patterns']}"
                )

        if implications:
            lines.append("\n### Inter-Faction Dialogue Dynamics:")
            for imp in implications:
                lines.append(
                    f"- {imp.get('source_entry_id', '?')} ↔ {imp.get('target_entry_id', '?')} "
                    f"({imp.get('relation_type', '?')}): {imp.get('dialogue_implications', '')}"
                )

        return "\n".join(lines)

    def _get_established_concepts(self) -> str:
        """Extract established concepts from recent summary metadata.

        Merges concepts across recent scenes, advancing maturity for
        concepts that appear multiple times. Returns formatted context
        text or empty string if no concepts found.
        """
        if not self.chapter_memory:
            return ""

        result = self.chapter_memory.collection.get(
            include=["metadatas"],
        )
        if not result["ids"]:
            return ""

        # Collect all concepts from recent summaries (keyed by concept_id)
        merged: dict[str, dict] = {}
        for meta in result["metadatas"]:
            raw = meta.get("established_concepts", "")
            if not raw:
                continue
            try:
                concepts = json.loads(raw)
            except (ValueError, TypeError):
                continue
            for c in concepts:
                cid = c.get("concept_id", "")
                if not cid:
                    continue
                if cid in merged:
                    # Merge: advance maturity and extend scenes_present
                    existing = merged[cid]
                    new_scenes = c.get("scenes_present", [])
                    for s in new_scenes:
                        if s not in existing.get("scenes_present", []):
                            existing.setdefault("scenes_present", []).append(s)
                    # Keep the higher maturity and latest guidance
                    maturity_order = ["introduced", "developing", "established", "evolved"]
                    old_idx = maturity_order.index(existing.get("maturity", "introduced")) if existing.get("maturity") in maturity_order else 0
                    new_idx = maturity_order.index(c.get("maturity", "introduced")) if c.get("maturity") in maturity_order else 0
                    if new_idx > old_idx:
                        existing["maturity"] = c["maturity"]
                    existing["guidance_for_next"] = c.get("guidance_for_next", existing.get("guidance_for_next", ""))
                else:
                    merged[cid] = dict(c)

        if not merged:
            if len(result["ids"]) > 0:
                logger.info(
                    "Context assembler: %d summaries in memory but none contain "
                    "established_concepts — concept maturity tracking not active",
                    len(result["ids"]),
                )
            return ""

        logger.info("Context assembler: injecting %d established concepts into context", len(merged))
        lines = ["## Established Concepts (Do Not Restate)"]
        lines.append("These concepts have already been introduced to the reader. Do NOT re-explain them from scratch.")
        lines.append("")
        for c in merged.values():
            scenes = ", ".join(c.get("scenes_present", []))
            lines.append(f"- **{c.get('label', c.get('concept_id', '?'))}** [{c.get('maturity', '?')}] (scenes: {scenes})")
            guidance = c.get("guidance_for_next", "")
            if guidance:
                lines.append(f"  → {guidance}")

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
