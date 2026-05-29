import type {
  Budget,
  ContextItem,
  ContextPack,
  PackOptions,
  TraceStep,
} from "./types.js";
import {
  createScorer,
  createQueryAwareScorer,
  defaultItemScorer,
} from "./score.js";
import { estimateTokens } from "./estimate.js";
import { eliminateRedundancy, eliminateRedundancySync } from "./redundancy.js";
import { enrichWithEmbeddings, normalizeQuery } from "./relevance.js";
import { EstimationError } from "./errors.js";
import { validatePackInputs } from "./schemas.js";
import { noopLogger } from "./logger.js";

interface PackResult {
  pack: ContextPack;
  steps?: TraceStep[];
}

function applyCompression(
  item: ContextItem,
  remainingTokens: number,
  options: PackOptions
): { item: ContextItem; usedCompression: boolean } | null {
  if (!options.allowCompression) return null;

  const compressions = item.compressions ?? [];
  const summarizer = options.summarizer;

  // Resolve token counts for all compressions, then sort descending (largest first).
  // We pick the largest compression that fits to maximize content quality.
  const withTokens = compressions.map(compression => ({
    ...compression,
    tokens:
      compression.tokens ??
      estimateTokens(compression.content, {
        estimator: options.tokenEstimator,
      }),
  }));
  const sorted = withTokens.sort((a, b) => b.tokens - a.tokens);

  for (const compression of sorted) {
    if (compression.tokens <= remainingTokens) {
      return {
        item: {
          ...item,
          content: compression.content,
          tokens: compression.tokens,
          metadata: {
            ...item.metadata,
            compressionNote: compression.note ?? "compression",
          },
        },
        usedCompression: true,
      };
    }
  }

  if (summarizer) {
    const summary = summarizer(item, remainingTokens);
    if (summary) {
      const tokens =
        summary.tokens ??
        estimateTokens(summary.content, { estimator: options.tokenEstimator });
      if (tokens <= remainingTokens) {
        return {
          item: { ...summary, tokens },
          usedCompression: true,
        };
      }
    }
  }

  return null;
}

/**
 * Pack context items into a token budget using greedy score-based selection.
 *
 * Items are scored (default: priority*1.0 + recency*0.7 + salience*0.5),
 * sorted by score, and greedily selected until the budget is exhausted.
 * If compression is enabled, oversized items may be compressed to fit.
 *
 * @param items - Context items to pack
 * @param budget - Token budget with maxTokens and optional reserveTokens
 * @param options - Packing options (custom scorer, estimator, compression, weights)
 * @returns A ContextPack with selected items, dropped items, and stats
 * @throws {ValidationError} If items or budget fail validation
 * @throws {BudgetExceededError} If reserveTokens >= maxTokens
 * @throws {EstimationError} If token estimation fails
 *
 * @example
 * ```ts
 * const result = pack(
 *   [{ id: "doc", content: "Hello world", priority: 5 }],
 *   { maxTokens: 1000 }
 * );
 * ```
 */

/**
 * Async version of pack that supports async operations like redundancy elimination.
 */
export async function packAsync(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions = {}
): Promise<ContextPack> {
  const result = await internalPackAsync(items, budget, options);
  return result.pack;
}

export function pack(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions = {}
): ContextPack {
  return internalPack(items, budget, options).pack;
}

export async function internalPackAsync(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions = {},
  trace = false
): Promise<PackResult> {
  // Validate before eliminateRedundancy and enrichWithEmbeddings, both of which
  // consume item.content. internalPack re-validates the filtered/enriched items
  // (harmless double-validation), but validating here ensures off-type content
  // throws the documented ValidationError rather than a raw TypeError.
  validatePackInputs(items, budget);

  let processedItems = items;
  let processedOptions = options;

  if (options.redundancyConfig) {
    processedItems = await eliminateRedundancy(items, options.redundancyConfig);
  }

  // Enrich with embeddings if an embedding provider and query are present
  if (options.embeddingProvider && options.query) {
    const query = normalizeQuery(options.query);
    const enriched = await enrichWithEmbeddings(
      processedItems,
      query,
      options.embeddingProvider
    );
    processedItems = enriched.items;
    processedOptions = { ...options, query: enriched.query };
  }

  return internalPack(processedItems, budget, processedOptions, trace);
}

export function internalPack(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions = {},
  trace = false
): PackResult {
  // Validate inputs before any code path that consumes item.content (e.g.
  // redundancy tokenization), so off-type content surfaces as the documented
  // ValidationError instead of a raw TypeError.
  validatePackInputs(items, budget);

  // Sync Jaccard redundancy elimination when no embedding provider is configured
  if (options.redundancyConfig && !options.redundancyConfig.embeddingProvider) {
    items = eliminateRedundancySync(items, options.redundancyConfig);
  }

  const scorer =
    options.scorer ??
    (options.query
      ? createQueryAwareScorer(options.query, options.weights, items)
      : options.weights
        ? createScorer(options.weights)
        : defaultItemScorer);
  const tokenEstimator = options.tokenEstimator;
  const maxTokens = budget.maxTokens - (budget.reserveTokens ?? 0);

  const logger = options.logger ?? noopLogger;
  logger.info("pack:start", {
    itemCount: items.length,
    maxTokens,
    reserveTokens: budget.reserveTokens,
  });

  const scoredItems = items.map(item => {
    let tokens: number;
    try {
      tokens =
        item.tokens ??
        estimateTokens(item.content, { estimator: tokenEstimator });
    } catch (err) {
      throw new EstimationError(
        `Failed to estimate tokens for item "${item.id}": ${err instanceof Error ? err.message : String(err)}`
      );
    }
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
  const selected: ContextItem[] = [];
  const dropped: ContextItem[] = [];
  const steps: TraceStep[] = [];

  for (const item of sorted) {
    if ((item.tokens ?? 0) <= remaining) {
      selected.push(item);
      remaining -= item.tokens ?? 0;
      if (trace) {
        steps.push({
          id: item.id,
          decision: "include",
          tokens: item.tokens,
          score: item.score,
          reason: "fits_budget",
        });
      }
      continue;
    }

    const compressed = applyCompression(item, remaining, {
      ...options,
      tokenEstimator,
    });

    if (compressed) {
      selected.push(compressed.item);
      remaining -= compressed.item.tokens ?? 0;
      if (trace) {
        steps.push({
          id: item.id,
          decision: "compress",
          tokens: item.tokens,
          compressedTokens: compressed.item.tokens,
          score: item.score,
          usedCompression: true,
          reason: "compressed_to_fit",
        });
      }
    } else {
      dropped.push(item);
      if (trace) {
        steps.push({
          id: item.id,
          decision: "exclude",
          tokens: item.tokens,
          score: item.score,
          reason: "over_budget",
        });
      }
    }
  }

  logger.info("pack:complete", {
    selectedCount: selected.length,
    droppedCount: dropped.length,
  });

  const totalTokens = selected.reduce(
    (sum, item) => sum + (item.tokens ?? 0),
    0
  );

  const packResult: ContextPack = {
    budget,
    selected,
    dropped,
    totalTokens,
    stats: {
      remainingTokens: Math.max(0, maxTokens - totalTokens),
      selectedCount: selected.length,
      droppedCount: dropped.length,
    },
  };

  return trace ? { pack: packResult, steps } : { pack: packResult };
}
