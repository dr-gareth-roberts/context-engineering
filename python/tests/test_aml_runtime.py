from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from context_framework import (
    USE_CASE_INDEX,
    AMLExecutionPolicy,
    AMLKYCFincrimeCommander,
    InMemoryCaseActionAdapter,
    InMemorySanctionsScreenAdapter,
    InMemoryTransactionGraphAdapter,
    TriProviderPipeline,
)


class _FlakyGraphAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def lookup_account_graph(self, account_id: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting transaction graph")
        return {
            "account_id": account_id,
            "anomaly_score": 0.82,
            "cross_border_count": 4,
            "high_risk_jurisdictions": ["IR"],
        }


class _SleepyGraphAdapter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def lookup_account_graph(self, account_id: str):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {
            "account_id": account_id,
            "anomaly_score": 0.52,
            "cross_border_count": 2,
            "high_risk_jurisdictions": [],
        }


class AMLRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["aml_kyc_fincrime"]
        return TriProviderPipeline(spec)

    def test_extract_signals(self) -> None:
        rows = AMLKYCFincrimeCommander.extract_signals(
            "CASE-9001 for ACC-1001 and ENT-ALPHA with TX-ABCD and $125,500"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].case_id, "CASE-9001")
        self.assertEqual(rows[0].account_id, "ACC-1001")
        self.assertEqual(rows[0].entity_id, "ENT-ALPHA")
        self.assertEqual(rows[0].transaction_id, "TX-ABCD")
        self.assertEqual(rows[0].observed_amount, 125500.0)

    def test_dry_mode_gates_actions_by_default(self) -> None:
        commander = AMLKYCFincrimeCommander(
            pipeline=self._pipeline(),
            transaction_graph_adapter=InMemoryTransactionGraphAdapter(
                accounts={"ACC-1001": {"anomaly_score": 0.82}}
            ),
            sanctions_screen_adapter=InMemorySanctionsScreenAdapter(
                entities={"ENT-ALPHA": {"match_score": 0.95, "watchlist_hit": True}}
            ),
            case_action_adapter=InMemoryCaseActionAdapter(),
            execution_policy=AMLExecutionPolicy(execute_actions_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="CASE-9001 for ACC-1001 and ENT-ALPHA with suspicious movement",
            mode="dry",
        )
        self.assertGreaterEqual(len(report.actions), 1)
        self.assertTrue(all(row.status == "skipped" for row in report.actions))
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_actions(self) -> None:
        action_adapter = InMemoryCaseActionAdapter()
        commander = AMLKYCFincrimeCommander(
            pipeline=self._pipeline(),
            transaction_graph_adapter=InMemoryTransactionGraphAdapter(
                accounts={"ACC-1001": {"anomaly_score": 0.9}}
            ),
            sanctions_screen_adapter=InMemorySanctionsScreenAdapter(
                entities={"ENT-ALPHA": {"match_score": 0.96, "watchlist_hit": True}}
            ),
            case_action_adapter=action_adapter,
            execution_policy=AMLExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = "CASE-9001 for ACC-1001 and ENT-ALPHA"
        first = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})
        second = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})

        self.assertTrue(any(row.status == "executed" for row in first.actions))
        self.assertTrue(all(row.status == "skipped" for row in second.actions))
        self.assertEqual(len(action_adapter.frozen_accounts), 1)
        self.assertEqual(len(action_adapter.sar_cases), 1)

    def test_high_sanctions_routes_freeze_and_sar(self) -> None:
        commander = AMLKYCFincrimeCommander(
            pipeline=self._pipeline(),
            transaction_graph_adapter=InMemoryTransactionGraphAdapter(
                accounts={"ACC-1001": {"anomaly_score": 0.42}}
            ),
            sanctions_screen_adapter=InMemorySanctionsScreenAdapter(
                entities={"ENT-ALPHA": {"match_score": 0.98, "watchlist_hit": True}}
            ),
            case_action_adapter=InMemoryCaseActionAdapter(),
            execution_policy=AMLExecutionPolicy(execute_actions_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="CASE-9001 for ACC-1001 and ENT-ALPHA",
            mode="dry",
        )

        self.assertEqual(report.decisions[0].route, "freeze_and_sar")
        ops = {row.operation for row in report.actions if row.status == "executed"}
        self.assertIn("freeze_account", ops)
        self.assertIn("create_sar", ops)

    def test_retry_recovers_from_transient_graph_failure(self) -> None:
        flaky_graph = _FlakyGraphAdapter()
        commander = AMLKYCFincrimeCommander(
            pipeline=self._pipeline(),
            transaction_graph_adapter=flaky_graph,
            sanctions_screen_adapter=InMemorySanctionsScreenAdapter(
                entities={"ENT-ALPHA": {"match_score": 0.2, "watchlist_hit": False}}
            ),
            case_action_adapter=InMemoryCaseActionAdapter(),
            execution_policy=AMLExecutionPolicy(execute_actions_in_dry_run=False),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="CASE-9001 for ACC-1001 and ENT-ALPHA",
            mode="dry",
        )

        self.assertEqual(flaky_graph.calls, 2)
        graph_result = next(
            row for row in report.enrichments if row.integration == "transaction_graph"
        )
        self.assertTrue(graph_result.success)
        self.assertEqual(graph_result.retried, 1)
        self.assertEqual(graph_result.attempts, 2)

    def test_parallel_graph_enrichment_reduces_latency(self) -> None:
        sleepy_graph = _SleepyGraphAdapter(delay_seconds=0.08)
        commander = AMLKYCFincrimeCommander(
            pipeline=self._pipeline(),
            transaction_graph_adapter=sleepy_graph,
            sanctions_screen_adapter=InMemorySanctionsScreenAdapter(),
            case_action_adapter=InMemoryCaseActionAdapter(),
            execution_policy=AMLExecutionPolicy(
                execute_actions_in_dry_run=False,
                max_parallel_tasks=6,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "CASE-1001 ACC-1001 ENT-A CASE-1002 ACC-1002 ENT-B "
            "CASE-1003 ACC-1003 ENT-C CASE-1004 ACC-1004 ENT-D"
        )
        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        graph_rows = [row for row in report.enrichments if row.integration == "transaction_graph"]
        self.assertEqual(len(graph_rows), 4)
        sequential = sleepy_graph.delay_seconds * sleepy_graph.calls
        self.assertLess(elapsed, sequential * 0.8)

    def test_runtime_script_executes_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "aml_kyc_fincrime_runtime.py"
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
