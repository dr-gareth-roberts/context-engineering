import pytest
from context_engineering.core import pack, diff, estimate_tokens, Budget, ContextItem


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
    with pytest.raises((ValueError, Exception)):
        pack([], Budget(maxTokens=-1))


def test_pack_rejects_zero_budget():
    with pytest.raises((ValueError, Exception)):
        pack([], Budget(maxTokens=0))


def test_pack_rejects_reserve_exceeding_max():
    items = [ContextItem(id="a", content="test", tokens=10)]
    with pytest.raises((ValueError, Exception)):
        pack(items, Budget(maxTokens=100, reserveTokens=100))


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
