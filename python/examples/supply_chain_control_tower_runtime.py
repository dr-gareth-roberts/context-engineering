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
    InMemoryFulfillmentActionAdapter,
    InMemoryLaneDelayAdapter,
    InMemorySupplierRiskAdapter,
    JSONLAuditLogger,
    SupplyChainControlTowerCommander,
    SupplyChainExecutionPolicy,
    TriProviderPipeline,
    build_fulfillment_action_adapter_from_env,
    build_lane_delay_adapter_from_env,
    build_supplier_risk_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "Port disruption alert: ORD-7001 on LANE-SEA-LAX with SUP-ALPHA has 26h delay, "
    "ORD-7002 on LANE-SZX-LAX with SUP-BETA has 14h delay, and ORD-7003 on LANE-RTM-JFK "
    "with SUP-GAMMA shows constrained capacity."
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
        help="Use SUPPLY_*_BASE_URL and SUPPLY_*_API_KEY env vars for adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--execute-actions-in-dry-run",
        action="store_true",
        help="Allow reroute/split/expedite/hold calls in dry mode.",
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


def build_commander(args: argparse.Namespace) -> SupplyChainControlTowerCommander:
    spec = USE_CASE_INDEX["supply_chain_control_tower"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        lane = build_lane_delay_adapter_from_env()
        supplier = build_supplier_risk_adapter_from_env()
        actions = build_fulfillment_action_adapter_from_env()
    else:
        lane = InMemoryLaneDelayAdapter(
            lanes={
                "LANE-SEA-LAX": {
                    "delay_hours": 26,
                    "congestion_level": "critical",
                    "alternate_lane": "LANE-SEA-OAK-LAX",
                },
                "LANE-SZX-LAX": {
                    "delay_hours": 14,
                    "congestion_level": "high",
                    "alternate_lane": "SZX->LGB",
                },
                "LANE-RTM-JFK": {
                    "delay_hours": 6,
                    "congestion_level": "medium",
                    "alternate_lane": "RTM->EWR",
                },
            }
        )
        supplier = InMemorySupplierRiskAdapter(
            suppliers={
                "SUP-ALPHA": {"risk_score": 0.31, "capacity_pct": 0.72},
                "SUP-BETA": {"risk_score": 0.22, "capacity_pct": 0.55},
                "SUP-GAMMA": {"risk_score": 0.88, "capacity_pct": 0.28},
            }
        )
        actions = InMemoryFulfillmentActionAdapter()

    policy = SupplyChainExecutionPolicy(
        execute_actions_in_dry_run=args.execute_actions_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "lane_delay_adapter": lane,
        "supplier_risk_adapter": supplier,
        "fulfillment_action_adapter": actions,
        "execution_policy": policy,
    }
    if args.audit_log:
        commander_kwargs["audit_logger"] = JSONLAuditLogger(Path(args.audit_log))

    return SupplyChainControlTowerCommander(**commander_kwargs)


def print_human(report: dict[str, object]) -> None:
    print(f"Batch ID: {report['batch_id']}")
    print(f"Mode: {report['mode']}")

    stats = report["stats"]
    assert isinstance(stats, dict)
    print(
        "Stats:",
        f"orders={stats['orders_total']}",
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
            f"- {row['order_id']}: route={row['route']} priority={row['priority']} "
            f"delay={row['lane_delay_hours']}h risk={row['supplier_risk']:.2f}"
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
