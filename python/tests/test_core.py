from context_engineering.core import Budget, ContextItem, pack, diff


def test_pack_selects_high_priority():
    items = [
        ContextItem(id="a", content="High", priority=10, tokens=50),
        ContextItem(id="b", content="Low", priority=1, tokens=60),
        ContextItem(id="c", content="Medium", priority=5, tokens=30),
    ]
    result = pack(items, Budget(maxTokens=80))
    selected_ids = {item.id for item in result.selected}
    assert "a" in selected_ids
    assert "c" in selected_ids
    assert "b" not in selected_ids


def test_diff_detects_changes():
    before = [ContextItem(id="a", content="Alpha", tokens=10)]
    after = [ContextItem(id="b", content="Beta", tokens=10)]
    result = diff(before, after)
    assert len(result["added"]) == 1
    assert len(result["removed"]) == 1
