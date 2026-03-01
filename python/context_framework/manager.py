from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Callable, Sequence

import structlog

from .models import ContextItem, ContextKind, ContextPacket
from .retrieval import Retriever
from .scoring import KeywordOverlapScorer, RelevanceScorer
from .summarization import (
    ConversationSummarizer,
    HeuristicConversationSummarizer,
    RollingSummaryConfig,
)
from .tokenizer import ApproxTokenCounter, TokenCounter

logger = structlog.get_logger(__name__)

SummaryBuilder = Callable[[Sequence[ContextItem], int], str]


@dataclass(slots=True)
class WeightConfig:
    relevance: float = 0.55
    importance: float = 0.25
    recency: float = 0.20

    def normalized(self) -> tuple[float, float, float]:
        total = self.relevance + self.importance + self.recency
        if total <= 0:
            raise ValueError("At least one context score weight must be > 0")
        return (
            self.relevance / total,
            self.importance / total,
            self.recency / total,
        )


class ContextManager:
    """
    Budget-aware context planner for LLM prompts.

    It blends:
    - hard-priority items (system + pinned memory/docs),
    - recency for conversational continuity,
    - query relevance for retrieval behavior.
    """

    def __init__(
        self,
        *,
        token_counter: TokenCounter | None = None,
        scorer: RelevanceScorer | None = None,
        default_token_budget: int = 8192,
        reserved_response_tokens: int = 1024,
        weights: WeightConfig | None = None,
        summary_builder: SummaryBuilder | None = None,
        rolling_summary: RollingSummaryConfig | None = None,
        conversation_summarizer: ConversationSummarizer | None = None,
    ) -> None:
        if default_token_budget < 1:
            raise ValueError("default_token_budget must be >= 1")
        if reserved_response_tokens < 0:
            raise ValueError("reserved_response_tokens must be >= 0")

        self._token_counter = token_counter or ApproxTokenCounter()
        self._scorer = scorer or KeywordOverlapScorer()
        self._weights = weights or WeightConfig()
        self._summary_builder = summary_builder
        self._rolling_summary_config = rolling_summary or RollingSummaryConfig()
        self._rolling_summary_config.validate()
        self._conversation_summarizer = conversation_summarizer or HeuristicConversationSummarizer(
            token_counter=self._token_counter
        )
        self.default_token_budget = default_token_budget
        self.reserved_response_tokens = reserved_response_tokens

        self._system_items: list[ContextItem] = []
        self._conversation_items: list[ContextItem] = []
        self._knowledge_items: list[ContextItem] = []
        self._retrievers: dict[str, Retriever] = {}
        self._rolling_summary_item: ContextItem | None = None

    def add_system(
        self,
        text: str,
        *,
        source: str | None = None,
        importance: float = 1.0,
        pinned: bool = True,
        tags: tuple[str, ...] = (),
        metadata: dict[str, object] | None = None,
        created_at: datetime | None = None,
    ) -> ContextItem:
        return self._push(
            kind=ContextKind.SYSTEM,
            role="system",
            text=text,
            source=source,
            importance=importance,
            pinned=pinned,
            tags=tags,
            metadata=metadata,
            created_at=created_at,
        )

    def add_message(
        self,
        role: str,
        text: str,
        *,
        source: str | None = None,
        importance: float = 0.5,
        pinned: bool = False,
        tags: tuple[str, ...] = (),
        metadata: dict[str, object] | None = None,
        created_at: datetime | None = None,
    ) -> ContextItem:
        return self._push(
            kind=ContextKind.MESSAGE,
            role=role,
            text=text,
            source=source,
            importance=importance,
            pinned=pinned,
            tags=tags,
            metadata=metadata,
            created_at=created_at,
        )

    def add_memory(
        self,
        text: str,
        *,
        source: str | None = None,
        importance: float = 0.7,
        pinned: bool = False,
        tags: tuple[str, ...] = (),
        metadata: dict[str, object] | None = None,
        created_at: datetime | None = None,
    ) -> ContextItem:
        return self._push(
            kind=ContextKind.MEMORY,
            role="system",
            text=text,
            source=source,
            importance=importance,
            pinned=pinned,
            tags=tags,
            metadata=metadata,
            created_at=created_at,
        )

    def add_document(
        self,
        text: str,
        *,
        source: str | None = None,
        importance: float = 0.5,
        pinned: bool = False,
        tags: tuple[str, ...] = (),
        metadata: dict[str, object] | None = None,
        created_at: datetime | None = None,
    ) -> ContextItem:
        return self._push(
            kind=ContextKind.DOCUMENT,
            role="system",
            text=text,
            source=source,
            importance=importance,
            pinned=pinned,
            tags=tags,
            metadata=metadata,
            created_at=created_at,
        )

    def add_item(self, item: ContextItem) -> ContextItem:
        item.created_at = self._normalize_datetime(item.created_at)

        if item.kind == ContextKind.SYSTEM:
            self._system_items.append(item)
        elif item.kind == ContextKind.MESSAGE:
            self._conversation_items.append(item)
            self._maybe_rollup_conversation()
        else:
            self._knowledge_items.append(item)

        if item.kind == ContextKind.SUMMARY and item.source == self._rolling_summary_config.source:
            self._rolling_summary_item = item
        return item

    def all_items(self) -> list[ContextItem]:
        return [
            *self._system_items,
            *self._conversation_items,
            *self._knowledge_items,
        ]

    def clear(self, *, keep_system: bool = True) -> None:
        self._conversation_items.clear()
        self._knowledge_items.clear()
        self._rolling_summary_item = None
        if not keep_system:
            self._system_items.clear()

    def register_retriever(self, name: str, retriever: Retriever) -> None:
        key = name.strip()
        if not key:
            raise ValueError("Retriever name cannot be empty")
        self._retrievers[key] = retriever

    def unregister_retriever(self, name: str) -> None:
        self._retrievers.pop(name, None)

    def list_retrievers(self) -> tuple[str, ...]:
        return tuple(sorted(self._retrievers.keys()))

    def ingest_retrieval(
        self,
        query: str,
        *,
        retriever: Retriever | str | None = None,
        k: int = 5,
        min_score: float | None = None,
        default_importance: float = 0.6,
        tags: tuple[str, ...] = (),
    ) -> list[ContextItem]:
        resolved = self._resolve_retriever(retriever)
        chunks = resolved.retrieve(query, k=k, min_score=min_score)

        items: list[ContextItem] = []
        for chunk in chunks:
            metadata = dict(chunk.metadata)
            if chunk.score is not None:
                metadata.setdefault("retrieval_score", float(chunk.score))
            metadata.setdefault("retrieved_for", query)

            if chunk.tags:
                merged_tags = tuple(dict.fromkeys([*tags, *chunk.tags]))
            else:
                merged_tags = tags

            item = self.add_document(
                chunk.text,
                source=chunk.source,
                importance=chunk.importance if chunk.importance is not None else default_importance,
                pinned=False,
                tags=merged_tags,
                metadata=metadata,
            )
            items.append(item)
        return items

    def retrieve_and_build(
        self,
        query: str,
        *,
        retriever: Retriever | str | None = None,
        retrieval_k: int = 5,
        retrieval_min_score: float | None = None,
        retrieval_default_importance: float = 0.6,
        retrieval_tags: tuple[str, ...] = (),
        token_budget: int | None = None,
        reserve_response_tokens: int | None = None,
        recent_message_limit: int = 12,
    ) -> ContextPacket:
        self.ingest_retrieval(
            query,
            retriever=retriever,
            k=retrieval_k,
            min_score=retrieval_min_score,
            default_importance=retrieval_default_importance,
            tags=retrieval_tags,
        )
        return self.build_context(
            query=query,
            token_budget=token_budget,
            reserve_response_tokens=reserve_response_tokens,
            recent_message_limit=recent_message_limit,
        )

    def build_context(
        self,
        query: str = "",
        *,
        token_budget: int | None = None,
        reserve_response_tokens: int | None = None,
        recent_message_limit: int = 12,
    ) -> ContextPacket:
        if recent_message_limit < 0:
            raise ValueError("recent_message_limit must be >= 0")

        budget = token_budget if token_budget is not None else self.default_token_budget
        reserve = (
            reserve_response_tokens
            if reserve_response_tokens is not None
            else self.reserved_response_tokens
        )
        if budget < 1:
            raise ValueError("token_budget must be >= 1")
        if reserve < 0:
            raise ValueError("reserve_response_tokens must be >= 0")
        if reserve >= budget:
            raise ValueError("reserve_response_tokens must be smaller than token_budget")

        available_tokens = budget - reserve
        used_tokens = 0
        notes: list[str] = []
        selected_ids: set[str] = set()

        system_items = sorted(self._system_items, key=lambda item: item.created_at)
        conversation_items = sorted(self._conversation_items, key=lambda item: item.created_at)
        knowledge_items = sorted(self._knowledge_items, key=lambda item: item.created_at)

        selected_system: list[ContextItem] = []
        selected_knowledge: list[ContextItem] = []
        selected_summaries: list[ContextItem] = []
        selected_conversation: list[ContextItem] = []

        def try_add(
            bucket: list[ContextItem],
            item: ContextItem,
            *,
            allow_truncate: bool = False,
        ) -> bool:
            nonlocal used_tokens
            if item.id in selected_ids:
                return True

            remaining = available_tokens - used_tokens
            if remaining <= 0:
                return False

            tokens = self._ensure_token_count(item)
            if tokens <= remaining:
                bucket.append(item)
                selected_ids.add(item.id)
                used_tokens += tokens
                return True

            if not allow_truncate:
                return False

            truncated_item = self._truncate_item(item, remaining)
            if truncated_item is None:
                return False

            truncated_tokens = self._ensure_token_count(truncated_item)
            if truncated_tokens > remaining:
                return False

            bucket.append(truncated_item)
            selected_ids.add(item.id)
            used_tokens += truncated_tokens
            notes.append(
                f"Truncated {item.kind.value} item {item.id} to {truncated_tokens} tokens."
            )
            return True

        for item in system_items:
            if not try_add(selected_system, item, allow_truncate=True):
                notes.append(f"Skipped system item {item.id}; no available budget.")

        pinned_knowledge = [item for item in knowledge_items if item.pinned]
        pinned_knowledge.sort(
            key=lambda item: (item.importance, item.created_at.timestamp()),
            reverse=True,
        )
        for item in pinned_knowledge:
            if not try_add(selected_knowledge, item, allow_truncate=True):
                notes.append(f"Skipped pinned item {item.id}; no available budget.")

        recent_candidates = sorted(
            conversation_items, key=lambda item: item.created_at, reverse=True
        )[:recent_message_limit]
        for item in recent_candidates:
            try_add(selected_conversation, item)

        rank_pool = [
            item
            for item in [*knowledge_items, *conversation_items]
            if item.id not in selected_ids and not item.pinned
        ]

        weight_relevance, weight_importance, weight_recency = self._weights.normalized()
        if rank_pool:
            oldest = min(item.created_at for item in rank_pool)
            newest = max(item.created_at for item in rank_pool)
        else:
            now = datetime.now(timezone.utc)
            oldest = now
            newest = now

        item_scores = {}
        for item in rank_pool:
            relevance = self._scorer.score(query, item) if query else 0.0
            importance = item.importance
            recency = self._recency_score(item.created_at, oldest, newest)
            score = (
                (weight_relevance * relevance)
                + (weight_importance * importance)
                + (weight_recency * recency)
            )
            item_scores[id(item)] = score

        ranked_items = sorted(
            rank_pool,
            key=lambda item: (item_scores[id(item)], item.created_at.timestamp()),
            reverse=True,
        )

        for item in ranked_items:
            if item.kind == ContextKind.MESSAGE:
                try_add(selected_conversation, item)
            else:
                try_add(selected_knowledge, item)

        remaining = available_tokens - used_tokens
        if self._summary_builder and remaining > 0:
            omitted_conversation = [
                item for item in conversation_items if item.id not in selected_ids
            ]
            if omitted_conversation:
                target_tokens = min(remaining, max(16, int(available_tokens * 0.2)))
                summary_text = self._summary_builder(omitted_conversation, target_tokens)
                summary_text = summary_text.strip()
                if summary_text:
                    summary_item = ContextItem(
                        text=summary_text,
                        kind=ContextKind.SUMMARY,
                        role="system",
                        source="conversation-summary",
                        importance=1.0,
                        pinned=True,
                    )
                    try_add(selected_summaries, summary_item, allow_truncate=True)

        selected_conversation.sort(key=lambda item: item.created_at)
        final_items = [
            *selected_system,
            *selected_knowledge,
            *selected_summaries,
            *selected_conversation,
        ]

        known_items = [*system_items, *knowledge_items, *conversation_items]
        dropped_items = [item for item in known_items if item.id not in selected_ids]

        notes.append(f"Used {used_tokens}/{available_tokens} context tokens.")
        return ContextPacket(
            items=final_items,
            used_tokens=used_tokens,
            token_budget=available_tokens,
            dropped_items=dropped_items,
            notes=notes,
        )

    def build_messages(
        self,
        query: str = "",
        *,
        token_budget: int | None = None,
        reserve_response_tokens: int | None = None,
        recent_message_limit: int = 12,
        abstain_on_low_confidence: bool = True,
        min_confidence_threshold: float = 0.4,
    ) -> list[dict[str, str]]:
        log = logger.bind(query=query, action="build_messages")

        packet = self.build_context(
            query=query,
            token_budget=token_budget,
            reserve_response_tokens=reserve_response_tokens,
            recent_message_limit=recent_message_limit,
        )

        # Abstention Logic
        if abstain_on_low_confidence and packet.items:
            max_importance = max(
                [getattr(i, "importance", 0.0) or 0.0 for i in packet.items] + [0.0]
            )
            if max_importance < min_confidence_threshold:
                log.warning(
                    "abstaining_due_to_low_confidence",
                    max_importance=max_importance,
                    threshold=min_confidence_threshold,
                )
                return [
                    {"role": "system", "content": "I abstain: insufficient evidence to answer."}
                ]

        log.info("messages_built", num_items=len(packet.items), budget=packet.token_budget)
        return packet.as_messages()

    def _push(
        self,
        *,
        kind: ContextKind,
        role: str,
        text: str,
        source: str | None,
        importance: float,
        pinned: bool,
        tags: tuple[str, ...],
        metadata: dict[str, object] | None,
        created_at: datetime | None,
    ) -> ContextItem:
        item = ContextItem(
            text=text,
            kind=kind,
            role=role,
            source=source,
            importance=importance,
            pinned=pinned,
            tags=tags,
            metadata=dict(metadata or {}),
            created_at=self._normalize_datetime(created_at),
        )
        self.add_item(item)
        return item

    def _ensure_token_count(self, item: ContextItem) -> int:
        if item.token_count is None:
            item.token_count = self._token_counter.count(item.text)
        return item.token_count

    def _resolve_retriever(self, retriever: Retriever | str | None) -> Retriever:
        if retriever is None:
            if not self._retrievers:
                raise ValueError(
                    "No retrievers are registered. Pass a retriever instance or register one first."
                )
            if len(self._retrievers) == 1:
                return next(iter(self._retrievers.values()))
            names = ", ".join(sorted(self._retrievers.keys()))
            raise ValueError(
                f"Multiple retrievers are registered ({names}). Pass retriever='<name>'."
            )

        if isinstance(retriever, str):
            try:
                return self._retrievers[retriever]
            except KeyError as exc:
                raise ValueError(f"Unknown retriever: {retriever!r}") from exc

        return retriever

    def _maybe_rollup_conversation(self) -> None:
        config = self._rolling_summary_config
        if not config.enabled:
            return
        if len(self._conversation_items) <= config.trigger_messages:
            return

        cutoff = len(self._conversation_items) - config.keep_recent_messages
        if cutoff <= 0:
            return

        to_summarize = self._conversation_items[:cutoff]
        if not to_summarize:
            return

        existing_summary = self._rolling_summary_item.text if self._rolling_summary_item else ""
        summary_text = self._conversation_summarizer.summarize(
            existing_summary=existing_summary,
            new_messages=to_summarize,
            max_tokens=config.target_tokens,
        ).strip()
        if not summary_text:
            return

        now = datetime.now(timezone.utc)
        if self._rolling_summary_item is None:
            self._rolling_summary_item = ContextItem(
                text=summary_text,
                kind=ContextKind.SUMMARY,
                role="system",
                source=config.source,
                importance=1.0,
                pinned=True,
                created_at=now,
            )
            self._knowledge_items.append(self._rolling_summary_item)
        else:
            self._rolling_summary_item.text = summary_text
            self._rolling_summary_item.token_count = None
            self._rolling_summary_item.created_at = now

        del self._conversation_items[:cutoff]

    def _truncate_item(self, item: ContextItem, max_tokens: int) -> ContextItem | None:
        if max_tokens <= 0:
            return None

        text = item.text.strip()
        if not text:
            return None

        if self._token_counter.count(text) <= max_tokens:
            return replace(item, text=text, token_count=self._token_counter.count(text))

        low = 1
        high = len(text)
        best = ""
        while low <= high:
            mid = (low + high) // 2
            candidate = text[:mid].rstrip()
            if mid < len(text):
                candidate = f"{candidate}..."

            tokens = self._token_counter.count(candidate)
            if tokens <= max_tokens:
                best = candidate
                low = mid + 1
            else:
                high = mid - 1

        if not best:
            return None
        return replace(item, text=best, token_count=self._token_counter.count(best))

    @staticmethod
    def _normalize_datetime(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    @staticmethod
    def _recency_score(created_at: datetime, oldest: datetime, newest: datetime) -> float:
        if newest <= oldest:
            return 1.0

        total_window = (newest - oldest).total_seconds()
        age_position = (created_at - oldest).total_seconds()
        if total_window <= 0:
            return 1.0
        return max(0.0, min(1.0, age_position / total_window))
