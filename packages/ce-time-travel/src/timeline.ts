import type { ContextItem } from "@context-engineering/core";
import { analyzeContext } from "@context-engineering/core";
import type {
  Branch,
  BranchComparison,
  MergeOptions,
  MergeResult,
  Snapshot,
  Timeline,
  TimelineOptions,
  TimelineState,
} from "./types.js";
import { createSnapshot, deepCopyItems } from "./snapshot.js";
import { executeMerge } from "./merge-strategies.js";

/**
 * Create a new Timeline for git-like branching, forking, and merging
 * of context states.
 *
 * @param options - Configuration for the timeline
 * @returns A Timeline instance
 *
 * @example
 * ```ts
 * const tl = createTimeline();
 * tl.setItems([item1, item2]);
 * tl.checkpoint("initial");
 *
 * tl.fork("experiment");
 * tl.addItems(item3);
 * tl.checkpoint("with-item3");
 *
 * tl.checkout("main");
 * tl.merge("experiment", { strategy: "union" });
 * ```
 */
export function createTimeline(options?: TimelineOptions): Timeline {
  const defaultBranch = options?.defaultBranch ?? "main";
  const autoSnapshot = options?.autoSnapshot ?? false;
  const maxSnapshots = options?.maxSnapshots;

  let snapshots: Snapshot[] = [];
  let branches: Branch[] = [];
  let activeBranch = defaultBranch;

  // Items per branch, keyed by branch name
  const branchItems = new Map<string, ContextItem[]>();

  // Initialize the default branch
  const initialSnapshot = createSnapshot("init", [], defaultBranch, null);
  snapshots.push(initialSnapshot);

  branches.push({
    name: defaultBranch,
    headSnapshotId: initialSnapshot.id,
    createdAt: Date.now(),
    parentBranch: null,
    forkPoint: null,
  });
  branchItems.set(defaultBranch, []);

  function getBranch(name: string): Branch {
    const branch = branches.find(b => b.name === name);
    if (!branch) {
      throw new Error(`Branch "${name}" does not exist`);
    }
    return branch;
  }

  function pruneSnapshots(): void {
    if (maxSnapshots && snapshots.length > maxSnapshots) {
      // Keep the newest maxSnapshots, prune oldest first.
      // But never prune a snapshot that is a branch head or fork point.
      const protectedIds = new Set<string>();
      for (const branch of branches) {
        protectedIds.add(branch.headSnapshotId);
        if (branch.forkPoint) {
          protectedIds.add(branch.forkPoint);
        }
      }

      const prunable = snapshots.filter(s => !protectedIds.has(s.id));
      const toRemove =
        prunable.length - (maxSnapshots - (snapshots.length - prunable.length));
      if (toRemove > 0) {
        // Sort prunable by createdAt ascending (oldest first)
        prunable.sort((a, b) => a.createdAt - b.createdAt);
        const removeIds = new Set(prunable.slice(0, toRemove).map(s => s.id));
        snapshots = snapshots.filter(s => !removeIds.has(s.id));
      }
    }
  }

  function doAutoSnapshot(action: string): void {
    if (autoSnapshot) {
      const items = branchItems.get(activeBranch) ?? [];
      const branch = getBranch(activeBranch);
      const snap = createSnapshot(
        `auto:${action}`,
        items,
        activeBranch,
        branch.headSnapshotId
      );
      snapshots.push(snap);
      branch.headSnapshotId = snap.id;
      pruneSnapshots();
    }
  }

  function getItems(): ContextItem[] {
    return deepCopyItems(branchItems.get(activeBranch) ?? []);
  }

  function setItems(items: ContextItem[]): void {
    branchItems.set(activeBranch, deepCopyItems(items));
    doAutoSnapshot("setItems");
  }

  function addItems(...items: ContextItem[]): void {
    const current = branchItems.get(activeBranch) ?? [];
    const existingIds = new Set(current.map(i => i.id));
    const newItems = items.filter(i => !existingIds.has(i.id));
    branchItems.set(activeBranch, [...current, ...deepCopyItems(newItems)]);
    doAutoSnapshot("addItems");
  }

  function removeItems(...ids: string[]): void {
    const removeSet = new Set(ids);
    const current = branchItems.get(activeBranch) ?? [];
    branchItems.set(
      activeBranch,
      current.filter(i => !removeSet.has(i.id))
    );
    doAutoSnapshot("removeItems");
  }

  function checkpoint(
    name: string,
    metadata?: Record<string, unknown>
  ): Snapshot {
    const items = branchItems.get(activeBranch) ?? [];
    const branch = getBranch(activeBranch);
    const snap = createSnapshot(
      name,
      items,
      activeBranch,
      branch.headSnapshotId,
      metadata
    );
    snapshots.push(snap);
    branch.headSnapshotId = snap.id;
    pruneSnapshots();
    return snap;
  }

  function rewind(nameOrId: string): void {
    const snap = findSnapshot(nameOrId, activeBranch);
    if (!snap) {
      throw new Error(
        `Snapshot "${nameOrId}" not found on branch "${activeBranch}"`
      );
    }
    branchItems.set(activeBranch, deepCopyItems(snap.items));
    const branch = getBranch(activeBranch);
    branch.headSnapshotId = snap.id;
  }

  function fork(branchName: string, fromSnapshot?: string): Branch {
    if (branches.some(b => b.name === branchName)) {
      throw new Error(`Branch "${branchName}" already exists`);
    }

    let sourceItems: ContextItem[];
    let forkPointId: string;

    if (fromSnapshot) {
      // Fork from a specific snapshot (search across all branches)
      const snap = findSnapshotGlobal(fromSnapshot);
      if (!snap) {
        throw new Error(`Snapshot "${fromSnapshot}" not found`);
      }
      sourceItems = snap.items;
      forkPointId = snap.id;
    } else {
      // Fork from current branch head
      sourceItems = branchItems.get(activeBranch) ?? [];
      forkPointId = getBranch(activeBranch).headSnapshotId;
    }

    const snap = createSnapshot(
      `fork:${branchName}`,
      sourceItems,
      branchName,
      forkPointId
    );
    snapshots.push(snap);

    const newBranch: Branch = {
      name: branchName,
      headSnapshotId: snap.id,
      createdAt: Date.now(),
      parentBranch: activeBranch,
      forkPoint: forkPointId,
    };
    branches.push(newBranch);
    branchItems.set(branchName, deepCopyItems(sourceItems));

    // Switch to the new branch
    activeBranch = branchName;

    pruneSnapshots();
    return newBranch;
  }

  function checkout(branchName: string): void {
    getBranch(branchName); // Throws if branch doesn't exist
    activeBranch = branchName;
  }

  function currentBranch(): string {
    return activeBranch;
  }

  function listBranches(): Branch[] {
    return branches.map(b => ({ ...b }));
  }

  function compare(branch1: string, branch2: string): BranchComparison {
    getBranch(branch1);
    getBranch(branch2);

    const items1 = branchItems.get(branch1) ?? [];
    const items2 = branchItems.get(branch2) ?? [];

    const map1 = new Map(items1.map(i => [i.id, i]));
    const map2 = new Map(items2.map(i => [i.id, i]));

    const onlyInBranch1: ContextItem[] = [];
    const onlyInBranch2: ContextItem[] = [];
    const common: ContextItem[] = [];
    const modified: Array<{
      id: string;
      branch1Content: string;
      branch2Content: string;
    }> = [];

    for (const [id, item] of map1) {
      const other = map2.get(id);
      if (!other) {
        onlyInBranch1.push(item);
      } else if (item.content !== other.content) {
        modified.push({
          id,
          branch1Content: item.content,
          branch2Content: other.content,
        });
      } else {
        common.push(item);
      }
    }

    for (const [id, item] of map2) {
      if (!map1.has(id)) {
        onlyInBranch2.push(item);
      }
    }

    const quality1 = analyzeContext(items1);
    const quality2 = analyzeContext(items2);

    return {
      branch1,
      branch2,
      onlyInBranch1,
      onlyInBranch2,
      common,
      modified,
      quality1,
      quality2,
    };
  }

  function merge(fromBranch: string, mergeOptions?: MergeOptions): MergeResult {
    getBranch(fromBranch);

    const ours = branchItems.get(activeBranch) ?? [];
    const theirs = branchItems.get(fromBranch) ?? [];

    const result = executeMerge(
      ours,
      theirs,
      fromBranch,
      activeBranch,
      mergeOptions
    );

    // Apply the merged items to the current branch
    branchItems.set(activeBranch, deepCopyItems(result.items));

    // Create a merge snapshot
    const branch = getBranch(activeBranch);
    const snap = createSnapshot(
      `merge:${fromBranch}`,
      result.items,
      activeBranch,
      branch.headSnapshotId
    );
    snapshots.push(snap);
    branch.headSnapshotId = snap.id;
    pruneSnapshots();

    return result;
  }

  function history(): Snapshot[] {
    return snapshots
      .filter(s => s.branchName === activeBranch)
      .sort((a, b) => a.createdAt - b.createdAt);
  }

  function findSnapshot(nameOrId: string, branchName: string): Snapshot | null {
    return (
      snapshots.find(
        s =>
          s.branchName === branchName &&
          (s.id === nameOrId || s.name === nameOrId)
      ) ?? null
    );
  }

  function findSnapshotGlobal(nameOrId: string): Snapshot | null {
    return (
      snapshots.find(s => s.id === nameOrId || s.name === nameOrId) ?? null
    );
  }

  function getSnapshotFn(nameOrId: string): Snapshot | null {
    return findSnapshotGlobal(nameOrId);
  }

  function exportState(): TimelineState {
    return {
      branches: branches.map(b => ({ ...b })),
      snapshots: snapshots.map(s => ({
        ...s,
        items: deepCopyItems(s.items),
        metadata: s.metadata ? { ...s.metadata } : undefined,
      })),
      currentBranch: activeBranch,
    };
  }

  function importState(state: TimelineState): void {
    branches = state.branches.map(b => ({ ...b }));
    snapshots = state.snapshots.map(s => ({
      ...s,
      items: deepCopyItems(s.items),
      metadata: s.metadata ? { ...s.metadata } : undefined,
    }));
    activeBranch = state.currentBranch;

    // Rebuild branchItems from the head snapshot of each branch
    branchItems.clear();
    for (const branch of branches) {
      const headSnap = snapshots.find(s => s.id === branch.headSnapshotId);
      branchItems.set(
        branch.name,
        headSnap ? deepCopyItems(headSnap.items) : []
      );
    }
  }

  return {
    getItems,
    setItems,
    addItems,
    removeItems,
    checkpoint,
    rewind,
    fork,
    checkout,
    currentBranch,
    listBranches,
    compare,
    merge,
    history,
    getSnapshot: getSnapshotFn,
    exportState,
    importState,
  };
}
