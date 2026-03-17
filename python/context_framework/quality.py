from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal, Protocol, Sequence

_WHITESPACE_RUN_RE = re.compile(r"\s+")


def precision_at_k(ranked_ids: Sequence[str], relevant_ids: set[str], k: int) -> float:
    if k < 1 or not ranked_ids or not relevant_ids:
        return 0.0
    retrieved = ranked_ids[: min(k, len(ranked_ids))]
    hits = sum(1 for doc_id in retrieved if doc_id in relevant_ids)
    return hits / len(retrieved) if retrieved else 0.0


def recall_at_k(ranked_ids: Sequence[str], relevant_ids: set[str], k: int) -> float:
    if k < 1 or not ranked_ids or not relevant_ids:
        return 0.0
    retrieved = ranked_ids[: min(k, len(ranked_ids))]
    hits = sum(1 for doc_id in retrieved if doc_id in relevant_ids)
    return hits / len(relevant_ids) if relevant_ids else 0.0


def mrr(ranked_ids: Sequence[str], relevant_ids: set[str]) -> float:
    if not ranked_ids or not relevant_ids:
        return 0.0
    for idx, doc_id in enumerate(ranked_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / idx
    return 0.0


def average_precision(ranked_ids: Sequence[str], relevant_ids: set[str]) -> float:
    if not ranked_ids or not relevant_ids:
        return 0.0

    hits = 0
    total = 0.0
    for idx, doc_id in enumerate(ranked_ids, start=1):
        if doc_id in relevant_ids:
            hits += 1
            total += hits / idx
    return total / len(relevant_ids) if relevant_ids else 0.0


def ndcg_at_k(ranked_ids: Sequence[str], relevant_ids: set[str], k: int) -> float:
    if k < 1 or not ranked_ids or not relevant_ids:
        return 0.0

    k = min(k, len(ranked_ids))
    dcg = 0.0
    for i in range(k):
        if ranked_ids[i] in relevant_ids:
            dcg += 1.0 / math.log2(i + 2)

    ideal_hits = min(k, len(relevant_ids))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return (dcg / idcg) if idcg > 0 else 0.0


@dataclass(frozen=True, slots=True)
class FaithfulnessVerdict:
    verdict: Literal["pass", "fail", "abstain"]
    reason: str


class FaithfulnessJudge(Protocol):
    async def judge(self, *, claim: str, context: str) -> FaithfulnessVerdict:
        """Judge whether a claim is supported by the provided context."""


@dataclass(frozen=True, slots=True)
class QuoteOnlyFaithfulnessJudge:
    """Offline-safe judge that only 'passes' direct quotes.

    This is intentionally conservative: if the claim is not literally present in
    the context, it abstains rather than hallucinating faithfulness.
    """

    min_claim_chars: int = 16

    async def judge(self, *, claim: str, context: str) -> FaithfulnessVerdict:
        normalized_claim = _WHITESPACE_RUN_RE.sub(" ", (claim or "").strip()).lower()
        normalized_context = _WHITESPACE_RUN_RE.sub(" ", (context or "")).lower()
        if len(normalized_claim) < self.min_claim_chars:
            return FaithfulnessVerdict(verdict="abstain", reason="Claim too short to judge safely.")
        if normalized_claim in normalized_context:
            return FaithfulnessVerdict(
                verdict="pass", reason="Claim is a direct substring of context (case-insensitive)."
            )
        return FaithfulnessVerdict(
            verdict="abstain", reason="No direct textual support found in context."
        )
