"""Shared cosine similarity utility.

Consolidated from core.py, memory.py, redundancy.py, and segmentation.py
to ensure consistent behavior across the SDK.
"""

from __future__ import annotations

import math
from typing import List


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        v1: First vector.
        v2: Second vector (must have same dimensionality as v1).

    Returns:
        Cosine similarity in [-1, 1]. Returns 0.0 if either vector
        has zero magnitude.

    Raises:
        ValueError: If vectors have different dimensions.
    """
    if len(v1) != len(v2):
        raise ValueError(f"Embedding dimensions must match: {len(v1)} != {len(v2)}")
    dot_product = sum(a * b for a, b in zip(v1, v2))
    m1 = math.sqrt(sum(a * a for a in v1))
    m2 = math.sqrt(sum(a * a for a in v2))
    if m1 == 0.0 or m2 == 0.0:
        return 0.0
    return dot_product / (m1 * m2)
