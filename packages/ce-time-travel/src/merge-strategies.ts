import type { ContextItem } from "@context-engineering/core";
import { analyzeContext } from "@context-engineering/core";
import type { MergeOptions, MergeResult } from "./types.js";

/**
 * Union merge: keep all items from both branches.
 * When the same ID exists in both, keep the version with higher recency.
 */
function mergeUnion(
  ours: ContextItem[],
  theirs: ContextItem[]
): {
  items: ContextItem[];
  added: ContextItem[];
  removed: ContextItem[];
  conflicts: number;
} {
  const oursMap = new Map(ours.map(item => [item.id, item]));
  const theirsMap = new Map(theirs.map(item => [item.id, item]));

  const result: ContextItem[] = [];
  const added: ContextItem[] = [];
  let conflicts = 0;

  // Start with all of ours
  for (const item of ours) {
    const theirItem = theirsMap.get(item.id);
    if (theirItem && theirItem.content !== item.content) {
      conflicts++;
      // Keep the one with higher recency
      const ourRecency = item.recency ?? 0;
      const theirRecency = theirItem.recency ?? 0;
      result.push(theirRecency > ourRecency ? theirItem : item);
    } else {
      result.push(item);
    }
  }

  // Add items only in theirs
  for (const item of theirs) {
    if (!oursMap.has(item.id)) {
      result.push(item);
      added.push(item);
    }
  }

  return { items: result, added, removed: [], conflicts };
}

/**
 * Intersection merge: keep only items that exist in both branches (by ID).
 */
function mergeIntersection(
  ours: ContextItem[],
  theirs: ContextItem[]
): {
  items: ContextItem[];
  added: ContextItem[];
  removed: ContextItem[];
  conflicts: number;
} {
  const theirsMap = new Map(theirs.map(item => [item.id, item]));

  const items: ContextItem[] = [];
  const removed: ContextItem[] = [];
  let conflicts = 0;

  for (const item of ours) {
    const theirItem = theirsMap.get(item.id);
    if (theirItem) {
      if (theirItem.content !== item.content) {
        conflicts++;
      }
      // Keep ours for intersection
      items.push(item);
    } else {
      removed.push(item);
    }
  }

  // Also remove items only in theirs (they are not in intersection)
  const oursMap = new Map(ours.map(item => [item.id, item]));
  for (const item of theirs) {
    if (!oursMap.has(item.id)) {
      removed.push(item);
    }
  }

  return { items, added: [], removed, conflicts };
}

/**
 * Best-quality merge: analyze both branches' items and keep
 * the set with the better quality score on the chosen dimension.
 */
function mergeBestQuality(
  ours: ContextItem[],
  theirs: ContextItem[],
  dimension: "density" | "diversity" | "freshness" | "redundancy" | "overall"
): {
  items: ContextItem[];
  added: ContextItem[];
  removed: ContextItem[];
  conflicts: number;
} {
  const oursQuality = analyzeContext(ours);
  const theirsQuality = analyzeContext(theirs);

  let oursScore: number;
  let theirsScore: number;

  if (dimension === "redundancy") {
    // Lower redundancy is better
    oursScore = 1 - oursQuality.redundancy;
    theirsScore = 1 - theirsQuality.redundancy;
  } else {
    oursScore = oursQuality[dimension];
    theirsScore = theirsQuality[dimension];
  }

  // Count conflicts (same ID, different content)
  const oursMap = new Map(ours.map(item => [item.id, item]));
  let conflicts = 0;
  for (const item of theirs) {
    const ourItem = oursMap.get(item.id);
    if (ourItem && ourItem.content !== item.content) {
      conflicts++;
    }
  }

  if (theirsScore > oursScore) {
    // Theirs is better; added = items from theirs not in ours, removed = ours items not in theirs
    const theirsMap = new Map(theirs.map(item => [item.id, item]));
    const added = theirs.filter(item => !oursMap.has(item.id));
    const removed = ours.filter(item => !theirsMap.has(item.id));
    return { items: [...theirs], added, removed, conflicts };
  }

  // Ours is better or equal, keep ours
  return { items: [...ours], added: [], removed: [], conflicts };
}

/**
 * Highest-priority merge: for items with the same ID, keep the one
 * with higher priority. Items unique to either branch are included.
 */
function mergeHighestPriority(
  ours: ContextItem[],
  theirs: ContextItem[]
): {
  items: ContextItem[];
  added: ContextItem[];
  removed: ContextItem[];
  conflicts: number;
} {
  const oursMap = new Map(ours.map(item => [item.id, item]));
  const theirsMap = new Map(theirs.map(item => [item.id, item]));

  const result: ContextItem[] = [];
  const added: ContextItem[] = [];
  let conflicts = 0;

  // Process all our items, resolving conflicts by priority
  for (const item of ours) {
    const theirItem = theirsMap.get(item.id);
    if (theirItem && theirItem.content !== item.content) {
      conflicts++;
      const ourPriority = item.priority ?? 0;
      const theirPriority = theirItem.priority ?? 0;
      result.push(theirPriority > ourPriority ? theirItem : item);
    } else {
      result.push(item);
    }
  }

  // Add items only in theirs
  for (const item of theirs) {
    if (!oursMap.has(item.id)) {
      result.push(item);
      added.push(item);
    }
  }

  return { items: result, added, removed: [], conflicts };
}

/**
 * Manual merge: delegate to the user-supplied resolver function.
 */
function mergeManual(
  ours: ContextItem[],
  theirs: ContextItem[],
  resolver: (ours: ContextItem[], theirs: ContextItem[]) => ContextItem[]
): {
  items: ContextItem[];
  added: ContextItem[];
  removed: ContextItem[];
  conflicts: number;
} {
  const oursMap = new Map(ours.map(item => [item.id, item]));

  const items = resolver(ours, theirs);
  const resultMap = new Map(items.map(item => [item.id, item]));

  // Compute added/removed relative to ours
  const added = items.filter(item => !oursMap.has(item.id));
  const removed = ours.filter(item => !resultMap.has(item.id));

  // Count conflicts
  let conflicts = 0;
  for (const item of theirs) {
    const ourItem = oursMap.get(item.id);
    if (ourItem && ourItem.content !== item.content) {
      conflicts++;
    }
  }

  return { items, added, removed, conflicts };
}

/**
 * Execute a merge between two sets of items using the specified strategy.
 */
export function executeMerge(
  ours: ContextItem[],
  theirs: ContextItem[],
  fromBranch: string,
  intoBranch: string,
  options: MergeOptions = { strategy: "union" }
): MergeResult {
  const strategy = options.strategy;

  let result: {
    items: ContextItem[];
    added: ContextItem[];
    removed: ContextItem[];
    conflicts: number;
  };

  switch (strategy) {
    case "union":
      result = mergeUnion(ours, theirs);
      break;
    case "intersection":
      result = mergeIntersection(ours, theirs);
      break;
    case "best-quality":
      result = mergeBestQuality(
        ours,
        theirs,
        options.qualityDimension ?? "overall"
      );
      break;
    case "highest-priority":
      result = mergeHighestPriority(ours, theirs);
      break;
    case "manual": {
      if (!options.resolver) {
        throw new Error(
          'Manual merge strategy requires a "resolver" function in MergeOptions'
        );
      }
      result = mergeManual(ours, theirs, options.resolver);
      break;
    }
    default: {
      const _exhaustive: never = strategy;
      throw new Error(`Unknown merge strategy: ${_exhaustive}`);
    }
  }

  return {
    items: result.items,
    strategy,
    fromBranch,
    intoBranch,
    added: result.added,
    removed: result.removed,
    conflicts: result.conflicts,
  };
}
