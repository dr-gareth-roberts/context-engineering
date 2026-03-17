"""Query-aware relevance scoring for context selection."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Set, Union

from ._similarity import cosine_similarity
from .core import ContextItem

STOPWORDS: Set[str] = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "his",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "me",
    "my",
    "no",
    "nor",
    "not",
    "of",
    "on",
    "or",
    "our",
    "out",
    "own",
    "she",
    "so",
    "some",
    "than",
    "that",
    "the",
    "their",
    "them",
    "then",
    "there",
    "these",
    "they",
    "this",
    "to",
    "too",
    "up",
    "us",
    "was",
    "we",
    "were",
    "what",
    "when",
    "which",
    "who",
    "will",
    "with",
    "would",
    "you",
    "your",
}


@dataclass
class QueryContext:
    text: str
    keywords: Optional[List[str]] = None
    embedding: Optional[List[float]] = None


QueryInput = Union[str, QueryContext]


def extract_keywords(text: str) -> Set[str]:
    """Extract meaningful keywords from text, filtering stopwords and single chars."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if t not in STOPWORDS and len(t) > 1}


def normalize_query(input: QueryInput) -> QueryContext:
    """Normalize a string or QueryContext into a QueryContext with keywords."""
    if isinstance(input, str):
        keywords = sorted(extract_keywords(input))
        return QueryContext(text=input, keywords=keywords)

    # Already a QueryContext — extract keywords if missing
    if input.keywords is None:
        input.keywords = sorted(extract_keywords(input.text))
    return input


def keyword_relevance(query: QueryContext, item: ContextItem) -> float:
    """Compute asymmetric Jaccard relevance: fraction of query keywords found in item content."""
    if not query.keywords:
        return 0.0

    query_kws = set(query.keywords)
    item_kws = extract_keywords(item.content)

    if not query_kws:
        return 0.0

    overlap = query_kws & item_kws
    return len(overlap) / len(query_kws)


def compute_relevance(query: QueryContext, item: ContextItem) -> float:
    """Compute relevance between query and item.

    Uses cosine similarity when both have embeddings, otherwise falls back
    to keyword relevance.
    """
    if query.embedding is not None and hasattr(item, "embedding") and item.embedding is not None:
        score = cosine_similarity(query.embedding, item.embedding)
        return max(0.0, min(1.0, score))

    return keyword_relevance(query, item)
