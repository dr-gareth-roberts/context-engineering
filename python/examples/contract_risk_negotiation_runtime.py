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
    ContractExecutionPolicy,
    ContractNegotiationCommander,
    InMemoryClauseRiskAdapter,
    InMemoryContractActionAdapter,
    InMemoryNegotiationPrecedentAdapter,
    JSONLAuditLogger,
    TriProviderPipeline,
    build_clause_risk_adapter_from_env,
    build_contract_action_adapter_from_env,
    build_negotiation_precedent_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "Negotiation packet: CONTRACT-ALPHA-2026 includes CLAUSE-LIABILITY-01 for strategic vendor "
    "VENDOR-OMEGA with unlimited liability and 5x cap over 48 months. "
    "CONTRACT-BETA-771 includes CLAUSE-DATA-77 for VENDOR-SIGMA with broad data use rights over "
    "24 months and 1x cap."
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
        help="Use CONTRACT_*_BASE_URL and CONTRACT_*_API_KEY env vars for adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--execute-actions-in-dry-run",
        action="store_true",
        help="Allow contract action calls in dry mode.",
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


def build_commander(args: argparse.Namespace) -> ContractNegotiationCommander:
    spec = USE_CASE_INDEX["contract_risk_negotiation"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        clause_risk = build_clause_risk_adapter_from_env()
        precedent = build_negotiation_precedent_adapter_from_env()
        actions = build_contract_action_adapter_from_env()
    else:
        clause_risk = InMemoryClauseRiskAdapter(
            clauses={
                "CLAUSE-LIABILITY-01": {
                    "clause_severity": 0.93,
                    "counterparty_resistance": 0.82,
                    "enforceability_risk": 0.88,
                },
                "CLAUSE-DATA-77": {
                    "clause_severity": 0.60,
                    "counterparty_resistance": 0.66,
                    "enforceability_risk": 0.56,
                },
            }
        )
        precedent = InMemoryNegotiationPrecedentAdapter(
            clauses={
                "CLAUSE-LIABILITY-01": {
                    "precedent_acceptance_rate": 0.28,
                    "fallback_cap_multiplier": 1.0,
                    "fallback_text": (
                        "Cap aggregate liability at 1x fees, carve out only willful misconduct, "
                        "and tie data use to contracted services."
                    ),
                },
                "CLAUSE-DATA-77": {
                    "precedent_acceptance_rate": 0.70,
                    "fallback_cap_multiplier": 1.0,
                    "fallback_text": (
                        "Restrict data rights to service delivery, support, and aggregated "
                        "performance analytics only."
                    ),
                },
            }
        )
        actions = InMemoryContractActionAdapter()

    policy = ContractExecutionPolicy(
        execute_actions_in_dry_run=args.execute_actions_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "clause_risk_adapter": clause_risk,
        "precedent_adapter": precedent,
        "action_adapter": actions,
        "execution_policy": policy,
    }
    if args.audit_log:
        commander_kwargs["audit_logger"] = JSONLAuditLogger(Path(args.audit_log))

    return ContractNegotiationCommander(**commander_kwargs)


def print_human(report: dict[str, object]) -> None:
    print(f"Batch ID: {report['batch_id']}")
    print(f"Mode: {report['mode']}")

    stats = report["stats"]
    assert isinstance(stats, dict)
    print(
        "Stats:",
        f"contracts={stats['contracts_total']}",
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
            f"- {row['contract_id']}: route={row['route']} priority={row['priority']} "
            f"risk={row['risk_score']:.2f} clause={row['clause_id']} "
            f"term_months={row['term_months']}"
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
