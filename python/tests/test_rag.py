"""Tests for context-aware RAG — information gain, retrieval, and hybrid search."""

import asyncio

from context_engineering.core import Budget, ContextItem
from context_engineering.rag import (
    RetrieveOptions,
    RetrieverConfig,
    VectorResult,
    compute_information_gain,
    create_context_aware_retriever,
    create_hybrid_retriever,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeVectorStore:
    """In-memory vector store for testing."""

    def __init__(self, results: list[VectorResult]) -> None:
        self._results = results

    async def query(self, text: str, top_k: int) -> list[VectorResult]:
        return self._results[:top_k]


def _make_item(id: str, content: str, **kwargs) -> ContextItem:
    return ContextItem(id=id, content=content, **kwargs)


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# compute_information_gain
# ---------------------------------------------------------------------------


class TestComputeInformationGain:
    def test_novel_item_returns_high_gain(self):
        candidate = _make_item("new", "quantum computing basics and algorithms")
        existing = [_make_item("old", "classical database indexing strategies")]

        result = compute_information_gain(candidate, existing)

        assert result.gain > 0.5
        assert result.novelty > 0.5

    def test_duplicate_item_returns_low_gain(self):
        content = "the quick brown fox jumps over the lazy dog"
        candidate = _make_item("dup", content)
        existing = [_make_item("orig", content)]

        result = compute_information_gain(candidate, existing)

        assert result.novelty < 0.1
        assert result.gain < 0.2

    def test_empty_context_returns_full_novelty(self):
        candidate = _make_item("first", "some unique content here")

        result = compute_information_gain(candidate, [])

        assert result.novelty == 1.0
        assert result.gain > 0.5

    def test_query_relevance_boosts_gain(self):
        candidate = _make_item("doc", "python async programming patterns guide")
        existing = [_make_item("old", "javascript basics tutorial")]

        result_with_query = compute_information_gain(
            candidate, existing, query="python async programming"
        )
        result_without_query = compute_information_gain(candidate, existing)

        assert result_with_query.query_relevance > 0.0
        assert result_with_query.gain >= result_without_query.gain

    def test_embedding_similarity_used_when_available(self):
        candidate = _make_item("a", "content a", embedding=[1.0, 0.0, 0.0])
        existing = [_make_item("b", "content b", embedding=[0.99, 0.1, 0.0])]

        result = compute_information_gain(candidate, existing)

        # High embedding similarity means low novelty.
        assert result.novelty < 0.5

    def test_custom_weights(self):
        candidate = _make_item("new", "novel information about context engineering")
        existing = [_make_item("old", "unrelated content about cooking recipes")]

        result_novelty_heavy = compute_information_gain(
            candidate, existing, novelty_weight=0.9, relevance_weight=0.1
        )
        result_relevance_heavy = compute_information_gain(
            candidate, existing, novelty_weight=0.1, relevance_weight=0.9
        )

        # Both should compute differently.
        assert result_novelty_heavy.gain != result_relevance_heavy.gain


# ---------------------------------------------------------------------------
# ContextAwareRetriever
# ---------------------------------------------------------------------------


class TestContextAwareRetriever:
    def test_retriever_returns_items(self):
        results = [
            VectorResult(id="r1", content="unique document about quantum physics", score=0.9),
            VectorResult(id="r2", content="another unique doc about machine learning", score=0.8),
        ]
        store = FakeVectorStore(results)
        config = RetrieverConfig(
            store=store,
            current_context=[],
            budget=Budget(maxTokens=5000),
        )
        retriever = create_context_aware_retriever(config)

        pack = _run(retriever.retrieve("quantum physics"))

        assert len(pack.items) > 0
        assert pack.candidates_evaluated == 2
        assert pack.tokens_used > 0

    def test_retriever_filters_redundant_candidates(self):
        existing_content = "the quick brown fox jumps over the lazy dog repeatedly"
        results = [
            VectorResult(id="r1", content=existing_content, score=0.95),
            VectorResult(
                id="r2", content="completely novel content about space exploration", score=0.7
            ),
        ]
        store = FakeVectorStore(results)
        config = RetrieverConfig(
            store=store,
            current_context=[_make_item("existing", existing_content)],
            budget=Budget(maxTokens=5000),
        )
        retriever = create_context_aware_retriever(config)

        pack = _run(retriever.retrieve("anything", RetrieveOptions(min_gain=0.3)))

        # The duplicate should be filtered.
        selected_ids = {item.id for item in pack.items}
        assert "r1" not in selected_ids
        assert pack.candidates_filtered > 0

    def test_retriever_respects_budget(self):
        results = [
            VectorResult(
                id=f"r{i}",
                content=f"unique document number {i} with enough words to use tokens",
                score=0.9 - i * 0.1,
            )
            for i in range(10)
        ]
        store = FakeVectorStore(results)
        config = RetrieverConfig(
            store=store,
            current_context=[],
            budget=Budget(maxTokens=50),  # Very small budget.
        )
        retriever = create_context_aware_retriever(config)

        pack = _run(retriever.retrieve("documents"))

        # Should not exceed budget.
        assert pack.tokens_used <= 50

    def test_retriever_returns_empty_when_all_redundant(self):
        shared = "identical content shared across all documents in the collection"
        results = [
            VectorResult(id="r1", content=shared, score=0.9),
            VectorResult(id="r2", content=shared, score=0.8),
        ]
        store = FakeVectorStore(results)
        config = RetrieverConfig(
            store=store,
            current_context=[_make_item("existing", shared)],
            budget=Budget(maxTokens=5000),
        )
        retriever = create_context_aware_retriever(config)

        pack = _run(retriever.retrieve("query", RetrieveOptions(min_gain=0.3)))

        assert len(pack.items) == 0
        assert pack.total_gain == 0.0

    def test_retriever_metadata_includes_source(self):
        results = [
            VectorResult(id="r1", content="unique rag content for testing source tag", score=0.9),
        ]
        store = FakeVectorStore(results)
        config = RetrieverConfig(
            store=store,
            current_context=[],
            budget=Budget(maxTokens=5000),
        )
        retriever = create_context_aware_retriever(config)

        pack = _run(retriever.retrieve("test"))

        assert len(pack.items) > 0
        assert pack.items[0].metadata.get("source") == "rag"


# ---------------------------------------------------------------------------
# Hybrid retriever
# ---------------------------------------------------------------------------


class TestHybridRetriever:
    def test_hybrid_combines_rankings(self):
        results = [
            VectorResult(id="r1", content="python programming language guide", score=0.9),
            VectorResult(id="r2", content="javascript framework tutorial overview", score=0.8),
            VectorResult(id="r3", content="python data science libraries pandas numpy", score=0.7),
        ]
        store = FakeVectorStore(results)
        config = RetrieverConfig(
            store=store,
            current_context=[],
            budget=Budget(maxTokens=5000),
        )
        retriever = create_hybrid_retriever(config)

        pack = _run(retriever.retrieve("python programming"))

        assert len(pack.items) > 0
        assert pack.candidates_evaluated == 3

    def test_hybrid_respects_budget(self):
        results = [
            VectorResult(
                id=f"r{i}",
                content=f"unique document about topic {i} with substantial content",
                score=0.9 - i * 0.05,
            )
            for i in range(10)
        ]
        store = FakeVectorStore(results)
        config = RetrieverConfig(
            store=store,
            current_context=[],
            budget=Budget(maxTokens=30),
        )
        retriever = create_hybrid_retriever(config)

        pack = _run(retriever.retrieve("topics"))

        assert pack.tokens_used <= 30

    def test_hybrid_filters_low_gain(self):
        shared = "shared content that is identical across all results and existing context"
        results = [
            VectorResult(id="r1", content=shared, score=0.95),
            VectorResult(
                id="r2", content="completely novel unique content about astrophysics", score=0.6
            ),
        ]
        store = FakeVectorStore(results)
        config = RetrieverConfig(
            store=store,
            current_context=[_make_item("existing", shared)],
            budget=Budget(maxTokens=5000),
        )
        retriever = create_hybrid_retriever(config)

        pack = _run(retriever.retrieve("anything", RetrieveOptions(min_gain=0.3)))

        selected_ids = {item.id for item in pack.items}
        assert "r1" not in selected_ids
