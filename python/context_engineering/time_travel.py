"""
Context Time Travel -- git-like branching, forking, and merging of context states.

Provides snapshot, branch, merge, and rewind capabilities for debugging
agent conversations and exploring alternative context configurations.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional

from .core import ContextItem
from .quality import ContextQuality, analyze_context

# ---------------------------------------------------------------------------
# ID generation
# ---------------------------------------------------------------------------

_snapshot_counter = 0


def _generate_snapshot_id() -> str:
    global _snapshot_counter
    _snapshot_counter += 1
    return f"snap_{int(time.time() * 1000)}_{_snapshot_counter}"


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

MergeStrategy = Literal["union", "intersection", "best-quality", "highest-priority", "manual"]

QualityDimension = Literal["density", "diversity", "freshness", "redundancy", "overall"]


@dataclass
class Snapshot:
    id: str
    name: str
    items: List[ContextItem]
    created_at: float
    parent_id: Optional[str]
    branch_name: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    quality: Optional[ContextQuality] = None


@dataclass
class Branch:
    name: str
    head_snapshot_id: str
    created_at: float
    parent_branch: Optional[str]
    fork_point: Optional[str]


@dataclass
class MergeOptions:
    strategy: MergeStrategy = "union"
    resolver: Optional[Callable[[List[ContextItem], List[ContextItem]], List[ContextItem]]] = None
    quality_dimension: QualityDimension = "overall"


@dataclass
class MergeResult:
    items: List[ContextItem]
    strategy: MergeStrategy
    from_branch: str
    into_branch: str
    added: List[ContextItem]
    removed: List[ContextItem]
    conflicts: int


@dataclass
class BranchComparison:
    branch1: str
    branch2: str
    only_in_branch1: List[ContextItem]
    only_in_branch2: List[ContextItem]
    common: List[ContextItem]
    modified: List[Dict[str, str]]
    quality1: Optional[ContextQuality] = None
    quality2: Optional[ContextQuality] = None


@dataclass
class TimelineState:
    branches: List[Branch]
    snapshots: List[Snapshot]
    current_branch: str


@dataclass
class TimelineOptions:
    default_branch: str = "main"
    auto_snapshot: bool = False
    max_snapshots: Optional[int] = None


# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------


def _deep_copy_items(items: List[ContextItem]) -> List[ContextItem]:
    """Deep-copy a list of ContextItems to prevent shared references."""
    return [item.model_copy(deep=True) for item in items]


def create_snapshot(
    name: str,
    items: List[ContextItem],
    branch_name: str,
    parent_id: Optional[str],
    metadata: Optional[Dict[str, Any]] = None,
) -> Snapshot:
    """Create a new snapshot storing a deep copy of the given items."""
    return Snapshot(
        id=_generate_snapshot_id(),
        name=name,
        items=_deep_copy_items(items),
        created_at=time.time() * 1000,
        parent_id=parent_id,
        branch_name=branch_name,
        metadata=metadata or {},
    )


@dataclass
class SnapshotDiff:
    added: List[ContextItem]
    removed: List[ContextItem]
    modified: List[Dict[str, Any]]
    unchanged: List[ContextItem]


def diff_snapshots(a: Snapshot, b: Snapshot) -> SnapshotDiff:
    """Compute an item-level diff between two snapshots.

    Items are matched by ``id``. An item is "modified" when its content
    differs between the two snapshots.
    """
    a_map = {item.id: item for item in a.items}
    b_map = {item.id: item for item in b.items}

    added: List[ContextItem] = []
    removed: List[ContextItem] = []
    modified: List[Dict[str, Any]] = []
    unchanged: List[ContextItem] = []

    for item_id, b_item in b_map.items():
        a_item = a_map.get(item_id)
        if a_item is None:
            added.append(b_item)
        elif a_item.content != b_item.content:
            modified.append({"id": item_id, "before": a_item, "after": b_item})
        else:
            unchanged.append(b_item)

    for item_id, a_item in a_map.items():
        if item_id not in b_map:
            removed.append(a_item)

    return SnapshotDiff(added=added, removed=removed, modified=modified, unchanged=unchanged)


# ---------------------------------------------------------------------------
# Merge strategies
# ---------------------------------------------------------------------------


def _merge_union(ours: List[ContextItem], theirs: List[ContextItem]) -> Dict[str, Any]:
    ours_map = {item.id: item for item in ours}
    theirs_map = {item.id: item for item in theirs}

    result: List[ContextItem] = []
    added: List[ContextItem] = []
    conflicts = 0

    for item in ours:
        their_item = theirs_map.get(item.id)
        if their_item and their_item.content != item.content:
            conflicts += 1
            our_recency = item.recency or 0
            their_recency = their_item.recency or 0
            result.append(their_item if their_recency > our_recency else item)
        else:
            result.append(item)

    for item in theirs:
        if item.id not in ours_map:
            result.append(item)
            added.append(item)

    return {"items": result, "added": added, "removed": [], "conflicts": conflicts}


def _merge_intersection(ours: List[ContextItem], theirs: List[ContextItem]) -> Dict[str, Any]:
    theirs_map = {item.id: item for item in theirs}
    ours_map = {item.id: item for item in ours}

    items: List[ContextItem] = []
    removed: List[ContextItem] = []
    conflicts = 0

    for item in ours:
        their_item = theirs_map.get(item.id)
        if their_item:
            if their_item.content != item.content:
                conflicts += 1
            items.append(item)
        else:
            removed.append(item)

    for item in theirs:
        if item.id not in ours_map:
            removed.append(item)

    return {"items": items, "added": [], "removed": removed, "conflicts": conflicts}


def _merge_best_quality(
    ours: List[ContextItem],
    theirs: List[ContextItem],
    dimension: QualityDimension,
) -> Dict[str, Any]:
    ours_quality = analyze_context(ours)
    theirs_quality = analyze_context(theirs)

    if dimension == "redundancy":
        ours_score = 1 - ours_quality.redundancy
        theirs_score = 1 - theirs_quality.redundancy
    else:
        ours_score = getattr(ours_quality, dimension)
        theirs_score = getattr(theirs_quality, dimension)

    ours_map = {item.id: item for item in ours}
    conflicts = 0
    for item in theirs:
        our_item = ours_map.get(item.id)
        if our_item and our_item.content != item.content:
            conflicts += 1

    if theirs_score > ours_score:
        theirs_map = {item.id: item for item in theirs}
        added = [item for item in theirs if item.id not in ours_map]
        removed = [item for item in ours if item.id not in theirs_map]
        return {"items": list(theirs), "added": added, "removed": removed, "conflicts": conflicts}

    return {"items": list(ours), "added": [], "removed": [], "conflicts": conflicts}


def _merge_highest_priority(ours: List[ContextItem], theirs: List[ContextItem]) -> Dict[str, Any]:
    ours_map = {item.id: item for item in ours}
    theirs_map = {item.id: item for item in theirs}

    result: List[ContextItem] = []
    added: List[ContextItem] = []
    conflicts = 0

    for item in ours:
        their_item = theirs_map.get(item.id)
        if their_item and their_item.content != item.content:
            conflicts += 1
            our_priority = item.priority or 0
            their_priority = their_item.priority or 0
            result.append(their_item if their_priority > our_priority else item)
        else:
            result.append(item)

    for item in theirs:
        if item.id not in ours_map:
            result.append(item)
            added.append(item)

    return {"items": result, "added": added, "removed": [], "conflicts": conflicts}


def _merge_manual(
    ours: List[ContextItem],
    theirs: List[ContextItem],
    resolver: Callable[[List[ContextItem], List[ContextItem]], List[ContextItem]],
) -> Dict[str, Any]:
    ours_map = {item.id: item for item in ours}

    items = resolver(ours, theirs)
    result_map = {item.id: item for item in items}

    added = [item for item in items if item.id not in ours_map]
    removed = [item for item in ours if item.id not in result_map]

    conflicts = 0
    for item in theirs:
        our_item = ours_map.get(item.id)
        if our_item and our_item.content != item.content:
            conflicts += 1

    return {"items": items, "added": added, "removed": removed, "conflicts": conflicts}


def execute_merge(
    ours: List[ContextItem],
    theirs: List[ContextItem],
    from_branch: str,
    into_branch: str,
    options: Optional[MergeOptions] = None,
) -> MergeResult:
    """Execute a merge between two sets of items using the specified strategy."""
    opts = options or MergeOptions()
    strategy = opts.strategy

    if strategy == "union":
        result = _merge_union(ours, theirs)
    elif strategy == "intersection":
        result = _merge_intersection(ours, theirs)
    elif strategy == "best-quality":
        result = _merge_best_quality(ours, theirs, opts.quality_dimension)
    elif strategy == "highest-priority":
        result = _merge_highest_priority(ours, theirs)
    elif strategy == "manual":
        if opts.resolver is None:
            raise ValueError('Manual merge strategy requires a "resolver" function in MergeOptions')
        result = _merge_manual(ours, theirs, opts.resolver)
    else:
        raise ValueError(f"Unknown merge strategy: {strategy}")

    return MergeResult(
        items=result["items"],
        strategy=strategy,
        from_branch=from_branch,
        into_branch=into_branch,
        added=result["added"],
        removed=result["removed"],
        conflicts=result["conflicts"],
    )


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------


class Timeline:
    """Git-like branching, forking, and merging of context states.

    Example::

        tl = create_timeline()
        tl.set_items([item1, item2])
        tl.checkpoint("initial")

        tl.fork("experiment")
        tl.add_items(item3)
        tl.checkpoint("with-item3")

        tl.checkout("main")
        tl.merge("experiment", MergeOptions(strategy="union"))
    """

    def __init__(self, options: Optional[TimelineOptions] = None) -> None:
        opts = options or TimelineOptions()
        self._default_branch = opts.default_branch
        self._auto_snapshot = opts.auto_snapshot
        self._max_snapshots = opts.max_snapshots

        self._snapshots: List[Snapshot] = []
        self._branches: List[Branch] = []
        self._active_branch = self._default_branch
        self._branch_items: Dict[str, List[ContextItem]] = {}

        initial_snap = create_snapshot("init", [], self._default_branch, None)
        self._snapshots.append(initial_snap)

        self._branches.append(
            Branch(
                name=self._default_branch,
                head_snapshot_id=initial_snap.id,
                created_at=time.time() * 1000,
                parent_branch=None,
                fork_point=None,
            )
        )
        self._branch_items[self._default_branch] = []

    def _get_branch(self, name: str) -> Branch:
        for branch in self._branches:
            if branch.name == name:
                return branch
        raise ValueError(f'Branch "{name}" does not exist')

    def _prune_snapshots(self) -> None:
        if self._max_snapshots is None or len(self._snapshots) <= self._max_snapshots:
            return

        protected_ids = set()
        for branch in self._branches:
            protected_ids.add(branch.head_snapshot_id)
            if branch.fork_point:
                protected_ids.add(branch.fork_point)

        prunable = [s for s in self._snapshots if s.id not in protected_ids]
        to_remove = len(prunable) - (self._max_snapshots - (len(self._snapshots) - len(prunable)))
        if to_remove > 0:
            prunable.sort(key=lambda s: s.created_at)
            remove_ids = {s.id for s in prunable[:to_remove]}
            self._snapshots = [s for s in self._snapshots if s.id not in remove_ids]

    def _do_auto_snapshot(self, action: str) -> None:
        if not self._auto_snapshot:
            return
        items = self._branch_items.get(self._active_branch, [])
        branch = self._get_branch(self._active_branch)
        snap = create_snapshot(
            f"auto:{action}", items, self._active_branch, branch.head_snapshot_id
        )
        self._snapshots.append(snap)
        branch.head_snapshot_id = snap.id
        self._prune_snapshots()

    # -- Item operations --

    def get_items(self) -> List[ContextItem]:
        """Get all items on the current branch."""
        return _deep_copy_items(self._branch_items.get(self._active_branch, []))

    def set_items(self, items: List[ContextItem]) -> None:
        """Set items on the current branch."""
        self._branch_items[self._active_branch] = _deep_copy_items(items)
        self._do_auto_snapshot("set_items")

    def add_items(self, *items: ContextItem) -> None:
        """Add items to the current branch."""
        current = self._branch_items.get(self._active_branch, [])
        existing_ids = {i.id for i in current}
        new_items = [i for i in items if i.id not in existing_ids]
        self._branch_items[self._active_branch] = current + _deep_copy_items(new_items)
        self._do_auto_snapshot("add_items")

    def remove_items(self, *ids: str) -> None:
        """Remove items by ID."""
        remove_set = set(ids)
        current = self._branch_items.get(self._active_branch, [])
        self._branch_items[self._active_branch] = [i for i in current if i.id not in remove_set]
        self._do_auto_snapshot("remove_items")

    # -- Checkpoints --

    def checkpoint(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> Snapshot:
        """Create a named checkpoint on the current branch."""
        items = self._branch_items.get(self._active_branch, [])
        branch = self._get_branch(self._active_branch)
        snap = create_snapshot(name, items, self._active_branch, branch.head_snapshot_id, metadata)
        self._snapshots.append(snap)
        branch.head_snapshot_id = snap.id
        self._prune_snapshots()
        return snap

    def rewind(self, name_or_id: str) -> None:
        """Rewind the current branch to a named checkpoint or snapshot ID."""
        snap = self._find_snapshot(name_or_id, self._active_branch)
        if snap is None:
            raise ValueError(f'Snapshot "{name_or_id}" not found on branch "{self._active_branch}"')
        self._branch_items[self._active_branch] = _deep_copy_items(snap.items)
        branch = self._get_branch(self._active_branch)
        branch.head_snapshot_id = snap.id

    # -- Branching --

    def fork(self, branch_name: str, from_snapshot: Optional[str] = None) -> Branch:
        """Create a new branch from the current state (or a specific snapshot)."""
        if any(b.name == branch_name for b in self._branches):
            raise ValueError(f'Branch "{branch_name}" already exists')

        if from_snapshot:
            snap = self._find_snapshot_global(from_snapshot)
            if snap is None:
                raise ValueError(f'Snapshot "{from_snapshot}" not found')
            source_items = snap.items
            fork_point_id = snap.id
        else:
            source_items = self._branch_items.get(self._active_branch, [])
            fork_point_id = self._get_branch(self._active_branch).head_snapshot_id

        snap = create_snapshot(f"fork:{branch_name}", source_items, branch_name, fork_point_id)
        self._snapshots.append(snap)

        new_branch = Branch(
            name=branch_name,
            head_snapshot_id=snap.id,
            created_at=time.time() * 1000,
            parent_branch=self._active_branch,
            fork_point=fork_point_id,
        )
        self._branches.append(new_branch)
        self._branch_items[branch_name] = _deep_copy_items(source_items)
        self._active_branch = branch_name
        self._prune_snapshots()
        return new_branch

    def checkout(self, branch_name: str) -> None:
        """Switch to a different branch."""
        self._get_branch(branch_name)  # validates existence
        self._active_branch = branch_name

    def current_branch(self) -> str:
        """Get current branch name."""
        return self._active_branch

    def list_branches(self) -> List[Branch]:
        """List all branches."""
        return [
            Branch(
                name=b.name,
                head_snapshot_id=b.head_snapshot_id,
                created_at=b.created_at,
                parent_branch=b.parent_branch,
                fork_point=b.fork_point,
            )
            for b in self._branches
        ]

    # -- Comparison & Merge --

    def compare(self, branch1: str, branch2: str) -> BranchComparison:
        """Compare two branches."""
        self._get_branch(branch1)
        self._get_branch(branch2)

        items1 = self._branch_items.get(branch1, [])
        items2 = self._branch_items.get(branch2, [])

        map1 = {i.id: i for i in items1}
        map2 = {i.id: i for i in items2}

        only_in_1: List[ContextItem] = []
        only_in_2: List[ContextItem] = []
        common: List[ContextItem] = []
        modified: List[Dict[str, str]] = []

        for item_id, item in map1.items():
            other = map2.get(item_id)
            if other is None:
                only_in_1.append(item)
            elif item.content != other.content:
                modified.append(
                    {
                        "id": item_id,
                        "branch1_content": item.content,
                        "branch2_content": other.content,
                    }
                )
            else:
                common.append(item)

        for item_id, item in map2.items():
            if item_id not in map1:
                only_in_2.append(item)

        return BranchComparison(
            branch1=branch1,
            branch2=branch2,
            only_in_branch1=only_in_1,
            only_in_branch2=only_in_2,
            common=common,
            modified=modified,
            quality1=analyze_context(items1),
            quality2=analyze_context(items2),
        )

    def merge(self, from_branch: str, options: Optional[MergeOptions] = None) -> MergeResult:
        """Merge another branch into the current branch."""
        self._get_branch(from_branch)

        ours = self._branch_items.get(self._active_branch, [])
        theirs = self._branch_items.get(from_branch, [])

        result = execute_merge(ours, theirs, from_branch, self._active_branch, options)

        self._branch_items[self._active_branch] = _deep_copy_items(result.items)

        branch = self._get_branch(self._active_branch)
        snap = create_snapshot(
            f"merge:{from_branch}",
            result.items,
            self._active_branch,
            branch.head_snapshot_id,
        )
        self._snapshots.append(snap)
        branch.head_snapshot_id = snap.id
        self._prune_snapshots()

        return result

    # -- History --

    def history(self) -> List[Snapshot]:
        """Get the full history of the current branch (all snapshots)."""
        return sorted(
            [s for s in self._snapshots if s.branch_name == self._active_branch],
            key=lambda s: s.created_at,
        )

    def get_snapshot(self, name_or_id: str) -> Optional[Snapshot]:
        """Get a specific snapshot by name or ID."""
        return self._find_snapshot_global(name_or_id)

    # -- Persistence --

    def export_state(self) -> TimelineState:
        """Export the entire timeline state for persistence."""
        return TimelineState(
            branches=[
                Branch(
                    name=b.name,
                    head_snapshot_id=b.head_snapshot_id,
                    created_at=b.created_at,
                    parent_branch=b.parent_branch,
                    fork_point=b.fork_point,
                )
                for b in self._branches
            ],
            snapshots=[
                Snapshot(
                    id=s.id,
                    name=s.name,
                    items=_deep_copy_items(s.items),
                    created_at=s.created_at,
                    parent_id=s.parent_id,
                    branch_name=s.branch_name,
                    metadata=dict(s.metadata) if s.metadata else {},
                    quality=s.quality,
                )
                for s in self._snapshots
            ],
            current_branch=self._active_branch,
        )

    def import_state(self, state: TimelineState) -> None:
        """Import a previously exported timeline state."""
        self._branches = [
            Branch(
                name=b.name,
                head_snapshot_id=b.head_snapshot_id,
                created_at=b.created_at,
                parent_branch=b.parent_branch,
                fork_point=b.fork_point,
            )
            for b in state.branches
        ]
        self._snapshots = [
            Snapshot(
                id=s.id,
                name=s.name,
                items=_deep_copy_items(s.items),
                created_at=s.created_at,
                parent_id=s.parent_id,
                branch_name=s.branch_name,
                metadata=dict(s.metadata) if s.metadata else {},
                quality=s.quality,
            )
            for s in state.snapshots
        ]
        self._active_branch = state.current_branch

        self._branch_items.clear()
        for branch in self._branches:
            head_snap = next(
                (s for s in self._snapshots if s.id == branch.head_snapshot_id),
                None,
            )
            self._branch_items[branch.name] = _deep_copy_items(head_snap.items) if head_snap else []

    # -- Internal helpers --

    def _find_snapshot(self, name_or_id: str, branch_name: str) -> Optional[Snapshot]:
        return next(
            (
                s
                for s in self._snapshots
                if s.branch_name == branch_name and (s.id == name_or_id or s.name == name_or_id)
            ),
            None,
        )

    def _find_snapshot_global(self, name_or_id: str) -> Optional[Snapshot]:
        return next(
            (s for s in self._snapshots if s.id == name_or_id or s.name == name_or_id),
            None,
        )


def create_timeline(options: Optional[TimelineOptions] = None) -> Timeline:
    """Create a new Timeline for git-like branching of context states.

    Args:
        options: Configuration for the timeline (default branch, auto-snapshot, etc).

    Returns:
        A Timeline instance.
    """
    return Timeline(options)
