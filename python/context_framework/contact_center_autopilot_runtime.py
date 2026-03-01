from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Protocol
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

from .soc_runtime import (
    AuditLogger,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    NoOpAuditLogger,
)
from .tri_provider_pipeline import TriProviderPipeline, UseCaseExecutionReport

_ID_SUFFIX_RE = r"(?:[-_][A-Za-z0-9]+|[0-9]{2,}[A-Za-z0-9]*)(?:[-_][A-Za-z0-9]+)*"
_TICKET_RE = re.compile(
    rf"\b(?:TICKET|CASE|THREAD|CONVERSATION){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_CUSTOMER_RE = re.compile(
    rf"\b(?:CUSTOMER|ACCOUNT|ACCT|USER){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_QUEUE_RE = re.compile(
    rf"\b(?:QUEUE|SKILL|CHANNEL|LANG){_ID_SUFFIX_RE}\b",
    re.IGNORECASE,
)
_WAIT_MINUTES_RE = re.compile(r"\b(\d{1,4})\s*minutes?\b", re.IGNORECASE)
_RECONTACT_COUNT_RE = re.compile(
    r"\b(\d{1,3})\s*(?:recontacts?|callbacks?|contacts?)\b",
    re.IGNORECASE,
)
_CSAT_SCORE_RE = re.compile(r"\b(?:csat|nps)\s*[:=]?\s*(\d{1,3})\b", re.IGNORECASE)

_RISK_HINT_KEYWORDS = (
    "billing dispute",
    "fraud claim",
    "regulatory complaint",
    "legal threat",
    "cancellation threat",
    "data deletion request",
    "chargeback",
)
_RISK_HINT_RE = re.compile(
    "|".join(re.escape(keyword) for keyword in _RISK_HINT_KEYWORDS), re.IGNORECASE
)
_SEVERE_SENTIMENT_RE = re.compile(
    r"(?:angry|frustrated|escalate now|cancel account|churn|formal complaint)",
    re.IGNORECASE,
)
_VIP_RE = re.compile(
    r"(?:vip|enterprise tier|strategic account|high value customer)",
    re.IGNORECASE,
)


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


def _normalize(value: str) -> str:
    return value.strip().replace("_", "-").upper()


class CustomerProfileAdapter(Protocol):
    def lookup_customer(self, customer_id: str) -> dict[str, Any]: ...


class PolicyGuardrailAdapter(Protocol):
    def lookup_ticket(self, ticket_id: str) -> dict[str, Any]: ...


class ContactResolutionActionAdapter(Protocol):
    def create_supervisor_escalation(self, ticket_id: str, *, reason: str) -> dict[str, Any]: ...

    def draft_compliant_response(
        self,
        ticket_id: str,
        *,
        response_template: str,
        reason: str,
    ) -> dict[str, Any]: ...

    def issue_compensation_offer(self, ticket_id: str, *, reason: str) -> dict[str, Any]: ...

    def schedule_priority_callback(self, customer_id: str, *, reason: str) -> dict[str, Any]: ...

    def open_quality_review(self, ticket_id: str, *, reason: str) -> dict[str, Any]: ...


class NoOpCustomerProfileAdapter:
    def lookup_customer(self, customer_id: str) -> dict[str, Any]:
        return {
            "customer_id": customer_id,
            "churn_risk": 0.42,
            "fraud_risk": 0.22,
            "lifetime_value_tier": 0.56,
            "source": "noop",
        }


class NoOpPolicyGuardrailAdapter:
    def lookup_ticket(self, ticket_id: str) -> dict[str, Any]:
        return {
            "ticket_id": ticket_id,
            "compliance_risk": 0.38,
            "autopilot_allowed": True,
            "supervisor_required": False,
            "refund_flexibility": 0.52,
            "recommended_response_template": "Acknowledge issue, restate policy, and offer next-best compliant option.",
            "source": "noop",
        }


class NoOpContactResolutionActionAdapter:
    def create_supervisor_escalation(self, ticket_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "ticket_id": ticket_id,
            "action": "create_supervisor_escalation",
            "reason": reason,
            "status": "noop",
        }

    def draft_compliant_response(
        self,
        ticket_id: str,
        *,
        response_template: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "ticket_id": ticket_id,
            "action": "draft_compliant_response",
            "response_template": response_template,
            "reason": reason,
            "status": "noop",
        }

    def issue_compensation_offer(self, ticket_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "ticket_id": ticket_id,
            "action": "issue_compensation_offer",
            "reason": reason,
            "status": "noop",
        }

    def schedule_priority_callback(self, customer_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "customer_id": customer_id,
            "action": "schedule_priority_callback",
            "reason": reason,
            "status": "noop",
        }

    def open_quality_review(self, ticket_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "ticket_id": ticket_id,
            "action": "open_quality_review",
            "reason": reason,
            "status": "noop",
        }


@dataclass(slots=True)
class InMemoryCustomerProfileAdapter:
    customers: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_customer(self, customer_id: str) -> dict[str, Any]:
        customer = _normalize(customer_id)
        payload = self.customers.get(customer, {})
        churn_risk = float(payload.get("churn_risk", 0.44))
        fraud_risk = float(payload.get("fraud_risk", 0.23))
        lifetime_tier = float(payload.get("lifetime_value_tier", 0.58))
        return {
            "customer_id": customer,
            "churn_risk": max(0.0, min(1.0, churn_risk)),
            "fraud_risk": max(0.0, min(1.0, fraud_risk)),
            "lifetime_value_tier": max(0.0, min(1.0, lifetime_tier)),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryPolicyGuardrailAdapter:
    tickets: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_ticket(self, ticket_id: str) -> dict[str, Any]:
        ticket = _normalize(ticket_id)
        payload = self.tickets.get(ticket, {})
        compliance_risk = float(payload.get("compliance_risk", 0.40))
        autopilot_allowed = bool(payload.get("autopilot_allowed", True))
        supervisor_required = bool(payload.get("supervisor_required", False))
        refund_flexibility = float(payload.get("refund_flexibility", 0.50))
        response_template = str(
            payload.get(
                "recommended_response_template",
                "Acknowledge issue, explain policy limits, and provide compliant next steps.",
            )
        )
        return {
            "ticket_id": ticket,
            "compliance_risk": max(0.0, min(1.0, compliance_risk)),
            "autopilot_allowed": autopilot_allowed,
            "supervisor_required": supervisor_required,
            "refund_flexibility": max(0.0, min(1.0, refund_flexibility)),
            "recommended_response_template": response_template,
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryContactResolutionActionAdapter:
    supervisor_escalations: set[str] = field(default_factory=set)
    drafted_responses: set[str] = field(default_factory=set)
    compensation_offers: set[str] = field(default_factory=set)
    callbacks: set[str] = field(default_factory=set)
    quality_reviews: set[str] = field(default_factory=set)

    def create_supervisor_escalation(self, ticket_id: str, *, reason: str) -> dict[str, Any]:
        ticket = _normalize(ticket_id)
        self.supervisor_escalations.add(ticket)
        return {
            "ticket_id": ticket,
            "action": "create_supervisor_escalation",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def draft_compliant_response(
        self,
        ticket_id: str,
        *,
        response_template: str,
        reason: str,
    ) -> dict[str, Any]:
        ticket = _normalize(ticket_id)
        self.drafted_responses.add(ticket)
        return {
            "ticket_id": ticket,
            "action": "draft_compliant_response",
            "response_template": response_template,
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def issue_compensation_offer(self, ticket_id: str, *, reason: str) -> dict[str, Any]:
        ticket = _normalize(ticket_id)
        self.compensation_offers.add(ticket)
        return {
            "ticket_id": ticket,
            "action": "issue_compensation_offer",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def schedule_priority_callback(self, customer_id: str, *, reason: str) -> dict[str, Any]:
        customer = _normalize(customer_id)
        self.callbacks.add(customer)
        return {
            "customer_id": customer,
            "action": "schedule_priority_callback",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def open_quality_review(self, ticket_id: str, *, reason: str) -> dict[str, Any]:
        ticket = _normalize(ticket_id)
        self.quality_reviews.add(ticket)
        return {
            "ticket_id": ticket,
            "action": "open_quality_review",
            "reason": reason,
            "updated": True,
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
class HTTPCustomerProfileAdapter(_HTTPJSONAdapterBase):
    lookup_path: str = "/contact/customer_profile"

    def lookup_customer(self, customer_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"customer_id": customer_id})


@dataclass(slots=True)
class HTTPPolicyGuardrailAdapter(_HTTPJSONAdapterBase):
    lookup_path: str = "/contact/policy_guardrail"

    def lookup_ticket(self, ticket_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"ticket_id": ticket_id})


@dataclass(slots=True)
class HTTPContactResolutionActionAdapter(_HTTPJSONAdapterBase):
    escalation_path: str = "/contact/create_supervisor_escalation"
    response_path: str = "/contact/draft_compliant_response"
    compensation_path: str = "/contact/issue_compensation_offer"
    callback_path: str = "/contact/schedule_priority_callback"
    quality_review_path: str = "/contact/open_quality_review"

    def create_supervisor_escalation(self, ticket_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.escalation_path, {"ticket_id": ticket_id, "reason": reason})

    def draft_compliant_response(
        self,
        ticket_id: str,
        *,
        response_template: str,
        reason: str,
    ) -> dict[str, Any]:
        return self._post(
            self.response_path,
            {
                "ticket_id": ticket_id,
                "response_template": response_template,
                "reason": reason,
            },
        )

    def issue_compensation_offer(self, ticket_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.compensation_path, {"ticket_id": ticket_id, "reason": reason})

    def schedule_priority_callback(self, customer_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.callback_path, {"customer_id": customer_id, "reason": reason})

    def open_quality_review(self, ticket_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.quality_review_path, {"ticket_id": ticket_id, "reason": reason})


def build_customer_profile_adapter_from_env() -> CustomerProfileAdapter:
    base = os.getenv("CONTACT_PROFILE_BASE_URL")
    token = os.getenv("CONTACT_PROFILE_API_KEY")
    if base and token:
        path = os.getenv("CONTACT_PROFILE_LOOKUP_PATH", "/contact/customer_profile")
        return HTTPCustomerProfileAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpCustomerProfileAdapter()


def build_policy_guardrail_adapter_from_env() -> PolicyGuardrailAdapter:
    base = os.getenv("CONTACT_POLICY_BASE_URL")
    token = os.getenv("CONTACT_POLICY_API_KEY")
    if base and token:
        path = os.getenv("CONTACT_POLICY_LOOKUP_PATH", "/contact/policy_guardrail")
        return HTTPPolicyGuardrailAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpPolicyGuardrailAdapter()


def build_contact_resolution_action_adapter_from_env() -> ContactResolutionActionAdapter:
    base = os.getenv("CONTACT_ACTION_BASE_URL")
    token = os.getenv("CONTACT_ACTION_API_KEY")
    if base and token:
        return HTTPContactResolutionActionAdapter(
            base_url=base,
            api_key=token,
            escalation_path=os.getenv(
                "CONTACT_ACTION_ESCALATION_PATH",
                "/contact/create_supervisor_escalation",
            ),
            response_path=os.getenv(
                "CONTACT_ACTION_RESPONSE_PATH",
                "/contact/draft_compliant_response",
            ),
            compensation_path=os.getenv(
                "CONTACT_ACTION_COMPENSATION_PATH",
                "/contact/issue_compensation_offer",
            ),
            callback_path=os.getenv(
                "CONTACT_ACTION_CALLBACK_PATH",
                "/contact/schedule_priority_callback",
            ),
            quality_review_path=os.getenv(
                "CONTACT_ACTION_QUALITY_REVIEW_PATH",
                "/contact/open_quality_review",
            ),
        )
    return NoOpContactResolutionActionAdapter()


ContactCenterRoute = Literal[
    "immediate_supervisor_intervention",
    "supervised_autopilot_resolution",
    "autopilot_resolution",
    "monitor",
]


@dataclass(slots=True, frozen=True)
class ContactCenterSignal:
    ticket_id: str
    customer_id: str
    queue_id: str
    issue_hint: str | None
    observed_wait_minutes: int | None
    observed_recontact_count: int | None
    observed_csat_score: int | None
    severe_sentiment_indicator: bool
    vip_indicator: bool


@dataclass(slots=True, frozen=True)
class ContactCenterDecision:
    ticket_id: str
    customer_id: str
    queue_id: str
    route: ContactCenterRoute
    priority: str
    confidence: float
    risk_score: float
    churn_risk: float
    fraud_risk: float
    lifetime_value_tier: float
    compliance_risk: float
    refund_flexibility: float
    autopilot_allowed: bool
    supervisor_required: bool
    wait_minutes: int
    recontact_count: int
    csat_score: int
    response_template: str
    rationale: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ContactCenterActionResult:
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
class ContactCenterExecutionPolicy:
    execute_actions_in_dry_run: bool = False
    max_parallel_tasks: int = 6
    max_tickets_to_process: int = 20
    immediate_risk_threshold: float = 0.82
    supervised_risk_threshold: float = 0.56
    autopilot_risk_threshold: float = 0.32
    high_wait_minutes_threshold: int = 45
    high_recontact_threshold: int = 3
    allow_auto_escalation: bool = True
    allow_auto_response: bool = True
    allow_auto_compensation: bool = True
    allow_auto_callback: bool = True
    allow_auto_quality_review: bool = True

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if self.max_tickets_to_process < 1:
            raise ValueError("max_tickets_to_process must be >= 1")
        if self.high_wait_minutes_threshold < 1:
            raise ValueError("high_wait_minutes_threshold must be >= 1")
        if self.high_recontact_threshold < 1:
            raise ValueError("high_recontact_threshold must be >= 1")
        for name, value in (
            ("immediate_risk_threshold", self.immediate_risk_threshold),
            ("supervised_risk_threshold", self.supervised_risk_threshold),
            ("autopilot_risk_threshold", self.autopilot_risk_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(slots=True, frozen=True)
class ContactCenterExecutionStats:
    tickets_total: int
    enrichment_total: int
    enrichment_success: int
    actions_total: int
    actions_success: int
    actions_skipped: int
    actions_failed: int
    immediate_count: int
    supervised_count: int
    autopilot_count: int
    monitor_count: int


@dataclass(slots=True, frozen=True)
class ContactCenterExecutionReport:
    batch_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    signals: tuple[ContactCenterSignal, ...]
    enrichments: tuple[ContactCenterActionResult, ...]
    decisions: tuple[ContactCenterDecision, ...]
    actions: tuple[ContactCenterActionResult, ...]
    stats: ContactCenterExecutionStats
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
            "signals": [asdict(item) for item in self.signals],
            "enrichments": [asdict(item) for item in self.enrichments],
            "decisions": [asdict(item) for item in self.decisions],
            "actions": [asdict(item) for item in self.actions],
            "stats": asdict(self.stats),
            "recommendations": list(self.recommendations),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass(slots=True, frozen=True)
class _ExecutionTask:
    integration: str
    operation: str
    target: str
    request_payload: dict[str, Any]
    idempotency_key: str | None
    call: Callable[[], dict[str, Any]]


@dataclass(slots=True)
class ContactCenterAutopilotCommander:
    pipeline: TriProviderPipeline
    customer_profile_adapter: CustomerProfileAdapter
    policy_guardrail_adapter: PolicyGuardrailAdapter
    action_adapter: ContactResolutionActionAdapter
    execution_policy: ContactCenterExecutionPolicy = field(
        default_factory=ContactCenterExecutionPolicy
    )
    idempotency_store: IdempotencyStore = field(default_factory=InMemoryIdempotencyStore)
    audit_logger: AuditLogger = field(default_factory=NoOpAuditLogger)
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
    ) -> ContactCenterExecutionReport:
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
        signals = self.extract_signals(
            source_text,
            max_signals=self.execution_policy.max_tickets_to_process,
        )

        enrichments = self._run_enrichment(signals)
        decisions = self._build_decisions(signals, enrichments)

        execute_actions = True
        if mode == "dry" and not self.execution_policy.execute_actions_in_dry_run:
            execute_actions = False
            warnings.append("Contact-center actions skipped in dry mode by execution policy.")

        actions = self._run_actions(
            batch_id=batch_id,
            decisions=decisions,
            execute_actions=execute_actions,
        )

        for row in (*enrichments, *actions):
            if not row.success:
                errors.append(
                    f"{row.integration}.{row.operation} failed for {row.target}: {row.error}"
                )
            self._log_audit_event(batch_id=batch_id, mode=mode, row=row)

        stats = self._build_stats(
            signals=signals,
            enrichments=enrichments,
            decisions=decisions,
            actions=actions,
        )

        recommendations = self._recommendations(
            pipeline_report=pipeline_report,
            stats=stats,
            decisions=decisions,
            errors=errors,
        )

        completed_at = datetime.now(timezone.utc)
        return ContactCenterExecutionReport(
            batch_id=batch_id,
            pipeline_report=pipeline_report,
            mode=mode,
            started_at=started_at,
            completed_at=completed_at,
            signals=tuple(signals),
            enrichments=tuple(enrichments),
            decisions=tuple(decisions),
            actions=tuple(actions),
            stats=stats,
            recommendations=tuple(recommendations),
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    @staticmethod
    def extract_signals(text: str, *, max_signals: int = 20) -> list[ContactCenterSignal]:
        ticket_matches = list(_TICKET_RE.finditer(text))
        customers = [_normalize(m.group(0)) for m in _CUSTOMER_RE.finditer(text)]
        queues = [_normalize(m.group(0)) for m in _QUEUE_RE.finditer(text)]
        wait_values = [int(m.group(1)) for m in _WAIT_MINUTES_RE.finditer(text)]
        recontact_values = [int(m.group(1)) for m in _RECONTACT_COUNT_RE.finditer(text)]
        csat_values = [int(m.group(1)) for m in _CSAT_SCORE_RE.finditer(text)]
        issue_hints = [m.group(0).lower() for m in _RISK_HINT_RE.finditer(text)]
        has_severe_sentiment = bool(_SEVERE_SENTIMENT_RE.search(text))
        has_vip = bool(_VIP_RE.search(text))

        def _pick(values: list[str], index: int, default: str) -> str:
            if not values:
                return default
            if index < len(values):
                return values[index]
            return values[-1]

        def _pick_int(values: list[int], index: int) -> int | None:
            if not values:
                return None
            if index < len(values):
                return values[index]
            return values[-1]

        if not ticket_matches:
            ticket_id = f"TICKET-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8].upper()}"
            return [
                ContactCenterSignal(
                    ticket_id=ticket_id,
                    customer_id=_pick(customers, 0, "CUSTOMER-AUTO-01"),
                    queue_id=_pick(queues, 0, "QUEUE-AUTO-01"),
                    issue_hint=_pick(issue_hints, 0, "") or None,
                    observed_wait_minutes=_pick_int(wait_values, 0),
                    observed_recontact_count=_pick_int(recontact_values, 0),
                    observed_csat_score=_pick_int(csat_values, 0),
                    severe_sentiment_indicator=has_severe_sentiment,
                    vip_indicator=has_vip,
                )
            ]

        rows: list[ContactCenterSignal] = []
        seen_tickets: set[str] = set()
        for idx, match in enumerate(ticket_matches):
            if len(rows) >= max_signals:
                break

            ticket_id = _normalize(match.group(0))
            key = ticket_id.lower()
            if key in seen_tickets:
                continue
            seen_tickets.add(key)

            segment_index = len(rows)
            start = match.start()
            end = ticket_matches[idx + 1].start() if idx + 1 < len(ticket_matches) else len(text)
            segment = text[start:end]

            customer_match = _CUSTOMER_RE.search(segment)
            queue_match = _QUEUE_RE.search(segment)
            wait_match = _WAIT_MINUTES_RE.search(segment)
            recontact_match = _RECONTACT_COUNT_RE.search(segment)
            csat_match = _CSAT_SCORE_RE.search(segment)
            issue_hint_match = _RISK_HINT_RE.search(segment)
            severe_sentiment_match = _SEVERE_SENTIMENT_RE.search(segment)
            vip_match = _VIP_RE.search(segment)

            rows.append(
                ContactCenterSignal(
                    ticket_id=ticket_id,
                    customer_id=_normalize(customer_match.group(0))
                    if customer_match
                    else _pick(customers, segment_index, "CUSTOMER-AUTO-01"),
                    queue_id=_normalize(queue_match.group(0))
                    if queue_match
                    else _pick(queues, segment_index, "QUEUE-AUTO-01"),
                    issue_hint=issue_hint_match.group(0).lower()
                    if issue_hint_match
                    else (_pick(issue_hints, segment_index, "") or None),
                    observed_wait_minutes=int(wait_match.group(1))
                    if wait_match
                    else _pick_int(wait_values, segment_index),
                    observed_recontact_count=int(recontact_match.group(1))
                    if recontact_match
                    else _pick_int(recontact_values, segment_index),
                    observed_csat_score=int(csat_match.group(1))
                    if csat_match
                    else _pick_int(csat_values, segment_index),
                    severe_sentiment_indicator=bool(severe_sentiment_match) or has_severe_sentiment,
                    vip_indicator=bool(vip_match) or has_vip,
                )
            )

        return rows

    @staticmethod
    def _build_batch_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"contact-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _run_enrichment(
        self, signals: list[ContactCenterSignal]
    ) -> list[ContactCenterActionResult]:
        tasks: list[_ExecutionTask] = []

        customer_ids = _unique_preserve([signal.customer_id for signal in signals])
        for customer_id in customer_ids:
            tasks.append(
                _ExecutionTask(
                    integration="customer_profile",
                    operation="lookup_customer",
                    target=customer_id,
                    request_payload={"customer_id": customer_id},
                    idempotency_key=None,
                    call=lambda customer_id=customer_id: (
                        self.customer_profile_adapter.lookup_customer(customer_id)
                    ),
                )
            )

        ticket_ids = _unique_preserve([signal.ticket_id for signal in signals])
        for ticket_id in ticket_ids:
            tasks.append(
                _ExecutionTask(
                    integration="policy_guardrail",
                    operation="lookup_ticket",
                    target=ticket_id,
                    request_payload={"ticket_id": ticket_id},
                    idempotency_key=None,
                    call=lambda ticket_id=ticket_id: self.policy_guardrail_adapter.lookup_ticket(
                        ticket_id
                    ),
                )
            )

        return self._execute_tasks(tasks)

    def _build_decisions(
        self,
        signals: list[ContactCenterSignal],
        enrichments: list[ContactCenterActionResult],
    ) -> list[ContactCenterDecision]:
        profile_data: dict[str, dict[str, Any]] = {}
        policy_data: dict[str, dict[str, Any]] = {}

        for row in enrichments:
            if not row.success or row.status != "executed":
                continue
            if row.integration == "customer_profile":
                profile_data[row.target] = row.response or {}
            elif row.integration == "policy_guardrail":
                policy_data[row.target] = row.response or {}

        decisions: list[ContactCenterDecision] = []
        for signal in signals:
            profile = profile_data.get(signal.customer_id, {})
            policy = policy_data.get(signal.ticket_id, {})

            churn_risk = self._as_float(profile, keys=("churn_risk",), default=0.44)
            fraud_risk = self._as_float(profile, keys=("fraud_risk",), default=0.23)
            lifetime_tier = self._as_float(profile, keys=("lifetime_value_tier",), default=0.58)
            compliance_risk = self._as_float(policy, keys=("compliance_risk",), default=0.40)
            refund_flexibility = self._as_float(policy, keys=("refund_flexibility",), default=0.50)
            autopilot_allowed = bool(policy.get("autopilot_allowed", True))
            supervisor_required = bool(policy.get("supervisor_required", False))
            response_template = str(
                policy.get(
                    "recommended_response_template",
                    "Acknowledge issue, explain policy, and provide compliant next steps.",
                )
            )

            wait_minutes = signal.observed_wait_minutes or 12
            recontact_count = signal.observed_recontact_count or 1
            csat_score = (
                signal.observed_csat_score if signal.observed_csat_score is not None else 72
            )

            wait_risk = min(1.0, wait_minutes / 90.0)
            recontact_risk = min(1.0, recontact_count / 6.0)
            csat_risk = 0.0 if csat_score >= 85 else min(1.0, max(0, 85 - csat_score) / 85.0)
            hint_risk = 0.0
            if signal.issue_hint in {
                "billing dispute",
                "fraud claim",
                "regulatory complaint",
                "legal threat",
                "chargeback",
            }:
                hint_risk = 0.08

            risk_score = min(
                1.0,
                churn_risk * 0.22
                + compliance_risk * 0.21
                + fraud_risk * 0.12
                + (1.0 - lifetime_tier) * 0.08
                + wait_risk * 0.12
                + recontact_risk * 0.08
                + csat_risk * 0.07
                + hint_risk
                + (0.10 if signal.severe_sentiment_indicator else 0.0)
                + (0.06 if signal.vip_indicator else 0.0)
                + (0.10 if not autopilot_allowed else 0.0)
                + (0.08 if supervisor_required else 0.0),
            )

            route: ContactCenterRoute = "monitor"
            rationale: list[str] = []
            if (
                risk_score >= self.execution_policy.immediate_risk_threshold
                or supervisor_required
                or (signal.severe_sentiment_indicator and compliance_risk >= 0.60)
            ):
                route = "immediate_supervisor_intervention"
                rationale.append("Case risk requires immediate supervisor intervention.")
            elif (
                risk_score >= self.execution_policy.supervised_risk_threshold
                or not autopilot_allowed
                or wait_minutes >= self.execution_policy.high_wait_minutes_threshold
                or recontact_count >= self.execution_policy.high_recontact_threshold
            ):
                route = "supervised_autopilot_resolution"
                rationale.append("Case risk supports supervised autopilot resolution flow.")
            elif risk_score >= self.execution_policy.autopilot_risk_threshold:
                route = "autopilot_resolution"
                rationale.append("Case risk supports autonomous compliant response handling.")
            else:
                rationale.append(
                    "Current case risk supports monitoring and queue-level optimization."
                )

            if not profile:
                rationale.append("Customer-profile enrichment missing; confidence reduced.")
            if not policy:
                rationale.append("Policy-guardrail enrichment missing; confidence reduced.")

            priority = self._priority_for(route)
            confidence = self._confidence_for(
                route=route,
                profile_enriched=bool(profile),
                policy_enriched=bool(policy),
            )

            decisions.append(
                ContactCenterDecision(
                    ticket_id=signal.ticket_id,
                    customer_id=signal.customer_id,
                    queue_id=signal.queue_id,
                    route=route,
                    priority=priority,
                    confidence=confidence,
                    risk_score=risk_score,
                    churn_risk=churn_risk,
                    fraud_risk=fraud_risk,
                    lifetime_value_tier=lifetime_tier,
                    compliance_risk=compliance_risk,
                    refund_flexibility=refund_flexibility,
                    autopilot_allowed=autopilot_allowed,
                    supervisor_required=supervisor_required,
                    wait_minutes=max(0, wait_minutes),
                    recontact_count=max(0, recontact_count),
                    csat_score=max(0, min(100, csat_score)),
                    response_template=response_template,
                    rationale=tuple(rationale),
                )
            )

        decisions.sort(
            key=lambda row: (
                row.route
                in {"immediate_supervisor_intervention", "supervised_autopilot_resolution"},
                row.priority == "urgent",
                row.risk_score,
            ),
            reverse=True,
        )
        return decisions

    def _run_actions(
        self,
        *,
        batch_id: str,
        decisions: list[ContactCenterDecision],
        execute_actions: bool,
    ) -> list[ContactCenterActionResult]:
        tasks: list[_ExecutionTask] = []
        skipped: list[ContactCenterActionResult] = []

        for row in decisions:
            reason = "; ".join(row.rationale)
            if not execute_actions:
                skipped.append(
                    ContactCenterActionResult(
                        integration="contact_actions",
                        operation=row.route,
                        target=row.ticket_id,
                        success=True,
                        latency_ms=0,
                        request={"ticket_id": row.ticket_id, "route": row.route},
                        status="skipped",
                        attempts=0,
                        notes=("action execution disabled by runtime policy",),
                    )
                )
                continue

            if row.route == "monitor":
                skipped.append(
                    ContactCenterActionResult(
                        integration="contact_actions",
                        operation="monitor",
                        target=row.ticket_id,
                        success=True,
                        latency_ms=0,
                        request={"ticket_id": row.ticket_id, "route": "monitor"},
                        status="skipped",
                        attempts=0,
                        notes=("monitor route requires no external action call",),
                    )
                )
                continue

            if row.route in {
                "immediate_supervisor_intervention",
                "supervised_autopilot_resolution",
            }:
                if self.execution_policy.allow_auto_escalation:
                    key = f"{batch_id}:escalation:{row.ticket_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contact_actions",
                            operation="create_supervisor_escalation",
                            target=row.ticket_id,
                            request_payload={"ticket_id": row.ticket_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.create_supervisor_escalation(
                                    row.ticket_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContactCenterActionResult(
                            integration="contact_actions",
                            operation="create_supervisor_escalation",
                            target=row.ticket_id,
                            success=True,
                            latency_ms=0,
                            request={"ticket_id": row.ticket_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto supervisor escalation disabled by policy",),
                        )
                    )

            if row.route in {
                "immediate_supervisor_intervention",
                "supervised_autopilot_resolution",
                "autopilot_resolution",
            }:
                if self.execution_policy.allow_auto_response:
                    key = f"{batch_id}:response:{row.ticket_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contact_actions",
                            operation="draft_compliant_response",
                            target=row.ticket_id,
                            request_payload={
                                "ticket_id": row.ticket_id,
                                "response_template": row.response_template,
                                "reason": reason,
                            },
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.draft_compliant_response(
                                    row.ticket_id,
                                    response_template=row.response_template,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContactCenterActionResult(
                            integration="contact_actions",
                            operation="draft_compliant_response",
                            target=row.ticket_id,
                            success=True,
                            latency_ms=0,
                            request={"ticket_id": row.ticket_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto response drafting disabled by policy",),
                        )
                    )

            if row.route in {
                "immediate_supervisor_intervention",
                "supervised_autopilot_resolution",
            }:
                if self.execution_policy.allow_auto_callback:
                    key = f"{batch_id}:callback:{row.customer_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contact_actions",
                            operation="schedule_priority_callback",
                            target=row.customer_id,
                            request_payload={"customer_id": row.customer_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.schedule_priority_callback(
                                    row.customer_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContactCenterActionResult(
                            integration="contact_actions",
                            operation="schedule_priority_callback",
                            target=row.customer_id,
                            success=True,
                            latency_ms=0,
                            request={"customer_id": row.customer_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto callback scheduling disabled by policy",),
                        )
                    )

            if row.route in {"immediate_supervisor_intervention", "autopilot_resolution"} and (
                row.churn_risk >= 0.65 or row.csat_score <= 50
            ):
                if self.execution_policy.allow_auto_compensation:
                    key = f"{batch_id}:comp:{row.ticket_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contact_actions",
                            operation="issue_compensation_offer",
                            target=row.ticket_id,
                            request_payload={"ticket_id": row.ticket_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.issue_compensation_offer(
                                    row.ticket_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContactCenterActionResult(
                            integration="contact_actions",
                            operation="issue_compensation_offer",
                            target=row.ticket_id,
                            success=True,
                            latency_ms=0,
                            request={"ticket_id": row.ticket_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto compensation offers disabled by policy",),
                        )
                    )

            if row.route == "immediate_supervisor_intervention" and row.compliance_risk >= 0.60:
                if self.execution_policy.allow_auto_quality_review:
                    key = f"{batch_id}:quality:{row.ticket_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="contact_actions",
                            operation="open_quality_review",
                            target=row.ticket_id,
                            request_payload={"ticket_id": row.ticket_id, "reason": reason},
                            idempotency_key=key,
                            call=lambda row=row, reason=reason: (
                                self.action_adapter.open_quality_review(
                                    row.ticket_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        ContactCenterActionResult(
                            integration="contact_actions",
                            operation="open_quality_review",
                            target=row.ticket_id,
                            success=True,
                            latency_ms=0,
                            request={"ticket_id": row.ticket_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto quality review disabled by policy",),
                        )
                    )

        executed = self._execute_tasks(tasks)
        return [*skipped, *executed]

    def _execute_tasks(self, tasks: list[_ExecutionTask]) -> list[ContactCenterActionResult]:
        if not tasks:
            return []

        workers = min(self.execution_policy.max_parallel_tasks, len(tasks))
        if workers == 1:
            return [self._execute_task(task) for task in tasks]

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._execute_task, task) for task in tasks]
            return [future.result() for future in futures]

    def _execute_task(self, task: _ExecutionTask) -> ContactCenterActionResult:
        if task.idempotency_key and self.idempotency_store.seen(task.idempotency_key):
            return ContactCenterActionResult(
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

        result = self._execute_with_retry(
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

    def _execute_with_retry(
        self,
        *,
        integration: str,
        operation: str,
        target: str,
        request_payload: dict[str, Any],
        call: Callable[[], dict[str, Any]],
        idempotency_key: str | None,
    ) -> ContactCenterActionResult:
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
                return ContactCenterActionResult(
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
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                if attempt >= attempts or not self._is_retryable_error(exc):
                    break
                retried += 1
                time.sleep(self.retry_backoff_seconds * attempt)

        latency_ms = int((time.perf_counter() - start) * 1000)
        return ContactCenterActionResult(
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
        row: ContactCenterActionResult,
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

    @staticmethod
    def _as_float(
        data: dict[str, Any],
        *,
        keys: tuple[str, ...],
        default: float,
        cap_1: bool = True,
    ) -> float:
        for key in keys:
            value = data.get(key)
            if value is None:
                continue
            try:
                out = float(value)
            except Exception:  # noqa: BLE001
                continue
            if cap_1 and out > 1.0:
                out = out / 100.0
            if cap_1:
                out = max(0.0, min(1.0, out))
            return out
        return default

    @staticmethod
    def _priority_for(route: ContactCenterRoute) -> str:
        if route == "immediate_supervisor_intervention":
            return "urgent"
        if route == "supervised_autopilot_resolution":
            return "high"
        if route == "autopilot_resolution":
            return "normal"
        return "low"

    @staticmethod
    def _confidence_for(
        *,
        route: ContactCenterRoute,
        profile_enriched: bool,
        policy_enriched: bool,
    ) -> float:
        base = {
            "immediate_supervisor_intervention": 0.90,
            "supervised_autopilot_resolution": 0.84,
            "autopilot_resolution": 0.76,
            "monitor": 0.68,
        }[route]
        if not profile_enriched:
            base -= 0.15
        if not policy_enriched:
            base -= 0.15
        return round(min(0.99, max(0.05, base)), 3)

    @staticmethod
    def _build_stats(
        *,
        signals: list[ContactCenterSignal],
        enrichments: list[ContactCenterActionResult],
        decisions: list[ContactCenterDecision],
        actions: list[ContactCenterActionResult],
    ) -> ContactCenterExecutionStats:
        route_counts: dict[ContactCenterRoute, int] = defaultdict(int)
        for row in decisions:
            route_counts[row.route] += 1

        actions_success = sum(1 for row in actions if row.success and row.status == "executed")
        actions_skipped = sum(1 for row in actions if row.status == "skipped")
        actions_failed = sum(1 for row in actions if not row.success)

        return ContactCenterExecutionStats(
            tickets_total=len(signals),
            enrichment_total=len(enrichments),
            enrichment_success=sum(1 for row in enrichments if row.success),
            actions_total=len(actions),
            actions_success=actions_success,
            actions_skipped=actions_skipped,
            actions_failed=actions_failed,
            immediate_count=route_counts["immediate_supervisor_intervention"],
            supervised_count=route_counts["supervised_autopilot_resolution"],
            autopilot_count=route_counts["autopilot_resolution"],
            monitor_count=route_counts["monitor"],
        )

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        stats: ContactCenterExecutionStats,
        decisions: list[ContactCenterDecision],
        errors: list[str],
    ) -> list[str]:
        recs: list[str] = [
            (
                "Decision mix: "
                f"immediate={stats.immediate_count}, "
                f"supervised={stats.supervised_count}, "
                f"autopilot={stats.autopilot_count}, monitor={stats.monitor_count}."
            ),
            (
                f"Enrichment success {stats.enrichment_success}/{stats.enrichment_total}; "
                f"actions success={stats.actions_success}, skipped={stats.actions_skipped}, failed={stats.actions_failed}."
            ),
            "For immediate cases, pair supervisor escalation with callback commitments and compliance QA.",
            "For supervised cases, tune guardrails and response templates by queue and issue family.",
            "For autopilot cases, monitor CSAT drift and adjust compensation thresholds.",
        ]

        if pipeline_report.ranked_actions:
            recs.append(f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}")

        if errors:
            recs.append(
                "At least one integration failed; route impacted tickets to manual operations review."
            )

        top = decisions[:3]
        if top:
            recs.append(
                "Top tickets: "
                + ", ".join(
                    f"{row.ticket_id}:{row.route}:{row.risk_score:.2f}:{row.customer_id}"
                    for row in top
                )
                + "."
            )

        return recs
