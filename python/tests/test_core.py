import pytest

from context_engineering.core import (
    Budget,
    ContextItem,
    create_context_item,
    diff,
    estimate_tokens,
    pack,
)
from context_engineering.errors import (
    BudgetExceededError,
    ContextEngineeringError,
    EstimationError,
    ValidationDetail,
    ValidationError,
)


def test_pack_selects_high_priority():
    items = [
        ContextItem(id="a", content="important", priority=10, tokens=50),
        ContextItem(id="b", content="less", priority=1, tokens=50),
    ]
    result = pack(items, Budget(maxTokens=60))
    ids = [i.id for i in result.selected]
    assert "a" in ids
    assert "b" not in ids


def test_diff_detects_changes():
    before = [ContextItem(id="a", content="hello", tokens=10)]
    after = [ContextItem(id="b", content="world", tokens=10)]
    result = diff(before, after)
    assert len(result["added"]) == 1
    assert len(result["removed"]) == 1


def test_pack_empty_items():
    result = pack([], Budget(maxTokens=100))
    assert result.selected == []
    assert result.dropped == []
    assert result.total_tokens == 0


def test_pack_rejects_negative_budget():
    with pytest.raises(ValidationError) as exc_info:
        pack([], Budget(maxTokens=-1))
    assert exc_info.value.code == "VALIDATION_ERROR"


def test_pack_rejects_zero_budget():
    with pytest.raises(ValidationError):
        pack([], Budget(maxTokens=0))


def test_pack_rejects_reserve_exceeding_max():
    items = [ContextItem(id="a", content="test", tokens=10)]
    with pytest.raises(BudgetExceededError) as exc_info:
        pack(items, Budget(maxTokens=100, reserveTokens=100))
    assert exc_info.value.code == "BUDGET_EXCEEDED"


def test_estimate_tokens_empty_string():
    assert estimate_tokens("") == 0


def test_estimate_tokens_normal_text():
    tokens = estimate_tokens("hello world")
    assert tokens > 0


def test_diff_empty_inputs():
    result = diff([], [])
    assert result["added"] == []
    assert result["removed"] == []


def test_diff_content_changes():
    before = [ContextItem(id="a", content="old", tokens=10)]
    after = [ContextItem(id="a", content="new", tokens=10)]
    result = diff(before, after)
    assert len(result["changed"]) == 1


def test_pack_drops_all_when_nothing_fits():
    items = [ContextItem(id="a", content="big item", tokens=1000)]
    result = pack(items, Budget(maxTokens=5))
    assert len(result.selected) == 0
    assert len(result.dropped) == 1


# --- Error hierarchy tests ---


def test_error_hierarchy():
    """All custom errors inherit from ContextEngineeringError."""
    assert issubclass(ValidationError, ContextEngineeringError)
    assert issubclass(BudgetExceededError, ContextEngineeringError)
    assert issubclass(EstimationError, ContextEngineeringError)
    # And from Exception
    assert issubclass(ContextEngineeringError, Exception)


def test_validation_error_has_details():
    """ValidationError carries structured details."""
    err = ValidationError("bad input", [{"path": "budget", "message": "must be positive"}])
    assert err.code == "VALIDATION_ERROR"
    assert len(err.details) == 1
    assert err.details[0] == ValidationDetail(path="budget", message="must be positive")


def test_pack_treats_mismatched_embedding_dimensions_as_non_redundant():
    items = [
        ContextItem(
            id="a",
            content="one",
            tokens=10,
            embedding=[1.0, 0.0],
        ),
        ContextItem(
            id="b",
            content="two",
            tokens=10,
            embedding=[1.0, 0.0, 0.0],
        ),
    ]

    result = pack(items, Budget(maxTokens=100), redundancy_threshold=0.5)
    assert [item.id for item in result.selected] == ["a", "b"]


def test_estimation_error_from_cost():
    """estimate_cost raises EstimationError for unknown models."""
    from context_engineering.cost import estimate_cost

    items = [ContextItem(id="a", content="test", tokens=100)]
    # Create a minimal CacheAwarePack to pass to estimate_cost
    from context_engineering.cache_topology import pack_with_cache_topology

    pack_result = pack_with_cache_topology(items, Budget(maxTokens=500))
    with pytest.raises(EstimationError) as exc_info:
        estimate_cost(pack_result, "nonexistent-model-xyz")
    assert "nonexistent-model-xyz" in str(exc_info.value)
    assert exc_info.value.code == "ESTIMATION_ERROR"


# --- create_context_item tests ---


def test_create_context_item_basic():
    """create_context_item creates a valid ContextItem with just id and content."""
    item = create_context_item("readme", "# Hello World")
    assert item.id == "readme"
    assert item.content == "# Hello World"
    assert item.kind is None
    assert item.priority is None


def test_create_context_item_with_overrides():
    """create_context_item accepts keyword overrides."""
    item = create_context_item("code", "def foo(): pass", kind="code", priority=10, tokens=50)
    assert item.id == "code"
    assert item.kind == "code"
    assert item.priority == 10
    assert item.tokens == 50


def test_create_context_item_works_with_pack():
    """Items from create_context_item work with pack()."""
    items = [
        create_context_item("a", "hello world", tokens=10),
        create_context_item("b", "foo bar", tokens=20),
    ]
    result = pack(items, Budget(maxTokens=50))
    assert len(result.selected) == 2


# --- Core edge case tests ---


def test_pack_tokens_zero_respected():
    """Item with tokens=0 should be selected and the 0 respected (not re-estimated)."""
    items = [ContextItem(id="zero", content="some text", tokens=0)]
    result = pack(items, Budget(maxTokens=10))
    assert len(result.selected) == 1
    assert result.selected[0].tokens == 0
    assert result.total_tokens == 0


def test_pack_negative_tokens_rejected():
    """Item with negative tokens should be rejected."""
    items = [ContextItem(id="neg", content="test", tokens=-5)]
    with pytest.raises(ValidationError, match="negative tokens"):
        pack(items, Budget(maxTokens=100))


def test_pack_all_undefined_scoring():
    """Items with no priority/recency/score should still pack successfully."""
    items = [
        ContextItem(id="a", content="hello world"),  # no priority, recency, score, tokens
        ContextItem(id="b", content="foo bar"),
    ]
    result = pack(items, Budget(maxTokens=1000))
    assert len(result.selected) == 2


def test_pack_budget_1_positive_fit():
    """Item with tokens=1 fits budget=1 exactly."""
    items = [ContextItem(id="tiny", content="x", tokens=1)]
    result = pack(items, Budget(maxTokens=1))
    assert len(result.selected) == 1
    assert result.total_tokens == 1


def test_pack_duplicate_ids():
    """Two items with the same ID are both processed without crash."""
    items = [
        ContextItem(id="dupe", content="first", tokens=10, priority=10),
        ContextItem(id="dupe", content="second", tokens=10, priority=5),
    ]
    result = pack(items, Budget(maxTokens=50))
    assert len(result.selected) == 2


def test_estimate_tokens_none_input():
    """estimate_tokens(None) returns 0."""
    assert estimate_tokens(None) == 0


def test_estimate_tokens_whitespace_only():
    """Whitespace-only string returns 0 tokens."""
    assert estimate_tokens("   \t  ") == 0


def test_estimate_tokens_newlines_only():
    """Newlines-only string returns 0."""
    assert estimate_tokens("\n\n\n") == 0


def test_estimate_tokens_unicode_emoji():
    """Unicode/emoji text returns > 0."""
    result = estimate_tokens("Hello 🎉🎉🎉 world")
    assert result > 0


def test_diff_one_empty():
    """Diff with empty before and non-empty after returns all added."""
    items = [ContextItem(id="a", content="new", tokens=10)]
    result = diff([], items)
    assert len(result["added"]) == 1
    assert len(result["removed"]) == 0


def test_diff_all_kept():
    """Diff with identical inputs returns all kept."""
    items = [
        ContextItem(id="a", content="hello", tokens=10),
        ContextItem(id="b", content="world", tokens=10),
    ]
    result = diff(items, items)
    assert len(result["kept"]) == 2
    assert len(result["added"]) == 0
    assert len(result["removed"]) == 0
    assert len(result["changed"]) == 0


def test_create_context_item_empty_id():
    """create_context_item with empty id creates the item (validation happens at pack time)."""
    item = create_context_item("", "content")
    assert item.id == ""
    assert item.content == "content"


def test_create_context_item_empty_content():
    """create_context_item with empty content creates the item."""
    item = create_context_item("x", "")
    assert item.id == "x"
    assert item.content == ""


# --- NaN/Infinity validation tests ---


def test_pack_rejects_infinity_priority():
    """pack() rejects items with Infinity priority."""
    items = [ContextItem(id="a", content="test", priority=float("inf"), tokens=10)]
    with pytest.raises(ValidationError, match="non-finite"):
        pack(items, Budget(maxTokens=100))


def test_pack_rejects_nan_priority():
    """pack() rejects items with NaN priority."""
    items = [ContextItem(id="a", content="test", priority=float("nan"), tokens=10)]
    with pytest.raises(ValidationError, match="non-finite"):
        pack(items, Budget(maxTokens=100))


def test_pack_rejects_infinity_tokens():
    """Infinity tokens rejected (Pydantic rejects at model creation for int field)."""
    with pytest.raises(Exception):
        ContextItem(id="a", content="test", tokens=float("inf"))


def test_pack_rejects_nan_recency():
    """pack() rejects items with NaN recency."""
    items = [ContextItem(id="a", content="test", recency=float("nan"), tokens=10)]
    with pytest.raises(ValidationError, match="non-finite"):
        pack(items, Budget(maxTokens=100))


# --- Empty ID validation tests ---


def test_pack_rejects_empty_id():
    """pack() rejects items with empty string id."""
    items = [ContextItem(id="", content="test", tokens=10)]
    with pytest.raises(ValidationError, match="empty id"):
        pack(items, Budget(maxTokens=100))
