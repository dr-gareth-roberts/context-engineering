from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from context_framework import USE_CASES, TriProviderPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dry", "live"], default="dry")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reports = []
    for spec in USE_CASES:
        pipeline = TriProviderPipeline(spec)
        report = pipeline.run(
            scenario=f"Run the {spec.title} scenario with high urgency and constrained resources.",
            mode=args.mode,
        )
        reports.append(report)

    if args.json:
        print(json.dumps([r.to_dict() for r in reports], indent=2))
        return

    for report in reports:
        print(f"[{report.use_case_id}] {report.title}")
        print(
            f"  mode={report.mode} tokens={report.context_tokens_used}/{report.context_token_budget}"
        )
        if report.ranked_actions:
            top = report.ranked_actions[0]
            print(f"  top_action={top.action}")
            print(f"  top_score={top.score:.4f} source={top.source}")
        if report.warnings:
            print(f"  warnings={len(report.warnings)}")
        if report.errors:
            print(f"  errors={len(report.errors)}")
        print("")


if __name__ == "__main__":
    main()
