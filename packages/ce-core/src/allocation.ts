/**
 * Kind-Aware Budget Allocation
 *
 * Replaces flat greedy packing with category-level budget constraints.
 * Instead of treating all items as a flat list, groups them by `kind`
 * and allocates budget per category with min/max/target constraints.
 *
 * Research: "Token-Budget-Aware LLM Reasoning" (ACL 2025) showed up to
 * 47% cost reduction with dynamic budget approaches while maintaining accuracy.
 */

import type { Budget, ContextItem, ContextPack, PackOptions } from "./types.js";
import { pack } from "./pack.js";

/**
 * Budget constraint for a single item kind.
 */
export interface KindAllocation {
  /** The kind to match (e.g., "system", "memory", "retrieval") */
  kind: string;
  /** Minimum tokens to allocate (floor) */
  minTokens?: number;
  /** Maximum tokens to allocate (ceiling) */
  maxTokens?: number;
  /** Target fraction of total budget (0-1) */
  targetRatio?: number;
  /** Priority for surplus redistribution (higher = gets surplus first) */
  priority?: number;
}

/**
 * Per-kind allocation result.
 */
export interface KindResult {
  kind: string;
  budgetAllocated: number;
  budgetUsed: number;
  itemCount: number;
  surplus: number;
}

/**
 * Result of kind-aware packing, extending ContextPack.
 */
export interface AllocatedPack extends ContextPack {
  /** Per-kind allocation breakdown */
  allocations: Record<string, KindResult>;
  /** How well actual allocation matches target (0-1) */
  allocationEfficiency: number;
}

/**
 * Pack items with kind-aware budget allocation.
 *
 * Groups items by `kind`, allocates budget per category respecting
 * min/max/target constraints, then packs greedily within each allocation.
 * Surplus budget from underfilled categories is redistributed to
 * overfilled ones by priority.
 *
 * @param items - Context items to pack (should have `kind` set)
 * @param budget - Total token budget
 * @param allocations - Per-kind budget constraints
 * @param options - Standard pack options
 * @returns AllocatedPack with per-kind breakdown
 *
 * @example
 * ```ts
 * const result = packWithAllocation(
 *   items,
 *   { maxTokens: 8000 },
 *   [
 *     { kind: "system", minTokens: 500, maxTokens: 1500, targetRatio: 0.15, priority: 10 },
 *     { kind: "retrieval", targetRatio: 0.40, priority: 5 },
 *     { kind: "conversation", targetRatio: 0.35, priority: 7 },
 *     { kind: "memory", targetRatio: 0.10, priority: 3 },
 *   ],
 *   {}
 * );
 * console.log(result.allocations);
 * console.log(result.allocationEfficiency);
 * ```
 */
export function packWithAllocation(
  items: ContextItem[],
  budget: Budget,
  allocations: KindAllocation[],
  options: PackOptions = {}
): AllocatedPack {
  const effectiveBudget = budget.maxTokens - (budget.reserveTokens ?? 0);

  // Group items by kind
  const kindGroups = new Map<string, ContextItem[]>();
  const uncategorized: ContextItem[] = [];

  for (const item of items) {
    const kind = item.kind ?? "_uncategorized";
    const alloc = allocations.find(a => a.kind === kind);
    if (alloc) {
      const group = kindGroups.get(kind) ?? [];
      group.push(item);
      kindGroups.set(kind, group);
    } else {
      uncategorized.push(item);
    }
  }

  // Phase 1: Compute initial allocation per kind
  const kindBudgets = new Map<string, number>();
  let allocatedTotal = 0;

  for (const alloc of allocations) {
    let tokens = 0;
    if (alloc.targetRatio !== undefined) {
      tokens = Math.floor(effectiveBudget * alloc.targetRatio);
    }
    if (alloc.minTokens !== undefined) {
      tokens = Math.max(tokens, alloc.minTokens);
    }
    if (alloc.maxTokens !== undefined) {
      tokens = Math.min(tokens, alloc.maxTokens);
    }
    kindBudgets.set(alloc.kind, tokens);
    allocatedTotal += tokens;
  }

  // Scale if over-allocated
  if (allocatedTotal > effectiveBudget) {
    const scale = effectiveBudget / allocatedTotal;
    kindBudgets.forEach((tokens, kind) => {
      const alloc = allocations.find(a => a.kind === kind);
      let scaled = Math.floor(tokens * scale);
      if (alloc?.minTokens !== undefined) {
        scaled = Math.max(scaled, alloc.minTokens);
      }
      kindBudgets.set(kind, scaled);
    });
  }

  // Phase 2: Pack within each kind's allocation
  const kindResults = new Map<
    string,
    { selected: ContextItem[]; dropped: ContextItem[]; used: number }
  >();
  let totalSurplus = 0;

  for (const alloc of allocations) {
    const kindItems = kindGroups.get(alloc.kind) ?? [];
    const kindBudget = kindBudgets.get(alloc.kind) ?? 0;

    if (kindItems.length === 0 || kindBudget <= 0) {
      kindResults.set(alloc.kind, {
        selected: [],
        dropped: kindItems,
        used: 0,
      });
      totalSurplus += kindBudget;
      continue;
    }

    const result = pack(kindItems, { maxTokens: kindBudget }, options);
    kindResults.set(alloc.kind, {
      selected: result.selected,
      dropped: result.dropped,
      used: result.totalTokens,
    });

    const surplus = kindBudget - result.totalTokens;
    if (surplus > 0) totalSurplus += surplus;
  }

  // Phase 3: Redistribute surplus to kinds that need more space
  if (totalSurplus > 0) {
    const sortedByPriority = [...allocations].sort(
      (a, b) => (b.priority ?? 0) - (a.priority ?? 0)
    );

    for (const alloc of sortedByPriority) {
      if (totalSurplus <= 0) break;

      const result = kindResults.get(alloc.kind);
      if (!result || result.dropped.length === 0) continue;

      const maxExtra =
        alloc.maxTokens !== undefined
          ? alloc.maxTokens - result.used
          : totalSurplus;

      if (maxExtra <= 0) continue;

      const extraBudget = Math.min(totalSurplus, maxExtra);
      const extraPack = pack(
        result.dropped,
        { maxTokens: extraBudget },
        options
      );

      result.selected.push(...extraPack.selected);
      result.dropped = extraPack.dropped;
      result.used += extraPack.totalTokens;
      totalSurplus -= extraPack.totalTokens;
    }
  }

  // Phase 4: Pack uncategorized items into remaining budget
  const usedSoFar = Array.from(kindResults.values()).reduce(
    (sum, r) => sum + r.used,
    0
  );
  const remainingBudget = effectiveBudget - usedSoFar;

  let uncategorizedResult: { selected: ContextItem[]; dropped: ContextItem[] };
  if (uncategorized.length > 0 && remainingBudget > 0) {
    const result = pack(uncategorized, { maxTokens: remainingBudget }, options);
    uncategorizedResult = {
      selected: result.selected,
      dropped: result.dropped,
    };
  } else {
    uncategorizedResult = { selected: [], dropped: uncategorized };
  }

  // Compose final result
  const allSelected: ContextItem[] = [];
  const allDropped: ContextItem[] = [];
  const allocResult: Record<string, KindResult> = {};

  for (const alloc of allocations) {
    const result = kindResults.get(alloc.kind);
    if (!result) continue;
    allSelected.push(...result.selected);
    allDropped.push(...result.dropped);
    allocResult[alloc.kind] = {
      kind: alloc.kind,
      budgetAllocated: kindBudgets.get(alloc.kind) ?? 0,
      budgetUsed: result.used,
      itemCount: result.selected.length,
      surplus: Math.max(0, (kindBudgets.get(alloc.kind) ?? 0) - result.used),
    };
  }

  allSelected.push(...uncategorizedResult.selected);
  allDropped.push(...uncategorizedResult.dropped);

  if (
    uncategorizedResult.selected.length > 0 ||
    uncategorizedResult.dropped.length > 0
  ) {
    const uncatTokens = uncategorizedResult.selected.reduce(
      (sum, i) => sum + (i.tokens ?? 0),
      0
    );
    allocResult["_uncategorized"] = {
      kind: "_uncategorized",
      budgetAllocated: remainingBudget,
      budgetUsed: uncatTokens,
      itemCount: uncategorizedResult.selected.length,
      surplus: Math.max(0, remainingBudget - uncatTokens),
    };
  }

  const totalTokens = allSelected.reduce((sum, i) => sum + (i.tokens ?? 0), 0);

  // Compute allocation efficiency: how close actual ratios match targets
  let efficiencySum = 0;
  let efficiencyCount = 0;
  for (const alloc of allocations) {
    if (alloc.targetRatio !== undefined && totalTokens > 0) {
      const actualRatio =
        (allocResult[alloc.kind]?.budgetUsed ?? 0) / totalTokens;
      const diff = Math.abs(actualRatio - alloc.targetRatio);
      efficiencySum += 1 - Math.min(diff / alloc.targetRatio, 1);
      efficiencyCount++;
    }
  }

  return {
    budget,
    selected: allSelected,
    dropped: allDropped,
    totalTokens,
    stats: {
      kindCount: allocations.length,
      remainingTokens: Math.max(0, effectiveBudget - totalTokens),
    },
    allocations: allocResult,
    allocationEfficiency:
      efficiencyCount > 0
        ? Math.round((efficiencySum / efficiencyCount) * 1000) / 1000
        : 1,
  };
}
