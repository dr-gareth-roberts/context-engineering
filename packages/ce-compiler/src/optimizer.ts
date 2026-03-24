import type { ContextItem } from "@context-engineering/core";
import { estimateTokens } from "@context-engineering/core";
import type { Slot, CompileTarget, OptimizationPass } from "./types.js";

function wordSet(text: string): Set<string> {
  return new Set(
    text
      .toLowerCase()
      .split(/\s+/)
      .filter(w => w.length > 2)
  );
}

function jaccardSimilarity(a: Set<string>, b: Set<string>): number {
  let intersection = 0;
  for (const word of a) {
    if (b.has(word)) intersection++;
  }
  const union = a.size + b.size - intersection;
  return union > 0 ? intersection / union : 0;
}

function getSlotForItem(item: ContextItem, slots: Slot[]): Slot | undefined {
  return slots.find(s => s.kind === item.kind);
}

/**
 * Position-aware placement: move items from "first" slots to the beginning
 * and "last" slots to the end. Model-specific attention optimization applied.
 */
function positionAwarePlacement(
  items: ContextItem[],
  target: CompileTarget,
  slots: Slot[]
): { items: ContextItem[]; pass: OptimizationPass } {
  const firstItems: ContextItem[] = [];
  const lastItems: ContextItem[] = [];
  const anyItems: ContextItem[] = [];

  for (const item of items) {
    const slot = getSlotForItem(item, slots);
    const position = slot?.position ?? "any";

    if (position === "first") {
      firstItems.push(item);
    } else if (position === "last") {
      lastItems.push(item);
    } else {
      anyItems.push(item);
    }
  }

  // Model-specific ordering of "any" items
  if (target === "claude") {
    // U-shaped attention: high priority at start and end
    const sorted = [...anyItems].sort(
      (a, b) => (b.priority ?? 0) - (a.priority ?? 0)
    );
    const half = Math.ceil(sorted.length / 2);
    const startItems = sorted.slice(0, half);
    const endItems = sorted.slice(half).reverse();
    anyItems.length = 0;
    anyItems.push(...startItems, ...endItems);
  } else if (target === "gpt4") {
    // GPT-4: strong recency bias, favor start
    anyItems.sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
  } else if (target === "gemini") {
    // Gemini: more uniform, keep original order but group by kind
    anyItems.sort((a, b) => (a.kind ?? "").localeCompare(b.kind ?? ""));
  }
  // generic: leave as-is

  const result = [...firstItems, ...anyItems, ...lastItems];
  const totalTokens = result.reduce(
    (sum, item) => sum + (item.tokens ?? estimateTokens(item.content)),
    0
  );

  return {
    items: result,
    pass: {
      name: "position-aware-placement",
      description: `Ordered items by position constraints for ${target} target`,
      itemsReordered: result.length,
      tokensAffected: totalTokens,
    },
  };
}

/**
 * Cache prefix ordering: within "first" and "any" slot groups, sort by ID
 * for deterministic ordering to maximize cache reuse.
 */
function cachePrefixOrdering(
  items: ContextItem[],
  _target: CompileTarget,
  slots: Slot[]
): { items: ContextItem[]; pass: OptimizationPass } {
  // Identify contiguous groups of first/any items before any "last" items
  const lastStartIndex = items.findIndex(item => {
    const slot = getSlotForItem(item, slots);
    return slot?.position === "last";
  });
  const boundary = lastStartIndex === -1 ? items.length : lastStartIndex;

  // Sort the prefix portion by ID for cache stability
  const prefix = items.slice(0, boundary);
  const suffix = items.slice(boundary);

  // Group prefix by slot position to avoid mixing first/any
  const firstPrefix = prefix.filter(item => {
    const slot = getSlotForItem(item, slots);
    return slot?.position === "first";
  });
  const anyPrefix = prefix.filter(item => {
    const slot = getSlotForItem(item, slots);
    return slot?.position !== "first";
  });

  // Only sort "first"-position items by ID for cache prefix stability.
  // "any"-position items keep their model-optimized order from position-aware-placement.
  firstPrefix.sort((a, b) => a.id.localeCompare(b.id));

  const result = [...firstPrefix, ...anyPrefix, ...suffix];
  const tokensAffected = firstPrefix.reduce(
    (sum, item) => sum + (item.tokens ?? estimateTokens(item.content)),
    0
  );

  return {
    items: result,
    pass: {
      name: "cache-prefix-ordering",
      description:
        "Sorted prefix items by ID for deterministic cache-friendly ordering",
      itemsReordered: prefix.length,
      tokensAffected,
    },
  };
}

/**
 * Deduplication: for slots with deduplicate: true, remove items with
 * >0.8 Jaccard word-level overlap.
 */
function deduplication(
  items: ContextItem[],
  _target: CompileTarget,
  slots: Slot[]
): { items: ContextItem[]; pass: OptimizationPass } {
  const deduplicateKinds = new Set(
    slots.filter(s => s.deduplicate).map(s => s.kind)
  );

  if (deduplicateKinds.size === 0) {
    return {
      items,
      pass: {
        name: "deduplication",
        description: "No slots configured for deduplication",
        itemsReordered: 0,
        tokensAffected: 0,
      },
    };
  }

  const result: ContextItem[] = [];
  const removedTokens: number[] = [];

  // Process items: keep non-dedup items as-is, deduplicate within dedup kinds
  const dedupItems: ContextItem[] = [];
  const otherItems: ContextItem[] = [];

  for (const item of items) {
    if (item.kind && deduplicateKinds.has(item.kind)) {
      dedupItems.push(item);
    } else {
      otherItems.push(item);
    }
  }

  // Deduplicate within the dedup set
  const kept: ContextItem[] = [];
  const keptWordSets: Set<string>[] = [];

  for (const item of dedupItems) {
    const ws = wordSet(item.content);
    let isDuplicate = false;

    for (const existingWs of keptWordSets) {
      if (jaccardSimilarity(ws, existingWs) > 0.8) {
        isDuplicate = true;
        removedTokens.push(item.tokens ?? estimateTokens(item.content));
        break;
      }
    }

    if (!isDuplicate) {
      kept.push(item);
      keptWordSets.push(ws);
    }
  }

  // Reconstruct in original order
  const keptIds = new Set(kept.map(i => i.id));
  const otherIds = new Set(otherItems.map(i => i.id));
  for (const item of items) {
    if (otherIds.has(item.id) || keptIds.has(item.id)) {
      result.push(item);
    }
  }

  const totalRemovedTokens = removedTokens.reduce((a, b) => a + b, 0);

  return {
    items: result,
    pass: {
      name: "deduplication",
      description: `Removed ${removedTokens.length} duplicate items (>0.8 Jaccard overlap)`,
      itemsReordered: removedTokens.length,
      tokensAffected: totalRemovedTokens,
    },
  };
}

/**
 * Staleness pruning: remove items whose recency is below the slot's
 * maxStaleness threshold.
 */
function stalenessPruning(
  items: ContextItem[],
  _target: CompileTarget,
  slots: Slot[]
): { items: ContextItem[]; pass: OptimizationPass } {
  const stalenessMap = new Map<string, number>();
  for (const slot of slots) {
    if (slot.maxStaleness !== undefined) {
      stalenessMap.set(slot.kind, slot.maxStaleness);
    }
  }

  if (stalenessMap.size === 0) {
    return {
      items,
      pass: {
        name: "staleness-pruning",
        description: "No slots configured with maxStaleness",
        itemsReordered: 0,
        tokensAffected: 0,
      },
    };
  }

  const result: ContextItem[] = [];
  let removedCount = 0;
  let removedTokens = 0;

  for (const item of items) {
    const threshold = item.kind ? stalenessMap.get(item.kind) : undefined;
    if (threshold !== undefined) {
      const recency = item.recency ?? 0;
      if (recency < threshold) {
        removedCount++;
        removedTokens += item.tokens ?? estimateTokens(item.content);
        continue;
      }
    }
    result.push(item);
  }

  return {
    items: result,
    pass: {
      name: "staleness-pruning",
      description: `Removed ${removedCount} stale items below recency threshold`,
      itemsReordered: removedCount,
      tokensAffected: removedTokens,
    },
  };
}

/**
 * Apply per-model optimization passes to a set of items.
 *
 * Passes applied in order:
 * 1. staleness-pruning (remove stale items first)
 * 2. deduplication (remove duplicates)
 * 3. position-aware-placement (model-specific ordering)
 * 4. cache-prefix-ordering (deterministic prefix for cache reuse)
 */
export function optimizeForTarget(
  items: ContextItem[],
  target: CompileTarget,
  slots: Slot[]
): { items: ContextItem[]; passes: OptimizationPass[] } {
  const passes: OptimizationPass[] = [];
  let current = [...items];

  // 1. Staleness pruning
  const staleness = stalenessPruning(current, target, slots);
  current = staleness.items;
  passes.push(staleness.pass);

  // 2. Deduplication
  const dedup = deduplication(current, target, slots);
  current = dedup.items;
  passes.push(dedup.pass);

  // 3. Position-aware placement
  const placement = positionAwarePlacement(current, target, slots);
  current = placement.items;
  passes.push(placement.pass);

  // 4. Cache prefix ordering
  const cacheOrder = cachePrefixOrdering(current, target, slots);
  current = cacheOrder.items;
  passes.push(cacheOrder.pass);

  return { items: current, passes };
}
