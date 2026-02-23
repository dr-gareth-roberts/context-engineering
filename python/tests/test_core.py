import pytest
from context_engineering.core import pack, diff, estimate_tokens, Budget, ContextItem, create_context_item
from context_engineering.errors import (
    ContextEngineeringError,
    ValidationError,
    BudgetExceededError,
    EstimationError,
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
    assert err.details[0]["path"] == "budget"


def test_estimation_error_from_cost():
    """estimate_cost raises EstimationError for unknown models."""
    from context_engineering.cost import estimate_cost
    from context_engineering.cache_topology import CacheAwarePack, CacheConfig

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
