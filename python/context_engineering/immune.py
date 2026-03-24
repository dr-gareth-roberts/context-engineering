"""Context Immune System -- learns from past context failures and develops antibodies.

Individual context items can be fine, but certain *combinations* are toxic.
The immune system learns these toxic patterns and screens future context packs
to prevent the same failure modes from recurring.

Mirrors the TypeScript ``@context-engineering/immune`` package.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Set

from .core import Budget, ContextItem

# ---------------------------------------------------------------------------
# Internal counter for deterministic IDs
# ---------------------------------------------------------------------------

_antibody_counter = 0


def _next_antibody_id() -> str:
    global _antibody_counter
    _antibody_counter += 1
    return f"ab-{_antibody_counter}"


def reset_id_counter() -> None:
    """Reset the internal antibody ID counter (useful for testing)."""
    global _antibody_counter
    _antibody_counter = 0


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class Stats:
    """Basic statistical summary of a numeric distribution."""

    min: float = 0.0
    max: float = 0.0
    mean: float = 0.0
    std: float = 0.0


@dataclass
class Fingerprint:
    """Feature vector extracted from a set of context items."""

    kinds_present: List[str] = field(default_factory=list)
    kind_ratios: Dict[str, float] = field(default_factory=dict)
    priority_stats: Stats = field(default_factory=Stats)
    recency_stats: Stats = field(default_factory=Stats)
    token_utilization: float = 0.0
    item_count: int = 0
    staleness_ratio: float = 0.0
    redundancy_estimate: float = 0.0


@dataclass
class Antibody:
    """A learned rule that matches a toxic context pattern."""

    id: str = ""
    pattern: Fingerprint = field(default_factory=Fingerprint)
    symptom: str = ""
    diagnosis: str = ""
    severity: Literal["warning", "block"] = "warning"
    created_at: float = 0.0
    match_threshold: float = 0.7


@dataclass
class FailureRecord:
    """A record of a context configuration that caused a failure."""

    items: List[ContextItem] = field(default_factory=list)
    budget: Budget = field(default_factory=lambda: Budget(maxTokens=4000))
    symptom: str = ""
    diagnosis: Optional[str] = None
    severity: Optional[Literal["warning", "block"]] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class ScreeningAlert:
    """An alert generated when a screening matches an antibody."""

    antibody_id: str = ""
    similarity: float = 0.0
    symptom: str = ""
    diagnosis: str = ""
    severity: Literal["warning", "block"] = "warning"


@dataclass
class ScreeningResult:
    """The result of screening a context configuration."""

    safe: bool = True
    warnings: List[ScreeningAlert] = field(default_factory=list)
    blocked: List[ScreeningAlert] = field(default_factory=list)
    antibodies_fired: List[Antibody] = field(default_factory=list)


@dataclass
class ImmuneSystemConfig:
    """Configuration for the immune system."""

    match_threshold: float = 0.7
    max_antibodies: int = 100
    on_alert: Optional[Callable[[ScreeningResult], None]] = None


@dataclass
class ImmuneSystemState:
    """Serializable state for persistence."""

    antibodies: List[Antibody] = field(default_factory=list)
    failure_count: int = 0


# ---------------------------------------------------------------------------
# Fingerprint extraction
# ---------------------------------------------------------------------------


def compute_stats(values: List[float]) -> Stats:
    """Compute basic statistics for a list of numbers."""
    if not values:
        return Stats()

    min_val = min(values)
    max_val = max(values)
    mean_val = sum(values) / len(values)
    variance = sum((v - mean_val) ** 2 for v in values) / len(values)
    std_val = math.sqrt(variance)
    return Stats(min=min_val, max=max_val, mean=mean_val, std=std_val)


def _word_set(content: str) -> Set[str]:
    """Extract a set of lowercased words from content."""
    return set(content.lower().split())


def _jaccard_similarity(a: Set[str], b: Set[str]) -> float:
    """Compute Jaccard similarity between two word sets."""
    if not a and not b:
        return 1.0
    intersection = len(a & b)
    union = len(a | b)
    if union == 0:
        return 1.0
    return intersection / union


def extract_fingerprint(items: List[ContextItem], budget: Optional[Budget] = None) -> Fingerprint:
    """Extract a feature vector from a set of context items."""
    if not items:
        return Fingerprint()

    # Kinds
    kind_counts: Dict[str, int] = {}
    for item in items:
        kind = item.kind or "unknown"
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    kinds_present = sorted(kind_counts.keys())
    kind_ratios = {k: v / len(items) for k, v in kind_counts.items()}

    # Priority and recency distributions
    priorities = [item.priority if item.priority is not None else 0.5 for item in items]
    recencies = [item.recency if item.recency is not None else 0.5 for item in items]
    priority_stats = compute_stats(priorities)
    recency_stats = compute_stats(recencies)

    # Token utilization
    total_tokens = 0
    for item in items:
        total_tokens += item.tokens if item.tokens is not None else max(1, len(item.content) // 4)
    max_tokens = budget.max_tokens if budget else total_tokens
    token_utilization = min(total_tokens / max_tokens, 1.0) if max_tokens > 0 else 0.0

    # Staleness ratio: fraction of items with recency < 0.2
    stale_count = sum(
        1 for item in items if (item.recency if item.recency is not None else 0.5) < 0.2
    )
    staleness_ratio = stale_count / len(items)

    # Redundancy estimate: O(n^2) pairwise Jaccard, capped at 50 items
    capped = items[:50]
    word_sets = [_word_set(item.content) for item in capped]
    redundant_items: Set[int] = set()
    for i in range(len(word_sets)):
        for j in range(i + 1, len(word_sets)):
            if _jaccard_similarity(word_sets[i], word_sets[j]) > 0.8:
                redundant_items.add(i)
                redundant_items.add(j)
    redundancy_estimate = len(redundant_items) / len(capped) if capped else 0.0

    return Fingerprint(
        kinds_present=kinds_present,
        kind_ratios=kind_ratios,
        priority_stats=priority_stats,
        recency_stats=recency_stats,
        token_utilization=token_utilization,
        item_count=len(items),
        staleness_ratio=staleness_ratio,
        redundancy_estimate=redundancy_estimate,
    )


# ---------------------------------------------------------------------------
# Fingerprint comparison
# ---------------------------------------------------------------------------


def _kind_ratio_cosine_similarity(a: Dict[str, float], b: Dict[str, float]) -> float:
    """Cosine similarity between two kind-ratio vectors."""
    all_keys = set(a.keys()) | set(b.keys())
    if not all_keys:
        return 1.0

    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in all_keys)
    norm_a = math.sqrt(sum(a.get(k, 0.0) ** 2 for k in all_keys))
    norm_b = math.sqrt(sum(b.get(k, 0.0) ** 2 for k in all_keys))
    denom = norm_a * norm_b
    if denom == 0:
        return 1.0
    return dot / denom


def _stats_similarity(a: Stats, b: Stats) -> float:
    """1 - normalized Euclidean distance between two Stats."""
    diffs = [a.min - b.min, a.max - b.max, a.mean - b.mean, a.std - b.std]
    distance = math.sqrt(sum(d * d for d in diffs))
    normalized = distance / 2.0
    return max(0.0, 1.0 - normalized)


def compare_fingerprints(a: Fingerprint, b: Fingerprint) -> float:
    """Compare two fingerprints, returning a 0-1 similarity score."""
    weights = {
        "kind_ratios": 0.20,
        "priority_stats": 0.15,
        "recency_stats": 0.15,
        "token_utilization": 0.15,
        "item_count": 0.10,
        "staleness_ratio": 0.10,
        "redundancy_estimate": 0.15,
    }

    kind_sim = _kind_ratio_cosine_similarity(a.kind_ratios, b.kind_ratios)
    priority_sim = _stats_similarity(a.priority_stats, b.priority_stats)
    recency_sim = _stats_similarity(a.recency_stats, b.recency_stats)
    token_sim = 1.0 - abs(a.token_utilization - b.token_utilization)
    max_count = max(a.item_count, b.item_count)
    item_count_sim = 1.0 - abs(a.item_count - b.item_count) / max_count if max_count > 0 else 1.0
    staleness_sim = 1.0 - abs(a.staleness_ratio - b.staleness_ratio)
    redundancy_sim = 1.0 - abs(a.redundancy_estimate - b.redundancy_estimate)

    return (
        weights["kind_ratios"] * kind_sim
        + weights["priority_stats"] * priority_sim
        + weights["recency_stats"] * recency_sim
        + weights["token_utilization"] * token_sim
        + weights["item_count"] * item_count_sim
        + weights["staleness_ratio"] * staleness_sim
        + weights["redundancy_estimate"] * redundancy_sim
    )


# ---------------------------------------------------------------------------
# Antibodies
# ---------------------------------------------------------------------------


def create_antibody(record: FailureRecord, threshold: Optional[float] = None) -> Antibody:
    """Create an antibody from a failure record."""
    import time

    pattern = extract_fingerprint(record.items, record.budget)
    return Antibody(
        id=_next_antibody_id(),
        pattern=pattern,
        symptom=record.symptom,
        diagnosis=record.diagnosis or "Unknown cause",
        severity=record.severity or "warning",
        created_at=time.time(),
        match_threshold=threshold if threshold is not None else 0.7,
    )


def match_antibody(antibody: Antibody, fingerprint: Fingerprint) -> Dict[str, Any]:
    """Check whether an antibody matches a fingerprint.

    Returns ``{"matches": bool, "similarity": float}``.
    """
    similarity = compare_fingerprints(antibody.pattern, fingerprint)
    return {"matches": similarity >= antibody.match_threshold, "similarity": similarity}


# ---------------------------------------------------------------------------
# Immune System
# ---------------------------------------------------------------------------


class ImmuneSystem:
    """Context Immune System that learns from failures and screens context packs."""

    def __init__(self, config: Optional[ImmuneSystemConfig] = None) -> None:
        cfg = config or ImmuneSystemConfig()
        self._match_threshold = cfg.match_threshold
        self._max_antibodies = cfg.max_antibodies
        self._on_alert = cfg.on_alert
        self._antibodies: List[Antibody] = []
        self._failure_count = 0

    def _prune_if_needed(self) -> None:
        if len(self._antibodies) > self._max_antibodies:
            self._antibodies.sort(key=lambda ab: ab.created_at)
            self._antibodies = self._antibodies[len(self._antibodies) - self._max_antibodies :]

    def record_failure(self, record: FailureRecord) -> Antibody:
        """Record a context failure and create an antibody."""
        self._failure_count += 1
        antibody = create_antibody(record, self._match_threshold)
        self._antibodies.append(antibody)
        self._prune_if_needed()
        return antibody

    def screen(
        self,
        items: List[ContextItem],
        budget: Optional[Budget] = None,
    ) -> ScreeningResult:
        """Screen a set of items against known failure patterns."""
        fingerprint = extract_fingerprint(items, budget)

        warnings: List[ScreeningAlert] = []
        blocked: List[ScreeningAlert] = []
        antibodies_fired: List[Antibody] = []

        for antibody in self._antibodies:
            result = match_antibody(antibody, fingerprint)
            if result["matches"]:
                alert = ScreeningAlert(
                    antibody_id=antibody.id,
                    similarity=result["similarity"],
                    symptom=antibody.symptom,
                    diagnosis=antibody.diagnosis,
                    severity=antibody.severity,
                )
                antibodies_fired.append(antibody)
                if antibody.severity == "block":
                    blocked.append(alert)
                else:
                    warnings.append(alert)

        screening_result = ScreeningResult(
            safe=len(blocked) == 0,
            warnings=warnings,
            blocked=blocked,
            antibodies_fired=antibodies_fired,
        )

        if (warnings or blocked) and self._on_alert:
            self._on_alert(screening_result)

        return screening_result

    def get_antibodies(self) -> List[Antibody]:
        """Return a copy of all antibodies."""
        return list(self._antibodies)

    def remove_antibody(self, antibody_id: str) -> bool:
        """Remove an antibody by ID. Returns True if found."""
        for i, ab in enumerate(self._antibodies):
            if ab.id == antibody_id:
                self._antibodies.pop(i)
                return True
        return False

    def reset(self) -> None:
        """Reset all antibodies and failure count."""
        self._antibodies = []
        self._failure_count = 0

    def export_state(self) -> ImmuneSystemState:
        """Export state for persistence."""
        return ImmuneSystemState(
            antibodies=list(self._antibodies),
            failure_count=self._failure_count,
        )

    def import_state(self, state: ImmuneSystemState) -> None:
        """Import previously exported state."""
        self._antibodies = list(state.antibodies)
        self._failure_count = state.failure_count
        self._prune_if_needed()


def create_immune_system(
    config: Optional[ImmuneSystemConfig] = None,
) -> ImmuneSystem:
    """Create a new Context Immune System."""
    return ImmuneSystem(config)
