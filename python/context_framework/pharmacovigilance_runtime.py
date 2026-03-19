from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from .runtime_base import (
    AuditLogger,
    BaseIntegrationCommanderMixin,
    HTTPJSONAdapterBase,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    IntegrationActionResult,
    IntegrationExecutionTask,
    NoOpAuditLogger,
    unique_preserve as _unique_preserve,
)
from .tri_provider_pipeline import TriProviderPipeline, UseCaseExecutionReport

# Backward-compatible alias.
PVActionResult = IntegrationActionResult

_SIGNAL_RE = re.compile(r"\b(?:AE|CASE|PV)[-_]?[A-Za-z0-9]{3,}\b", re.IGNORECASE)
_LOT_RE = re.compile(r"\bLOT[-_]?[A-Za-z0-9]{3,}\b", re.IGNORECASE)
_COMPOUND_RE = re.compile(r"\b(?:CMP|DRUG|MED)[-_]?[A-Za-z0-9]{2,}\b", re.IGNORECASE)
_COUNT_RE = re.compile(r"\b(\d{1,5})\s*(?:reports|cases|events)\b", re.IGNORECASE)

_SYMPTOM_KEYWORDS = (
    "anaphylaxis",
    "arrhythmia",
    "hepatotoxicity",
    "renal failure",
    "thrombosis",
    "seizure",
    "rash",
    "death",
)
_SYMPTOM_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(keyword) for keyword in _SYMPTOM_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def _normalize(value: str) -> str:
    return value.strip().replace("_", "-").upper()


class FAERSAdapter(Protocol):
    def lookup_signal(self, compound: str, symptom: str) -> dict[str, Any]: ...


class LotTraceabilityAdapter(Protocol):
    def lookup_lot(self, lot_id: str) -> dict[str, Any]: ...


class SafetyActionAdapter(Protocol):
    def queue_medical_review(self, signal_id: str, *, reason: str) -> dict[str, Any]: ...

    def hold_lot(self, lot_id: str, *, reason: str) -> dict[str, Any]: ...

    def submit_regulatory_alert(self, signal_id: str, *, reason: str) -> dict[str, Any]: ...


class NoOpFAERSAdapter:
    def lookup_signal(self, compound: str, symptom: str) -> dict[str, Any]:
        return {
            "compound": compound,
            "symptom": symptom,
            "serious_event_rate": 0.22,
            "recent_case_count": 18,
            "fatal_case_count": 0,
            "source": "noop",
        }


class NoOpLotTraceabilityAdapter:
    def lookup_lot(self, lot_id: str) -> dict[str, Any]:
        return {
            "lot_id": lot_id,
            "deviation_rate": 0.11,
            "units_shipped": 15000,
            "distribution_regions": ["US-EAST"],
            "source": "noop",
        }


class NoOpSafetyActionAdapter:
    def queue_medical_review(self, signal_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "signal_id": signal_id,
            "action": "queue_medical_review",
            "reason": reason,
            "status": "noop",
        }

    def hold_lot(self, lot_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "lot_id": lot_id,
            "action": "hold_lot",
            "reason": reason,
            "status": "noop",
        }

    def submit_regulatory_alert(self, signal_id: str, *, reason: str) -> dict[str, Any]:
        return {
            "signal_id": signal_id,
            "action": "submit_regulatory_alert",
            "reason": reason,
            "status": "noop",
        }


@dataclass(slots=True)
class InMemoryFAERSAdapter:
    signals: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_signal(self, compound: str, symptom: str) -> dict[str, Any]:
        key = f"{_normalize(compound)}|{symptom.lower()}"
        payload = self.signals.get(key, {})
        serious = float(payload.get("serious_event_rate", 0.28))
        recent = int(payload.get("recent_case_count", 15))
        fatal = int(payload.get("fatal_case_count", 0))
        return {
            "compound": _normalize(compound),
            "symptom": symptom.lower(),
            "serious_event_rate": max(0.0, min(1.0, serious)),
            "recent_case_count": max(0, recent),
            "fatal_case_count": max(0, fatal),
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemoryLotTraceabilityAdapter:
    lots: dict[str, dict[str, Any]] = field(default_factory=dict)

    def lookup_lot(self, lot_id: str) -> dict[str, Any]:
        lot = _normalize(lot_id)
        payload = self.lots.get(lot, {})
        deviation = float(payload.get("deviation_rate", 0.12))
        units = int(payload.get("units_shipped", 12000))
        regions = list(payload.get("distribution_regions", ["US-NATIONAL"]))
        return {
            "lot_id": lot,
            "deviation_rate": max(0.0, min(1.0, deviation)),
            "units_shipped": max(0, units),
            "distribution_regions": regions,
            "source": "in-memory",
        }


@dataclass(slots=True)
class InMemorySafetyActionAdapter:
    medical_reviews: set[str] = field(default_factory=set)
    held_lots: set[str] = field(default_factory=set)
    alerts: set[str] = field(default_factory=set)

    def queue_medical_review(self, signal_id: str, *, reason: str) -> dict[str, Any]:
        signal = _normalize(signal_id)
        self.medical_reviews.add(signal)
        return {
            "signal_id": signal,
            "action": "queue_medical_review",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def hold_lot(self, lot_id: str, *, reason: str) -> dict[str, Any]:
        lot = _normalize(lot_id)
        self.held_lots.add(lot)
        return {
            "lot_id": lot,
            "action": "hold_lot",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }

    def submit_regulatory_alert(self, signal_id: str, *, reason: str) -> dict[str, Any]:
        signal = _normalize(signal_id)
        self.alerts.add(signal)
        return {
            "signal_id": signal,
            "action": "submit_regulatory_alert",
            "reason": reason,
            "updated": True,
            "source": "in-memory",
        }


_HTTPJSONAdapterBase = HTTPJSONAdapterBase


@dataclass(slots=True)
class HTTPFAERSAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/pv/faers_lookup"

    def lookup_signal(self, compound: str, symptom: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"compound": compound, "symptom": symptom})


@dataclass(slots=True)
class HTTPLotTraceabilityAdapter(HTTPJSONAdapterBase):
    lookup_path: str = "/pv/lot_trace"

    def lookup_lot(self, lot_id: str) -> dict[str, Any]:
        return self._post(self.lookup_path, {"lot_id": lot_id})


@dataclass(slots=True)
class HTTPSafetyActionAdapter(HTTPJSONAdapterBase):
    review_path: str = "/pv/queue_medical_review"
    hold_path: str = "/pv/hold_lot"
    alert_path: str = "/pv/regulatory_alert"

    def queue_medical_review(self, signal_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.review_path, {"signal_id": signal_id, "reason": reason})

    def hold_lot(self, lot_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.hold_path, {"lot_id": lot_id, "reason": reason})

    def submit_regulatory_alert(self, signal_id: str, *, reason: str) -> dict[str, Any]:
        return self._post(self.alert_path, {"signal_id": signal_id, "reason": reason})


def build_faers_adapter_from_env() -> FAERSAdapter:
    base = os.getenv("PV_FAERS_BASE_URL")
    token = os.getenv("PV_FAERS_API_KEY")
    if base and token:
        path = os.getenv("PV_FAERS_LOOKUP_PATH", "/pv/faers_lookup")
        return HTTPFAERSAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpFAERSAdapter()


def build_lot_traceability_adapter_from_env() -> LotTraceabilityAdapter:
    base = os.getenv("PV_LOT_BASE_URL")
    token = os.getenv("PV_LOT_API_KEY")
    if base and token:
        path = os.getenv("PV_LOT_LOOKUP_PATH", "/pv/lot_trace")
        return HTTPLotTraceabilityAdapter(base_url=base, api_key=token, lookup_path=path)
    return NoOpLotTraceabilityAdapter()


def build_safety_action_adapter_from_env() -> SafetyActionAdapter:
    base = os.getenv("PV_ACTIONS_BASE_URL")
    token = os.getenv("PV_ACTIONS_API_KEY")
    if base and token:
        return HTTPSafetyActionAdapter(
            base_url=base,
            api_key=token,
            review_path=os.getenv("PV_ACTIONS_REVIEW_PATH", "/pv/queue_medical_review"),
            hold_path=os.getenv("PV_ACTIONS_HOLD_PATH", "/pv/hold_lot"),
            alert_path=os.getenv("PV_ACTIONS_ALERT_PATH", "/pv/regulatory_alert"),
        )
    return NoOpSafetyActionAdapter()


PVRoute = Literal[
    "lot_hold_and_report",
    "urgent_medical_review",
    "enhanced_monitoring",
    "monitor",
]


@dataclass(slots=True, frozen=True)
class PVSignal:
    signal_id: str
    lot_id: str
    compound: str
    symptom: str
    observed_case_count: int | None


@dataclass(slots=True, frozen=True)
class PVDecision:
    signal_id: str
    lot_id: str
    compound: str
    symptom: str
    route: PVRoute
    priority: str
    confidence: float
    risk_score: float
    serious_event_rate: float
    lot_deviation_rate: float
    fatal_case_count: int
    rationale: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class PharmacovigilanceExecutionPolicy:
    execute_actions_in_dry_run: bool = False
    max_parallel_tasks: int = 6
    max_signals_to_process: int = 20
    lot_hold_threshold: float = 0.82
    regulatory_alert_threshold: float = 0.9
    medical_review_threshold: float = 0.55
    allow_auto_lot_hold: bool = True
    allow_auto_regulatory_alert: bool = True
    allow_auto_medical_review: bool = True

    def __post_init__(self) -> None:
        if self.max_parallel_tasks < 1:
            raise ValueError("max_parallel_tasks must be >= 1")
        if self.max_signals_to_process < 1:
            raise ValueError("max_signals_to_process must be >= 1")
        for name, value in (
            ("lot_hold_threshold", self.lot_hold_threshold),
            ("regulatory_alert_threshold", self.regulatory_alert_threshold),
            ("medical_review_threshold", self.medical_review_threshold),
        ):
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1")


@dataclass(slots=True, frozen=True)
class PharmacovigilanceExecutionStats:
    signals_total: int
    enrichment_total: int
    enrichment_success: int
    actions_total: int
    actions_success: int
    actions_skipped: int
    actions_failed: int
    lot_hold_count: int
    urgent_review_count: int
    enhanced_monitor_count: int
    monitor_count: int


@dataclass(slots=True, frozen=True)
class PharmacovigilanceExecutionReport:
    batch_id: str
    pipeline_report: UseCaseExecutionReport
    mode: str
    started_at: datetime
    completed_at: datetime
    signals: tuple[PVSignal, ...]
    enrichments: tuple[PVActionResult, ...]
    decisions: tuple[PVDecision, ...]
    actions: tuple[PVActionResult, ...]
    stats: PharmacovigilanceExecutionStats
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


_ExecutionTask = IntegrationExecutionTask


@dataclass(slots=True)
class PharmacovigilanceCommander(BaseIntegrationCommanderMixin):
    pipeline: TriProviderPipeline
    faers_adapter: FAERSAdapter
    lot_traceability_adapter: LotTraceabilityAdapter
    safety_action_adapter: SafetyActionAdapter
    execution_policy: PharmacovigilanceExecutionPolicy = field(
        default_factory=PharmacovigilanceExecutionPolicy
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
    ) -> PharmacovigilanceExecutionReport:
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
            max_signals=self.execution_policy.max_signals_to_process,
        )

        enrichments = self._run_enrichment(signals)
        decisions = self._build_decisions(signals, enrichments)

        execute_actions = True
        if mode == "dry" and not self.execution_policy.execute_actions_in_dry_run:
            execute_actions = False
            warnings.append("Pharmacovigilance actions skipped in dry mode by execution policy.")

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
            self._log_integration_audit_event(batch_id=batch_id, mode=mode, row=row)

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
        return PharmacovigilanceExecutionReport(
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
    def extract_signals(text: str, *, max_signals: int = 20) -> list[PVSignal]:
        signal_matches = list(_SIGNAL_RE.finditer(text))
        lots = [_normalize(m.group(0)) for m in _LOT_RE.finditer(text)]
        compounds = [_normalize(m.group(0)) for m in _COMPOUND_RE.finditer(text)]
        symptoms = [m.group(0).lower() for m in _SYMPTOM_RE.finditer(text)]
        counts = [int(m.group(1)) for m in _COUNT_RE.finditer(text)]

        def _pick(values: list[str], index: int, default: str) -> str:
            if not values:
                return default
            if index < len(values):
                return values[index]
            return values[-1]

        def _pick_count(index: int) -> int | None:
            if not counts:
                return None
            if index < len(counts):
                return counts[index]
            return counts[-1]

        if not signal_matches:
            return [
                PVSignal(
                    signal_id=f"AE-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:8].upper()}",
                    lot_id=_pick(lots, 0, "LOT-AUTO-01"),
                    compound=_pick(compounds, 0, "CMP-AUTO-01"),
                    symptom=_pick(symptoms, 0, "unknown-symptom"),
                    observed_case_count=_pick_count(0),
                )
            ]

        rows: list[PVSignal] = []
        seen_signal_ids: set[str] = set()
        for idx, match in enumerate(signal_matches):
            if len(rows) >= max_signals:
                break

            signal_id = _normalize(match.group(0))
            signal_key = signal_id.lower()
            if signal_key in seen_signal_ids:
                continue
            seen_signal_ids.add(signal_key)

            segment_index = len(rows)
            start = match.start()
            end = signal_matches[idx + 1].start() if idx + 1 < len(signal_matches) else len(text)
            segment = text[start:end]

            lot_match = _LOT_RE.search(segment)
            compound_match = _COMPOUND_RE.search(segment)
            symptom_match = _SYMPTOM_RE.search(segment)
            count_match = _COUNT_RE.search(segment)

            rows.append(
                PVSignal(
                    signal_id=signal_id,
                    lot_id=_normalize(lot_match.group(0))
                    if lot_match
                    else _pick(lots, segment_index, "LOT-AUTO-01"),
                    compound=_normalize(compound_match.group(0))
                    if compound_match
                    else _pick(compounds, segment_index, "CMP-AUTO-01"),
                    symptom=symptom_match.group(0).lower()
                    if symptom_match
                    else _pick(symptoms, segment_index, "unknown-symptom"),
                    observed_case_count=int(count_match.group(1))
                    if count_match
                    else _pick_count(segment_index),
                )
            )

        return rows

    @staticmethod
    def _build_batch_id(scenario: str, started_at: datetime) -> str:
        digest = hashlib.sha256(
            f"{started_at.isoformat()}::{scenario}".encode("utf-8")
        ).hexdigest()[:16]
        return f"pv-{started_at.strftime('%Y%m%d%H%M%S')}-{digest}"

    def _run_enrichment(self, signals: list[PVSignal]) -> list[PVActionResult]:
        tasks: list[_ExecutionTask] = []

        for signal in signals:
            tasks.append(
                _ExecutionTask(
                    integration="faers",
                    operation="lookup_signal",
                    target=signal.signal_id,
                    request_payload={"compound": signal.compound, "symptom": signal.symptom},
                    idempotency_key=None,
                    call=lambda signal=signal: self.faers_adapter.lookup_signal(
                        signal.compound,
                        signal.symptom,
                    ),
                )
            )

        lot_ids = _unique_preserve([signal.lot_id for signal in signals])
        for lot_id in lot_ids:
            tasks.append(
                _ExecutionTask(
                    integration="lot_traceability",
                    operation="lookup_lot",
                    target=lot_id,
                    request_payload={"lot_id": lot_id},
                    idempotency_key=None,
                    call=lambda lot_id=lot_id: self.lot_traceability_adapter.lookup_lot(lot_id),
                )
            )

        return self._execute_integration_tasks(tasks)

    def _build_decisions(
        self,
        signals: list[PVSignal],
        enrichments: list[PVActionResult],
    ) -> list[PVDecision]:
        faers_data: dict[str, dict[str, Any]] = {}
        lot_data: dict[str, dict[str, Any]] = {}

        for row in enrichments:
            if not row.success or row.status != "executed":
                continue
            if row.integration == "faers":
                faers_data[row.target] = row.response or {}
            elif row.integration == "lot_traceability":
                lot_data[row.target] = row.response or {}

        decisions: list[PVDecision] = []
        for signal in signals:
            faers = faers_data.get(signal.signal_id, {})
            lot = lot_data.get(signal.lot_id, {})

            serious_rate = self._as_float(
                faers,
                keys=("serious_event_rate", "serious_rate", "risk_score"),
                default=0.25,
            )
            fatal_count = int(
                self._as_float(faers, keys=("fatal_case_count",), default=0, cap_1=False)
            )
            lot_deviation = self._as_float(
                lot,
                keys=("deviation_rate", "defect_rate", "quality_signal"),
                default=0.1,
            )
            case_count = self._as_float(
                faers,
                keys=("recent_case_count", "case_count", "count"),
                default=float(signal.observed_case_count or 0),
                cap_1=False,
            )

            risk_score = min(
                1.0,
                serious_rate * 0.55
                + lot_deviation * 0.30
                + min(1.0, case_count / 200.0) * 0.15
                + (0.2 if fatal_count > 0 else 0.0),
            )

            route: PVRoute = "monitor"
            rationale: list[str] = []
            if risk_score >= self.execution_policy.regulatory_alert_threshold or fatal_count > 0:
                route = "lot_hold_and_report"
                rationale.append("High composite safety risk and/or fatal case evidence.")
            elif risk_score >= self.execution_policy.lot_hold_threshold:
                route = "lot_hold_and_report"
                rationale.append("Risk score exceeds lot-hold threshold.")
            elif risk_score >= self.execution_policy.medical_review_threshold:
                route = "urgent_medical_review"
                rationale.append("Risk score exceeds medical-review threshold.")
            elif risk_score >= 0.35:
                route = "enhanced_monitoring"
                rationale.append("Moderate risk, continue enhanced monitoring.")
            else:
                rationale.append("Low current signal strength, continue baseline monitoring.")

            if not faers:
                rationale.append("FAERS enrichment missing; confidence reduced.")
            if not lot:
                rationale.append("Lot traceability enrichment missing; confidence reduced.")

            priority = self._priority_for(route)
            confidence = self._confidence_for(
                route=route,
                faers_enriched=bool(faers),
                lot_enriched=bool(lot),
            )

            decisions.append(
                PVDecision(
                    signal_id=signal.signal_id,
                    lot_id=signal.lot_id,
                    compound=signal.compound,
                    symptom=signal.symptom,
                    route=route,
                    priority=priority,
                    confidence=confidence,
                    risk_score=risk_score,
                    serious_event_rate=serious_rate,
                    lot_deviation_rate=lot_deviation,
                    fatal_case_count=fatal_count,
                    rationale=tuple(rationale),
                )
            )

        decisions.sort(
            key=lambda row: (
                row.route in {"lot_hold_and_report", "urgent_medical_review"},
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
        decisions: list[PVDecision],
        execute_actions: bool,
    ) -> list[PVActionResult]:
        tasks: list[_ExecutionTask] = []
        skipped: list[PVActionResult] = []

        for row in decisions:
            reason = "; ".join(row.rationale)
            if not execute_actions:
                skipped.append(
                    PVActionResult(
                        integration="safety_actions",
                        operation=row.route,
                        target=row.signal_id,
                        success=True,
                        latency_ms=0,
                        request={"signal_id": row.signal_id, "route": row.route},
                        status="skipped",
                        attempts=0,
                        notes=("action execution disabled by runtime policy",),
                    )
                )
                continue

            if row.route == "monitor":
                skipped.append(
                    PVActionResult(
                        integration="safety_actions",
                        operation="monitor",
                        target=row.signal_id,
                        success=True,
                        latency_ms=0,
                        request={"signal_id": row.signal_id, "route": "monitor"},
                        status="skipped",
                        attempts=0,
                        notes=("monitor route requires no external action call",),
                    )
                )
                continue

            if row.route == "lot_hold_and_report":
                if self.execution_policy.allow_auto_lot_hold:
                    hold_key = f"{batch_id}:hold_lot:{row.lot_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="safety_actions",
                            operation="hold_lot",
                            target=row.lot_id,
                            request_payload={"lot_id": row.lot_id, "reason": reason},
                            idempotency_key=hold_key,
                            call=lambda row=row, reason=reason: self.safety_action_adapter.hold_lot(
                                row.lot_id,
                                reason=reason,
                            ),
                        )
                    )
                else:
                    skipped.append(
                        PVActionResult(
                            integration="safety_actions",
                            operation="hold_lot",
                            target=row.lot_id,
                            success=True,
                            latency_ms=0,
                            request={"lot_id": row.lot_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto lot hold disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_regulatory_alert:
                    alert_key = f"{batch_id}:regulatory_alert:{row.signal_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="safety_actions",
                            operation="submit_regulatory_alert",
                            target=row.signal_id,
                            request_payload={"signal_id": row.signal_id, "reason": reason},
                            idempotency_key=alert_key,
                            call=lambda row=row, reason=reason: (
                                self.safety_action_adapter.submit_regulatory_alert(
                                    row.signal_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        PVActionResult(
                            integration="safety_actions",
                            operation="submit_regulatory_alert",
                            target=row.signal_id,
                            success=True,
                            latency_ms=0,
                            request={"signal_id": row.signal_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto regulatory alert disabled by policy",),
                        )
                    )

                if self.execution_policy.allow_auto_medical_review:
                    review_key = f"{batch_id}:medical_review:{row.signal_id}"
                    tasks.append(
                        _ExecutionTask(
                            integration="safety_actions",
                            operation="queue_medical_review",
                            target=row.signal_id,
                            request_payload={"signal_id": row.signal_id, "reason": reason},
                            idempotency_key=review_key,
                            call=lambda row=row, reason=reason: (
                                self.safety_action_adapter.queue_medical_review(
                                    row.signal_id,
                                    reason=reason,
                                )
                            ),
                        )
                    )
                else:
                    skipped.append(
                        PVActionResult(
                            integration="safety_actions",
                            operation="queue_medical_review",
                            target=row.signal_id,
                            success=True,
                            latency_ms=0,
                            request={"signal_id": row.signal_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto medical review disabled by policy",),
                        )
                    )
                continue

            if row.route == "urgent_medical_review":
                if not self.execution_policy.allow_auto_medical_review:
                    skipped.append(
                        PVActionResult(
                            integration="safety_actions",
                            operation="queue_medical_review",
                            target=row.signal_id,
                            success=True,
                            latency_ms=0,
                            request={"signal_id": row.signal_id},
                            status="skipped",
                            attempts=0,
                            notes=("auto medical review disabled by policy",),
                        )
                    )
                    continue
                review_key = f"{batch_id}:medical_review:{row.signal_id}"
                tasks.append(
                    _ExecutionTask(
                        integration="safety_actions",
                        operation="queue_medical_review",
                        target=row.signal_id,
                        request_payload={"signal_id": row.signal_id, "reason": reason},
                        idempotency_key=review_key,
                        call=lambda row=row, reason=reason: (
                            self.safety_action_adapter.queue_medical_review(
                                row.signal_id,
                                reason=reason,
                            )
                        ),
                    )
                )
                continue

            if row.route == "enhanced_monitoring":
                skipped.append(
                    PVActionResult(
                        integration="safety_actions",
                        operation="enhanced_monitoring",
                        target=row.signal_id,
                        success=True,
                        latency_ms=0,
                        request={"signal_id": row.signal_id, "route": "enhanced_monitoring"},
                        status="skipped",
                        attempts=0,
                        notes=("enhanced monitoring is tracked without external action call",),
                    )
                )

        executed = self._execute_integration_tasks(tasks)
        return [*skipped, *executed]

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
    def _priority_for(route: PVRoute) -> str:
        if route == "lot_hold_and_report":
            return "urgent"
        if route == "urgent_medical_review":
            return "high"
        if route == "enhanced_monitoring":
            return "normal"
        return "low"

    @staticmethod
    def _confidence_for(
        *,
        route: PVRoute,
        faers_enriched: bool,
        lot_enriched: bool,
    ) -> float:
        base = {
            "lot_hold_and_report": 0.9,
            "urgent_medical_review": 0.84,
            "enhanced_monitoring": 0.76,
            "monitor": 0.68,
        }[route]
        if not faers_enriched:
            base -= 0.15
        if not lot_enriched:
            base -= 0.15
        return round(min(0.99, max(0.05, base)), 3)

    @staticmethod
    def _build_stats(
        *,
        signals: list[PVSignal],
        enrichments: list[PVActionResult],
        decisions: list[PVDecision],
        actions: list[PVActionResult],
    ) -> PharmacovigilanceExecutionStats:
        route_counts: dict[PVRoute, int] = defaultdict(int)
        for row in decisions:
            route_counts[row.route] += 1

        actions_success = sum(1 for row in actions if row.success and row.status == "executed")
        actions_skipped = sum(1 for row in actions if row.status == "skipped")
        actions_failed = sum(1 for row in actions if not row.success)

        return PharmacovigilanceExecutionStats(
            signals_total=len(signals),
            enrichment_total=len(enrichments),
            enrichment_success=sum(1 for row in enrichments if row.success),
            actions_total=len(actions),
            actions_success=actions_success,
            actions_skipped=actions_skipped,
            actions_failed=actions_failed,
            lot_hold_count=route_counts["lot_hold_and_report"],
            urgent_review_count=route_counts["urgent_medical_review"],
            enhanced_monitor_count=route_counts["enhanced_monitoring"],
            monitor_count=route_counts["monitor"],
        )

    @staticmethod
    def _recommendations(
        *,
        pipeline_report: UseCaseExecutionReport,
        stats: PharmacovigilanceExecutionStats,
        decisions: list[PVDecision],
        errors: list[str],
    ) -> list[str]:
        recs: list[str] = [
            (
                f"Decision mix: lot_hold+report={stats.lot_hold_count}, urgent_review={stats.urgent_review_count}, "
                f"enhanced_monitoring={stats.enhanced_monitor_count}, monitor={stats.monitor_count}."
            ),
            (
                f"Enrichment success {stats.enrichment_success}/{stats.enrichment_total}; "
                f"actions success={stats.actions_success}, skipped={stats.actions_skipped}, failed={stats.actions_failed}."
            ),
            "For lot-hold cases, validate retained samples and distribution-level exposure counts.",
            "For urgent medical review cases, pre-assemble case narratives with chronology and dose details.",
            "For enhanced monitoring cases, tighten follow-up windows and signal recency weighting.",
        ]

        if pipeline_report.ranked_actions:
            recs.append(f"Primary tri-provider action: {pipeline_report.ranked_actions[0].action}")

        if errors:
            recs.append(
                "At least one integration failed; route affected signals to manual safety review queue."
            )

        top = decisions[:3]
        if top:
            recs.append(
                "Top-priority signals: "
                + ", ".join(
                    f"{row.signal_id}:{row.route}:{row.risk_score:.2f}:{row.serious_event_rate:.2f}"
                    for row in top
                )
                + "."
            )

        return recs
