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
    ContactCenterAutopilotCommander,
    ContactCenterExecutionPolicy,
    InMemoryContactResolutionActionAdapter,
    InMemoryCustomerProfileAdapter,
    InMemoryPolicyGuardrailAdapter,
    JSONLAuditLogger,
    TriProviderPipeline,
    build_contact_resolution_action_adapter_from_env,
    build_customer_profile_adapter_from_env,
    build_policy_guardrail_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "Operations stream: TICKET-BILL-1001 for CUSTOMER-ENT-77 in QUEUE-RETENTION has 62 minutes wait, "
    "4 recontacts, CSAT 35, billing dispute with regulatory complaint and angry tone, vip account. "
    "TICKET-SUPPORT-2002 for CUSTOMER-SMB-12 in QUEUE-GENERAL has 18 minutes wait, 1 recontact, CSAT 78."
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
        help="Use CONTACT_* env vars for adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--execute-actions-in-dry-run",
        action="store_true",
        help="Allow contact actions in dry mode.",
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


def build_commander(args: argparse.Namespace) -> ContactCenterAutopilotCommander:
    spec = USE_CASE_INDEX["contact_center_autopilot"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        profile = build_customer_profile_adapter_from_env()
        guardrail = build_policy_guardrail_adapter_from_env()
        actions = build_contact_resolution_action_adapter_from_env()
    else:
        profile = InMemoryCustomerProfileAdapter(
            customers={
                "CUSTOMER-ENT-77": {
                    "churn_risk": 0.88,
                    "fraud_risk": 0.26,
                    "lifetime_value_tier": 0.94,
                },
                "CUSTOMER-SMB-12": {
                    "churn_risk": 0.38,
                    "fraud_risk": 0.14,
                    "lifetime_value_tier": 0.36,
                },
            }
        )
        guardrail = InMemoryPolicyGuardrailAdapter(
            tickets={
                "TICKET-BILL-1001": {
                    "compliance_risk": 0.79,
                    "autopilot_allowed": False,
                    "supervisor_required": True,
                    "refund_flexibility": 0.62,
                    "recommended_response_template": (
                        "Acknowledge impact, confirm policy constraints, escalate supervisor, "
                        "and provide callback SLA."
                    ),
                },
                "TICKET-SUPPORT-2002": {
                    "compliance_risk": 0.22,
                    "autopilot_allowed": True,
                    "supervisor_required": False,
                    "refund_flexibility": 0.48,
                    "recommended_response_template": (
                        "Provide resolution steps, validate customer understanding, and offer follow-up option."
                    ),
                },
            }
        )
        actions = InMemoryContactResolutionActionAdapter()

    execution_policy = ContactCenterExecutionPolicy(
        execute_actions_in_dry_run=args.execute_actions_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "customer_profile_adapter": profile,
        "policy_guardrail_adapter": guardrail,
        "action_adapter": actions,
        "execution_policy": execution_policy,
    }
    if args.audit_log:
        commander_kwargs["audit_logger"] = JSONLAuditLogger(Path(args.audit_log))

    return ContactCenterAutopilotCommander(**commander_kwargs)


def print_human(report: dict[str, object]) -> None:
    print(f"Batch ID: {report['batch_id']}")
    print(f"Mode: {report['mode']}")

    stats = report["stats"]
    assert isinstance(stats, dict)
    print(
        "Stats:",
        f"tickets={stats['tickets_total']}",
        f"enrichment={stats['enrichment_success']}/{stats['enrichment_total']}",
        f"actions_ok={stats['actions_success']}",
        f"actions_skipped={stats['actions_skipped']}",
        f"actions_failed={stats['actions_failed']}",
    )

    print("\nTop decisions:")
    decisions = report.get("decisions") or []
    for row in decisions[:5]:
        assert isinstance(row, dict)
        print(
            f"- {row['ticket_id']}: route={row['route']} priority={row['priority']} "
            f"risk={row['risk_score']:.2f} wait={row['wait_minutes']}m "
            f"recontacts={row['recontact_count']}"
        )

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
