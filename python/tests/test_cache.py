"""Tests for the cache module: LRU-cached token estimator."""
import pytest

from context_engineering.cache import create_cached_estimator


class TestCachedEstimator:
    def test_returns_same_result(self):
        base = lambda text: len(text.split())
        cached = create_cached_estimator(base)
        assert cached("hello world") == 2
        assert cached("one two three") == 3

    def test_cache_avoids_recomputation(self):
        call_count = 0

        def counting_estimator(text: str) -> int:
            nonlocal call_count
            call_count += 1
            return len(text.split())

        cached = create_cached_estimator(counting_estimator)
        cached("hello world")
        cached("hello world")
        cached("hello world")
        assert call_count == 1

    def test_different_texts_cached_separately(self):
        call_count = 0

        def counting_estimator(text: str) -> int:
            nonlocal call_count
            call_count += 1
            return len(text.split())

        cached = create_cached_estimator(counting_estimator)
        cached("hello")
        cached("world")
        cached("hello")
        cached("world")
        assert call_count == 2

    def test_max_size_eviction(self):
        call_count = 0

        def counting_estimator(text: str) -> int:
            nonlocal call_count
            call_count += 1
            return len(text)

        cached = create_cached_estimator(counting_estimator, max_size=3)
        cached("a")  # cache: [a]
        cached("b")  # cache: [a, b]
        cached("c")  # cache: [a, b, c]
        cached("d")  # cache: [b, c, d] — a evicted
        assert call_count == 4

        # "a" was evicted, should recompute
        cached("a")
        assert call_count == 5

        # "d" is still cached
        cached("d")
        assert call_count == 5

    def test_empty_string(self):
        base = lambda text: 0 if not text.strip() else len(text.split())
        cached = create_cached_estimator(base)
        assert cached("") == 0
        assert cached("") == 0
