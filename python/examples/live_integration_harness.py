from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from context_framework import LiveIntegrationHarness


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="append",
        default=[],
        help=("Check name to run. Can be repeated. Defaults to all checks."),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat skipped checks as failure.",
    )
    parser.add_argument(
        "--use-case-id",
        default="text_governance_orchestrator",
        help="Use-case ID for tri_provider_live check.",
    )
    parser.add_argument(
        "--anthropic-method",
        choices=["query", "client"],
        default="query",
        help="Anthropic agentic SDK execution mode.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    harness = LiveIntegrationHarness(
        strict=args.strict,
        use_case_id=args.use_case_id,
        anthropic_method=args.anthropic_method,
    )
    report = harness.run(args.check or None)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return

    payload = report.to_dict()
    print(f"Success: {payload['success']}")
    print(f"Passed: {payload['passed']}")
    print(f"Failed: {payload['failed']}")
    print(f"Skipped: {payload['skipped']}")
    print("")

    for row in payload["checks"]:
        print(f"[{row['status']}] {row['check']} ({row['duration_ms']}ms)")
        print(f"  {row['message']}")
        if row["details"]:
            print(f"  details={json.dumps(row['details'])}")

    if not report.success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
