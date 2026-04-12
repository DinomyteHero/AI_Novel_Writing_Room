# Scene Card Generation Template

Use this template when generating scene cards in an external LLM chat (Claude, ChatGPT, Gemini, etc.). You need a **completed concept seed** before generating scene cards — the seed provides the characters, structure, hooks, and revelations that scene cards reference.

## Prerequisites

- A valid `concept_seed.json` in your project directory
- The concept seed should have: premise, conflict, theme, ensemble cast with Weiland arcs, Brooks structural outline, subplots, hooks, and revelation schedule

## Generation Rules

Follow these rules when creating scene cards:

### Scene Count
- Each chapter MUST contain **2-4 scenes** (default 3)
- Single-scene chapters are reserved for rare high-impact moments (climax, major plot points) — **maximum 3** in the entire novel

### Bickham Scene & Sequel
Alternate these scene types within chapters:
- **Action scene**: Goal → Conflict → Setback (external plot movement)
- **Sequel scene**: Reaction → Dilemma → Decision (internal processing)

### Scene Roles
Each scene serves one of these narrative functions:
- `hook` — Opens a chapter with immediate engagement
- `escalation` — Raises stakes or tension
- `reveal` — Delivers key information
- `decision` — Forces a consequential choice
- `aftermath` — Processes the emotional/practical fallout

### Within-Chapter Rules
- Each scene MUST have a **distinct mission** — no two scenes in the same chapter should accomplish the same narrative goal
- Every scene MUST have a **closing_hook** that creates a question, complication, or urgent decision
- Chapters 1-3 also require an **opening_hook**
- **Pressure must escalate** across the chapter — the final scene should not be the lowest-pressure moment
- **Vary conflict types** — no chapter should have all scenes with the same conflict_type

### Word Budget
- Per-scene target: `total_word_count / target_chapters / 3` (e.g., 100,000 / 28 / 3 = ~1,190 words)
- Sum of scene word counts per chapter must be **90-110%** of the chapter budget

## Scene Card Fields

For each scene, provide:

### Identification
- `chapter_number` — integer
- `scene_number` — integer, starting at 1 within each chapter
- `structural_phase` — one of: setup, first_plot_point, response, first_pinch, midpoint, attack, second_pinch, second_plot_point, resolution, climax
- `scene_type` — "action" or "sequel"
- `scene_role` — "hook", "escalation", "reveal", "decision", or "aftermath"

### Narrative Core
- `pov_character` — who sees this scene
- `mission` — what this scene uniquely accomplishes (specific, not vague)
- `why_now` — specific causal justification for this scene's timing (no generic filler like "follows the previous scene")
- `conflict` — what opposes the POV character
- `conflict_type` — "internal", "interpersonal", "external", or "environmental"
- `turning_point` — the moment that changes the scene's direction

### Engagement
- `opening_hook` — how the scene opens with immediate engagement
- `closing_hook` — the question/complication/decision at scene end
- `emotional_trajectory` — the emotional arc within the scene (e.g., "determination -> shock")

### Stakes
- `stakes.personal` — what the POV character personally stands to lose or gain
- `stakes.interpersonal` — what is at risk in relationships
- `stakes.external` — what is at risk in the wider story world

### Setting & Characters
- `characters_present` — list of character names in this scene
- `setting` — location and time
- `sensory_details` — key sensory notes (optional but recommended)

### Story Threading
- `active_subplots` — list of subplot IDs active in this scene (e.g., ["SP1", "SP-A"])
- `plot_threads_advanced` — list of plot threads moved forward
- `promises_planted` — narrative promises planted (foreshadowing, setups)
- `promises_paid` — promises fulfilled in this scene
- `hook_actions` — list of `{hook_id, action}` where action is "plant", "advance", "resolve", or "subvert"
- `revelations` — list of revelation IDs revealed in this scene (e.g., ["R03", "R04"])

### Character Arc Tracking
- `pov_arc_phase` — current Weiland arc phase (e.g., "lie_reinforced", "lie_challenged", "moment_of_truth")
- `arc_phase_transition` — new phase if this scene triggers a transition, else null

### Word Budget
- `target_word_count` — per scene (NOT per chapter)

## Example Scene Card

```json
{
  "chapter_number": 5,
  "scene_number": 2,
  "structural_phase": "first_plot_point",
  "scene_type": "action",
  "scene_role": "escalation",
  "pov_character": "Ben Skywalker",
  "mission": "Ben confronts Sera about Gavran's true intentions for the anchors",
  "why_now": "Archive records from the fortress reveal Gavran sealed Sera against her will",
  "conflict": "Sera defends Gavran's decision; Ben challenges the morality of using people as infrastructure",
  "conflict_type": "interpersonal",
  "turning_point": "Sera admits she argued against the sealing — Gavran overruled her",
  "opening_hook": "The archive tablet trembles in Ben's hands as he reads Gavran's orders",
  "closing_hook": "Torin has been listening from the doorway. His expression is unreadable.",
  "characters_present": ["Ben Skywalker", "Sera Varik", "Torin Hal"],
  "setting": "Fortress archive level, artificial light, dust motes in the air",
  "emotional_trajectory": "Righteous anger -> uncomfortable empathy -> dread",
  "stakes": {
    "personal": "Ben's ability to trust the survivors he just woke up",
    "interpersonal": "The fragile alliance between Ben and Sera",
    "external": "Understanding the seal's design is critical to stopping its collapse"
  },
  "target_word_count": 1300,
  "active_subplots": ["SP-A", "SP1"],
  "plot_threads_advanced": ["anchor_system_truth", "sera_trust_arc"],
  "promises_planted": ["torin_was_listening"],
  "promises_paid": [],
  "hook_actions": [
    {"hook_id": "H05", "action": "advance"},
    {"hook_id": "H06", "action": "plant"}
  ],
  "revelations": ["R04"],
  "pov_arc_phase": "lie_reinforced",
  "arc_phase_transition": null,
  "notes": "This scene establishes that Gavran was not purely noble — seeds doubt about institutional authority"
}
```

## Chunked Generation

LLMs have output limits. Generate scene cards in batches of **7 chapters at a time**:

1. **Batch 1**: Chapters 1-7 (setup through early response)
2. **Batch 2**: Chapters 8-14 (response through midpoint)
3. **Batch 3**: Chapters 15-21 (attack through second plot point)
4. **Batch 4**: Chapters 22-28 (resolution and climax)

For each batch after the first, provide a summary of the previous batch's key events and closing hooks so the LLM maintains continuity.

## Saving Scene Cards

Save each scene card as an individual JSON file in your project's `scene_cards/` directory:

```
data/projects/<your-project>/scene_cards/
  chapter_01_scene_01.json
  chapter_01_scene_02.json
  chapter_01_scene_03.json
  chapter_02_scene_01.json
  ...
```

File naming convention: `chapter_NN_scene_NN.json` (zero-padded to 2 digits).

## Running the Pipeline

Once scene cards are saved, skip `--generate-outline` and run the pipeline directly:

```bash
python -m src.main \
    data/projects/<your-project>/concept_seed.json \
    data/projects/<your-project>/scene_cards \
    --phase 4
```

Test with a single chapter first:

```bash
python -m src.main \
    data/projects/<your-project>/concept_seed.json \
    data/projects/<your-project>/scene_cards \
    --chapter 1 --phase 4
```
