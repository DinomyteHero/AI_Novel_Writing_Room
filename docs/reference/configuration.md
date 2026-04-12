# Configuration

All configuration files are in the `config/` directory.

## settings.yaml

The main configuration file. Controls deployment mode, model routing, and pipeline behavior.

### Deployment Mode

```yaml
deployment_mode: cloud  # local | cloud | hybrid
```

### Local Models

```yaml
models:
  local:
    inference_backend: llama-server
    base_url: http://localhost:8080/v1
    models:
      primary_moe: Qwen3-30B-A3B-Instruct-2507-Q4_K_M
      fast_moe: Gemma-4-26B-A4B-Q5_K_M
      utility: Qwen3.5-9B-Q5_K_M
      embedding: nomic-embed-text
    default_params:
      primary_moe:
        temperature: 0.7
        min_p: 0.05
        top_p: 1.0
        top_k: 0
        repetition_penalty: 1.1
      prose:
        temperature: 1.0
        min_p: 0.05
      utility:
        temperature: 0.3
        min_p: 0.1
```

### Cloud Models

```yaml
models:
  cloud:
    provider: openrouter
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY    # Environment variable name
    models:
      primary: anthropic/claude-sonnet-4-20250514
      premium: anthropic/claude-opus-4-20250514
      budget: anthropic/claude-haiku-4-5-20251001
      primary_moe: google/gemma-4-31b-it:free
      fast_moe: google/gemma-4-31b-it:free
      utility: google/gemma-4-26b-a4b-it:free
      prose: google/gemma-4-31b-it:free
```

The cloud section includes both free and paid model alternatives (paid options are commented out).

### Timeout Settings

Both local and cloud model sections accept a `timeout_seconds` field controlling the HTTP client timeout for API calls:

```yaml
models:
  local:
    timeout_seconds: 300   # Default: 300 seconds
  cloud:
    timeout_seconds: 300   # Default: 300 seconds
```

Increase this value if you experience timeouts during large requests (e.g., scene card generation for novels with 25+ chapters). The cloud timeout was previously hardcoded at 120 seconds, which was insufficient for multi-scene outline generation.

### Agent Routing

Maps each agent role to a backend, model tier, and optional parameter overrides:

```yaml
agent_routing:
  plot_architect:    { backend: local, model: primary_moe, params: { temperature: 0.4 } }
  prose_stylist:     { backend: local, model: primary_moe, params: { temperature: 0.9 } }
  gate_critic:       { backend: local, model: primary_moe, params: { temperature: 0.3 } }
  craft_editor:      { backend: local, model: primary_moe, params: { temperature: 0.4 } }
  canon_expert:      { backend: local, model: fast_moe }
  summarizer:        { backend: local, model: utility, params: { temperature: 0.2 } }
  character_specialist: { backend: local, model: primary_moe, params: { temperature: 0.4 } }
  voice_checker:     { backend: cloud, model: primary, params: { temperature: 0.3 } }
  judge_evaluator:   { backend: cloud, model: primary, params: { temperature: 0.2 } }
  concept_workshop:  { backend: cloud, model: primary, params: { temperature: 0.7 } }
  outline_planner:   { backend: cloud, model: primary, params: { temperature: 0.5, max_tokens: 16384 } }
  seed_builder:      { backend: cloud, model: primary, params: { temperature: 0.3, max_tokens: 16384 } }
  # Revision agents, dialogue polish, etc. also defined here
```

When `deployment_mode` is `cloud`, the `backend` field in agent routing is overridden -- all agents use cloud models.

### Pipeline Settings

```yaml
pipeline:
  max_structural_retries: 3
  max_voice_retries: 2
  # chapter_output_dir: defaults to output/{project-slug}/chapters/
  # run_ledger_path: auto-resolved per-project at data/projects/<slug>/state/run_ledger.db
```

### Local Inference Settings

```yaml
local_inference:
  gpu_layers: 99
  expert_offload: CPU
  context_size: 32768
  batch_size: 512
  flash_attention: true
```

### Worldbuilding Settings

```yaml
worldbuilding:
  db_path: data/worldbuilding.db              # SQLite database for universes/lore
  vectors_dir: data/worldbuilding_vectors     # ChromaDB persistent directory
  default_top_k: 5                            # Default semantic retrieval limit
  walk_parents: true                          # Walk universe inheritance chain
  include_provisional_in_context: false       # Include provisional entries (flagged)
  auto_extraction:
    enabled: true                             # Run extraction after each chapter
    auto_promote: false                       # Skip quarantine on extracted entries
  terminology:
    always_include: true                      # Bypass top-K for terminology
  reconciliation:
    run_on_startup: true                      # Run SQLite/ChromaDB reconciliation at startup
    interval_minutes: 60                      # Periodic reconciliation (0 = disabled)
```

The `lore_extractor` agent routing is also defined in `agent_routing`:

```yaml
agent_routing:
  lore_extractor: { backend: local, model: utility, params: { temperature: 0.2 } }
```

---

## failure_codes.yaml

Defines the 19 failure codes used by GateCritic, organized into 3 categories:

### Structural (10 codes)

| Code | Description |
|------|-------------|
| CONTINUITY_CONTRADICTION | Scene contradicts established story state |
| WEAK_TURNING_POINT | Scene ends in roughly the same state it began |
| MISSING_TURNING_POINT | No identifiable shift in scene dynamics |
| UNEARNED_RESOLUTION | Conflict resolved without sufficient buildup or cost |
| STRUCTURAL_PHASE_VIOLATION | Scene actions violate Brooks phase constraints |
| PROMISE_BROKEN | Setup or foreshadow contradicted without intentional subversion |
| MOTIVATION_GAP | Character action lacks traceable motivation |
| CHARACTER_ARC_STALL | POV character has not progressed Weiland arc phase within expected structural window |
| HOOK_VIOLATION | Unauthorized hook planted, or required hook advancement missed |
| SUBPLOT_DRIFT | Active subplot ignored or resolved subplot reopened without justification |

### Voice (5 codes)

| Code | Description |
|------|-------------|
| OOC_DIALOGUE | Character speaks inconsistently with voice profile |
| OOC_ACTION | Character acts inconsistently with established dimensions |
| TELLING_NOT_SHOWING | Emotional state narrated rather than demonstrated |
| TERMINOLOGY_DRIFT | Term from registry spelled differently or used inconsistently |
| VOICE_DEFINITION_VIOLATION | Prose violates voice definition rules (anti-slop, anti-patterns) |

### Polish (4 codes)

| Code | Description |
|------|-------------|
| EXPOSITION_LEAK | World-building info dumped outside natural scene flow |
| PACING_FLATLINE | Insufficient sentence/event variety |
| PROSE_CLICHE_BURST | Multiple banned phrases or AI-tells detected |
| CANON_VIOLATION | Scene contradicts established franchise lore |

### Routing

| Category | Action |
|----------|--------|
| fail_structural | full_rewrite (back to ProseStylist with failure context) |
| fail_voice | targeted_revision (ProseStylist with specific notes) |
| fail_polish | craft_edit (CraftEditor, non-blocking) |

---

## negative_constraints.yaml

Defines banned phrases and structural rules for quality checking.

### Banned Phrases

5 categories:
- **faux_profundity** -- Overused portentous constructions
- **sensory_cliches** -- Stock physical descriptions
- **magic_adverbs** -- Lazy modifier patterns
- **ai_tells** -- Words that signal AI-generated text (e.g., "delve", "tapestry", "nuanced", "multifaceted")

### Structural Rules

| Rule | Default | Description |
|------|---------|-------------|
| max_adverb_density | 0.02 | Max ratio of adverbs to total words |
| min_sentence_length_variance | 0.3 | Minimum coefficient of variation in sentence length |
| max_same_opener_pct | 0.15 | Max percentage of paragraphs starting with the same pattern |
| metaphor_cooldown_paragraphs | 8 | Minimum paragraphs between figurative language uses |

---

## eval_rubric.yaml

Defines the 5 dimensions used by JudgeEvaluator (LLM-as-judge):

| Dimension | 1-3 | 4-6 | 7-8 | 9-10 |
|-----------|-----|-----|-----|------|
| narrative_engagement | flat | adequate | compelling | unputdownable |
| character_authenticity | cardboard | adequate | vivid | unforgettable |
| prose_craftsmanship | clumsy | adequate | polished | masterful |
| thematic_resonance | absent | present | resonant | profound |
| structural_contribution | filler | functional | essential | irreplaceable |
