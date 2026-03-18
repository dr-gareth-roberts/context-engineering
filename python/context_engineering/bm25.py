"""BM25 index and Unicode-aware tokenizer for relevance scoring."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Callable


def unicode_tokenize(text: str | None) -> list[str]:
    """Split text on Unicode word boundaries, lowercase, filter length <= 1."""
    if not text:
        return []
    matches = re.findall(r"[\w]+", text.lower(), re.UNICODE)
    return [w for w in matches if len(w) > 1 and w != "_" and not w.startswith("_")]


class BM25Index:
    """Okapi BM25 index for scoring document relevance to queries."""

    def __init__(
        self,
        k1: float = 1.2,
        b: float = 0.75,
        tokenizer: Callable[[str], list[str]] | None = None,
    ):
        self._k1 = k1
        self._b = b
        self._tokenize = tokenizer or unicode_tokenize
        self._docs: dict[str, dict[str, int]] = {}
        self._doc_lengths: dict[str, int] = {}
        self._df: dict[str, int] = defaultdict(int)
        self._total_length = 0

    @property
    def document_count(self) -> int:
        return len(self._docs)

    def add(self, id: str, text: str) -> None:
        tokens = self._tokenize(text)
        freq: dict[str, int] = defaultdict(int)
        for t in tokens:
            freq[t] += 1
        self._docs[id] = dict(freq)
        self._doc_lengths[id] = len(tokens)
        self._total_length += len(tokens)
        for term in freq:
            self._df[term] += 1

    def score(self, query: str, id: str) -> float:
        doc_freq = self._docs.get(id)
        if doc_freq is None:
            return 0.0
        query_tokens = self._tokenize(query)
        if not query_tokens:
            return 0.0

        n = len(self._docs)
        dl = self._doc_lengths.get(id, 0)
        avgdl = self._total_length / n if n > 0 else 1.0
        total = 0.0

        for term in query_tokens:
            term_df = self._df.get(term, 0)
            tf = doc_freq.get(term, 0)
            if tf == 0:
                continue
            idf = math.log((n - term_df + 0.5) / (term_df + 0.5) + 1)
            tf_norm = (tf * (self._k1 + 1)) / (tf + self._k1 * (1 - self._b + self._b * dl / avgdl))
            total += idf * tf_norm

        return total

    def score_all(self, query: str) -> dict[str, float]:
        return {id: self.score(query, id) for id in self._docs}


def create_bm25_index(
    k1: float = 1.2,
    b: float = 0.75,
    tokenizer: Callable[[str], list[str]] | None = None,
) -> BM25Index:
    """Create a BM25 index with configurable parameters."""
    return BM25Index(k1=k1, b=b, tokenizer=tokenizer)
