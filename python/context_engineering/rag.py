"""Context-Aware RAG — retrieves only chunks that add new information.

Computes information gain against existing context to avoid redundant
retrieval and respects token budgets during selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from ._similarity import cosine_similarity
from .bm25 import create_bm25_index, unicode_tokenize
from .core import Budget, ContextItem, ScoringWeights, pack
from .relevance import compute_relevance, normalize_query

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass
class VectorResult:
    """A single result from a vector store query."""

    id: str
    content: str
    score: float
    metadata: dict[str, Any] | None = None


@runtime_checkable
class VectorStoreLike(Protocol):
    """Protocol for vector stores that support async query."""

    async def query(self, text: str, top_k: int) -> list[VectorResult]: ...


@dataclass
class RetrieverConfig:
    """Configuration for a context-aware retriever."""

    store: VectorStoreLike
    current_context: list[ContextItem]
    budget: Budget
    redundancy_threshold: float = 0.7
    max_candidates: int | None = None
    scoring_weights: ScoringWeights | None = None


@dataclass
class RetrieveOptions:
    """Options for a single retrieval call."""

    top_k: int = 10
    min_gain: float = 0.1
    query: str | None = None


@dataclass
class RetrievedPack:
    """Result of a context-aware retrieval."""

    items: list[ContextItem]
    total_gain: float
    candidates_evaluated: int
    candidates_filtered: int
    tokens_used: int


@dataclass
class InformationGainResult:
    """Breakdown of information gain for a candidate."""

    gain: float
    novelty: float
    query_relevance: float


# ---------------------------------------------------------------------------
# Information gain
# ---------------------------------------------------------------------------


def _jaccard_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Jaccard similarity between two token sets."""
    if not tokens_a and not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def compute_information_gain(
    candidate: ContextItem,
    existing_context: list[ContextItem],
    novelty_weight: float = 0.6,
    relevance_weight: float = 0.4,
    query: str | None = None,
) -> InformationGainResult:
    """Compute how much new information a candidate adds vs existing context.

    Uses Jaccard similarity on unicode tokens for novelty and optionally
    cosine similarity when embeddings are available.  Query relevance is
    computed via BM25 when a query string is provided.

    Args:
        candidate: The item being evaluated.
        existing_context: Items already in the context window.
        novelty_weight: Weight for the novelty component (default 0.6).
        relevance_weight: Weight for the query-relevance component (default 0.4).
        query: Optional query string for relevance scoring.

    Returns:
        InformationGainResult with gain, novelty, and query_relevance.
    """
    if not existing_context:
        # Everything is novel when context is empty.
        query_relevance = 0.0
        if query:
            q = normalize_query(query)
            query_relevance = compute_relevance(q, candidate)
        novelty = 1.0
        gain = novelty * novelty_weight + query_relevance * relevance_weight
        return InformationGainResult(gain=gain, novelty=novelty, query_relevance=query_relevance)

    # Compute novelty as 1 - max similarity to any existing item.
    candidate_tokens = set(unicode_tokenize(candidate.content))
    max_similarity = 0.0

    for existing in existing_context:
        # Prefer embedding similarity when both have embeddings.
        if candidate.embedding and existing.embedding:
            try:
                sim = cosine_similarity(candidate.embedding, existing.embedding)
            except ValueError:
                sim = 0.0
        else:
            existing_tokens = set(unicode_tokenize(existing.content))
            sim = _jaccard_similarity(candidate_tokens, existing_tokens)
        max_similarity = max(max_similarity, sim)

    novelty = max(0.0, 1.0 - max_similarity)

    # Query relevance via BM25.
    query_relevance = 0.0
    if query:
        q = normalize_query(query)
        query_relevance = compute_relevance(q, candidate)

    gain = novelty * novelty_weight + query_relevance * relevance_weight
    return InformationGainResult(gain=gain, novelty=novelty, query_relevance=query_relevance)


# ---------------------------------------------------------------------------
# ContextAwareRetriever
# ---------------------------------------------------------------------------


class ContextAwareRetriever:
    """Retrieves context items from a vector store, filtering by information gain."""

    def __init__(self, config: RetrieverConfig) -> None:
        self._config = config

    async def retrieve(self, query: str, options: RetrieveOptions | None = None) -> RetrievedPack:
        """Retrieve context items that add genuine information.

        1. Fetch candidates from the vector store.
        2. Convert to ContextItem with metadata.source='rag'.
        3. Compute information gain for each candidate.
        4. Filter by min_gain.
        5. Sort by gain descending, pack within budget.
        6. Return RetrievedPack.
        """
        opts = options or RetrieveOptions()
        top_k = opts.top_k
        max_candidates = self._config.max_candidates or top_k * 3

        # 1. Fetch candidates.
        results = await self._config.store.query(query, max_candidates)

        # 2. Convert to ContextItem.
        candidates: list[tuple[ContextItem, float]] = []
        existing = list(self._config.current_context)

        for result in results:
            item = ContextItem(
                id=result.id,
                content=result.content,
                metadata={
                    **(result.metadata or {}),
                    "source": "rag",
                    "vector_score": result.score,
                },
            )

            # 3. Compute information gain.
            gain_result = compute_information_gain(
                item,
                existing,
                query=opts.query or query,
            )

            # 4. Filter by min_gain.
            if gain_result.gain >= opts.min_gain:
                candidates.append((item, gain_result.gain))

        candidates_evaluated = len(results)
        candidates_filtered = candidates_evaluated - len(candidates)

        # 5. Sort by gain descending.
        candidates.sort(key=lambda x: x[1], reverse=True)

        # 6. Fill within budget using pack().
        items_with_scores = [
            item.model_copy(update={"priority": gain, "score": gain}) for item, gain in candidates
        ]

        if not items_with_scores:
            return RetrievedPack(
                items=[],
                total_gain=0.0,
                candidates_evaluated=candidates_evaluated,
                candidates_filtered=candidates_filtered,
                tokens_used=0,
            )

        packed = pack(
            items_with_scores,
            self._config.budget,
            weights=self._config.scoring_weights,
        )

        total_gain = sum(
            gain for item, gain in candidates if item.id in {s.id for s in packed.selected}
        )

        return RetrievedPack(
            items=packed.selected,
            total_gain=round(total_gain, 4),
            candidates_evaluated=candidates_evaluated,
            candidates_filtered=candidates_filtered,
            tokens_used=packed.total_tokens,
        )


def create_context_aware_retriever(config: RetrieverConfig) -> ContextAwareRetriever:
    """Factory for context-aware retriever."""
    return ContextAwareRetriever(config)


# ---------------------------------------------------------------------------
# Hybrid retriever — vector + BM25 with Reciprocal Rank Fusion
# ---------------------------------------------------------------------------


def _reciprocal_rank_fusion(
    rankings: list[list[str]],
    weights: list[float],
    k: int = 60,
) -> dict[str, float]:
    """Merge multiple rankings using weighted Reciprocal Rank Fusion.

    Args:
        rankings: List of ranked id lists (best first).
        weights: Weight for each ranking.
        k: RRF constant (default 60).

    Returns:
        Dict mapping id to fused score.
    """
    scores: dict[str, float] = {}
    for ranking, weight in zip(rankings, weights):
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + rank + 1)
    return scores


class _HybridRetriever(ContextAwareRetriever):
    """Retriever that combines vector search with BM25 via RRF."""

    def __init__(
        self,
        config: RetrieverConfig,
        bm25_weight: float,
        vector_weight: float,
    ) -> None:
        super().__init__(config)
        self._bm25_weight = bm25_weight
        self._vector_weight = vector_weight

    async def retrieve(self, query: str, options: RetrieveOptions | None = None) -> RetrievedPack:
        opts = options or RetrieveOptions()
        max_candidates = self._config.max_candidates or opts.top_k * 3

        # Vector search.
        vector_results = await self._config.store.query(query, max_candidates)

        # Build BM25 index from vector results.
        bm25_index = create_bm25_index()
        result_map: dict[str, VectorResult] = {}
        for r in vector_results:
            bm25_index.add(r.id, r.content)
            result_map[r.id] = r

        # BM25 ranking.
        bm25_scores = bm25_index.score_all(query)
        bm25_ranking = sorted(bm25_scores, key=lambda x: bm25_scores[x], reverse=True)

        # Vector ranking (already sorted by score from the store).
        vector_ranking = [r.id for r in vector_results]

        # RRF fusion.
        fused = _reciprocal_rank_fusion(
            [vector_ranking, bm25_ranking],
            [self._vector_weight, self._bm25_weight],
        )
        fused_ranking = sorted(fused, key=lambda x: fused[x], reverse=True)

        # Convert to ContextItem and compute information gain.
        existing = list(self._config.current_context)
        candidates: list[tuple[ContextItem, float]] = []

        for doc_id in fused_ranking:
            r = result_map.get(doc_id)
            if r is None:
                continue
            item = ContextItem(
                id=r.id,
                content=r.content,
                metadata={
                    **(r.metadata or {}),
                    "source": "rag",
                    "vector_score": r.score,
                    "rrf_score": fused[doc_id],
                },
            )
            gain_result = compute_information_gain(
                item,
                existing,
                query=opts.query or query,
            )
            if gain_result.gain >= opts.min_gain:
                candidates.append((item, gain_result.gain))

        candidates_evaluated = len(vector_results)
        candidates_filtered = candidates_evaluated - len(candidates)

        # Sort by gain and pack within budget.
        candidates.sort(key=lambda x: x[1], reverse=True)
        items_with_scores = [
            item.model_copy(update={"priority": gain, "score": gain}) for item, gain in candidates
        ]

        if not items_with_scores:
            return RetrievedPack(
                items=[],
                total_gain=0.0,
                candidates_evaluated=candidates_evaluated,
                candidates_filtered=candidates_filtered,
                tokens_used=0,
            )

        packed = pack(
            items_with_scores,
            self._config.budget,
            weights=self._config.scoring_weights,
        )

        total_gain = sum(
            gain for item, gain in candidates if item.id in {s.id for s in packed.selected}
        )

        return RetrievedPack(
            items=packed.selected,
            total_gain=round(total_gain, 4),
            candidates_evaluated=candidates_evaluated,
            candidates_filtered=candidates_filtered,
            tokens_used=packed.total_tokens,
        )


def create_hybrid_retriever(
    config: RetrieverConfig,
    bm25_weight: float = 0.4,
    vector_weight: float = 0.6,
) -> ContextAwareRetriever:
    """Create a hybrid vector + BM25 retriever with Reciprocal Rank Fusion."""
    return _HybridRetriever(config, bm25_weight, vector_weight)
