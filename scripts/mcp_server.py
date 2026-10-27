"""The Writers Room tools for the Claude plugin (an MCP server over stdio).

The plugin starts this for you. On first run it installs what it needs into
its own folder (a Python virtual environment), so nothing is installed into
your system Python. Requires Python 3.10 or newer.
"""

import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEEDS = ["httpx>=0.27.0", "pyyaml>=6.0", "python-dotenv>=1.0.0", "anthropic>=2.3.0"]


def _have_dependencies() -> bool:
    try:
        import anthropic  # noqa: F401
        import dotenv  # noqa: F401
        import httpx  # noqa: F401
        import yaml  # noqa: F401
    except ImportError:
        return False
    return True


def _ensure_dependencies() -> None:
    """Use this Python if it has what's needed; otherwise a private virtual
    environment in the plugin's data folder, created on first run."""
    if _have_dependencies():
        return
    data = Path(os.environ.get("WRITERS_ROOM_DATA") or Path.home() / ".writers-room")
    env_dir = data / "venv"
    python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if Path(sys.prefix).resolve() == env_dir.resolve():
        print("Writers Room: installing what it needs (first run only)...", file=sys.stderr)
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", *NEEDS], stdout=sys.stderr, check=True)
        if not _have_dependencies():
            sys.exit("Writers Room: couldn't install its dependencies; see the messages above.")
        return
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(env_dir)
    if os.name == "nt":
        # Windows has no real exec: os.execv starts a new process and ends this
        # one, so the plugin host would see its server exit. Run it as a child.
        sys.exit(subprocess.call([str(python), __file__, *sys.argv[1:]]))
    os.execv(str(python), [str(python), __file__, *sys.argv[1:]])


if __name__ == "__main__":
    _ensure_dependencies()
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    # Plugin settings left blank arrive as empty strings; let .env fill them.
    for key in [k for k, v in os.environ.items() if v == "" and k.endswith("_API_KEY")]:
        del os.environ[key]
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")

    from src.studio.mcp import Tools, default_library, make_router_factory, serve
    from src.studio.project import Library

    config = ROOT / "config" / "settings.yaml"
    serve(Tools(Library(default_library()), make_router_factory(config), config))
