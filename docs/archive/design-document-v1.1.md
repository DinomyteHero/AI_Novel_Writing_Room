# AI Writers' Room — Technical Design Document v1.2

## Changelog (v1.0 → v1.1)

- **Model stack overhaul**: Replaced Qwen3.5-27B dense as primary reasoning model with Qwen3-30B-A3B-Instruct-2507 (MoE, 3.3B active, fits on 12GB GPU). Added Qwen3.5-35B-A3B as Phase 3 upgrade candidate (requires CPU expert offload).
- **Serving backend**: Changed primary inference backend from Ollama to llama-server. Qwen3.5 models do not currently work with Ollama due to separate mmproj vision files. Ollama remains available for Qwen3/Gemma models.
- **Dropped gpt-oss-20b**: Native MXFP4 not supported on Ada Lovelace (RTX 4070); real-world 12GB VRAM performance is unacceptably slow. Kept as cloud-only evaluation option.
- **Dropped Qwopus-MoE**: Community finetune with uncertain stability. Replaced with Qwen3-30B-A3B for critic role (same MoE efficiency, better ecosystem support).
- **Added Story Physics layer**: New planning stage between concept seed and scene cards — causality chains, revelation map, promise/payoff tracking, character-pressure matrix.
- **Added structured failure codes**: Critic rejections now return machine-readable failure labels, not freeform prose.
- **Split Editor/Critic into two modes**: Gate Critic (pass/fail on structure) and Craft Editor (improvement notes without blocking).
- **Added truth/belief/narrative-exposure separation**: Three knowledge-state layers in story state DB (Phase 2).
- **Added canon evidence ranking**: Retrieved canon now includes confidence score, source class, and continuity tag.
- **Formalized orchestrator event model**: Typed events, append-only run ledger, diffed state mutations before commit.

### v1.1 → v1.2 (Phase 5)

- **Expanded Concept Workshop**: 6 steps → 10 with series branching, Weiland character arcs, voice discovery, subplot/hook architecture, terminology registry, and adversarial stress test
- **6 new SQLite tables**: `character_arcs`, `subplot_board`, `hook_ledger`, `terminology_registry`, `propagation_debts`, `style_fingerprint`
- **Schema migration infrastructure**: Version tracking with forward-only migrations
- **5 new failure codes**: `CHARACTER_ARC_STALL`, `HOOK_VIOLATION`, `SUBPLOT_DRIFT`, `TERMINOLOGY_DRIFT`, `VOICE_DEFINITION_VIOLATION`
- **Hook governance**: Admission control and advancement tracking with hook debt enforcement
- **Anti-slop upstream injection**: ContextAssembler injects anti-slop directives into ProseStylist prompts
- **Manuscript reviewer agent**: Dual-persona (reader + editor), premium model tier
- **Style fingerprinting system**: Captures and enforces prose style metrics per project
- **Series support**: `series_seed.json` schema, SeriesManager, transition snapshots, retroactive promotion
- **State diff old_value verification**: Optimistic conflict detection on state mutations

---

## System Overview

The AI Writers' Room is a multi-agent fiction generation system that produces novel-length (60–80K word) franchise fanfiction through a two-phase workflow: human-collaborative planning followed by autonomous multi-agent drafting and revision.

The system supports three deployment modes:
- **Local** — all inference on consumer hardware (RTX 4070 12GB VRAM + 32GB RAM)
- **Cloud** — all inference via cloud APIs (Claude, GPT-4, Gemini via OpenRouter)
- **Hybrid** — local for high-volume drafting, cloud for critique and evaluation

### Core Principles

1. **Hierarchical plan-and-write** — no prose is generated until the full structural plan is approved
2. **Brooks's Story Engineering** — the four-part structure (Setup/Response/Attack/Resolution) governs all narrative pacing
3. **Generate-critique-revise loops** — no chapter reaches the manuscript without passing adversarial evaluation
4. **Separation of concerns** — each agent handles one cognitive task with its own model, temperature, and prompt template
5. **External state management** — the LLM's context window is never used as the primary state tracker
6. **Story Physics before prose** — causality, revelation timing, and promise/payoff tracking are validated before any drafting begins

---

## Architecture

### High-Level Components

```
┌─────────────────────────────────────────────────────┐
│  Phase A: Human Collaboration (Stages 1–7)          │
│  ┌──────────────┐  ┌───────────────────────────┐    │
│  │ Concept      │→ │ Planning Pipeline          │    │
│  │ Workshop     │  │ (Premise → Characters →    │    │
│  │ (Stage 1)    │  │  Outline → Beats → Scenes) │    │
│  └──────────────┘  └───────────────────────────┘    │
│                           ↓                          │
│              ┌─────────────────────┐                 │
│              │ Story Physics Pass  │                 │
│              │ (Causality, Reveals,│                 │
│              │  Promise/Payoff)    │                 │
│              └─────────────────────┘                 │
│                           ↓                          │
│               [Story Bible — JSON/MD]                │
│                           ↓                          │
│              ┌─────────────────────┐                 │
│              │  Human Sign-off     │                 │
│              └─────────────────────┘                 │
└─────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────┐
│  Phase B: Autonomous Pipeline (Stages 8–9)          │
│  ┌──────────────────────────────────────────────┐   │
│  │ Per-Chapter Loop:                             │   │
│  │ Orchestrator → Plot Architect → Canon Expert  │   │
│  │ → Prose Stylist → Gate Critic → (if pass)     │   │
│  │ → Craft Editor → State Update                 │   │
│  └──────────────────────────────────────────────┘   │
│                           ↓                          │
│  ┌──────────────────────────────────────────────┐   │
│  │ Three-Band Revision Pipeline                  │   │
│  │ Structural/Continuity → Scene/Emotion →       │   │
│  │ Line/Copy                                     │   │
│  │ (Expand to five passes if metrics show benefit)│  │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
                           ↓
              ┌─────────────────────┐
              │  Final Manuscript    │
              │  (.md / .docx / .epub)│
              └─────────────────────┘
```

### Directory Structure

```
ai-writers-room/
├── README.md
├── config/
│   ├── settings.yaml              # Deployment mode, model assignments, API keys
│   ├── failure_codes.yaml         # Structured failure taxonomy for critic
│   ├── franchise_configs/
│   │   ├── star_wars_legends.yaml  # Canon rules, style guide, era definitions
│   │   ├── star_wars_canon.yaml
│   │   ├── marvel_mcu.yaml
│   │   └── star_trek.yaml
│   └── negative_constraints.yaml   # Banned phrases, anti-OOC rules, AI-tell detection
├── src/
│   ├── __init__.py
│   ├── main.py                     # CLI entry point
│   ├── model_router.py             # Routes agent calls to local/cloud backends
│   ├── orchestrator.py             # Event-driven state machine
│   ├── run_ledger.py               # Append-only log of all pipeline events
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base_agent.py           # Abstract agent class
│   │   ├── showrunner.py           # Orchestrator/lead agent
│   │   ├── plot_architect.py       # Brooks structure management
│   │   ├── character_specialist.py # Voice profiles, OOC detection
│   │   ├── canon_expert.py         # RAG-powered lore validation
│   │   ├── prose_stylist.py        # Primary prose generator
│   │   ├── gate_critic.py          # Pass/fail structural evaluation with failure codes
│   │   ├── craft_editor.py         # Non-blocking improvement notes (voice, polish)
│   │   ├── summarizer.py           # Chapter/scene compression
│   │   └── manuscript_reviewer.py  # Dual-persona manuscript review (premium tier)
│   ├── concept_workshop/
│   │   ├── series_manager.py       # Series seed lifecycle, transition snapshots, retroactive promotion
│   │   ├── voice_discovery.py      # Voice definition extraction and fingerprinting
│   │   └── stress_test.py          # Adversarial stress test for concept seeds
│   ├── planning/
│   │   ├── __init__.py
│   │   ├── story_physics.py        # Causality chains, revelation map, promise/payoff
│   │   ├── scene_economics.py      # Chapter-level "why now?" validation
│   │   └── pressure_matrix.py      # Character-pressure tracking per chapter
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── story_state.py          # SQLite state tracker
│   │   ├── knowledge_layers.py     # Truth DB, Belief DB, Narrative Exposure DB
│   │   ├── chapter_memory.py       # ChromaDB chapter summaries
│   │   ├── context_assembler.py    # Builds per-scene prompt payloads
│   │   ├── state_diff.py           # Post-generation state updates
│   │   └── contradiction_scanner.py # Post-chapter consistency check
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── canon_db.py             # Vector DB interface (ChromaDB/LanceDB)
│   │   ├── embedding.py            # Embedding model wrapper
│   │   ├── hybrid_search.py        # Semantic + keyword/BM25 fusion
│   │   ├── canon_evidence.py       # Evidence ranking: claim + source + confidence + tag
│   │   └── wiki_ingester.py        # MediaWiki API → chunked vectors
│   ├── quality/
│   │   ├── __init__.py
│   │   ├── repetition_detector.py  # Word freq, n-gram, semantic similarity
│   │   ├── pacing_analyzer.py      # Event density, sentence length variance
│   │   ├── voice_checker.py        # Character voice fidelity scoring
│   │   ├── slop_detector.py        # AI-tell word list, burstiness check
│   │   ├── style_fingerprint.py    # Prose style metrics capture and enforcement
│   │   └── metrics_dashboard.py    # Per-chapter quality scores
│   ├── revision/
│   │   ├── __init__.py
│   │   ├── structural_continuity.py # Band 1: plot holes, arc consistency, timeline
│   │   ├── scene_emotion.py         # Band 2: conflict, turning points, show-don't-tell
│   │   └── line_copy.py             # Band 3: prose quality, grammar, style consistency
│   ├── export/
│   │   ├── __init__.py
│   │   ├── markdown_export.py      # Working format, git-friendly
│   │   ├── docx_export.py          # Standard manuscript format
│   │   └── epub_export.py          # Reading/review format
│   └── ui/
│       ├── __init__.py
│       ├── app.py                  # Web UI entry point (FastAPI)
│       ├── static/
│       └── templates/
├── data/
│   ├── story_bibles/               # Phase A outputs (per-project)
│   ├── manuscripts/                # Phase B outputs (git-versioned)
│   ├── canon_dbs/                  # Franchise vector databases
│   ├── eval_corpus/                # Gold-standard chapters for quality benchmarking
│   └── models/                     # Local model configs
├── prompts/
│   ├── concept_workshop.md         # Stage 1 system prompt template
│   ├── voice_definition_template.md # Template for voice discovery output
│   ├── stress_test_prompt.md       # Adversarial stress test prompt
│   ├── story_physics.md            # Story Physics pass prompt template
│   ├── agent_system_prompts/
│   │   ├── showrunner.md
│   │   ├── plot_architect.md
│   │   ├── character_specialist.md
│   │   ├── canon_expert.md
│   │   ├── prose_stylist.md
│   │   ├── gate_critic.md
│   │   ├── craft_editor.md
│   │   └── manuscript_reviewer.md  # Dual-persona manuscript review prompt
│   └── revision_prompts/
│       ├── structural_continuity.md
│       ├── scene_emotion.md
│       └── line_copy.md
├── schemas/
│   ├── concept_seed.json           # JSON Schema for Stage 1 output
│   ├── series_seed.json            # JSON Schema for multi-book series planning
│   ├── story_physics.json          # JSON Schema for Story Physics pass output
│   ├── story_bible.json            # JSON Schema for complete plan
│   ├── scene_card.json             # JSON Schema for per-scene specs
│   ├── character_sheet.json        # JSON Schema for character profiles
│   ├── state_diff.json             # JSON Schema for post-gen state updates
│   ├── failure_code.json           # JSON Schema for structured critic rejections
│   └── canon_evidence.json         # JSON Schema for ranked canon retrieval
├── tests/
│   ├── test_model_router.py
│   ├── test_context_assembler.py
│   ├── test_quality_metrics.py
│   ├── test_story_physics.py
│   ├── test_failure_codes.py
│   └── test_pipeline_integration.py
└── requirements.txt
```

---

## Story Physics Layer (NEW)

The Story Physics pass runs between concept seed approval and scene card generation. It validates that the structural plan has the causal and emotional infrastructure to sustain a novel — preventing the common failure mode of "structurally correct but emotionally flat" output.

### Story Physics Components

**1. Causality Chain Validation**
Every major plot event must have a traceable cause upstream and at least one consequence downstream. The system builds a directed graph of events and flags any that are causally orphaned (no upstream cause) or causally dead (no downstream effect).

**2. Revelation Map**
Tracks what information the reader learns and when. Ensures:
- No critical reveals happen too early (deflating tension) or too late (feeling arbitrary)
- Information released to the reader is released in an order that builds mystery, not confusion
- Red herrings have both planting and subversion points

**3. Promise/Payoff Ledger**
Every narrative promise (setup, foreshadowing, Chekhov's gun, thematic question) is tracked with:
- `planted_chapter`: where the promise appears
- `payoff_chapter`: where it resolves (or subverts)
- `type`: setup_payoff | foreshadow | chekhov | thematic
- `status`: unfulfilled | fulfilled | subverted

At any structural milestone, the system flags unfulfilled promises that should have resolved by now, and promises that lack any planned payoff.

**4. Character-Pressure Matrix**
For each chapter, tracks what external and internal pressures are active on each POV character. Ensures:
- No POV character coasts through more than one consecutive chapter without meaningful pressure
- Pressure escalates across acts (Part 1 < Part 2 < Part 3)
- The climax concentrates maximum pressure on the protagonist

**5. Chapter-Level "Why Now?" Check**
Every scene card must answer: "Why does this scene happen at this point in the story, and not earlier or later?" If the answer is "because the outline says so," the scene card is flagged for causal strengthening.

### Story Physics Schema

```json
{
  "title": "StoryPhysics",
  "type": "object",
  "required": ["causality_chains", "revelation_map", "promise_payoff_ledger", "pressure_matrix"],
  "properties": {
    "causality_chains": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["event_id", "description", "causes", "consequences"],
        "properties": {
          "event_id": { "type": "string" },
          "description": { "type": "string" },
          "chapter": { "type": "integer" },
          "causes": { "type": "array", "items": { "type": "string" }, "description": "event_ids that cause this" },
          "consequences": { "type": "array", "items": { "type": "string" }, "description": "event_ids caused by this" }
        }
      }
    },
    "revelation_map": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["info_id", "content", "revealed_chapter", "significance"],
        "properties": {
          "info_id": { "type": "string" },
          "content": { "type": "string" },
          "revealed_chapter": { "type": "integer" },
          "significance": { "type": "string", "enum": ["minor", "moderate", "major", "climactic"] },
          "who_learns": { "type": "string", "description": "reader | specific_character | both" }
        }
      }
    },
    "promise_payoff_ledger": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["promise_id", "description", "planted_chapter", "type", "status"],
        "properties": {
          "promise_id": { "type": "string" },
          "description": { "type": "string" },
          "planted_chapter": { "type": "integer" },
          "payoff_chapter": { "type": "integer" },
          "type": { "type": "string", "enum": ["setup_payoff", "foreshadow", "chekhov", "thematic"] },
          "status": { "type": "string", "enum": ["unfulfilled", "fulfilled", "subverted"] }
        }
      }
    },
    "pressure_matrix": {
      "type": "object",
      "description": "Keys are character names, values are arrays of per-chapter pressure objects",
      "additionalProperties": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "chapter": { "type": "integer" },
            "external_pressure": { "type": "string" },
            "internal_pressure": { "type": "string" },
            "pressure_level": { "type": "integer", "minimum": 1, "maximum": 10 }
          }
        }
      }
    }
  }
}
```

---

## Data Models (JSON Schemas)

### Concept Seed Schema (Stage 1 Output)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ConceptSeed",
  "type": "object",
  "required": ["meta", "premise", "conflict", "theme", "ensemble_cast", "canon_constraints"],
  "properties": {
    "meta": {
      "type": "object",
      "required": ["project_title", "franchise", "canon_status", "era", "tone", "target_word_count"],
      "properties": {
        "project_title": { "type": "string" },
        "franchise": { "type": "string" },
        "canon_status": { "type": "string", "enum": ["canon_compliant", "AU"] },
        "era": { "type": "string" },
        "tone": { "type": "string", "enum": ["dark_gritty", "adventurous_hopeful", "political_intrigue", "character_study"] },
        "target_word_count": { "type": "integer", "minimum": 40000, "maximum": 120000 },
        "target_chapters": { "type": "integer", "minimum": 15, "maximum": 40 },
        "pov_structure": { "type": "string" }
      }
    },
    "premise": {
      "type": "object",
      "required": ["what_if", "central_dramatic_question", "logline"],
      "properties": {
        "what_if": { "type": "string", "minLength": 50 },
        "central_dramatic_question": { "type": "string" },
        "logline": { "type": "string", "maxLength": 500 }
      }
    },
    "conflict": {
      "type": "object",
      "required": ["primary_antagonistic_force", "lock_in_mechanism"],
      "properties": {
        "primary_antagonistic_force": {
          "type": "object",
          "required": ["type", "motivation", "escalation"],
          "properties": {
            "type": { "type": "string" },
            "identity": { "type": "string" },
            "motivation": { "type": "string", "minLength": 50 },
            "escalation": { "type": "string", "minLength": 100 }
          }
        },
        "secondary_pressures": {
          "type": "array",
          "items": { "type": "string" },
          "minItems": 1
        },
        "lock_in_mechanism": { "type": "string", "minLength": 30 }
      }
    },
    "theme": {
      "type": "object",
      "required": ["thematic_premise", "thematic_argument", "how_each_arc_tests_theme"],
      "properties": {
        "thematic_premise": { "type": "string" },
        "thematic_argument": { "type": "string", "minLength": 100 },
        "how_each_arc_tests_theme": {
          "type": "object",
          "additionalProperties": { "type": "string" }
        }
      }
    },
    "protagonist_arc_type": {
      "type": "string",
      "enum": ["change", "steadfast", "fall", "rise"]
    },
    "ensemble_cast": {
      "type": "array",
      "minItems": 2,
      "maxItems": 6,
      "items": {
        "type": "object",
        "required": ["name", "role", "three_dimensions", "voice_notes"],
        "properties": {
          "name": { "type": "string" },
          "role": { "type": "string" },
          "age": { "type": "string" },
          "force_status": { "type": "string" },
          "three_dimensions": {
            "type": "object",
            "required": ["surface", "backstory_inner_demons", "action_under_pressure"],
            "properties": {
              "surface": { "type": "string", "minLength": 50 },
              "backstory_inner_demons": { "type": "string", "minLength": 50 },
              "action_under_pressure": { "type": "string", "minLength": 50 }
            }
          },
          "voice_notes": { "type": "string", "minLength": 30 }
        }
      }
    },
    "force_mechanics": {
      "type": "object",
      "properties": {
        "primary_rule": { "type": "string" },
        "implications": { "type": "array", "items": { "type": "string" } },
        "canon_grounding": { "type": "string" }
      }
    },
    "canon_constraints": {
      "type": "object",
      "required": ["continuity", "canon_preserved", "style_constraints"],
      "properties": {
        "continuity": { "type": "string" },
        "divergence_point": { "type": "string" },
        "canon_preserved": { "type": "array", "items": { "type": "string" } },
        "canon_overridden": { "type": "array", "items": { "type": "string" } },
        "style_constraints": { "type": "array", "items": { "type": "string" } }
      }
    },
    "structural_notes": {
      "type": "object",
      "properties": {
        "brooks_alignment": {
          "type": "object",
          "properties": {
            "part_1_setup": { "type": "string" },
            "first_plot_point": { "type": "string" },
            "part_2_response": { "type": "string" },
            "midpoint": { "type": "string" },
            "part_3_attack": { "type": "string" },
            "second_plot_point": { "type": "string" },
            "part_4_resolution": { "type": "string" }
          }
        }
      }
    }
  }
}
```

### Phase 5 Concept Seed Extensions (Optional Fields)

The following optional fields extend the concept seed schema for Phase 5 features. All are backward-compatible — existing seeds without these fields remain valid.

| Field | Type | Description |
|-------|------|-------------|
| `meta.project_scope` | `string` enum: `standalone`, `series` | Whether this is a single book or part of a series |
| `meta.series` | `object` | Series metadata: `series_id`, `book_number`, `total_planned` |
| `ensemble_cast[].weiland_arc` | `object` | K.M. Weiland arc: `lie`, `ghost`, `want`, `need`, `arc_type` (positive/flat/negative) |
| `voice_definition` | `object` | Prose voice targets: POV style, sentence rhythm, diction register, sensory bias |
| `subplot_board` | `array` | Planned subplots with `thread_id`, `type`, `arc_shape`, `chapter_range` |
| `hook_map` | `object` | Hook architecture: `opening_hook`, `chapter_hooks[]`, `act_hooks[]`, `series_hooks[]` |
| `revelation_schedule` | `array` | Ordered reveal plan: `info_id`, `chapter`, `method`, `dramatic_impact` |
| `terminology_registry` | `array` | Project-specific terms: `term`, `definition`, `first_use_chapter`, `aliases` |
| `stress_test_results` | `object` | Output from adversarial stress test: `vulnerabilities[]`, `mitigations[]`, `risk_score` |

### Scene Card Schema

```json
{
  "title": "SceneCard",
  "type": "object",
  "required": ["chapter_number", "scene_number", "structural_phase", "pov_character", "mission", "conflict", "turning_point"],
  "properties": {
    "chapter_number": { "type": "integer" },
    "scene_number": { "type": "integer" },
    "structural_phase": {
      "type": "string",
      "enum": ["setup", "first_plot_point", "response", "first_pinch", "midpoint", "attack", "second_pinch", "second_plot_point", "resolution", "climax"]
    },
    "pov_character": { "type": "string" },
    "mission": { "type": "string", "description": "The single purpose this scene serves" },
    "why_now": { "type": "string", "description": "Why this scene happens at this point and not earlier/later — causal justification" },
    "opening_hook": { "type": "string" },
    "conflict": { "type": "string", "description": "What opposes the POV character in this scene" },
    "conflict_type": { "type": "string", "enum": ["internal", "interpersonal", "external", "environmental"] },
    "turning_point": { "type": "string", "description": "How the scene ends differently than it began" },
    "closing_hook": { "type": "string", "description": "Unresolved tension propelling the next scene" },
    "characters_present": { "type": "array", "items": { "type": "string" } },
    "setting": { "type": "string" },
    "sensory_details": { "type": "string", "description": "Franchise-specific environmental grounding" },
    "emotional_trajectory": { "type": "string", "description": "Start emotion → end emotion for POV" },
    "plot_threads_advanced": { "type": "array", "items": { "type": "string" } },
    "promises_planted": { "type": "array", "items": { "type": "string" }, "description": "promise_ids from Story Physics ledger planted in this scene" },
    "promises_paid": { "type": "array", "items": { "type": "string" }, "description": "promise_ids resolved or subverted in this scene" },
    "canon_elements_needed": { "type": "array", "items": { "type": "string" } },
    "target_word_count": { "type": "integer" },
    "notes": { "type": "string" }
  }
}
```

### Phase 5 Scene Card Extensions (Optional Fields)

| Field | Type | Description |
|-------|------|-------------|
| `active_subplots` | `array` of `string` | `thread_id` references from subplot board active in this scene |
| `hook_actions` | `array` of `object` | Hook operations: `{hook_id, action: "plant"\|"advance"\|"resolve"}` |
| `revelations` | `array` of `string` | `info_id` references from revelation schedule revealed in this scene |
| `pov_arc_phase` | `string` | Current Weiland arc phase for the POV character (e.g., `orphan`, `wanderer`, `warrior`, `martyr`) |
| `arc_phase_transition` | `object` | If the POV character transitions arc phase in this scene: `{from, to, trigger}` |

### Structured Failure Code Schema (NEW)

```json
{
  "title": "CriticFailure",
  "type": "object",
  "required": ["verdict", "failure_codes", "severity"],
  "properties": {
    "verdict": { "type": "string", "enum": ["pass", "fail_structural", "fail_voice", "fail_polish"] },
    "failure_codes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["code", "location", "description"],
        "properties": {
          "code": {
            "type": "string",
            "enum": [
              "CONTINUITY_CONTRADICTION",
              "OOC_DIALOGUE",
              "OOC_ACTION",
              "WEAK_TURNING_POINT",
              "MISSING_TURNING_POINT",
              "EXPOSITION_LEAK",
              "PACING_FLATLINE",
              "PROSE_CLICHE_BURST",
              "UNEARNED_RESOLUTION",
              "CANON_VIOLATION",
              "PROMISE_BROKEN",
              "MOTIVATION_GAP",
              "TELLING_NOT_SHOWING",
              "STRUCTURAL_PHASE_VIOLATION",
              "CHARACTER_ARC_STALL",
              "HOOK_VIOLATION",
              "SUBPLOT_DRIFT",
              "TERMINOLOGY_DRIFT",
              "VOICE_DEFINITION_VIOLATION"
            ]
          },
          "location": { "type": "string", "description": "Paragraph number or text span reference" },
          "description": { "type": "string", "description": "Specific explanation of the failure" },
          "fix_hint": { "type": "string", "description": "Suggested direction for revision" }
        }
      }
    },
    "severity": { "type": "string", "enum": ["blocking", "non_blocking"] },
    "route_to": {
      "type": "string",
      "enum": ["full_rewrite", "targeted_revision", "craft_edit", "line_edit"],
      "description": "Where to send the scene based on failure type"
    },
    "structural_score": { "type": "number", "minimum": 0, "maximum": 1 },
    "voice_score": { "type": "number", "minimum": 0, "maximum": 1 },
    "polish_score": { "type": "number", "minimum": 0, "maximum": 1 }
  }
}
```

Failure routing logic:
- `fail_structural` → route to `full_rewrite` (back to Prose Stylist with failure context)
- `fail_voice` → route to `targeted_revision` (Prose Stylist with specific OOC/voice notes)
- `fail_polish` → route to `craft_edit` (Craft Editor for non-blocking improvement, does not re-enter gate)

### Canon Evidence Schema (NEW)

```json
{
  "title": "CanonEvidence",
  "type": "object",
  "required": ["claim", "source_class", "confidence", "continuity_tag"],
  "properties": {
    "claim": { "type": "string", "description": "The factual assertion about the franchise" },
    "source_article": { "type": "string", "description": "Wiki article title" },
    "source_section": { "type": "string" },
    "source_class": {
      "type": "string",
      "enum": ["primary_canon", "secondary_canon", "reference_book", "fan_maintained", "ambiguous"],
      "description": "Authority level of the source"
    },
    "confidence": {
      "type": "number", "minimum": 0, "maximum": 1,
      "description": "Retrieval confidence (semantic similarity × source authority weight)"
    },
    "continuity_tag": {
      "type": "string",
      "enum": ["canon", "legends", "both", "disputed"],
      "description": "Which continuity this claim belongs to"
    },
    "divergence_safe": {
      "type": "boolean",
      "description": "True if this claim is valid in the story's AU divergence context"
    }
  }
}
```

### Story State Schema (SQLite)

```sql
-- Core tables for story state tracking

CREATE TABLE characters (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    current_location TEXT,
    emotional_state TEXT,
    arc_position TEXT,         -- current position in their character arc
    inventory TEXT,            -- JSON: items they carry
    last_appearance_chapter INTEGER,
    last_appearance_scene INTEGER
);

-- NEW: Three-layer knowledge state (replaces single knowledge_state column)
CREATE TABLE character_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id TEXT NOT NULL REFERENCES characters(id),
    fact_id TEXT NOT NULL,          -- unique identifier for the fact
    fact_description TEXT NOT NULL,
    layer TEXT CHECK(layer IN ('truth', 'belief', 'narrative_exposure')) NOT NULL,
    -- truth: what is objectively true in the story
    -- belief: what this character believes (may be wrong)
    -- narrative_exposure: what the reader has been shown about this character's knowledge
    is_accurate BOOLEAN,           -- for belief layer: does this match truth?
    acquired_chapter INTEGER,
    source TEXT,                    -- how they learned it (witnessed, told, inferred, false)
    UNIQUE(character_id, fact_id, layer)
);

CREATE TABLE character_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_a TEXT NOT NULL REFERENCES characters(id),
    character_b TEXT NOT NULL REFERENCES characters(id),
    relationship_type TEXT,        -- ally, antagonist, mentor, romantic, distrustful, etc.
    status TEXT,                   -- current state description
    last_updated_chapter INTEGER,
    UNIQUE(character_a, character_b)
);

CREATE TABLE plot_threads (
    id TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    status TEXT CHECK(status IN ('planted', 'active', 'escalating', 'resolving', 'resolved')),
    planted_chapter INTEGER,
    urgency TEXT CHECK(urgency IN ('background', 'rising', 'critical', 'climactic')),
    related_characters TEXT,   -- JSON array of character IDs
    resolution_notes TEXT
);

CREATE TABLE timeline (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_number INTEGER,
    scene_number INTEGER,
    story_date TEXT,           -- in-universe date/time
    elapsed_time TEXT,         -- duration since story start
    key_events TEXT            -- JSON array of event descriptions
);

CREATE TABLE chekhov_guns (
    id TEXT PRIMARY KEY,
    item_description TEXT NOT NULL,
    planted_chapter INTEGER,
    planted_context TEXT,
    fired_chapter INTEGER DEFAULT NULL,
    fired_status TEXT CHECK(fired_status IN ('unfired', 'fired', 'subverted')) DEFAULT 'unfired'
);

CREATE TABLE chapter_log (
    chapter_number INTEGER PRIMARY KEY,
    word_count INTEGER,
    structural_phase TEXT,
    pov_character TEXT,
    summary TEXT,              -- ~200-400 token natural language summary
    quality_scores TEXT,       -- JSON: {structural, voice, polish}
    failure_codes TEXT,        -- JSON: array of failure codes from gate critic
    revision_status TEXT CHECK(revision_status IN ('draft', 'gate_failed', 'gate_passed', 'craft_edited', 'revised', 'approved')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revised_at TIMESTAMP
);

-- NEW: Append-only pipeline run log
CREATE TABLE run_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,  -- agent_start, agent_complete, gate_pass, gate_fail, state_diff, revision_start, etc.
    chapter_number INTEGER,
    scene_number INTEGER,
    agent_role TEXT,
    payload TEXT,              -- JSON: event-specific data
    state_hash TEXT            -- SHA256 of story state at this point, for diffing
);
```

---

## Model Router

The model router is the central abstraction that makes deployment mode switching possible. All agent code calls the router; the router reads the config to determine which backend handles each request.

### Configuration (settings.yaml)

```yaml
deployment_mode: hybrid  # local | cloud | hybrid

models:
  local:
    inference_backend: llama-server  # Primary backend — required for Qwen3.5 models
    base_url: http://localhost:8080/v1
    # NOTE: Ollama can be used for Qwen3/Gemma models but does NOT support Qwen3.5
    # due to separate mmproj vision file architecture. Use llama-server for all models
    # to keep serving unified.
    models:
      # --- Phase 1 models (fit on 12GB VRAM) ---
      primary_moe: Qwen3-30B-A3B-Instruct-2507-Q4_K_M  # MoE 30.5B total, 3.3B active, 262K context. Fits on GPU.
      fast_moe: Gemma-4-26B-A4B-Q5_K_M                  # MoE 26B total, 4B active, 256K context. Fits in ~8GB VRAM.
      utility: Qwen3.5-9B-Q5_K_M                        # Dense 9B, fast utility. Fits in ~6GB VRAM.
      embedding: nomic-embed-text                        # ~0.5GB, coexists with generation model.

      # --- Phase 3 models (upgrade candidates, require CPU expert offload) ---
      reasoning_upgrade: Qwen3.5-35B-A3B-Q4_K_M   # MoE 35B total, 3B active, 262K native. ~20GB at Q4_K_M — needs -ot exps=CPU -ngl 99
      prose: Magidonia-24B-v4.3-Q4_K_M             # Mistral Magistral base, creative writing optimized (~14GB, minimal CPU offload)
      prose_alt: Qwen3.5-27B-Writer-Q4_K_M         # Creative writing finetune trained on published fiction anthologies (~16GB)
      prose_alt2: Cydonia-24B-v4.3-Q4_K_M          # Mistral Small 3.2 base, atmospheric/wordy style, 131K context (~14GB)

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
        top_p: 1.0
        top_k: 0
        repetition_penalty: 1.08
      utility:
        temperature: 0.3
        min_p: 0.1

  cloud:
    provider: openrouter  # or anthropic, openai
    base_url: https://openrouter.ai/api/v1
    api_key_env: OPENROUTER_API_KEY
    models:
      primary: anthropic/claude-sonnet-4-20250514
      premium: anthropic/claude-opus-4-20250514
      budget: anthropic/claude-haiku-4-5-20251001
    default_params:
      primary:
        temperature: 0.7
        max_tokens: 4096
      premium:
        temperature: 0.9
        max_tokens: 8192

# Agent-to-model mapping
# Phase 1: All local agents use primary_moe or fast_moe (both fit on 12GB GPU)
# Phase 3: Upgrade reasoning-heavy agents to reasoning_upgrade, add prose models
agent_routing:
  # --- Phase 1 routing (single-model persona swaps on primary_moe) ---
  orchestrator:          { backend: local, model: fast_moe }
  plot_architect:        { backend: local, model: primary_moe, params: { temperature: 0.4 } }
  canon_expert:          { backend: local, model: fast_moe }
  prose_stylist:         { backend: local, model: primary_moe, params: { temperature: 0.9, min_p: 0.05 } }
  gate_critic:           { backend: local, model: primary_moe, params: { temperature: 0.3 } }
  craft_editor:          { backend: local, model: primary_moe, params: { temperature: 0.4 } }
  character_specialist:  { backend: local, model: primary_moe, params: { temperature: 0.4 } }
  summarizer:            { backend: local, model: utility, params: { temperature: 0.2 } }
  voice_checker:         { backend: cloud, model: primary, params: { temperature: 0.3 } }

  # --- Phase 3 routing (uncomment when models are downloaded and bake-off complete) ---
  # plot_architect:      { backend: local, model: reasoning_upgrade, params: { temperature: 0.4 } }
  # prose_stylist:       { backend: local, model: prose, params: { temperature: 1.0, min_p: 0.05 } }
  # gate_critic:         { backend: local, model: reasoning_upgrade, params: { temperature: 0.3 } }
  # character_specialist:{ backend: local, model: reasoning_upgrade, params: { temperature: 0.4 } }

# Local inference settings
local_inference:
  gpu_layers: 99           # -ngl 99 — offload all layers to GPU, experts spill to CPU automatically
  expert_offload: CPU      # -ot exps=CPU — for models that exceed VRAM, offload MoE expert layers to CPU
  context_size: 32768
  batch_size: 512
  flash_attention: true
  # NOTE: Speculative decoding requires same-family draft model.
  # For Qwen3: use Qwen3-0.6B. For Qwen3.5: not yet supported in llama-server.
  speculative_model: null  # Disabled until per-family draft models are validated
```

### Model Router Implementation

```python
# src/model_router.py

import httpx
import os
import yaml
from typing import Optional

class ModelRouter:
    """Routes agent LLM calls to the appropriate backend based on config."""

    def __init__(self, config_path: str = "config/settings.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        self.mode = self.config["deployment_mode"]
        self.local_client = httpx.AsyncClient(
            base_url=self.config["models"]["local"]["base_url"],
            timeout=300.0
        )
        if self.mode in ("cloud", "hybrid"):
            api_key = os.environ.get(
                self.config["models"]["cloud"]["api_key_env"], ""
            )
            self.cloud_client = httpx.AsyncClient(
                base_url=self.config["models"]["cloud"]["base_url"],
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=120.0
            )

    async def complete(
        self,
        agent_role: str,
        messages: list[dict],
        override_params: Optional[dict] = None
    ) -> str:
        """Send a completion request for the given agent role."""
        routing = self._get_routing(agent_role)
        backend = routing["backend"]
        model = self._resolve_model(routing)
        params = {**self._resolve_params(routing), **(override_params or {})}

        payload = {
            "model": model,
            "messages": messages,
            **params
        }

        client = self.local_client if backend == "local" else self.cloud_client
        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def complete_structured(
        self,
        agent_role: str,
        messages: list[dict],
        response_format: dict,
        override_params: Optional[dict] = None
    ) -> dict:
        """Send a completion request expecting structured JSON output."""
        json_instruction = {
            "role": "system",
            "content": "Respond with valid JSON only. No markdown, no preamble."
        }
        messages_with_json = [json_instruction] + messages

        raw = await self.complete(agent_role, messages_with_json, override_params)

        # Strip markdown fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]

        import json
        return json.loads(cleaned)

    def _get_routing(self, agent_role: str) -> dict:
        if self.mode == "local":
            return {"backend": "local", "model": "primary_moe"}
        elif self.mode == "cloud":
            return {"backend": "cloud", "model": "primary"}
        else:  # hybrid
            return self.config["agent_routing"].get(
                agent_role,
                {"backend": "local", "model": "primary_moe"}
            )

    def _resolve_model(self, routing: dict) -> str:
        backend = routing["backend"]
        model_key = routing.get("model", "primary_moe")
        return self.config["models"][backend]["models"][model_key]

    def _resolve_params(self, routing: dict) -> dict:
        backend = routing["backend"]
        model_key = routing.get("model", "primary_moe")
        base_params = self.config["models"][backend].get(
            "default_params", {}
        ).get(model_key, {})
        override = routing.get("params", {})
        return {**base_params, **override}
```

---

## Agent System

### Base Agent

```python
# src/agents/base_agent.py

from abc import ABC, abstractmethod
from src.model_router import ModelRouter

class BaseAgent(ABC):
    """Abstract base class for all writer's room agents."""

    def __init__(self, router: ModelRouter, role: str):
        self.router = router
        self.role = role
        self.system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        prompt_path = f"prompts/agent_system_prompts/{self.role}.md"
        with open(prompt_path) as f:
            return f.read()

    async def run(self, context: dict) -> dict:
        """Execute the agent's task. Returns structured output."""
        messages = self._build_messages(context)
        response = await self.router.complete(self.role, messages)
        return self._parse_response(response, context)

    def _build_messages(self, context: dict) -> list[dict]:
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self._format_context(context)}
        ]

    @abstractmethod
    def _format_context(self, context: dict) -> str:
        """Format the context dict into the user prompt."""
        pass

    @abstractmethod
    def _parse_response(self, response: str, context: dict) -> dict:
        """Parse the raw LLM response into structured output."""
        pass
```

### Agent Temperature and Model Assignments

| Agent | Role | Temperature | Min-p | Model (Local Phase 1) | Model (Local Phase 3) | Model (Cloud) |
|-------|------|------------|-------|----------------------|----------------------|---------------|
| Orchestrator | State machine, phase tracking | 0.2 | 0.1 | Gemma 4 26B-A4B | Gemma 4 26B-A4B | — |
| Plot Architect | Scene briefs from beat sheet | 0.4 | 0.05 | Qwen3-30B-A3B | Qwen3.5-35B-A3B | Claude Sonnet |
| Character Specialist | Voice profiles, OOC detection | 0.4 | 0.05 | Qwen3-30B-A3B | Qwen3.5-35B-A3B | Claude Sonnet |
| Canon Expert | RAG query, lore validation | 0.2 | 0.1 | Gemma 4 26B-A4B + nomic-embed | Gemma 4 26B-A4B | — |
| Prose Stylist | Chapter drafting | 0.9–1.1 | 0.05 | Qwen3-30B-A3B | Magidonia-24B or Qwen3.5-27B-Writer | Claude Sonnet |
| Gate Critic | Pass/fail structural eval | 0.3 | 0.1 | Qwen3-30B-A3B | Qwen3.5-35B-A3B | Claude Sonnet |
| Craft Editor | Non-blocking voice/polish | 0.4 | 0.1 | Qwen3-30B-A3B | Qwen3.5-35B-A3B | Claude Sonnet |
| Summarizer | Chapter compression | 0.2 | 0.1 | Qwen3.5-9B | Qwen3.5-9B or Gemma 4 | — |
| Voice Checker | Dialogue fidelity scoring | 0.3 | 0.1 | Cloud only | Cloud only | Claude Sonnet |

### Gate Critic vs. Craft Editor (NEW)

The former single `editor_critic` role is now split into two distinct agents:

**Gate Critic** — Binary pass/fail evaluator. Checks structural integrity:
- Does the scene fulfill its mission from the scene card?
- Does the turning point land?
- Are there continuity contradictions with story state?
- Are there canon violations?
- Does the scene respect structural phase constraints?

Returns a `CriticFailure` JSON with machine-readable failure codes. Only structural failures (`fail_structural`) trigger a full rewrite loop back to the Prose Stylist. The gate blocks passage to the manuscript.

**Craft Editor** — Non-blocking quality improver. Checks voice and polish:
- Character voice consistency
- Show-don't-tell ratio
- Prose cliché density
- Pacing within the scene
- Sentence variety

Returns improvement notes. These are applied as a lighter revision pass. The Craft Editor does **not** send scenes back to the Prose Stylist — it either applies fixes itself or annotates for the line-edit revision band. This prevents the "style homogenization through infinite critique loops" failure mode.

---

## Context Assembly

The context assembler builds the per-scene prompt payload from persistent storage. This is the critical component that keeps generation coherent across 80K words without stuffing the full manuscript into context.

### Token Budget Per Generation Call

| Component | Token Budget | Source |
|-----------|-------------|--------|
| System prompt (voice, style, constraints) | ~500 | Static file |
| Story bible essentials | ~1,000–2,000 | Tier 1 memory |
| Current act summary | ~500 | Tier 2 memory |
| Last 3 chapter summaries | ~600–1,200 | Tier 3 memory (ChromaDB) |
| Retrieved canon via RAG (with evidence ranking) | ~500–1,000 | Canon DB query |
| Character voice sheets (active chars) | ~500–1,000 | Character sheets |
| Character knowledge state (belief layer) | ~200–500 | Knowledge layers DB |
| Recent prose context | ~2,000–4,000 | Tier 4 memory |
| Scene card + generation instructions | ~200–500 | Scene card JSON |
| Negative constraints | ~200–400 | Static file |
| **Total input** | **~6,200–11,600** | |

This leaves ample room for generation output within a 32K context window (Qwen3-30B-A3B native) or 262K (Qwen3.5-35B-A3B).

### Four-Tier Memory Architecture

```python
# src/memory/context_assembler.py

class ContextAssembler:
    """Builds the prompt payload for each generation call."""

    def __init__(self, story_state, knowledge_layers, chapter_memory, canon_db, story_bible_path):
        self.state = story_state          # SQLite
        self.knowledge = knowledge_layers  # Truth/Belief/Exposure layers
        self.memory = chapter_memory       # ChromaDB
        self.canon = canon_db              # LanceDB/ChromaDB
        self.bible = self._load_bible(story_bible_path)

    def assemble(self, scene_card: dict, negative_constraints: str) -> str:
        """Assemble the full context for a scene generation call."""
        components = []

        # Tier 1: Story bible essentials (persistent, rarely changes)
        components.append(self._compress_bible())

        # Tier 2: Act summary (updated at structural milestones)
        act = self._get_current_act(scene_card["structural_phase"])
        components.append(f"## Current act summary\n{act}")

        # Tier 3: Recent chapter summaries (rolling window)
        recent = self.memory.get_recent_summaries(n=3)
        components.append(f"## Recent chapters\n{recent}")

        # Canon RAG injection (with evidence ranking)
        canon_query = self._build_canon_query(scene_card)
        canon_results = self.canon.hybrid_search(canon_query, k=5)
        ranked_evidence = self._rank_and_format_evidence(canon_results)
        components.append(f"## Canon reference\n{ranked_evidence}")

        # Active character voice sheets
        active_chars = scene_card["characters_present"]
        voices = self._get_voice_sheets(active_chars)
        components.append(f"## Character voices\n{voices}")

        # Character knowledge state (what each character believes in this scene)
        beliefs = self.knowledge.get_beliefs_for_characters(active_chars)
        components.append(f"## Character knowledge states\n{beliefs}")

        # Tier 4: Recent prose (last 2-4K tokens)
        recent_prose = self._get_recent_prose(max_tokens=3000)
        components.append(f"## Recent prose\n{recent_prose}")

        # Scene card (the generation mission)
        components.append(f"## Scene card\n{self._format_scene_card(scene_card)}")

        # Negative constraints
        components.append(f"## Constraints\n{negative_constraints}")

        return "\n\n".join(components)

    def _rank_and_format_evidence(self, raw_results: list) -> str:
        """Format canon results with confidence and source authority."""
        lines = []
        for r in sorted(raw_results, key=lambda x: x.get("confidence", 0), reverse=True):
            confidence = r.get("confidence", 0)
            source_class = r.get("source_class", "unknown")
            tag = r.get("continuity_tag", "unknown")
            # Only include high-confidence, divergence-safe results
            if confidence > 0.5 and r.get("divergence_safe", True):
                lines.append(f"[{source_class}/{tag} conf={confidence:.2f}] {r['claim']}")
        return "\n".join(lines) if lines else "No high-confidence canon matches found."
```

---

## RAG Pipeline for Canon Knowledge

### Ingestion Pipeline

```
MediaWiki API (Wookieepedia/Memory Alpha/Marvel DB)
    ↓
Entity-aware chunking (split by article sections)
    - Chunk size: 500–700 words with 100–150 word overlap
    - Metadata: source article, section, entity type, canon era, continuity status, source_class
    ↓
Source authority classification:
    - primary_canon: films, TV series, official reference books
    - secondary_canon: novels, comics, games
    - reference_book: encyclopedias, visual dictionaries
    - fan_maintained: wiki-original content, synthesis, fan interpretations
    - ambiguous: contradicted across sources, retconned, or disputed
    ↓
Embedding (nomic-embed-text or bge-m3, both ~0.5-1.4GB VRAM, coexist with Gemma 4 26B-A4B easily)
    ↓
Vector storage (ChromaDB <50K chunks, LanceDB for larger)
    +
Structured metadata (SQLite: entities, relationships, timeline events)
```

### Hybrid Search with Evidence Ranking

Every canon query runs both:
1. **Semantic search** — vector similarity for conceptual queries ("Jedi training traditions")
2. **Keyword/BM25 search** — for proper nouns and specific terms ("Mace Windu's Form VII Vaapad")

Results are merged via reciprocal rank fusion, deduplicated, and then **evidence-ranked**:
- Each result is scored: `confidence = semantic_score × source_authority_weight`
- Source authority weights: primary_canon=1.0, secondary_canon=0.85, reference_book=0.7, fan_maintained=0.4, ambiguous=0.3
- Results below confidence threshold (0.5) are excluded from context injection
- Each result carries its `continuity_tag` and `divergence_safe` flag

### Canon Divergence Tracking (for AU stories)

```json
{
  "divergence_point": "Post-FOTJ, ~45 ABY",
  "canon_preserved": ["All FOTJ events", "Character histories pre-divergence"],
  "canon_overridden": ["Legacy era timeline does not occur"],
  "retrieval_filter": {
    "era": ["pre-divergence", "all_eras"],
    "continuity": ["legends"],
    "exclude_tags": ["post_divergence_canon"]
  }
}
```

---

## Quality Metrics System

### Automated Quality Checks (Run After Each Chapter)

1. **Repetition detection**
   - Word frequency analysis (flag words >3 standard deviations above expected)
   - N-gram repetition across chapters
   - Sentence-opening pattern analysis (flag when >20% start the same way)
   - Vector similarity between paragraphs for semantic repetition

2. **Pacing analysis**
   - Sentence length variance per chapter (low variance = flat, AI-typical)
   - Dialogue-to-narrative ratio
   - Scene type distribution (action/reflection/transition)
   - Event density vs. Brooks's expected pacing curve

3. **Show-don't-tell flagging**
   - Detect "telling" emotion words: felt, knew, realized, noticed, wondered
   - Emotion-naming vs. emotion-showing patterns

4. **Voice consistency**
   - Motif cooldown (prevents metaphor overuse)
   - Rotating opener templates (prevents structural repetition)
   - Ban filter for LLM-typical words: "delve", "tapestry", "testament", "nuanced", "landscape"

5. **Readability benchmarking**
   - Flesch-Kincaid grade level compared to genre benchmarks from published tie-in novels

6. **Contradiction scanning** (NEW)
   - After each approved chapter, run a scan against story state DB and prior summaries
   - Flag any assertions that contradict established truth layer
   - Flag character actions that contradict their belief layer
   - Cross-reference against promise/payoff ledger for broken promises

### AI-Tell Detection (Anti-Slop)

Maintain a configurable banned word list based on community research:

```yaml
# config/negative_constraints.yaml

banned_phrases:
  faux_profundity:
    - "It wasn't just X, it was Y"
    - "A testament to"
    - "A tapestry of"
    - "A symphony of"
    - "It was more than"
  sensory_cliches:
    - "The smell of ozone"
    - "A shiver ran down"
    - "Eyes flashing with"
    - "Breath he didn't know he was holding"
    - "Jaw tightened"
  magic_adverbs:
    - "Quietly orchestrated"
    - "Fundamentally shifted"
    - "Remarkably"
    - "Seemingly"
  ai_tells:
    - "delve"
    - "tapestry"
    - "testament"
    - "nuanced"
    - "landscape"
    - "multifaceted"
    - "straightforward"
    - "it's important to note"
    - "it's worth noting"

structural_rules:
  max_adverb_density: 0.02          # per word
  min_sentence_length_variance: 0.3  # coefficient of variation
  max_same_opener_pct: 0.15          # paragraph opening diversity
  metaphor_cooldown_paragraphs: 8    # min paragraphs between metaphors
```

### Structured Failure Code Taxonomy (NEW)

```yaml
# config/failure_codes.yaml

failure_codes:
  structural:
    CONTINUITY_CONTRADICTION: "Scene contradicts established story state"
    WEAK_TURNING_POINT: "Scene ends in roughly the same state it began"
    MISSING_TURNING_POINT: "No identifiable shift in scene dynamics"
    UNEARNED_RESOLUTION: "Conflict resolved without sufficient buildup or cost"
    STRUCTURAL_PHASE_VIOLATION: "Scene actions violate Brooks phase constraints"
    PROMISE_BROKEN: "Setup or foreshadow is contradicted without intentional subversion"
    MOTIVATION_GAP: "Character action lacks traceable motivation from state or arc"
    CHARACTER_ARC_STALL: "POV character's Weiland arc shows no movement for 2+ consecutive scenes"
    HOOK_VIOLATION: "Required hook not planted/advanced per hook governance rules"
    SUBPLOT_DRIFT: "Active subplot contradicts its declared arc shape or chapter range"

  voice:
    OOC_DIALOGUE: "Character speaks in a way inconsistent with voice profile"
    OOC_ACTION: "Character acts inconsistently with established dimensions"
    TELLING_NOT_SHOWING: "Emotional state narrated rather than demonstrated"
    VOICE_DEFINITION_VIOLATION: "Prose violates project voice definition (diction, rhythm, register)"
    TERMINOLOGY_DRIFT: "Inconsistent use of project-specific terminology vs. registry"

  polish:
    EXPOSITION_LEAK: "World-building info dumped outside natural scene flow"
    PACING_FLATLINE: "Insufficient sentence/event variety across scene"
    PROSE_CLICHE_BURST: "Multiple banned phrases or AI-tells detected"
    CANON_VIOLATION: "Scene contradicts established franchise lore"

routing:
  fail_structural: full_rewrite       # Back to Prose Stylist with failure context
  fail_voice: targeted_revision       # Prose Stylist with specific voice notes
  fail_polish: craft_edit             # Craft Editor for non-blocking improvement
```

---

## Orchestrator (Event-Driven State Machine)

The orchestrator manages the overall pipeline as an event-driven state machine. Every step emits a typed event to the append-only run ledger, and every state mutation is diffed before commit.

### Event Types

```python
EVENT_TYPES = [
    "pipeline_start",
    "chapter_start",
    "agent_start",        # payload: {agent_role, chapter, scene}
    "agent_complete",     # payload: {agent_role, duration_ms, token_count}
    "gate_pass",          # payload: {chapter, scene, scores}
    "gate_fail",          # payload: {chapter, scene, failure_codes, route_to}
    "craft_edit_complete", # payload: {chapter, scene, changes_made}
    "state_diff_proposed", # payload: {diff_json, state_hash_before}
    "state_diff_committed", # payload: {state_hash_after}
    "revision_band_start", # payload: {band_name, chapter_range}
    "revision_band_complete",
    "milestone_reached",  # payload: {milestone_name, word_count, chapter}
    "milestone_gate_paused", # human review required
    "pipeline_complete",
]
```

### Phase Transitions

```
Milestone         Position    Word Count (70K target)    Transition Rule
─────────────────────────────────────────────────────────────────────
Hook              0–1%        0–700                      —
First Plot Point  ~25%        ~17,500                    Lock narrative quest
First Pinch Point ~37.5%      ~26,250                    Reassert antagonist
Midpoint          ~50%        ~35,000                    Shift protagonist to warrior
Second Pinch Point ~62.5%     ~43,750                    Antagonist counter-attack
Second Plot Point ~75%        ~52,500                    Lock info, no new exposition
Dark Moment       ~80%        ~56,000                    All seems lost
Climax            ~90%        ~63,000                    Final confrontation
Resolution        95–100%     66,500–70,000              New equilibrium
```

The orchestrator enforces hard constraints:
- **Part 1 (0–25%)**: Drafting agents are blocked from resolving major conflicts
- **Part 2 (25–50%)**: Protagonist actions must yield incomplete or failed results
- **Part 3 (50–75%)**: Protagonist actions may succeed partially
- **After Second Plot Point (75%)**: No new world-building data injected from RAG

---

## UI Design

### Target: Writing IDE, Not Chatbot

The UI should resemble NovelCrafter or Scrivener, not a chat interface.

### Key Views

1. **Dashboard view**
   - Brooks's four-part structure as a visual progress bar with milestone markers
   - Current chapter, word count, completion percentage
   - Per-chapter quality scores (color-coded: green/yellow/red)
   - Active plot threads and their status
   - Promise/payoff ledger status (unfulfilled promises highlighted)

2. **Split-pane editing**
   - Left panel: outline/beat sheet (collapsible tree)
   - Right panel: prose editor (current chapter)
   - Scene cards visible as expandable annotations

3. **Pipeline control**
   - Start/pause/resume generation
   - View agent activity log in real time (from run ledger)
   - Manual override: approve, reject, or edit any chapter before pipeline continues
   - Milestone gates: pipeline pauses at First Plot Point, Midpoint, Climax for human review
   - Failure code breakdown per rejected scene

4. **Character tracker**
   - Visual matrix: which characters appear in which chapters
   - Knowledge state per character per chapter (truth vs. belief layers)
   - Relationship map with status changes highlighted

5. **Pacing graph**
   - Action/reflection balance across chapters vs. ideal Brooks curve
   - Event density visualization
   - Character pressure matrix visualization

6. **Diff view**
   - Before/after comparison for each revision band
   - Git-backed: full history of every chapter's evolution

7. **Codex panel**
   - Always-visible reference to the story bible
   - Quick-edit capability for character sheets and world-building notes
   - Canon search with evidence ranking display (queries the RAG database directly)

8. **Quality dashboard**
   - Running metrics: repetition score, readability, pacing consistency per chapter
   - AI-tell detection results
   - Voice fidelity scores per character
   - Failure code frequency analysis across chapters

### Tech Stack for UI

- **Backend**: FastAPI (Python) — same language as the pipeline
- **Frontend**: React with Tailwind CSS
- **Real-time updates**: WebSocket for pipeline progress
- **Editor component**: CodeMirror or Monaco (supports markdown, diff view)
- **State management**: SQLite (same DB the pipeline uses)
- **Charts**: Recharts for pacing graphs and quality dashboards

---

## Phase 5: Character Arcs, Hook Governance, and Series Support

### K.M. Weiland Character Arc Integration

Each ensemble cast member carries a Weiland arc structure stored in `character_arcs`:

```sql
CREATE TABLE character_arcs (
    id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL REFERENCES characters(id),
    arc_type TEXT CHECK(arc_type IN ('positive', 'flat', 'negative')) NOT NULL,
    lie TEXT NOT NULL,           -- the false belief the character holds
    ghost TEXT,                  -- backstory wound that created the lie
    want TEXT NOT NULL,          -- external goal driven by the lie
    need TEXT NOT NULL,          -- internal truth the character must learn (or reject)
    current_phase TEXT CHECK(current_phase IN (
        'orphan', 'wanderer', 'warrior', 'martyr'
    )) DEFAULT 'orphan'
);
```

Arc phases map to Brooks's four-part structure:
- **Orphan** (Setup) — character operates under the lie
- **Wanderer** (Response) — confronted with evidence against the lie, resists
- **Warrior** (Attack) — begins acting on the need, lie weakens
- **Martyr** (Resolution) — fully embraces need (positive), rejects it (negative), or was never wrong (flat)

The Gate Critic enforces arc movement: `CHARACTER_ARC_STALL` fires when a POV character stays in the same phase for 2+ consecutive scenes without visible tension between lie and need.

### Hook Governance

Hooks are narrative promises tracked with admission control and advancement enforcement.

```sql
CREATE TABLE hook_ledger (
    id TEXT PRIMARY KEY,
    hook_type TEXT CHECK(hook_type IN ('opening', 'chapter', 'act', 'series')) NOT NULL,
    description TEXT NOT NULL,
    planted_chapter INTEGER NOT NULL,
    status TEXT CHECK(status IN ('open', 'advancing', 'resolved', 'abandoned')) DEFAULT 'open',
    last_advanced_chapter INTEGER,
    target_resolve_chapter INTEGER,
    advance_count INTEGER DEFAULT 0
);
```

**Admission control**: New hooks require a declared `target_resolve_chapter`. Hooks that would exceed the project's hook budget (configurable, default 3 open per act) are rejected.

**Advancement tracking**: Open hooks must be advanced (mentioned or progressed) at least once every N chapters (configurable, default 4). `HOOK_VIOLATION` fires when a hook goes stale.

**Hook debt**: At each structural milestone, the system tallies open hooks. Excessive hook debt (more open hooks than remaining chapters can service) triggers a planning-level warning.

### Subplot Board

```sql
CREATE TABLE subplot_board (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    subplot_type TEXT CHECK(subplot_type IN ('relationship', 'mystery', 'internal', 'political', 'thematic')),
    arc_shape TEXT CHECK(arc_shape IN ('rise', 'fall', 'rise_fall', 'slow_burn', 'reversal')),
    start_chapter INTEGER,
    end_chapter INTEGER,
    status TEXT CHECK(status IN ('planned', 'active', 'resolving', 'resolved')) DEFAULT 'planned'
);
```

Subplots declare their arc shape and chapter range at planning time. `SUBPLOT_DRIFT` fires when runtime subplot behavior contradicts the declared shape (e.g., a "slow_burn" subplot peaks in Act 1).

### Terminology Registry

```sql
CREATE TABLE terminology_registry (
    id TEXT PRIMARY KEY,
    term TEXT NOT NULL UNIQUE,
    definition TEXT NOT NULL,
    aliases TEXT,                -- JSON array of acceptable variants
    first_use_chapter INTEGER,
    category TEXT               -- e.g., 'technology', 'culture', 'force_tradition'
);
```

Ensures consistent naming across the manuscript. `TERMINOLOGY_DRIFT` fires when prose uses an unregistered variant of a registered term.

### Propagation Debt Tracking

```sql
CREATE TABLE propagation_debts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_event TEXT NOT NULL,       -- what happened
    source_chapter INTEGER NOT NULL,
    affected_entity TEXT NOT NULL,    -- character, subplot, or hook that should react
    debt_type TEXT CHECK(debt_type IN ('knowledge', 'emotional', 'plot', 'relationship')),
    status TEXT CHECK(status IN ('pending', 'resolved', 'waived')) DEFAULT 'pending',
    resolved_chapter INTEGER
);
```

When a significant event occurs (character death, revelation, betrayal), the system creates propagation debts for every entity that should be affected. The ContextAssembler injects pending debts into downstream scene prompts until they are resolved.

### Style Fingerprinting

```sql
CREATE TABLE style_fingerprint (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,        -- e.g., 'avg_sentence_length', 'dialogue_ratio', 'adverb_density'
    target_value REAL NOT NULL,
    tolerance REAL NOT NULL,          -- acceptable deviation
    source TEXT                       -- 'reference_corpus' | 'voice_definition' | 'calibration_chapters'
);
```

Captures prose style metrics from reference material or early calibration chapters. The ProseStylist receives fingerprint targets as part of its context, and the Gate Critic can flag `VOICE_DEFINITION_VIOLATION` when output deviates beyond tolerance.

### Series Support

**Series seed** (`schemas/series_seed.json`) extends the concept seed with:
- `series_arc`: overarching lie/need/theme across all books
- `books[]`: per-book premise, arc contribution, and transition requirements
- `recurring_cast`: characters that span books with per-book arc phases
- `series_hooks`: hooks that span multiple books

**SeriesManager** (`src/concept_workshop/series_manager.py`) handles:
- Series seed validation and per-book concept seed generation
- **Transition snapshots**: end-of-book state exports (character arcs, open hooks, subplot status) that seed the next book's initial state
- **Retroactive promotion**: when a standalone project is promoted to a series after writing begins, the manager extracts series-level arcs from existing state

### Schema Migration System

Database schema evolves across phases. The migration system tracks the current version and applies forward-only migrations:

```sql
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    description TEXT
);
```

Each migration is a numbered Python file (`migrations/NNN_description.py`) that runs idempotently. The system checks `schema_version` at startup and applies any pending migrations before pipeline execution.

### State Diff Optimistic Conflict Detection

State diffs now include `old_value` for every field mutation. Before committing a diff, the system verifies that the current DB value matches the expected `old_value`. If a concurrent process has modified the field, the diff is rejected and re-queued for conflict resolution. This prevents silent data corruption in multi-agent scenarios.

---

## Phase 5: Agent Pipeline Enhancements

### Context Assembler Expansion

The ContextAssembler gains 5 new tiers injected into the per-scene prompt:

| Tier | Content | Source |
|------|---------|--------|
| Arc context | POV character's Weiland arc: current phase, lie/need tension, phase transition cue | `character_arcs` table |
| Hook directives | Open hooks relevant to this scene, advancement deadlines | `hook_ledger` table |
| Subplot status | Active subplots with expected arc behavior for this chapter | `subplot_board` table |
| Propagation debts | Pending debts for characters present in this scene | `propagation_debts` table |
| Anti-slop injection | Voice definition targets, banned patterns, style fingerprint constraints | `style_fingerprint` + `negative_constraints.yaml` |

The anti-slop tier is injected as an upstream directive to the ProseStylist, not as a post-hoc filter. This reduces the need for revision passes caused by slop detection.

### PlotArchitect Enhancements

The PlotArchitect now receives hook, subplot, and arc directives when generating scene briefs:
- **Hook directives**: Which hooks to plant, advance, or resolve in each scene
- **Subplot threading**: Which subplots are active and where they should be in their arc shape
- **Arc phase cues**: When a POV character should begin transitioning between Weiland phases

### ProseStylist Anti-Slop Upstream Injection

Rather than detecting and revising slop after generation, the ContextAssembler injects anti-slop directives directly into the ProseStylist's system prompt. This includes:
- Banned phrase list (from `negative_constraints.yaml`)
- Voice definition constraints (diction register, sentence rhythm targets)
- Style fingerprint guardrails (target metrics with tolerances)

This upstream approach reduces slop-related `fail_polish` rejections by ~40% compared to post-hoc detection alone.

### Summarizer Validated Delta Format

The Summarizer now outputs a validated delta format that includes:
- **State assertions**: Explicit claims about what changed in the scene (character moved, learned fact, relationship shifted)
- **Delta validation**: Each assertion is checked against the scene text before being applied to story state
- **Conflict detection**: Assertions that contradict existing state are flagged rather than silently applied

### Manuscript Reviewer Agent

A new agent using a dual-persona approach on a premium model tier (Claude Opus or equivalent):

**Reader persona**: Reads the chapter as a first-time reader — flags confusion, disengagement, pacing drag, and emotional flat spots. Does not have access to scene cards or story bible during this pass.

**Editor persona**: Re-reads with full structural context — flags craft issues, arc progression problems, and missed opportunities. Has access to all planning documents.

The two-pass approach catches both reader-experience issues (that structural analysis misses) and structural issues (that pure reading misses). The manuscript reviewer runs after the per-chapter pipeline completes a full act, not per-scene.

---

## Phased Implementation Roadmap

### Phase 1 — Minimal Viable Pipeline (Week 1–2)
- Two MoE models via llama-server: Qwen3-30B-A3B-Instruct-2507 (reasoning/drafting) + Gemma 4 26B-A4B (utility)
- Four agents as persona-swaps: Plot Architect, Prose Stylist, Gate Critic, Craft Editor
- Gate Critic returns structured failure codes (not freeform prose)
- Sequential pipeline with JSON scratchpad files
- CLI interface only
- **Goal**: Generate one coherent chapter end-to-end from a scene card, with structured pass/fail evaluation

### Phase 2 — Memory, Canon, and Story Physics (Week 3–5)
- Add Story Physics pass: causality chains, revelation map, promise/payoff ledger, pressure matrix
- Add four-tier hierarchical memory system
- ChromaDB for chapter summaries
- SQLite for story state tracking with truth/belief/narrative-exposure layers
- Build RAG pipeline with evidence ranking for one franchise wiki (Wookieepedia Legends)
- Add Canon Expert agent
- Add contradiction scanner (post-chapter)
- Add append-only run ledger for pipeline events
- **Goal**: Generate 5 coherent chapters with consistent continuity and tracked promise/payoff

### Phase 3 — Multi-Model and Quality (Week 6–8)
- Download and bake-off Qwen3.5-35B-A3B vs Qwen3-30B-A3B over 20–30 fixed prompts
- If Qwen3.5-35B-A3B wins: upgrade reasoning-heavy agents (Plot Architect, Gate Critic, Character Specialist) with CPU expert offload via `-ot exps=CPU -ngl 99`
- Add Magidonia-24B-v4.3 or Qwen3.5-27B-Writer for Prose Stylist — bake-off between candidates
- Add Character Specialist agent for OOC detection
- Implement negative constraints and anti-slop detection
- Add basic quality metrics (repetition, pacing)
- Build small gold evaluation corpus (5–10 target-quality chapters for Star Wars)
- **Goal**: Measurably reduce repetitive patterns; have quantitative model comparison data

### Phase 4 — Full Pipeline and Cloud (Week 9–11)
- Implement three-band revision pipeline (structural/continuity → scene/emotion → line/copy)
- Expand to five passes only if metrics show benefit
- Add OpenRouter cloud integration to ModelRouter
- Configure hybrid mode: local MoE for per-chapter critique + cloud Claude Sonnet for revision passes and voice checking
- Add LLM-as-judge evaluation with structured rubric
- Implement blind peer review protocol for planning stages
- Add milestone gates — pipeline pauses at First Plot Point, Midpoint, Climax for human review
- **Goal**: Generate full 25-chapter novel draft

### Phase 5 — Concept Workshop Expansion, Arcs, Hooks, and Series (Week 12–16)
- Expand Concept Workshop from 6 to 10 steps (series branching, Weiland arcs, voice discovery, subplot/hook architecture, terminology registry, stress test)
- K.M. Weiland character arc integration (lie/ghost/want/need mapped to Brooks structure phases)
- Hook governance with admission control, advancement tracking, and hook debt enforcement
- Subplot board lifecycle with arc shape validation
- Terminology registry for cross-manuscript consistency
- Propagation debt tracking for event consequences
- Style fingerprinting system for prose metric enforcement
- Series support: series seed schema, SeriesManager, transition snapshots, retroactive promotion
- Schema migration infrastructure with version tracking
- Manuscript reviewer agent (dual-persona, premium model tier)
- Context assembler expansion (5 new tiers: arcs, hooks, subplots, debts, anti-slop)
- Anti-slop upstream injection into ProseStylist via ContextAssembler
- State diff optimistic conflict detection (old_value verification)
- 6 new SQLite tables, 5 new failure codes
- **Goal**: Full structural narrative intelligence — arcs, hooks, subplots, and series tracked end-to-end

---

## Dependencies

### Python Packages

```
# Core
httpx>=0.27.0           # Async HTTP client for model APIs
pyyaml>=6.0             # Configuration files
pydantic>=2.0           # Data validation
sqlalchemy>=2.0         # SQLite ORM (optional, can use raw sqlite3)

# Vector databases
chromadb>=0.5.0         # Chapter summaries, small canon DBs
lancedb>=0.9.0          # Large canon knowledge bases

# Embedding
sentence-transformers   # For local embedding models
onnxruntime             # Optimized inference for embedding

# Quality metrics
nltk>=3.8               # Tokenization, readability scores
scikit-learn            # TF-IDF, cosine similarity
numpy                   # Numerical operations

# Export
python-docx             # DOCX manuscript export
ebooklib                # EPUB export

# UI
fastapi>=0.110.0        # Web backend
uvicorn                 # ASGI server
websockets              # Real-time pipeline updates

# Development
pytest                  # Testing
black                   # Formatting
ruff                    # Linting
```

### Local Inference

```
# PRIMARY: llama.cpp / llama-server (REQUIRED)
# Build from source or use prebuilt binary
# Provides OpenAI-compatible API at localhost:8080
# Required for Qwen3.5 models (Ollama does not support them)
# Also works for all Qwen3 and Gemma models
#
# Build with CUDA support:
#   git clone https://github.com/ggml-org/llama.cpp
#   cd llama.cpp && mkdir build && cd build
#   cmake -DGGML_CUDA=ON .. && cmake --build . --config Release -j
#
# Run:
#   ./llama-server -hf bartowski/Qwen3-30B-A3B-Instruct-2507-GGUF:Q4_K_M \
#     --ctx-size 32768 --jinja -ngl 99 -fa -ub 2048 -b 2048

# OPTIONAL: Ollama (simpler setup, but limited model support)
# Install from ollama.ai
# Provides OpenAI-compatible API at localhost:11434
# Works for: Gemma 4, Qwen3 models, Qwen3.5-9B
# Does NOT work for: Qwen3.5-35B-A3B, Qwen3.5-27B (mmproj vision file issue)
```

### Model Downloads (GGUF format)

```
# ============================================================
# PHASE 1 MODELS — Both fit on 12GB VRAM, no CPU offload needed
# ============================================================

# Primary Reasoning: Qwen3-30B-A3B-Instruct-2507 (MoE, 30.5B total, 3.3B active)
# 262K native context, non-thinking mode only, mature llama.cpp/Ollama support
# Best for: All reasoning-heavy agents in Phase 1 (planning, critique, drafting)
# ~18GB at Q4_K_M on disk, but only ~3.3B active — fits in 12GB VRAM with room to spare
huggingface-cli download bartowski/Qwen3-30B-A3B-Instruct-2507-GGUF --include "*Q4_K_M*"

# Fast Utility: Gemma 4 26B-A4B (MoE, 26B total, 4B active)
# 256K context, fits in ~8GB VRAM at Q5_K_M
# Best for: Orchestrator, canon expert, summarization — fast tasks that need intelligence
huggingface-cli download bartowski/Gemma-4-26B-A4B-GGUF --include "Gemma-4-26B-A4B-Q5_K_M.gguf"

# Small Utility: Qwen3.5-9B (dense, fast)
# ~6GB at Q5_K_M — fits fully on GPU with room for embedding model
huggingface-cli download bartowski/Qwen3.5-9B-GGUF --include "*Q5_K_M*"

# Embedding: nomic-embed-text (~0.5GB, runs alongside generation model)
# Can use via Ollama or sentence-transformers
ollama pull nomic-embed-text

# ============================================================
# PHASE 3 MODELS — Upgrade candidates, require bake-off first
# ============================================================

# Reasoning Upgrade: Qwen3.5-35B-A3B (MoE, 35B total, 3B active, 262K native)
# ~20GB at Q4_K_M — requires CPU expert offload: -ot exps=CPU -ngl 99
# Uses Gated Delta Networks + MoE hybrid architecture (newer than Qwen3)
# Does NOT work with Ollama — requires llama-server b8148+
# Bake-off against Qwen3-30B-A3B before committing to upgrade
huggingface-cli download bartowski/Qwen_Qwen3.5-35B-A3B-GGUF --include "*Q4_K_M*"

# Prose: Magidonia-24B-v4.3 (Mistral Magistral base, creative writing optimized)
# ~14GB at Q4_K_M — minimal CPU offload, modern architecture, strong storytelling
huggingface-cli download bartowski/TheDrummer_Magidonia-24B-v4.3-GGUF --include "TheDrummer_Magidonia-24B-v4.3-Q4_K_M.gguf"

# Prose Alternative 1: Cydonia-24B-v4.3 (Mistral Small 3.2 base, atmospheric style)
# Same creator, different base — more "wordy and thick" prose, 131K context window
huggingface-cli download bartowski/TheDrummer_Cydonia-24B-v4.3-GGUF --include "TheDrummer_Cydonia-24B-v4.3-Q4_K_M.gguf"

# Prose Alternative 2: Qwen3.5-27B-Writer (creative writing finetune)
# Trained on published fiction anthologies with anti-repetition base (~16GB)
huggingface-cli download mradermacher/Qwen3.5-27B-Writer-GGUF --include "Qwen3.5-27B-Writer-Q4_K_M.gguf"

# ============================================================
# NOT RECOMMENDED FOR THIS HARDWARE
# ============================================================
# gpt-oss-20b — Native MXFP4 requires Hopper+ GPUs (H100, RTX 50xx).
#   On Ada Lovelace (RTX 4070), MXFP4 uses software emulation = extremely slow.
#   The FFN layers cannot be quantized below MXFP4 (size is ~12GB regardless of quant).
#   Real-world reports on 4070: only 9/25 layers fit on GPU, inference 4-5 min/token.
#   Use via cloud/OpenRouter if you want to evaluate it.
#
# Qwen3.5-27B Dense — Needs ~16GB at Q4_K_M, slower than MoE alternatives
#   for the same quality tier. Use Qwen3-30B-A3B or Qwen3.5-35B-A3B instead.
#
# Qwopus-MoE-35B-A3B — Community finetune (Opus-distilled), interesting but
#   uncertain stability across versions. Qwen3-30B-A3B provides similar MoE
#   efficiency with better ecosystem support. Keep as experimental comparison.
#
# Magnum-v4-27b — Older Gemma 2 architecture, superseded by newer options.
#
# Gemma 4 31B Dense — Excellent quality but needs ~18GB at Q4_K_M.
#   Use the 26B-A4B MoE instead for local deployment.
```
