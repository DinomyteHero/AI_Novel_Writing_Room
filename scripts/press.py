"""The press: build chapters from your finished plan.

Examples:
    python scripts/press.py build next
    python scripts/press.py build all
    python scripts/press.py build 4 --rounds 2
    python scripts/press.py story-so-far --title "Book One"
    python scripts/press.py export
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.studio.cli import press_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(press_main())
