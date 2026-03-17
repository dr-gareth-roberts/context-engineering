import type { Budget, ContextItem, PackOptions } from "./types.js";
import { validatePackInputs } from "./schemas.js";
import { createScorer, defaultItemScorer } from "./score.js";
import { estimateTokens } from "./estimate.js";

/**
 * Stream-pack context items, yielding each selected item as it's chosen.
 *
 * Same greedy algorithm as pack() but yields items one at a time via
 * async generator. Useful for large item sets where you want to start
 * processing selected items before packing completes.
 *
 * Supports compression when `allowCompression` is set in options:
 * if an item exceeds the remaining budget, its compressions are tried
 * (largest fitting first), and a summarizer is consulted as a fallback.
 *
 * @param items - Context items to pack
 * @param budget - Token budget
 * @param options - Packing options (including allowCompression, summarizer)
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
  validatePackInputs(items, budget);

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
      continue;
    }

    // Attempt compression if enabled (C3 fix: match pack() behavior)
    if (options.allowCompression) {
      const compressed = tryCompress(item, remaining, options);
      if (compressed) {
        remaining -= compressed.tokens ?? 0;
        yield compressed;
      }
    }
  }
}

/**
 * Try to compress an item to fit within remainingTokens.
 * Picks the largest compression that fits (best quality).
 */
function tryCompress(
  item: ContextItem,
  remainingTokens: number,
  options: PackOptions
): ContextItem | null {
  const compressions = item.compressions ?? [];

  // Resolve tokens and sort descending (largest first = best quality)
  const withTokens = compressions.map(c => ({
    ...c,
    tokens:
      c.tokens ??
      estimateTokens(c.content, { estimator: options.tokenEstimator }),
  }));
  const sorted = withTokens.sort((a, b) => b.tokens - a.tokens);

  for (const compression of sorted) {
    if (compression.tokens <= remainingTokens) {
      return {
        ...item,
        content: compression.content,
        tokens: compression.tokens,
        metadata: {
          ...item.metadata,
          compressionNote: compression.note ?? "compression",
        },
      };
    }
  }

  // Fall back to summarizer
  if (options.summarizer) {
    const summary = options.summarizer(item, remainingTokens);
    if (summary) {
      const tokens =
        summary.tokens ??
        estimateTokens(summary.content, { estimator: options.tokenEstimator });
      if (tokens <= remainingTokens) {
        return { ...summary, tokens };
      }
    }
  }

  return null;
}
