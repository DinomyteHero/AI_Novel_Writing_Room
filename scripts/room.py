"""The room: plan, review and direct changes to your book.

Examples:
    python scripts/room.py new "My Novel"
    python scripts/room.py new "Book Two" --series "My Novel"
    python scripts/room.py status
    python scripts/room.py review
    python scripts/room.py revise 3 --note "more banter, less brooding"
    python scripts/room.py rename "Mara" "Maren" --apply
    python scripts/room.py check
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.studio.cli import room_main  # noqa: E402

if __name__ == "__main__":
    sys.exit(room_main())
