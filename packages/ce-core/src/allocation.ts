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
import { pack, packAsync } from "./pack.js";
import { KindAllocationSchema, validateWithSchema } from "./schemas.js";
import type { MaybeAsync } from "./maybe-async.js";
import { chain } from "./maybe-async.js";

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

/** Function that packs items into a budget, returning sync or async. */
type PackFn = (
  items: ContextItem[],
  budget: Budget,
  options: PackOptions
) => MaybeAsync<ContextPack>;

/**
 * Shared implementation for both sync and async packWithAllocation.
 *
 * Uses MaybeAsync + chain() so the sync path never creates Promises,
 * while the async path chains naturally through .then().
 */
function packWithAllocationImpl(
  items: ContextItem[],
  budget: Budget,
  allocations: KindAllocation[],
  options: PackOptions,
  packFn: PackFn
): MaybeAsync<AllocatedPack> {
  for (let i = 0; i < allocations.length; i++) {
    validateWithSchema(
      KindAllocationSchema,
      allocations[i],
      `allocations[${i}]`
    );
  }

  const effectiveBudget = budget.maxTokens - (budget.reserveTokens ?? 0);
  const priorityByKind = new Map(
    allocations.map(alloc => [alloc.kind, alloc.priority ?? 0])
  );

  // Build a Set of allocated kinds for O(1) lookup (M1 fix)
  const allocatedKinds = new Set(allocations.map(a => a.kind));

  // Group items by kind
  const kindGroups = new Map<string, ContextItem[]>();
  const uncategorized: ContextItem[] = [];

  for (const item of items) {
    const kind = item.kind ?? "_uncategorized";
    if (allocatedKinds.has(kind)) {
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

  // Normalize if over-allocated. Prefer preserving higher-priority kinds.
  if (allocatedTotal > effectiveBudget) {
    let overflow = allocatedTotal - effectiveBudget;
    const adjustable = [...allocations].sort(
      (a, b) => (a.priority ?? 0) - (b.priority ?? 0)
    );

    for (const alloc of adjustable) {
      if (overflow <= 0) break;
      const current = kindBudgets.get(alloc.kind) ?? 0;
      const floor = alloc.minTokens ?? 0;
      const reducible = Math.max(0, current - floor);
      if (reducible <= 0) continue;
      const reduction = Math.min(reducible, overflow);
      kindBudgets.set(alloc.kind, current - reduction);
      overflow -= reduction;
    }

    for (const alloc of adjustable) {
      if (overflow <= 0) break;
      const current = kindBudgets.get(alloc.kind) ?? 0;
      if (current <= 0) continue;
      const reduction = Math.min(current, overflow);
      kindBudgets.set(alloc.kind, current - reduction);
      overflow -= reduction;
    }
  }

  // Phase 2: Pack within each kind's allocation
  const kindResults = new Map<
    string,
    { selected: ContextItem[]; dropped: ContextItem[]; used: number }
  >();
  let totalSurplus = 0;

  // Process each allocation sequentially, chaining MaybeAsync results
  let phase2: MaybeAsync<void> = undefined as unknown as void;

  for (const alloc of allocations) {
    phase2 = chain(phase2, () => {
      const kindItems = kindGroups.get(alloc.kind) ?? [];
      const kindBudget = kindBudgets.get(alloc.kind) ?? 0;

      if (kindItems.length === 0 || kindBudget <= 0) {
        kindResults.set(alloc.kind, {
          selected: [],
          dropped: kindItems,
          used: 0,
        });
        totalSurplus += kindBudget;
        return;
      }

      return chain(
        packFn(kindItems, { maxTokens: kindBudget }, options),
        result => {
          kindResults.set(alloc.kind, {
            selected: result.selected,
            dropped: result.dropped,
            used: result.totalTokens,
          });

          const surplus = kindBudget - result.totalTokens;
          if (surplus > 0) totalSurplus += surplus;
        }
      );
    });
  }

  // Phase 3: Redistribute surplus to kinds that need more space
  return chain(phase2, () => {
    let redistributeChain: MaybeAsync<void> = undefined as unknown as void;

    if (totalSurplus > 0) {
      const sortedByPriority = [...allocations].sort(
        (a, b) => (b.priority ?? 0) - (a.priority ?? 0)
      );

      for (const alloc of sortedByPriority) {
        redistributeChain = chain(redistributeChain, () => {
          if (totalSurplus <= 0) return;

          const result = kindResults.get(alloc.kind);
          if (!result || result.dropped.length === 0) return;

          const maxExtra =
            alloc.maxTokens !== undefined
              ? alloc.maxTokens - result.used
              : totalSurplus;

          if (maxExtra <= 0) return;

          const extraBudget = Math.min(totalSurplus, maxExtra);
          return chain(
            packFn(result.dropped, { maxTokens: extraBudget }, options),
            extraPack => {
              result.selected.push(...extraPack.selected);
              result.dropped = extraPack.dropped;
              result.used += extraPack.totalTokens;
              kindBudgets.set(
                alloc.kind,
                (kindBudgets.get(alloc.kind) ?? result.used) +
                  extraPack.totalTokens
              );
              totalSurplus -= extraPack.totalTokens;
            }
          );
        });
      }
    }

    // Phase 4: Pack uncategorized items into remaining budget
    return chain(redistributeChain, () => {
      const usedSoFar = Array.from(kindResults.values()).reduce(
        (sum, r) => sum + r.used,
        0
      );
      const remainingBudget = effectiveBudget - usedSoFar;

      const uncatPack: MaybeAsync<{
        selected: ContextItem[];
        dropped: ContextItem[];
      }> =
        uncategorized.length > 0 && remainingBudget > 0
          ? chain(
              packFn(uncategorized, { maxTokens: remainingBudget }, options),
              result => ({
                selected: result.selected,
                dropped: result.dropped,
              })
            )
          : { selected: [], dropped: uncategorized };

      return chain(uncatPack, uncategorizedResult => {
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
            surplus: Math.max(
              0,
              (kindBudgets.get(alloc.kind) ?? 0) - result.used
            ),
          };
        }

        allSelected.sort((a, b) => {
          const kindDelta =
            (priorityByKind.get(b.kind ?? "_uncategorized") ?? 0) -
            (priorityByKind.get(a.kind ?? "_uncategorized") ?? 0);
          if (kindDelta !== 0) return kindDelta;
          return (b.priority ?? 0) - (a.priority ?? 0);
        });

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

        const totalTokens = allSelected.reduce(
          (sum, i) => sum + (i.tokens ?? 0),
          0
        );

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
      });
    });
  });
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
  return packWithAllocationImpl(
    items,
    budget,
    allocations,
    options,
    pack
  ) as AllocatedPack;
}

/**
 * Async variant of packWithAllocation.
 *
 * Same logic as packWithAllocation but delegates to packAsync() internally,
 * supporting async operations like embedding-based redundancy elimination.
 *
 * @param items - Context items to pack (should have `kind` set)
 * @param budget - Total token budget
 * @param allocations - Per-kind budget constraints
 * @param options - Standard pack options (supports embeddingProvider, redundancyConfig)
 * @returns Promise<AllocatedPack> with per-kind breakdown
 */
export async function packWithAllocationAsync(
  items: ContextItem[],
  budget: Budget,
  allocations: KindAllocation[],
  options: PackOptions = {}
): Promise<AllocatedPack> {
  return packWithAllocationImpl(
    items,
    budget,
    allocations,
    options,
    packAsync
  ) as Promise<AllocatedPack>;
}
