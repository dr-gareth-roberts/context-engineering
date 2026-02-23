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

_CLAIM_ID_RE = re.compile(r"\b(?:CLM|CLAIM)[-_]?\d{3,}\b", re.IGNORECASE)
_CLAIMANT_ID_RE = re.compile(
    r"\b(?:CLMT|CUST|CLAIMANT|POLHOLDER)[-_]?[A-Za-z0-9]{3,}\b",
    re.IGNORECASE,
)
_POLICY_ID_RE = re.compile(r"\b(?:POL|POLICY)[-_]?\d{2,}\b", re.IGNORECASE)
_REGION_RE = re.compile(r"\b[A-Z]{2}-\d{5}\b")


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


def _normalize_identifier(value: str) -> str:
    return value.strip().replace("_", "-").upper()


class PolicyAdapter(Protocol):
    def lookup_claim(self, claim_id: str) -> dict[str, Any]:
        ...


class FraudAdapter(Protocol):
    def evaluate_claim(self, claim_id: str, *, claimant_id: str | None = None) -> dict[str, Any]:
        ...


class PayoutAdapter(Protocol):
    def issue_advance(self, claim_id: str, *, amount_cents: int, reason: str) -> dict[str, Any]:
        ...

    def place_hold(self, claim_id: str, *, reason: str) -> dict[str, Any]:
        ...


class AuditLogger(Protocol):
    def log(self, event: dict[str, Any]) -> None:
        ...


class IdempotencyStore(Protocol):
    def seen(self, key: str) -> bool:
        ...

    def mark(self, key: str, *, ttl_seconds: int | None = None) -> None:
        ...


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


class NoOpPolicyAdapter:
    def lookup_claim(self, claim_id: str) -> dict[str, Any]:
        return {
            "claim_id": _normalize_identifier(claim_id),
            "policy_status": "active",
            "coverage_limit_cents": 1_000_000,
            "deductible_cents": 100_000,
            "source": "noop",
        }


class NoOpFraudAdapter:
    def evaluate_claim(self, claim_id: str, *, claimant_id: str | None = None) -> dict[str, Any]:
        return {
            "claim_id": _normalize_identifier(claim_id),
            "claimant_id": claimant_id,
            "fraud_score": 0.15,
            "signals": [],
            "source": "noop",
        }


class NoOpPayoutAdapter:
    def issue_advance(self, claim_id: str, *, amount_cents: int, reason: str) -> dict[str, Any]:
        return {
            "claim_id": _normalize_identifier(claim_id),
            "amount_cents": amount_cents,
            "reason": reason,
            "status": "noop",
            "source": "noop",
        }

    def place_hold(self, claim_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "claim_id": _normalize_identifier(claim_id),
            "reason": reason,
            "status": "noop",
            "source": "noop",
        }


@dataclass(slots=True)
class InMemoryPolicyAdapter:
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    default_policy_status: str = "active"

    def lookup_claim(self, claim_id: str) -> dict[str, Any]:
        key = _normalize_identifier(claim_id)
        response = {
            "claim_id": key,
            "policy_status": self.default_policy_status,
            "coverage_limit_cents": 1_500_000,
            "deductible_cents": 75_000,
            "line_of_business": "property",
            "source": "in-memory",
        }
        if key in self.claims:
            response.update(dict(self.claims[key]))
        response["claim_id"] = key
        return response


@dataclass(slots=True)
class InMemoryFraudAdapter:
    scores: dict[str, float] = field(default_factory=dict)
    default_score: float = 0.15

    def evaluate_claim(self, claim_id: str, *, claimant_id: str | None = None) -> dict[str, Any]:
        key = _normalize_identifier(claim_id)
        score = self._normalize_score(self.scores.get(key, self.default_score))
        signals: list[str] = []
        if score >= 0.85:
            signals.append("multi-claim duplicate footprint")
            signals.append("identity geolocation mismatch")
        elif score >= 0.55:
            signals.append("inconsistent loss chronology")
        return {
            "claim_id": key,
            "claimant_id": claimant_id,
            "fraud_score": score,
            "signals": signals,
            "source": "in-memory",
        }

    @staticmethod
    def _normalize_score(value: Any) -> float:
        try:
            score = float(value)
        except Exception:  # noqa: BLE001
            score = 0.0
        if score > 1.0:
            score = score / 100.0
        return max(0.0, min(1.0, score))


@dataclass(slots=True)
class InMemoryPayoutAdapter:
    actions: list[dict[str, Any]] = field(default_factory=list)

    def issue_advance(self, claim_id: str, *, amount_cents: int, reason: str) -> dict[str, Any]:
        row = {
            "action": "issue_advance",
            "claim_id": _normalize_identifier(claim_id),
            "amount_cents": int(amount_cents),
            "reason": reason,
            "status": "queued",
            "source": "in-memory",
        }
        self.actions.append(dict(row))
        return row

    def place_hold(self, claim_id: str, *, reason: str) -> dict[str, Any]:
        row = {
            "action": "place_hold",
            "claim_id": _normalize_identifier(claim_id),
            "reason": reason,
            "status": "queued",
            "source": "in-memory",
        }
        self.actions.append(dict(row))
        return row


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
class HTTPPolicyAdapter(_HTTPJSONAdapterBase):
    lookup_path: str = "/claims/policy_lookup"

    def lookup_claim(self, claim_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"claim_id": _normalize_identifier(claim_id)})


@dataclass(slots=True)
class HTTPFraudAdapter(_HTTPJSONAdapterBase):
    evaluate_path: str = "/claims/fraud_lookup"

    def evaluate_claim(self, claim_id: str, *, claimant_id: str | None = None) -> dict[str, Any]:
        payload = {"claim_id": _normalize_identifier(claim_id)}
        if claimant_id:
            payload["claimant_id"] = claimant_id
        return self._post(self.evaluate_path, payload)


@dataclass(slots=True)
class HTTPPayoutAdapter(_HTTPJSONAdapterBase):
    advance_path: str = "/claims/issue_advance"
    hold_path: str = "/claims/place_hold"

    def issue_advance(self, claim_id: str, *, amount_cents: int, reason: str) -> dict[str, Any]:
        return self._post(
            self.advance_path,
            {
                "claim_id": _normalize_identifier(claim_id),
                "amount_cents": int(amount_cents),
                "reason": reason,
            },
        )

    def place_hold(self, claim_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.hold_path,
            {
                "claim_id": _normalize_identifier(claim_id),
                "reason": reason,
            },
        )


def build_policy_adapter_from_env() -> PolicyAdapter:
    base = os.getenv("CLAIMS_POLICY_BASE_URL")
    token = os.getenv("CLAIMS_POLICY_API_KEY")
    if base and token:
        path = os.getenv("CLAIMS_POLICY_LOOKUP_PATH", "/claims/policy_lookup")
        return HTTPPolicyAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpPolicyAdapter()


def build_fraud_adapter_from_env() -> FraudAdapter:
    base = os.getenv("CLAIMS_FRAUD_BASE_URL")
    token = os.getenv("CLAIMS_FRAUD_API_KEY")
    if base and token:
        path = os.getenv("CLAIMS_FRAUD_EVALUATE_PATH", "/claims/fraud_lookup")
        return HTTPFraudAdapter(base_url=base, api_key=token, evaluate_path=path)
    return NoOpFraudAdapter()


def build_payout_adapter_from_env() -> PayoutAdapter:
    base = os.getenv("CLAIMS_PAYOUT_BASE_URL")
    token = os.getenv("CLAIMS_PAYOUT_API_KEY")
    if base and token:
        advance = os.getenv("CLAIMS_PAYOUT_ADVANCE_PATH", "/claims/issue_advance")
        hold = os.getenv("CLAIMS_PAYOUT_HOLD_PATH", "/claims/place_hold")
        return HTTPPayoutAdapter(
            base_url=base,
            api_key=token,
            advance_path=advance,
            hold_path=hold,
        )
    return NoOpPayoutAdapter()


@dataclass(slots=True, frozen=True)
class ClaimIndicators:
    claim_ids: tuple[str, ...]
    claimant_ids: tuple[str, ...]
    policy_ids: tuple[str, ...]
    regions: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ClaimsExecutionPolicy:
    require_coverage_for_advance: bool = True
    require_fraud_clear_for_advance: bool = True
    auto_execute_payouts_in_dry_run: bool = False
    fraud_hold_threshold: float = 0.85
    fraud_manual_review_threshold: float = 0.55
    high_severity_threshold: float = 0.65
    max_auto_advances: int = 10
    default_advance_cents: int = 150_000
    max_parallel_tasks: int = 6

    def __post_init__(self) -> None:
        if not (0.0 <= self.fraud_manual_review_threshold <= 1.0):
            raise ValueError("fraud_manual_review_threshold must be between 0 and 1")
        if not (0.0 <= self.fraud_hold_threshold <= 1.0):
            raise ValueError("fraud_hold_threshold must be between 0 and 1")
        if self.fraud_manual_review_threshold > self.fraud_hold_threshold:
            raise ValueError("fraud_manual_review_threshold cannot exceed fraud_hold_threshold")
        if not (0.0 <= self.high_severity_threshold <= 1.0):
            raise ValueError("high_severity_threshold must be between 0 and 1")
        if self.max_auto_advances < 1:
            raise ValueError("max_auto_advances must be >= 1")
        if self.default_advance_cents < 1:
            raise ValueError("default_advance_cents must be >= 1")
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")


@dataclass(slots=True, frozen=True)
class ClaimAssessment:
    claim_id: str
    claimant_id: str | None
    policy_status: str
    severity_score: float
    fraud_score: float
    priority_score: float
    recommended_action: str
    proposed_advance_cents: int
    rationale: str


@dataclass(slots=True, frozen=True)
class ClaimsToolExecutionResult:
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
class ClaimsExecutionStats:
    policy_total: int
    policy_success: int
    fraud_total: int
    fraud_success: int
    payout_total: int
    payout_success: int
    skipped_total: int
    failed_total: int


@dataclass(slots=True, frozen=True)
class CatastropheClaimsExecutionReport:
    batch_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    indicators: ClaimIndicators
    assessments: tuple[ClaimAssessment, ...]
    action_plan: tuple[str, ...]
    policy_results: tuple[ClaimsToolExecutionResult, ...]
    fraud_results: tuple[ClaimsToolExecutionResult, ...]
    payout_actions: tuple[ClaimsToolExecutionResult, ...]
    stats: ClaimsExecutionStats
    recommendations: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "pipeline_report": self.pipeline_report.to_dict(),
            "mode": self.mode,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat(),
            "indicators": asdict(self.indicators),
            "assessments": [asdict(item) for item in self.assessments],
            "action_plan": list(self.action_plan),
            "policy_results": [asdict(item) for item in self.policy_results],
            "fraud_results": [asdict(item) for item in self.fraud_results],
            "payout_actions": [asdict(item) for item in self.payout_actions],
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
class CatastropheClaimsCommander:
    pipeline: TriProviderPipeline
    policy_adapter: PolicyAdapter
    fraud_adapter: FraudAdapter
    payout_adapter: PayoutAdapter
    execution_policy: ClaimsExecutionPolicy = field(default_factory=ClaimsExecutionPolicy)
    audit_logger: AuditLogger = field(default_factory=NoOpAuditLogger)
    idempotency_store: IdempotencyStore = field(default_factory=InMemoryIdempotencyStore)
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
    ) -> CatastropheClaimsExecutionReport:
        if mode not in {"dry", "live"}:
            raise ValueError("mode must be 'dry' or 'live'")

        started_at = datetime.now(timezone.utc)
        warnings: list[str] = []
        errors: list[str] = []

        meta = dict(metadata or {})
        batch_id = meta.get("batch_id") or self._build_batch_id(scenario, started_at)
        meta["batch_id"] = batch_id

        pipeline_mode = "live" if mode == "live" else "dry"
        pipeline_report = self.pipeline.run(
            scenario=scenario,
            evidence_documents=evidence_documents,
            mode=pipeline_mode,
            metadata=meta,
        )

        source_text = " ".join((scenario, *evidence_documents))
        indicators = self.extract_indicators(source_text)
        claim_records = self._build_claim_records(indicators, scenario=scenario, warnings=warnings)

        policy_tasks = self._build_policy_lookup_tasks(claim_records)
        policy_results = self._execute_tasks(policy_tasks)

        fraud_tasks = self._build_fraud_lookup_tasks(claim_records)
        fraud_results = self._execute_tasks(fraud_tasks)

        assessments = self._assess_claims(
            claim_records=claim_records,
            policy_results=tuple(policy_results),
            fraud_results=tuple(fraud_results),
            scenario=scenario,
            pipeline_report=pipeline_report,
        )

        payout_tasks = self._build_payout_tasks(
            batch_id=batch_id,
            mode=mode,
            assessments=assessments,
            warnings=warnings,
        )
        payout_actions = self._execute_tasks(payout_tasks)

        for row in (*policy_results, *fraud_results, *payout_actions):
            if not row.success:
                errors.append(f"{row.tool} failed for {row.target}: {row.error}")
            self._log_audit_event(
                batch_id=batch_id,
                mode=mode,
                row=row,
            )

        stats = self._build_stats(
            policy_results=tuple(policy_results),
            fraud_results=tuple(fraud_results),
            payout_actions=tuple(payout_actions),
        )

        action_plan = self._build_action_plan(
            assessments=assessments,
            mode=mode,
            payouts_executed=len(payout_actions),
        )

        recommendations = self._recommendations(
            pipeline_report=pipeline_report,
            assessments=assessments,
            stats=stats,
            warnings=warnings,
        )

        completed_at = datetime.now(timezone.utc)
        return CatastropheClaimsExecutionReport(
            batch_id=batch_id,
            pipeline_report=pipeline_report,
            mode=mode,
            started_at=started_at,
            completed_at=completed_at,
            indicators=indicators,
            assessments=tuple(assessments),
            action_plan=tuple(action_plan),
            policy_results=tuple(policy_results),
            fraud_results=tuple(fraud_results),
            payout_actions=tuple(payout_actions),
            stats=stats,
            recommendations=tuple(recommendations),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    @staticmethod
    def extract_indicators(text: str) -> ClaimIndicators:
        claim_ids = _unique_preserve(
            [_normalize_identifier(match.group(0)) for match in _CLAIM_ID_RE.finditer(text)]
        )
        claimant_ids = _unique_preserve(
            [_normalize_identifier(match.group(0)) for match in _CLAIMANT_ID_RE.finditer(text)]
        )
        policy_ids = _unique_preserve(
            [_normalize_identifier(match.group(0)) for match in _POLICY_ID_RE.finditer(text)]
        )
        regions = _unique_preserve([match.group(0) for match in _REGION_RE.finditer(text)])
        return ClaimIndicators(
            claim_ids=tuple(claim_ids),
            claimant_ids=tuple(claimant_ids),
            policy_ids=tuple(policy_ids),
            regions=tuple(regions),
        )

    @staticmethod
    def _build_batch_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"claims-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _build_claim_records(
        self,
        indicators: ClaimIndicators,
        *,
        scenario: str,
        warnings: list[str],
    ) -> list[tuple[str, str | None]]:
        claim_ids = list(indicators.claim_ids)
        claimant_ids = list(indicators.claimant_ids)

        if not claim_ids:
            fallback = f"CLM-{hashlib.sha256(scenario.encode('utf-8')).hexdigest()[:8].upper()}"
            claim_ids.append(fallback)
            warnings.append(
                "No explicit claim IDs found; generated synthetic claim id for triage continuity."
            )

        rows: list[tuple[str, str | None]] = []
        for idx, claim_id in enumerate(claim_ids):
            claimant_id = claimant_ids[idx] if idx < len(claimant_ids) else None
            rows.append((claim_id, claimant_id))
        return rows

    def _build_policy_lookup_tasks(
        self,
        claim_records: list[tuple[str, str | None]],
    ) -> list[_ExecutionTask]:
        tasks: list[_ExecutionTask] = []
        for claim_id, _ in claim_records:
            tasks.append(
                _ExecutionTask(
                    tool="policy_lookup",
                    target=claim_id,
                    request_payload={"claim_id": claim_id},
                    idempotency_key=None,
                    call=lambda claim_id=claim_id: self.policy_adapter.lookup_claim(claim_id),
                )
            )
        return tasks

    def _build_fraud_lookup_tasks(
        self,
        claim_records: list[tuple[str, str | None]],
    ) -> list[_ExecutionTask]:
        tasks: list[_ExecutionTask] = []
        for claim_id, claimant_id in claim_records:
            tasks.append(
                _ExecutionTask(
                    tool="fraud_signal_search",
                    target=claim_id,
                    request_payload={"claim_id": claim_id, "claimant_id": claimant_id},
                    idempotency_key=None,
                    call=lambda claim_id=claim_id, claimant_id=claimant_id: self.fraud_adapter.evaluate_claim(
                        claim_id,
                        claimant_id=claimant_id,
                    ),
                )
            )
        return tasks

    def _assess_claims(
        self,
        *,
        claim_records: list[tuple[str, str | None]],
        policy_results: tuple[ClaimsToolExecutionResult, ...],
        fraud_results: tuple[ClaimsToolExecutionResult, ...],
        scenario: str,
        pipeline_report: UseCaseExecutionReport,
    ) -> list[ClaimAssessment]:
        policy_by_claim = {
            row.target: row.response or {}
            for row in policy_results
            if row.success and row.status == "executed"
        }
        fraud_by_claim = {
            row.target: row.response or {}
            for row in fraud_results
            if row.success and row.status == "executed"
        }

        assessments: list[ClaimAssessment] = []
        for claim_id, claimant_id in claim_records:
            policy_response = policy_by_claim.get(claim_id, {})
            fraud_response = fraud_by_claim.get(claim_id, {})

            policy_status = self._parse_policy_status(policy_response)
            fraud_score = self._parse_fraud_score(fraud_response)
            severity_score = self._severity_score(
                claim_id=claim_id,
                scenario=scenario,
                pipeline_report=pipeline_report,
            )

            coverage_active = policy_status in {"active", "covered", "in-force", "inforce"}
            recommended_action = "manual_review"
            rationale_parts: list[str] = []

            if not coverage_active and self.execution_policy.require_coverage_for_advance:
                recommended_action = "manual_review"
                rationale_parts.append("policy not in active coverage state")
            elif (
                self.execution_policy.require_fraud_clear_for_advance
                and fraud_score >= self.execution_policy.fraud_hold_threshold
            ):
                recommended_action = "hold"
                rationale_parts.append("fraud risk exceeds hold threshold")
            elif fraud_score >= self.execution_policy.fraud_manual_review_threshold:
                recommended_action = "manual_review"
                rationale_parts.append("fraud risk requires manual investigation")
            elif severity_score >= self.execution_policy.high_severity_threshold:
                recommended_action = "advance"
                rationale_parts.append("high-severity claim with clear coverage/fraud profile")
            else:
                recommended_action = "manual_review"
                rationale_parts.append("severity below auto-advance threshold")

            coverage_limit = self._parse_money(
                policy_response,
                keys=("coverage_limit_cents", "limit_cents", "coverage_cents"),
                default=self.execution_policy.default_advance_cents * 10,
            )
            proposed_advance = min(
                int(self.execution_policy.default_advance_cents * (1.0 + severity_score)),
                max(self.execution_policy.default_advance_cents, coverage_limit // 5),
            )

            coverage_factor = 1.0 if coverage_active else 0.35
            priority_score = max(
                0.0,
                min(1.0, severity_score * coverage_factor * (1.0 - min(1.0, fraud_score))),
            )

            assessments.append(
                ClaimAssessment(
                    claim_id=claim_id,
                    claimant_id=claimant_id,
                    policy_status=policy_status,
                    severity_score=severity_score,
                    fraud_score=fraud_score,
                    priority_score=priority_score,
                    recommended_action=recommended_action,
                    proposed_advance_cents=proposed_advance,
                    rationale="; ".join(rationale_parts),
                )
            )

        assessments.sort(key=lambda row: row.priority_score, reverse=True)
        return assessments

    def _build_payout_tasks(
        self,
        *,
        batch_id: str,
        mode: str,
        assessments: list[ClaimAssessment],
        warnings: list[str],
    ) -> list[_ExecutionTask]:
        if mode == "dry" and not self.execution_policy.auto_execute_payouts_in_dry_run:
            warnings.append("Financial actions skipped in dry mode by execution policy.")
            return []

        tasks: list[_ExecutionTask] = []
        advance_count = 0
        for assessment in assessments:
            claim_id = assessment.claim_id
            if assessment.recommended_action == "advance":
                if advance_count >= self.execution_policy.max_auto_advances:
                    warnings.append(
                        "Auto-advance cap reached; remaining claims require manual payout approval."
                    )
                    continue
                advance_count += 1
                reason = "Catastrophe fast-track advance after policy/fraud triage"
                idempotency_key = f"{batch_id}:issue_advance:{claim_id}"
                tasks.append(
                    _ExecutionTask(
                        tool="issue_advance",
                        target=claim_id,
                        request_payload={
                            "claim_id": claim_id,
                            "amount_cents": assessment.proposed_advance_cents,
                            "reason": reason,
                        },
                        idempotency_key=idempotency_key,
                        call=lambda claim_id=claim_id, amount=assessment.proposed_advance_cents, reason=reason: self.payout_adapter.issue_advance(
                            claim_id,
                            amount_cents=amount,
                            reason=reason,
                        ),
                    )
                )
            elif assessment.recommended_action == "hold":
                reason = "Fraud hold threshold exceeded during catastrophe triage"
                idempotency_key = f"{batch_id}:place_hold:{claim_id}"
                tasks.append(
                    _ExecutionTask(
                        tool="place_hold",
                        target=claim_id,
                        request_payload={"claim_id": claim_id, "reason": reason},
                        idempotency_key=idempotency_key,
                        call=lambda claim_id=claim_id, reason=reason: self.payout_adapter.place_hold(
                            claim_id,
                            reason=reason,
                        ),
                    )
                )
        return tasks

    def _execute_tasks(self, tasks: list[_ExecutionTask]) -> list[ClaimsToolExecutionResult]:
        if not tasks:
            return []

        workers = min(self.execution_policy.max_parallel_tasks, len(tasks))
        if workers == 1:
            return [self._execute_task(task) for task in tasks]

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._execute_task, task) for task in tasks]
            return [future.result() for future in futures]

    def _execute_task(self, task: _ExecutionTask) -> ClaimsToolExecutionResult:
        if task.idempotency_key and self.idempotency_store.seen(task.idempotency_key):
            return ClaimsToolExecutionResult(
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
            self.idempotency_store.mark(task.idempotency_key, ttl_seconds=self.idempotency_ttl_seconds)

        return result

    def _execute_with_retry(
        self,
        *,
        tool: str,
        target: str,
        request_payload: dict[str, Any],
        call: Callable[[], dict[str, Any]],
        idempotency_key: str | None,
    ) -> ClaimsToolExecutionResult:
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
                return ClaimsToolExecutionResult(
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
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                if attempt >= attempts or not self._is_retryable_error(exc):
                    break
                retried += 1
                time.sleep(self.retry_backoff_seconds * attempt)

        latency_ms = int((time.perf_counter() - start) * 1000)
        return ClaimsToolExecutionResult(
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
        markers = (
            "timeout",
            "tempor",
            "rate limit",
            "connection reset",
            "connection aborted",
            "unavailable",
            "502",
            "503",
            "504",
            "429",
        )
        return any(marker in text for marker in markers)

    def _log_audit_event(
        self,
        *,
        batch_id: str,
        mode: str,
        row: ClaimsToolExecutionResult,
    ) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "batch_id": batch_id,
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
    def _parse_policy_status(response: dict[str, Any]) -> str:
        for key in ("policy_status", "coverage_status", "status", "coverage"):
            value = response.get(key)
            if value:
                return str(value).strip().lower()
        return "unknown"

    @staticmethod
    def _parse_money(response: dict[str, Any], *, keys: tuple[str, ...], default: int) -> int:
        for key in keys:
            value = response.get(key)
            if value is None:
                continue
            try:
                amount = int(float(value))
                if amount > 0:
                    return amount
            except Exception:  # noqa: BLE001
                continue
        return default

    @staticmethod
    def _parse_fraud_score(response: dict[str, Any]) -> float:
        for key in ("fraud_score", "risk_score", "score"):
            value = response.get(key)
            if value is None:
                continue
            try:
                score = float(value)
            except Exception:  # noqa: BLE001
                continue
            if score > 1.0:
                score = score / 100.0
            return max(0.0, min(1.0, score))
        return 0.0

    def _severity_score(
        self,
        *,
        claim_id: str,
        scenario: str,
        pipeline_report: UseCaseExecutionReport,
    ) -> float:
        corpus = " ".join(
            [
                scenario.lower(),
                pipeline_report.openai_stage.response_preview.lower(),
                pipeline_report.final_plan.lower(),
            ]
        )
        keywords = {
            "fatal": 0.35,
            "injury": 0.3,
            "displaced": 0.24,
            "hurricane": 0.2,
            "wildfire": 0.2,
            "flood": 0.18,
            "critical": 0.18,
            "life/safety": 0.25,
            "total loss": 0.2,
        }
        score = 0.25
        for key, weight in keywords.items():
            if key in corpus:
                score += weight

        if claim_id.lower() in scenario.lower():
            score += 0.05

        return max(0.0, min(1.0, score))

    @staticmethod
    def _build_stats(
        *,
        policy_results: tuple[ClaimsToolExecutionResult, ...],
        fraud_results: tuple[ClaimsToolExecutionResult, ...],
        payout_actions: tuple[ClaimsToolExecutionResult, ...],
    ) -> ClaimsExecutionStats:
        all_rows = (*policy_results, *fraud_results, *payout_actions)
        return ClaimsExecutionStats(
            policy_total=len(policy_results),
            policy_success=sum(1 for row in policy_results if row.success),
            fraud_total=len(fraud_results),
            fraud_success=sum(1 for row in fraud_results if row.success),
            payout_total=len(payout_actions),
            payout_success=sum(1 for row in payout_actions if row.success),
            skipped_total=sum(1 for row in all_rows if row.status == "skipped"),
            failed_total=sum(1 for row in all_rows if not row.success),
        )

    @staticmethod
    def _build_action_plan(
        *,
        assessments: list[ClaimAssessment],
        mode: str,
        payouts_executed: int,
    ) -> list[str]:
        advances = sum(1 for row in assessments if row.recommended_action == "advance")
        holds = sum(1 for row in assessments if row.recommended_action == "hold")
        reviews = sum(1 for row in assessments if row.recommended_action == "manual_review")

        steps = [
            "Run parallel policy and fraud checks for incoming catastrophe claims.",
            "Rank claims by severity-adjusted, fraud-aware priority score.",
            f"Decision mix: advances={advances}, holds={holds}, manual_review={reviews}.",
        ]
        if mode == "live":
            steps.append(f"Executed financial actions: {payouts_executed} payout workflow calls.")
        else:
            steps.append(
                "Dry mode completed: financial actions are policy-gated unless explicitly enabled."
            )
        steps.append("Capture decisions and rationales for adjuster QA and regulatory traceability.")
        return steps

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        assessments: list[ClaimAssessment],
        stats: ClaimsExecutionStats,
        warnings: list[str],
    ) -> list[str]:
        recommendations: list[str] = []
        recommendations.append(
            f"Policy lookups success rate: {stats.policy_success}/{stats.policy_total}; "
            f"fraud checks success rate: {stats.fraud_success}/{stats.fraud_total}."
        )
        if stats.payout_total:
            recommendations.append(
                f"Payout workflow actions completed: {stats.payout_success}/{stats.payout_total}."
            )
        if stats.skipped_total:
            recommendations.append(
                f"Skipped actions due to policy/idempotency controls: {stats.skipped_total}."
            )

        top = assessments[:3]
        if top:
            ranked = ", ".join(
                f"{row.claim_id}:{row.recommended_action}:{row.priority_score:.2f}" for row in top
            )
            recommendations.append(f"Top triage claims: {ranked}.")

        if pipeline_report.ranked_actions:
            recommendations.append(
                f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}"
            )
        else:
            recommendations.append("Primary tri-provider action unavailable; escalate for manual queue strategy.")

        if warnings:
            recommendations.append("Review warnings and confirm policy overrides before production payout calls.")

        recommendations.append("Post-cat event: backtest fraud thresholds against false-positive leakage.")
        return recommendations
