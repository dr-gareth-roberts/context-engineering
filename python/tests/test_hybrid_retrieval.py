from __future__ import annotations

import unittest

from context_framework.hybrid_retrieval import HybridInMemoryRetriever
from context_framework.retrieval import RetrievedChunk


def _embed_for_tests(text: str) -> list[float]:
    text_lower = text.lower()
    if "query:" in text_lower:
        return [1.0, 0.0]
    if "vector-winner" in text_lower:
        return [1.0, 0.0]
    if "bm25-winner" in text_lower:
        return [0.8, 0.6]
    return [0.0, 1.0]


class HybridInMemoryRetrieverTests(unittest.TestCase):
    def test_rrf_promotes_items_present_in_both_lists(self) -> None:
        chunks = [
            RetrievedChunk(
                text="vector-winner: unrelated words",
                source="doc-vector",
            ),
            RetrievedChunk(
                text="bm25-winner: acetaminophen dosing guidance",
                source="doc-bm25",
            ),
            RetrievedChunk(
                text="noise: dosing table for ibuprofen",
                source="doc-noise",
            ),
        ]

        retriever = HybridInMemoryRetriever(chunks, embed=_embed_for_tests, oversample=2)
        results = retriever.retrieve("query: acetaminophen dosing", k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source, "doc-bm25")
        self.assertIn("rrf_score", results[0].metadata)
        self.assertTrue(any(key.endswith("_rank") for key in results[0].metadata))
