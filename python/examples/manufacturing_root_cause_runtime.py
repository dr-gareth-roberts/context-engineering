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
    InMemoryLineTelemetryAdapter,
    InMemoryMaintenanceHistoryAdapter,
    InMemoryManufacturingActionAdapter,
    JSONLAuditLogger,
    ManufacturingExecutionPolicy,
    ManufacturingRootCauseCommander,
    TriProviderPipeline,
    build_line_telemetry_adapter_from_env,
    build_maintenance_history_adapter_from_env,
    build_manufacturing_action_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "Production incident: MFG-8101 on LINE-A12 with ASSET-R77 after shift B firmware change, "
    "18% yield drop, 10.8 mm/s vibration, and 94 C thermal reading with safety interlock trips. "
    "MFG-8102 on LINE-C31 with ASSET-P12 shows 7% yield drop and 5.2 mm/s vibration."
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
        help="Use MFG_*_BASE_URL and MFG_*_API_KEY env vars for adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--execute-actions-in-dry-run",
        action="store_true",
        help="Allow pause/rollback/dispatch/inspection actions in dry mode.",
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


def build_commander(args: argparse.Namespace) -> ManufacturingRootCauseCommander:
    spec = USE_CASE_INDEX["manufacturing_root_cause"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        line_telemetry = build_line_telemetry_adapter_from_env()
        maintenance = build_maintenance_history_adapter_from_env()
        actions = build_manufacturing_action_adapter_from_env()
    else:
        line_telemetry = InMemoryLineTelemetryAdapter(
            lines={
                "LINE-A12": {
                    "yield_rate": 0.79,
                    "vibration_risk": 0.88,
                    "thermal_risk": 0.82,
                    "fault_rate_per_hour": 3.6,
                },
                "LINE-C31": {
                    "yield_rate": 0.92,
                    "vibration_risk": 0.42,
                    "thermal_risk": 0.34,
                    "fault_rate_per_hour": 1.2,
                },
            }
        )
        maintenance = InMemoryMaintenanceHistoryAdapter(
            assets={
                "ASSET-R77": {
                    "recent_failures_30d": 4,
                    "overdue_pm_days": 37,
                    "firmware_change_recent": True,
                },
                "ASSET-P12": {
                    "recent_failures_30d": 1,
                    "overdue_pm_days": 8,
                    "firmware_change_recent": False,
                },
            }
        )
        actions = InMemoryManufacturingActionAdapter()

    policy = ManufacturingExecutionPolicy(
        execute_actions_in_dry_run=args.execute_actions_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "line_telemetry_adapter": line_telemetry,
        "maintenance_history_adapter": maintenance,
        "action_adapter": actions,
        "execution_policy": policy,
    }
    if args.audit_log:
        commander_kwargs["audit_logger"] = JSONLAuditLogger(Path(args.audit_log))

    return ManufacturingRootCauseCommander(**commander_kwargs)


def print_human(report: dict[str, object]) -> None:
    print(f"Batch ID: {report['batch_id']}")
    print(f"Mode: {report['mode']}")

    stats = report["stats"]
    assert isinstance(stats, dict)
    print(
        "Stats:",
        f"anomalies={stats['anomalies_total']}",
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
            f"- {row['anomaly_id']}: route={row['route']} priority={row['priority']} "
            f"risk={row['risk_score']:.2f} yield_loss={row['yield_loss']:.2f} "
            f"line={row['line_id']}"
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
