# Planning Manuscript Template

Use this template as a guide when developing your story concept in an external LLM chat (Claude, ChatGPT, Gemini, etc.). Cover each section below during your conversation, then export the result as a markdown file for import into the AI Writers' Room.

You don't need to follow this order exactly — creative conversations are non-linear. But make sure all sections are addressed before exporting. The Seed Builder agent will extract and structure your creative decisions into the required format.

---

## 1. Project Overview

Establish the basics:
- What is the project title?
- Is this original fiction or set in an existing franchise? If franchise, what era/continuity?
- Target word count and approximate chapter count
- Single POV or multiple? Who is the POV character(s)?
- What is the overall tone? (e.g., dark and gritty, adventurous, character study, heroic with weight)

## 2. Premise

Develop these three elements:
- **What-if**: The core speculative question driving the story. What surprising situation or discovery launches everything?
- **Central dramatic question**: What question must be answered by the end? This is what keeps the reader turning pages.
- **Logline**: A 1-2 sentence summary that captures protagonist, conflict, and stakes.

## 3. Conflict Architecture

Map out the opposition:
- **Primary antagonist**: Who or what opposes the protagonist? What is their motivation? How do they escalate across the story?
- **Secondary pressures**: 2-4 additional sources of conflict (internal, interpersonal, institutional, environmental)
- **Lock-in mechanism**: What prevents the protagonist from walking away? Why must they see this through?

## 4. Theme

Define the thematic argument:
- **Thematic premise**: The story's core claim about life/human nature, stated as a testable proposition
- **Thematic argument**: How does the story test this premise? What evidence does the plot provide?
- For each major character: How does their arc test the theme? Characters who prove it, characters who disprove it, characters who complicate it

## 5. Characters (Weiland Arc Framework)

For each significant character (2-6), develop:
- **Name, role, age**
- **Three dimensions**:
  - Surface: How they present to the world
  - Backstory/inner demons: The wound or history that shapes them
  - Action under pressure: How they behave when things go wrong
- **Weiland arc components**:
  - Lie believed: The false belief driving their behavior
  - Ghost: The event or wound that created the lie
  - Want: What they consciously pursue
  - Need: What they actually need (often contradicts the want)
  - Arc type: positive change, flat (steadfast), negative (tragic), or disillusionment
  - Arc progression: At what story beats does the lie get reinforced, challenged, cracked, confronted, and resolved?

## 6. Voice and Style

Define the narrative identity:
- POV approach (close third, first person, omniscient, etc.)
- Prose register (literary, commercial, YA, etc.)
- 2-4 reference authors: whose style to emulate and what to avoid from each
- Character voice distinctions: How does each character sound in dialogue and internal thought?
- Anti-patterns: What should the prose never do? (cliches to avoid, structural patterns to reject)
- Pacing feel: How should the reading experience evolve across the story?

## 7. Structure (Brooks Four-Part)

Map your story to the four-part structure with approximate chapter ranges:
- **Part 1 — Setup** (roughly first 25%): What is the protagonist's normal world? What establishes the status quo?
- **First Plot Point**: The event that locks the protagonist into the story. What changes everything?
- **Part 2 — Response** (roughly 25-50%): How does the protagonist react to the new situation? What are they learning?
- **Midpoint**: The shift from reactive to proactive. What new information or event changes the protagonist's approach?
- **Part 3 — Attack** (roughly 50-75%): The protagonist goes on the offensive. What is their plan? What complications arise?
- **Second Plot Point**: The final revelation or event before the climax.
- **Part 4 — Resolution** (roughly 75-100%): The climax and aftermath. How is the central dramatic question answered?

## 8. Subplots

For each subplot thread:
- What is it about? (relationship, mystery, internal struggle, etc.)
- What function does it serve? (tests theme, complicates main plot, provides relief, etc.)
- Which chapters is it active in?
- How does it resolve?

## 9. Hooks and Revelations

**Hooks** (questions that keep the reader reading):
- For each major hook: When is it planted? When is it resolved? Is it a hard hook (must be resolved) or soft hook (optional payoff)?

**Revelations** (information reveals):
- What key information is revealed and when?
- Who knows what at each point?
- What is the impact of each revelation on the characters and plot?

## 10. Terminology and World-Building

For franchise fiction or stories with invented terminology:
- Key terms with definitions and spelling
- Character name variants and how they're used
- Place names with pronunciation notes if needed
- Technology, magic systems, or cultural terms

---

## Exporting Your Manuscript

When your conversation is complete, ask your LLM to compile the results into a single comprehensive summary covering all sections above. Save this as a markdown file (e.g., `my-novel-manuscript.md`).

Then import it:

```cmd
python -m src.main --import-summary my-novel-manuscript.md --project my-novel --phase 4
```

The Seed Builder agent will extract your creative decisions into a structured `concept_seed.json`, validate it, and save it to your project directory. Review the compliance report for any gaps that need addressing.
