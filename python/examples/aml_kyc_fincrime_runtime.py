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
    AMLExecutionPolicy,
    AMLKYCFincrimeCommander,
    InMemoryCaseActionAdapter,
    InMemorySanctionsScreenAdapter,
    InMemoryTransactionGraphAdapter,
    JSONLAuditLogger,
    TriProviderPipeline,
    USE_CASE_INDEX,
    build_case_action_adapter_from_env,
    build_sanctions_screen_adapter_from_env,
    build_transaction_graph_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "AML alert stream: CASE-8801 for ACC-1001 linked to ENT-ALPHA with TX-9AA77 "
    "shows cross-border hops and $245,000 rapid movement. CASE-8802 for ACC-1002 "
    "linked to ENT-BETA shows repeated structuring under reporting thresholds."
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
        help="Use AML_*_BASE_URL and AML_*_API_KEY env vars for adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--execute-actions-in-dry-run",
        action="store_true",
        help="Allow freeze/SAR/EDD action calls in dry mode.",
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


def build_commander(args: argparse.Namespace) -> AMLKYCFincrimeCommander:
    spec = USE_CASE_INDEX["aml_kyc_fincrime"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        graph = build_transaction_graph_adapter_from_env()
        sanctions = build_sanctions_screen_adapter_from_env()
        actions = build_case_action_adapter_from_env()
    else:
        graph = InMemoryTransactionGraphAdapter(
            accounts={
                "ACC-1001": {
                    "anomaly_score": 0.86,
                    "cross_border_count": 7,
                    "high_risk_jurisdictions": ["IR", "KP"],
                },
                "ACC-1002": {
                    "anomaly_score": 0.58,
                    "cross_border_count": 2,
                    "high_risk_jurisdictions": [],
                },
                "ACC-1003": {
                    "anomaly_score": 0.21,
                    "cross_border_count": 1,
                    "high_risk_jurisdictions": [],
                },
            }
        )
        sanctions = InMemorySanctionsScreenAdapter(
            entities={
                "ENT-ALPHA": {"match_score": 0.93, "watchlist_hit": True},
                "ENT-BETA": {"match_score": 0.18, "watchlist_hit": False},
                "ENT-GAMMA": {"match_score": 0.06, "watchlist_hit": False},
            }
        )
        actions = InMemoryCaseActionAdapter()

    policy = AMLExecutionPolicy(
        execute_actions_in_dry_run=args.execute_actions_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "transaction_graph_adapter": graph,
        "sanctions_screen_adapter": sanctions,
        "case_action_adapter": actions,
        "execution_policy": policy,
    }
    if args.audit_log:
        commander_kwargs["audit_logger"] = JSONLAuditLogger(Path(args.audit_log))

    return AMLKYCFincrimeCommander(**commander_kwargs)


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
            f"- {row['case_id']}: route={row['route']} priority={row['priority']} "
            f"sanctions={row['sanctions_match_score']:.2f} anomaly={row['anomaly_score']:.2f}"
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
