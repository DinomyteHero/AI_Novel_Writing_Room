"""Validate generated prose against an executable scene contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.quality.scene_contract_validator import validate_prose_file  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate prose against a deterministic scene contract."
    )
    parser.add_argument("--contract", required=True, help="Path to scene contract JSON.")
    parser.add_argument("--prose", required=True, help="Path to generated prose file.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full validation result as JSON.",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Always exit 0, even when the contract fails.",
    )
    args = parser.parse_args()

    result = validate_prose_file(args.prose, args.contract)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        status = "PASS" if result["passed"] else "FAIL"
        print(
            f"[{status}] {result.get('scene_id') or Path(args.contract).stem}: "
            f"{result['hard_failure_count']} hard / "
            f"{result['failure_count']} total failures"
        )
        for failure in result["failures"]:
            location = f" line {failure['line']}" if "line" in failure else ""
            speaker = f" {failure['speaker']}" if "speaker" in failure else ""
            print(
                f"- {failure['severity'].upper()} {failure['check_id']}"
                f"{speaker}{location}: {failure['message']}"
            )
            if failure.get("excerpt"):
                print(f"  {failure['excerpt']}")

    if not args.no_fail and not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

