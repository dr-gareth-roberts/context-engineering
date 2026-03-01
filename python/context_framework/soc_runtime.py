from __future__ import annotations

import hashlib
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Protocol
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from .tri_provider_pipeline import TriProviderPipeline, UseCaseExecutionReport

_IP_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_HOST_RE = re.compile(r"\b[a-zA-Z0-9][a-zA-Z0-9.-]{2,63}\b")
_USER_ID_RE = re.compile(r"\b(?:user|uid|acct)[-_]?[A-Za-z0-9._-]{2,}\b", re.IGNORECASE)


def _unique_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered


class SIEMAdapter(Protocol):
    def query(self, query: str, *, limit: int = 100) -> dict[str, Any]: ...


class EDRAdapter(Protocol):
    def isolate_host(self, hostname: str, *, reason: str) -> dict[str, Any]: ...


class IAMAdapter(Protocol):
    def suspend_user(self, user_id: str, *, reason: str) -> dict[str, Any]: ...


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


class NoOpSIEMAdapter:
    def query(self, query: str, *, limit: int = 100) -> dict[str, Any]:
        return {
            "query": query,
            "limit": limit,
            "events": [],
            "source": "noop",
        }


class NoOpEDRAdapter:
    def isolate_host(self, hostname: str, *, reason: str) -> dict[str, Any]:
        return {
            "hostname": hostname,
            "reason": reason,
            "status": "noop",
        }


class NoOpIAMAdapter:
    def suspend_user(self, user_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "user_id": user_id,
            "reason": reason,
            "status": "noop",
        }


@dataclass(slots=True)
class InMemorySIEMAdapter:
    events: list[dict[str, Any]]

    def query(self, query: str, *, limit: int = 100) -> dict[str, Any]:
        query_terms = [term for term in re.split(r"\W+", query.lower()) if term]
        matched: list[dict[str, Any]] = []
        for event in self.events:
            haystack = json.dumps(event, separators=(",", ":")).lower()
            if all(term in haystack for term in query_terms[:3]):
                matched.append(event)
            if len(matched) >= limit:
                break
        return {"query": query, "events": matched, "source": "in-memory"}


@dataclass(slots=True)
class InMemoryEDRAdapter:
    isolated_hosts: set[str] = field(default_factory=set)

    def isolate_host(self, hostname: str, *, reason: str) -> dict[str, Any]:
        self.isolated_hosts.add(hostname.lower())
        return {
            "hostname": hostname,
            "reason": reason,
            "isolated": True,
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryIAMAdapter:
    suspended_users: set[str] = field(default_factory=set)

    def suspend_user(self, user_id: str, *, reason: str) -> dict[str, Any]:
        self.suspended_users.add(user_id.lower())
        return {
            "user_id": user_id,
            "reason": reason,
            "suspended": True,
            "source": "in-memory",
        }


@dataclass(slots=True)
class _HTTPJSONAdapterBase:
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


@dataclass(slots=True)
class HTTPSIEMAdapter(_HTTPJSONAdapterBase):
    query_path: str = "/siem/query"

    def query(self, query: str, *, limit: int = 100) -> dict[str, Any]:
        return self._post(self.query_path, {"query": query, "limit": limit})


@dataclass(slots=True)
class HTTPEDRAdapter(_HTTPJSONAdapterBase):
    isolate_path: str = "/edr/isolate"

    def isolate_host(self, hostname: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.isolate_path, {"hostname": hostname, "reason": reason})


@dataclass(slots=True)
class HTTPIAMAdapter(_HTTPJSONAdapterBase):
    suspend_path: str = "/iam/suspend"

    def suspend_user(self, user_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.suspend_path, {"user_id": user_id, "reason": reason})


def build_siem_adapter_from_env() -> SIEMAdapter:
    base = os.getenv("SOC_SIEM_BASE_URL")
    token = os.getenv("SOC_SIEM_API_KEY")
    if base and token:
        path = os.getenv("SOC_SIEM_QUERY_PATH", "/siem/query")
        return HTTPSIEMAdapter(base_url=base, api_key=token, query_path=path)
    return NoOpSIEMAdapter()


def build_edr_adapter_from_env() -> EDRAdapter:
    base = os.getenv("SOC_EDR_BASE_URL")
    token = os.getenv("SOC_EDR_API_KEY")
    if base and token:
        path = os.getenv("SOC_EDR_ISOLATE_PATH", "/edr/isolate")
        return HTTPEDRAdapter(base_url=base, api_key=token, isolate_path=path)
    return NoOpEDRAdapter()


def build_iam_adapter_from_env() -> IAMAdapter:
    base = os.getenv("SOC_IAM_BASE_URL")
    token = os.getenv("SOC_IAM_API_KEY")
    if base and token:
        path = os.getenv("SOC_IAM_SUSPEND_PATH", "/iam/suspend")
        return HTTPIAMAdapter(base_url=base, api_key=token, suspend_path=path)
    return NoOpIAMAdapter()


@dataclass(slots=True, frozen=True)
class SOCIndicators:
    ips: tuple[str, ...]
    users: tuple[str, ...]
    hosts: tuple[str, ...]
    emails: tuple[str, ...]

    def all_entities(self) -> tuple[str, ...]:
        return (*self.ips, *self.users, *self.hosts, *self.emails)


@dataclass(slots=True, frozen=True)
class ExecutionPolicy:
    require_high_risk_for_containment: bool = True
    execute_containment_in_dry_run: bool = False
    allow_automated_edr: bool = True
    allow_automated_iam: bool = True
    max_parallel_tasks: int = 4
    siem_query_limit: int = 100

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if self.siem_query_limit < 1:
            raise ValueError("siem_query_limit must be >= 1")


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


@dataclass(slots=True, frozen=True)
class SOCExecutionStats:
    siem_total: int
    siem_success: int
    edr_total: int
    edr_success: int
    iam_total: int
    iam_success: int
    skipped_total: int
    failed_total: int


@dataclass(slots=True, frozen=True)
class SOCExecutionReport:
    incident_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    high_risk: bool
    indicators: SOCIndicators
    action_plan: tuple[str, ...]
    siem_results: tuple[ToolExecutionResult, ...]
    edr_actions: tuple[ToolExecutionResult, ...]
    iam_actions: tuple[ToolExecutionResult, ...]
    stats: SOCExecutionStats
    recommendations: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "incident_id": self.incident_id,
            "pipeline_report": self.pipeline_report.to_dict(),
            "mode": self.mode,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "high_risk": self.high_risk,
            "indicators": asdict(self.indicators),
            "action_plan": list(self.action_plan),
            "siem_results": [asdict(item) for item in self.siem_results],
            "edr_actions": [asdict(item) for item in self.edr_actions],
            "iam_actions": [asdict(item) for item in self.iam_actions],
            "stats": asdict(self.stats),
            "recommendations": list(self.recommendations),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(slots=True, frozen=True)
class _ExecutionTask:
    tool: str
    target: str
    request_payload: dict[str, Any]
    idempotency_key: str | None
    call: Callable[[], dict[str, Any]]


@dataclass(slots=True)
class SOCIncidentCommander:
    pipeline: TriProviderPipeline
    siem: SIEMAdapter
    edr: EDRAdapter
    iam: IAMAdapter
    audit_logger: AuditLogger = field(default_factory=NoOpAuditLogger)
    execution_policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    idempotency_store: IdempotencyStore = field(default_factory=InMemoryIdempotencyStore)
    max_hosts_to_isolate: int = 3
    max_users_to_suspend: int = 3
    retry_attempts: int = 2
    retry_backoff_seconds: float = 0.35
    idempotency_ttl_seconds: int = 4 * 60 * 60

    def run(
        self,
        *,
        scenario: str,
        evidence_documents: tuple[str, ...] = (),
        mode: str = "dry",
        metadata: dict[str, str] | None = None,
    ) -> SOCExecutionReport:
        if mode not in {"dry", "live"}:
            raise ValueError("mode must be 'dry' or 'live'")

        started_at = datetime.now(timezone.utc)
        warnings: list[str] = []
        errors: list[str] = []

        meta = dict(metadata or {})
        incident_id = meta.get("incident_id") or self._build_incident_id(scenario, started_at)
        meta["incident_id"] = incident_id

        pipeline_mode = "live" if mode == "live" else "dry"
        pipeline_report = self.pipeline.run(
            scenario=scenario,
            evidence_documents=evidence_documents,
            mode=pipeline_mode,
            metadata=meta,
        )

        indicators = self.extract_indicators(" ".join((scenario, *evidence_documents)))
        siem_queries = self._build_siem_queries(indicators)
        siem_tasks = self._build_siem_tasks(siem_queries)
        siem_results = self._execute_tasks(siem_tasks)

        high_risk = self._is_high_risk(pipeline_report, scenario)
        can_contain = True
        if self.execution_policy.require_high_risk_for_containment and not high_risk:
            can_contain = False
            warnings.append(
                "Scenario not classified as high risk; containment actions were gated by policy."
            )
        if mode == "dry" and not self.execution_policy.execute_containment_in_dry_run:
            can_contain = False
            warnings.append("Containment actions skipped in dry mode by execution policy.")

        action_plan = self._build_action_plan(
            indicators=indicators,
            high_risk=high_risk,
            can_contain=can_contain,
            max_hosts_to_isolate=self.max_hosts_to_isolate,
            max_users_to_suspend=self.max_users_to_suspend,
        )

        containment_tasks = self._build_containment_tasks(
            incident_id=incident_id,
            indicators=indicators,
            can_contain=can_contain,
        )
        containment_results = self._execute_tasks(containment_tasks)
        edr_actions = [row for row in containment_results if row.tool == "edr_isolate_host"]
        iam_actions = [row for row in containment_results if row.tool == "iam_suspend_user"]

        for row in (*siem_results, *containment_results):
            if not row.success:
                errors.append(f"{row.tool} failed for {row.target}: {row.error}")
            self._log_audit_event(
                incident_id=incident_id,
                mode=mode,
                row=row,
            )

        stats = self._build_stats(
            siem_results=tuple(siem_results),
            edr_actions=tuple(edr_actions),
            iam_actions=tuple(iam_actions),
        )

        recommendations = self._recommendations(
            pipeline_report=pipeline_report,
            high_risk=high_risk,
            indicators=indicators,
            siem_results=tuple(siem_results),
            edr_actions=tuple(edr_actions),
            iam_actions=tuple(iam_actions),
            stats=stats,
        )

        completed_at = datetime.now(timezone.utc)
        return SOCExecutionReport(
            incident_id=incident_id,
            pipeline_report=pipeline_report,
            mode=mode,
            started_at=started_at,
            completed_at=completed_at,
            high_risk=high_risk,
            indicators=indicators,
            action_plan=tuple(action_plan),
            siem_results=tuple(siem_results),
            edr_actions=tuple(edr_actions),
            iam_actions=tuple(iam_actions),
            stats=stats,
            recommendations=tuple(recommendations),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    @staticmethod
    def extract_indicators(text: str) -> SOCIndicators:
        ips = _unique_preserve([match.group(0) for match in _IP_RE.finditer(text)])
        emails = _unique_preserve([match.group(0) for match in _EMAIL_RE.finditer(text)])
        users = _unique_preserve([match.group(0) for match in _USER_ID_RE.finditer(text)] + emails)
        hosts = _unique_preserve(
            [
                value
                for value in (match.group(0) for match in _HOST_RE.finditer(text))
                if "." in value and "@" not in value and not _IP_RE.fullmatch(value)
            ]
        )
        return SOCIndicators(
            ips=tuple(ips),
            users=tuple(users),
            hosts=tuple(hosts),
            emails=tuple(emails),
        )

    @staticmethod
    def _build_siem_queries(indicators: SOCIndicators) -> tuple[str, ...]:
        queries: list[str] = []
        for ip in indicators.ips[:4]:
            queries.append(f'source.ip:"{ip}" OR destination.ip:"{ip}"')
        for user in indicators.users[:4]:
            queries.append(f'user.name:"{user}" OR principal.user:"{user}"')
        for host in indicators.hosts[:4]:
            queries.append(f'host.name:"{host}" OR endpoint.hostname:"{host}"')
        if not queries:
            queries.append("event.category:authentication AND event.outcome:failure")
        return tuple(queries)

    @staticmethod
    def _is_high_risk(report: UseCaseExecutionReport, scenario: str) -> bool:
        corpus = " ".join(
            [
                scenario.lower(),
                report.openai_stage.response_preview.lower(),
                report.final_plan.lower(),
            ]
        )
        return any(
            token in corpus
            for token in (
                "critical",
                "high",
                "compromise",
                "exfiltration",
                "ransomware",
                "active incident",
            )
        )

    @staticmethod
    def _build_incident_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"inc-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _build_siem_tasks(self, queries: tuple[str, ...]) -> list[_ExecutionTask]:
        tasks: list[_ExecutionTask] = []
        for query in queries:
            tasks.append(
                _ExecutionTask(
                    tool="siem_query",
                    target=query,
                    request_payload={
                        "query": query,
                        "limit": self.execution_policy.siem_query_limit,
                    },
                    idempotency_key=None,
                    call=lambda query=query: self.siem.query(
                        query,
                        limit=self.execution_policy.siem_query_limit,
                    ),
                )
            )
        return tasks

    def _build_containment_tasks(
        self,
        *,
        incident_id: str,
        indicators: SOCIndicators,
        can_contain: bool,
    ) -> list[_ExecutionTask]:
        if not can_contain:
            return []

        tasks: list[_ExecutionTask] = []

        if self.execution_policy.allow_automated_edr:
            for host in indicators.hosts[: self.max_hosts_to_isolate]:
                reason = f"{self.pipeline.spec.use_case_id}: automated containment"
                tasks.append(
                    _ExecutionTask(
                        tool="edr_isolate_host",
                        target=host,
                        request_payload={"hostname": host, "reason": reason},
                        idempotency_key=f"{incident_id}:edr_isolate_host:{host.lower()}",
                        call=lambda host=host, reason=reason: self.edr.isolate_host(
                            host, reason=reason
                        ),
                    )
                )

        if self.execution_policy.allow_automated_iam:
            for user in indicators.users[: self.max_users_to_suspend]:
                reason = f"{self.pipeline.spec.use_case_id}: suspicious identity activity"
                tasks.append(
                    _ExecutionTask(
                        tool="iam_suspend_user",
                        target=user,
                        request_payload={"user_id": user, "reason": reason},
                        idempotency_key=f"{incident_id}:iam_suspend_user:{user.lower()}",
                        call=lambda user=user, reason=reason: self.iam.suspend_user(
                            user, reason=reason
                        ),
                    )
                )

        return tasks

    def _execute_tasks(self, tasks: list[_ExecutionTask]) -> list[ToolExecutionResult]:
        if not tasks:
            return []

        workers = min(self.execution_policy.max_parallel_tasks, len(tasks))
        if workers == 1:
            return [self._execute_task(task) for task in tasks]

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._execute_task, task) for task in tasks]
            return [future.result() for future in futures]

    def _execute_task(self, task: _ExecutionTask) -> ToolExecutionResult:
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

    @staticmethod
    def _build_action_plan(
        *,
        indicators: SOCIndicators,
        high_risk: bool,
        can_contain: bool,
        max_hosts_to_isolate: int,
        max_users_to_suspend: int,
    ) -> list[str]:
        plan: list[str] = [
            "Run indicator-led SIEM pivots and establish event timeline.",
            "Correlate identity and endpoint signals before broad remediation.",
        ]

        if can_contain:
            if indicators.hosts:
                plan.append(
                    "Isolate up to "
                    f"{min(len(indicators.hosts), max_hosts_to_isolate)} suspicious hosts "
                    "with rollback checkpoints."
                )
            if indicators.users:
                plan.append(
                    "Suspend up to "
                    f"{min(len(indicators.users), max_users_to_suspend)} risky identities "
                    "with owner notification."
                )
        elif high_risk:
            plan.append("High-risk signals present; request human approval to execute containment.")
        else:
            plan.append(
                "Maintain enhanced monitoring until risk is elevated or confidence improves."
            )

        plan.append("Document timeline, preservation actions, and post-incident detection gaps.")
        return plan

    @staticmethod
    def _build_stats(
        *,
        siem_results: tuple[ToolExecutionResult, ...],
        edr_actions: tuple[ToolExecutionResult, ...],
        iam_actions: tuple[ToolExecutionResult, ...],
    ) -> SOCExecutionStats:
        all_rows = (*siem_results, *edr_actions, *iam_actions)
        skipped_total = sum(1 for row in all_rows if row.status == "skipped")
        failed_total = sum(1 for row in all_rows if not row.success)
        return SOCExecutionStats(
            siem_total=len(siem_results),
            siem_success=sum(1 for row in siem_results if row.success),
            edr_total=len(edr_actions),
            edr_success=sum(1 for row in edr_actions if row.success),
            iam_total=len(iam_actions),
            iam_success=sum(1 for row in iam_actions if row.success),
            skipped_total=skipped_total,
            failed_total=failed_total,
        )

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        high_risk: bool,
        indicators: SOCIndicators,
        siem_results: tuple[ToolExecutionResult, ...],
        edr_actions: tuple[ToolExecutionResult, ...],
        iam_actions: tuple[ToolExecutionResult, ...],
        stats: SOCExecutionStats,
    ) -> list[str]:
        recommendations: list[str] = []
        if high_risk:
            recommendations.append(
                "Maintain elevated incident bridge until containment verification completes."
            )
        else:
            recommendations.append(
                "Continue enhanced monitoring and wait for corroborating high-risk indicators."
            )

        recommendations.append(
            f"SIEM queries executed successfully: {stats.siem_success}/{stats.siem_total}."
        )

        if edr_actions:
            recommendations.append(
                f"Endpoint isolations applied: {stats.edr_success}/{stats.edr_total}."
            )
        if iam_actions:
            recommendations.append(
                f"Identity suspensions applied: {stats.iam_success}/{stats.iam_total}."
            )
        if stats.skipped_total:
            recommendations.append(
                f"Skipped actions due to idempotency/policy: {stats.skipped_total}."
            )

        if indicators.ips:
            recommendations.append(
                "Correlate east-west and egress telemetry for extracted IP indicators."
            )
        if indicators.users:
            recommendations.append("Review privileged operations for extracted user indicators.")

        recommendations.append("Post-incident: run detection-gap review and update playbooks.")
        if pipeline_report.ranked_actions:
            recommendations.append(
                f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}"
            )
        else:
            recommendations.append(
                "Primary tri-provider action unavailable; escalate for manual triage."
            )

        if siem_results and all(not row.success for row in siem_results):
            recommendations.append(
                "SIEM failed for all pivots; switch to backup telemetry stack immediately."
            )

        return recommendations
