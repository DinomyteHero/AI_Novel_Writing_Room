"""WorkshopRunner — CLI entry point for concept workshop sessions.

Manages the conversation loop, state persistence, session transcription,
and context summarization for multi-session concept development.

Usage:
    python -m src.concept_workshop.workshop_runner --project beyond_the_veil
    python -m src.concept_workshop.workshop_runner --project beyond_the_veil --resume
    python -m src.concept_workshop.workshop_runner --project beyond_the_veil --finalize
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from src.model_router import ModelRouter
from src.concept_workshop.state_writer import ConceptWorkshopStateWriter
from src.concept_workshop.workshop_summarizer import WorkshopSummarizer
from src.concept_workshop.series_manager import SeriesManager

logger = logging.getLogger(__name__)

_EXIT_COMMANDS = {"exit", "done", "finalize"}


class WorkshopRunner:
    """Runs an interactive concept workshop session."""

    def __init__(
        self,
        project_name: str,
        router: ModelRouter,
        resume: bool = False,
        series: bool = False,
        continue_from: str | None = None,
        promote_to_series: bool = False,
        input_fn=None,
        print_fn=None,
    ):
        self.project_name = project_name
        self.router = router
        self.resume = resume
        self.series = series
        self.continue_from = continue_from
        self.promote_to_series = promote_to_series
        self._input = input_fn or input
        self._print = print_fn or print

        self.project_dir = Path(f"data/story_bibles/{project_name}")
        self.project_dir.mkdir(parents=True, exist_ok=True)
        sessions_dir = self.project_dir / "workshop_sessions"
        sessions_dir.mkdir(exist_ok=True)

        self.state_writer = ConceptWorkshopStateWriter(
            project_name, self.project_dir, router,
        )
        self.series_manager = SeriesManager(self.project_dir)
        self.summarizer = WorkshopSummarizer(router, self.project_dir)
        self.conversation_history: list[dict] = []
        self.session_id = self._next_session_id(sessions_dir)
        self.transcript_path = sessions_dir / f"{self.session_id}.jsonl"

        # Set project scope based on flags
        if series:
            self.state_writer.state.meta["project_scope"] = "planned_series"
        elif continue_from:
            self.state_writer.state.meta["project_scope"] = "continuation"

    async def run(self) -> None:
        """Run the interactive conversation loop."""
        self.router.start_workshop_session()

        system_prompt = self._load_system_prompt()
        if self.resume:
            session_ctx = self.state_writer.get_session_context()
            system_prompt = system_prompt + "\n\n" + session_ctx

        # Phase 5: Inject continuation context from transition snapshot
        if self.continue_from:
            try:
                snapshot = self.series_manager.import_transition_snapshot(self.continue_from)
                system_prompt += (
                    "\n\n## Inherited State from Previous Book\n"
                    f"Book {snapshot.get('book_number', '?')} transition snapshot loaded.\n"
                    f"Characters: {len(snapshot.get('character_end_states', []))}\n"
                    f"Unresolved threads: {len(snapshot.get('unresolved_threads', []))}\n"
                    f"Unresolved hooks: {len(snapshot.get('unresolved_hooks', []))}\n"
                    "Review these inherited elements and confirm which carry forward."
                )
            except (FileNotFoundError, ValueError) as e:
                self._print(f"Warning: Could not load transition snapshot: {e}")

        self.conversation_history.append(
            {"role": "system", "content": system_prompt},
        )

        # Get the initial assistant greeting.
        response = await self.router.complete(
            "concept_workshop", self.conversation_history,
        )
        self._print(f"\nAssistant: {response}\n")
        self.conversation_history.append({"role": "assistant", "content": response})
        self._append_transcript("assistant", response)
        await self.state_writer.process_turn("assistant", response)

        # Main loop.
        finalize_requested = False
        try:
            while True:
                try:
                    user_input = self._input("You: ")
                except EOFError:
                    break

                user_input = user_input.strip()
                if not user_input:
                    continue

                if user_input.lower() in _EXIT_COMMANDS:
                    if user_input.lower() == "finalize":
                        finalize_requested = True
                    break

                self.conversation_history.append({"role": "user", "content": user_input})
                self._append_transcript("human", user_input)
                await self.state_writer.process_turn("human", user_input)

                # Check if summarization is needed.
                if self.summarizer.should_summarize(self.conversation_history):
                    logger.info("Context threshold reached — summarizing...")
                    summary = await self.summarizer.summarize(
                        self.conversation_history,
                        self.state_writer.state,
                        session_id=self.session_id,
                    )
                    recent = self.conversation_history[-WorkshopSummarizer.DEFAULT_RECENT_TURNS:]
                    self.conversation_history = self.summarizer.rebuild_context(
                        summary, recent, self.state_writer.state,
                    )

                response = await self.router.complete(
                    "concept_workshop", self.conversation_history,
                )
                self._print(f"\nAssistant: {response}\n")
                self.conversation_history.append({"role": "assistant", "content": response})
                self._append_transcript("assistant", response)
                await self.state_writer.process_turn("assistant", response)

        except KeyboardInterrupt:
            self._print("\nSession interrupted — saving state...")

        # Clean shutdown.
        self.state_writer.state.save(self.state_writer.state_path)
        self.router.end_workshop_session()

        if finalize_requested:
            output = str(self.project_dir / "book_1_seed.json")
            self.state_writer.finalize(output)
            self._print(f"Concept seed finalized → {output}")

        # Print status summary.
        confirmed = self.state_writer.state.get_confirmed_summary()
        open_qs = self.state_writer.state.get_open_questions()
        self._print(f"\n--- Session summary ---\n{confirmed}")
        if open_qs:
            self._print(f"\nPending ({len(open_qs)} fields):")
            for q in open_qs[:5]:
                self._print(f"  - {q}")
            if len(open_qs) > 5:
                self._print(f"  ... and {len(open_qs) - 5} more")

    def _next_session_id(self, sessions_dir: Path) -> str:
        """Determine the next sequential session ID."""
        existing = sorted(sessions_dir.glob("session_*.jsonl"))
        if existing:
            last_name = existing[-1].stem  # e.g. "session_003"
            last_num = int(last_name.split("_")[1])
            return f"session_{last_num + 1:03d}"
        return "session_001"

    def _load_system_prompt(self) -> str:
        """Load the concept workshop system prompt."""
        prompt_path = Path("prompts/concept_workshop.md")
        if prompt_path.exists():
            return prompt_path.read_text(encoding="utf-8")
        return "You are a concept workshop facilitator."

    def _append_transcript(self, role: str, content: str) -> None:
        """Append a turn to the session transcript JSONL."""
        entry = {"role": role, "content": content}
        with open(self.transcript_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Concept Workshop")
    parser.add_argument("--project", required=True, help="Project name")
    parser.add_argument("--resume", action="store_true", help="Resume existing session")
    parser.add_argument("--mode", default=None, help="Override deployment mode")
    parser.add_argument("--finalize", action="store_true", help="Finalize concept seed")
    # Phase 5 flags
    parser.add_argument("--series", action="store_true", help="Planned series mode")
    parser.add_argument("--continue-from", type=str, default=None,
                        help="Path to previous book's transition snapshot")
    parser.add_argument("--promote-to-series", action="store_true",
                        help="Promote standalone concept to series")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    config_path = "config/settings.yaml"
    router = ModelRouter(config_path)

    if args.finalize:
        project_dir = Path(f"data/story_bibles/{args.project}")
        writer = ConceptWorkshopStateWriter(args.project, project_dir, router)
        output_path = str(project_dir / "book_1_seed.json")
        writer.finalize(output_path)
        print(f"Concept seed finalized → {output_path}")
        return

    runner = WorkshopRunner(
        args.project, router,
        resume=args.resume,
        series=args.series,
        continue_from=getattr(args, "continue_from", None),
        promote_to_series=getattr(args, "promote_to_series", False),
    )
    try:
        asyncio.run(runner.run())
    except KeyboardInterrupt:
        print("\nSession interrupted — saving state...")
        runner.state_writer.state.save(runner.state_writer.state_path)
        print("State saved. Resume with --resume.")


if __name__ == "__main__":
    main()
