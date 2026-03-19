"""Shared infrastructure for domain-specific Commander runtimes.

Every runtime (SOC, AML, Claims, Supply Chain, etc.) needs the same
building blocks:

- ``AuditLogger`` / ``IdempotencyStore`` protocols and default
  implementations (``NoOpAuditLogger``, ``JSONLAuditLogger``,
  ``InMemoryIdempotencyStore``).
- ``HTTPJSONAdapterBase`` for HTTP-backed tool adapters.
- ``ExecutionTask`` / ``ToolExecutionResult`` for tool-based execution.
- ``IntegrationExecutionTask`` / ``IntegrationActionResult`` for
  integration-based execution (3-field: integration, operation, target).
- ``unique_preserve()`` helper.
- ``BaseCommanderMixin`` with ``_execute_tasks``, ``_execute_task``,
  ``_execute_with_retry``, ``_is_retryable_error``, ``_safe_payload``,
  and ``_log_audit_event``.
- ``BaseIntegrationCommanderMixin`` — the same for integration runtimes
  that use the ``integration/operation/target`` pattern.

This module centralises those patterns so each runtime only needs its
domain-specific logic.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Protocol
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def unique_preserve(values: list[str]) -> list[str]:
    """Deduplicate *values* while preserving first-seen order (case-insensitive)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered


# ---------------------------------------------------------------------------
# Audit & Idempotency protocols + default implementations
# ---------------------------------------------------------------------------


class AuditLogger(Protocol):
    def log(self, event: dict[str, Any]) -> None: ...


class IdempotencyStore(Protocol):
    def seen(self, key: str) -> bool: ...

    def mark(self, key: str, *, ttl_seconds: int | None = None) -> None: ...


class NoOpAuditLogger:
    def log(self, event: dict[str, Any]) -> None:
        _ = event


@dataclass(slots=True)
class JSONLAuditLogger:
    path: Path

    def __post_init__(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, separators=(",", ":"), default=str)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")


@dataclass(slots=True)
class InMemoryIdempotencyStore:
    default_ttl_seconds: int = 4 * 60 * 60
    _entries: dict[str, float] = field(default_factory=dict, init=False)
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    def seen(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            self._prune(now)
            expires_at = self._entries.get(key)
            return expires_at is not None and expires_at > now

    def mark(self, key: str, *, ttl_seconds: int | None = None) -> None:
        ttl = self.default_ttl_seconds if ttl_seconds is None else max(1, ttl_seconds)
        with self._lock:
            self._entries[key] = time.time() + ttl

    def _prune(self, now: float) -> None:
        stale = [key for key, expires_at in self._entries.items() if expires_at <= now]
        for key in stale:
            self._entries.pop(key, None)


# ---------------------------------------------------------------------------
# HTTP adapter base
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class HTTPJSONAdapterBase:
    """Shared base for all HTTP-backed tool adapters."""

    base_url: str
    api_key: str
    timeout_seconds: float = 10.0

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{self.base_url.rstrip('/')}{path}"
        body = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urlrequest.urlopen(req, timeout=self.timeout_seconds) as response:
                data = response.read().decode("utf-8")
                if not data.strip():
                    return {}
                return json.loads(data)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Network error: {exc}") from exc


# ---------------------------------------------------------------------------
# Execution primitives
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class ExecutionTask:
    tool: str
    target: str
    request_payload: dict[str, Any]
    idempotency_key: str | None
    call: Callable[[], dict[str, Any]]


@dataclass(slots=True, frozen=True)
class ToolExecutionResult:
    tool: str
    target: str
    success: bool
    latency_ms: int
    request: dict[str, Any]
    response: dict[str, Any] | None = None
    error: str | None = None
    retried: int = 0
    attempts: int = 1
    status: str = "executed"
    idempotency_key: str | None = None
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Base commander mixin
# ---------------------------------------------------------------------------


class BaseCommanderMixin:
    """Mixin providing shared task-execution, retry, audit, and idempotency logic.

    Concrete Commander classes should inherit from this mixin and provide:
    - ``audit_logger: AuditLogger``
    - ``idempotency_store: IdempotencyStore``
    - ``retry_attempts: int``
    - ``retry_backoff_seconds: float``
    - ``idempotency_ttl_seconds: int``
    - ``execution_policy`` with ``max_parallel_tasks: int``
    """

    # Subclass must set these (typically via dataclass fields).
    audit_logger: AuditLogger
    idempotency_store: IdempotencyStore
    retry_attempts: int
    retry_backoff_seconds: float
    idempotency_ttl_seconds: int

    def _get_max_parallel_tasks(self) -> int:
        policy = getattr(self, "execution_policy", None)
        if policy is not None:
            return getattr(policy, "max_parallel_tasks", 4)
        return 4

    def _execute_tasks(self, tasks: list[ExecutionTask]) -> list[ToolExecutionResult]:
        if not tasks:
            return []

        from concurrent.futures import ThreadPoolExecutor

        workers = min(self._get_max_parallel_tasks(), len(tasks))
        if workers == 1:
            return [self._execute_task(task) for task in tasks]

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._execute_task, task) for task in tasks]
            return [future.result() for future in futures]

    def _execute_task(self, task: ExecutionTask) -> ToolExecutionResult:
        if task.idempotency_key and self.idempotency_store.seen(task.idempotency_key):
            return ToolExecutionResult(
                tool=task.tool,
                target=task.target,
                success=True,
                latency_ms=0,
                request=task.request_payload,
                response=None,
                retried=0,
                attempts=0,
                status="skipped",
                idempotency_key=task.idempotency_key,
                notes=("duplicate action suppressed by idempotency store",),
            )

        result = self._execute_with_retry(
            tool=task.tool,
            target=task.target,
            request_payload=task.request_payload,
            call=task.call,
            idempotency_key=task.idempotency_key,
        )

        if result.success and result.status == "executed" and task.idempotency_key:
            self.idempotency_store.mark(
                task.idempotency_key, ttl_seconds=self.idempotency_ttl_seconds
            )

        return result

    def _execute_with_retry(
        self,
        *,
        tool: str,
        target: str,
        request_payload: dict[str, Any],
        call: Callable[[], dict[str, Any]],
        idempotency_key: str | None,
    ) -> ToolExecutionResult:
        attempts = max(1, self.retry_attempts)
        retried = 0
        last_error: str | None = None
        used_attempts = 0
        start = time.perf_counter()
        for attempt in range(1, attempts + 1):
            used_attempts = attempt
            try:
                response = call()
                latency_ms = int((time.perf_counter() - start) * 1000)
                return ToolExecutionResult(
                    tool=tool,
                    target=target,
                    success=True,
                    latency_ms=latency_ms,
                    request=request_payload,
                    response=response,
                    retried=retried,
                    attempts=used_attempts,
                    status="executed",
                    idempotency_key=idempotency_key,
                )
            except Exception as exc:  # noqa: BLE001 - explicit operational capture
                last_error = str(exc)
                if attempt >= attempts or not self._is_retryable_error(exc):
                    break
                retried += 1
                time.sleep(self.retry_backoff_seconds * attempt)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return ToolExecutionResult(
            tool=tool,
            target=target,
            success=False,
            latency_ms=latency_ms,
            request=request_payload,
            response=None,
            error=last_error or "unknown error",
            retried=retried,
            attempts=used_attempts,
            status="executed",
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        text = str(exc).lower()
        retryable_markers = (
            "timeout",
            "tempor",
            "rate limit",
            "connection reset",
            "connection aborted",
            "unavailable",
            "429",
            "502",
            "503",
            "504",
        )
        return any(marker in text for marker in retryable_markers)

    def _log_audit_event(
        self,
        *,
        incident_id: str,
        mode: str,
        row: ToolExecutionResult,
    ) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "incident_id": incident_id,
            "mode": mode,
            "tool": row.tool,
            "target": row.target,
            "status": row.status,
            "success": row.success,
            "latency_ms": row.latency_ms,
            "attempts": row.attempts,
            "retried": row.retried,
            "idempotency_key": row.idempotency_key,
            "request": self._safe_payload(row.request),
            "response": self._safe_payload(row.response),
            "error": row.error,
            "notes": list(row.notes),
        }
        self.audit_logger.log(event)

    @staticmethod
    def _safe_payload(payload: Any, *, max_chars: int = 900) -> Any:
        if payload is None:
            return None
        try:
            encoded = json.dumps(payload, separators=(",", ":"), default=str)
        except Exception:  # noqa: BLE001
            return str(payload)[:max_chars]
        if len(encoded) <= max_chars:
            return payload
        return {
            "truncated": True,
            "size": len(encoded),
            "preview": encoded[:max_chars],
        }


# ---------------------------------------------------------------------------
# Integration-pattern execution primitives
# ---------------------------------------------------------------------------
# Many domain runtimes (supply chain, pharma, grid, AML, …) use a
# 3-field task descriptor (integration, operation, target) rather than
# the 2-field (tool, target) used by the SOC/Claims mixin.  The types
# and mixin below centralise that pattern.


@dataclass(slots=True, frozen=True)
class IntegrationActionResult:
    """Result of a single integration call (integration/operation/target pattern)."""

    integration: str
    operation: str
    target: str
    success: bool
    latency_ms: int
    request: dict[str, Any]
    response: dict[str, Any] | None = None
    error: str | None = None
    retried: int = 0
    attempts: int = 1
    status: str = "executed"
    idempotency_key: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class IntegrationExecutionTask:
    """Task descriptor for integration-based execution."""

    integration: str
    operation: str
    target: str
    request_payload: dict[str, Any]
    idempotency_key: str | None
    call: Callable[[], dict[str, Any]]


class BaseIntegrationCommanderMixin:
    """Mixin providing shared task-execution, retry, audit, and idempotency
    logic for runtimes that use the ``integration/operation/target`` pattern.

    Concrete Commander classes should inherit from this mixin and provide:
    - ``audit_logger: AuditLogger``
    - ``idempotency_store: IdempotencyStore``
    - ``retry_attempts: int``
    - ``retry_backoff_seconds: float``
    - ``idempotency_ttl_seconds: int``
    - ``execution_policy`` with ``max_parallel_tasks: int``
    """

    # Subclass must set these (typically via dataclass fields).
    audit_logger: AuditLogger
    idempotency_store: IdempotencyStore
    retry_attempts: int
    retry_backoff_seconds: float
    idempotency_ttl_seconds: int

    def _get_max_parallel_tasks(self) -> int:
        policy = getattr(self, "execution_policy", None)
        if policy is not None:
            return getattr(policy, "max_parallel_tasks", 4)
        return 4

    def _execute_integration_tasks(
        self, tasks: list[IntegrationExecutionTask]
    ) -> list[IntegrationActionResult]:
        if not tasks:
            return []

        from concurrent.futures import ThreadPoolExecutor

        workers = min(self._get_max_parallel_tasks(), len(tasks))
        if workers == 1:
            return [self._execute_integration_task(task) for task in tasks]

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._execute_integration_task, task) for task in tasks]
            return [future.result() for future in futures]

    def _execute_integration_task(
        self, task: IntegrationExecutionTask
    ) -> IntegrationActionResult:
        if task.idempotency_key and self.idempotency_store.seen(task.idempotency_key):
            return IntegrationActionResult(
                integration=task.integration,
                operation=task.operation,
                target=task.target,
                success=True,
                latency_ms=0,
                request=task.request_payload,
                response=None,
                retried=0,
                attempts=0,
                status="skipped",
                idempotency_key=task.idempotency_key,
                notes=("duplicate action suppressed by idempotency store",),
            )

        result = self._execute_integration_with_retry(
            integration=task.integration,
            operation=task.operation,
            target=task.target,
            request_payload=task.request_payload,
            call=task.call,
            idempotency_key=task.idempotency_key,
        )

        if result.success and result.status == "executed" and task.idempotency_key:
            self.idempotency_store.mark(
                task.idempotency_key, ttl_seconds=self.idempotency_ttl_seconds
            )

        return result

    def _execute_integration_with_retry(
        self,
        *,
        integration: str,
        operation: str,
        target: str,
        request_payload: dict[str, Any],
        call: Callable[[], dict[str, Any]],
        idempotency_key: str | None,
    ) -> IntegrationActionResult:
        attempts = max(1, self.retry_attempts)
        retried = 0
        used_attempts = 0
        last_error: str | None = None
        start = time.perf_counter()

        for attempt in range(1, attempts + 1):
            used_attempts = attempt
            try:
                response = call()
                latency_ms = int((time.perf_counter() - start) * 1000)
                return IntegrationActionResult(
                    integration=integration,
                    operation=operation,
                    target=target,
                    success=True,
                    latency_ms=latency_ms,
                    request=request_payload,
                    response=response,
                    retried=retried,
                    attempts=used_attempts,
                    status="executed",
                    idempotency_key=idempotency_key,
                )
            except Exception as exc:  # noqa: BLE001 - capture runtime integration failures
                last_error = str(exc)
                if attempt >= attempts or not self._is_retryable_error(exc):
                    break
                retried += 1
                time.sleep(self.retry_backoff_seconds * attempt)

        latency_ms = int((time.perf_counter() - start) * 1000)
        return IntegrationActionResult(
            integration=integration,
            operation=operation,
            target=target,
            success=False,
            latency_ms=latency_ms,
            request=request_payload,
            error=last_error or "unknown error",
            retried=retried,
            attempts=used_attempts,
            status="executed",
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        text = str(exc).lower()
        retryable_markers = (
            "timeout",
            "tempor",
            "rate limit",
            "connection reset",
            "connection aborted",
            "unavailable",
            "429",
            "502",
            "503",
            "504",
        )
        return any(marker in text for marker in retryable_markers)

    def _log_integration_audit_event(
        self,
        *,
        batch_id: str,
        mode: str,
        row: IntegrationActionResult,
    ) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "batch_id": batch_id,
            "mode": mode,
            "integration": row.integration,
            "operation": row.operation,
            "target": row.target,
            "status": row.status,
            "success": row.success,
            "latency_ms": row.latency_ms,
            "attempts": row.attempts,
            "retried": row.retried,
            "idempotency_key": row.idempotency_key,
            "request": self._safe_payload(row.request),
            "response": self._safe_payload(row.response),
            "error": row.error,
            "notes": list(row.notes),
        }
        self.audit_logger.log(event)

    @staticmethod
    def _safe_payload(payload: Any, *, max_chars: int = 900) -> Any:
        if payload is None:
            return None
        try:
            encoded = json.dumps(payload, separators=(",", ":"), default=str)
        except Exception:  # noqa: BLE001
            return str(payload)[:max_chars]
        if len(encoded) <= max_chars:
            return payload
        return {
            "truncated": True,
            "size": len(encoded),
            "preview": encoded[:max_chars],
        }
