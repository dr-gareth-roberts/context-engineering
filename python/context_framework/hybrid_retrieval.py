from __future__ import annotations

import math
from collections import Counter
from typing import Callable, Sequence

try:
    from rank_bm25 import BM25Okapi  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    BM25Okapi = None  # type: ignore[assignment]

from .retrieval import RetrievedChunk, Retriever
from .scoring import cosine_similarity


def _tokenize_for_bm25(text: str) -> list[str]:
    return [t for t in text.lower().split() if t]


class _SimpleBM25:
    def __init__(
        self, tokenized_corpus: Sequence[Sequence[str]], *, k1: float = 1.5, b: float = 0.75
    ):
        self._k1 = k1
        self._b = b
        self._corpus = [list(doc) for doc in tokenized_corpus]
        self._doc_lens = [len(doc) for doc in self._corpus]
        self._avgdl = (sum(self._doc_lens) / len(self._doc_lens)) if self._doc_lens else 0.0

        df: Counter[str] = Counter()
        for doc in self._corpus:
            df.update(set(doc))
        self._df = df
        self._n_docs = len(self._corpus)

        # idf with BM25+ style smoothing
        self._idf: dict[str, float] = {}
        for term, freq in df.items():
            self._idf[term] = math.log((self._n_docs - freq + 0.5) / (freq + 0.5) + 1.0)

        self._tfs = [Counter(doc) for doc in self._corpus]

    def get_scores(self, query_tokens: Sequence[str]) -> list[float]:
        if self._n_docs == 0:
            return []
        scores = [0.0 for _ in range(self._n_docs)]
        for term in query_tokens:
            idf = self._idf.get(term)
            if idf is None:
                continue
            for i in range(self._n_docs):
                tf = self._tfs[i].get(term, 0)
                if tf == 0:
                    continue
                dl = self._doc_lens[i]
                denom = tf + self._k1 * (1.0 - self._b + self._b * (dl / (self._avgdl or 1.0)))
                scores[i] += idf * ((tf * (self._k1 + 1.0)) / denom)
        return scores


def _chunk_key(chunk: RetrievedChunk) -> str:
    if chunk.source:
        return chunk.source
    synthetic = chunk.metadata.get("id") if isinstance(chunk.metadata, dict) else None
    if synthetic:
        return str(synthetic)
    return chunk.text


def rrf_fuse(
    *,
    ranked_lists: Sequence[Sequence[RetrievedChunk]],
    k: int = 60,
    top_k: int = 5,
) -> list[RetrievedChunk]:
    """Fuse ranked lists with Reciprocal Rank Fusion (RRF).

    Args:
        ranked_lists: Each list is assumed to already be ranked best-first.
        k: RRF constant (higher dampens rank differences). Common default is 60.
        top_k: Number of fused results to return.
    """

    if top_k < 1:
        return []

    scores: dict[str, float] = {}
    canonical: dict[str, RetrievedChunk] = {}
    ranks: dict[str, dict[str, int]] = {}

    for list_idx, ranked in enumerate(ranked_lists):
        list_name = f"list_{list_idx}"
        for rank, chunk in enumerate(ranked, start=1):
            key = _chunk_key(chunk)
            canonical.setdefault(key, chunk)
            scores[key] = scores.get(key, 0.0) + (1.0 / (k + rank))
            ranks.setdefault(key, {})[f"{list_name}_rank"] = rank

    fused_keys = sorted(scores.keys(), key=lambda key: scores[key], reverse=True)[:top_k]
    fused: list[RetrievedChunk] = []
    for key in fused_keys:
        base = canonical[key]
        metadata = dict(base.metadata)
        metadata.update(ranks.get(key, {}))
        metadata["rrf_score"] = scores[key]
        fused.append(
            RetrievedChunk(
                text=base.text,
                source=base.source,
                score=scores[key],
                importance=base.importance,
                tags=base.tags,
                metadata=metadata,
            )
        )
    return fused


class HybridInMemoryRetriever(Retriever):
    """Hybrid retriever (BM25 + cosine similarity) fused with RRF.

    This is designed for local testing and small corpora. In production you'd
    likely back this with a sparse index (BM25) + a vector DB, then fuse the
    two ranked lists with RRF.
    """

    def __init__(
        self,
        chunks: Sequence[RetrievedChunk],
        *,
        embed: Callable[[str], Sequence[float]],
        rrf_k: int = 60,
        oversample: int = 2,
    ) -> None:
        self._chunks = list(chunks)
        self._embed = embed
        self._rrf_k = rrf_k
        self._oversample = max(1, oversample)

        self._vectors = [tuple(float(v) for v in embed(chunk.text)) for chunk in self._chunks]
        tokenized_corpus = [_tokenize_for_bm25(chunk.text) for chunk in self._chunks]
        if BM25Okapi is not None:
            self._bm25 = BM25Okapi(tokenized_corpus)  # type: ignore[misc]
        else:
            self._bm25 = _SimpleBM25(tokenized_corpus)

    def _vector_rank(self, query: str, *, k: int) -> list[RetrievedChunk]:
        query_vector = tuple(float(v) for v in self._embed(query))
        scored: list[tuple[float, int]] = []
        for idx, vector in enumerate(self._vectors):
            scored.append((cosine_similarity(query_vector, vector), idx))
        scored.sort(key=lambda pair: pair[0], reverse=True)

        ranked: list[RetrievedChunk] = []
        for score, idx in scored[:k]:
            base = self._chunks[idx]
            metadata = dict(base.metadata)
            metadata["vector_score"] = float(score)
            ranked.append(
                RetrievedChunk(
                    text=base.text,
                    source=base.source,
                    score=float(score),
                    importance=base.importance,
                    tags=base.tags,
                    metadata=metadata,
                )
            )
        return ranked

    def _bm25_rank(self, query: str, *, k: int) -> list[RetrievedChunk]:
        tokenized_query = _tokenize_for_bm25(query)
        scores = list(float(v) for v in self._bm25.get_scores(tokenized_query))
        scored: list[tuple[float, int]] = [(score, idx) for idx, score in enumerate(scores)]
        scored.sort(key=lambda pair: pair[0], reverse=True)

        ranked: list[RetrievedChunk] = []
        for score, idx in scored[:k]:
            base = self._chunks[idx]
            metadata = dict(base.metadata)
            metadata["bm25_score"] = float(score)
            ranked.append(
                RetrievedChunk(
                    text=base.text,
                    source=base.source,
                    score=float(score),
                    importance=base.importance,
                    tags=base.tags,
                    metadata=metadata,
                )
            )
        return ranked

    def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        if k < 1:
            return []

        candidate_k = k * self._oversample
        vector_ranked = self._vector_rank(query, k=candidate_k)
        bm25_ranked = self._bm25_rank(query, k=candidate_k)

        fused = rrf_fuse(ranked_lists=[vector_ranked, bm25_ranked], k=self._rrf_k, top_k=k)
        if min_score is not None:
            fused = [c for c in fused if (c.score or 0.0) >= min_score]
        return fused
