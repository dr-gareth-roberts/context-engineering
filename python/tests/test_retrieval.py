from __future__ import annotations

import unittest

from context_framework import (
    ContextKind,
    ContextManager,
    InMemoryVectorRetriever,
    RetrievedChunk,
)


def toy_embed(text: str) -> tuple[float, float, float]:
    lower = text.lower()
    return (
        float(lower.count("retry")),
        float(lower.count("billing")),
        float(lower.count("error")),
    )


class RetrievalAdapterTests(unittest.TestCase):
    def test_inmemory_retriever_ranks_by_similarity(self) -> None:
        retriever = InMemoryVectorRetriever(
            [
                RetrievedChunk(
                    text="Retry policy with exponential backoff and jitter.",
                    source="retry-doc",
                ),
                RetrievedChunk(
                    text="Billing and invoice lifecycle details.",
                    source="billing-doc",
                ),
            ],
            embed=toy_embed,
        )

        results = retriever.retrieve("How should retry logic work?", k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "retry-doc")
        self.assertGreaterEqual(results[0].score or 0.0, 0.0)

    def test_manager_ingests_retriever_results(self) -> None:
        manager = ContextManager(default_token_budget=160, reserved_response_tokens=20)
        retriever = InMemoryVectorRetriever(
            [
                RetrievedChunk(text="Retry jobs with capped backoff.", source="retry-doc"),
                RetrievedChunk(text="Billing tax summary table.", source="billing-doc"),
            ],
            embed=toy_embed,
        )

        manager.register_retriever("memory", retriever)
        added = manager.ingest_retrieval("retry failures", retriever="memory", k=1)
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].source, "retry-doc")
        self.assertIn("retrieval_score", added[0].metadata)
        self.assertEqual(added[0].metadata["retrieved_for"], "retry failures")

        packet = manager.build_context("retry failures")
        selected_sources = [item.source for item in packet.items if item.kind == ContextKind.DOCUMENT]
        self.assertIn("retry-doc", selected_sources)


if __name__ == "__main__":
    unittest.main()
