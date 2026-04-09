# Adversarial Concept Stress Test

You are a veteran developmental editor with 30 years of experience. Your job is to find weaknesses in this concept before the author commits to an 80,000-word draft. Be constructive but ruthless — better to fix problems now than at chapter 15.

## Your Task

Evaluate the concept seed below across nine dimensions. For each, score 1-10 and list specific issues. Dimensions that don't apply (lore_and_continuity for original-setting projects, series_coherence for standalone projects) should be returned as `null`.

## Evaluation Dimensions

### 1. Structural Integrity (1-10)
- Does the four-part structure have a clear First Plot Point, Midpoint, and Second Plot Point?
- Does the Midpoint actually change the protagonist's approach (not just present new information)?
- Is the Second Plot Point earned through character agency, not coincidence?
- Does the climax directly resolve the central dramatic question?
- Is the lock-in mechanism strong enough to prevent the protagonist from walking away?

### 2. Character Depth (1-10)
- Does each POV character have a distinct, testable Lie/Want/Need that drives decisions?
- Are the characters' lies specific enough to generate conflict in every scene?
- At the Midpoint, is each character's Moment of Truth earned by preceding events?
- Does the climactic choice force each POV character to choose between Lie and Need with real costs?
- Could any two characters be merged without losing narrative function?

### 3. Hook Discipline (1-10)
- Are all hard hooks resolved by the final chapter (or registered as series hooks)?
- Is the hook budget respected? (Rule of thumb: hard hooks ≤ target_chapters / 3)
- Do revelations have adequate foreshadowing (the "fair play" test)?
- Are there coincidence plot points where the protagonist succeeds through luck rather than agency?
- Does every hard hook have a planned payoff, and do hooks serve distinct narrative purposes?

### 4. Thematic Resonance (1-10)
- Is the theme present in the A-line conflict (not just in subplots)?
- Does at least one character's arc argue AGAINST the thematic premise (providing counterargument)?
- Is the theme resolved through action in the climax, not through dialogue/narration?
- Do different characters test the theme from different angles?
- Is the thematic argument specific and debatable, not a cliché?

### 5. Conflict Architecture (1-10)
- Is there a specific, named antagonistic force with concrete motivation?
- What specifically happens if the protagonist fails? Are the stakes visceral, not just cosmic?
- Does the antagonist escalate across the four parts (not just appear, vanish, reappear)?
- Are secondary pressures (internal, interpersonal, environmental) distinct from the primary antagonist?
- Can the antagonist's plan be defeated by a simpler solution the characters haven't tried?

### 6. Pacing and Proportion (1-10)
- Are the four parts roughly proportional (20-25% / 25% / 25% / 25-30%)?
- Is the midpoint at the actual structural midpoint (within a chapter or two)?
- Are there dead zones where nothing is changing — no new information, no new conflict, no character progression?
- Are action and sequel scenes balanced, or is the story front-loaded / back-loaded?
- Does the total target word count across scene cards match the book's target?

### 7. Lore and Continuity (1-10) — franchise fiction only; null for original settings
- Does the story fit within the established canon/AU framework without contradictions?
- Are original elements (characters, locations, events, magic/Force concepts) plausible within the franchise's established rules?
- Are existing canon characters portrayed consistently with their established characterization?
- Has a full timeline check been performed to verify dates are internally consistent?
- If AU divergences exist, are they clearly defined and consistently applied?

### 8. World-Building Coherence (1-10)
- Are all original locations physically and ecologically plausible within the setting?
- Are communication, transportation, and logistics internally consistent?
- Do technology levels, political structures, and cultural details align with the established era?
- Are there any "convenience" world-building elements that exist only to serve the plot without in-universe justification?
- Does the magic/Force/special-mechanic system have specific, learnable rules that create both opportunities and constraints?

### 9. Series Coherence (1-10) — series only; null for standalone
- Does this book advance the series dramatic question without resolving it (unless final book)?
- Are all series promises due in this book addressed?
- Does this book plant at least one new series promise for future payoff?
- Are the stakes appropriately positioned in the series escalation?
- Could a reader enjoy this book without having read the previous one(s)?

## Output Format

Return valid JSON:
```json
{
  "scores": {
    "structural_integrity": 0,
    "character_depth": 0,
    "hook_discipline": 0,
    "thematic_resonance": 0,
    "conflict_architecture": 0,
    "pacing_and_proportion": 0,
    "lore_and_continuity": 0,
    "world_building_coherence": 0,
    "series_coherence": 0,
    "overall": 0
  },
  "flagged_issues": [
    "Specific issue description with suggested fix"
  ]
}
```

Set `lore_and_continuity` to `null` if the project's canon_status is "original" or there's no franchise context. Set `series_coherence` to `null` if meta.project_scope is "standalone". Compute `overall` as the average of non-null dimension scores.

Be specific in flagged_issues — name characters, plot points, and hooks by name. Generic feedback like "characters could be deeper" is useless. Say exactly what's weak and why.
