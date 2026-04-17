# Adding Agents

This guide explains how to create a new agent for the pipeline.

## Step 1: Create the System Prompt

Create a Markdown file in `prompts/agent_system_prompts/{role_name}.md`. This is loaded automatically by `BaseAgent._load_system_prompt()`.

The prompt should define:
- The agent's role and responsibilities
- What input it receives
- What output format it should produce
- Evaluation criteria or constraints

Look at existing prompts for examples:
- `prompts/agent_system_prompts/gate_critic.md` -- Structured JSON output with failure codes
- `prompts/agent_system_prompts/prose_stylist.md` -- Free-text prose output
- `prompts/agent_system_prompts/character_specialist.md` -- Structured analysis with JSON

## Step 2: Implement the Agent Class

Create a new file in `src/agents/` that extends `BaseAgent`:

```python
from src.agents.base_agent import BaseAgent
from src.model_router import ModelRouter


class MyAgent(BaseAgent):
    def __init__(self, router: ModelRouter):
        super().__init__(router, role="my_agent")  # matches prompt filename

    def _format_context(self, context: dict) -> str:
        """Build the user prompt from the context dict."""
        prose = context["prose"]
        scene_card = context.get("scene_card", {})
        # Build a string with all the context the agent needs
        return f"## Scene Card\n{scene_card}\n\n## Prose\n{prose}"

    def _parse_response(self, response: str, context: dict) -> dict:
        """Parse the LLM's response into structured output."""
        # For JSON responses, parse and validate
        # For free-text responses, wrap in a dict
        return {"output": response}
```

For agents that return JSON, use `run_structured()` instead of `run()`:

```python
async def analyze(self, context: dict) -> dict:
    return await self.run_structured(context)
```

## Step 3: Add Agent Routing

Add the agent to `config/settings.yaml` under `agent_routing`:

```yaml
agent_routing:
  my_agent: { backend: local, model: primary_moe, params: { temperature: 0.4 } }
```

Choose appropriate settings:
- **backend**: `local` for high-volume calls, `cloud` for quality-critical evaluation
- **model**: `primary_moe` for complex reasoning, `fast_moe` for quick tasks, `utility` for simple operations
- **temperature**: Lower (0.2-0.4) for evaluation/analysis, higher (0.7-1.0) for creative generation

## Step 4: Integrate with the Orchestrator

If the agent should run as part of the per-chapter pipeline:

1. Add it as an optional dependency in `Orchestrator.__init__()`:
   ```python
   my_agent: Optional["MyAgent"] = None,
   ```

2. Call it at the appropriate point in `run_chapter()`:
   ```python
   if self.my_agent is not None:
       result = await self.my_agent.run(context)
       self.ledger.emit("my_agent_complete", chapter_number=..., payload=result)
   ```

3. Initialize it in `src/main.py` within the appropriate phase init function.

Follow the optional dependency pattern -- always check for `None` so lower phases still work.

## Template-Driven Agent Pattern

For agents that need to work across multiple franchises without hardcoded franchise-specific strings, use the **template-driven agent pattern**. The Canon Expert agent is the reference implementation of this approach.

Key principles:

- The agent's system prompt is franchise-agnostic -- it contains no hardcoded franchise names, lore, or terminology
- All franchise-specific context is read from the concept seed's `canon_profile` at runtime and injected into the prompt template
- The `canon_profile` (constructed during Step 1 of the Concept Workshop) provides franchise name, continuity rules, key canon elements, cross-continuity violations to avoid, and canon-specific terminology
- This makes the agent automatically work for any franchise without code changes

When building a new agent that needs franchise awareness, follow the Canon Expert's pattern: define a generic prompt template with placeholder sections, and populate them from the concept seed's structured data at runtime. Avoid embedding franchise-specific knowledge in the prompt file itself.

## Step 5: Legacy — Revision Band Prompts

> **Deprecated.** The 3-band revision pipeline and `src/revision/` module were removed in the [pipeline redesign](../architecture/pipeline-redesign.md). Polish is now a single bounded `quality_polish` pass guarded by a compression check and the Final Gate.
>
> New "polish-like" behaviors should extend [`src/agents/quality_polish.py`](../../src/agents/quality_polish.py) or add a new agent that runs alongside it — not a revision band. The `prompts/revision_prompts/` directory and any `AdaptiveRevisionPipeline` references in older docs describe a dead code path.

## Step 6: Write Tests

Create `tests/test_my_agent.py`. Use the `mock_router` fixture to provide canned LLM responses:

```python
import pytest
from src.agents.my_agent import MyAgent


@pytest.mark.asyncio
async def test_my_agent_basic(mock_router):
    agent = MyAgent(mock_router)
    result = await agent.run({"prose": "test prose", "scene_card": {}})
    assert "output" in result
```

## Checklist

- [ ] System prompt in `prompts/agent_system_prompts/{role}.md`
- [ ] Agent class in `src/agents/{name}.py` extending `BaseAgent`
- [ ] Agent routing in `config/settings.yaml`
- [ ] Orchestrator integration (if pipeline agent)
- [ ] Tests in `tests/test_{name}.py`
- [ ] Event logging via `ledger.emit()`
