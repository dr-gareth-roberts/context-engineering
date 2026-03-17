from __future__ import annotations

import math
import re
import statistics
from abc import ABC, abstractmethod
from typing import List, Optional

from pydantic import BaseModel

from ._similarity import cosine_similarity
from .core import ContextItem, estimate_tokens
from .providers import CerebrasProvider, EmbeddingProvider


class SegmentBoundary(BaseModel):
    """Boundary metadata for a segment. Pydantic model so it survives model_copy/model_dump."""

    is_start: bool = False
    is_end: bool = False
    index: int = 0
    total_segments: int = 0
    parent_id: str = ""


class Segment(ContextItem):
    boundary: Optional[SegmentBoundary] = None

    def to_context_text(self) -> str:
        if not self.boundary:
            return self.content

        header = f"[Segment {self.boundary.index + 1}/{self.boundary.total_segments}"
        if self.boundary.parent_id:
            header += f" of '{self.boundary.parent_id}'"
        header += "]\n"

        footer = ""
        if not self.boundary.is_end:
            footer = "\n[...CONTINUED IN NEXT SEGMENT...]"

        return header + self.content + footer


class BoundaryProtector:
    """
    Ensures segment boundaries don't break atomic information units.
    Protects: Dates, UUIDs, Version numbers, and technical identifiers.
    """

    PROTECTED_PATTERNS = [
        r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2})?",  # ISO Dates/Times
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",  # UUIDs
        r"v?\d+\.\d+\.\d+(?:-\w+)?",  # Version numbers
        r"[A-Z][a-z]+(?:[A-Z][a-z]+)+",  # CamelCase identifiers
        r"\b[A-Z0-9_]{3,}\b",  # CONSTANTS_OR_IDS
    ]

    def __init__(self, custom_entities: Optional[List[str]] = None):
        patterns = self.PROTECTED_PATTERNS.copy()
        if custom_entities:
            # Escape and add custom entities as whole-word matches
            patterns.append(r"\b(?:" + "|".join(map(re.escape, custom_entities)) + r")\b")
        self.combined_re = re.compile("|".join(patterns))

    def get_protection_zones(self, text: str) -> List[tuple[int, int]]:
        """Returns (start, end) indices of characters that should not be split."""
        return [(m.start(), m.end()) for m in self.combined_re.finditer(text)]

    def is_split_safe(self, text: str, split_index: int) -> bool:
        """Checks if a split at char index is inside a protected zone."""
        for start, end in self.get_protection_zones(text):
            if start < split_index < end:
                return False
        return True


class BaseSegmenter(ABC):
    @abstractmethod
    def segment(self, text: str, doc_id: str = "doc") -> List[Segment]:
        pass


class StructuralSegmenter(BaseSegmenter):
    def __init__(
        self, use_markdown: bool = True, max_tokens: int = 500, protector: BoundaryProtector = None
    ):
        self.use_markdown = use_markdown
        self.max_tokens = max_tokens
        self.protector = protector or BoundaryProtector()

    def segment(self, text: str, doc_id: str = "doc") -> List[Segment]:
        if self.use_markdown:
            parts = re.split(r"(^#+\s+.*$)", text, flags=re.MULTILINE)
        else:
            parts = re.split(r"(\n\n+)", text)

        chunks = []
        current_chunk = ""
        for part in parts:
            if not part.strip():
                continue
            candidate = (current_chunk + "\n" + part).strip()

            # If candidate is too big, we split the current_chunk
            if estimate_tokens(candidate) > self.max_tokens and current_chunk:
                chunks.append(current_chunk)
                current_chunk = part
            else:
                current_chunk = candidate

        if current_chunk:
            chunks.append(current_chunk)
        return self._create_segments(chunks, doc_id)

    def _create_segments(self, chunks: List[str], doc_id: str) -> List[Segment]:
        segments = []
        total = len(chunks)
        for i, chunk in enumerate(chunks):
            boundary = SegmentBoundary(
                is_start=(i == 0),
                is_end=(i == total - 1),
                index=i,
                total_segments=total,
                parent_id=doc_id,
            )
            segments.append(
                Segment(id=f"{doc_id}_seg_{i}", content=chunk, boundary=boundary, priority=1.0)
            )
        return segments


class SemanticSegmenter(BaseSegmenter):
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        min_window: int = 1,
        max_window: int = 5,
        threshold: float = 0.7,
        max_tokens: int = 1000,
        model: str = "text-embedding-3-small",
        protector: BoundaryProtector = None,
    ):
        self.provider = embedding_provider
        self.min_window = min_window
        self.max_window = max_window
        self.threshold = threshold
        self.max_tokens = max_tokens
        self.model = model
        self.protector = protector or BoundaryProtector()

    def _get_mean_vector(self, vectors: List[List[float]]) -> List[float]:
        if not vectors:
            return []
        dim = len(vectors[0])
        mean = [0.0] * dim
        for v in vectors:
            for i in range(dim):
                mean[i] += v[i]
        return [x / len(vectors) for x in mean]

    def _calculate_local_variance(
        self, embeddings: List[List[float]], index: int, scope: int = 5
    ) -> float:
        start = max(0, index - scope)
        end = min(len(embeddings), index + scope)
        neighborhood = embeddings[start:end]
        if len(neighborhood) < 2:
            return 0.0
        sims = [
            cosine_similarity(neighborhood[i], neighborhood[i + 1])
            for i in range(len(neighborhood) - 1)
        ]
        return statistics.variance(sims) if len(sims) > 1 else 0.0

    def segment(self, text: str, doc_id: str = "doc") -> List[Segment]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if len(sentences) <= self.min_window:
            return self._create_segments([" ".join(sentences)], doc_id)

        result = self.provider.embed(sentences, model=self.model)
        embeddings = result.vectors

        boundary_scores = []
        for i in range(1, len(sentences)):
            variance = self._calculate_local_variance(embeddings, i)
            norm_var = min(1.0, variance * 10.0)
            dynamic_window = math.ceil(
                self.max_window - (norm_var * (self.max_window - self.min_window))
            )

            prev_start = max(0, i - dynamic_window)
            prev_block = embeddings[prev_start:i]
            next_end = min(len(sentences), i + dynamic_window)
            next_block = embeddings[i:next_end]

            v_prev = self._get_mean_vector(prev_block)
            v_next = self._get_mean_vector(next_block)
            boundary_scores.append(cosine_similarity(v_prev, v_next))

        chunks = []
        current_chunk_sentences = []
        current_chunk_tokens = 0

        # Offset mapping to check protector
        full_text = text
        current_text_offset = 0

        for i, score in enumerate(boundary_scores):
            sent_text = sentences[i]
            current_chunk_sentences.append(sent_text)
            current_chunk_tokens += estimate_tokens(sent_text)

            # Update offset
            current_text_offset = full_text.find(sent_text, current_text_offset) + len(sent_text)

            is_valley = False
            if 0 < i < len(boundary_scores) - 1:
                if score < boundary_scores[i - 1] and score < boundary_scores[i + 1]:
                    is_valley = True

            # SPLIT DECISION
            if (score < self.threshold or is_valley) or current_chunk_tokens > self.max_tokens:
                # ITEM #7: PROTECTOR CHECK
                # If splitting here breaks an entity, we deferred the split
                if self.protector.is_split_safe(full_text, current_text_offset):
                    chunks.append(" ".join(current_chunk_sentences))
                    current_chunk_sentences = []
                    current_chunk_tokens = 0
                # else: we 'leak' into the next loop to keep the entity whole

        if current_chunk_sentences:
            remaining = " ".join(current_chunk_sentences + sentences[len(boundary_scores) :])
            chunks.append(remaining)
        elif boundary_scores and chunks:
            # The last sentence (after boundary_scores) may not have been added
            last_sentence_idx = len(boundary_scores)
            if last_sentence_idx < len(sentences):
                chunks[-1] += " " + sentences[last_sentence_idx]

        return self._create_segments(chunks, doc_id)

    def _create_segments(self, chunks: List[str], doc_id: str) -> List[Segment]:
        return StructuralSegmenter()._create_segments(chunks, doc_id)


class PerplexitySegmenter(BaseSegmenter):
    def __init__(
        self,
        cerebras_provider: CerebrasProvider,
        z_threshold: float = 2.0,
        max_tokens: int = 800,
        model: str = "llama3.1-8b",
        protector: BoundaryProtector = None,
    ):
        self.provider = cerebras_provider
        self.z_threshold = z_threshold
        self.max_tokens = max_tokens
        self.model = model
        self.protector = protector or BoundaryProtector()

    def segment(self, text: str, doc_id: str = "doc") -> List[Segment]:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if len(sentences) < 2:
            return self._create_segments([" ".join(sentences)], doc_id)

        scores = [self.provider.score_perplexity(s, model=self.model) for s in sentences]
        mean = statistics.mean(scores)
        stdev = statistics.stdev(scores) if len(scores) > 1 else 1.0
        z_scores = [(s - mean) / stdev if stdev > 0 else 0.0 for s in scores]

        chunks = []
        current_chunk_sentences = []
        current_chunk_tokens = 0
        current_offset = 0

        for i, z in enumerate(z_scores):
            sent_text = sentences[i]
            current_offset = text.find(sent_text, current_offset) + len(sent_text)

            if current_chunk_sentences and z > self.z_threshold:
                # CHECK PROTECTOR
                if self.protector.is_split_safe(text, current_offset):
                    chunks.append(" ".join(current_chunk_sentences))
                    current_chunk_sentences = [sent_text]
                    current_chunk_tokens = estimate_tokens(sent_text)
                    continue

            current_chunk_sentences.append(sent_text)
            current_chunk_tokens += estimate_tokens(sent_text)
            if current_chunk_tokens > self.max_tokens:
                if self.protector.is_split_safe(text, current_offset):
                    chunks.append(" ".join(current_chunk_sentences))
                    current_chunk_sentences = []
                    current_chunk_tokens = 0

        if current_chunk_sentences:
            chunks.append(" ".join(current_chunk_sentences))
        return self._create_segments(chunks, doc_id)

    def _create_segments(self, chunks: List[str], doc_id: str) -> List[Segment]:
        return StructuralSegmenter()._create_segments(chunks, doc_id)


class HybridSegmenter(BaseSegmenter):
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        cerebras_provider: CerebrasProvider,
        max_tokens: int = 1000,
        semantic_threshold: float = 0.7,
        perplexity_z_threshold: float = 2.0,
        protector: BoundaryProtector = None,
    ):
        self.protector = protector or BoundaryProtector()
        self.structural = StructuralSegmenter(max_tokens=max_tokens * 2, protector=self.protector)
        self.semantic = SemanticSegmenter(
            embedding_provider,
            threshold=semantic_threshold,
            max_tokens=max_tokens,
            protector=self.protector,
        )
        self.perplexity = PerplexitySegmenter(
            cerebras_provider,
            z_threshold=perplexity_z_threshold,
            max_tokens=max_tokens,
            protector=self.protector,
        )
        self.max_tokens = max_tokens

    def segment(self, text: str, doc_id: str = "doc") -> List[Segment]:
        initial_segments = self.structural.segment(text, doc_id)
        final_chunks = []
        for seg in initial_segments:
            sem_refined = self.semantic.segment(seg.content, doc_id="refined")
            for sr in sem_refined:
                perp_refined = self.perplexity.segment(sr.content, doc_id="perp")
                for pr in perp_refined:
                    final_chunks.append(pr.content)
        return self.structural._create_segments(final_chunks, doc_id)
