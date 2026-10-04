import {
  estimateTokens,
  analyzeContext,
  createQueryAwareScorer,
  createScorer,
} from "@context-engineering/core";
import type { ContextItem } from "@context-engineering/core";
import type {
  ContextProgram,
  CompileOptions,
  CompileResult,
  CompileDiagnostic,
  Slot,
  ContextCompiler,
} from "./types.js";
import type { ItemScorer, PackOptions } from "@context-engineering/core";
import { validateConstraints } from "./constraints.js";
import { optimizeForTarget } from "./optimizer.js";

function getItemTokens(
  item: ContextItem,
  tokenEstimator?: PackOptions["tokenEstimator"]
): number {
  // Explicit item.tokens wins, matching pack() in ce-core.
  return (
    item.tokens ?? estimateTokens(item.content, { estimator: tokenEstimator })
  );
}

function resolveScorer(
  items: ContextItem[],
  packOptions?: PackOptions
): ItemScorer | null {
  if (!packOptions) return null;
  if (packOptions.scorer) return packOptions.scorer;
  if (packOptions.query) {
    return createQueryAwareScorer(
      packOptions.query,
      packOptions.weights,
      items
    );
  }
  if (packOptions.weights) return createScorer(packOptions.weights);
  return null;
}

/**
 * Order slot candidates. An explicit slot `strategy` wins; otherwise
 * packOptions scoring (scorer / query / weights) is used when provided, and
 * "priority" is the default.
 */
function selectByStrategy(
  items: ContextItem[],
  slotStrategy: "priority" | "recency" | "relevance" | undefined,
  packOptions?: PackOptions
): ContextItem[] {
  const scorer = slotStrategy ? null : resolveScorer(items, packOptions);
  const strategy = slotStrategy ?? "priority";
  if (scorer) {
    const tokenEstimator = packOptions?.tokenEstimator;
    return [...items].sort((a, b) => {
      const scoreA = scorer({
        ...a,
        tokens: getItemTokens(a, tokenEstimator),
      });
      const scoreB = scorer({
        ...b,
        tokens: getItemTokens(b, tokenEstimator),
      });
      if (scoreB === scoreA) {
        return (b.recency ?? 0) - (a.recency ?? 0);
      }
      return scoreB - scoreA;
    });
  }

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
  const matchedItems = new WeakSet<ContextItem>();

  for (const slot of slots) {
    slotItems.set(slot.name, []);
  }

  for (const item of items) {
    for (const slot of slots) {
      if (item.kind === slot.kind) {
        const itemsForSlot = slotItems.get(slot.name);
        if (itemsForSlot) {
          itemsForSlot.push(item);
        }
        matchedItems.add(item);
        break;
      }
    }
  }

  const uncategorized = items.filter(item => !matchedItems.has(item));
  return { slotItems, uncategorized };
}

function slotProcessingOrder(slots: Slot[], fillRemaining: boolean): Slot[] {
  return slots
    .map((slot, index) => ({ slot, index }))
    .filter(entry => Boolean(entry.slot.fillRemaining) === fillRemaining)
    .sort((a, b) => {
      const requiredDelta =
        Number(b.slot.required === true) - Number(a.slot.required === true);
      return requiredDelta || a.index - b.index;
    })
    .map(entry => entry.slot);
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
      const { target, items, budget, packOptions } = options;
      const { slots, constraints } = program;
      const maxTokens = budget.maxTokens - (budget.reserveTokens ?? 0);
      const tokenEstimator = packOptions?.tokenEstimator;

      // 1. Categorize items into slots
      const { slotItems, uncategorized } = categorizeItems(items, slots);

      // 2. Select items per slot respecting budgets and strategies
      const selected: ContextItem[] = [];
      const dropped: ContextItem[] = [];
      const slotStats: Record<
        string,
        { itemCount: number; tokensUsed: number; satisfied: boolean }
      > = {};
      const selectedBySlot = new Map<string, ContextItem[]>();
      let usedTokens = 0;

      // First pass: non-fill slots. Required slots are processed first so
      // optional slots declared earlier cannot starve required context.
      for (const slot of slotProcessingOrder(slots, false)) {
        const candidates = slotItems.get(slot.name) ?? [];
        const sorted = selectByStrategy(candidates, slot.strategy, packOptions);

        const slotMaxTokens = slot.maxTokens ?? maxTokens;
        let slotTokens = 0;
        const slotSelected: ContextItem[] = [];

        for (const item of sorted) {
          const itemTokens = getItemTokens(item, tokenEstimator);
          if (
            usedTokens + slotTokens + itemTokens <= maxTokens &&
            slotTokens + itemTokens <= slotMaxTokens
          ) {
            slotSelected.push(item);
            slotTokens += itemTokens;
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

        selectedBySlot.set(slot.name, slotSelected);
        usedTokens += slotTokens;
      }

      // Second pass: fillRemaining slots get leftover budget + uncategorized items
      // Each uncategorized item may only be consumed by a single fillRemaining
      // slot; track which ones have already been placed so later slots exclude them.
      const uncategorizedItems = new WeakSet(uncategorized);
      const placedUncategorized = new WeakSet<ContextItem>();
      for (const slot of slotProcessingOrder(slots, true)) {
        const candidates = [
          ...(slotItems.get(slot.name) ?? []),
          ...uncategorized.filter(u => !placedUncategorized.has(u)),
        ];
        const sorted = selectByStrategy(candidates, slot.strategy, packOptions);

        const remainingBudget = maxTokens - usedTokens;
        const slotMaxTokens = slot.maxTokens
          ? Math.min(slot.maxTokens, remainingBudget)
          : remainingBudget;
        let slotTokens = 0;
        const slotSelected: ContextItem[] = [];

        for (const item of sorted) {
          const itemTokens = getItemTokens(item, tokenEstimator);
          if (
            slotTokens + itemTokens <= slotMaxTokens &&
            usedTokens + slotTokens + itemTokens <= maxTokens
          ) {
            slotSelected.push(item);
            slotTokens += itemTokens;
            // An uncategorized item consumed here must not be re-offered to a
            // later fillRemaining slot, which would duplicate it in `selected`.
            if (uncategorizedItems.has(item)) {
              placedUncategorized.add(item);
            }
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

        selectedBySlot.set(slot.name, slotSelected);
        usedTokens += slotTokens;
      }

      // Preserve declared slot order in the selected layout even though required
      // slots may have been processed earlier for budget priority.
      for (const slot of slots) {
        selected.push(...(selectedBySlot.get(slot.name) ?? []));
      }

      // 3. Optimize for target model
      const optimized = optimizeForTarget(
        selected,
        target,
        slots,
        tokenEstimator
      );

      // Compute dropped after all selection and optimization passes so an item
      // cannot appear in both result.items and dropped. Use object identity:
      // duplicate IDs can represent distinct caller-provided items.
      const finalSelected = new WeakSet(optimized.items);
      for (const item of items) {
        if (!finalSelected.has(item)) {
          dropped.push(item);
        }
      }

      // 4. Validate constraints
      const diagnostics: CompileDiagnostic[] = validateConstraints(
        optimized.items,
        constraints,
        slots,
        budget,
        tokenEstimator
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
        (sum, item) => sum + getItemTokens(item, tokenEstimator),
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
