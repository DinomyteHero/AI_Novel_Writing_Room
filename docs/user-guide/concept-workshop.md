# Concept Workshop

The Concept Workshop is an interactive CLI tool for developing a story concept from initial spark to pipeline-ready seed document. It guides you through a structured ten-step protocol (Steps 0-10) with an AI facilitator, including series support and adversarial stress testing.

## Starting a Workshop

```bash
python -m src.concept_workshop.workshop_runner --project <project_name>
```

| Flag | Description |
|------|-------------|
| `--project NAME` | Project name (creates `data/projects/<NAME>/` directory) |
| `--resume` | Resume a previous session with saved state context |
| `--finalize` | Finalize the concept and generate the seed document |
| `--series` | Planned series mode (activates Step 0a: Series Seed Workshop) |
| `--continue-from PATH` | Continue from a previous book's transition snapshot |
| `--promote-to-series` | Retroactively promote a standalone concept to series |

## The Ten-Step Protocol

The workshop facilitator walks you through these steps:

0. **Project Scope** -- Choose standalone, planned series, or continuation
   - 0a. **Series Seed Workshop** *(series only)* -- Define series arc, stakes progression, cross-book promises
   - 0b. **Retroactive Series Promotion** *(optional)* -- Promote a completed standalone to series
1. **Fandom, Era, Tone, Cast Type** -- Choose franchise, timeline, tone. Series continuations show inherited constraints.
2. **"What If" Seed Generation** -- The AI generates 3-5 premise seeds based on your inputs
3. **Premise Development** -- Central dramatic question, conflict stress test, hook classification (hard/soft/series)
4. **Character Creation + Weiland Arc Beats** -- Three-dimensional profiles plus lie/ghost/want/need/arc_type for each POV character, mapped to Brooks structural phases
5. **Narrative Voice Discovery** -- POV approach, prose register, reference authors, anti-slop rules, anti-patterns
6. **Structural Outline** -- Map to Brooks's four-part structure (Setup/Response/Attack/Resolution)
7. **Subplot Architecture + Hook Map** -- Subplot board (A/B/C/D lines), hook map with admission control, revelation schedule
8. **Scene Cards** -- Chapter-level cards referencing subplots, hooks, revelations, and arc phases
9. **Terminology Registry** -- Canonical terms, aliases, and definitions for consistency
10. **Adversarial Stress Test** -- Devil's advocate evaluation across 5 dimensions (premise, character, structure, hooks, series). Must score >= 7.0 or address flagged issues.

**Validation gates** at Steps 0a, 3, 4, 7, 8, and 10 prevent advancing until requirements are met.

## Session Persistence

Workshop state is saved automatically to `data/projects/<project>/`:

- `workshop_sessions/` -- JSONL transcripts for each session
- `workshop_state.json` -- The evolving concept seed state with confirmation tracking
- `series_seed.json` -- Series-level seed (planned series mode only)
- Workshop state tracks decisions made so far, so you can resume across multiple sessions

## Conversation Commands

During the workshop, type:

- Your response to the facilitator's questions
- `exit`, `done`, or `finalize` to end the session

The facilitator is designed to push back on weak premises and enforce structural rigor. It won't advance past validation gates until the concept is sound.

## Output

When finalized, the workshop produces a concept seed JSON (`book_1_seed.json`) that contains:

- Story metadata (franchise, era, tone, project scope)
- Characters with three-dimensional profiles and Weiland arc definitions
- Voice definition (POV, register, anti-slop rules, anti-patterns)
- Four-part structural outline
- Subplot board and hook map with admission control
- Terminology registry
- Adversarial stress test scores
- Story physics (causality chains, revelations, promises)
- Scene cards for the pipeline

For series projects, a `series_seed.json` is also produced with the series-level arc, cross-book promises, and per-book outlines.

## Example

```bash
# Start a new standalone project
python -m src.concept_workshop.workshop_runner --project my_novel

# Start a planned series
python -m src.concept_workshop.workshop_runner --project void_chronicles --series

# Continue from Book 1
python -m src.concept_workshop.workshop_runner --project void_chronicles_book2 \
    --continue-from data/projects/void-chronicles/book_1_transition.json

# Resume later
python -m src.concept_workshop.workshop_runner --project my_novel --resume

# Finalize
python -m src.concept_workshop.workshop_runner --project my_novel --finalize
```
