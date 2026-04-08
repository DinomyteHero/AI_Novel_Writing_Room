"""Web server entry point for the AI Writers' Room.

Usage:
    python -m src.ui.server data/story_bibles/beyond_the_veil/concept_seed.json
    python -m src.ui.server concept_seed.json --port 8080 --dev
"""

import argparse
import sys


def run_server(
    concept_seed_path: str,
    config_path: str = "config/settings.yaml",
    host: str = "127.0.0.1",
    port: int = 8000,
    phase: int = 4,
    dev: bool = False,
) -> None:
    """Start the FastAPI server with uvicorn."""
    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn not installed. Run: pip install uvicorn[standard]")
        sys.exit(1)

    try:
        from src.ui.app import create_app
    except ImportError as e:
        print(f"Error: FastAPI dependencies not available: {e}")
        print("Run: pip install fastapi uvicorn[standard] websockets")
        sys.exit(1)

    app = create_app(
        config_path=config_path,
        concept_seed_path=concept_seed_path,
        phase=phase,
    )

    print(f"Starting AI Writers' Room web server...")
    print(f"  Config: {config_path}")
    print(f"  Concept seed: {concept_seed_path}")
    print(f"  Phase: {phase}")
    print(f"  URL: http://{host}:{port}")

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=dev,
        log_level="info",
    )


def main():
    """CLI entry point for the web server."""
    parser = argparse.ArgumentParser(
        description="AI Writers' Room — Web Server"
    )
    parser.add_argument(
        "concept_seed",
        help="Path to the concept seed JSON file",
    )
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="Path to settings.yaml (default: config/settings.yaml)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Server port (default: 8000)",
    )
    parser.add_argument(
        "--phase",
        type=int,
        default=4,
        choices=[1, 2, 3, 4],
        help="Pipeline phase (default: 4)",
    )
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Enable auto-reload for development",
    )

    args = parser.parse_args()

    from pathlib import Path
    if not Path(args.concept_seed).exists():
        print(f"Error: Concept seed not found: {args.concept_seed}")
        sys.exit(1)
    if not Path(args.config).exists():
        print(f"Error: Config not found: {args.config}")
        sys.exit(1)

    run_server(
        concept_seed_path=args.concept_seed,
        config_path=args.config,
        host=args.host,
        port=args.port,
        phase=args.phase,
        dev=args.dev,
    )


if __name__ == "__main__":
    main()
