"""Cache module: LRU-cached token estimator wrapper.

Wraps an existing estimator with content-keyed caching to avoid
redundant estimation of the same text.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Callable


def create_cached_estimator(
    estimator: Callable[[str], int],
    max_size: int = 1000,
) -> Callable[[str], int]:
    """Create a cached token estimator using an LRU cache.

    Args:
        estimator: The base token estimator to wrap.
        max_size: Maximum cache entries (default: 1000).

    Returns:
        A cached estimator function with the same signature.
    """
    cache: OrderedDict[str, int] = OrderedDict()
    lock = threading.Lock()

    def cached(text: str) -> int:
        with lock:
            if text in cache:
                cache.move_to_end(text)
                return cache[text]

        result = estimator(text)

        with lock:
            if len(cache) >= max_size:
                cache.popitem(last=False)

            cache[text] = result
        return result

    return cached
