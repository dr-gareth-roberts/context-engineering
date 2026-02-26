from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from context_framework import (
    USE_CASE_INDEX,
    InMemoryFulfillmentActionAdapter,
    InMemoryLaneDelayAdapter,
    InMemorySupplierRiskAdapter,
    SupplyChainControlTowerCommander,
    SupplyChainExecutionPolicy,
    TriProviderPipeline,
)


class _FlakyLaneAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def lookup_lane(self, lane_id: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting lane-delay service")
        return {
            "lane_id": lane_id,
            "delay_hours": 22,
            "congestion_level": "high",
            "alternate_lane": f"{lane_id}-ALT",
        }


class _SleepyLaneAdapter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def lookup_lane(self, lane_id: str):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {
            "lane_id": lane_id,
            "delay_hours": 12,
            "congestion_level": "medium",
            "alternate_lane": f"{lane_id}-ALT",
        }


class SupplyChainRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["supply_chain_control_tower"]
        return TriProviderPipeline(spec)

    def test_extract_signals(self) -> None:
        rows = SupplyChainControlTowerCommander.extract_signals(
            "ORD-100 on LANE-SEA-LAX with SUP-ALPHA and ORD-101 on SZX->LAX with SUP-BETA"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].order_id, "ORD-100")
        self.assertEqual(rows[0].lane_id, "LANE-SEA-LAX")
        self.assertEqual(rows[0].supplier_id, "SUP-ALPHA")
        self.assertEqual(rows[1].lane_id, "SZX->LAX")

    def test_dry_mode_gates_actions_by_default(self) -> None:
        commander = SupplyChainControlTowerCommander(
            pipeline=self._pipeline(),
            lane_delay_adapter=InMemoryLaneDelayAdapter(
                lanes={"LANE-SEA-LAX": {"delay_hours": 20, "alternate_lane": "LANE-SEA-OAK-LAX"}}
            ),
            supplier_risk_adapter=InMemorySupplierRiskAdapter(
                suppliers={"SUP-ALPHA": {"risk_score": 0.2, "capacity_pct": 0.8}}
            ),
            fulfillment_action_adapter=InMemoryFulfillmentActionAdapter(),
            execution_policy=SupplyChainExecutionPolicy(execute_actions_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="ORD-100 on LANE-SEA-LAX from SUP-ALPHA delayed 20h",
            mode="dry",
        )

        self.assertGreaterEqual(len(report.actions), 1)
        self.assertTrue(all(row.status == "skipped" for row in report.actions))
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_actions(self) -> None:
        action_adapter = InMemoryFulfillmentActionAdapter()
        commander = SupplyChainControlTowerCommander(
            pipeline=self._pipeline(),
            lane_delay_adapter=InMemoryLaneDelayAdapter(
                lanes={"LANE-SEA-LAX": {"delay_hours": 25, "alternate_lane": "LANE-SEA-OAK-LAX"}}
            ),
            supplier_risk_adapter=InMemorySupplierRiskAdapter(
                suppliers={"SUP-ALPHA": {"risk_score": 0.2, "capacity_pct": 0.8}}
            ),
            fulfillment_action_adapter=action_adapter,
            execution_policy=SupplyChainExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = "ORD-100 on LANE-SEA-LAX from SUP-ALPHA delayed 25h"
        first = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})
        second = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})

        self.assertTrue(any(row.status == "executed" for row in first.actions))
        self.assertTrue(all(row.status == "skipped" for row in second.actions))
        self.assertEqual(len(action_adapter.reroutes), 1)

    def test_high_risk_supplier_routes_hold_review(self) -> None:
        commander = SupplyChainControlTowerCommander(
            pipeline=self._pipeline(),
            lane_delay_adapter=InMemoryLaneDelayAdapter(
                lanes={"LANE-SEA-LAX": {"delay_hours": 6, "alternate_lane": "LANE-SEA-OAK-LAX"}}
            ),
            supplier_risk_adapter=InMemorySupplierRiskAdapter(
                suppliers={"SUP-ALPHA": {"risk_score": 0.95, "capacity_pct": 0.8}}
            ),
            fulfillment_action_adapter=InMemoryFulfillmentActionAdapter(),
            execution_policy=SupplyChainExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="ORD-100 on LANE-SEA-LAX from SUP-ALPHA delayed 6h",
            mode="dry",
        )
        self.assertEqual(report.decisions[0].route, "hold_review")
        self.assertEqual(report.actions[0].operation, "hold_review")
        self.assertTrue(report.actions[0].success)

    def test_retry_recovers_from_transient_lane_failure(self) -> None:
        flaky_lane = _FlakyLaneAdapter()
        commander = SupplyChainControlTowerCommander(
            pipeline=self._pipeline(),
            lane_delay_adapter=flaky_lane,
            supplier_risk_adapter=InMemorySupplierRiskAdapter(
                suppliers={"SUP-ALPHA": {"risk_score": 0.2, "capacity_pct": 0.8}}
            ),
            fulfillment_action_adapter=InMemoryFulfillmentActionAdapter(),
            execution_policy=SupplyChainExecutionPolicy(execute_actions_in_dry_run=False),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="ORD-100 on LANE-SEA-LAX from SUP-ALPHA delayed 20h",
            mode="dry",
        )

        self.assertEqual(flaky_lane.calls, 2)
        lane_result = next(row for row in report.enrichments if row.integration == "lane_delay")
        self.assertTrue(lane_result.success)
        self.assertEqual(lane_result.retried, 1)
        self.assertEqual(lane_result.attempts, 2)

    def test_parallel_lane_enrichment_reduces_latency(self) -> None:
        sleepy_lane = _SleepyLaneAdapter(delay_seconds=0.08)
        commander = SupplyChainControlTowerCommander(
            pipeline=self._pipeline(),
            lane_delay_adapter=sleepy_lane,
            supplier_risk_adapter=InMemorySupplierRiskAdapter(),
            fulfillment_action_adapter=InMemoryFulfillmentActionAdapter(),
            execution_policy=SupplyChainExecutionPolicy(
                execute_actions_in_dry_run=False,
                max_parallel_tasks=6,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = " ".join(
            [
                "ORD-1001 on LANE-AAA-BBB",
                "ORD-1002 on LANE-BBB-CCC",
                "ORD-1003 on LANE-CCC-DDD",
                "ORD-1004 on LANE-DDD-EEE",
                "from SUP-ALPHA",
            ]
        )

        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        lane_calls = [row for row in report.enrichments if row.integration == "lane_delay"]
        self.assertEqual(len(lane_calls), 4)
        sequential = sleepy_lane.delay_seconds * sleepy_lane.calls
        self.assertLess(elapsed, sequential * 0.8)

    def test_runtime_script_executes_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "supply_chain_control_tower_runtime.py"
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
