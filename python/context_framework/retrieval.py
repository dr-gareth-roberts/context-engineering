from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol, Sequence

from .scoring import cosine_similarity


@dataclass(slots=True)
class RetrievedChunk:
    text: str
    source: str | None = None
    score: float | None = None
    importance: float | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class Retriever(Protocol):
    def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        min_score: float | None = None,
    ) -> list[RetrievedChunk]: ...


class InMemoryVectorRetriever:
    """
    Lightweight retriever for local testing and small projects.
    """

    def __init__(
        self,
        items: Sequence[RetrievedChunk | str],
        *,
        embed: Callable[[str], Sequence[float]],
    ) -> None:
        self._embed = embed
        self._chunks: list[RetrievedChunk] = []
        self._vectors: list[tuple[float, ...]] = []
        for item in items:
            chunk = item if isinstance(item, RetrievedChunk) else RetrievedChunk(text=item)
            self._chunks.append(chunk)
            self._vectors.append(tuple(float(v) for v in embed(chunk.text)))

    def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        if k < 1:
            return []
        query_vector = tuple(float(v) for v in self._embed(query))
        scored: list[tuple[float, RetrievedChunk]] = []
        for vector, chunk in zip(self._vectors, self._chunks, strict=True):
            score = cosine_similarity(query_vector, vector)
            if min_score is not None and score < min_score:
                continue
            scored.append((score, chunk))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        selected: list[RetrievedChunk] = []
        for score, chunk in scored[:k]:
            selected.append(
                RetrievedChunk(
                    text=chunk.text,
                    source=chunk.source,
                    score=score,
                    importance=chunk.importance,
                    tags=chunk.tags,
                    metadata=dict(chunk.metadata),
                )
            )
        return selected


class ChromaRetriever:
    """
    Adapter for Chroma collections (`collection.query`).

    The ``distance_metric`` parameter must match the metric used by the
    Chroma collection (default ``"l2"``).  Supported values: ``"l2"``,
    ``"cosine"``, ``"ip"`` (inner product).
    """

    def __init__(
        self,
        collection: Any,
        *,
        distance_metric: Literal["l2", "cosine", "ip"] = "l2",
    ) -> None:
        self._collection = collection
        self._distance_metric = distance_metric

    def _distance_to_score(self, distance: float) -> float:
        if self._distance_metric == "l2":
            return 1.0 / (1.0 + distance)
        if self._distance_metric == "cosine":
            return 1.0 - distance
        # inner product: Chroma returns negative IP as distance
        return -distance

    def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        if k < 1:
            return []
        result = self._collection.query(query_texts=[query], n_results=k)
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]

        chunks: list[RetrievedChunk] = []
        for idx, text in enumerate(docs):
            metadata = dict(metas[idx] or {}) if idx < len(metas) else {}
            source = metadata.get("source") or (ids[idx] if idx < len(ids) else None)
            distance = float(distances[idx]) if idx < len(distances) else 0.0
            score = self._distance_to_score(distance)
            if min_score is not None and score < min_score:
                continue
            chunks.append(
                RetrievedChunk(
                    text=text,
                    source=str(source) if source is not None else None,
                    score=score,
                    metadata=metadata,
                )
            )
        return chunks


class PineconeRetriever:
    """
    Adapter for Pinecone indexes (`index.query`).
    """

    def __init__(
        self,
        index: Any,
        *,
        embed: Callable[[str], Sequence[float]],
        namespace: str | None = None,
        text_field: str = "text",
        source_field: str = "source",
    ) -> None:
        self._index = index
        self._embed = embed
        self._namespace = namespace
        self._text_field = text_field
        self._source_field = source_field

    def retrieve(
        self,
        query: str,
        *,
        k: int = 5,
        min_score: float | None = None,
    ) -> list[RetrievedChunk]:
        if k < 1:
            return []

        vector = list(float(v) for v in self._embed(query))
        kwargs: dict[str, Any] = {
            "vector": vector,
            "top_k": k,
            "include_metadata": True,
        }
        if self._namespace:
            kwargs["namespace"] = self._namespace

        response = self._index.query(**kwargs)
        matches = response.get("matches") if isinstance(response, dict) else response.matches

        chunks: list[RetrievedChunk] = []
        for match in matches:
            if isinstance(match, dict):
                metadata = dict(match.get("metadata") or {})
                score = float(match.get("score") or 0.0)
                match_id = match.get("id")
            else:
                metadata = dict(getattr(match, "metadata", {}) or {})
                score = float(getattr(match, "score", 0.0))
                match_id = getattr(match, "id", None)

            if min_score is not None and score < min_score:
                continue

            text = metadata.get(self._text_field)
            if not text:
                continue
            source = metadata.get(self._source_field) or match_id
            chunks.append(
                RetrievedChunk(
                    text=str(text),
                    source=str(source) if source is not None else None,
                    score=score,
                    metadata=metadata,
                )
            )
        return chunks
