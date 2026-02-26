"""
Composable Context Pipeline

A fluent builder API that chains context engineering operations
into a single, readable pipeline. This is the primary DX surface
for the library — it composes all the individual pieces.

Example:
    from context_engineering import pipeline

    result = (pipeline(8000)
        .add(system_prompt, tool_defs)
        .add_many(rag_results, kind="retrieval")
        .allocate([
            KindAllocation(kind="system", target_ratio=0.15, min_tokens=500),
            KindAllocation(kind="retrieval", target_ratio=0.50),
            KindAllocation(kind="conversation", target_ratio=0.35),
        ])
        .cache_topology(provider="anthropic")
        .quality_gate(min_overall=0.7)
        .build())

    print(result.selected)
    print(result.total_tokens)
    print(result.quality)
    print(result.cache_key)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from .allocation import KindAllocation, pack_with_allocation
from .bridge import BridgeOptions, memory_to_context
from .cache_topology import CacheConfig, pack_with_cache_topology
from .core import Budget, ContextItem, estimate_tokens, pack
from .memory import MemoryItem
from .placement import place_items
from .quality import ContextQuality, analyze_context
from .session import ContextSession, SessionDelta


@dataclass
class PipelineResult:
    """Result of a pipeline build."""

    selected: List[ContextItem]
    dropped: List[ContextItem]
    total_tokens: int
    budget: Budget
    quality: Optional[ContextQuality] = None
    cache_key: Optional[str] = None
    cache_efficiency: Optional[float] = None
    cacheable_tokens: Optional[int] = None
    delta: Optional[SessionDelta] = None
    allocations: Optional[Dict[str, Any]] = None
    allocation_efficiency: Optional[float] = None
    input_count: int = 0
    stages: List[str] = field(default_factory=list)


class ContextPipeline:
    """A composable pipeline for context engineering.

    Methods can be chained in any order. The pipeline resolves
    at .build() time, applying stages in the correct order.
    """

    def __init__(self, budget: Union[Budget, int]):
        self._budget = Budget(max_tokens=budget) if isinstance(budget, int) else budget
        self._items: List[ContextItem] = []
        self._pack_options: Dict[str, Any] = {}

        self._allocation_config: Optional[List[KindAllocation]] = None
        self._cache_topology_config: Optional[CacheConfig] = None
        self._placement_config: Optional[Dict[str, Any]] = None
        self._quality_config: Optional[Dict[str, Any]] = None
        self._session_instance: Optional[ContextSession] = None
        self._stages_applied: List[str] = []

    def add(self, *items: ContextItem) -> "ContextPipeline":
        """Add one or more context items directly."""
        self._items.extend(items)
        return self

    def add_many(self, items: List[ContextItem], **defaults: Any) -> "ContextPipeline":
        """Add many items with optional default properties."""
        for item in items:
            merged = item.model_copy(update={k: v for k, v in defaults.items() if v is not None})
            self._items.append(merged)
        return self

    def add_memories(
        self, memories: List[MemoryItem], options: Optional[BridgeOptions] = None
    ) -> "ContextPipeline":
        """Bridge memory items into context items and add them."""
        context_items = memory_to_context(memories, options)
        self._items.extend(context_items)
        self._stages_applied.append("bridge")
        return self

    def allocate(self, allocations: List[KindAllocation]) -> "ContextPipeline":
        """Configure kind-aware budget allocation."""
        self._allocation_config = allocations
        return self

    def cache_topology(
        self, provider: Optional[str] = None, mark_breakpoints: bool = False
    ) -> "ContextPipeline":
        """Configure cache-topology-aware packing."""
        self._cache_topology_config = CacheConfig(
            provider=provider, mark_breakpoints=mark_breakpoints
        )
        return self

    def place(
        self, strategy: str = "score-order", model: Optional[str] = None
    ) -> "ContextPipeline":
        """Configure attention-aware placement."""
        self._placement_config = {"strategy": strategy, "model": model}
        return self

    def quality_gate(
        self, min_overall: Optional[float] = None, warn: bool = False
    ) -> "ContextPipeline":
        """Add a quality gate."""
        self._quality_config = {"min_overall": min_overall, "warn": warn}
        return self

    def session(self, session: ContextSession) -> "ContextPipeline":
        """Attach a session for differential context tracking."""
        self._session_instance = session
        return self

    def weights(
        self, priority: float = 1.0, recency: float = 0.0, salience: float = 0.0
    ) -> "ContextPipeline":
        """Set scoring weights."""
        self._pack_options["weights"] = {
            "priority": priority,
            "recency": recency,
            "salience": salience,
        }
        return self

    def build(self) -> PipelineResult:
        """Build the pipeline and return the result."""
        input_count = len(self._items)
        stages = list(self._stages_applied)

        # Ensure all items have token estimates
        items = []
        for item in self._items:
            if item.tokens is None:
                item = item.model_copy(update={"tokens": estimate_tokens(item.content)})
            items.append(item)

        selected: List[ContextItem] = []
        dropped: List[ContextItem] = []
        total_tokens = 0
        cache_key = None
        cache_efficiency = None
        cacheable_tokens = None
        allocations = None
        allocation_efficiency = None

        # Stage 1: Pack (allocation -> cache topology -> standard)
        if self._allocation_config:
            stages.append("allocate")
            result = pack_with_allocation(items, self._budget, self._allocation_config)
            selected = list(result.selected)
            dropped = list(result.dropped)
            total_tokens = result.total_tokens
            allocations = {k: v.__dict__ for k, v in result.allocations.items()}
            allocation_efficiency = result.allocation_efficiency

            if self._cache_topology_config:
                stages.append("cacheTopology")
                cache_result = pack_with_cache_topology(
                    selected,
                    Budget(max_tokens=total_tokens + 100),
                    cache_config=self._cache_topology_config,
                )
                selected = list(cache_result.selected)
                cache_key = cache_result.cache_key
                cache_efficiency = cache_result.cache_efficiency
                cacheable_tokens = cache_result.cacheable_tokens

        elif self._cache_topology_config:
            stages.append("cacheTopology")
            result = pack_with_cache_topology(
                items,
                self._budget,
                cache_config=self._cache_topology_config,
            )
            selected = list(result.selected)
            dropped = list(result.dropped)
            total_tokens = result.total_tokens
            cache_key = result.cache_key
            cache_efficiency = result.cache_efficiency
            cacheable_tokens = result.cacheable_tokens

        else:
            stages.append("pack")
            result = pack(items, self._budget)
            selected = list(result.selected)
            dropped = list(result.dropped)
            total_tokens = result.total_tokens

        # Stage 2: Placement
        if self._placement_config:
            stages.append("place")
            selected = place_items(
                selected,
                strategy=self._placement_config.get("strategy", "score-order"),
                model=self._placement_config.get("model"),
            )

        # Stage 3: Quality gate
        quality = None
        if self._quality_config is not None:
            stages.append("quality")
            quality = analyze_context(selected)

            min_overall = self._quality_config.get("min_overall")
            if min_overall is not None and quality.overall < min_overall and len(selected) > 1:
                while len(selected) > 1 and quality.overall < min_overall:
                    removed = selected.pop()
                    dropped.append(removed)
                    total_tokens -= removed.tokens or 0
                    quality = analyze_context(selected)

        # Stage 4: Session tracking
        delta = None
        if self._session_instance:
            stages.append("session")
            self._session_instance.set_items(selected)
            session_result = self._session_instance.compile()
            delta = session_result.delta

        return PipelineResult(
            selected=selected,
            dropped=dropped,
            total_tokens=total_tokens,
            budget=self._budget,
            quality=quality,
            cache_key=cache_key,
            cache_efficiency=cache_efficiency,
            cacheable_tokens=cacheable_tokens,
            delta=delta,
            allocations=allocations,
            allocation_efficiency=allocation_efficiency,
            input_count=input_count,
            stages=stages,
        )


def create_pipeline(budget: Union[Budget, int]) -> ContextPipeline:
    """Create a new context pipeline.

    Args:
        budget: Token budget (number or Budget object)

    Returns:
        A chainable ContextPipeline

    Example:
        result = (create_pipeline(8000)
            .add(system_prompt)
            .add_many(docs, kind="retrieval")
            .cache_topology(provider="anthropic")
            .build())
    """
    return ContextPipeline(budget)
