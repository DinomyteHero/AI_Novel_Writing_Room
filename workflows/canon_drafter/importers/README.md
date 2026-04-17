# canon-drafter — plain_markdown importer

```markdown
# Canon Profile

## Canon Constraints
continuity: Star Wars Legends EU (post-Wookieepedia AU)
divergence_point: post-Ruusan crisis

## Canon Preserved
- Force philosophy as established in Legends
- Sith Code references

## Canon Overridden
- Bane's escape from Ruusan

## Style Constraints
- No 21st-century idioms
- No real-world brand names

## Canon Profile
franchise: Star Wars (Legends EU)
continuity: Legends
continuity_description: Pre-Disney expanded universe through 2014.
era_description: Old Republic, ~1000 BBY
narrative_register: space opera with weight

## Cross-Continuity Violations
- midi-chlorians (Disney canon)
- Grogu

## Meta-Reference Rules
- No "Force-sensitive" Wookieepedia tags

## Force Mechanics
primary_rule: The Force responds to intention; mastery comes from discipline.
canon_grounding: Original trilogy + Legends-era novels.

## Force Implications
- Sith corruption is irreversible without confrontation
- Light/Dark balance is a falsehood

### Term: Bogan
term: Bogan
definition: Pre-Republic Sith term for the dark side current of the Force.
category: cultural_term
first_appearance: 3

### Term: Ashla
term: Ashla
definition: Pre-Republic Sith term for the light side current of the Force.
category: cultural_term
```

Each `### Term: <name>` subsection produces one entry in
`terminology_registry`. `definition` and `category` are required per
entry; `aliases` (bullets), `first_appearance`, and `usage_notes` are
optional.
