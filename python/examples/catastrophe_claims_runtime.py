from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from context_framework import (  # noqa: E402
    USE_CASE_INDEX,
    CatastropheClaimsCommander,
    ClaimsExecutionPolicy,
    InMemoryFraudAdapter,
    InMemoryPayoutAdapter,
    InMemoryPolicyAdapter,
    JSONLAuditLogger,
    TriProviderPipeline,
    build_fraud_adapter_from_env,
    build_payout_adapter_from_env,
    build_policy_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "Hurricane landfall triggered surge intake: CLM-41021 (CLMT-77001) severe roof collapse, "
    "CLM-41022 (CLMT-77002) partial flood damage, and CLM-41023 (CLMT-77003) "
    "duplicate-loss chronology with geolocation mismatch in FL-33101."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dry", "live"], default="dry")
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument(
        "--evidence-file",
        action="append",
        default=[],
        help="Path to a text file included as evidence. Can be repeated.",
    )
    parser.add_argument(
        "--use-http-adapters",
        action="store_true",
        help="Use CLAIMS_*_BASE_URL and CLAIMS_*_API_KEY env vars for adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--auto-execute-payouts-in-dry-run",
        action="store_true",
        help="Allow issue_advance/place_hold calls in dry mode.",
    )
    parser.add_argument("--max-parallel", type=int, default=6)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def load_evidence(paths: Sequence[str]) -> tuple[str, ...]:
    docs: list[str] = []
    for path in paths:
        value = Path(path).read_text(encoding="utf-8").strip()
        if value:
            docs.append(value)
    return tuple(docs)


def build_commander(args: argparse.Namespace) -> CatastropheClaimsCommander:
    spec = USE_CASE_INDEX["catastrophe_claims_pipeline"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        policy_adapter = build_policy_adapter_from_env()
        fraud_adapter = build_fraud_adapter_from_env()
        payout_adapter = build_payout_adapter_from_env()
    else:
        policy_adapter = InMemoryPolicyAdapter(
            claims={
                "CLM-41021": {
                    "policy_status": "active",
                    "coverage_limit_cents": 2_500_000,
                    "deductible_cents": 100_000,
                },
                "CLM-41022": {
                    "policy_status": "active",
                    "coverage_limit_cents": 800_000,
                    "deductible_cents": 75_000,
                },
                "CLM-41023": {
                    "policy_status": "active",
                    "coverage_limit_cents": 1_200_000,
                    "deductible_cents": 50_000,
                },
            }
        )
        fraud_adapter = InMemoryFraudAdapter(
            scores={
                "CLM-41021": 0.08,
                "CLM-41022": 0.22,
                "CLM-41023": 0.93,
            }
        )
        payout_adapter = InMemoryPayoutAdapter()

    audit_logger = JSONLAuditLogger(Path(args.audit_log)) if args.audit_log else None
    policy = ClaimsExecutionPolicy(
        auto_execute_payouts_in_dry_run=args.auto_execute_payouts_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "policy_adapter": policy_adapter,
        "fraud_adapter": fraud_adapter,
        "payout_adapter": payout_adapter,
        "execution_policy": policy,
    }
    if audit_logger is not None:
        commander_kwargs["audit_logger"] = audit_logger

    return CatastropheClaimsCommander(**commander_kwargs)


def print_human(report: dict[str, object]) -> None:
    print(f"Batch ID: {report['batch_id']}")
    print(f"Mode: {report['mode']}")

    stats = report["stats"]
    assert isinstance(stats, dict)
    print(
        "Stats:",
        f"policy={stats['policy_success']}/{stats['policy_total']}",
        f"fraud={stats['fraud_success']}/{stats['fraud_total']}",
        f"payout={stats['payout_success']}/{stats['payout_total']}",
        f"skipped={stats['skipped_total']}",
        f"failed={stats['failed_total']}",
    )

    print("\nTop assessments:")
    assessments = report.get("assessments") or []
    for row in assessments[:5]:
        assert isinstance(row, dict)
        print(
            "-",
            row["claim_id"],
            f"action={row['recommended_action']}",
            f"priority={row['priority_score']:.2f}",
            f"severity={row['severity_score']:.2f}",
            f"fraud={row['fraud_score']:.2f}",
        )

    print("\nAction plan:")
    for step in report["action_plan"]:
        print(f"- {step}")

    print("\nRecommendations:")
    for rec in report["recommendations"]:
        print(f"- {rec}")

    warnings = report.get("warnings") or []
    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"- {warning}")

    errors = report.get("errors") or []
    if errors:
        print("\nErrors:")
        for err in errors:
            print(f"- {err}")


def main() -> None:
    args = parse_args()
    commander = build_commander(args)

    report = commander.run(
        scenario=args.scenario,
        evidence_documents=load_evidence(args.evidence_file),
        mode=args.mode,
    ).to_dict()

    if args.json:
        print(json.dumps(report, indent=2))
        return

    print_human(report)


if __name__ == "__main__":
    main()
