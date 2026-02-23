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
    InMemoryDependencyGraphAdapter,
    InMemoryMigrationActionAdapter,
    InMemorySystemInventoryAdapter,
    JSONLAuditLogger,
    LegacyMigrationExecutionPolicy,
    LegacyModernMigrationCommander,
    TriProviderPipeline,
    USE_CASE_INDEX,
    build_dependency_graph_adapter_from_env,
    build_migration_action_adapter_from_env,
    build_system_inventory_adapter_from_env,
)

DEFAULT_SCENARIO = (
    "Modernization intake: APP-CORE-LEGACY linked to COMPONENT-BILLING owned by TEAM-PLATFORM is "
    "12 years old with 140 dependencies and 36 hours outage, eol runtime, mission-critical. "
    "SERVICE-ORDER-HUB linked to COMPONENT-ORDER owned by TEAM-COMMERCE is 6 years old with "
    "38 dependencies and 4 hours outage."
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
        help="Use MIGRATION_* env vars for adapters.",
    )
    parser.add_argument(
        "--audit-log",
        default="",
        help="Optional JSONL audit output path.",
    )
    parser.add_argument(
        "--execute-actions-in-dry-run",
        action="store_true",
        help="Allow migration action calls in dry mode.",
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


def build_commander(args: argparse.Namespace) -> LegacyModernMigrationCommander:
    spec = USE_CASE_INDEX["legacy_modern_migration"]
    pipeline = TriProviderPipeline(spec)

    if args.use_http_adapters:
        system_inventory = build_system_inventory_adapter_from_env()
        dependency_graph = build_dependency_graph_adapter_from_env()
        actions = build_migration_action_adapter_from_env()
    else:
        system_inventory = InMemorySystemInventoryAdapter(
            systems={
                "APP-CORE-LEGACY": {
                    "tech_debt_score": 0.94,
                    "modernization_blocker_score": 0.86,
                    "criticality": 0.92,
                    "change_failure_rate": 0.78,
                },
                "SERVICE-ORDER-HUB": {
                    "tech_debt_score": 0.58,
                    "modernization_blocker_score": 0.48,
                    "criticality": 0.66,
                    "change_failure_rate": 0.42,
                },
            }
        )
        dependency_graph = InMemoryDependencyGraphAdapter(
            systems={
                "APP-CORE-LEGACY": {
                    "dependency_count": 140,
                    "coupling_score": 0.88,
                    "blast_radius": 0.84,
                    "target_platform": "PLATFORM-K8S-PRIME",
                    "parallel_run_readiness": 0.40,
                },
                "SERVICE-ORDER-HUB": {
                    "dependency_count": 38,
                    "coupling_score": 0.52,
                    "blast_radius": 0.46,
                    "target_platform": "PLATFORM-K8S-01",
                    "parallel_run_readiness": 0.70,
                },
            }
        )
        actions = InMemoryMigrationActionAdapter()

    policy = LegacyMigrationExecutionPolicy(
        execute_actions_in_dry_run=args.execute_actions_in_dry_run,
        max_parallel_tasks=max(1, args.max_parallel),
    )

    commander_kwargs = {
        "pipeline": pipeline,
        "system_inventory_adapter": system_inventory,
        "dependency_graph_adapter": dependency_graph,
        "action_adapter": actions,
        "execution_policy": policy,
    }
    if args.audit_log:
        commander_kwargs["audit_logger"] = JSONLAuditLogger(Path(args.audit_log))

    return LegacyModernMigrationCommander(**commander_kwargs)


def print_human(report: dict[str, object]) -> None:
    print(f"Batch ID: {report['batch_id']}")
    print(f"Mode: {report['mode']}")

    stats = report["stats"]
    assert isinstance(stats, dict)
    print(
        "Stats:",
        f"systems={stats['systems_total']}",
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
            f"- {row['system_id']}: route={row['route']} priority={row['priority']} "
            f"risk={row['risk_score']:.2f} deps={row['dependency_count']} "
            f"age_years={row['age_years']}"
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
