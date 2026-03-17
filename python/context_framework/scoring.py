from __future__ import annotations

import math
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

from .models import ContextItem

_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")


def _tokenize(text: str) -> set[str]:
    return {match.group(0).lower() for match in _WORD_RE.finditer(text)}


class RelevanceScorer(Protocol):
    def score(self, query: str, item: ContextItem) -> float: ...


class KeywordOverlapScorer:
    """
    Scores overlap between query and item text using Jaccard similarity.
    """

    def score(self, query: str, item: ContextItem) -> float:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return 0.0

        item_tokens = _tokenize(item.text)
        if not item_tokens:
            return 0.0

        overlap = len(query_tokens.intersection(item_tokens))
        union = len(query_tokens.union(item_tokens))
        return overlap / union if union else 0.0


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise ValueError("Embedding vectors must have the same dimensions")

    dot = sum(lv * rv for lv, rv in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(v * v for v in left))
    right_norm = math.sqrt(sum(v * v for v in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


_DEFAULT_EMBEDDING_CACHE_SIZE = 2048


@dataclass(slots=True)
class EmbeddingScorer:
    """
    Relevance scorer backed by a user-supplied embedder function.

    The embedding cache is bounded to ``max_cache_size`` entries (LRU eviction)
    to prevent unbounded memory growth in long-running processes.
    """

    embed: Callable[[str], Sequence[float]]
    max_cache_size: int = _DEFAULT_EMBEDDING_CACHE_SIZE
    _cache: OrderedDict[str, tuple[float, ...]] = field(default_factory=OrderedDict)

    def _embed_cached(self, text: str) -> tuple[float, ...]:
        cached = self._cache.get(text)
        if cached is not None:
            self._cache.move_to_end(text)
            return cached

        vector = tuple(float(v) for v in self.embed(text))
        self._cache[text] = vector
        if len(self._cache) > self.max_cache_size:
            self._cache.popitem(last=False)
        return vector

    def score(self, query: str, item: ContextItem) -> float:
        query_vector = self._embed_cached(query)
        item_vector = self._embed_cached(item.text)
        return max(0.0, cosine_similarity(query_vector, item_vector))
