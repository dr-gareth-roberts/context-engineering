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
    ClinicalExecutionPolicy,
    ClinicalOperationsCommander,
    InMemoryAcuityIntelAdapter,
    InMemoryBedCapacityAdapter,
    InMemoryClinicalActionAdapter,
    JSONLAuditLogger,
    TriProviderPipeline,
    USE_CASE_INDEX,
    build_acuity_intel_adapter_from_env,
    build_bed_capacity_adapter_from_env,
    build_clinical_action_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "Clinical update: UNIT-ICU-01 TEAM-CRITICAL LINE-NEURO at 96% occupancy with 11 hours boarding and "
    "34 patients waiting, high acuity, diversion, sepsis alerts. "
    "UNIT-MED-03 TEAM-MEDICINE LINE-GENERAL at 84% occupancy with 4 hours boarding and 16 patients waiting."
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
        help="Use CLINICAL_* env vars for adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--execute-actions-in-dry-run",
        action="store_true",
        help="Allow clinical actions in dry mode.",
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


def build_commander(args: argparse.Namespace) -> ClinicalOperationsCommander:
    spec = USE_CASE_INDEX["clinical_operations_optimizer"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        bed_capacity = build_bed_capacity_adapter_from_env()
        acuity_intel = build_acuity_intel_adapter_from_env()
        actions = build_clinical_action_adapter_from_env()
    else:
        bed_capacity = InMemoryBedCapacityAdapter(
            units={
                "UNIT-ICU-01": {
                    "occupancy_pct": 96,
                    "staffed_bed_ratio": 0.68,
                    "discharge_backlog": 46,
                    "diversion_risk": 0.89,
                },
                "UNIT-MED-03": {
                    "occupancy_pct": 84,
                    "staffed_bed_ratio": 0.80,
                    "discharge_backlog": 22,
                    "diversion_risk": 0.36,
                },
            }
        )
        acuity_intel = InMemoryAcuityIntelAdapter(
            units={
                "UNIT-ICU-01": {
                    "high_acuity_ratio": 0.92,
                    "deteriorating_patients": 14,
                    "transfer_blockers": 0.83,
                    "surge_probability": 0.90,
                },
                "UNIT-MED-03": {
                    "high_acuity_ratio": 0.44,
                    "deteriorating_patients": 5,
                    "transfer_blockers": 0.38,
                    "surge_probability": 0.42,
                },
            }
        )
        actions = InMemoryClinicalActionAdapter()

    policy = ClinicalExecutionPolicy(
        execute_actions_in_dry_run=args.execute_actions_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "bed_capacity_adapter": bed_capacity,
        "acuity_intel_adapter": acuity_intel,
        "action_adapter": actions,
        "execution_policy": policy,
    }
    if args.audit_log:
        commander_kwargs["audit_logger"] = JSONLAuditLogger(Path(args.audit_log))

    return ClinicalOperationsCommander(**commander_kwargs)


def print_human(report: dict[str, object]) -> None:
    print(f"Batch ID: {report['batch_id']}")
    print(f"Mode: {report['mode']}")

    stats = report["stats"]
    assert isinstance(stats, dict)
    print(
        "Stats:",
        f"units={stats['units_total']}",
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
            f"- {row['unit_id']}: route={row['route']} priority={row['priority']} "
            f"risk={row['risk_score']:.2f} occupancy={row['occupancy_pct']}% "
            f"waiting={row['waiting_patients']}"
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
