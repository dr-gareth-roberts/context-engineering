"""Adaptive Learning — feedback loop that learns optimal scoring weights.

Observes which context items correlate with good model outputs and adjusts
scoring weights over time using Pearson correlation + EMA updates + L2
regularization.  Pythonic equivalent of the TypeScript ``ce-adaptive`` package.
"""

from __future__ import annotations

import copy
import json
import math
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol

from .core import (
    Budget,
    ContextItem,
    ContextPack,
    ScoringWeights,
    pack,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WEIGHT_MIN = 0.01
WEIGHT_MAX = 10.0
SCORING_DIMENSIONS = ("priority", "recency", "salience", "relevance")

DEFAULT_MIN_SAMPLES = 20
DEFAULT_LEARNING_RATE = 0.1
DEFAULT_REGULARIZATION = 0.01
DEFAULT_BASE_WEIGHTS = ScoringWeights(
    priority=1.0,
    recency=1.0,
    salience=1.0,
    relevance=1.0,
)

_id_counter = 0
_id_lock = threading.Lock()


def _generate_id() -> str:
    global _id_counter
    with _id_lock:
        _id_counter += 1
        cnt = _id_counter
    return f"opt_{int(time.time() * 1000)}_{cnt}"


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Outcome:
    """Result of a model invocation for feedback correlation."""

    quality: float  # 0-1
    accepted: bool | None = None
    latency: float | None = None
    response: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class ItemFeature:
    """Per-item scoring dimensions recorded at pack time."""

    item_id: str
    kind: str
    priority: float
    recency: float
    salience: float
    relevance: float
    tokens: int
    selected: bool


@dataclass
class FeedbackRecord:
    """A single pack + optional outcome observation."""

    id: str
    timestamp: float
    pack_id: str
    segment: str
    selected_item_ids: list[str]
    dropped_item_ids: list[str]
    item_features: list[ItemFeature]
    weights_used: ScoringWeights
    budget: int
    utilization: float
    outcome: Outcome | None = None


@dataclass
class KindInsight:
    """How a specific item ``kind`` correlates with output quality."""

    kind: str
    avg_quality_when_included: float
    avg_quality_when_excluded: float
    inclusion_lift: float
    count: int


@dataclass
class WeightInsights:
    """Learning analytics produced by :meth:`ContextOptimizer.get_insights`."""

    current_weights: ScoringWeights
    sample_count: int
    correlations: dict[str, float]
    recommended_weights: ScoringWeights
    confidence: float
    kind_insights: list[KindInsight]


@dataclass
class OptimizedPack:
    """Extends ContextPack fields with optimizer tracking."""

    budget: Budget
    selected: list[ContextItem]
    dropped: list[ContextItem]
    total_tokens: int
    optimizer_id: str
    weights_used: ScoringWeights


@dataclass
class OptimizerConfig:
    """Configuration for :class:`ContextOptimizer`."""

    feedback: Literal["implicit", "explicit", "metric"] = "explicit"
    quality_metric: Callable[[str, list[ContextItem]], float] | None = None
    min_samples: int = DEFAULT_MIN_SAMPLES
    learning_rate: float = DEFAULT_LEARNING_RATE
    regularization: float = DEFAULT_REGULARIZATION
    base_weights: ScoringWeights | None = None
    store: FeedbackStore | None = None
    segment: str = "default"


@dataclass
class OptimizerState:
    """Serialisable snapshot for export/import."""

    weights: ScoringWeights
    segment: str
    sample_count: int
    exported_at: float


# ---------------------------------------------------------------------------
# FeedbackStore protocol + implementations
# ---------------------------------------------------------------------------


class FeedbackStore(Protocol):
    """Storage backend for feedback records (sync)."""

    def save(self, record: FeedbackRecord) -> None: ...

    def update_outcome(self, pack_id: str, outcome: Outcome) -> None: ...

    def get_records(
        self, segment: str | None = None, limit: int | None = None
    ) -> list[FeedbackRecord]: ...

    def get_records_with_outcomes(self, segment: str | None = None) -> list[FeedbackRecord]: ...

    def clear(self, segment: str | None = None) -> None: ...


class InMemoryFeedbackStore:
    """List-backed store for testing."""

    def __init__(self) -> None:
        self._records: list[FeedbackRecord] = []
        self._lock = threading.Lock()

    def save(self, record: FeedbackRecord) -> None:
        with self._lock:
            self._records.append(copy.deepcopy(record))

    def update_outcome(self, pack_id: str, outcome: Outcome) -> None:
        with self._lock:
            for r in self._records:
                if r.pack_id == pack_id:
                    r.outcome = outcome
                    return

    def get_records(
        self, segment: str | None = None, limit: int | None = None
    ) -> list[FeedbackRecord]:
        with self._lock:
            result = list(self._records)
        if segment is not None:
            result = [r for r in result if r.segment == segment]
        result.sort(key=lambda r: r.timestamp, reverse=True)
        if limit is not None:
            result = result[:limit]
        return [copy.deepcopy(r) for r in result]

    def get_records_with_outcomes(self, segment: str | None = None) -> list[FeedbackRecord]:
        with self._lock:
            result = [r for r in self._records if r.outcome is not None]
        if segment is not None:
            result = [r for r in result if r.segment == segment]
        result.sort(key=lambda r: r.timestamp, reverse=True)
        return [copy.deepcopy(r) for r in result]

    def clear(self, segment: str | None = None) -> None:
        with self._lock:
            if segment is not None:
                self._records = [r for r in self._records if r.segment != segment]
            else:
                self._records = []


class FileFeedbackStore:
    """JSON-lines file store with advisory locking."""

    def __init__(
        self,
        file_path: str,
        lock_timeout: float = 5.0,
        stale_lock_age: float = 10.0,
        disable_locking: bool = False,
    ) -> None:
        self.file_path = file_path
        self._records: list[FeedbackRecord] = []
        self._loaded = False
        self._lock = threading.Lock()
        self._lock_timeout = lock_timeout
        self._stale_lock_age = stale_lock_age
        self._disable_locking = disable_locking
        self._lock_path = file_path + ".lock"

    # -- serialisation helpers -----------------------------------------------

    @staticmethod
    def _outcome_to_dict(o: Outcome) -> dict[str, Any]:
        d: dict[str, Any] = {"quality": o.quality}
        if o.accepted is not None:
            d["accepted"] = o.accepted
        if o.latency is not None:
            d["latency"] = o.latency
        if o.response is not None:
            d["response"] = o.response
        if o.metadata is not None:
            d["metadata"] = o.metadata
        return d

    @staticmethod
    def _outcome_from_dict(d: dict[str, Any]) -> Outcome:
        return Outcome(
            quality=d["quality"],
            accepted=d.get("accepted"),
            latency=d.get("latency"),
            response=d.get("response"),
            metadata=d.get("metadata"),
        )

    @staticmethod
    def _weights_to_dict(w: ScoringWeights) -> dict[str, float]:
        return {
            "priority": w.priority,
            "recency": w.recency,
            "salience": w.salience,
            "relevance": w.relevance,
            "cost": w.cost,
            "latency": w.latency,
            "relation_boost": w.relation_boost,
        }

    @staticmethod
    def _weights_from_dict(d: dict[str, Any]) -> ScoringWeights:
        return ScoringWeights(
            priority=d.get("priority", 1.0),
            recency=d.get("recency", 0.7),
            salience=d.get("salience", 0.5),
            relevance=d.get("relevance", 0.0),
            cost=d.get("cost", -0.3),
            latency=d.get("latency", -0.2),
            relation_boost=d.get("relation_boost", 2.0),
        )

    def _record_to_dict(self, r: FeedbackRecord) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": r.id,
            "timestamp": r.timestamp,
            "pack_id": r.pack_id,
            "segment": r.segment,
            "selected_item_ids": r.selected_item_ids,
            "dropped_item_ids": r.dropped_item_ids,
            "item_features": [
                {
                    "item_id": f.item_id,
                    "kind": f.kind,
                    "priority": f.priority,
                    "recency": f.recency,
                    "salience": f.salience,
                    "relevance": f.relevance,
                    "tokens": f.tokens,
                    "selected": f.selected,
                }
                for f in r.item_features
            ],
            "weights_used": self._weights_to_dict(r.weights_used),
            "budget": r.budget,
            "utilization": r.utilization,
        }
        if r.outcome is not None:
            d["outcome"] = self._outcome_to_dict(r.outcome)
        return d

    def _record_from_dict(self, d: dict[str, Any]) -> FeedbackRecord:
        return FeedbackRecord(
            id=d["id"],
            timestamp=d["timestamp"],
            pack_id=d["pack_id"],
            segment=d["segment"],
            selected_item_ids=d["selected_item_ids"],
            dropped_item_ids=d["dropped_item_ids"],
            item_features=[
                ItemFeature(
                    item_id=f["item_id"],
                    kind=f["kind"],
                    priority=f["priority"],
                    recency=f["recency"],
                    salience=f["salience"],
                    relevance=f["relevance"],
                    tokens=f["tokens"],
                    selected=f["selected"],
                )
                for f in d["item_features"]
            ],
            weights_used=self._weights_from_dict(d["weights_used"]),
            budget=d["budget"],
            utilization=d["utilization"],
            outcome=(self._outcome_from_dict(d["outcome"]) if "outcome" in d else None),
        )

    # -- file I/O ------------------------------------------------------------

    def _load(self) -> None:
        if self._loaded:
            return
        dirname = os.path.dirname(self.file_path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        if os.path.exists(self.file_path):
            with open(self.file_path, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        d = json.loads(stripped)
                        self._records.append(self._record_from_dict(d))
                    except Exception:
                        pass  # skip corrupted lines
        self._loaded = True

    def _persist(self) -> None:
        tmp_path = self.file_path + ".tmp"
        with open(tmp_path, "w") as f:
            for r in self._records:
                f.write(json.dumps(self._record_to_dict(r)) + "\n")
        os.replace(tmp_path, self.file_path)

    def _with_file_lock(self) -> "_FileLockContext":
        return _FileLockContext(self)

    # -- public API ----------------------------------------------------------

    def save(self, record: FeedbackRecord) -> None:
        with self._with_file_lock():
            with self._lock:
                self._load()
                self._records.append(copy.deepcopy(record))
                self._persist()

    def update_outcome(self, pack_id: str, outcome: Outcome) -> None:
        with self._with_file_lock():
            with self._lock:
                self._load()
                for r in self._records:
                    if r.pack_id == pack_id:
                        r.outcome = outcome
                        self._persist()
                        return

    def get_records(
        self, segment: str | None = None, limit: int | None = None
    ) -> list[FeedbackRecord]:
        with self._lock:
            self._load()
            result = list(self._records)
        if segment is not None:
            result = [r for r in result if r.segment == segment]
        result.sort(key=lambda r: r.timestamp, reverse=True)
        if limit is not None:
            result = result[:limit]
        return [copy.deepcopy(r) for r in result]

    def get_records_with_outcomes(self, segment: str | None = None) -> list[FeedbackRecord]:
        with self._lock:
            self._load()
            result = [r for r in self._records if r.outcome is not None]
        if segment is not None:
            result = [r for r in result if r.segment == segment]
        result.sort(key=lambda r: r.timestamp, reverse=True)
        return [copy.deepcopy(r) for r in result]

    def clear(self, segment: str | None = None) -> None:
        with self._with_file_lock():
            with self._lock:
                self._load()
                if segment is not None:
                    self._records = [r for r in self._records if r.segment != segment]
                else:
                    self._records = []
                self._persist()


class _FileLockContext:
    """Context-manager for advisory file locking (same pattern as FileStore in memory.py)."""

    def __init__(self, store: FileFeedbackStore) -> None:
        self._store = store

    def __enter__(self) -> None:
        if self._store._disable_locking:
            return
        backoff = 0.05
        deadline = time.monotonic() + self._store._lock_timeout
        while True:
            try:
                fd = os.open(self._store._lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(
                        fd,
                        f"pid={os.getpid()} ts={time.time()}\n".encode(),
                    )
                finally:
                    os.close(fd)
                return
            except FileExistsError:
                try:
                    mtime = os.path.getmtime(self._store._lock_path)
                    if time.time() - mtime > self._store._stale_lock_age:
                        try:
                            os.unlink(self._store._lock_path)
                        except FileNotFoundError:
                            pass
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"Could not acquire file lock {self._store._lock_path} "
                        f"within {self._store._lock_timeout}s"
                    )
                time.sleep(backoff)
                backoff = min(backoff * 2, 1.0)

    def __exit__(self, *_: Any) -> None:
        if self._store._disable_locking:
            return
        try:
            os.unlink(self._store._lock_path)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# WeightOptimizer — statistical engine
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    return sum((v - m) ** 2 for v in values) / len(values)


def _pearson_correlation(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    x_mean = _mean(xs)
    y_mean = _mean(ys)
    numerator = 0.0
    x_sum_sq = 0.0
    y_sum_sq = 0.0
    for i in range(n):
        dx = xs[i] - x_mean
        dy = ys[i] - y_mean
        numerator += dx * dy
        x_sum_sq += dx * dx
        y_sum_sq += dy * dy
    denominator = math.sqrt(x_sum_sq * y_sum_sq)
    if denominator == 0:
        return 0.0
    return numerator / denominator


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


class WeightOptimizer:
    """Computes optimal scoring weights from feedback using correlation analysis
    with exponential moving average updates.
    """

    def __init__(
        self,
        learning_rate: float,
        regularization: float,
        base_weights: ScoringWeights,
        min_samples: int,
    ) -> None:
        self.learning_rate = learning_rate
        self.regularization = regularization
        self.base_weights = base_weights
        self.min_samples = min_samples

    def optimize(self, records: list[FeedbackRecord]) -> ScoringWeights:
        """Return optimised weights, or base weights if insufficient samples."""
        with_outcomes = [r for r in records if r.outcome is not None]
        if len(with_outcomes) < self.min_samples:
            return ScoringWeights(
                priority=self.base_weights.priority,
                recency=self.base_weights.recency,
                salience=self.base_weights.salience,
                relevance=self.base_weights.relevance,
                cost=self.base_weights.cost,
                latency=self.base_weights.latency,
                relation_boost=self.base_weights.relation_boost,
            )

        correlations = self.compute_correlations(with_outcomes)
        current = ScoringWeights(
            priority=self.base_weights.priority,
            recency=self.base_weights.recency,
            salience=self.base_weights.salience,
            relevance=self.base_weights.relevance,
            cost=self.base_weights.cost,
            latency=self.base_weights.latency,
            relation_boost=self.base_weights.relation_boost,
        )

        lr = self.learning_rate
        reg = self.regularization

        for dim in SCORING_DIMENSIONS:
            base_val = getattr(self.base_weights, dim)
            cur_val = getattr(current, dim)
            signal = correlations.get(dim, 0.0)

            updated = (1 - lr) * cur_val + lr * (base_val + signal)
            updated -= reg * (updated - base_val)
            setattr(current, dim, _clamp(updated, WEIGHT_MIN, WEIGHT_MAX))

        return current

    def compute_correlations(self, records: list[FeedbackRecord]) -> dict[str, float]:
        """Pearson correlation between each dimension and quality."""
        with_outcomes = [r for r in records if r.outcome is not None]
        if len(with_outcomes) < 2:
            return {dim: 0.0 for dim in SCORING_DIMENSIONS}

        result: dict[str, float] = {}
        for dim in SCORING_DIMENSIONS:
            pairs_dim: list[float] = []
            pairs_quality: list[float] = []
            for record in with_outcomes:
                selected_features = [f for f in record.item_features if f.selected]
                if not selected_features:
                    continue
                avg_dim = _mean([getattr(f, dim) for f in selected_features])
                pairs_dim.append(avg_dim)
                pairs_quality.append(record.outcome.quality if record.outcome else 0.0)

            result[dim] = (
                _pearson_correlation(pairs_dim, pairs_quality) if len(pairs_dim) >= 2 else 0.0
            )
        return result

    def compute_kind_insights(self, records: list[FeedbackRecord]) -> list[KindInsight]:
        """Per-kind quality correlation analysis."""
        with_outcomes = [r for r in records if r.outcome is not None]
        if not with_outcomes:
            return []

        all_kinds: set[str] = set()
        for record in with_outcomes:
            for feature in record.item_features:
                all_kinds.add(feature.kind)

        insights: list[KindInsight] = []
        for kind in all_kinds:
            quality_when_included: list[float] = []
            quality_when_excluded: list[float] = []
            for record in with_outcomes:
                quality = record.outcome.quality if record.outcome else 0.0
                has_kind_selected = any(f.kind == kind and f.selected for f in record.item_features)
                if has_kind_selected:
                    quality_when_included.append(quality)
                else:
                    quality_when_excluded.append(quality)

            avg_included = _mean(quality_when_included)
            avg_excluded = _mean(quality_when_excluded)
            insights.append(
                KindInsight(
                    kind=kind,
                    avg_quality_when_included=avg_included,
                    avg_quality_when_excluded=avg_excluded,
                    inclusion_lift=avg_included - avg_excluded,
                    count=len(quality_when_included) + len(quality_when_excluded),
                )
            )
        insights.sort(key=lambda ki: ki.inclusion_lift, reverse=True)
        return insights

    def compute_confidence(self, records: list[FeedbackRecord]) -> float:
        """0-1 confidence based on sample size and quality variance."""
        with_outcomes = [r for r in records if r.outcome is not None]
        if not with_outcomes:
            return 0.0

        sample_factor = 1 - math.exp(-len(with_outcomes) / 50)

        qualities = [r.outcome.quality for r in with_outcomes if r.outcome]
        quality_variance = _variance(qualities)

        if quality_variance < 0.01:
            variance_factor = quality_variance / 0.01
        elif quality_variance > 0.25:
            variance_factor = max(0.0, 1 - (quality_variance - 0.25) / 0.25)
        else:
            variance_factor = 1.0

        return _clamp(sample_factor * variance_factor, 0.0, 1.0)


# ---------------------------------------------------------------------------
# ContextOptimizer — main entry point
# ---------------------------------------------------------------------------


def _build_item_features(
    all_items: list[ContextItem], selected_items: list[ContextItem]
) -> list[ItemFeature]:
    selected_ids = {i.id for i in selected_items}
    return [
        ItemFeature(
            item_id=item.id,
            kind=item.kind or "unknown",
            priority=item.priority or 0.0,
            recency=item.recency or 0.0,
            salience=float(item.metadata.get("salience", 0.0)),
            relevance=float(item.metadata.get("relevance", 0.0)),
            tokens=item.tokens or 0,
            selected=item.id in selected_ids,
        )
        for item in all_items
    ]


class ContextOptimizer:
    """Adaptive context optimizer that learns which scoring weights produce
    the best model outputs over time.
    """

    def __init__(self, config: OptimizerConfig) -> None:
        self._config = config
        self._store: FeedbackStore = config.store or InMemoryFeedbackStore()
        self._segment = config.segment
        base = config.base_weights or DEFAULT_BASE_WEIGHTS
        self._weight_optimizer = WeightOptimizer(
            learning_rate=config.learning_rate,
            regularization=config.regularization,
            base_weights=base,
            min_samples=config.min_samples,
        )
        self._learned_weights: ScoringWeights | None = None

    # -- public API ----------------------------------------------------------

    def pack(
        self,
        items: list[ContextItem],
        budget: Budget,
        *,
        weights: ScoringWeights | None = None,
    ) -> OptimizedPack:
        """Pack items with learned weights, recording feedback for later analysis."""
        optimizer_id = _generate_id()
        learned = self._get_current_weights()
        merged = _merge_weights(learned, weights)

        result: ContextPack = pack(items, budget, weights=merged)

        item_features = _build_item_features(items, result.selected)

        record = FeedbackRecord(
            id=_generate_id(),
            timestamp=time.time(),
            pack_id=optimizer_id,
            segment=self._segment,
            selected_item_ids=[i.id for i in result.selected],
            dropped_item_ids=[i.id for i in result.dropped],
            item_features=item_features,
            weights_used=merged,
            budget=budget.max_tokens,
            utilization=(result.total_tokens / budget.max_tokens if budget.max_tokens > 0 else 0),
        )
        self._store.save(record)

        return OptimizedPack(
            budget=result.budget,
            selected=result.selected,
            dropped=result.dropped,
            total_tokens=result.total_tokens,
            optimizer_id=optimizer_id,
            weights_used=merged,
        )

    def report_outcome(self, optimizer_id: str, outcome: Outcome) -> None:
        """Report the outcome of a previous pack to feed the learning loop."""
        self._store.update_outcome(optimizer_id, outcome)
        self._learned_weights = None  # invalidate cache

    def get_insights(self) -> WeightInsights:
        """Return current learning analytics."""
        records = self._store.get_records_with_outcomes(segment=self._segment)
        correlations = self._weight_optimizer.compute_correlations(records)
        recommended = self._weight_optimizer.optimize(records)
        confidence = self._weight_optimizer.compute_confidence(records)
        kind_insights = self._weight_optimizer.compute_kind_insights(records)

        return WeightInsights(
            current_weights=self._get_current_weights(),
            sample_count=len(records),
            correlations={
                "priority": correlations.get("priority", 0.0),
                "recency": correlations.get("recency", 0.0),
                "salience": correlations.get("salience", 0.0),
                "relevance": correlations.get("relevance", 0.0),
            },
            recommended_weights=recommended,
            confidence=confidence,
            kind_insights=kind_insights,
        )

    def reset(self) -> None:
        """Clear all feedback for this segment and reset learned weights."""
        self._store.clear(self._segment)
        self._learned_weights = None

    def export_state(self) -> OptimizerState:
        """Export current state for persistence or sharing."""
        records = self._store.get_records_with_outcomes(segment=self._segment)
        return OptimizerState(
            weights=self._weight_optimizer.optimize(records),
            segment=self._segment,
            sample_count=len(records),
            exported_at=time.time(),
        )

    def import_state(self, state: OptimizerState) -> None:
        """Import previously exported state, setting learned weights directly."""
        self._learned_weights = ScoringWeights(
            priority=state.weights.priority,
            recency=state.weights.recency,
            salience=state.weights.salience,
            relevance=state.weights.relevance,
            cost=state.weights.cost,
            latency=state.weights.latency,
            relation_boost=state.weights.relation_boost,
        )

    # -- internals -----------------------------------------------------------

    def _get_current_weights(self) -> ScoringWeights:
        if self._learned_weights is not None:
            return ScoringWeights(
                priority=self._learned_weights.priority,
                recency=self._learned_weights.recency,
                salience=self._learned_weights.salience,
                relevance=self._learned_weights.relevance,
                cost=self._learned_weights.cost,
                latency=self._learned_weights.latency,
                relation_boost=self._learned_weights.relation_boost,
            )
        records = self._store.get_records_with_outcomes(segment=self._segment)
        weights = self._weight_optimizer.optimize(records)
        self._learned_weights = weights
        return ScoringWeights(
            priority=weights.priority,
            recency=weights.recency,
            salience=weights.salience,
            relevance=weights.relevance,
            cost=weights.cost,
            latency=weights.latency,
            relation_boost=weights.relation_boost,
        )


def _merge_weights(learned: ScoringWeights, overrides: ScoringWeights | None) -> ScoringWeights:
    """Merge learned weights with user-provided overrides."""
    if overrides is None:
        return learned
    return ScoringWeights(
        priority=overrides.priority,
        recency=overrides.recency,
        salience=overrides.salience,
        relevance=overrides.relevance,
        cost=overrides.cost,
        latency=overrides.latency,
        relation_boost=overrides.relation_boost,
    )


def create_context_optimizer(
    feedback: Literal["implicit", "explicit", "metric"] = "explicit",
    min_samples: int = DEFAULT_MIN_SAMPLES,
    learning_rate: float = DEFAULT_LEARNING_RATE,
    regularization: float = DEFAULT_REGULARIZATION,
    store: FeedbackStore | None = None,
    base_weights: ScoringWeights | None = None,
    segment: str = "default",
    quality_metric: Callable[[str, list[ContextItem]], float] | None = None,
) -> ContextOptimizer:
    """Convenience factory for :class:`ContextOptimizer`."""
    return ContextOptimizer(
        OptimizerConfig(
            feedback=feedback,
            min_samples=min_samples,
            learning_rate=learning_rate,
            regularization=regularization,
            store=store,
            base_weights=base_weights,
            segment=segment,
            quality_metric=quality_metric,
        )
    )
