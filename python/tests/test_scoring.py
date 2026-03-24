"""Tests for context_framework.scoring module."""

from __future__ import annotations

import pytest

from context_framework.models import ContextItem, ContextKind
from context_framework.scoring import KeywordOverlapScorer, cosine_similarity

# ---------------------------------------------------------------------------
# KeywordOverlapScorer
# ---------------------------------------------------------------------------


def _item(text: str) -> ContextItem:
    return ContextItem(text=text, kind=ContextKind.DOCUMENT)


def test_keyword_overlap_returns_zero_for_no_overlap():
    scorer = KeywordOverlapScorer()
    score = scorer.score("alpha beta gamma", _item("delta epsilon zeta"))
    assert score == 0.0


def test_keyword_overlap_returns_one_for_identical_sets():
    scorer = KeywordOverlapScorer()
    score = scorer.score("hello world", _item("hello world"))
    assert score == 1.0


def test_keyword_overlap_returns_fraction_for_partial_overlap():
    scorer = KeywordOverlapScorer()
    # query tokens: {machine, learning}
    # item tokens: {machine, vision}
    # overlap = 1, union = 3 => 1/3
    score = scorer.score("machine learning", _item("machine vision"))
    assert 0.0 < score < 1.0
    assert abs(score - 1 / 3) < 1e-9


# ---------------------------------------------------------------------------
# cosine_similarity
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical_vectors():
    assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal_vectors():
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_cosine_similarity_raises_on_different_dimensions():
    with pytest.raises(ValueError, match="same dimensions"):
        cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])
