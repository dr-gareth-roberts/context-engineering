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
    InMemoryFAERSAdapter,
    InMemoryLotTraceabilityAdapter,
    InMemorySafetyActionAdapter,
    JSONLAuditLogger,
    PharmacovigilanceCommander,
    PharmacovigilanceExecutionPolicy,
    TriProviderPipeline,
    USE_CASE_INDEX,
    build_faers_adapter_from_env,
    build_lot_traceability_adapter_from_env,
    build_safety_action_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "Safety intake: AE-5011 linked to LOT-A112 for DRUG-ZX1 with anaphylaxis and 47 reports, "
    "AE-5012 linked to LOT-B204 for DRUG-ZX1 with arrhythmia and 18 reports, and AE-5013 "
    "linked to LOT-C330 for DRUG-QP9 with rash and 6 reports."
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
        help="Use PV_*_BASE_URL and PV_*_API_KEY env vars for adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--execute-actions-in-dry-run",
        action="store_true",
        help="Allow hold-lot/review/regulatory-alert calls in dry mode.",
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


def build_commander(args: argparse.Namespace) -> PharmacovigilanceCommander:
    spec = USE_CASE_INDEX["pharmacovigilance_events"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        faers = build_faers_adapter_from_env()
        lot = build_lot_traceability_adapter_from_env()
        actions = build_safety_action_adapter_from_env()
    else:
        faers = InMemoryFAERSAdapter(
            signals={
                "DRUG-ZX1|anaphylaxis": {
                    "serious_event_rate": 0.92,
                    "recent_case_count": 47,
                    "fatal_case_count": 2,
                },
                "DRUG-ZX1|arrhythmia": {
                    "serious_event_rate": 0.64,
                    "recent_case_count": 18,
                    "fatal_case_count": 0,
                },
                "DRUG-QP9|rash": {
                    "serious_event_rate": 0.18,
                    "recent_case_count": 6,
                    "fatal_case_count": 0,
                },
            }
        )
        lot = InMemoryLotTraceabilityAdapter(
            lots={
                "LOT-A112": {
                    "deviation_rate": 0.88,
                    "units_shipped": 62000,
                    "distribution_regions": ["US", "EU"],
                },
                "LOT-B204": {
                    "deviation_rate": 0.43,
                    "units_shipped": 24000,
                    "distribution_regions": ["US"],
                },
                "LOT-C330": {
                    "deviation_rate": 0.11,
                    "units_shipped": 11000,
                    "distribution_regions": ["US"],
                },
            }
        )
        actions = InMemorySafetyActionAdapter()

    policy = PharmacovigilanceExecutionPolicy(
        execute_actions_in_dry_run=args.execute_actions_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "faers_adapter": faers,
        "lot_traceability_adapter": lot,
        "safety_action_adapter": actions,
        "execution_policy": policy,
    }
    if args.audit_log:
        commander_kwargs["audit_logger"] = JSONLAuditLogger(Path(args.audit_log))

    return PharmacovigilanceCommander(**commander_kwargs)


def print_human(report: dict[str, object]) -> None:
    print(f"Batch ID: {report['batch_id']}")
    print(f"Mode: {report['mode']}")

    stats = report["stats"]
    assert isinstance(stats, dict)
    print(
        "Stats:",
        f"signals={stats['signals_total']}",
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
            f"- {row['signal_id']}: route={row['route']} priority={row['priority']} "
            f"risk={row['risk_score']:.2f} serious={row['serious_event_rate']:.2f}"
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
