from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

from context_framework import (
    USE_CASE_INDEX,
    CatastropheClaimsCommander,
    ClaimsExecutionPolicy,
    InMemoryFraudAdapter,
    InMemoryIdempotencyStore,
    InMemoryPayoutAdapter,
    InMemoryPolicyAdapter,
    TriProviderPipeline,
)


class _FlakyFraudAdapter:
    def __init__(self) -> None:
        self.calls = 0

    def evaluate_claim(self, claim_id: str, *, claimant_id: str | None = None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting fraud service")
        return {
            "claim_id": claim_id,
            "claimant_id": claimant_id,
            "fraud_score": 0.1,
            "signals": [],
        }


class _SleepyPolicyAdapter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def lookup_claim(self, claim_id: str):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {
            "claim_id": claim_id,
            "policy_status": "active",
            "coverage_limit_cents": 1_000_000,
        }


class ClaimsRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["catastrophe_claims_pipeline"]
        return TriProviderPipeline(spec)

    def test_extract_indicators(self) -> None:
        indicators = CatastropheClaimsCommander.extract_indicators(
            "CLM-1001 CLM-1002 claimant CLMT-7001 policy POL-99 in FL-33101"
        )
        self.assertEqual(indicators.claim_ids, ("CLM-1001", "CLM-1002"))
        self.assertIn("CLMT-7001", indicators.claimant_ids)
        self.assertIn("POL-99", indicators.policy_ids)
        self.assertIn("FL-33101", indicators.regions)

    def test_dry_mode_gates_financial_actions_by_default(self) -> None:
        commander = CatastropheClaimsCommander(
            pipeline=self._pipeline(),
            policy_adapter=InMemoryPolicyAdapter(
                claims={"CLM-1001": {"policy_status": "active", "coverage_limit_cents": 2_000_000}}
            ),
            fraud_adapter=InMemoryFraudAdapter(scores={"CLM-1001": 0.08}),
            payout_adapter=InMemoryPayoutAdapter(),
            execution_policy=ClaimsExecutionPolicy(auto_execute_payouts_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="Hurricane severe structural loss for CLM-1001 and claimant CLMT-7001",
            mode="dry",
        )

        self.assertEqual(report.stats.payout_total, 0)
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_payout_actions(self) -> None:
        payout = InMemoryPayoutAdapter()
        commander = CatastropheClaimsCommander(
            pipeline=self._pipeline(),
            policy_adapter=InMemoryPolicyAdapter(
                claims={"CLM-1001": {"policy_status": "active", "coverage_limit_cents": 2_000_000}}
            ),
            fraud_adapter=InMemoryFraudAdapter(scores={"CLM-1001": 0.05}),
            payout_adapter=payout,
            idempotency_store=InMemoryIdempotencyStore(default_ttl_seconds=60),
            execution_policy=ClaimsExecutionPolicy(auto_execute_payouts_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = "Hurricane critical total loss for CLM-1001 and claimant CLMT-7001"
        first = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})
        second = commander.run(scenario=scenario, mode="dry", metadata={"batch_id": "batch-fixed"})

        self.assertGreaterEqual(len(first.payout_actions), 1)
        self.assertTrue(all(row.status == "executed" for row in first.payout_actions))
        self.assertTrue(all(row.status == "skipped" for row in second.payout_actions))
        self.assertEqual(second.stats.skipped_total, len(second.payout_actions))
        self.assertEqual(len(payout.actions), len(first.payout_actions))

    def test_high_fraud_routes_to_hold(self) -> None:
        commander = CatastropheClaimsCommander(
            pipeline=self._pipeline(),
            policy_adapter=InMemoryPolicyAdapter(
                claims={"CLM-9001": {"policy_status": "active", "coverage_limit_cents": 2_000_000}}
            ),
            fraud_adapter=InMemoryFraudAdapter(scores={"CLM-9001": 0.96}),
            payout_adapter=InMemoryPayoutAdapter(),
            execution_policy=ClaimsExecutionPolicy(auto_execute_payouts_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="Cat event duplicate filing and geolocation mismatch for CLM-9001",
            mode="dry",
        )

        self.assertEqual(report.assessments[0].recommended_action, "hold")
        self.assertEqual(len(report.payout_actions), 1)
        self.assertEqual(report.payout_actions[0].tool, "place_hold")
        self.assertTrue(report.payout_actions[0].success)

    def test_retry_recovers_from_transient_fraud_failure(self) -> None:
        flaky = _FlakyFraudAdapter()
        commander = CatastropheClaimsCommander(
            pipeline=self._pipeline(),
            policy_adapter=InMemoryPolicyAdapter(
                claims={"CLM-7007": {"policy_status": "active", "coverage_limit_cents": 2_000_000}}
            ),
            fraud_adapter=flaky,
            payout_adapter=InMemoryPayoutAdapter(),
            execution_policy=ClaimsExecutionPolicy(auto_execute_payouts_in_dry_run=False),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario="Hurricane severe roof collapse for CLM-7007",
            mode="dry",
        )

        self.assertEqual(flaky.calls, 2)
        self.assertTrue(report.fraud_results[0].success)
        self.assertEqual(report.fraud_results[0].retried, 1)
        self.assertEqual(report.fraud_results[0].attempts, 2)

    def test_parallel_policy_execution_reduces_latency(self) -> None:
        sleepy = _SleepyPolicyAdapter(delay_seconds=0.08)
        commander = CatastropheClaimsCommander(
            pipeline=self._pipeline(),
            policy_adapter=sleepy,
            fraud_adapter=InMemoryFraudAdapter(),
            payout_adapter=InMemoryPayoutAdapter(),
            execution_policy=ClaimsExecutionPolicy(
                auto_execute_payouts_in_dry_run=False,
                max_parallel_tasks=6,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = " ".join([f"CLM-{n}" for n in (1001, 1002, 1003, 1004)])
        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        self.assertEqual(len(report.policy_results), 4)
        sequential = sleepy.delay_seconds * sleepy.calls
        self.assertLess(elapsed, sequential * 0.8)

    def test_catastrophe_runtime_script_executes_in_dry_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "examples" / "catastrophe_claims_runtime.py"
        result = subprocess.run(
            [sys.executable, str(script), "--mode", "dry", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertIn("batch_id", payload)
        self.assertIn("assessments", payload)
        self.assertEqual(payload["mode"], "dry")


if __name__ == "__main__":
    unittest.main()
