"""Tests for context debugger — diagnosis, proactive checks, and comparison."""

import pytest

from context_engineering.core import Budget, ContextItem, ContextPack
from context_engineering.debugger import (
    QualityThresholds,
    create_context_debugger,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_item(id: str, content: str, **kwargs) -> ContextItem:
    return ContextItem(id=id, content=content, **kwargs)


def _make_pack(
    selected: list[ContextItem],
    dropped: list[ContextItem] | None = None,
    max_tokens: int = 10000,
) -> ContextPack:
    total = sum(item.tokens or 10 for item in selected)
    return ContextPack(
        budget=Budget(maxTokens=max_tokens),
        selected=selected,
        dropped=dropped or [],
        totalTokens=total,
    )


# ---------------------------------------------------------------------------
# Diagnosis — redundancy
# ---------------------------------------------------------------------------


class TestDiagnoseRedundancy:
    def test_detects_high_redundancy(self):
        # Create items with very similar content.
        items = [
            _make_item("a", "the quick brown fox jumps over the lazy dog", tokens=20),
            _make_item("b", "the quick brown fox leaps over the lazy dog", tokens=20),
            _make_item("c", "the quick brown fox hops over the lazy dog", tokens=20),
        ]
        pack = _make_pack(items)
        debugger = create_context_debugger(QualityThresholds(max_redundancy=0.1))

        diagnosis = debugger.diagnose(pack)

        redundancy_issues = [i for i in diagnosis.issues if i.category == "redundancy"]
        assert len(redundancy_issues) > 0

    def test_no_redundancy_issue_for_diverse_content(self):
        items = [
            _make_item("a", "quantum mechanics wave function collapse", tokens=20),
            _make_item("b", "database indexing strategies B-tree hash", tokens=20),
            _make_item("c", "machine learning gradient descent optimizer", tokens=20),
        ]
        pack = _make_pack(items)
        debugger = create_context_debugger()

        diagnosis = debugger.diagnose(pack)

        redundancy_issues = [i for i in diagnosis.issues if i.category == "redundancy"]
        assert len(redundancy_issues) == 0


# ---------------------------------------------------------------------------
# Diagnosis — staleness
# ---------------------------------------------------------------------------


class TestDiagnoseStaleness:
    def test_detects_stale_context(self):
        items = [
            _make_item("a", "old content about legacy systems", tokens=20, recency=0.1),
            _make_item("b", "another old document from archives", tokens=20, recency=0.2),
            _make_item("c", "outdated specification from last decade", tokens=20, recency=0.0),
        ]
        pack = _make_pack(items)
        debugger = create_context_debugger()

        diagnosis = debugger.diagnose(pack)

        stale_issues = [i for i in diagnosis.issues if i.category == "stale-context"]
        assert len(stale_issues) > 0

    def test_no_staleness_issue_for_fresh_content(self):
        items = [
            _make_item("a", "latest update on current system", tokens=20, recency=8.0),
            _make_item("b", "recent changes to the API", tokens=20, recency=9.0),
        ]
        pack = _make_pack(items)
        debugger = create_context_debugger()

        diagnosis = debugger.diagnose(pack)

        stale_issues = [i for i in diagnosis.issues if i.category == "stale-context"]
        assert len(stale_issues) == 0


# ---------------------------------------------------------------------------
# Diagnosis — diversity
# ---------------------------------------------------------------------------


class TestDiagnoseDiversity:
    def test_detects_low_diversity(self):
        # Very similar bigram patterns.
        items = [
            _make_item("a", "foo bar baz", tokens=10),
            _make_item("b", "foo bar baz", tokens=10),
        ]
        pack = _make_pack(items)
        debugger = create_context_debugger(QualityThresholds(min_diversity=0.9))

        diagnosis = debugger.diagnose(pack)

        diversity_issues = [i for i in diagnosis.issues if i.category == "low-diversity"]
        assert len(diversity_issues) > 0


# ---------------------------------------------------------------------------
# Diagnosis — dropped items
# ---------------------------------------------------------------------------


class TestDiagnoseDroppedItems:
    def test_detects_dropped_high_priority_items(self):
        selected = [
            _make_item("low", "low priority content kept", tokens=50, priority=2.0),
        ]
        dropped = [
            _make_item("high", "high priority content dropped", tokens=100, priority=9.0),
        ]
        pack = _make_pack(selected, dropped, max_tokens=60)
        debugger = create_context_debugger()

        diagnosis = debugger.diagnose(pack)

        assert diagnosis.dropped_analysis.total_dropped == 1
        assert len(diagnosis.dropped_analysis.high_priority_dropped) == 1
        # Should flag as critical.
        assert diagnosis.overall_health == "critical"


# ---------------------------------------------------------------------------
# Overall health
# ---------------------------------------------------------------------------


class TestOverallHealth:
    def test_returns_good_for_balanced_pack(self):
        items = [
            _make_item(
                "a", "comprehensive guide to quantum computing fundamentals", tokens=50, recency=8.0
            ),
            _make_item(
                "b", "database optimization strategies and best practices", tokens=50, recency=7.0
            ),
            _make_item(
                "c",
                "machine learning deployment pipeline architecture overview",
                tokens=50,
                recency=9.0,
            ),
        ]
        pack = _make_pack(items, max_tokens=200)
        debugger = create_context_debugger()

        diagnosis = debugger.diagnose(pack)

        # No critical issues for diverse, fresh, non-redundant content.
        critical = [i for i in diagnosis.issues if i.severity == "critical"]
        assert len(critical) == 0

    def test_returns_critical_for_bad_pack(self):
        content = "repeated identical content across all items for testing purposes"
        items = [
            _make_item("a", content, tokens=20, recency=0.1),
            _make_item("b", content, tokens=20, recency=0.0),
        ]
        dropped = [_make_item("c", "important content", tokens=50, priority=9.0)]
        pack = _make_pack(items, dropped, max_tokens=50)
        debugger = create_context_debugger(QualityThresholds(max_redundancy=0.1))

        diagnosis = debugger.diagnose(pack)

        assert diagnosis.overall_health == "critical"


# ---------------------------------------------------------------------------
# Proactive check
# ---------------------------------------------------------------------------


class TestProactiveCheck:
    def test_proactive_check_catches_issues(self):
        items = [
            _make_item("a", "content alpha", tokens=20, priority=1.0),
            _make_item("b", "content beta", tokens=20, priority=10.0),
            _make_item("c", "content gamma delta epsilon", tokens=200, priority=5.0),
        ]
        debugger = create_context_debugger()

        diagnosis = debugger.proactive_check(items, Budget(maxTokens=50))

        # Some items should be dropped.
        assert diagnosis.dropped_analysis.total_dropped > 0

    def test_proactive_check_with_query(self):
        items = [
            _make_item("a", "python async programming patterns", tokens=20, priority=5.0),
            _make_item("b", "javascript dom manipulation basics", tokens=20, priority=5.0),
        ]
        debugger = create_context_debugger()

        diagnosis = debugger.proactive_check(items, Budget(maxTokens=100), query="python async")

        assert diagnosis.quality is not None


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


class TestComparison:
    def test_comparison_computes_quality_delta(self):
        pack_a = _make_pack(
            [
                _make_item("a1", "quantum mechanics wave function", tokens=20),
                _make_item("a2", "general relativity spacetime curvature", tokens=20),
            ]
        )
        pack_b = _make_pack(
            [
                _make_item("b1", "machine learning neural networks deep", tokens=20),
                _make_item("a1", "quantum mechanics wave function", tokens=20),
            ]
        )
        debugger = create_context_debugger()

        result = debugger.compare_responses(pack_a, 0.6, pack_b, 0.9)

        assert result.quality_delta == pytest.approx(0.3, abs=0.01)
        assert "a2" in result.item_diff["only_in_a"]
        assert "b1" in result.item_diff["only_in_b"]
        assert "a1" in result.item_diff["shared"]

    def test_comparison_generates_insights(self):
        pack_a = _make_pack(
            [
                _make_item("a", "old legacy content repeated", tokens=20, recency=0.1),
            ]
        )
        pack_b = _make_pack(
            [
                _make_item("b", "fresh new content with details", tokens=20, recency=9.0),
            ]
        )
        debugger = create_context_debugger()

        result = debugger.compare_responses(pack_a, 0.3, pack_b, 0.8)

        assert len(result.insights) > 0
        assert result.quality_delta > 0

    def test_comparison_with_identical_packs(self):
        items = [_make_item("a", "shared content", tokens=20)]
        pack_a = _make_pack(items)
        pack_b = _make_pack(items)
        debugger = create_context_debugger()

        result = debugger.compare_responses(pack_a, 0.7, pack_b, 0.7)

        assert result.quality_delta == 0.0
        assert len(result.item_diff["only_in_a"]) == 0
        assert len(result.item_diff["only_in_b"]) == 0
