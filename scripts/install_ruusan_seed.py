"""One-shot installer for the Ruusan Atonement concept seed.

Loads the workshop output from Downloads, applies all enrichments
(voice_definition, arc_phase_map, promise_payoff_ledger, canon_constraints,
extended_metadata restructure), writes the final seed to
data/projects/the-ruusan-atonement/concept_seed.json, and extracts
28 individual scene cards to data/projects/the-ruusan-atonement/scene_cards/.

Validates the final seed against schemas/concept_seed.json and each
extracted scene card against schemas/scene_card.json.

Run once from the repo root:
    python scripts/install_ruusan_seed.py
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import jsonschema

# Make ``src`` importable when this script is run directly from the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.concept_workshop.scene_card_translator import translate_scene_card  # noqa: E402
from src.concept_workshop.seed_transforms import (  # noqa: E402
    apply_arc_phase_maps,
    apply_canon_constraints,
    apply_promise_payoff_ledger,
    apply_voice_definition,
    apply_workshop_origin,
    move_to_extended_metadata,
    normalize_enums,
)

SOURCE_SEED = Path("C:/Users/LouisBouwer/Downloads/the_ruusan_atonement_concept_seed.json")
TARGET_DIR = REPO_ROOT / "data" / "projects" / "the-ruusan-atonement"
TARGET_SEED = TARGET_DIR / "concept_seed.json"
SCENE_CARDS_DIR = TARGET_DIR / "scene_cards"
CONCEPT_SEED_SCHEMA = REPO_ROOT / "schemas" / "concept_seed.json"
SCENE_CARD_SCHEMA = REPO_ROOT / "schemas" / "scene_card.json"


# ---------------------------------------------------------------------------
# Task 2 — voice_definition (verbatim from the task prompt)
# ---------------------------------------------------------------------------

VOICE_DEFINITION = {
    "pov_approach": (
        "Close third person, locked to Ben Skywalker throughout. The narrative "
        "voice has access to Ben's thoughts and perceptions but not other "
        "characters' internal states. Other characters are experienced through "
        "Ben's observation — their words, actions, expressions, and Force "
        "presences as Ben perceives them."
    ),
    "prose_register": (
        "Commercial genre fiction — accessible, propulsive, emotionally direct. "
        "Not literary/experimental. Not YA-simple. The register of the better "
        "Star Wars EU novels: clean prose that doesn't draw attention to itself, "
        "serves the story's pace, and trusts the reader to track subtext "
        "without over-explaining."
    ),
    "reference_authors": [
        {
            "author": "Matthew Stover",
            "what_to_emulate": (
                "Visceral Force-perception descriptions, intense internal "
                "monologue under pressure, the ability to make philosophy feel "
                "like action. Stover's Traitor and Shatterpoint are the gold "
                "standard for Star Wars novels that are both accessible and "
                "intellectually serious."
            ),
            "what_to_avoid": (
                "Stover's occasional purple prose and his tendency toward "
                "sentence fragments as a stylistic tic can become exhausting "
                "over 100k words."
            ),
        },
        {
            "author": "Timothy Zahn",
            "what_to_emulate": (
                "Clean, precise plotting. Tactical clarity in action scenes. "
                "The ability to make intelligent characters sound intelligent "
                "without becoming lecturing. Zahn's dialogue is efficient — "
                "every line does work."
            ),
            "what_to_avoid": (
                "Zahn's prose can be emotionally cool — functional rather than "
                "felt. This story needs more emotional warmth than Zahn "
                "typically provides, especially in the Sera/Torin and Ben/Desh "
                "dynamics."
            ),
        },
        {
            "author": "Aaron Allston",
            "what_to_emulate": (
                "Humor that coexists with genuine stakes. Allston's ability to "
                "make characters funny without undermining the drama. Desh's "
                "voice in particular should channel Allston's tone — dry, "
                "self-aware, grounding."
            ),
            "what_to_avoid": (
                "Allston occasionally lets humor deflate tension at moments "
                "that should land hard. The Torin turn, the breach experience, "
                "and the climax need humor-free zones."
            ),
        },
        {
            "author": "James Luceno",
            "what_to_emulate": (
                "Deep lore integration that feels organic rather than "
                "encyclopedic. Luceno weaves EU history into narrative without "
                "stopping for footnotes. The technique lineage sections should "
                "feel like Luceno — rich context delivered through character "
                "perspective, not authorial lecture."
            ),
            "what_to_avoid": (
                "Luceno's pacing can be slow and his prose dense. This story "
                "needs to move faster than Luceno typically does, especially in "
                "Parts 3-4."
            ),
        },
    ],
    "character_voices": {
        "Ben Skywalker": (
            "Internal voice is sharp, self-aware, occasionally self-deprecating. "
            "Thinks in tactical assessments but feels in emotional undercurrents "
            "he doesn't always acknowledge. His humor is dry and defensive — he "
            "jokes to create distance. His narrative voice matures subtly across "
            "the book: more guarded and controlled in Part 1, more open and "
            "uncertain in Parts 2-3, more grounded and decisive in Part 4. He "
            "does NOT sound like Luke — he's more pragmatic, more skeptical, "
            "more his mother's son."
        ),
        "Sera Varik": (
            "Dialogue is formal, archaic in syntax — no contractions early in "
            "the story, gradually loosening as she adapts. She speaks with "
            "precision and weight. Short sentences under pressure. Longer, more "
            "considered sentences in debate. She does NOT monologue — when she "
            "has something to say, she says it once and expects it to land. Her "
            "formality should soften specifically with Ben as trust builds — "
            "the shift from 'Skywalker' to 'Ben' is a marker the reader should "
            "feel."
        ),
        "Torin Hal": (
            "Warm, easy, disarming. He tells stories. He uses humor to put "
            "people at ease. His dialogue should feel like the most *likeable* "
            "person in the room — which is what makes his turn devastating. As "
            "the story progresses, his warmth thins. The humor becomes slightly "
            "mechanical. The ease becomes slightly performed. The shift should "
            "be subtle enough that the reader feels it before they can name it. "
            "Post-technique in the climax, his voice flattens — still "
            "articulate but emotionally hollow."
        ),
        "Kael Drenn": (
            "Clipped, observational, dry. He doesn't volunteer — he responds. "
            "His humor is deadpan and often arrives after a beat of silence, as "
            "if he considered not saying anything and then couldn't resist. He "
            "speaks less than anyone else in the group. When he does speak, it "
            "tends to be the thing nobody wanted to hear. His voice should warm "
            "incrementally — not dramatically, just enough that the reader "
            "notices he's using more words per sentence by Part 4 than he did "
            "in Part 1."
        ),
        "Darth Veraine": (
            "Precise, academic, unruffled. She speaks in complete, "
            "grammatically sophisticated sentences. No contractions ever. She "
            "asks questions she already knows the answers to. Her dialogue "
            "should feel like a university lecturer who happens to be "
            "discussing the fate of the galaxy. She is never sarcastic — "
            "sarcasm implies emotional investment. She is occasionally "
            "*curious*, which is more unsettling."
        ),
        "Desh Rolan": (
            "Casual, practical, professionally understated. Ex-intelligence "
            "operative who defaults to dry humor under stress. He speaks in "
            "shorter sentences than the Force-users because he's thinking "
            "about concrete things while they're debating philosophy. His "
            "humor is the Allston channel — grounding, well-timed, never at "
            "the expense of the moment's weight. He's the character most "
            "likely to say something the reader is thinking."
        ),
    },
    "anti_slop_rules": [
        "Never use 'a sense of' or 'a feeling of' — describe the sensation directly",
        "Never use 'couldn't help but' — characters make choices, they don't succumb to narrative inevitability",
        "Never use 'it was as if' more than once per chapter — prefer direct metaphor or simile",
        "Never use 'he realized' or 'she realized' as a revelation delivery mechanism — show the realization through reaction and changed behavior",
        "Never use 'little did he know' or any omniscient narrator intrusion — we are locked in close third",
        "Never use 'suddenly' — if something is sudden, the sentence structure should convey that through pacing, not adverb",
        "Never use 'indescribable' or 'beyond words' — if the narrative says something can't be described, the narrative has failed",
        "Never describe a character's eyes changing color or glowing to indicate emotion (except established Force effects)",
        "Avoid 'felt a chill run down his spine' and all variants — find original physical responses to fear/dread",
        "Avoid starting paragraphs with 'And then' — this is a pacing crutch",
        "Avoid 'the young Jedi' or 'the Skywalker heir' as Ben substitutions — use 'Ben' or 'he', never epithets",
        "Avoid 'ancient wisdom' or 'timeless knowledge' when describing archive content — be specific about what the knowledge IS",
        "Avoid adverb-dialogue-tag combinations ('he said quietly', 'she whispered softly') — let the dialogue and context convey tone",
        "Limit exclamation points to actual exclamations — never in narration, rarely in dialogue",
        "Never use 'reach out with the Force' more than twice in the entire manuscript — find varied descriptions for Force-perception",
    ],
    "anti_patterns": [
        "No prophecy fulfillment structure — the story is about choices, not destiny. No character should feel 'fated' to do anything.",
        "No dark side temptation scenes where a character hears whispered voices or sees visions of power. The technique's danger is more subtle and more interesting than standard dark-side temptation.",
        "No training montages — Ben is already a competent Knight. The survivors don't need to learn modern techniques. Growth happens through experience and relationship, not practice sessions.",
        "No 'chosen one' framing — Ben's unique Force perception (the wrongness) is a plot mechanism, not a destiny marker. Other Skywalkers could potentially perceive it too; Ben is simply in the right place and state of mind.",
        "No villainous monologues — Veraine presents arguments, not speeches. She never explains her plan because she doesn't need to justify herself to opponents.",
        "No redemption-through-combat — no character switches sides because they're defeated in a lightsaber duel. Ideological change comes through evidence and experience, not physical submission.",
        "No 'the Force wills it' as explanation — the Force in this story is a system with properties, not a sentient guide. Characters may believe the Force guides them, but the narrative never confirms it.",
        "No convenient timing — if two events coincide, establish the causal or thematic connection. Coincidence is the enemy of earned narrative.",
        "Avoid the 'wise mentor explains things' pattern — Sera, Torin, and Kael are knowledge sources but they should disagree and be wrong about things. No single character has all the answers.",
        "Avoid resolution through superior firepower — the climax is won through collaboration and trust, not through being stronger. The lattice resonance is not a superweapon.",
    ],
    "force_description_guidelines": (
        "The Force in this story has specific phenomenological rules. "
        "Structured Force (normal): perceived as textured, directional, with "
        "distinguishable aspects (light/dark, intent, emotion). It provides "
        "moral intuition — a sense of rightness or wrongness that guides Jedi "
        "decisions. De-structured Force (the wound): perceived as formless, "
        "directionless, without distinguishable aspects. Abilities still "
        "function but without the feedback loop that tells the user whether "
        "their action aligns with light or dark. Described as 'losing color "
        "vision' — everything is present but meaning has drained out. The "
        "technique's activation: perceived as a simplification — the complex "
        "texture of the Force collapsing into a single frequency. Efficient "
        "but brutal. The lattice resonance: perceived as unprecedented — "
        "three different textures interacting, producing an overtone none of "
        "them could create alone. Described as a chord building from notes "
        "that shouldn't harmonize but do. Beautiful, strange, and overwhelming."
    ),
}


# ---------------------------------------------------------------------------
# Task 4 — arc_phase_map for each main character
# ---------------------------------------------------------------------------

ARC_PHASE_MAPS = {
    "Ben Skywalker": {
        "lie_established": "Chapter 1",
        "lie_reinforced": "Chapter 5",
        "lie_challenged": "Chapter 13 (breach experience) / Chapter 18 (Jacen pattern recognized)",
        "moment_of_truth": "Chapter 21",
        "new_truth_demonstrated": "Chapter 25-26",
        "arc_resolved": "Chapter 28",
    },
    "Sera Varik": {
        "lie_established": "Chapter 5",
        "lie_reinforced": "Chapter 8-9",
        "lie_challenged": "Chapter 12 / Chapter 16",
        "moment_of_truth": "Chapter 14",
        "new_truth_demonstrated": "Chapter 22 / Chapter 25-26",
        "arc_resolved": "Chapter 27",
    },
    "Kael Drenn": {
        "lie_established": "Chapter 5",
        "lie_reinforced": "Chapter 8 / Chapter 10",
        "lie_challenged": "Chapter 13 / Chapter 16",
        "moment_of_truth": "Chapter 19",
        "new_truth_demonstrated": "Chapter 23 / Chapter 25-26",
        "arc_resolved": "Chapter 27",
    },
    "Torin Hal": {
        "lie_established": "Chapter 5",
        "lie_reinforced": "Chapter 8 / Chapter 9 / Chapter 12",
        "lie_deepened": "Chapter 15 / Chapter 17",
        "point_of_no_return": "Chapter 18",
        "lie_acted_upon": "Chapter 21",
        "lie_consequence": "Chapter 25-26",
        "arc_resolved_tragic": "Chapter 27",
    },
    "Darth Veraine": {
        "lie_established": "Chapter 5 (referenced)",
        "lie_reinforced": "Chapter 10 / Chapter 16",
        "lie_tested": "Chapter 25-26",
        "lie_unchanged": "Chapter 27",
    },
}


# ---------------------------------------------------------------------------
# Task 5 — promise/payoff ledger (25 curated entries)
# ---------------------------------------------------------------------------

PROMISE_PAYOFF_LEDGER = [
    {
        "promise_id": "PP01",
        "promise": "The wrongness in the Force has a source; Ben will find it",
        "planted_in": "Chapter 1",
        "payoff_in": "Chapter 5",
        "type": "plot",
        "related_hook_id": "H01",
        "rationale": "The opening mystery — the reader's primary entry hook. Cashes at the First Plot Point when the wound is explained.",
    },
    {
        "promise_id": "PP02",
        "promise": "Ben and Desh share unspoken history from their GAG service under Jacen",
        "planted_in": "Chapter 1",
        "payoff_in": "Chapter 11",
        "type": "character",
        "rationale": "Reader senses weight between them in early dialogue; the book owes the honest acknowledgment conversation.",
    },
    {
        "promise_id": "PP03",
        "promise": "Sera and Torin's thousand-year unresolved relationship will play out",
        "planted_in": "Chapter 5",
        "payoff_in": "Chapter 27",
        "type": "character",
        "rationale": "Subplot arc-level promise spanning the entire book — tracked from awakening to Sera choosing to stay with his diminished form.",
    },
    {
        "promise_id": "PP04",
        "promise": "Torin's certainty is dangerous and he will act on it",
        "planted_in": "Chapter 6",
        "payoff_in": "Chapter 21",
        "type": "character",
        "related_hook_id": "H06",
        "rationale": "Fifteen-chapter slow burn from 'Gavran thought so too. Before.' to the turn at the Second Plot Point.",
    },
    {
        "promise_id": "PP05",
        "promise": "Maetha's warning ('the caldera does not consume you, it replaces you') will prove true",
        "planted_in": "Chapter 12",
        "payoff_in": "Chapter 25-26",
        "type": "thematic",
        "rationale": "Direct verbatim foreshadowing — the book owes Torin's diminishment as its fulfillment.",
    },
    {
        "promise_id": "PP06",
        "promise": "Veraine is ahead and methodical; the group will confront and defeat her",
        "planted_in": "Chapter 5",
        "payoff_in": "Chapter 25-26",
        "type": "plot",
        "related_hook_id": "H05",
        "rationale": "Primary antagonist arc — reader expects both ideological confrontation (Ch 16) and empirical defeat at the climax.",
    },
    {
        "promise_id": "PP07",
        "promise": "The Jacen Solo parallel will be recognized by Ben, and he will break the pattern",
        "planted_in": "Chapter 5",
        "payoff_in": "Chapter 21",
        "type": "thematic",
        "rationale": "Ben's personal history resonating with the story's thematic argument — structural throughline across four explicit touchpoints.",
    },
    {
        "promise_id": "PP08",
        "promise": "The institutional lie (the Reformations' true history) must be told to the Order",
        "planted_in": "Chapter 5",
        "payoff_in": "Chapter 28",
        "type": "thematic",
        "rationale": "SP4 subplot's organizational-level thematic test — reader watches the cover-up's weight build and expects institutional reckoning.",
    },
    {
        "promise_id": "PP09",
        "promise": "Kael's detachment is a defense mechanism; he will choose to commit voluntarily",
        "planted_in": "Chapter 5",
        "payoff_in": "Chapter 23",
        "type": "character",
        "related_hook_id": "H22",
        "rationale": "Kael's full arc — reader watches the outsider question his own pattern and wants to see him choose to belong.",
    },
    {
        "promise_id": "PP10",
        "promise": "Gavran's archived note about lattice resonance will matter to the climax",
        "planted_in": "Chapter 14",
        "payoff_in": "Chapter 25-26",
        "type": "plot",
        "related_hook_id": "H14",
        "rationale": "Chekhov's gun planted explicitly — 'we lacked the will to attempt it' and the reader expects the attempt.",
    },
    {
        "promise_id": "PP11",
        "promise": "Each generation of technique-developers thought they were smarter; the resonance breaks that cycle",
        "planted_in": "Chapter 5",
        "payoff_in": "Chapter 25-26",
        "type": "thematic",
        "rationale": "Historical cycle-breaking promise — seven chapters of lineage exposition expect a thematically satisfying break.",
    },
    {
        "promise_id": "PP12",
        "promise": "Ben's unilateral pattern (withholding from Luke) will resolve in transparency",
        "planted_in": "Chapter 5",
        "payoff_in": "Chapter 28",
        "type": "thematic",
        "rationale": "Ben's Weiland arc resolution — reader watches him make the exact choice the story's theme condemns, then return to undo it.",
    },
    {
        "promise_id": "PP13",
        "promise": "Three different Force traditions can genuinely work in concert",
        "planted_in": "Chapter 9",
        "payoff_in": "Chapter 25-26",
        "type": "thematic",
        "rationale": "Ankhural Codex debate establishes four incompatible positions in Ch 9; the climax demands the reader see them harmonize.",
    },
    {
        "promise_id": "PP14",
        "promise": "The Ankhural Codex's theoretical framework has a real-world answer",
        "planted_in": "Chapter 9",
        "payoff_in": "Chapter 25-26",
        "type": "thematic",
        "rationale": "Abstract theoretical framework must be empirically tested — 'does the theory hold?' promise distinct from PP10's engineered solution.",
    },
    {
        "promise_id": "PP15",
        "promise": "Sera's formal distance from Ben will thaw; trust must be earned",
        "planted_in": "Chapter 5",
        "payoff_in": "Chapter 14 / Chapter 28",
        "type": "character",
        "rationale": "Tracked explicitly in the terminology registry: 'Skywalker' shifts to 'Ben' — micro-promise the reader feels before they can name it.",
    },
    {
        "promise_id": "PP16",
        "promise": "Veraine's philosophy is coherent enough to be genuinely unsettling, not a straw man",
        "planted_in": "Chapter 8",
        "payoff_in": "Chapter 16 / Chapter 25-26",
        "type": "thematic",
        "rationale": "The story signals early that the antagonist's argument will be taken seriously — reader expects her best case, then a real answer.",
    },
    {
        "promise_id": "PP17",
        "promise": "The full de-structured Force experience will be delivered, not just referenced",
        "planted_in": "Chapter 8",
        "payoff_in": "Chapter 13",
        "type": "atmospheric",
        "related_hook_id": "H08",
        "rationale": "Thin-place preview promises the visceral midpoint experience — experiential sensory contract.",
    },
    {
        "promise_id": "PP18",
        "promise": "The primary wound site has a physical presence the reader will experience",
        "planted_in": "Chapter 3",
        "payoff_in": "Chapter 20",
        "type": "atmospheric",
        "rationale": "The seal is referenced abstractly early; the book promises a spatial/embodied encounter at Veranthos.",
    },
    {
        "promise_id": "PP19",
        "promise": "Desh, the non-Force-user, will matter to the climax",
        "planted_in": "Chapter 1",
        "payoff_in": "Chapter 25",
        "type": "character",
        "rationale": "Reader sees Desh as practical grounding from Ch 1; the book must deliver his essential role beyond emotional support.",
    },
    {
        "promise_id": "PP20",
        "promise": "Sera's rigidity will break into principled flexibility, not abandonment",
        "planted_in": "Chapter 5",
        "payoff_in": "Chapter 14 / Chapter 22 / Chapter 27",
        "type": "character",
        "rationale": "Sera's Weiland arc — three payoff moments showing she can adapt without betraying her principles.",
    },
    {
        "promise_id": "PP21",
        "promise": "Ben will find a new relationship with his legacy — not escape from it",
        "planted_in": "Chapter 1",
        "payoff_in": "Chapter 28",
        "type": "character",
        "rationale": "Opening 'Skywalker shadow' characterization promises a final image where he's at peace with his name.",
    },
    {
        "promise_id": "PP22",
        "promise": "Ben's unique Force perception will resolve into his own frequency",
        "planted_in": "Chapter 1",
        "payoff_in": "Chapter 28",
        "type": "atmospheric",
        "rationale": "Final image ('a note in a chord. Enough.') is a deliberate sensory callback to the opening wrongness.",
    },
    {
        "promise_id": "PP23",
        "promise": "Mere tactical cooperation will not work; the climax demands genuine unity",
        "planted_in": "Chapter 6",
        "payoff_in": "Chapter 25-26",
        "type": "thematic",
        "rationale": "Early group fractures set up that functional alliance won't suffice — climax demands something harder than coordination.",
    },
    {
        "promise_id": "PP24",
        "promise": "The seal failure has a hard timeline; the story is racing a clock",
        "planted_in": "Chapter 3",
        "payoff_in": "Chapter 25-26",
        "type": "plot",
        "rationale": "Ticking-clock promise — timeline compresses across Ch 13 and Ch 16 to days. Reader expects resolution before the seal collapses.",
    },
    {
        "promise_id": "PP25",
        "promise": "The group will reach Veranthos — the primary site must be physically visited",
        "planted_in": "Chapter 3",
        "payoff_in": "Chapter 20",
        "type": "plot",
        "rationale": "Destination promise — classic quest beat. Coordinates set in Ch 3; reader expects arrival as a plot milestone before climax.",
    },
]


# ---------------------------------------------------------------------------
# Task 1 — canon_constraints derivation
# ---------------------------------------------------------------------------

CANON_CONSTRAINTS = {
    "continuity": "Star Wars Legends (Expanded Universe), post-Fate of the Jedi, 47 ABY",
    "divergence_point": (
        "Diverges from published Legends continuity by introducing the Ruusan "
        "Atonement thread — the Ruusan Reformations recontextualized as penance "
        "for the Jedi Lords' forbidden technique (a localized de-structuring of "
        "the Force lattice created at the Battle of Veranthos c. 1000 BBY). "
        "The seal containing that wound has been maintained by the Order for a "
        "thousand years; in 47 ABY it begins to fail."
    ),
    "canon_preserved": [
        "Ben Skywalker as Jedi Knight, son of Luke and Mara Jade Skywalker",
        "Jacen Solo's fall to Darth Caedus and his murder of Mara Jade",
        "Ben's service in the Galactic Alliance Guard (GAG) under Jacen as a teenager",
        "The Abeloth crisis and its resolution in Fate of the Jedi",
        "Ben's prior relationship with Vestara Khai and her choice of the dark side",
        "Luke Skywalker as Grand Master of the Jedi Order",
        "The Ruusan Reformations (1000 BBY) as a real historical event in the EU timeline",
        "The Brotherhood of Darkness and Lord Kaan as pre-Reformations Sith entities",
    ],
    "canon_overridden": [
        "The true purpose of the Ruusan Reformations: published Legends treats them as a restructuring for military and doctrinal reasons; this AU treats them as a dual-purpose event — public reform plus private penance for the Jedi Lords' forbidden technique",
        "The existence of the forbidden technique lineage (Nathema study -> Malachor V wound fragmentary records -> Quelling of Tython -> Nihil Reach experiments -> Ankhural Codex -> Drathul IV incident -> Caldera Knights -> Gavran's technique)",
        "Darth Veraine (Brotherhood of Darkness alchemist) and the three Jedi survivors (Sera Varik, Torin Hal, Kael Drenn) sealed in stasis since the final stage of the New Sith Wars",
        "The Battle of Veranthos as a decisive (but previously erased) New Sith Wars engagement where Gavran deployed the technique at maximum scale",
        "Force lattice as a potentially imposed structure rather than a natural property — the Ankhural Codex's heretical theoretical framework",
    ],
    "style_constraints": [
        "Capitalize 'Human' per Lucasfilm style guide",
        "Decapitalize 'galaxy' in all contexts unless starting a sentence",
        "American English spellings throughout",
        "Hyperdrive classifications, ship specifications, and planetary names must match Wookieepedia entries where existing canon applies",
        "Technology and Force abilities must respect established Legends-era specifications",
        "'Jedi' is both singular and plural — never 'Jedis'",
        "'Darth' as a Sith title is capitalized when preceding a name; generic 'the Sith' lowercase",
    ],
}


# ---------------------------------------------------------------------------
# Ruusan-specific scene card overrides
# ---------------------------------------------------------------------------

# Chapter 26 is the structural climax even though its arc_phase says "Resolution".
# The generic translator accepts structural_overrides as a kwarg.
MANUAL_STRUCTURAL_OVERRIDES: dict[int, str] = {
    26: "climax",
}

# Canonical arc_type per main character — fed to normalize_enums.
ARC_TYPE_MAP: dict[str, str] = {
    "Ben Skywalker": "positive_change",
    "Sera Varik": "positive_change",
    "Kael Drenn": "positive_change",
    "Torin Hal": "negative",
    "Darth Veraine": "negative",
    "Desh Rolan": "positive_change",
}


# ---------------------------------------------------------------------------
# Main installer
# ---------------------------------------------------------------------------


def main() -> int:
    if not SOURCE_SEED.exists():
        print(f"ERROR: source seed not found at {SOURCE_SEED}", file=sys.stderr)
        return 1

    print(f"Loading source seed from {SOURCE_SEED}")
    seed = json.loads(SOURCE_SEED.read_text(encoding="utf-8"))

    # --- Task 2: Inject voice_definition ---
    print("Task 2: adding voice_definition")
    apply_voice_definition(seed, VOICE_DEFINITION)

    # --- Normalize enums: tone + canon_status + weiland_arc.arc_type ---
    print("Normalize: tone + canon_status + arc_type enums")
    normalize_enums(
        seed,
        tone_fallback="heroic_with_weight",
        canon_status_fallback="AU",
        arc_type_map=ARC_TYPE_MAP,
    )

    # --- Task 4: Add arc_phase_map to each main character's weiland_arc ---
    print("Task 4: adding arc_phase_map to main characters")
    apply_arc_phase_maps(seed, ARC_PHASE_MAPS)

    # --- Task 5: Add promise/payoff ledger ---
    print("Task 5: adding promise_payoff_ledger (25 entries)")
    apply_promise_payoff_ledger(seed, PROMISE_PAYOFF_LEDGER)

    # --- Restructure: move technique_lineage + jacen_parallel under extended_metadata ---
    print("Restructure: moving technique_lineage and jacen_parallel under extended_metadata")
    move_to_extended_metadata(seed, ["technique_lineage", "jacen_parallel"])
    apply_workshop_origin(
        seed,
        {
            "source": "claude_ai_simulation",
            "date": "2026-04-09",
            "session_type": "full_workshop_steps_0_to_10",
            "notes": (
                "Concept workshop simulation conducted in Claude.ai for Phase 5 "
                "protocol validation. Step 5 (Voice Discovery) was added post-hoc "
                "via this installer."
            ),
        },
    )

    # --- Task 1: add canon_constraints (derived from seed content) ---
    print("Task 1: adding canon_constraints")
    apply_canon_constraints(seed, CANON_CONSTRAINTS)

    # --- Write the enriched seed ---
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    SCENE_CARDS_DIR.mkdir(parents=True, exist_ok=True)
    TARGET_SEED.write_text(
        json.dumps(seed, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Wrote enriched seed to {TARGET_SEED}")

    # --- Extract 28 scene cards to individual files ---
    print("Task 1: extracting scene cards")
    scene_card_schema = json.loads(CONCEPT_SEED_SCHEMA.read_text(encoding="utf-8"))  # for reference
    scene_card_draft_schema = json.loads(SCENE_CARD_SCHEMA.read_text(encoding="utf-8"))
    for card in seed["scene_cards"]:
        translated = translate_scene_card(
            card, structural_overrides=MANUAL_STRUCTURAL_OVERRIDES
        )
        ch = translated["chapter_number"]
        sn = translated["scene_number"]
        filename = f"chapter_{ch:02d}_scene_{sn:02d}.json"
        path = SCENE_CARDS_DIR / filename
        path.write_text(
            json.dumps(translated, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        # Validate against scene card schema
        try:
            jsonschema.validate(translated, scene_card_draft_schema)
        except jsonschema.ValidationError as e:
            print(f"ERROR: scene card {filename} fails schema: {e.message}")
            return 2
    print(f"Wrote 28 scene cards to {SCENE_CARDS_DIR}")

    # --- Validate the enriched seed against concept_seed schema ---
    print("Validating enriched seed against schemas/concept_seed.json")
    try:
        jsonschema.validate(seed, scene_card_schema)
        print("Enriched seed: PASS")
    except jsonschema.ValidationError as e:
        print(f"Enriched seed: FAIL at path {list(e.absolute_path)}: {e.message}")
        return 3

    # --- Summary ---
    print()
    print("=== Installation summary ===")
    print(f"  Characters: {len(seed.get('ensemble_cast', []))}")
    print(f"  Subplots: {len(seed.get('subplots', []))}")
    print(f"  Hooks: {len(seed.get('hooks', []))}")
    print(f"  Revelations: {len(seed.get('revelation_schedule', []))}")
    print(f"  Scene cards: {len(seed.get('scene_cards', []))}")
    print(f"  Promise/payoff ledger: {len(seed.get('promise_payoff_ledger', []))}")
    print(f"  Terminology entries: {len(seed.get('terminology_registry', []))}")
    print(f"  Voice reference authors: {len(seed['voice_definition'].get('reference_authors', []))}")
    print(f"  Voice character_voices: {len(seed['voice_definition'].get('character_voices', {}))}")
    print(f"  Voice anti_slop_rules: {len(seed['voice_definition'].get('anti_slop_rules', []))}")
    print(f"  Voice anti_patterns: {len(seed['voice_definition'].get('anti_patterns', []))}")
    print(f"  Extended metadata keys: {list(seed['extended_metadata'].keys())}")
    print(f"  Stress test overall: {seed.get('stress_test_scores', {}).get('overall')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
