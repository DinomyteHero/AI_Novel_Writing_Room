> **Historical document.** This was the original project brief (v1.1). For current architecture including Phase 5 changes, see `AI_Writers_Room_Design_Document_v1.1.md` and `Phase_5_Changelog.md`.

# Claude Code Project Brief: AI Writers' Room (v1.1)

## Changelog (v1.0 → v1.1)

- Model stack: Qwen3-30B-A3B-Instruct-2507 replaces Qwen3.5-27B as Phase 1 primary. Qwen3.5-35B-A3B is Phase 3 upgrade (bake-off required).
- Serving: llama-server is now the primary backend. Ollama is optional and does not support Qwen3.5 models.
- Dropped gpt-oss-20b (MXFP4 incompatible with RTX 4070 Ada Lovelace) and Qwopus-MoE (unstable community finetune).
- Added Story Physics layer, structured failure codes, split Gate Critic / Craft Editor, truth/belief/exposure knowledge layers, canon evidence ranking, event-driven orchestrator with run ledger.
- Revision pipeline starts as three bands (not five), expandable if metrics justify.

## What We're Building

A multi-agent fiction generation system that produces novel-length (60–80K word) franchise fanfiction through two phases:

1. **Phase A (Human + AI)**: A structured concept workshop and planning pipeline where the human collaborates with an AI to develop a complete story bible (concept, characters, structural outline, beat sheet, Story Physics validation, scene cards)
2. **Phase B (Autonomous)**: A multi-agent pipeline that drafts chapters, evaluates them through a split Gate Critic / Craft Editor system with structured failure codes, revises them through a three-band revision pipeline, and produces a final manuscript — all driven by the story bible from Phase A

The system supports three deployment modes: fully local (RTX 4070 12GB VRAM + 32GB RAM), fully cloud (via OpenRouter API), or hybrid (local drafting + cloud critique).

## Reference Documents

Read `AI_Writers_Room_Design_Document.md` (v1.1) in this project — it contains the complete technical specification including:
- Directory structure
- All JSON schemas (concept seed, Story Physics, scene cards, character sheets, story state, failure codes, canon evidence)
- SQLite schema for story state tracking (with truth/belief/narrative-exposure knowledge layers)
- Model router implementation with the full settings.yaml config
- Base agent class pattern
- Context assembly logic with token budgets
- Canon evidence ranking system
- Quality metrics specifications
- Structured failure code taxonomy
- Negative constraints / anti-slop configuration
- UI design specifications
- Phased implementation roadmap
- All dependency lists

Read `Concept_Workshop_System_Prompt.md` — this is the system prompt template for Stage 1 (human concept ideation). It needs to be stored in `prompts/concept_workshop.md`.

Read `beyond_the_veil_concept_seed.json` — this is a real example of a completed Stage 1 output. Use it as your test fixture for pipeline development.

## Implementation Order

Follow the phased roadmap from the design doc. Build in this order:

### Phase 1 — Minimal Viable Pipeline
1. Set up the project structure per the design doc's directory layout
2. Implement `ModelRouter` — the central abstraction that routes agent calls to llama-server or cloud (OpenRouter) backends based on `settings.yaml`
3. Implement `BaseAgent` abstract class
4. Implement four agents as the minimum viable set:
   - `PlotArchitect` — reads a scene card, produces a generation brief
   - `ProseStylist` — takes the generation brief + assembled context, drafts prose
   - `GateCritic` — evaluates drafted prose against structural rubric, returns structured `CriticFailure` JSON with machine-readable failure codes and routing decisions
   - `CraftEditor` — non-blocking voice/polish improvements (does not send back to Prose Stylist)
5. Implement `failure_codes.yaml` and the failure routing logic:
   - `fail_structural` → full rewrite (back to Prose Stylist with failure context)
   - `fail_voice` → targeted revision (Prose Stylist with specific OOC/voice notes)
   - `fail_polish` → craft edit (Craft Editor, non-blocking)
6. Implement basic `ContextAssembler` — for Phase 1, this just concatenates the story bible, scene card, and any previous chapter text
7. Implement the `Orchestrator` — an event-driven loop: for each scene card → PlotArchitect → ProseStylist → GateCritic → if fail_structural, loop back with failure codes → if pass, route through CraftEditor → save chapter. All steps emit typed events to an append-only run ledger.
8. CLI entry point that takes a concept seed JSON + scene cards directory and runs the pipeline
9. Test end-to-end: feed the Beyond the Veil concept seed + a manually written scene card for Chapter 1 → generate one chapter with structured pass/fail evaluation

### Phase 2 — Memory, Canon, and Story Physics
1. Implement Story Physics pass:
   - Causality chain validator (directed graph of events, flag orphaned/dead nodes)
   - Revelation map (information release timing)
   - Promise/payoff ledger (track setup → payoff across chapters)
   - Character-pressure matrix (escalating pressure per POV per chapter)
   - Chapter-level "why now?" check on scene cards
2. Implement SQLite story state database (schema in design doc)
3. Implement truth/belief/narrative-exposure knowledge layers:
   - `character_knowledge` table with `layer` column (truth | belief | narrative_exposure)
   - `is_accurate` flag for belief layer (does it match truth?)
   - Query methods for assembling per-character belief state into context
4. Implement `ChapterMemory` using ChromaDB — stores chapter summaries as vectors, retrieves last N summaries
5. Implement `StateDiff` — after each chapter generation, the summarizer agent produces a state diff (JSON) that updates character positions, knowledge layers, plot thread status, and timeline. State diffs are diffed before commit and logged to run ledger.
6. Implement `ContradictionScanner` — post-chapter scan against story state DB and prior summaries
7. Upgrade `ContextAssembler` to the full four-tier memory system with token budgets, including character belief injection
8. Implement `CanonDB` — vector database for franchise knowledge with evidence ranking
9. Implement `WikiIngester` — ingests from MediaWiki API (Wookieepedia), entity-aware chunking at 500-700 words with metadata including source authority classification
10. Implement `CanonEvidence` — two-stage canon check: retrieve candidates → produce structured claim with confidence, source class, continuity tag, and divergence safety flag
11. Implement `HybridSearch` — semantic + BM25 keyword search with reciprocal rank fusion and evidence ranking
12. Add `CanonExpert` agent
13. Test: generate 5 consecutive chapters with consistent continuity, tracked promise/payoff, and zero contradiction scanner failures

### Phase 3 — Multi-Model and Quality
1. Download Qwen3.5-35B-A3B and run bake-off against Qwen3-30B-A3B-Instruct-2507 over 20–30 fixed prompts covering:
   - Structural obedience (does it follow scene card missions?)
   - Scene-brief quality (Plot Architect output)
   - Critic usefulness (Gate Critic failure code accuracy)
   - Prose contamination rate (does critic reasoning leak into prose style?)
2. If Qwen3.5-35B-A3B wins: upgrade reasoning-heavy agents with CPU expert offload via llama-server `-ot exps=CPU -ngl 99`
3. Download and bake-off prose models: Magidonia-24B-v4.3 vs Cydonia-24B-v4.3 vs Qwen3.5-27B-Writer
4. Keep Gemma 4 26B-A4B for fast utility tasks (orchestrator, canon expert, summarizer)
5. Keep Qwen3.5-9B as lightweight fallback
6. Model swapping: llama-server supports loading different models; implement a model-swap manager that unloads current model and loads the next agent's model
7. Implement quality metrics:
   - `RepetitionDetector` — word frequency, n-gram, semantic similarity
   - `PacingAnalyzer` — sentence length variance, event density
   - `SlopDetector` — AI-tell word list from negative_constraints.yaml
   - `VoiceChecker` — per-character voice fidelity via LLM-as-judge
8. Implement negative constraints injection into prose stylist prompts
9. Add `CharacterSpecialist` agent for OOC detection
10. Build small gold evaluation corpus (5–10 target-quality chapters)
11. Test: measure quality metrics before/after negative constraints, compare model A/B results

### Phase 4 — Full Pipeline and Cloud
1. Implement three-band revision pipeline:
   - Band 1: Structural/Continuity (plot holes, arc consistency, timeline, knowledge state)
   - Band 2: Scene/Emotion (conflict quality, turning points, show-don't-tell)
   - Band 3: Line/Copy (prose quality, grammar, style consistency)
   - Expand to five bands only if metrics show measurable benefit
2. Add OpenRouter cloud integration to ModelRouter
3. Configure hybrid mode: local MoE for per-chapter critique + cloud Claude Sonnet for structural revision and voice checking
4. A/B test local Qwen3.5-35B-A3B vs cloud Claude Sonnet critique quality
5. Add LLM-as-judge evaluation with structured rubric
6. Implement blind peer review protocol for planning stages
7. Add milestone gates — pipeline pauses at First Plot Point, Midpoint, Climax for human review
8. Test: generate full 25-chapter novel draft

### Phase 5 — UI
1. Build FastAPI backend serving the pipeline
2. WebSocket endpoint for real-time pipeline progress (streaming from run ledger)
3. React frontend with these views:
   - **Dashboard**: Brooks structure progress bar, chapter quality scores, word count, promise/payoff ledger status
   - **Split-pane editor**: outline tree (left) + prose editor (right)
   - **Pipeline control**: start/pause/resume, agent activity log from run ledger, manual approve/reject, failure code breakdown per rejected scene
   - **Character tracker**: appearance matrix, knowledge states (truth vs belief layers), relationship map
   - **Pacing graph**: event density vs. ideal Brooks curve, character pressure matrix (use Recharts)
   - **Diff view**: before/after for revision bands (use CodeMirror)
   - **Codex panel**: story bible reference with quick-edit, canon search with evidence ranking display
   - **Quality dashboard**: per-chapter metrics, failure code frequency analysis
4. Export pipeline: Markdown → DOCX → EPUB

## Key Technical Decisions

- **No LangChain.** Build the orchestration layer directly with httpx + custom Python. LangChain adds abstraction overhead without proportional benefit for this focused pipeline. Borrow graph/flow concepts (typed events, diffed state mutations) without adopting a framework.
- **llama-server as primary inference backend.** Qwen3.5 models do not work with Ollama due to mmproj vision file architecture. llama-server provides the same OpenAI-compatible API and supports all model families. Ollama remains optional for simpler models.
- **OpenAI-compatible API everywhere.** Both llama-server and OpenRouter speak the same `/v1/chat/completions` format. The ModelRouter is the only component that knows which backend is active.
- **SQLite for structured state, ChromaDB for vectors.** Both are file-based, no server needed, perfect for single-user local deployment.
- **GGUF format for all local models.** Use llama.cpp ecosystem (llama-server) for inference.
- **Git for manuscript versioning.** Chapters stored as .md files, branch per revision band, diff to track changes.
- **Structured JSON output** for all planning agents (Outlines library for constrained generation with llama.cpp backend).
- **min-p sampling instead of top-p** for prose generation (min_p=0.05, temperature=0.9-1.1, top_k=0, top_p=1.0).
- **Structured failure codes over freeform critique.** Every Gate Critic rejection returns machine-readable failure labels with severity and routing decisions. This makes retries targeted and prevents style homogenization.
- **Split critic architecture.** Gate Critic (blocking, structural) and Craft Editor (non-blocking, voice/polish) prevent the "infinite critique loop flattens style" failure mode.
- **Story Physics before scene cards.** Causality chains, revelation maps, and promise/payoff tracking are validated between concept seed and drafting, preventing structurally correct but emotionally flat novels.

## Testing Strategy

- Unit tests for ModelRouter (mock both local and cloud backends)
- Unit tests for ContextAssembler (verify token budget compliance)
- Unit tests for quality metrics (known good/bad text samples)
- Unit tests for Story Physics validator (known good/bad causal graphs)
- Unit tests for failure code routing (verify correct routing per failure type)
- Unit tests for canon evidence ranking (verify confidence scoring and filtering)
- Integration test: concept seed → 1 chapter with structured gate evaluation (Phase 1 milestone)
- Integration test: concept seed → 5 chapters with continuity and promise/payoff tracking (Phase 2 milestone)
- Quality regression test: measure repetition/pacing/slop scores across runs
- Model bake-off harness: 20–30 fixed prompts, scored on structural obedience, voice, and prose quality (Phase 3)

## Environment Setup

```bash
# Python 3.11+
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# llama.cpp / llama-server (PRIMARY — required)
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp && mkdir build && cd build
cmake -DGGML_CUDA=ON .. && cmake --build . --config Release -j

# Download Phase 1 models
# Qwen3-30B-A3B-Instruct-2507 (primary reasoning, MoE, fits on 12GB GPU)
huggingface-cli download bartowski/Qwen3-30B-A3B-Instruct-2507-GGUF --include "*Q4_K_M*"

# Gemma 4 26B-A4B (fast utility, MoE, fits in ~8GB)
huggingface-cli download bartowski/Gemma-4-26B-A4B-GGUF --include "Gemma-4-26B-A4B-Q5_K_M.gguf"

# Qwen3.5-9B (small utility, dense)
huggingface-cli download bartowski/Qwen3.5-9B-GGUF --include "*Q5_K_M*"

# Embedding model (via Ollama or sentence-transformers)
ollama pull nomic-embed-text

# Run llama-server with Phase 1 primary model:
./llama-server -hf bartowski/Qwen3-30B-A3B-Instruct-2507-GGUF:Q4_K_M \
  --ctx-size 32768 --jinja -ngl 99 -fa -ub 2048 -b 2048

# For Phase 3+ (additional models — download after bake-off decision)
# Qwen3.5-35B-A3B (reasoning upgrade, requires CPU expert offload):
#   huggingface-cli download bartowski/Qwen_Qwen3.5-35B-A3B-GGUF --include "*Q4_K_M*"
#   Run with: -ot exps=CPU -ngl 99 (offload MoE experts to CPU, keep attention on GPU)
#   Requires llama.cpp build b8148+
#
# Magidonia-24B-v4.3 (prose):
#   huggingface-cli download bartowski/TheDrummer_Magidonia-24B-v4.3-GGUF --include "*Q4_K_M*"
#
# Cydonia-24B-v4.3 (prose alt):
#   huggingface-cli download bartowski/TheDrummer_Cydonia-24B-v4.3-GGUF --include "*Q4_K_M*"
#
# Qwen3.5-27B-Writer (prose alt):
#   huggingface-cli download mradermacher/Qwen3.5-27B-Writer-GGUF --include "*Q4_K_M*"

# For cloud/hybrid mode
export OPENROUTER_API_KEY=your_key_here
```
