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
    EOCExecutionPolicy,
    EmergencyOperationsCommander,
    InMemoryEOCActionAdapter,
    InMemoryHazardIntelAdapter,
    InMemoryLogisticsCapacityAdapter,
    JSONLAuditLogger,
    TriProviderPipeline,
    USE_CASE_INDEX,
    build_eoc_action_adapter_from_env,
    build_hazard_intel_adapter_from_env,
    build_logistics_capacity_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "Situation update: EOC-7001 in ZONE-NORTH with UNIT-A11 reports wildfire spread, 280000 residents, "
    "time to impact 90 minutes, hospital and nursing home at risk, mandatory evacuation issued. "
    "EOC-7002 in ZONE-EAST with UNIT-B22 reports flood risk, 65000 residents, time to impact 4 hours."
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
        help="Use EOC_*_BASE_URL and EOC_*_API_KEY env vars for adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--execute-actions-in-dry-run",
        action="store_true",
        help="Allow evacuation/shelter/alert actions in dry mode.",
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


def build_commander(args: argparse.Namespace) -> EmergencyOperationsCommander:
    spec = USE_CASE_INDEX["emergency_operations_center"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        hazard = build_hazard_intel_adapter_from_env()
        logistics = build_logistics_capacity_adapter_from_env()
        actions = build_eoc_action_adapter_from_env()
    else:
        hazard = InMemoryHazardIntelAdapter(
            zones={
                "ZONE-NORTH": {
                    "hazard_severity": 0.91,
                    "spread_velocity": 0.86,
                    "weather_volatility": 0.66,
                    "time_to_impact_minutes": 90,
                },
                "ZONE-EAST": {
                    "hazard_severity": 0.52,
                    "spread_velocity": 0.40,
                    "weather_volatility": 0.34,
                    "time_to_impact_minutes": 240,
                },
            }
        )
        logistics = InMemoryLogisticsCapacityAdapter(
            zones={
                "ZONE-NORTH": {
                    "population_exposed": 280000,
                    "vulnerable_sites_count": 4,
                    "shelter_capacity_pct": 0.38,
                    "route_access_score": 0.30,
                },
                "ZONE-EAST": {
                    "population_exposed": 65000,
                    "vulnerable_sites_count": 1,
                    "shelter_capacity_pct": 0.74,
                    "route_access_score": 0.72,
                },
            }
        )
        actions = InMemoryEOCActionAdapter()

    policy = EOCExecutionPolicy(
        execute_actions_in_dry_run=args.execute_actions_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "hazard_adapter": hazard,
        "logistics_adapter": logistics,
        "action_adapter": actions,
        "execution_policy": policy,
    }
    if args.audit_log:
        commander_kwargs["audit_logger"] = JSONLAuditLogger(Path(args.audit_log))

    return EmergencyOperationsCommander(**commander_kwargs)


def print_human(report: dict[str, object]) -> None:
    print(f"Batch ID: {report['batch_id']}")
    print(f"Mode: {report['mode']}")

    stats = report["stats"]
    assert isinstance(stats, dict)
    print(
        "Stats:",
        f"incidents={stats['incidents_total']}",
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
            f"- {row['incident_id']}: route={row['route']} priority={row['priority']} "
            f"risk={row['risk_score']:.2f} hazard={row['hazard_severity']:.2f} "
            f"population={row['population_exposed']}"
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
