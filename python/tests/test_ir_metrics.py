from __future__ import annotations

import pytest

from context_framework.quality import (
    QuoteOnlyFaithfulnessJudge,
    average_precision,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_precision_and_recall_at_k() -> None:
    ranked = ["a", "b", "c", "d"]
    relevant = {"b", "d"}
    assert precision_at_k(ranked, relevant, 2) == 0.5
    assert recall_at_k(ranked, relevant, 2) == 0.5
    assert recall_at_k(ranked, relevant, 4) == 1.0


def test_mrr_and_average_precision() -> None:
    ranked = ["x", "y", "z"]
    relevant = {"z"}
    assert mrr(ranked, relevant) == pytest.approx(1 / 3)
    assert average_precision(ranked, relevant) == pytest.approx(1 / 3)


def test_ndcg_at_k_is_one_for_ideal_ranking() -> None:
    ranked = ["a", "b", "c"]
    relevant = {"a", "b"}
    assert ndcg_at_k(ranked, relevant, 2) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_quote_only_faithfulness_judge_is_conservative() -> None:
    judge = QuoteOnlyFaithfulnessJudge()
    verdict = await judge.judge(claim="this is not in context", context="different context")
    assert verdict.verdict == "abstain"
