from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from context_framework import (
    USE_CASE_INDEX,
    InMemoryDependencyGraphAdapter,
    InMemoryMigrationActionAdapter,
    InMemorySystemInventoryAdapter,
    LegacyMigrationExecutionPolicy,
    LegacyModernMigrationCommander,
    TriProviderPipeline,
)


class _FlakySystemInventoryAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def lookup_system(self, system_id: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting system-inventory service")
        return {
            "system_id": system_id,
            "tech_debt_score": 0.90,
            "modernization_blocker_score": 0.84,
            "criticality": 0.88,
            "change_failure_rate": 0.76,
        }


class _SleepySystemInventoryAdapter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def lookup_system(self, system_id: str):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {
            "system_id": system_id,
            "tech_debt_score": 0.58,
            "modernization_blocker_score": 0.52,
            "criticality": 0.60,
            "change_failure_rate": 0.48,
        }


class LegacyModernMigrationRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["legacy_modern_migration"]
        return TriProviderPipeline(spec)

    def test_extract_signals(self) -> None:
        rows = LegacyModernMigrationCommander.extract_signals(
            "APP-CORE-LEGACY COMPONENT-BILLING TEAM-PLATFORM eol runtime mission-critical 12 years 140 dependencies 36 hours"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].system_id, "APP-CORE-LEGACY")
        self.assertEqual(rows[0].service_id, "COMPONENT-BILLING")
        self.assertEqual(rows[0].owner_id, "TEAM-PLATFORM")
        self.assertEqual(rows[0].observed_age_years, 12)
        self.assertEqual(rows[0].observed_dependency_count, 140)
        self.assertEqual(rows[0].observed_recent_outage_hours, 36)
        self.assertTrue(rows[0].unsupported_runtime_indicator)
        self.assertTrue(rows[0].mission_critical_indicator)

    def test_extract_signals_preserves_event_alignment(self) -> None:
        rows = LegacyModernMigrationCommander.extract_signals(
            "APP-CORE-LEGACY COMPONENT-BILLING TEAM-PLATFORM 12 years 140 dependencies 36 hours. "
            "SERVICE-ORDER-HUB COMPONENT-ORDER TEAM-COMMERCE 6 years 38 dependencies 4 hours."
        )
        by_system = {row.system_id: row for row in rows}
        self.assertEqual(by_system["APP-CORE-LEGACY"].service_id, "COMPONENT-BILLING")
        self.assertEqual(by_system["APP-CORE-LEGACY"].owner_id, "TEAM-PLATFORM")
        self.assertEqual(by_system["SERVICE-ORDER-HUB"].service_id, "COMPONENT-ORDER")
        self.assertEqual(by_system["SERVICE-ORDER-HUB"].owner_id, "TEAM-COMMERCE")
        self.assertEqual(by_system["SERVICE-ORDER-HUB"].observed_age_years, 6)

    def test_extract_signals_avoids_generic_phrase_false_positive(self) -> None:
        rows = LegacyModernMigrationCommander.extract_signals(
            "Modernization update for two systems: APP-CORE-LEGACY and SERVICE-ORDER-HUB."
        )
        ids = [row.system_id for row in rows]
        self.assertEqual(ids, ["APP-CORE-LEGACY", "SERVICE-ORDER-HUB"])

    def test_dry_mode_gates_actions_by_default(self) -> None:
        commander = LegacyModernMigrationCommander(
            pipeline=self._pipeline(),
            system_inventory_adapter=InMemorySystemInventoryAdapter(
                systems={
                    "APP-CORE-LEGACY": {
                        "tech_debt_score": 0.92,
                        "modernization_blocker_score": 0.86,
                        "criticality": 0.90,
                        "change_failure_rate": 0.78,
                    }
                }
            ),
            dependency_graph_adapter=InMemoryDependencyGraphAdapter(
                systems={
                    "APP-CORE-LEGACY": {
                        "dependency_count": 128,
                        "coupling_score": 0.84,
                        "blast_radius": 0.82,
                        "target_platform": "PLATFORM-K8S-PRIME",
                        "parallel_run_readiness": 0.38,
                    }
                }
            ),
            action_adapter=InMemoryMigrationActionAdapter(),
            execution_policy=LegacyMigrationExecutionPolicy(execute_actions_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="APP-CORE-LEGACY COMPONENT-BILLING TEAM-PLATFORM eol runtime mission-critical 12 years 140 dependencies 36 hours",
            mode="dry",
        )

        self.assertGreaterEqual(len(report.actions), 1)
        self.assertTrue(all(row.status == "skipped" for row in report.actions))
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_actions(self) -> None:
        action_adapter = InMemoryMigrationActionAdapter()
        commander = LegacyModernMigrationCommander(
            pipeline=self._pipeline(),
            system_inventory_adapter=InMemorySystemInventoryAdapter(
                systems={
                    "APP-CORE-LEGACY": {
                        "tech_debt_score": 0.94,
                        "modernization_blocker_score": 0.88,
                        "criticality": 0.92,
                        "change_failure_rate": 0.80,
                    }
                }
            ),
            dependency_graph_adapter=InMemoryDependencyGraphAdapter(
                systems={
                    "APP-CORE-LEGACY": {
                        "dependency_count": 142,
                        "coupling_score": 0.86,
                        "blast_radius": 0.84,
                        "target_platform": "PLATFORM-K8S-PRIME",
                        "parallel_run_readiness": 0.34,
                    }
                }
            ),
            action_adapter=action_adapter,
            execution_policy=LegacyMigrationExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = "APP-CORE-LEGACY COMPONENT-BILLING TEAM-PLATFORM eol runtime mission-critical 12 years 140 dependencies 36 hours"
        first = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})
        second = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})

        self.assertTrue(any(row.status == "executed" for row in first.actions))
        self.assertTrue(all(row.status == "skipped" for row in second.actions))
        self.assertEqual(len(action_adapter.modernization_programs), 1)
        self.assertEqual(len(action_adapter.migration_waves), 1)
        self.assertEqual(len(action_adapter.parallel_runs), 1)
        self.assertEqual(len(action_adapter.rollback_plans), 1)

    def test_high_risk_routes_immediate_replatform(self) -> None:
        commander = LegacyModernMigrationCommander(
            pipeline=self._pipeline(),
            system_inventory_adapter=InMemorySystemInventoryAdapter(
                systems={
                    "APP-CORE-LEGACY": {
                        "tech_debt_score": 0.95,
                        "modernization_blocker_score": 0.90,
                        "criticality": 0.94,
                        "change_failure_rate": 0.82,
                    }
                }
            ),
            dependency_graph_adapter=InMemoryDependencyGraphAdapter(
                systems={
                    "APP-CORE-LEGACY": {
                        "dependency_count": 150,
                        "coupling_score": 0.88,
                        "blast_radius": 0.86,
                        "target_platform": "PLATFORM-K8S-PRIME",
                        "parallel_run_readiness": 0.30,
                    }
                }
            ),
            action_adapter=InMemoryMigrationActionAdapter(),
            execution_policy=LegacyMigrationExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="APP-CORE-LEGACY COMPONENT-BILLING TEAM-PLATFORM eol runtime mission-critical 12 years 150 dependencies 36 hours",
            mode="dry",
        )

        self.assertEqual(report.decisions[0].route, "immediate_replatform_program")
        ops = {row.operation for row in report.actions if row.status == "executed"}
        self.assertIn("open_modernization_program", ops)
        self.assertIn("create_migration_wave", ops)
        self.assertIn("schedule_parallel_run", ops)
        self.assertIn("register_rollback_plan", ops)
        self.assertIn("assign_transformation_owner", ops)

    def test_retry_recovers_from_transient_system_inventory_failure(self) -> None:
        flaky = _FlakySystemInventoryAdapter()
        commander = LegacyModernMigrationCommander(
            pipeline=self._pipeline(),
            system_inventory_adapter=flaky,
            dependency_graph_adapter=InMemoryDependencyGraphAdapter(),
            action_adapter=InMemoryMigrationActionAdapter(),
            execution_policy=LegacyMigrationExecutionPolicy(execute_actions_in_dry_run=False),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="APP-CORE-LEGACY COMPONENT-BILLING TEAM-PLATFORM 8 years 64 dependencies 8 hours",
            mode="dry",
        )

        self.assertEqual(flaky.calls, 2)
        row = next(r for r in report.enrichments if r.integration == "system_inventory")
        self.assertTrue(row.success)
        self.assertEqual(row.retried, 1)
        self.assertEqual(row.attempts, 2)

    def test_parallel_system_inventory_enrichment_reduces_latency(self) -> None:
        sleepy = _SleepySystemInventoryAdapter(delay_seconds=0.08)
        commander = LegacyModernMigrationCommander(
            pipeline=self._pipeline(),
            system_inventory_adapter=sleepy,
            dependency_graph_adapter=InMemoryDependencyGraphAdapter(),
            action_adapter=InMemoryMigrationActionAdapter(),
            execution_policy=LegacyMigrationExecutionPolicy(
                execute_actions_in_dry_run=False,
                max_parallel_tasks=8,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "APP-A-1001 COMPONENT-A TEAM-ONE 8 years 40 dependencies 4 hours "
            "APP-B-1002 COMPONENT-B TEAM-TWO 9 years 42 dependencies 5 hours "
            "APP-C-1003 COMPONENT-C TEAM-THREE 10 years 46 dependencies 6 hours "
            "APP-D-1004 COMPONENT-D TEAM-FOUR 11 years 52 dependencies 7 hours"
        )

        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        inventory_rows = [
            row for row in report.enrichments if row.integration == "system_inventory"
        ]
        self.assertEqual(len(inventory_rows), 4)
        sequential = sleepy.delay_seconds * sleepy.calls
        self.assertLess(elapsed, sequential * 0.9)

    def test_runtime_script_executes_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "legacy_modern_migration_runtime.py"
        result = subprocess.run(
            [sys.executable, str(script), "--mode", "dry", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertIn("batch_id", payload)
        self.assertIn("decisions", payload)
        self.assertEqual(payload["mode"], "dry")


if __name__ == "__main__":
    unittest.main()
