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

_ORDER_RE = re.compile(r"\b(?:ORD|ORDER)[-_]?[A-Za-z0-9]{3,}\b", re.IGNORECASE)
_SUPPLIER_RE = re.compile(r"\b(?:SUP|SUPPLIER)[-_]?[A-Za-z0-9]{2,}\b", re.IGNORECASE)
_LANE_CODE_RE = re.compile(r"\bLANE-[A-Za-z0-9-]{3,}\b", re.IGNORECASE)
_PORT_PAIR_RE = re.compile(r"\b[A-Z]{3}\s*(?:->|TO)\s*[A-Z]{3}\b")
_DELAY_HOURS_RE = re.compile(r"\b(\d{1,3})\s*(?:h|hr|hrs|hour|hours)\b", re.IGNORECASE)


def _normalize(value: str) -> str:
    return value.strip().replace("_", "-").upper()


def _normalize_port_pair(value: str) -> str:
    compact = re.sub(r"\s+", "", value.upper())
    compact = compact.replace("TO", "->")
    return compact


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


class LaneDelayAdapter(Protocol):
    def lookup_lane(self, lane_id: str) -> dict[str, Any]:
        ...


class SupplierRiskAdapter(Protocol):
    def lookup_supplier(self, supplier_id: str) -> dict[str, Any]:
        ...


class FulfillmentActionAdapter(Protocol):
    def reroute_order(self, order_id: str, *, lane_id: str, reason: str) -> dict[str, Any]:
        ...

    def split_order(self, order_id: str, *, supplier_id: str, reason: str) -> dict[str, Any]:
        ...

    def expedite_order(self, order_id: str, *, reason: str) -> dict[str, Any]:
        ...

    def hold_order(self, order_id: str, *, reason: str) -> dict[str, Any]:
        ...


class NoOpLaneDelayAdapter:
    def lookup_lane(self, lane_id: str) -> dict[str, Any]:
        return {
            "lane_id": lane_id,
            "delay_hours": 8,
            "congestion_level": "medium",
            "alternate_lane": f"{lane_id}-ALT",
            "source": "noop",
        }


class NoOpSupplierRiskAdapter:
    def lookup_supplier(self, supplier_id: str) -> dict[str, Any]:
        return {
            "supplier_id": supplier_id,
            "risk_score": 0.25,
            "capacity_pct": 0.72,
            "source": "noop",
        }


class NoOpFulfillmentActionAdapter:
    def reroute_order(self, order_id: str, *, lane_id: str, reason: str) -> dict[str, Any]:
        return {
            "order_id": order_id,
            "action": "reroute",
            "lane_id": lane_id,
            "reason": reason,
            "status": "noop",
        }

    def split_order(self, order_id: str, *, supplier_id: str, reason: str) -> dict[str, Any]:
        return {
            "order_id": order_id,
            "action": "split",
            "supplier_id": supplier_id,
            "reason": reason,
            "status": "noop",
        }

    def expedite_order(self, order_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "order_id": order_id,
            "action": "expedite",
            "reason": reason,
            "status": "noop",
        }

    def hold_order(self, order_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "order_id": order_id,
            "action": "hold",
            "reason": reason,
            "status": "noop",
        }


@dataclass(slots=True)
class InMemoryLaneDelayAdapter:
    lanes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_lane(self, lane_id: str) -> dict[str, Any]:
        lane = _normalize(lane_id)
        data = self.lanes.get(lane, {})
        delay = float(data.get("delay_hours", 12.0))
        level = str(data.get("congestion_level", "medium"))
        alt = str(data.get("alternate_lane", f"{lane}-ALT"))
        return {
            "lane_id": lane,
            "delay_hours": delay,
            "congestion_level": level,
            "alternate_lane": alt,
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemorySupplierRiskAdapter:
    suppliers: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_supplier(self, supplier_id: str) -> dict[str, Any]:
        supplier = _normalize(supplier_id)
        data = self.suppliers.get(supplier, {})
        risk = float(data.get("risk_score", 0.3))
        capacity = float(data.get("capacity_pct", 0.7))
        return {
            "supplier_id": supplier,
            "risk_score": max(0.0, min(1.0, risk)),
            "capacity_pct": max(0.0, min(1.0, capacity)),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryFulfillmentActionAdapter:
    reroutes: dict[str, str] = field(default_factory=dict)
    splits: dict[str, str] = field(default_factory=dict)
    expedited: set[str] = field(default_factory=set)
    held: set[str] = field(default_factory=set)

    def reroute_order(self, order_id: str, *, lane_id: str, reason: str) -> dict[str, Any]:
        order = _normalize(order_id)
        self.reroutes[order] = lane_id
        return {
            "order_id": order,
            "action": "reroute",
            "lane_id": lane_id,
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def split_order(self, order_id: str, *, supplier_id: str, reason: str) -> dict[str, Any]:
        order = _normalize(order_id)
        self.splits[order] = supplier_id
        return {
            "order_id": order,
            "action": "split",
            "supplier_id": supplier_id,
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def expedite_order(self, order_id: str, *, reason: str) -> dict[str, Any]:
        order = _normalize(order_id)
        self.expedited.add(order)
        return {
            "order_id": order,
            "action": "expedite",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def hold_order(self, order_id: str, *, reason: str) -> dict[str, Any]:
        order = _normalize(order_id)
        self.held.add(order)
        return {
            "order_id": order,
            "action": "hold",
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
class HTTPLaneDelayAdapter(_HTTPJSONAdapterBase):
    lookup_path: str = "/supply/lane_delay"

    def lookup_lane(self, lane_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"lane_id": lane_id})


@dataclass(slots=True)
class HTTPSupplierRiskAdapter(_HTTPJSONAdapterBase):
    lookup_path: str = "/supply/supplier_risk"

    def lookup_supplier(self, supplier_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"supplier_id": supplier_id})


@dataclass(slots=True)
class HTTPFulfillmentActionAdapter(_HTTPJSONAdapterBase):
    reroute_path: str = "/supply/reroute"
    split_path: str = "/supply/split"
    expedite_path: str = "/supply/expedite"
    hold_path: str = "/supply/hold"

    def reroute_order(self, order_id: str, *, lane_id: str, reason: str) -> dict[str, Any]:
        return self._post(
            self.reroute_path,
            {"order_id": order_id, "lane_id": lane_id, "reason": reason},
        )

    def split_order(self, order_id: str, *, supplier_id: str, reason: str) -> dict[str, Any]:
        return self._post(
            self.split_path,
            {"order_id": order_id, "supplier_id": supplier_id, "reason": reason},
        )

    def expedite_order(self, order_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.expedite_path,
            {"order_id": order_id, "reason": reason},
        )

    def hold_order(self, order_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(
            self.hold_path,
            {"order_id": order_id, "reason": reason},
        )


def build_lane_delay_adapter_from_env() -> LaneDelayAdapter:
    base = os.getenv("SUPPLY_LANE_BASE_URL")
    token = os.getenv("SUPPLY_LANE_API_KEY")
    if base and token:
        path = os.getenv("SUPPLY_LANE_LOOKUP_PATH", "/supply/lane_delay")
        return HTTPLaneDelayAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpLaneDelayAdapter()


def build_supplier_risk_adapter_from_env() -> SupplierRiskAdapter:
    base = os.getenv("SUPPLY_SUPPLIER_BASE_URL")
    token = os.getenv("SUPPLY_SUPPLIER_API_KEY")
    if base and token:
        path = os.getenv("SUPPLY_SUPPLIER_LOOKUP_PATH", "/supply/supplier_risk")
        return HTTPSupplierRiskAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpSupplierRiskAdapter()


def build_fulfillment_action_adapter_from_env() -> FulfillmentActionAdapter:
    base = os.getenv("SUPPLY_ACTION_BASE_URL")
    token = os.getenv("SUPPLY_ACTION_API_KEY")
    if base and token:
        return HTTPFulfillmentActionAdapter(
            base_url=base,
            api_key=token,
            reroute_path=os.getenv("SUPPLY_ACTION_REROUTE_PATH", "/supply/reroute"),
            split_path=os.getenv("SUPPLY_ACTION_SPLIT_PATH", "/supply/split"),
            expedite_path=os.getenv("SUPPLY_ACTION_EXPEDITE_PATH", "/supply/expedite"),
            hold_path=os.getenv("SUPPLY_ACTION_HOLD_PATH", "/supply/hold"),
        )
    return NoOpFulfillmentActionAdapter()


ActionRoute = Literal["reroute", "split_order", "expedite", "hold_review", "monitor"]


@dataclass(slots=True, frozen=True)
class SupplySignal:
    order_id: str
    lane_id: str
    supplier_id: str
    observed_delay_hours: int | None


@dataclass(slots=True, frozen=True)
class SupplyDecision:
    order_id: str
    lane_id: str
    supplier_id: str
    route: ActionRoute
    priority: str
    confidence: float
    lane_delay_hours: float
    supplier_risk: float
    supplier_capacity_pct: float
    rationale: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class IntegrationCallResult:
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
class SupplyChainExecutionPolicy:
    execute_actions_in_dry_run: bool = False
    max_parallel_tasks: int = 6
    max_orders_to_process: int = 20
    reroute_delay_hours: float = 18.0
    expedite_delay_hours: float = 8.0
    risk_hold_threshold: float = 0.85
    split_capacity_threshold: float = 0.45
    allow_auto_reroute: bool = True
    allow_auto_split: bool = True
    allow_auto_expedite: bool = True
    allow_auto_hold: bool = True

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if self.max_orders_to_process < 1:
            raise ValueError("max_orders_to_process must be >= 1")
        for name, value in (
            ("risk_hold_threshold", self.risk_hold_threshold),
            ("split_capacity_threshold", self.split_capacity_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(slots=True, frozen=True)
class SupplyChainExecutionStats:
    orders_total: int
    enrichment_total: int
    enrichment_success: int
    actions_total: int
    actions_success: int
    actions_skipped: int
    actions_failed: int
    reroute_count: int
    split_count: int
    expedite_count: int
    hold_count: int
    monitor_count: int


@dataclass(slots=True, frozen=True)
class SupplyChainExecutionReport:
    batch_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    signals: tuple[SupplySignal, ...]
    enrichments: tuple[IntegrationCallResult, ...]
    decisions: tuple[SupplyDecision, ...]
    actions: tuple[IntegrationCallResult, ...]
    stats: SupplyChainExecutionStats
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
class SupplyChainControlTowerCommander:
    pipeline: TriProviderPipeline
    lane_delay_adapter: LaneDelayAdapter
    supplier_risk_adapter: SupplierRiskAdapter
    fulfillment_action_adapter: FulfillmentActionAdapter
    execution_policy: SupplyChainExecutionPolicy = field(default_factory=SupplyChainExecutionPolicy)
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
    ) -> SupplyChainExecutionReport:
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
            max_signals=self.execution_policy.max_orders_to_process,
        )

        enrichments = self._run_enrichment(signals)
        decisions = self._build_decisions(signals, enrichments)

        execute_actions = True
        if mode == "dry" and not self.execution_policy.execute_actions_in_dry_run:
            execute_actions = False
            warnings.append("Fulfillment actions skipped in dry mode by execution policy.")

        actions = self._run_actions(
            batch_id=batch_id,
            decisions=decisions,
            execute_actions=execute_actions,
        )

        for row in (*enrichments, *actions):
            if not row.success:
                errors.append(f"{row.integration}.{row.operation} failed for {row.target}: {row.error}")
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
        return SupplyChainExecutionReport(
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
    def extract_signals(text: str, *, max_signals: int = 20) -> list[SupplySignal]:
        orders = _unique_preserve([_normalize(m.group(0)) for m in _ORDER_RE.finditer(text)])
        suppliers = _unique_preserve([_normalize(m.group(0)) for m in _SUPPLIER_RE.finditer(text)])
        lanes = _unique_preserve([_normalize(m.group(0)) for m in _LANE_CODE_RE.finditer(text)])
        lanes.extend(
            lane
            for lane in (
                _normalize_port_pair(m.group(0)) for m in _PORT_PAIR_RE.finditer(text.upper())
            )
            if lane not in lanes
        )

        delay_values = [int(m.group(1)) for m in _DELAY_HOURS_RE.finditer(text)]
        observed_delay = max(delay_values) if delay_values else None

        if not orders:
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8].upper()
            orders = [f"ORD-{digest}"]
        if not suppliers:
            suppliers = ["SUP-AUTO-01"]
        if not lanes:
            lanes = ["LANE-AUTO-01"]

        rows: list[SupplySignal] = []
        for idx, order in enumerate(orders[:max_signals]):
            rows.append(
                SupplySignal(
                    order_id=order,
                    lane_id=lanes[idx % len(lanes)],
                    supplier_id=suppliers[idx % len(suppliers)],
                    observed_delay_hours=observed_delay,
                )
            )
        return rows

    @staticmethod
    def _build_batch_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"supply-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _run_enrichment(self, signals: list[SupplySignal]) -> list[IntegrationCallResult]:
        tasks: list[_ExecutionTask] = []

        lane_ids = _unique_preserve([signal.lane_id for signal in signals])
        for lane_id in lane_ids:
            tasks.append(
                _ExecutionTask(
                    integration="lane_delay",
                    operation="lookup",
                    target=lane_id,
                    request_payload={"lane_id": lane_id},
                    idempotency_key=None,
                    call=lambda lane_id=lane_id: self.lane_delay_adapter.lookup_lane(lane_id),
                )
            )

        supplier_ids = _unique_preserve([signal.supplier_id for signal in signals])
        for supplier_id in supplier_ids:
            tasks.append(
                _ExecutionTask(
                    integration="supplier_risk",
                    operation="lookup",
                    target=supplier_id,
                    request_payload={"supplier_id": supplier_id},
                    idempotency_key=None,
                    call=lambda supplier_id=supplier_id: self.supplier_risk_adapter.lookup_supplier(
                        supplier_id
                    ),
                )
            )

        return self._execute_tasks(tasks)

    def _build_decisions(
        self,
        signals: list[SupplySignal],
        enrichments: list[IntegrationCallResult],
    ) -> list[SupplyDecision]:
        lane_data: dict[str, dict[str, Any]] = {}
        supplier_data: dict[str, dict[str, Any]] = {}

        for row in enrichments:
            if not row.success or row.status != "executed":
                continue
            if row.integration == "lane_delay":
                lane_data[row.target] = row.response or {}
            elif row.integration == "supplier_risk":
                supplier_data[row.target] = row.response or {}

        decisions: list[SupplyDecision] = []
        for signal in signals:
            lane = lane_data.get(signal.lane_id, {})
            supplier = supplier_data.get(signal.supplier_id, {})

            lane_delay = self._as_float(
                lane,
                keys=("delay_hours", "eta_delay_hours", "delay"),
                default=float(signal.observed_delay_hours or 0),
            )
            supplier_risk = self._as_float(
                supplier,
                keys=("risk_score", "supplier_risk", "score"),
                default=0.4,
                cap_1=True,
            )
            capacity = self._as_float(
                supplier,
                keys=("capacity_pct", "capacity", "available_capacity"),
                default=0.7,
                cap_1=True,
            )

            route: ActionRoute = "monitor"
            rationale: list[str] = []

            if supplier_risk >= self.execution_policy.risk_hold_threshold:
                route = "hold_review"
                rationale.append("Supplier risk exceeds hold threshold.")
            elif lane_delay >= self.execution_policy.reroute_delay_hours:
                route = "reroute"
                rationale.append("Lane delay exceeds reroute threshold.")
            elif capacity <= self.execution_policy.split_capacity_threshold:
                route = "split_order"
                rationale.append("Supplier capacity below split threshold.")
            elif lane_delay >= self.execution_policy.expedite_delay_hours:
                route = "expedite"
                rationale.append("Delay above expedite threshold but below reroute threshold.")
            else:
                rationale.append("Current lane and supplier conditions are stable; monitor.")

            if not lane:
                rationale.append("Lane enrichment missing; confidence reduced.")
            if not supplier:
                rationale.append("Supplier enrichment missing; confidence reduced.")

            priority = self._priority_for(route=route, lane_delay=lane_delay, supplier_risk=supplier_risk)
            confidence = self._confidence_for(
                route=route,
                lane_enriched=bool(lane),
                supplier_enriched=bool(supplier),
            )

            decisions.append(
                SupplyDecision(
                    order_id=signal.order_id,
                    lane_id=signal.lane_id,
                    supplier_id=signal.supplier_id,
                    route=route,
                    priority=priority,
                    confidence=confidence,
                    lane_delay_hours=lane_delay,
                    supplier_risk=supplier_risk,
                    supplier_capacity_pct=capacity,
                    rationale=tuple(rationale),
                )
            )

        decisions.sort(
            key=lambda row: (
                row.route in {"hold_review", "reroute", "split_order"},
                row.priority == "urgent",
                row.lane_delay_hours,
                row.supplier_risk,
            ),
            reverse=True,
        )
        return decisions

    def _run_actions(
        self,
        *,
        batch_id: str,
        decisions: list[SupplyDecision],
        execute_actions: bool,
    ) -> list[IntegrationCallResult]:
        tasks: list[_ExecutionTask] = []
        skipped: list[IntegrationCallResult] = []

        for row in decisions:
            reason = "; ".join(row.rationale)
            if not execute_actions:
                skipped.append(
                    IntegrationCallResult(
                        integration="fulfillment_actions",
                        operation=row.route,
                        target=row.order_id,
                        success=True,
                        latency_ms=0,
                        request={"order_id": row.order_id, "route": row.route},
                        status="skipped",
                        attempts=0,
                        notes=("action execution disabled by runtime policy",),
                    )
                )
                continue

            if row.route == "monitor":
                skipped.append(
                    IntegrationCallResult(
                        integration="fulfillment_actions",
                        operation="monitor",
                        target=row.order_id,
                        success=True,
                        latency_ms=0,
                        request={"order_id": row.order_id, "route": "monitor"},
                        status="skipped",
                        attempts=0,
                        notes=("monitor route requires no external action call",),
                    )
                )
                continue

            if row.route == "reroute":
                if not self.execution_policy.allow_auto_reroute:
                    skipped.append(
                        IntegrationCallResult(
                            integration="fulfillment_actions",
                            operation="reroute",
                            target=row.order_id,
                            success=True,
                            latency_ms=0,
                            request={"order_id": row.order_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto reroute disabled by policy",),
                        )
                    )
                    continue
                target_lane = f"{row.lane_id}-ALT"
                key = f"{batch_id}:reroute:{row.order_id}:{target_lane}"
                tasks.append(
                    _ExecutionTask(
                        integration="fulfillment_actions",
                        operation="reroute",
                        target=row.order_id,
                        request_payload={
                            "order_id": row.order_id,
                            "lane_id": target_lane,
                            "reason": reason,
                        },
                        idempotency_key=key,
                        call=lambda order_id=row.order_id, lane_id=target_lane, reason=reason: self.fulfillment_action_adapter.reroute_order(
                            order_id,
                            lane_id=lane_id,
                            reason=reason,
                        ),
                    )
                )
                continue

            if row.route == "split_order":
                if not self.execution_policy.allow_auto_split:
                    skipped.append(
                        IntegrationCallResult(
                            integration="fulfillment_actions",
                            operation="split_order",
                            target=row.order_id,
                            success=True,
                            latency_ms=0,
                            request={"order_id": row.order_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto split disabled by policy",),
                        )
                    )
                    continue
                fallback_supplier = f"{row.supplier_id}-ALT"
                key = f"{batch_id}:split:{row.order_id}:{fallback_supplier}"
                tasks.append(
                    _ExecutionTask(
                        integration="fulfillment_actions",
                        operation="split_order",
                        target=row.order_id,
                        request_payload={
                            "order_id": row.order_id,
                            "supplier_id": fallback_supplier,
                            "reason": reason,
                        },
                        idempotency_key=key,
                        call=lambda order_id=row.order_id, supplier_id=fallback_supplier, reason=reason: self.fulfillment_action_adapter.split_order(
                            order_id,
                            supplier_id=supplier_id,
                            reason=reason,
                        ),
                    )
                )
                continue

            if row.route == "expedite":
                if not self.execution_policy.allow_auto_expedite:
                    skipped.append(
                        IntegrationCallResult(
                            integration="fulfillment_actions",
                            operation="expedite",
                            target=row.order_id,
                            success=True,
                            latency_ms=0,
                            request={"order_id": row.order_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto expedite disabled by policy",),
                        )
                    )
                    continue
                key = f"{batch_id}:expedite:{row.order_id}"
                tasks.append(
                    _ExecutionTask(
                        integration="fulfillment_actions",
                        operation="expedite",
                        target=row.order_id,
                        request_payload={"order_id": row.order_id, "reason": reason},
                        idempotency_key=key,
                        call=lambda order_id=row.order_id, reason=reason: self.fulfillment_action_adapter.expedite_order(
                            order_id,
                            reason=reason,
                        ),
                    )
                )
                continue

            if row.route == "hold_review":
                if not self.execution_policy.allow_auto_hold:
                    skipped.append(
                        IntegrationCallResult(
                            integration="fulfillment_actions",
                            operation="hold_review",
                            target=row.order_id,
                            success=True,
                            latency_ms=0,
                            request={"order_id": row.order_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto hold disabled by policy",),
                        )
                    )
                    continue
                key = f"{batch_id}:hold:{row.order_id}"
                tasks.append(
                    _ExecutionTask(
                        integration="fulfillment_actions",
                        operation="hold_review",
                        target=row.order_id,
                        request_payload={"order_id": row.order_id, "reason": reason},
                        idempotency_key=key,
                        call=lambda order_id=row.order_id, reason=reason: self.fulfillment_action_adapter.hold_order(
                            order_id,
                            reason=reason,
                        ),
                    )
                )
                continue

        executed = self._execute_tasks(tasks)
        return [*skipped, *executed]

    def _execute_tasks(self, tasks: list[_ExecutionTask]) -> list[IntegrationCallResult]:
        if not tasks:
            return []

        workers = min(self.execution_policy.max_parallel_tasks, len(tasks))
        if workers == 1:
            return [self._execute_task(task) for task in tasks]

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(self._execute_task, task) for task in tasks]
            return [future.result() for future in futures]

    def _execute_task(self, task: _ExecutionTask) -> IntegrationCallResult:
        if task.idempotency_key and self.idempotency_store.seen(task.idempotency_key):
            return IntegrationCallResult(
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
            self.idempotency_store.mark(task.idempotency_key, ttl_seconds=self.idempotency_ttl_seconds)

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
    ) -> IntegrationCallResult:
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
                return IntegrationCallResult(
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
        return IntegrationCallResult(
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
        row: IntegrationCallResult,
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
        cap_1: bool = False,
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
    def _priority_for(*, route: ActionRoute, lane_delay: float, supplier_risk: float) -> str:
        if route in {"hold_review", "reroute"}:
            return "urgent"
        if route == "split_order":
            return "high"
        if route == "expedite":
            return "normal"
        if lane_delay > 24 or supplier_risk > 0.7:
            return "high"
        return "low"

    @staticmethod
    def _confidence_for(
        *,
        route: ActionRoute,
        lane_enriched: bool,
        supplier_enriched: bool,
    ) -> float:
        base = {
            "hold_review": 0.9,
            "reroute": 0.86,
            "split_order": 0.82,
            "expedite": 0.75,
            "monitor": 0.65,
        }[route]
        if not lane_enriched:
            base -= 0.15
        if not supplier_enriched:
            base -= 0.15
        return round(min(0.99, max(0.05, base)), 3)

    @staticmethod
    def _build_stats(
        *,
        signals: list[SupplySignal],
        enrichments: list[IntegrationCallResult],
        decisions: list[SupplyDecision],
        actions: list[IntegrationCallResult],
    ) -> SupplyChainExecutionStats:
        route_counts: dict[ActionRoute, int] = defaultdict(int)
        for row in decisions:
            route_counts[row.route] += 1

        actions_success = sum(1 for row in actions if row.success and row.status == "executed")
        actions_skipped = sum(1 for row in actions if row.status == "skipped")
        actions_failed = sum(1 for row in actions if not row.success)

        return SupplyChainExecutionStats(
            orders_total=len(signals),
            enrichment_total=len(enrichments),
            enrichment_success=sum(1 for row in enrichments if row.success),
            actions_total=len(actions),
            actions_success=actions_success,
            actions_skipped=actions_skipped,
            actions_failed=actions_failed,
            reroute_count=route_counts["reroute"],
            split_count=route_counts["split_order"],
            expedite_count=route_counts["expedite"],
            hold_count=route_counts["hold_review"],
            monitor_count=route_counts["monitor"],
        )

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        stats: SupplyChainExecutionStats,
        decisions: list[SupplyDecision],
        errors: list[str],
    ) -> list[str]:
        recs: list[str] = [
            (
                f"Decision mix: reroute={stats.reroute_count}, split={stats.split_count}, "
                f"expedite={stats.expedite_count}, hold={stats.hold_count}, monitor={stats.monitor_count}."
            ),
            (
                f"Enrichment success {stats.enrichment_success}/{stats.enrichment_total}; "
                f"actions success={stats.actions_success}, skipped={stats.actions_skipped}, failed={stats.actions_failed}."
            ),
            "For rerouted orders, validate alternate-lane contractual and customs constraints.",
            "For split-order actions, verify allocation fairness and downstream warehouse capacity.",
            "For hold-review orders, trigger supplier risk governance review and contingency sourcing plan.",
        ]

        if pipeline_report.ranked_actions:
            recs.append(f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}")

        if errors:
            recs.append("At least one integration failed; switch to manual control tower fallback workflow.")

        top = decisions[:3]
        if top:
            recs.append(
                "Top-priority orders: "
                + ", ".join(
                    f"{row.order_id}:{row.route}:{row.lane_delay_hours:.1f}h:{row.supplier_risk:.2f}"
                    for row in top
                )
                + "."
            )

        return recs
