from __future__ import annotations

import time
import unittest

from context_framework import (
    ExecutionPolicy,
    InMemoryEDRAdapter,
    InMemoryIAMAdapter,
    InMemoryIdempotencyStore,
    InMemorySIEMAdapter,
    SOCIncidentCommander,
    TriProviderPipeline,
    USE_CASE_INDEX,
)


class _SleepySIEM:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self.calls = 0

    def query(self, query: str, *, limit: int = 100):
        self.calls += 1
        time.sleep(self.delay_seconds)
        return {"query": query, "limit": limit, "events": []}


class _FlakyEDR:
    def __init__(self) -> None:
        self.calls = 0

    def isolate_host(self, hostname: str, *, reason: str):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("timeout contacting endpoint service")
        return {"hostname": hostname, "reason": reason, "isolated": True}


class SOCRuntimeTests(unittest.TestCase):
    def _pipeline(self) -> TriProviderPipeline:
        spec = USE_CASE_INDEX["soc_incident_commander"]
        return TriProviderPipeline(spec)

    def test_extract_indicators(self) -> None:
        indicators = SOCIncidentCommander.extract_indicators(
            "user_admin accessed host finance-01.prod.corp from 198.51.100.9 and sent email to sec@corp.example"
        )
        self.assertIn("198.51.100.9", indicators.ips)
        self.assertIn("user_admin", indicators.users)
        self.assertIn("finance-01.prod.corp", indicators.hosts)
        self.assertIn("sec@corp.example", indicators.emails)

    def test_dry_mode_gates_containment_by_default(self) -> None:
        commander = SOCIncidentCommander(
            pipeline=self._pipeline(),
            siem=InMemorySIEMAdapter(events=[]),
            edr=InMemoryEDRAdapter(),
            iam=InMemoryIAMAdapter(),
            execution_policy=ExecutionPolicy(execute_containment_in_dry_run=False),
            retry_backoff_seconds=0.0,
        )
        report = commander.run(
            scenario=(
                "Critical compromise detected for user_admin on host finance-01.prod.corp "
                "with egress to 198.51.100.9"
            ),
            mode="dry",
        )

        self.assertTrue(report.high_risk)
        self.assertEqual(len(report.edr_actions), 0)
        self.assertEqual(len(report.iam_actions), 0)
        self.assertIn("dry mode", " ".join(report.warnings).lower())

    def test_idempotency_skips_repeat_containment(self) -> None:
        id_store = InMemoryIdempotencyStore(default_ttl_seconds=60)
        commander = SOCIncidentCommander(
            pipeline=self._pipeline(),
            siem=InMemorySIEMAdapter(events=[]),
            edr=InMemoryEDRAdapter(),
            iam=InMemoryIAMAdapter(),
            idempotency_store=id_store,
            execution_policy=ExecutionPolicy(execute_containment_in_dry_run=True),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "Critical exfiltration: user_admin from 198.51.100.9 on host "
            "finance-01.prod.corp"
        )

        first = commander.run(
            scenario=scenario,
            mode="dry",
            metadata={"incident_id": "inc-fixed"},
        )
        second = commander.run(
            scenario=scenario,
            mode="dry",
            metadata={"incident_id": "inc-fixed"},
        )

        self.assertGreaterEqual(len(first.edr_actions), 1)
        self.assertGreaterEqual(len(first.iam_actions), 1)
        self.assertTrue(all(row.status == "executed" for row in first.edr_actions))
        self.assertTrue(all(row.status == "executed" for row in first.iam_actions))

        self.assertTrue(all(row.status == "skipped" for row in second.edr_actions))
        self.assertTrue(all(row.status == "skipped" for row in second.iam_actions))
        self.assertEqual(second.stats.skipped_total, len(second.edr_actions) + len(second.iam_actions))

    def test_retry_recovers_from_transient_edr_failure(self) -> None:
        flaky_edr = _FlakyEDR()
        commander = SOCIncidentCommander(
            pipeline=self._pipeline(),
            siem=InMemorySIEMAdapter(events=[]),
            edr=flaky_edr,
            iam=InMemoryIAMAdapter(),
            execution_policy=ExecutionPolicy(execute_containment_in_dry_run=True),
            retry_attempts=3,
            retry_backoff_seconds=0.0,
        )

        report = commander.run(
            scenario=(
                "Critical active incident for user_admin on host finance-01.prod.corp "
                "and source IP 198.51.100.9"
            ),
            mode="dry",
        )

        self.assertEqual(flaky_edr.calls, 2)
        edr = report.edr_actions[0]
        self.assertTrue(edr.success)
        self.assertEqual(edr.retried, 1)
        self.assertEqual(edr.attempts, 2)

    def test_parallel_siem_execution_reduces_wall_clock(self) -> None:
        sleepy = _SleepySIEM(delay_seconds=0.08)
        commander = SOCIncidentCommander(
            pipeline=self._pipeline(),
            siem=sleepy,
            edr=InMemoryEDRAdapter(),
            iam=InMemoryIAMAdapter(),
            execution_policy=ExecutionPolicy(
                execute_containment_in_dry_run=False,
                max_parallel_tasks=4,
            ),
            retry_backoff_seconds=0.0,
        )

        scenario = (
            "critical incident from 198.51.100.1 198.51.100.2 "
            "198.51.100.3 198.51.100.4"
        )

        started = time.perf_counter()
        report = commander.run(scenario=scenario, mode="dry")
        elapsed = time.perf_counter() - started

        self.assertEqual(len(report.siem_results), 4)
        sequential = sleepy.delay_seconds * sleepy.calls
        self.assertLess(elapsed, sequential * 0.8)


if __name__ == "__main__":
    unittest.main()
