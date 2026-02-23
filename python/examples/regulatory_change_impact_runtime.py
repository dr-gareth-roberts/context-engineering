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
    InMemoryComplianceActionAdapter,
    InMemoryControlCoverageAdapter,
    InMemoryRegulationIntelAdapter,
    JSONLAuditLogger,
    RegulatoryChangeCommander,
    RegulatoryExecutionPolicy,
    TriProviderPipeline,
    USE_CASE_INDEX,
    build_compliance_action_adapter_from_env,
    build_control_coverage_adapter_from_env,
    build_regulation_intel_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "Regulatory update: REG-AI-2026 for DOMAIN-MODEL-RISK owned by TEAM-GOV must comply in 120 days "
    "with model inventory and annual attestation obligations. "
    "REG-OPS-771 for DOMAIN-INCIDENT-REPORTING owned by TEAM-SEC requires mandatory incident reporting "
    "within 45 days with enforcement penalties."
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
        help="Use REG_CHANGE_*_BASE_URL and REG_CHANGE_*_API_KEY env vars for adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--execute-actions-in-dry-run",
        action="store_true",
        help="Allow compliance action calls in dry mode.",
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


def build_commander(args: argparse.Namespace) -> RegulatoryChangeCommander:
    spec = USE_CASE_INDEX["regulatory_change_impact"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        intel = build_regulation_intel_adapter_from_env()
        coverage = build_control_coverage_adapter_from_env()
        actions = build_compliance_action_adapter_from_env()
    else:
        intel = InMemoryRegulationIntelAdapter(
            requirements={
                "REG-AI-2026": {
                    "obligation_severity": 0.78,
                    "deadline_days": 120,
                    "penalty_risk": 0.64,
                    "obligations_count": 12,
                },
                "REG-OPS-771": {
                    "obligation_severity": 0.88,
                    "deadline_days": 45,
                    "penalty_risk": 0.82,
                    "obligations_count": 9,
                },
            }
        )
        coverage = InMemoryControlCoverageAdapter(
            domains={
                "DOMAIN-MODEL-RISK": {
                    "coverage_pct": 0.58,
                    "open_findings": 7,
                    "evidence_freshness_days": 122,
                },
                "DOMAIN-INCIDENT-REPORTING": {
                    "coverage_pct": 0.41,
                    "open_findings": 8,
                    "evidence_freshness_days": 98,
                },
            }
        )
        actions = InMemoryComplianceActionAdapter()

    policy = RegulatoryExecutionPolicy(
        execute_actions_in_dry_run=args.execute_actions_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "regulation_intel_adapter": intel,
        "control_coverage_adapter": coverage,
        "compliance_action_adapter": actions,
        "execution_policy": policy,
    }
    if args.audit_log:
        commander_kwargs["audit_logger"] = JSONLAuditLogger(Path(args.audit_log))

    return RegulatoryChangeCommander(**commander_kwargs)


def print_human(report: dict[str, object]) -> None:
    print(f"Batch ID: {report['batch_id']}")
    print(f"Mode: {report['mode']}")

    stats = report["stats"]
    assert isinstance(stats, dict)
    print(
        "Stats:",
        f"requirements={stats['requirements_total']}",
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
            f"- {row['requirement_id']}: route={row['route']} priority={row['priority']} "
            f"risk={row['risk_score']:.2f} coverage={row['coverage_pct']:.2f} "
            f"deadline_days={row['deadline_days']}"
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
