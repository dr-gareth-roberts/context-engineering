import type { ContextItem } from "@context-engineering/core";
import type { Snapshot } from "./types.js";

let snapshotCounter = 0;

/**
 * Generate a unique snapshot ID using an incrementing counter and timestamp.
 */
function generateSnapshotId(): string {
  snapshotCounter++;
  return `snap_${Date.now()}_${snapshotCounter}`;
}

/**
 * Deep-copy an array of ContextItems to prevent shared references.
 */
export function deepCopyItems(items: ContextItem[]): ContextItem[] {
  return items.map(item => ({
    ...item,
    metadata: item.metadata ? { ...item.metadata } : undefined,
    compressions: item.compressions
      ? item.compressions.map(c => ({ ...c }))
      : undefined,
    embedding: item.embedding ? [...item.embedding] : undefined,
    links: item.links ? [...item.links] : undefined,
    dependsOn: item.dependsOn ? [...item.dependsOn] : undefined,
  }));
}

/**
 * Create a new snapshot of the given items.
 *
 * Stores a deep copy so mutations to the original items do not affect
 * the snapshot.
 */
export function createSnapshot(
  name: string,
  items: ContextItem[],
  branchName: string,
  parentId: string | null,
  metadata?: Record<string, unknown>
): Snapshot {
  return {
    id: generateSnapshotId(),
    name,
    items: deepCopyItems(items),
    createdAt: Date.now(),
    parentId,
    branchName,
    metadata,
  };
}

export interface SnapshotDiff {
  added: ContextItem[];
  removed: ContextItem[];
  modified: Array<{
    id: string;
    before: ContextItem;
    after: ContextItem;
  }>;
  unchanged: ContextItem[];
}

/**
 * Compute an item-level diff between two snapshots.
 *
 * Items are matched by `id`. An item is "modified" when its content
 * differs between the two snapshots.
 */
export function diffSnapshots(a: Snapshot, b: Snapshot): SnapshotDiff {
  const aMap = new Map(a.items.map(item => [item.id, item]));
  const bMap = new Map(b.items.map(item => [item.id, item]));

  const added: ContextItem[] = [];
  const removed: ContextItem[] = [];
  const modified: Array<{
    id: string;
    before: ContextItem;
    after: ContextItem;
  }> = [];
  const unchanged: ContextItem[] = [];

  for (const [id, bItem] of bMap) {
    const aItem = aMap.get(id);
    if (!aItem) {
      added.push(bItem);
    } else if (aItem.content !== bItem.content) {
      modified.push({ id, before: aItem, after: bItem });
    } else {
      unchanged.push(bItem);
    }
  }

  for (const [id, aItem] of aMap) {
    if (!bMap.has(id)) {
      removed.push(aItem);
    }
  }

  return { added, removed, modified, unchanged };
}
