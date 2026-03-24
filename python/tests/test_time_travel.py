"""Tests for the Context Time Travel module."""

import pytest

from context_engineering.core import ContextItem
from context_engineering.time_travel import (
    MergeOptions,
    TimelineOptions,
    create_snapshot,
    create_timeline,
    diff_snapshots,
    execute_merge,
)


def make_item(id: str, content: str, **kwargs) -> ContextItem:
    return ContextItem(id=id, content=content, **kwargs)


# ---------------------------------------------------------------------------
# Snapshot tests
# ---------------------------------------------------------------------------


class TestCreateSnapshot:
    def test_creates_snapshot_with_auto_id_and_timestamp(self):
        items = [make_item("a", "hello")]
        snap = create_snapshot("v1", items, "main", None)

        assert snap.id.startswith("snap_")
        assert snap.name == "v1"
        assert snap.branch_name == "main"
        assert snap.parent_id is None
        assert snap.created_at > 0
        assert len(snap.items) == 1

    def test_stores_deep_copy(self):
        items = [make_item("a", "original", metadata={"key": "val"})]
        snap = create_snapshot("v1", items, "main", None)

        items[0].content = "mutated"
        items[0].metadata["key"] = "changed"

        assert snap.items[0].content == "original"
        assert snap.items[0].metadata["key"] == "val"

    def test_unique_ids(self):
        s1 = create_snapshot("a", [], "main", None)
        s2 = create_snapshot("b", [], "main", None)
        assert s1.id != s2.id


class TestDiffSnapshots:
    def test_detects_added_items(self):
        a = create_snapshot("a", [make_item("1", "one")], "main", None)
        b = create_snapshot("b", [make_item("1", "one"), make_item("2", "two")], "main", None)
        d = diff_snapshots(a, b)
        assert len(d.added) == 1
        assert d.added[0].id == "2"

    def test_detects_removed_items(self):
        a = create_snapshot("a", [make_item("1", "one"), make_item("2", "two")], "main", None)
        b = create_snapshot("b", [make_item("1", "one")], "main", None)
        d = diff_snapshots(a, b)
        assert len(d.removed) == 1
        assert d.removed[0].id == "2"

    def test_detects_modified_items(self):
        a = create_snapshot("a", [make_item("1", "old")], "main", None)
        b = create_snapshot("b", [make_item("1", "new")], "main", None)
        d = diff_snapshots(a, b)
        assert len(d.modified) == 1
        assert d.modified[0]["id"] == "1"


# ---------------------------------------------------------------------------
# Merge tests
# ---------------------------------------------------------------------------


class TestExecuteMerge:
    def test_union_combines_all_items(self):
        ours = [make_item("a", "alpha")]
        theirs = [make_item("b", "beta")]
        result = execute_merge(ours, theirs, "feature", "main")

        assert len(result.items) == 2
        assert result.strategy == "union"

    def test_union_resolves_conflicts_by_recency(self):
        ours = [make_item("a", "old", recency=3)]
        theirs = [make_item("a", "new", recency=8)]
        result = execute_merge(ours, theirs, "feature", "main", MergeOptions(strategy="union"))

        assert result.items[0].content == "new"
        assert result.conflicts == 1

    def test_intersection_keeps_only_common(self):
        ours = [make_item("a", "alpha"), make_item("b", "beta")]
        theirs = [make_item("b", "beta"), make_item("c", "gamma")]
        result = execute_merge(
            ours,
            theirs,
            "feature",
            "main",
            MergeOptions(strategy="intersection"),
        )

        assert len(result.items) == 1
        assert result.items[0].id == "b"

    def test_highest_priority_picks_higher(self):
        ours = [make_item("a", "low", priority=2)]
        theirs = [make_item("a", "high", priority=9)]
        result = execute_merge(
            ours,
            theirs,
            "feature",
            "main",
            MergeOptions(strategy="highest-priority"),
        )

        assert result.items[0].content == "high"

    def test_manual_delegates_to_resolver(self):
        ours = [make_item("a", "alpha")]
        theirs = [make_item("b", "beta")]
        result = execute_merge(
            ours,
            theirs,
            "feature",
            "main",
            MergeOptions(strategy="manual", resolver=lambda o, t: list(t)),
        )

        assert len(result.items) == 1
        assert result.items[0].id == "b"

    def test_manual_without_resolver_raises(self):
        with pytest.raises(ValueError, match="resolver"):
            execute_merge([], [], "f", "m", MergeOptions(strategy="manual"))


# ---------------------------------------------------------------------------
# Timeline tests
# ---------------------------------------------------------------------------


class TestTimeline:
    def test_starts_on_default_branch(self):
        tl = create_timeline()
        assert tl.current_branch() == "main"
        assert tl.get_items() == []

    def test_custom_default_branch(self):
        tl = create_timeline(TimelineOptions(default_branch="trunk"))
        assert tl.current_branch() == "trunk"

    def test_set_and_get_items(self):
        tl = create_timeline()
        tl.set_items([make_item("a", "alpha")])
        items = tl.get_items()
        assert len(items) == 1
        assert items[0].content == "alpha"

    def test_add_items_deduplicates(self):
        tl = create_timeline()
        tl.set_items([make_item("a", "alpha")])
        tl.add_items(make_item("b", "beta"), make_item("a", "dup"))
        assert len(tl.get_items()) == 2

    def test_remove_items(self):
        tl = create_timeline()
        tl.set_items([make_item("a", "alpha"), make_item("b", "beta")])
        tl.remove_items("a")
        items = tl.get_items()
        assert len(items) == 1
        assert items[0].id == "b"

    def test_checkpoint_and_rewind(self):
        tl = create_timeline()
        tl.set_items([make_item("a", "v1")])
        tl.checkpoint("version-1")

        tl.set_items([make_item("a", "v2"), make_item("b", "new")])
        assert len(tl.get_items()) == 2

        tl.rewind("version-1")
        items = tl.get_items()
        assert len(items) == 1
        assert items[0].content == "v1"

    def test_rewind_nonexistent_raises(self):
        tl = create_timeline()
        with pytest.raises(ValueError, match="not found"):
            tl.rewind("nonexistent")

    def test_fork_creates_independent_branch(self):
        tl = create_timeline()
        tl.set_items([make_item("a", "shared")])
        tl.fork("feature")

        tl.add_items(make_item("b", "feature-only"))
        assert len(tl.get_items()) == 2

        tl.checkout("main")
        assert len(tl.get_items()) == 1

    def test_changes_on_one_branch_do_not_affect_another(self):
        tl = create_timeline()
        tl.set_items([make_item("a", "main-item")])
        tl.fork("branch-a")
        tl.set_items([make_item("x", "branch-a-item")])

        tl.checkout("main")
        assert tl.get_items()[0].id == "a"

    def test_fork_from_specific_snapshot(self):
        tl = create_timeline()
        tl.set_items([make_item("a", "v1")])
        snap = tl.checkpoint("snap1")

        tl.set_items([make_item("a", "v2"), make_item("b", "new")])
        tl.fork("from-snap1", snap.id)

        assert len(tl.get_items()) == 1
        assert tl.get_items()[0].content == "v1"

    def test_fork_duplicate_name_raises(self):
        tl = create_timeline()
        tl.fork("feature")
        with pytest.raises(ValueError, match="already exists"):
            tl.fork("feature")

    def test_checkout_nonexistent_raises(self):
        tl = create_timeline()
        with pytest.raises(ValueError, match="does not exist"):
            tl.checkout("nope")

    def test_list_branches(self):
        tl = create_timeline()
        tl.fork("a")
        tl.checkout("main")
        tl.fork("b")
        names = sorted(b.name for b in tl.list_branches())
        assert names == ["a", "b", "main"]

    def test_compare_shows_differences(self):
        tl = create_timeline()
        tl.set_items([make_item("a", "shared"), make_item("b", "main-only")])
        tl.fork("feature")
        tl.set_items([make_item("a", "modified"), make_item("c", "feature-only")])

        cmp = tl.compare("main", "feature")
        assert len(cmp.only_in_branch1) == 1
        assert len(cmp.only_in_branch2) == 1
        assert len(cmp.modified) == 1

    def test_merge_into_current_branch(self):
        tl = create_timeline()
        tl.set_items([make_item("a", "main-item")])
        tl.fork("feature")
        tl.add_items(make_item("b", "feature-item"))
        tl.checkout("main")

        result = tl.merge("feature", MergeOptions(strategy="union"))
        assert len(result.items) == 2
        assert len(tl.get_items()) == 2

    def test_history_returns_chronological_order(self):
        tl = create_timeline()
        tl.checkpoint("first")
        tl.checkpoint("second")
        hist = tl.history()
        for i in range(1, len(hist)):
            assert hist[i].created_at >= hist[i - 1].created_at

    def test_get_snapshot_by_name(self):
        tl = create_timeline()
        tl.checkpoint("findme")
        snap = tl.get_snapshot("findme")
        assert snap is not None
        assert snap.name == "findme"

    def test_get_snapshot_returns_none_for_missing(self):
        tl = create_timeline()
        assert tl.get_snapshot("nonexistent") is None

    def test_export_import_roundtrip(self):
        tl = create_timeline()
        tl.set_items([make_item("a", "alpha"), make_item("b", "beta")])
        tl.checkpoint("v1")
        tl.fork("feature")
        tl.add_items(make_item("c", "gamma"))
        tl.checkpoint("feature-v1")

        state = tl.export_state()

        tl2 = create_timeline()
        tl2.import_state(state)

        assert tl2.current_branch() == "feature"
        assert len(tl2.get_items()) == 3
        tl2.checkout("main")
        assert len(tl2.get_items()) == 2

    def test_auto_snapshot_on_set_items(self):
        tl = create_timeline(TimelineOptions(auto_snapshot=True))
        before = len(tl.history())
        tl.set_items([make_item("a", "alpha")])
        after = len(tl.history())
        assert after > before

    def test_max_snapshots_pruning(self):
        tl = create_timeline(TimelineOptions(max_snapshots=5))
        for i in range(10):
            tl.set_items([make_item("a", f"version-{i}")])
            tl.checkpoint(f"v{i}")
        hist = tl.history()
        assert len(hist) <= 5
