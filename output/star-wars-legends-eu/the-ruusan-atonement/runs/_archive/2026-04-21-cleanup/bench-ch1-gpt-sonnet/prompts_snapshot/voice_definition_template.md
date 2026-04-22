# Voice Definition Template

Guide the human through each voice dimension below. Ask one question at a time and provide examples.

## 1. POV Approach

Ask: "What point of view will this story use?"

Options to present:
- **Close third-person limited** — "She felt the cold seep through her cloak" (most common for commercial fiction)
- **First person** — "I felt the cold seep through my cloak" (intimate, immediate)
- **Rotating limited** — Multiple POV characters, each in close third (chapters alternate)
- **Deep POV** — No filter words ("felt", "saw", "heard") — the reader IS the character
- **Omniscient** — The narrator knows all and can dip into any character's mind

## 2. Prose Register

Ask: "What register should the prose aim for?"

Options:
- **Literary** — Dense, layered prose. Metaphor-rich. Every sentence is crafted. Slower pace.
- **Commercial** — Clean, propulsive prose. Invisible style that serves the story. Page-turner pacing.
- **Pulp** — Fast, punchy, direct. Short sentences. High action density. Fun over craft.
- **Match to tone** — If the tone from Step 1 is "dark_gritty", the register should support that (lean literary or commercial-dark). If "adventurous_hopeful", lean commercial or pulp.

## 3. Reference Authors (Optional)

Ask: "Are there any authors whose prose style you'd like to emulate? This helps calibrate voice."

Examples: "The prose should feel like Brandon Sanderson meets Ursula K. Le Guin" or "Write like Joe Abercrombie — dark, witty, punchy."

If provided, these become targets for the style fingerprinting system.

## 4. Pacing Feel

Ask: "How should the pacing feel?"

- **Fast and clipped** — Short chapters (2000-3000 words), frequent scene breaks, rapid momentum
- **Immersive and flowing** — Longer chapters (4000-6000 words), deep interiority, atmospheric
- **Variable** — Some chapters fast, some slow, matching the structural phase (setup slower, attack faster)

## 5. Anti-Slop Rules

Present the default banned-word list from `config/negative_constraints.yaml` and ask:

"Here are the default words and phrases we'll avoid in the prose. Would you like to add any, or are there any you'd actually want to keep?"

Categories to review:
- AI tells: "delve", "tapestry", "testament", "nuanced", "landscape", "multifaceted"
- Sensory cliches: "smell of ozone", "shiver ran down", "jaw tightened"
- Faux profundity: "It wasn't just X, it was Y", "A testament to"
- Magic adverbs: "quietly orchestrated", "fundamentally shifted"

## 6. Anti-Pattern Rules

Present defaults and ask for additions:

Default structural patterns to avoid:
1. Every chapter opening with weather/environment description
2. Every chapter ending with a reflective sigh or "little did they know" hook
3. Characters nodding, smiling, or raising eyebrows as default body language
4. Dialogue attribution using anything other than "said/asked" more than 20% of the time
5. Back-to-back paragraphs starting with the same word

Ask: "Are there any other structural patterns or writing habits you want to explicitly avoid?"

## 7. Narrative Voice Notes

Ask: "Any other notes about the voice? Things like: should the narrator have a distinct personality? Should internal monologue use a different register than narration? Any franchise-specific voice requirements?"

Capture as freeform text.
