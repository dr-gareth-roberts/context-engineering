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

/** Deterministic serialisation (sorted keys) for structural comparison. */
function stableStringify(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map(stableStringify).join(",")}]`;
  }
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries
      .map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`)
      .join(",")}}`;
  }
  return JSON.stringify(value) ?? "undefined";
}

/** True when the item is unchanged from its merge-base version (any field). */
function sameContent(a: ContextItem | undefined, b: ContextItem): boolean {
  return a !== undefined && stableStringify(a) === stableStringify(b);
}

function resolveUnionConflict(
  ours: ContextItem,
  theirs: ContextItem
): ContextItem {
  const ourRecency = ours.recency ?? 0;
  const theirRecency = theirs.recency ?? 0;
  return theirRecency > ourRecency ? theirs : ours;
}

function resolvePriorityConflict(
  ours: ContextItem,
  theirs: ContextItem
): ContextItem {
  const ourPriority = ours.priority ?? 0;
  const theirPriority = theirs.priority ?? 0;
  return theirPriority > ourPriority ? theirs : ours;
}

function mergeThreeWayUnionLike(
  ours: ContextItem[],
  theirs: ContextItem[],
  ancestor: ContextItem[],
  resolveConflict: (ours: ContextItem, theirs: ContextItem) => ContextItem
): {
  items: ContextItem[];
  added: ContextItem[];
  removed: ContextItem[];
  conflicts: number;
} {
  const oursMap = new Map(ours.map(item => [item.id, item]));
  const theirsMap = new Map(theirs.map(item => [item.id, item]));
  const ancestorMap = new Map(ancestor.map(item => [item.id, item]));
  const orderedIds = new Set<string>([
    ...ours.map(item => item.id),
    ...theirs.map(item => item.id),
    ...ancestor.map(item => item.id),
  ]);

  const items: ContextItem[] = [];
  let conflicts = 0;

  for (const id of orderedIds) {
    const ourItem = oursMap.get(id);
    const theirItem = theirsMap.get(id);
    const baseItem = ancestorMap.get(id);

    if (!baseItem) {
      if (ourItem && theirItem) {
        if (ourItem.content !== theirItem.content) {
          conflicts++;
          items.push(resolveConflict(ourItem, theirItem));
        } else {
          items.push(ourItem);
        }
      } else if (ourItem) {
        items.push(ourItem);
      } else if (theirItem) {
        items.push(theirItem);
      }
      continue;
    }

    if (!ourItem && !theirItem) continue;

    const oursChanged =
      ourItem !== undefined && !sameContent(ourItem, baseItem);
    const theirsChanged =
      theirItem !== undefined && !sameContent(theirItem, baseItem);

    if (!ourItem) {
      if (theirItem && theirsChanged) {
        items.push(theirItem);
      }
      continue;
    }

    if (!theirItem) {
      if (oursChanged) {
        items.push(ourItem);
      }
      continue;
    }

    if (!oursChanged && !theirsChanged) {
      items.push(ourItem);
    } else if (oursChanged && !theirsChanged) {
      items.push(ourItem);
    } else if (!oursChanged && theirsChanged) {
      items.push(theirItem);
    } else if (sameContent(ourItem, theirItem)) {
      items.push(ourItem);
    } else {
      conflicts++;
      items.push(resolveConflict(ourItem, theirItem));
    }
  }

  const resultMap = new Map(items.map(item => [item.id, item]));
  const added = items.filter(item => !oursMap.has(item.id));
  const removed = ours.filter(item => !resultMap.has(item.id));

  return { items, added, removed, conflicts };
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
  options: MergeOptions = { strategy: "union" },
  ancestor?: ContextItem[]
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
      result = ancestor
        ? mergeThreeWayUnionLike(ours, theirs, ancestor, resolveUnionConflict)
        : mergeUnion(ours, theirs);
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
      result = ancestor
        ? mergeThreeWayUnionLike(
            ours,
            theirs,
            ancestor,
            resolvePriorityConflict
          )
        : mergeHighestPriority(ours, theirs);
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
