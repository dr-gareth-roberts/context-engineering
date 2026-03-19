"""Tests for context_framework.runtime_base shared infrastructure."""

from __future__ import annotations

import time
from typing import Any

import pytest

from context_framework.runtime_base import (
    BaseCommanderMixin,
    ExecutionTask,
    InMemoryIdempotencyStore,
    NoOpAuditLogger,
    unique_preserve,
)


# ---------------------------------------------------------------------------
# unique_preserve
# ---------------------------------------------------------------------------


def test_unique_preserve_deduplicates_preserving_order():
    result = unique_preserve(["alpha", "beta", "alpha", "gamma", "beta"])
    assert result == ["alpha", "beta", "gamma"]


def test_unique_preserve_case_insensitive():
    result = unique_preserve(["Hello", "hello", "HELLO", "World", "world"])
    assert result == ["Hello", "World"]


def test_unique_preserve_empty_list():
    assert unique_preserve([]) == []


# ---------------------------------------------------------------------------
# InMemoryIdempotencyStore
# ---------------------------------------------------------------------------


def test_idempotency_store_mark_then_seen():
    store = InMemoryIdempotencyStore()
    store.mark("key-1")
    assert store.seen("key-1") is True


def test_idempotency_store_seen_returns_false_for_unknown():
    store = InMemoryIdempotencyStore()
    assert store.seen("unknown-key") is False


# ---------------------------------------------------------------------------
# Minimal concrete subclass of BaseCommanderMixin for testing
# ---------------------------------------------------------------------------


class _TestCommander(BaseCommanderMixin):
    def __init__(
        self,
        retry_attempts: int = 2,
        retry_backoff_seconds: float = 0.0,
        idempotency_ttl_seconds: int = 3600,
    ) -> None:
        self.audit_logger = NoOpAuditLogger()
        self.idempotency_store = InMemoryIdempotencyStore()
        self.retry_attempts = retry_attempts
        self.retry_backoff_seconds = retry_backoff_seconds
        self.idempotency_ttl_seconds = idempotency_ttl_seconds


def _make_task(
    *,
    tool: str = "test-tool",
    target: str = "target-1",
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    call: Any = None,
) -> ExecutionTask:
    return ExecutionTask(
        tool=tool,
        target=target,
        request_payload=payload or {},
        idempotency_key=idempotency_key,
        call=call or (lambda: {"ok": True}),
    )


# ---------------------------------------------------------------------------
# _execute_tasks
# ---------------------------------------------------------------------------


def test_execute_tasks_empty_list():
    commander = _TestCommander()
    results = commander._execute_tasks([])
    assert results == []


# ---------------------------------------------------------------------------
# _execute_task — idempotency
# ---------------------------------------------------------------------------


def test_execute_task_skips_duplicate_via_idempotency():
    commander = _TestCommander()
    task = _make_task(idempotency_key="dup-key")

    # First execution succeeds and marks the key
    r1 = commander._execute_task(task)
    assert r1.success is True
    assert r1.status == "executed"

    # Second execution is skipped
    r2 = commander._execute_task(task)
    assert r2.success is True
    assert r2.status == "skipped"
    assert r2.attempts == 0


# ---------------------------------------------------------------------------
# _execute_with_retry
# ---------------------------------------------------------------------------


def test_execute_with_retry_succeeds_on_first_attempt():
    commander = _TestCommander(retry_attempts=3)
    result = commander._execute_with_retry(
        tool="t",
        target="tgt",
        request_payload={},
        call=lambda: {"result": "ok"},
        idempotency_key=None,
    )
    assert result.success is True
    assert result.attempts == 1
    assert result.retried == 0


def test_execute_with_retry_retries_on_retryable_error():
    call_count = 0

    def flaky_call() -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("503 Service Unavailable")
        return {"recovered": True}

    commander = _TestCommander(retry_attempts=3, retry_backoff_seconds=0.0)
    result = commander._execute_with_retry(
        tool="t",
        target="tgt",
        request_payload={},
        call=flaky_call,
        idempotency_key=None,
    )
    assert result.success is True
    assert result.retried == 1
    assert result.attempts == 2


# ---------------------------------------------------------------------------
# _is_retryable_error
# ---------------------------------------------------------------------------


def test_is_retryable_error_identifies_timeout_and_503():
    assert BaseCommanderMixin._is_retryable_error(RuntimeError("request timeout")) is True
    assert BaseCommanderMixin._is_retryable_error(RuntimeError("HTTP 503")) is True
    assert BaseCommanderMixin._is_retryable_error(RuntimeError("service unavailable")) is True
    assert BaseCommanderMixin._is_retryable_error(RuntimeError("rate limit exceeded")) is True


def test_is_retryable_error_returns_false_for_non_retryable():
    assert BaseCommanderMixin._is_retryable_error(ValueError("bad input")) is False
    assert BaseCommanderMixin._is_retryable_error(RuntimeError("not found")) is False
    assert BaseCommanderMixin._is_retryable_error(KeyError("missing")) is False


# ---------------------------------------------------------------------------
# _safe_payload
# ---------------------------------------------------------------------------


def test_safe_payload_truncates_large_payloads():
    large = {"data": "x" * 2000}
    result = BaseCommanderMixin._safe_payload(large, max_chars=100)
    assert isinstance(result, dict)
    assert result["truncated"] is True
    assert "preview" in result
    assert len(result["preview"]) <= 100


def test_safe_payload_handles_none():
    assert BaseCommanderMixin._safe_payload(None) is None
