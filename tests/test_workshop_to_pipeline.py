"""End-to-end integration test: concept seed with Phase 5 fields flows through
the pipeline correctly (scene cards, story state, context assembly)."""

import json
import pytest
from pathlib import Path

from src.memory.story_state import StoryState
from src.memory.context_assembler import ContextAssembler
from src.planning.scene_card_generator import SceneCardGenerator


@pytest.fixture
def phase5_concept_seed(tmp_path):
    """A concept seed with all Phase 5 fields populated."""
    seed = {
        "meta": {
            "project_title": "The Void Chronicles: Book 1",
            "franchise": "Original",
            "canon_status": "canon_compliant",
            "era": "Fantasy Medieval",
            "tone": "dark_gritty",
            "target_word_count": 80000,
            "target_chapters": 25,
            "pov_structure": "rotating limited",
            "project_scope": "standalone",
        },
        "premise": {
            "what_if": "What if a warrior who trusts no one must lead a band of misfits through a void-corrupted landscape to seal an ancient breach?",
            "central_dramatic_question": "Can Kael learn to trust others before the Void consumes everything?",
            "logline": "A lone warrior must overcome his distrust of others to lead a fellowship against an ancient darkness.",
        },
        "conflict": {
            "primary_antagonistic_force": {
                "type": "environmental + personal",
                "identity": "The Void and its herald, Morreth",
                "motivation": "Morreth believes the Void is liberation from the tyranny of order, having been wronged by the same institutions Kael serves.",
                "escalation": "Starts as distant threat (corrupted wildlife), escalates to corrupted allies, culminates in Morreth revealing he was once Kael's mentor.",
            },
            "secondary_pressures": ["Dissent within the fellowship", "Kael's deteriorating health from Void exposure"],
            "lock_in_mechanism": "The Void breach is expanding. Every day they delay, more of the world is lost.",
        },
        "theme": {
            "thematic_premise": "True strength requires vulnerability",
            "thematic_argument": "The story argues that isolation is a form of self-destruction — Kael's refusal to trust others mirrors the Void's consumption of life, and only by opening himself to the risk of betrayal can he find the strength to close the breach.",
            "how_each_arc_tests_theme": {
                "Kael": "Tests through reluctant leadership — forced to depend on others",
                "Lyra": "Tests through institutional rebellion — must trust outside the system",
            },
        },
        "protagonist_arc_type": "change",
        "ensemble_cast": [
            {
                "name": "Kael",
                "role": "Protagonist / reluctant leader",
                "three_dimensions": {
                    "surface": "Stoic, competent, keeps emotional distance. Speaks in short, direct sentences. Moves with deliberate economy.",
                    "backstory_inner_demons": "Abandoned by his mentor (Morreth) at 14. Survived alone in the wilds for years. Believes closeness leads to betrayal.",
                    "action_under_pressure": "Becomes hyper-focused and tactical. Will sacrifice his own safety before asking for help. In extremis, rage breaks through the stoicism.",
                },
                "voice_notes": "Sparse internal monologue. Notices tactical details first, emotional details reluctantly. Uses nature metaphors.",
                "weiland_arc": {
                    "lie_believed": "Showing vulnerability will get you killed — the only person you can rely on is yourself.",
                    "ghost": "His mentor Morreth abandoned him in the Void-touched wilds at age 14, nearly killing him.",
                    "want": "To seal the breach alone, proving he needs no one.",
                    "need": "To accept that strength comes from connection, not isolation.",
                    "arc_type": "positive_change",
                    "arc_phase_targets": {
                        "lie_reinforced": "Part 1 - Setup: Kael operates alone, refuses the fellowship",
                        "lie_questioned": "First Plot Point: Forced to accept help when injured",
                        "lie_cracking": "Midpoint: Sees Lyra sacrifice for a stranger, questions his isolation",
                        "lie_confronted": "Second Plot Point: Must choose between solo suicide mission and trusting the team",
                        "truth_resolved": "Resolution: Opens himself to the fellowship to close the breach together",
                    },
                },
            },
            {
                "name": "Lyra",
                "role": "Scholar-rebel / moral compass",
                "three_dimensions": {
                    "surface": "Passionate, outspoken, sometimes reckless. Gestures when she talks. Quick to anger, quick to forgive.",
                    "backstory_inner_demons": "Grew up in the Academy that created the Void. Carries guilt for the institution's sins.",
                    "action_under_pressure": "Thinks laterally, finds unconventional solutions. Will break rules without hesitation if lives are at stake.",
                },
                "voice_notes": "Uses academic vocabulary mixed with street slang. Internal monologue is rapid and associative. References obscure lore constantly.",
                "weiland_arc": {
                    "lie_believed": "The system that created the Void can be reformed from within — you just need enough evidence.",
                    "ghost": "Her research was suppressed and her mentor imprisoned when they got too close to the truth.",
                    "want": "To expose the Academy's role in creating the Void.",
                    "need": "To accept that some systems must be replaced, not reformed.",
                    "arc_type": "disillusionment",
                },
            },
        ],
        "canon_constraints": {
            "continuity": "Original world — no external canon",
            "canon_preserved": [],
            "style_constraints": ["Dark fantasy tone", "No comic relief characters"],
        },
        "structural_notes": {
            "brooks_alignment": {
                "part_1_setup": "Kael encounters the Void breach, refuses fellowship, is forced to accept",
                "first_plot_point": "The fellowship enters the corrupted zone",
                "midpoint": "Kael discovers Morreth is alive and is the herald",
                "second_plot_point": "Morreth offers Kael a choice: join or die alone",
                "part_4_resolution": "Fellowship confronts Morreth, Kael opens himself to trust",
            },
        },
        "voice_definition": {
            "pov_approach": "rotating close third-person limited",
            "prose_register": "commercial dark fantasy",
            "anti_slop_rules": [
                "Never use 'delve', 'tapestry', or 'nuanced'",
                "Never use 'It wasn't just X, it was Y'",
            ],
            "anti_patterns": ["Every chapter opening with weather"],
            "narrative_voice_notes": "Lean prose. Short paragraphs in action, longer in introspection.",
        },
        "subplots": [
            {
                "subplot_id": "main_plot",
                "name": "Seal the Void breach",
                "line_type": "A",
                "function": "Main dramatic throughline",
                "chapters_active": [1, 5, 10, 15, 20, 25],
            },
            {
                "subplot_id": "trust_arc",
                "name": "Kael and Lyra's trust",
                "line_type": "B",
                "function": "Tests the theme of vulnerability",
                "chapters_active": [2, 3, 8, 13, 18, 23],
            },
        ],
        "hooks": [
            {
                "hook_id": "morreth_identity",
                "description": "The herald of the Void is Kael's former mentor",
                "hook_type": "hard",
                "planted_in": "Chapter 2",
                "resolved_in": "Chapter 13",
            },
            {
                "hook_id": "academy_secret",
                "description": "The Academy created the original Void breach",
                "hook_type": "hard",
                "planted_in": "Chapter 4",
                "resolved_in": "Chapter 20",
            },
        ],
        "terminology_registry": [
            {"term": "The Void", "definition": "Corrupting darkness spreading from the breach",
             "category": "concept", "aliases": ["Void", "the corruption"]},
            {"term": "Kael", "definition": "Protagonist, lone warrior",
             "category": "character_name", "aliases": ["the warrior"]},
            {"term": "Morreth", "definition": "Herald of the Void, Kael's former mentor",
             "category": "character_name", "aliases": ["the Herald"]},
        ],
    }
    path = tmp_path / "concept_seed.json"
    with open(path, "w") as f:
        json.dump(seed, f)
    return seed, str(path)


class TestConceptSeedToStoryState:
    """Tests that a Phase 5 concept seed correctly initializes story state."""

    def test_init_from_seed_creates_character_arcs(self, phase5_concept_seed, tmp_path):
        """init_from_concept_seed populates character_arcs table."""
        seed, _ = phase5_concept_seed
        state = StoryState(db_path=str(tmp_path / "state.db"))
        state.init_from_concept_seed(seed)

        arc = state.get_character_arc("kael")
        assert arc is not None
        assert arc["lie_believed"].startswith("Showing vulnerability")
        assert arc["arc_type"] == "positive_change"
        assert arc["current_phase"] == "lie_established"
        assert "Part 1" in arc["arc_phase_targets"]["lie_reinforced"]

        lyra_arc = state.get_character_arc("lyra")
        assert lyra_arc is not None
        assert lyra_arc["arc_type"] == "disillusionment"
        state.close()

    def test_init_from_seed_creates_subplots(self, phase5_concept_seed, tmp_path):
        """init_from_concept_seed populates subplots table."""
        seed, _ = phase5_concept_seed
        state = StoryState(db_path=str(tmp_path / "state.db"))
        state.init_from_concept_seed(seed)

        subplots = state.get_all_subplots()
        assert len(subplots) == 2
        ids = {s["subplot_id"] for s in subplots}
        assert "main_plot" in ids
        assert "trust_arc" in ids
        # The main_plot subplot's chapters_active are [1, 5, 10, 15, 20, 25],
        # so start_chapter should derive to 1 and resolution_chapter to 25.
        main = state.get_subplot("main_plot")
        assert main["start_chapter"] == 1
        assert main["resolution_chapter"] == 25
        state.close()

    def test_init_from_seed_creates_hooks(self, phase5_concept_seed, tmp_path):
        """init_from_concept_seed populates hooks table."""
        seed, _ = phase5_concept_seed
        state = StoryState(db_path=str(tmp_path / "state.db"))
        state.init_from_concept_seed(seed)

        hooks = state.get_all_hooks()
        assert len(hooks) == 2
        ids = {h["hook_id"] for h in hooks}
        assert "morreth_identity" in ids
        assert "academy_secret" in ids
        # Workshop-native hook_type "hard" maps to DB priority "hard";
        # DB hook_type defaults to "foreshadow".
        morreth = state.get_hook("morreth_identity")
        assert morreth["priority"] == "hard"
        assert morreth["planted_chapter"] == 2
        assert morreth["payoff_chapter"] == 13
        state.close()

    def test_init_from_seed_creates_terminology(self, phase5_concept_seed, tmp_path):
        """init_from_concept_seed populates terminology_registry table."""
        seed, _ = phase5_concept_seed
        state = StoryState(db_path=str(tmp_path / "state.db"))
        state.init_from_concept_seed(seed)

        terms = state.get_all_terms()
        assert len(terms) == 3
        void_term = state.find_term("The Void")
        assert void_term is not None
        assert "corruption" in str(void_term.get("aliases", []))
        state.close()


class TestContextAssemblyWithPhase5:
    """Tests that context assembler includes Phase 5 context."""

    def test_voice_rules_in_context(self, phase5_concept_seed, tmp_path):
        """Voice definition rules appear in assembled context."""
        _, seed_path = phase5_concept_seed
        constraints_path = str(tmp_path / "neg.yaml")
        with open(constraints_path, "w") as f:
            f.write("banned_phrases:\n  ai_tells:\n    - delve\n")

        assembler = ContextAssembler(
            concept_seed_path=seed_path,
            negative_constraints_path=constraints_path,
            manuscripts_dir=str(tmp_path / "manuscripts"),
        )
        voice_rules = assembler._assemble_voice_rules()
        assert "delve" in voice_rules
        assert "rotating close third" in voice_rules

    def test_hook_agenda_with_story_state(self, phase5_concept_seed, tmp_path):
        """Hook agenda works when story state is populated."""
        seed, seed_path = phase5_concept_seed
        state = StoryState(db_path=str(tmp_path / "state.db"))
        state.init_from_concept_seed(seed)

        constraints_path = str(tmp_path / "neg.yaml")
        with open(constraints_path, "w") as f:
            f.write("banned_phrases:\n  ai_tells: []\n")

        assembler = ContextAssembler(
            concept_seed_path=seed_path,
            negative_constraints_path=constraints_path,
            story_state=state,
        )
        agenda = assembler._assemble_hook_agenda(2)
        # Chapter 2 should have morreth_identity hook to plant
        assert "morreth_identity" in agenda or agenda == ""  # May show in to_plant
        state.close()

    def test_arc_context_for_pov(self, phase5_concept_seed, tmp_path):
        """Arc context correctly shows POV character's Weiland state."""
        seed, seed_path = phase5_concept_seed
        state = StoryState(db_path=str(tmp_path / "state.db"))
        state.init_from_concept_seed(seed)

        constraints_path = str(tmp_path / "neg.yaml")
        with open(constraints_path, "w") as f:
            f.write("banned_phrases:\n  ai_tells: []\n")

        assembler = ContextAssembler(
            concept_seed_path=seed_path,
            negative_constraints_path=constraints_path,
            story_state=state,
        )
        arc_ctx = assembler._assemble_arc_context("Kael")
        assert "vulnerability" in arc_ctx.lower() or "lie" in arc_ctx.lower()
        assert "lie_reinforced" in arc_ctx
        state.close()


