from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union, cast

import structlog

from .core import (
    Budget,
    ContextHandoff,
    ContextItem,
    ContextPack,
    ContextTrace,
    ScoringWeights,
    estimate_tokens,
    pack,
    trace_pack,
)
from .memory import InMemoryStore, MemoryItem, MemoryStore
from .providers import LLMMessage
from .segmentation import BaseSegmenter, Segment, StructuralSegmenter

logger = structlog.get_logger(__name__)


class AdaptiveBudgetStrategy:
    """
    Logic for dynamically adjusting the token budget based on input complexity.
    """

    def __init__(self, min_budget: int = 512, max_budget: int = 8192):
        self.min_budget = min_budget
        self.max_budget = max_budget

    def calculate_budget(self, input_text: str, metadata: Dict[str, Any] = None) -> int:
        budget = self.min_budget
        tokens = estimate_tokens(input_text)
        if tokens > 500:
            budget += 1024
        complexity_keywords = ["analyze", "debug", "compare", "refactor", "summarize everything"]
        if any(kw in input_text.lower() for kw in complexity_keywords):
            budget += 2048
        if metadata and metadata.get("depth") == "exhaustive":
            budget = self.max_budget
        return min(budget, self.max_budget)


class AgentContextManager:
    """
    High-level framework for managing agent context across sessions.
    """

    def __init__(
        self,
        memory_store: Optional[MemoryStore] = None,
        default_budget: int = 4096,
        provider: str = "heuristic",
        segmenter: Optional[BaseSegmenter] = None,
        agent_id: str = "agent_unnamed",
        adaptive_strategy: Optional[AdaptiveBudgetStrategy] = None,
        scoring_weights: Optional[ScoringWeights] = None,
        abstain_on_low_confidence: bool = True,
        min_confidence_threshold: float = 0.4,
    ):
        self.agent_id = agent_id
        self.memory = memory_store or InMemoryStore()
        self.default_budget = default_budget
        self.active_budget = default_budget
        self.provider = provider
        self.segmenter = segmenter or StructuralSegmenter()
        self.adaptive_strategy = adaptive_strategy or AdaptiveBudgetStrategy()
        self.scoring_weights = scoring_weights or ScoringWeights()
        self.abstain_on_low_confidence = abstain_on_low_confidence
        self.min_confidence_threshold = min_confidence_threshold
        self.system_prompt: Optional[ContextItem] = None
        self.temporary_items: List[ContextItem] = []

    def adapt_budget(self, user_input: str, metadata: Dict[str, Any] = None):
        self.active_budget = self.adaptive_strategy.calculate_budget(user_input, metadata)
        return self.active_budget

    def set_system_prompt(self, content: str, id: str = "system"):
        self.system_prompt = ContextItem(id=id, content=content, priority=10.0)

    def add_document(self, content: str, id: str, priority: float = 5.0):
        segments = self.segmenter.segment(content, doc_id=id)
        for seg in segments:
            seg.priority = priority
            self.temporary_items.append(seg)

    def add_memory(
        self,
        content: str,
        id: Optional[str] = None,
        salience: float = 1.0,
        ttl: Optional[int] = None,
    ) -> MemoryItem:
        item = MemoryItem(
            id=id or f"mem_{int(datetime.now(timezone.utc).timestamp())}",
            content=content,
            salience=salience,
            ttlSeconds=ttl,
            createdAt=datetime.now(timezone.utc).isoformat(),
        )
        self.memory.put(item)
        return item

    async def add_memory_async(
        self,
        content: str,
        id: Optional[str] = None,
        salience: float = 1.0,
        ttl: Optional[int] = None,
    ) -> MemoryItem:
        item = MemoryItem(
            id=id or f"mem_{int(datetime.now(timezone.utc).timestamp())}",
            content=content,
            salience=salience,
            ttlSeconds=ttl,
            createdAt=datetime.now(timezone.utc).isoformat(),
        )
        await self.memory.aput(item)
        return item

    def add_temporary_context(
        self,
        content: str,
        id: str,
        priority: float = 5.0,
        compressions: List[Dict[str, Any]] = None,
        cost: float = 0.0,
        latency: float = 0.0,
    ):
        item = ContextItem(
            id=id,
            content=content,
            priority=priority,
            compressions=compressions or [],
            cost=cost,
            latency=latency,
        )
        self.temporary_items.append(item)

    def build_context(
        self,
        budget: Optional[int] = None,
        trace: bool = False,
        weights: Optional[ScoringWeights] = None,
    ) -> Union[ContextPack, ContextTrace]:
        target_budget = Budget(maxTokens=budget or self.active_budget)
        w = weights or self.scoring_weights

        memories = self.memory.query()
        context_items: List[ContextItem] = []
        for m in memories:
            context_items.append(
                ContextItem(
                    id=m.id,
                    content=m.content,
                    priority=m.salience or 1.0,
                    metadata=m.metadata,
                    embedding=m.embedding,
                )
            )

        context_items.extend(self.temporary_items)
        if self.system_prompt:
            context_items.append(self.system_prompt)

        if trace:
            return trace_pack(context_items, target_budget, provider=self.provider, weights=w)
        return pack(context_items, target_budget, provider=self.provider, weights=w)

    async def build_context_async(
        self,
        budget: Optional[int] = None,
        trace: bool = False,
        weights: Optional[ScoringWeights] = None,
    ) -> Union[ContextPack, ContextTrace]:
        # pack/trace_pack are CPU-only; run them in a thread to avoid blocking an async server.
        return await asyncio.to_thread(
            self.build_context, budget=budget, trace=trace, weights=weights
        )

    def export_handoff(
        self, target_agent_id: Optional[str] = None, budget: Optional[int] = None
    ) -> ContextHandoff:
        packed = cast(ContextPack, self.build_context(budget=budget))
        return ContextHandoff(
            sourceAgentId=self.agent_id,
            targetAgentId=target_agent_id,
            items=packed.selected,
            budget=packed.budget,
            metadata={"source_provider": self.provider},
        )

    async def export_handoff_async(
        self, target_agent_id: Optional[str] = None, budget: Optional[int] = None
    ) -> ContextHandoff:
        return await asyncio.to_thread(
            self.export_handoff, target_agent_id=target_agent_id, budget=budget
        )

    def import_handoff(self, handoff: ContextHandoff):
        self.temporary_items = handoff.items
        self.active_budget = handoff.budget.max_tokens

    def build_messages(
        self, budget: Optional[int] = None, weights: Optional[ScoringWeights] = None
    ) -> List[LLMMessage]:
        # Save segment map before packing (pack's model_copy loses Segment subclass)
        segment_map = {i.id: i for i in self.temporary_items if isinstance(i, Segment)}

        packed = cast(ContextPack, self.build_context(budget=budget, weights=weights))
        messages: List[LLMMessage] = []
        selected = packed.selected

        # Abstention Logic
        if self.abstain_on_low_confidence:
            max_confidence = max([getattr(i, "priority", 0.0) for i in selected] + [0.0])
            if max_confidence < self.min_confidence_threshold:
                logger.warning(
                    "abstaining_due_to_low_confidence",
                    agent_id=self.agent_id,
                    max_confidence=max_confidence,
                    threshold=self.min_confidence_threshold,
                )
                messages.append(
                    LLMMessage(role="system", content="I abstain: insufficient evidence to answer.")
                )
                return messages

        system_items = [i for i in selected if i.id == "system" or (i.priority or 0) >= 10]
        other_items = [i for i in selected if i not in system_items]

        for item in system_items:
            messages.append(LLMMessage(role="system", content=item.content))

        if other_items:
            blocks = []
            for i in other_items:
                if i.id in segment_map:
                    content = segment_map[i.id].to_context_text()
                else:
                    content = i.content
                blocks.append(f"### {i.id}\n{content}")
            context_block = chr(10).join(blocks)
            messages.append(LLMMessage(role="user", content=f"Context:\n{context_block}"))
        return messages

    async def build_messages_async(
        self, budget: Optional[int] = None, weights: Optional[ScoringWeights] = None
    ) -> List[LLMMessage]:
        return await asyncio.to_thread(self.build_messages, budget=budget, weights=weights)

    def clear_temporary(self):
        self.temporary_items = []
