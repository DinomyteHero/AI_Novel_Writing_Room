"""Post-chapter consistency check.

Runs after each approved chapter to detect contradictions against
the story state database. Non-blocking — logs warnings but does
not reject chapters.

Investigation notes (Phase 4 diagnostic):
- The scanner returned "clean" across 25 scenes and 8 chapters.
- This is NOT a stub — it has 5 real scanning dimensions.
- Reasons for zero detections in a short run:
  1. Truth layer: 200-char window around character names is too narrow for
     detecting location contradictions in literary prose. Consider widening
     to 500+ chars or using paragraph-level context.
  2. Belief layer: Depends on knowledge_layers having recorded beliefs.
     If the state diff doesn't populate beliefs, nothing fires.
  3. Promises: 10-chapter threshold means an 8-chapter run can't trigger it.
     Consider making the threshold configurable.
  4. Timeline: Requires story_date data in the timeline table. If the
     summarizer doesn't extract dates, this scan is inert.
  5. Relationships: 5-chapter staleness threshold is reasonable but won't
     fire until chapters 6+.
- TODO: Consider an LLM-powered contradiction check that receives the
  current scene prose + last 2-3 scene summaries from ChromaDB and checks
  for character state, object continuity, and timeline contradictions.
  This would catch semantic contradictions that heuristic pattern-matching
  misses. Run on a fast/cheap model.
"""

import re

from src.memory.knowledge_layers import KnowledgeLayers
from src.memory.story_state import StoryState
from src.run_ledger import RunLedger


class ContradictionScanner:
    """Post-chapter consistency scanner.

    Checks chapter prose against the story state database for:
    1. Truth layer contradictions
    2. Belief layer inconsistencies
    3. Promise/payoff violations
    4. Timeline inconsistencies
    5. Unexplained relationship shifts
    """

    def __init__(
        self,
        story_state: StoryState,
        knowledge_layers: KnowledgeLayers,
        ledger: RunLedger,
    ):
        self.state = story_state
        self.knowledge = knowledge_layers
        self.ledger = ledger

    def scan(
        self, chapter_number: int, prose: str, scene_card: dict,
        scene_number: int = 1,
    ) -> list[dict]:
        """Run all scans and return combined contradiction flags.

        Each flag: {type, severity, description, location}
        """
        flags = []
        flags.extend(self._scan_truth_layer(chapter_number, prose))
        flags.extend(self._scan_belief_layer(chapter_number, scene_card))
        flags.extend(self._scan_promises(chapter_number))
        flags.extend(self._scan_timeline(chapter_number))
        flags.extend(self._scan_relationships(chapter_number, scene_card))

        # Log all flags to the run ledger
        if flags:
            self.log_flags(flags, chapter_number, scene_number)

        return flags

    def _scan_truth_layer(self, chapter_number: int, prose: str) -> list[dict]:
        """Check factual assertions against the truth layer.

        Looks for character locations and states mentioned in prose that
        contradict the truth layer in the story state DB.
        """
        flags = []
        prose_lower = prose.lower()

        # Check character locations — if a character is mentioned as being
        # somewhere that contradicts their recorded location
        characters = self.state.get_all_characters()
        for char in characters:
            char_name = char["name"].lower()
            if char_name not in prose_lower:
                continue

            current_location = char.get("current_location")
            if not current_location:
                continue

            # Look for location mentions near the character's name
            # This is a heuristic — not perfect, but catches obvious cases
            for match in re.finditer(re.escape(char_name), prose_lower):
                start = max(0, match.start() - 200)
                end = min(len(prose_lower), match.end() + 200)
                context = prose_lower[start:end]

                # Check if a different location is mentioned near the character
                # without them traveling
                if current_location.lower() not in context:
                    # Only flag if another known location is explicitly mentioned
                    other_chars_locations = [
                        c.get("current_location", "").lower()
                        for c in characters
                        if c["id"] != char["id"] and c.get("current_location")
                    ]
                    for other_loc in other_chars_locations:
                        if other_loc and other_loc in context and other_loc != current_location.lower():
                            flags.append(
                                {
                                    "type": "truth_contradiction",
                                    "severity": "warning",
                                    "description": (
                                        f"{char['name']} appears near location '{other_loc}' "
                                        f"but their recorded location is '{current_location}'"
                                    ),
                                    "location": f"near '{char_name}' mention",
                                }
                            )

        return flags

    def _scan_belief_layer(
        self, chapter_number: int, scene_card: dict
    ) -> list[dict]:
        """Verify character actions are consistent with their belief state.

        Checks that characters present in the scene don't act on knowledge
        they shouldn't have.
        """
        flags = []
        characters_present = scene_card.get("characters_present", [])

        for char_name in characters_present:
            slug = char_name.lower().replace(" ", "_").replace("-", "_")
            beliefs = self.knowledge.get_beliefs(slug)

            # Check for inaccurate beliefs that haven't been corrected
            for belief in beliefs:
                if (
                    not belief.get("is_accurate", True)
                    and belief.get("acquired_chapter", 0) < chapter_number
                ):
                    # Character has a known false belief — flag for reviewer attention
                    flags.append(
                        {
                            "type": "belief_inconsistency",
                            "severity": "warning",
                            "description": (
                                f"{char_name} holds inaccurate belief: "
                                f"'{belief['fact_description']}' "
                                f"(acquired ch.{belief.get('acquired_chapter')}). "
                                f"Verify their actions in this scene are consistent."
                            ),
                            "location": f"chapter {chapter_number}",
                        }
                    )

        return flags

    def _scan_promises(self, chapter_number: int) -> list[dict]:
        """Cross-reference against the promise/payoff ledger.

        Flag Chekhov guns that have been unfired for too long.
        """
        flags = []

        unfired = self.state.get_unfired_guns()
        for gun in unfired:
            planted = gun.get("planted_chapter", 0)
            chapters_since = chapter_number - planted

            # Flag guns unfired after 10+ chapters
            if chapters_since >= 10:
                flags.append(
                    {
                        "type": "promise_overdue",
                        "severity": "warning",
                        "description": (
                            f"Chekhov's gun '{gun['item_description']}' planted in "
                            f"chapter {planted} still unfired after {chapters_since} chapters"
                        ),
                        "location": f"planted chapter {planted}",
                    }
                )

        return flags

    def _scan_timeline(self, chapter_number: int) -> list[dict]:
        """Check event sequencing against the timeline table."""
        flags = []

        timeline = self.state.get_timeline(chapter_number=chapter_number)
        if len(timeline) < 2:
            return flags

        # Check for temporal ordering issues
        prev_entry = None
        for entry in sorted(timeline, key=lambda x: (x.get("chapter_number", 0), x.get("scene_number", 0))):
            if prev_entry and entry.get("story_date") and prev_entry.get("story_date"):
                if entry["story_date"] < prev_entry["story_date"]:
                    flags.append(
                        {
                            "type": "timeline_inconsistency",
                            "severity": "warning",
                            "description": (
                                f"Timeline regression: ch.{entry.get('chapter_number')} "
                                f"date '{entry['story_date']}' is before "
                                f"ch.{prev_entry.get('chapter_number')} "
                                f"date '{prev_entry['story_date']}'"
                            ),
                            "location": f"chapter {chapter_number}",
                        }
                    )
            prev_entry = entry

        return flags

    def _scan_relationships(
        self, chapter_number: int, scene_card: dict
    ) -> list[dict]:
        """Flag unexplained shifts in character relationships."""
        flags = []

        characters_present = scene_card.get("characters_present", [])
        if len(characters_present) < 2:
            return flags

        # Check relationships between characters present in the scene
        for i, char_a_name in enumerate(characters_present):
            slug_a = char_a_name.lower().replace(" ", "_").replace("-", "_")
            for char_b_name in characters_present[i + 1 :]:
                slug_b = char_b_name.lower().replace(" ", "_").replace("-", "_")

                rels = self.state.get_relationships(slug_a)
                for rel in rels:
                    other = (
                        rel["character_b"]
                        if rel["character_a"] == slug_a
                        else rel["character_a"]
                    )
                    if other != slug_b:
                        continue

                    last_updated = rel.get("last_updated_chapter", 0)
                    chapters_since = chapter_number - last_updated

                    # Flag relationships not updated in 5+ chapters between
                    # characters who are present together
                    if chapters_since >= 5 and last_updated > 0:
                        flags.append(
                            {
                                "type": "relationship_stale",
                                "severity": "warning",
                                "description": (
                                    f"Relationship between {char_a_name} and {char_b_name} "
                                    f"({rel.get('relationship_type', 'unknown')}: "
                                    f"'{rel.get('status', '')}') hasn't been updated "
                                    f"since chapter {last_updated}. They are both present "
                                    f"in this scene."
                                ),
                                "location": f"chapter {chapter_number}",
                            }
                        )

        return flags

    def log_flags(self, flags: list[dict], chapter_number: int, scene_number: int = 1) -> None:
        """Emit contradiction flags to the run ledger."""
        self.ledger.emit(
            "contradiction_scan",
            chapter_number=chapter_number,
            payload={"scene_number": scene_number,
                "flag_count": len(flags),
                "flags": flags,
                "blocking_count": sum(
                    1 for f in flags if f["severity"] == "blocking"
                ),
                "warning_count": sum(
                    1 for f in flags if f["severity"] == "warning"
                ),
            },
        )
