"""Abstract base class for all writer's room agents."""

from abc import ABC, abstractmethod
from pathlib import Path

from src.model_router import ModelRouter


class BaseAgent(ABC):
    """Abstract base class for all writer's room agents.

    Each agent handles one cognitive task with its own model, temperature,
    and prompt template. All agents communicate through the ModelRouter.
    """

    def __init__(self, router: ModelRouter, role: str):
        self.router = router
        self.role = role
        self.system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        prompt_path = Path(f"prompts/agent_system_prompts/{self.role}.md")
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return f"You are the {self.role} agent."

    async def run(self, context: dict) -> dict:
        """Execute the agent's task. Returns structured output."""
        messages = self._build_messages(context)
        response = await self.router.complete(self.role, messages)
        return self._parse_response(response, context)

    async def run_structured(self, context: dict) -> dict:
        """Execute the agent's task expecting JSON output."""
        messages = self._build_messages(context)
        return await self.router.complete_structured(self.role, messages)

    def _build_messages(self, context: dict) -> list[dict]:
        messages = [{"role": "system", "content": self.system_prompt}]
        franchise_profile = context.get("franchise_profile_text", "")
        if franchise_profile:
            # Loaded from prompts/franchise_profiles/<slug>.md based on
            # concept_seed.meta.franchise_profile. Injected as a second
            # system message so franchise-specific register, author
            # references, and magic-system rules can be swapped per-project
            # without editing the agent prompts.
            messages.append({"role": "system", "content": franchise_profile})
        messages.append({"role": "user", "content": self._format_context(context)})
        return messages

    @abstractmethod
    def _format_context(self, context: dict) -> str:
        """Format the context dict into the user prompt."""
        ...

    @abstractmethod
    def _parse_response(self, response: str, context: dict) -> dict:
        """Parse the raw LLM response into structured output."""
        ...
