"""Three-layer knowledge state system.

Operates on the character_knowledge table in StoryState:
- Truth layer: What is objectively true in the story world
- Belief layer: What each character believes (may differ from truth)
- Narrative Exposure layer: What the reader has been shown

Drives dramatic irony — the reader may know things characters don't.
"""

from src.memory.story_state import StoryState

# Sentinel character_id for truth-layer entries (world-level facts)
TRUTH_ENTITY = "__world__"


class KnowledgeLayers:
    """Three-layer knowledge state system operating on StoryState."""

    def __init__(self, story_state: StoryState):
        self.state = story_state

    # === Truth Layer ===

    def add_truth(self, fact_id: str, description: str, chapter: int) -> None:
        """Add an objective fact to the truth layer."""
        self.state.add_knowledge(
            character_id=TRUTH_ENTITY,
            fact_id=fact_id,
            fact_description=description,
            layer="truth",
            is_accurate=True,
            acquired_chapter=chapter,
            source="world_state",
        )

    def get_truths(self) -> list[dict]:
        """Get all truth-layer facts."""
        return self.state.get_knowledge(character_id=TRUTH_ENTITY, layer="truth")

    def get_truth(self, fact_id: str) -> dict | None:
        """Get a specific truth-layer fact."""
        results = self.state.get_knowledge(
            character_id=TRUTH_ENTITY, layer="truth", fact_id=fact_id
        )
        return results[0] if results else None

    # === Belief Layer ===

    def add_belief(
        self,
        character_id: str,
        fact_id: str,
        description: str,
        is_accurate: bool,
        chapter: int,
        source: str,
    ) -> None:
        """Add a character belief.

        Args:
            character_id: Slug ID of the character.
            fact_id: Unique identifier for the fact.
            description: What the character believes.
            is_accurate: Whether this matches the truth layer.
            chapter: When they acquired this belief.
            source: How they learned it (witnessed/told/inferred/false).
        """
        self.state.add_knowledge(
            character_id=character_id,
            fact_id=fact_id,
            fact_description=description,
            layer="belief",
            is_accurate=is_accurate,
            acquired_chapter=chapter,
            source=source,
        )

    def get_beliefs(self, character_id: str) -> list[dict]:
        """Get all beliefs for a character."""
        return self.state.get_knowledge(character_id=character_id, layer="belief")

    # === Narrative Exposure Layer ===

    def add_exposure(
        self, character_id: str, fact_id: str, description: str, chapter: int
    ) -> None:
        """Record what the reader has been shown about a character's knowledge."""
        self.state.add_knowledge(
            character_id=character_id,
            fact_id=fact_id,
            fact_description=description,
            layer="narrative_exposure",
            acquired_chapter=chapter,
            source="narration",
        )

    def get_exposures(self, character_id: str) -> list[dict]:
        """Get all narrative exposures for a character."""
        return self.state.get_knowledge(
            character_id=character_id, layer="narrative_exposure"
        )

    # === Query Methods ===

    def get_beliefs_for_characters(self, character_ids: list[str]) -> str:
        """Format all beliefs for the given characters into a context string.

        This gets injected into the assembled context for the prose stylist,
        so the LLM knows what each character believes during the scene.
        """
        sections = []
        for char_id in character_ids:
            # Normalize: try slug form
            slug = char_id.lower().replace(" ", "_").replace("-", "_")
            beliefs = self.state.get_knowledge(character_id=slug, layer="belief")
            if not beliefs:
                # Try original form
                beliefs = self.state.get_knowledge(
                    character_id=char_id, layer="belief"
                )
            if beliefs:
                lines = [f"### {char_id}"]
                for b in beliefs:
                    accuracy = "accurate" if b.get("is_accurate") else "inaccurate"
                    lines.append(
                        f"- [{accuracy}] {b['fact_description']} "
                        f"(source: {b.get('source', 'unknown')})"
                    )
                sections.append("\n".join(lines))

        return "\n\n".join(sections) if sections else "No character beliefs recorded."

    def check_belief_accuracy(self, character_id: str, fact_id: str) -> bool | None:
        """Check if a character's belief matches the truth layer.

        Returns True if accurate, False if inaccurate, None if no matching belief.
        """
        beliefs = self.state.get_knowledge(
            character_id=character_id, layer="belief", fact_id=fact_id
        )
        if not beliefs:
            return None
        val = beliefs[0].get("is_accurate")
        if val is None:
            return None
        return bool(val)

    def get_dramatic_irony(self, chapter: int) -> list[dict]:
        """Find facts where reader exposure differs from character beliefs.

        Returns cases where the reader knows something a character doesn't,
        or where a character believes something the reader knows is false.
        """
        ironies = []

        # Get all truths
        truths = {t["fact_id"]: t for t in self.get_truths()}

        # Get all exposures (what the reader has been shown)
        all_knowledge = self.state.get_knowledge(layer="narrative_exposure")
        exposures_by_char = {}
        for k in all_knowledge:
            if k.get("acquired_chapter", 0) <= chapter:
                char = k["character_id"]
                exposures_by_char.setdefault(char, set()).add(k["fact_id"])

        # Get all beliefs
        all_beliefs = self.state.get_knowledge(layer="belief")
        beliefs_by_char = {}
        for b in all_beliefs:
            if b.get("acquired_chapter", 0) <= chapter:
                char = b["character_id"]
                beliefs_by_char.setdefault(char, {})[b["fact_id"]] = b

        # Find irony: reader knows truth, character has inaccurate belief
        for char_id, char_beliefs in beliefs_by_char.items():
            for fact_id, belief in char_beliefs.items():
                if not belief.get("is_accurate", True):
                    # Character has a false belief
                    # Check if the reader has been exposed to the truth
                    reader_exposed = fact_id in exposures_by_char.get(char_id, set())
                    truth = truths.get(fact_id)
                    if truth:
                        ironies.append(
                            {
                                "character_id": char_id,
                                "fact_id": fact_id,
                                "character_believes": belief["fact_description"],
                                "truth": truth["fact_description"],
                                "reader_knows_truth": reader_exposed,
                                "irony_type": (
                                    "dramatic_irony"
                                    if reader_exposed
                                    else "hidden_irony"
                                ),
                            }
                        )

        return ironies
