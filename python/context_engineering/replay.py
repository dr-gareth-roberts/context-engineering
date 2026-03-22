"""Context Replay — record pack decisions and A/B test strategies.

Usage::

    from context_engineering.replay import ContextRecorder, replay, ReplayVariant

    recorder = ContextRecorder()
    recorder.record(
        model="gpt-4o",
        items=items,
        budget=Budget(max_tokens=4096),
        result=pack_result,
        response="model output text",
        quality_score=0.85,
    )

    report = replay(
        recordings=recorder.get_recordings(),
        variants=[
            ReplayVariant(name="baseline"),
            ReplayVariant(name="recency-heavy", weights=ScoringWeights(priority=0.5, recency=2.0)),
            ReplayVariant(name="tight-budget", budget=Budget(max_tokens=2048)),
        ],
    )
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .core import Budget, ContextItem, ContextPack, ScoringWeights, pack


@dataclass
class ContextRecording:
    """A single recorded pack decision with optional quality feedback."""

    id: str
    timestamp: float
    model: str
    items: list[ContextItem]
    budget: Budget
    weights_used: ScoringWeights | None
    result: ContextPack
    response: str | None = None
    quality_score: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class ReplayVariant:
    """A variant configuration for A/B testing pack strategies."""

    name: str
    budget: Budget | None = None
    weights: ScoringWeights | None = None


@dataclass
class ReplayResult:
    """Result of replaying a single recording with a single variant."""

    recording_id: str
    variant_name: str
    original_tokens: int
    new_tokens: int
    token_delta: int
    newly_selected: list[str]
    newly_dropped: list[str]
    utilization: float


@dataclass
class VariantSummary:
    """Aggregated results for a single variant across all recordings."""

    name: str
    avg_token_delta: float
    avg_utilization: float
    recordings_affected: int
    results: list[ReplayResult]


@dataclass
class ReplayReport:
    """Full report from replaying recordings across multiple variants."""

    timestamp: float
    recording_count: int
    variants: list[VariantSummary]


class ContextRecorder:
    """Records pack decisions for later replay and analysis."""

    def __init__(self) -> None:
        self._recordings: list[ContextRecording] = []

    def record(
        self,
        model: str,
        items: list[ContextItem],
        budget: Budget,
        result: ContextPack,
        response: str | None = None,
        quality_score: float | None = None,
        metadata: dict[str, Any] | None = None,
        weights: ScoringWeights | None = None,
    ) -> ContextRecording:
        """Record a pack decision.

        Args:
            model: The model name used for the request.
            items: The input context items before packing.
            budget: The budget used for packing.
            result: The pack result.
            response: Optional model response text.
            quality_score: Optional quality score (0.0-1.0).
            metadata: Optional metadata dict.
            weights: Optional scoring weights used during packing.

        Returns:
            The created ContextRecording.
        """
        recording = ContextRecording(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            model=model,
            items=list(items),
            budget=budget,
            weights_used=weights,
            result=result,
            response=response,
            quality_score=quality_score,
            metadata=metadata,
        )
        self._recordings.append(recording)
        return recording

    def get_recordings(self) -> list[ContextRecording]:
        """Return all recordings."""
        return list(self._recordings)

    def get_recording(self, recording_id: str) -> ContextRecording | None:
        """Return a single recording by ID, or None if not found."""
        for rec in self._recordings:
            if rec.id == recording_id:
                return rec
        return None

    def score_recording(self, recording_id: str, quality_score: float) -> None:
        """Update the quality score for a recording after the fact.

        Args:
            recording_id: The recording ID to update.
            quality_score: The quality score (0.0-1.0).

        Raises:
            ValueError: If the recording ID is not found.
        """
        for rec in self._recordings:
            if rec.id == recording_id:
                rec.quality_score = quality_score
                return
        raise ValueError(f"Recording not found: {recording_id}")

    def save(self) -> str:
        """Serialize all recordings to JSON.

        Returns:
            A JSON string containing all recordings.
        """
        data = []
        for rec in self._recordings:
            data.append(_recording_to_dict(rec))
        return json.dumps(data, default=str)

    def load(self, data: str) -> None:
        """Load recordings from JSON, appending to existing recordings.

        Args:
            data: A JSON string produced by :meth:`save`.
        """
        entries = json.loads(data)
        for entry in entries:
            recording = _recording_from_dict(entry)
            self._recordings.append(recording)


def _recording_to_dict(rec: ContextRecording) -> dict[str, Any]:
    """Convert a ContextRecording to a serializable dict."""
    weights_dict = None
    if rec.weights_used is not None:
        weights_dict = {
            "priority": rec.weights_used.priority,
            "recency": rec.weights_used.recency,
            "salience": rec.weights_used.salience,
            "relevance": rec.weights_used.relevance,
            "cost": rec.weights_used.cost,
            "latency": rec.weights_used.latency,
            "relation_boost": rec.weights_used.relation_boost,
        }

    return {
        "id": rec.id,
        "timestamp": rec.timestamp,
        "model": rec.model,
        "items": [item.model_dump() for item in rec.items],
        "budget": rec.budget.model_dump(by_alias=True),
        "weights_used": weights_dict,
        "result": rec.result.model_dump(by_alias=True),
        "response": rec.response,
        "quality_score": rec.quality_score,
        "metadata": rec.metadata,
    }


def _recording_from_dict(data: dict[str, Any]) -> ContextRecording:
    """Reconstruct a ContextRecording from a dict."""
    weights = None
    if data.get("weights_used") is not None:
        weights = ScoringWeights(**data["weights_used"])

    items = [ContextItem.model_validate(item) for item in data.get("items", [])]
    budget = Budget.model_validate(data["budget"])
    result = ContextPack.model_validate(data["result"])

    return ContextRecording(
        id=data["id"],
        timestamp=data["timestamp"],
        model=data["model"],
        items=items,
        budget=budget,
        weights_used=weights,
        result=result,
        response=data.get("response"),
        quality_score=data.get("quality_score"),
        metadata=data.get("metadata"),
    )


def _replay_single(
    recording: ContextRecording,
    variant: ReplayVariant,
) -> ReplayResult:
    """Replay a single recording with a single variant configuration."""
    # Use variant budget or fall back to original
    budget = variant.budget if variant.budget is not None else recording.budget
    weights = variant.weights if variant.weights is not None else recording.weights_used

    # Re-pack with the variant's configuration
    new_result = pack(recording.items, budget, weights=weights)

    original_tokens = recording.result.total_tokens
    new_tokens = new_result.total_tokens
    token_delta = new_tokens - original_tokens

    original_ids = {item.id for item in recording.result.selected}
    new_ids = {item.id for item in new_result.selected}

    newly_selected = sorted(new_ids - original_ids)
    newly_dropped = sorted(original_ids - new_ids)

    effective_max = budget.max_tokens - (budget.reserve_tokens or 0)
    utilization = (new_tokens / effective_max * 100) if effective_max > 0 else 0.0

    return ReplayResult(
        recording_id=recording.id,
        variant_name=variant.name,
        original_tokens=original_tokens,
        new_tokens=new_tokens,
        token_delta=token_delta,
        newly_selected=newly_selected,
        newly_dropped=newly_dropped,
        utilization=round(utilization, 1),
    )


def replay(
    recordings: list[ContextRecording],
    variants: list[ReplayVariant],
) -> ReplayReport:
    """Replay recorded pack decisions with different variant configurations.

    For each variant, every recording is re-packed with the variant's budget
    and/or weights. The report summarizes token deltas, utilization changes,
    and selection differences.

    Args:
        recordings: List of recorded pack decisions.
        variants: List of variant configurations to test.

    Returns:
        A :class:`ReplayReport` with per-variant summaries.

    Example::

        report = replay(
            recordings=recorder.get_recordings(),
            variants=[
                ReplayVariant(name="baseline"),
                ReplayVariant(name="tight", budget=Budget(max_tokens=2048)),
            ],
        )
        for v in report.variants:
            print(f"{v.name}: avg_token_delta={v.avg_token_delta}")
    """
    variant_summaries: list[VariantSummary] = []

    for variant in variants:
        results: list[ReplayResult] = []

        for recording in recordings:
            result = _replay_single(recording, variant)
            results.append(result)

        if results:
            avg_token_delta = sum(r.token_delta for r in results) / len(results)
            avg_utilization = sum(r.utilization for r in results) / len(results)
            recordings_affected = sum(1 for r in results if r.newly_selected or r.newly_dropped)
        else:
            avg_token_delta = 0.0
            avg_utilization = 0.0
            recordings_affected = 0

        variant_summaries.append(
            VariantSummary(
                name=variant.name,
                avg_token_delta=round(avg_token_delta, 1),
                avg_utilization=round(avg_utilization, 1),
                recordings_affected=recordings_affected,
                results=results,
            )
        )

    return ReplayReport(
        timestamp=time.time(),
        recording_count=len(recordings),
        variants=variant_summaries,
    )
