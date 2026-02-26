import type { Budget, ContextItem, PackOptions } from "./types.js";
import { BudgetSchema, ContextItemSchema } from "./schemas.js";
import { ValidationError, BudgetExceededError } from "./errors.js";
import { createScorer, defaultItemScorer } from "./score.js";
import { estimateTokens } from "./estimate.js";
import { z } from "zod";

/**
 * Stream-pack context items, yielding each selected item as it's chosen.
 *
 * Same greedy algorithm as pack() but yields items one at a time via
 * async generator. Useful for large item sets where you want to start
 * processing selected items before packing completes.
 *
 * @param items - Context items to pack
 * @param budget - Token budget
 * @param options - Packing options
 * @yields Selected ContextItems in score order
 * @throws {ValidationError} If items or budget fail validation
 * @throws {BudgetExceededError} If reserveTokens >= maxTokens
 *
 * @example
 * ```ts
 * for await (const item of packStream(items, { maxTokens: 4096 })) {
 *   console.log(`Selected: ${item.id}`);
 * }
 * ```
 */
export async function* packStream(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions = {}
): AsyncGenerator<ContextItem> {
  const budgetResult = BudgetSchema.safeParse(budget);
  if (!budgetResult.success) {
    throw new ValidationError(
      `Invalid budget: ${budgetResult.error.issues.map((i: z.ZodIssue) => i.message).join(", ")}`,
      budgetResult.error.issues.map((i: z.ZodIssue) => ({
        path: i.path.join("."),
        message: i.message,
      }))
    );
  }

  if (
    budget.reserveTokens !== undefined &&
    budget.reserveTokens >= budget.maxTokens
  ) {
    throw new BudgetExceededError(
      `reserveTokens (${budget.reserveTokens}) must be less than maxTokens (${budget.maxTokens})`
    );
  }

  const itemsResult = z.array(ContextItemSchema).safeParse(items);
  if (!itemsResult.success) {
    throw new ValidationError(
      `Invalid items: ${itemsResult.error.issues.map((i: z.ZodIssue) => i.message).join(", ")}`,
      itemsResult.error.issues.map((i: z.ZodIssue) => ({
        path: i.path.join("."),
        message: i.message,
      }))
    );
  }

  const scorer =
    options.scorer ??
    (options.weights ? createScorer(options.weights) : defaultItemScorer);
  const tokenEstimator = options.tokenEstimator;
  const maxTokens = budget.maxTokens - (budget.reserveTokens ?? 0);

  const scoredItems = items.map(item => {
    const tokens =
      item.tokens ??
      estimateTokens(item.content, { estimator: tokenEstimator });
    const score = scorer({ ...item, tokens });
    return { ...item, tokens, score };
  });

  const sorted = [...scoredItems].sort((a, b) => {
    if ((b.score ?? 0) === (a.score ?? 0)) {
      return (b.recency ?? 0) - (a.recency ?? 0);
    }
    return (b.score ?? 0) - (a.score ?? 0);
  });

  let remaining = Math.max(0, maxTokens);

  for (const item of sorted) {
    if ((item.tokens ?? 0) <= remaining) {
      remaining -= item.tokens ?? 0;
      yield item;
    }
  }
}
