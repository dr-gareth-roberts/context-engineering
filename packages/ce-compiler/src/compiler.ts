import { estimateTokens, analyzeContext } from "@context-engineering/core";
import type { ContextItem } from "@context-engineering/core";
import type {
  ContextProgram,
  CompileOptions,
  CompileResult,
  CompileDiagnostic,
  Slot,
  ContextCompiler,
} from "./types.js";
import { validateConstraints } from "./constraints.js";
import { optimizeForTarget } from "./optimizer.js";

function getItemTokens(item: ContextItem): number {
  return item.tokens ?? estimateTokens(item.content);
}

function selectByStrategy(
  items: ContextItem[],
  strategy: "priority" | "recency" | "relevance"
): ContextItem[] {
  const sorted = [...items];
  switch (strategy) {
    case "priority":
      sorted.sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
      break;
    case "recency":
      sorted.sort((a, b) => (b.recency ?? 0) - (a.recency ?? 0));
      break;
    case "relevance":
      sorted.sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
      break;
  }
  return sorted;
}

function categorizeItems(
  items: ContextItem[],
  slots: Slot[]
): { slotItems: Map<string, ContextItem[]>; uncategorized: ContextItem[] } {
  const slotItems = new Map<string, ContextItem[]>();
  const matchedIds = new Set<string>();

  for (const slot of slots) {
    slotItems.set(slot.name, []);
  }

  for (const item of items) {
    let matched = false;
    for (const slot of slots) {
      if (item.kind === slot.kind) {
        slotItems.get(slot.name)!.push(item);
        matchedIds.add(item.id);
        matched = true;
        break;
      }
    }
    if (!matched && !matchedIds.has(item.id)) {
      // Will be handled by fillRemaining slots
    }
  }

  const uncategorized = items.filter(item => !matchedIds.has(item.id));
  return { slotItems, uncategorized };
}

/**
 * Create a context compiler instance.
 *
 * The compiler takes a declarative ContextProgram and a set of items,
 * then optimizes the layout for the target model.
 *
 * @example
 * ```ts
 * const compiler = createContextCompiler();
 * const result = compiler.compile(program, {
 *   target: "claude",
 *   items: myItems,
 *   budget: { maxTokens: 8000 },
 * });
 * ```
 */
export function createContextCompiler(): ContextCompiler {
  return {
    compile(program: ContextProgram, options: CompileOptions): CompileResult {
      const { target, items, budget } = options;
      const { slots, constraints } = program;
      const maxTokens = budget.maxTokens - (budget.reserveTokens ?? 0);

      // 1. Categorize items into slots
      const { slotItems, uncategorized } = categorizeItems(items, slots);

      // 2. Select items per slot respecting budgets and strategies
      const selected: ContextItem[] = [];
      const dropped: ContextItem[] = [];
      const slotStats: Record<
        string,
        { itemCount: number; tokensUsed: number; satisfied: boolean }
      > = {};
      let usedTokens = 0;

      // First pass: required slots and slots with explicit budgets
      for (const slot of slots) {
        if (slot.fillRemaining) continue;

        const candidates = slotItems.get(slot.name) ?? [];
        const strategy = slot.strategy ?? "priority";
        const sorted = selectByStrategy(candidates, strategy);

        const slotMaxTokens = slot.maxTokens ?? maxTokens;
        let slotTokens = 0;
        const slotSelected: ContextItem[] = [];

        for (const item of sorted) {
          const itemTokens = getItemTokens(item);
          if (
            usedTokens + slotTokens + itemTokens <= maxTokens &&
            slotTokens + itemTokens <= slotMaxTokens
          ) {
            slotSelected.push(item);
            slotTokens += itemTokens;
          } else {
            dropped.push(item);
          }
        }

        const minSatisfied = slot.minTokens
          ? slotTokens >= slot.minTokens
          : true;
        const hasCoverage = !slot.required || slotSelected.length > 0;

        slotStats[slot.name] = {
          itemCount: slotSelected.length,
          tokensUsed: slotTokens,
          satisfied: minSatisfied && hasCoverage,
        };

        selected.push(...slotSelected);
        usedTokens += slotTokens;
      }

      // Second pass: fillRemaining slots get leftover budget + uncategorized items
      for (const slot of slots) {
        if (!slot.fillRemaining) continue;

        const candidates = [
          ...(slotItems.get(slot.name) ?? []),
          ...uncategorized,
        ];
        const strategy = slot.strategy ?? "priority";
        const sorted = selectByStrategy(candidates, strategy);

        const remainingBudget = maxTokens - usedTokens;
        const slotMaxTokens = slot.maxTokens
          ? Math.min(slot.maxTokens, remainingBudget)
          : remainingBudget;
        let slotTokens = 0;
        const slotSelected: ContextItem[] = [];

        for (const item of sorted) {
          const itemTokens = getItemTokens(item);
          if (
            slotTokens + itemTokens <= slotMaxTokens &&
            usedTokens + slotTokens + itemTokens <= maxTokens
          ) {
            slotSelected.push(item);
            slotTokens += itemTokens;
          } else {
            dropped.push(item);
          }
        }

        const minSatisfied = slot.minTokens
          ? slotTokens >= slot.minTokens
          : true;
        const hasCoverage = !slot.required || slotSelected.length > 0;

        slotStats[slot.name] = {
          itemCount: slotSelected.length,
          tokensUsed: slotTokens,
          satisfied: minSatisfied && hasCoverage,
        };

        selected.push(...slotSelected);
        usedTokens += slotTokens;
      }

      // Drop any remaining uncategorized items that weren't placed
      const selectedIds = new Set(selected.map(i => i.id));
      for (const item of uncategorized) {
        if (!selectedIds.has(item.id)) {
          dropped.push(item);
        }
      }

      // 3. Optimize for target model
      const optimized = optimizeForTarget(selected, target, slots);

      // 4. Validate constraints
      const diagnostics: CompileDiagnostic[] = validateConstraints(
        optimized.items,
        constraints,
        slots,
        budget
      );

      // Add diagnostics for unsatisfied slots
      for (const [slotName, stats] of Object.entries(slotStats)) {
        if (!stats.satisfied) {
          const slot = slots.find(s => s.name === slotName);
          if (slot?.required) {
            diagnostics.push({
              level: "error",
              slot: slotName,
              message: `Required slot "${slotName}" is not satisfied (${stats.itemCount} items, ${stats.tokensUsed} tokens)`,
            });
          }
        }
      }

      // 5. Compute quality metrics
      const quality = analyzeContext(optimized.items);

      // 6. Compute final total tokens
      const totalTokens = optimized.items.reduce(
        (sum, item) => sum + getItemTokens(item),
        0
      );

      return {
        items: optimized.items,
        dropped,
        totalTokens,
        diagnostics,
        optimizations: optimized.passes,
        target,
        slots: slotStats,
        quality,
      };
    },
  };
}
