from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

from .models import ContextItem

_WORD_RE = re.compile(r"[a-zA-Z0-9_]+")


def _tokenize(text: str) -> set[str]:
    return {match.group(0).lower() for match in _WORD_RE.finditer(text)}


class RelevanceScorer(Protocol):
    def score(self, query: str, item: ContextItem) -> float:
        ...


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

    dot = sum(l * r for l, r in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(v * v for v in left))
    right_norm = math.sqrt(sum(v * v for v in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


@dataclass(slots=True)
class EmbeddingScorer:
    """
    Relevance scorer backed by a user-supplied embedder function.
    """

    embed: Callable[[str], Sequence[float]]
    _cache: dict[str, tuple[float, ...]] = field(default_factory=dict)

    def _embed_cached(self, text: str) -> tuple[float, ...]:
        cached = self._cache.get(text)
        if cached is not None:
            return cached

        vector = tuple(float(v) for v in self.embed(text))
        self._cache[text] = vector
        return vector

    def score(self, query: str, item: ContextItem) -> float:
        query_vector = self._embed_cached(query)
        item_vector = self._embed_cached(item.text)
        return max(0.0, cosine_similarity(query_vector, item_vector))
