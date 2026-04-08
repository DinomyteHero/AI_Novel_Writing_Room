# Concept Workshop

The Concept Workshop is an interactive CLI tool for developing a story concept from initial spark to pipeline-ready seed document. It guides you through a structured six-step protocol with an AI facilitator.

## Starting a Workshop

```bash
python -m src.concept_workshop.workshop_runner --project <project_name>
```

| Flag | Description |
|------|-------------|
| `--project NAME` | Project name (creates `data/story_bibles/<NAME>/` directory) |
| `--resume` | Resume a previous session with saved state context |
| `--finalize` | Finalize the concept and generate the seed document |
| `--config PATH` | Configuration file (default: `config/settings.yaml`) |

## The Six-Step Protocol

The workshop facilitator walks you through these steps:

1. **Fandom, Era, Tone, Cast Type** -- Choose your franchise, timeline era, tone, and cast type
2. **"What If" Seed Generation** -- The AI generates 3-5 premise seeds based on your inputs
3. **Premise Development** -- Develop the chosen premise into protagonist, antagonist, and central conflict
4. **Character Creation** -- Build detailed character sheets with motivations, flaws, and arcs
5. **Structural Outline** -- Map the story to Larry Brooks's four-part structure (Setup/Response/Attack/Resolution)
6. **Scene Cards** -- Break the outline into chapter-level scene cards ready for the pipeline

## Session Persistence

Workshop state is saved automatically to `data/story_bibles/<project>/`:

- `workshop_sessions/` -- JSONL transcripts for each session
- `concept_seed.json` -- The evolving concept seed document
- Workshop state tracks decisions made so far, so you can resume across multiple sessions

## Conversation Commands

During the workshop, type:

- Your response to the facilitator's questions
- `exit`, `done`, or `finalize` to end the session

The facilitator is designed to push back on weak premises and enforce structural rigor. It won't advance past validation gates until the concept is sound.

## Output

When finalized, the workshop produces a `concept_seed.json` that contains:

- Story metadata (franchise, era, tone)
- Characters with detailed profiles
- Four-part structural outline
- Story physics (causality chains, revelations, promises)
- Scene cards for the pipeline

This file becomes the input for the main generation pipeline.

## Example

```bash
# Start a new project
python -m src.concept_workshop.workshop_runner --project my_star_wars_novel

# Resume later
python -m src.concept_workshop.workshop_runner --project my_star_wars_novel --resume

# Run the pipeline with the result
python -m src.main \
    data/story_bibles/my_star_wars_novel/concept_seed.json \
    data/story_bibles/my_star_wars_novel/scene_cards \
    --phase 4
```
