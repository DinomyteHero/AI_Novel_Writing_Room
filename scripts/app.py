"""The Writers Room app: plan in conversation and build chapters, in your browser.

    python scripts/app.py               # opens http://127.0.0.1:8765/
    python scripts/app.py --port 9000 --no-browser
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.app.api import App  # noqa: E402
from src.app.server import serve  # noqa: E402
from src.studio.project import Library  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="app.py", description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--library", help="Library folder (default: ./library)")
    parser.add_argument("--no-browser", action="store_true", help="Don't open the browser")
    args = parser.parse_args()
    library = Path(args.library or os.environ.get("WRITERS_ROOM_LIBRARY") or ROOT / "library")
    app = App(Library(library), ROOT / "config" / "settings.yaml", ROOT / ".env")
    serve(app, port=args.port, open_browser=not args.no_browser)
