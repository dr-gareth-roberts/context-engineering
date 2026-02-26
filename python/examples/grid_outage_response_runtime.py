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
    GridExecutionPolicy,
    GridOutageCommander,
    InMemoryCriticalLoadAdapter,
    InMemoryGridActionAdapter,
    InMemoryGridTelemetryAdapter,
    JSONLAuditLogger,
    TriProviderPipeline,
    build_critical_load_adapter_from_env,
    build_grid_action_adapter_from_env,
    build_grid_telemetry_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "Outage briefing: OUT-9001 tied to SUB-A12 and FEEDER-F21 with cascading instability, "
    "620000 customers affected, restoration ETA 220 minutes, impacting hospital and water treatment "
    "infrastructure. OUT-9002 tied to SUB-B44 and FEEDER-G11 with 95000 customers and ETA 70 minutes."
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
        help="Use GRID_*_BASE_URL and GRID_*_API_KEY env vars for adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--execute-actions-in-dry-run",
        action="store_true",
        help="Allow dispatch/load-shed/notification calls in dry mode.",
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


def build_commander(args: argparse.Namespace) -> GridOutageCommander:
    spec = USE_CASE_INDEX["grid_outage_response"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        telemetry = build_grid_telemetry_adapter_from_env()
        critical_load = build_critical_load_adapter_from_env()
        action_adapter = build_grid_action_adapter_from_env()
    else:
        telemetry = InMemoryGridTelemetryAdapter(
            substations={
                "SUB-A12": {
                    "instability_score": 0.94,
                    "restoration_eta_minutes": 220,
                    "customers_affected": 620000,
                },
                "SUB-B44": {
                    "instability_score": 0.51,
                    "restoration_eta_minutes": 70,
                    "customers_affected": 95000,
                },
            }
        )
        critical_load = InMemoryCriticalLoadAdapter(
            feeders={
                "FEEDER-F21": {
                    "critical_sites_count": 5,
                    "hospitals_impacted": 2,
                    "life_safety_load_mw": 78.0,
                },
                "FEEDER-G11": {
                    "critical_sites_count": 1,
                    "hospitals_impacted": 0,
                    "life_safety_load_mw": 11.5,
                },
            }
        )
        action_adapter = InMemoryGridActionAdapter()

    policy = GridExecutionPolicy(
        execute_actions_in_dry_run=args.execute_actions_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "telemetry_adapter": telemetry,
        "critical_load_adapter": critical_load,
        "action_adapter": action_adapter,
        "execution_policy": policy,
    }
    if args.audit_log:
        commander_kwargs["audit_logger"] = JSONLAuditLogger(Path(args.audit_log))

    return GridOutageCommander(**commander_kwargs)


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
            f"risk={row['risk_score']:.2f} instability={row['instability_score']:.2f} "
            f"customers={row['customers_affected']}"
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
