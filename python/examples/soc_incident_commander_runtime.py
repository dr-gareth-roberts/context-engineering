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
    ExecutionPolicy,
    InMemoryEDRAdapter,
    InMemoryIAMAdapter,
    InMemorySIEMAdapter,
    JSONLAuditLogger,
    SOCIncidentCommander,
    TriProviderPipeline,
    build_edr_adapter_from_env,
    build_iam_adapter_from_env,
    build_siem_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "Critical incident: user_admin logged in from two impossible geographies, "
    "created anomalous API tokens, and host finance-payroll-01.prod.corp "
    "sent large outbound traffic to 198.51.100.44."
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
        help="Use SOC_*_BASE_URL and SOC_*_API_KEY env vars for SIEM/EDR/IAM adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--execute-containment-in-dry-run",
        action="store_true",
        help="Allow host/user containment calls in dry mode.",
    )
    parser.add_argument("--max-parallel", type=int, default=4)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def load_evidence(paths: Sequence[str]) -> tuple[str, ...]:
    docs: list[str] = []
    for path in paths:
        value = Path(path).read_text(encoding="utf-8").strip()
        if value:
            docs.append(value)
    return tuple(docs)


def build_in_memory_siem() -> InMemorySIEMAdapter:
    events = [
        {
            "timestamp": "2026-02-06T02:11:00Z",
            "user": "user_admin",
            "host": "finance-payroll-01.prod.corp",
            "source_ip": "198.51.100.44",
            "event": "token_creation",
            "severity": "high",
        },
        {
            "timestamp": "2026-02-06T02:13:24Z",
            "user": "user_admin",
            "host": "finance-payroll-02.prod.corp",
            "source_ip": "198.51.100.44",
            "event": "egress_spike",
            "severity": "critical",
        },
        {
            "timestamp": "2026-02-06T02:16:10Z",
            "user": "svc_backup",
            "host": "backup-node-03.prod.corp",
            "source_ip": "203.0.113.71",
            "event": "normal_backup",
            "severity": "low",
        },
    ]
    return InMemorySIEMAdapter(events=events)


def build_commander(args: argparse.Namespace) -> SOCIncidentCommander:
    spec = USE_CASE_INDEX["soc_incident_commander"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        siem = build_siem_adapter_from_env()
        edr = build_edr_adapter_from_env()
        iam = build_iam_adapter_from_env()
    else:
        siem = build_in_memory_siem()
        edr = InMemoryEDRAdapter()
        iam = InMemoryIAMAdapter()

    audit_logger = JSONLAuditLogger(Path(args.audit_log)) if args.audit_log else None
    policy = ExecutionPolicy(
        execute_containment_in_dry_run=args.execute_containment_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "siem": siem,
        "edr": edr,
        "iam": iam,
        "execution_policy": policy,
    }
    if audit_logger is not None:
        commander_kwargs["audit_logger"] = audit_logger

    return SOCIncidentCommander(**commander_kwargs)


def print_human(report: dict[str, object]) -> None:
    print(f"Incident ID: {report['incident_id']}")
    print(f"Mode: {report['mode']}")
    print(f"High risk: {report['high_risk']}")

    stats = report["stats"]
    assert isinstance(stats, dict)
    print(
        "Stats:",
        f"siem={stats['siem_success']}/{stats['siem_total']}",
        f"edr={stats['edr_success']}/{stats['edr_total']}",
        f"iam={stats['iam_success']}/{stats['iam_total']}",
        f"skipped={stats['skipped_total']}",
        f"failed={stats['failed_total']}",
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
