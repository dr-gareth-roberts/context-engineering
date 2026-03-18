"""Query-aware relevance scoring for context selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Set, Union

from ._similarity import cosine_similarity
from .bm25 import BM25Index, create_bm25_index, unicode_tokenize
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
    words = unicode_tokenize(text)
    return {w for w in words if w not in STOPWORDS}


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

    overlap = query_kws & item_kws
    return len(overlap) / len(query_kws)


def compute_relevance(
    query: QueryContext,
    item: ContextItem,
    *,
    scoring_method: str = "bm25",
    index: Optional[BM25Index] = None,
) -> float:
    """Compute relevance between query and item.

    Uses cosine similarity when both have embeddings, then BM25 (default)
    or keyword matching as fallback.

    Args:
        query: Normalized query context.
        item: Context item to score.
        scoring_method: "bm25" (default) or "keyword".
        index: Pre-built BM25 index for corpus-aware scoring.
    """
    if query.embedding is not None and hasattr(item, "embedding") and item.embedding is not None:
        score = cosine_similarity(query.embedding, item.embedding)
        return max(0.0, min(1.0, score))

    if scoring_method == "keyword":
        return keyword_relevance(query, item)

    # BM25 scoring
    if index is not None:
        raw = index.score(query.text, item.id)
        return raw / (raw + 1) if raw > 0 else 0.0

    # No index provided -- build a single-document index on the fly
    idx = create_bm25_index()
    idx.add(item.id, item.content)
    raw = idx.score(query.text, item.id)
    return raw / (raw + 1) if raw > 0 else 0.0
