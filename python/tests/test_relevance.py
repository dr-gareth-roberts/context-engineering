"""Tests for query-aware relevance scoring."""

from context_engineering.core import create_context_item
from context_engineering.relevance import (
    QueryContext,
    compute_relevance,
    extract_keywords,
    keyword_relevance,
    normalize_query,
)


class TestExtractKeywords:
    def test_filters_stopwords_and_single_chars(self):
        result = extract_keywords("The Quick Brown Fox is a Great Animal")
        assert "the" not in result
        assert "is" not in result
        assert "a" not in result
        assert "quick" in result
        assert "brown" in result
        assert "fox" in result

    def test_empty_string(self):
        assert len(extract_keywords("")) == 0


class TestNormalizeQuery:
    def test_string_input(self):
        result = normalize_query("search for relevant documents")
        assert result.text == "search for relevant documents"
        assert result.keywords is not None
        assert len(result.keywords) > 0
        assert "search" in result.keywords

    def test_preserves_existing_keywords(self):
        q = QueryContext(text="hello", keywords=["custom", "kw"])
        result = normalize_query(q)
        assert result.keywords == ["custom", "kw"]

    def test_extracts_when_missing(self):
        q = QueryContext(text="machine learning algorithms")
        result = normalize_query(q)
        assert result.keywords is not None
        assert len(result.keywords) > 0


class TestKeywordRelevance:
    def test_all_found(self):
        q = QueryContext(text="machine learning", keywords=["machine", "learning"])
        item = create_context_item("d", "machine learning is powerful")
        assert keyword_relevance(q, item) == 1.0

    def test_half_found(self):
        q = QueryContext(text="machine learning", keywords=["machine", "learning"])
        item = create_context_item("d", "machine is fast")
        assert keyword_relevance(q, item) == 0.5

    def test_none_found(self):
        q = QueryContext(text="machine learning", keywords=["machine", "learning"])
        item = create_context_item("d", "completely unrelated text")
        assert keyword_relevance(q, item) == 0.0

    def test_empty_query(self):
        q = QueryContext(text="", keywords=[])
        item = create_context_item("d", "some content")
        assert keyword_relevance(q, item) == 0.0


class TestComputeRelevance:
    def test_uses_embedding_when_available(self):
        q = QueryContext(text="test", keywords=["test"], embedding=[1.0, 0.0, 0.0])
        item = create_context_item("d", "unrelated", embedding=[1.0, 0.0, 0.0])
        score = compute_relevance(q, item)
        assert abs(score - 1.0) < 0.01

    def test_falls_back_to_keywords(self):
        q = QueryContext(text="machine learning", keywords=["machine", "learning"])
        item = create_context_item("d", "machine learning rocks")
        assert compute_relevance(q, item) == 1.0
