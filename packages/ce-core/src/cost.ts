/**
 * Cost Estimation with Cache Savings
 *
 * Estimates actual API costs for context packs, with special support
 * for prefix caching savings. Given a CacheAwarePack, shows concrete
 * dollar amounts saved by cache-topology-aware packing.
 *
 * Pricing as of 2025-06 (per million tokens):
 * - Claude Opus 4.6:   $15 input, $1.50 cached input, $75 output
 * - Claude Sonnet 4.6: $3 input, $0.30 cached input, $15 output
 * - GPT-4.1:          $2 input, $0.50 cached input, $8 output
 * - GPT-4o:           $2.50 input, $1.25 cached input, $10 output
 */

import type { CacheAwarePack } from "./cache-topology.js";
import { ValidationError } from "./errors.js";

/**
 * Pricing per million tokens for a model.
 */
export interface ModelPricing {
  /** Cost per million input tokens */
  inputPerMillion: number;
  /** Cost per million cached input tokens (prefix cache hit) */
  cachedInputPerMillion: number;
  /** Cost per million output tokens */
  outputPerMillion: number;
}

/**
 * Cost estimate for a single request.
 */
export interface CostEstimate {
  /** Model used for pricing */
  model: string;
  /** Total input tokens */
  inputTokens: number;
  /** Tokens that hit the prefix cache */
  cachedTokens: number;
  /** Tokens that miss the cache (billed at full rate) */
  uncachedTokens: number;
  /** Estimated output tokens (for total cost) */
  outputTokens: number;
  /** Cost without caching (all tokens at full input price) */
  costWithoutCache: number;
  /** Cost with caching (cached tokens at reduced rate) */
  costWithCache: number;
  /** Dollar savings from caching */
  savings: number;
  /** Savings as percentage */
  savingsPercent: number;
  /** Cache efficiency (0-1) */
  cacheEfficiency: number;
}

/**
 * Cost projection over multiple requests.
 */
export interface CostProjection {
  /** Per-request estimates */
  perRequest: CostEstimate;
  /** Number of requests projected */
  requestCount: number;
  /** Total cost without caching */
  totalWithoutCache: number;
  /** Total cost with caching */
  totalWithCache: number;
  /** Total savings */
  totalSavings: number;
  /** Monthly projection at this request rate */
  monthlyEstimate?: {
    requestsPerDay: number;
    monthlyCostWithoutCache: number;
    monthlyCostWithCache: number;
    monthlySavings: number;
  };
}

/**
 * Known model pricing (approximate, check provider docs for current rates).
 */
export const MODEL_PRICING: Record<string, ModelPricing> = {
  // Anthropic
  "claude-opus-4-6": {
    inputPerMillion: 15,
    cachedInputPerMillion: 1.5,
    outputPerMillion: 75,
  },
  "claude-sonnet-4-6": {
    inputPerMillion: 3,
    cachedInputPerMillion: 0.3,
    outputPerMillion: 15,
  },
  "claude-haiku-4-5": {
    inputPerMillion: 0.8,
    cachedInputPerMillion: 0.08,
    outputPerMillion: 4,
  },

  // OpenAI
  "gpt-4.1": {
    inputPerMillion: 2,
    cachedInputPerMillion: 0.5,
    outputPerMillion: 8,
  },
  "gpt-4.1-mini": {
    inputPerMillion: 0.4,
    cachedInputPerMillion: 0.1,
    outputPerMillion: 1.6,
  },
  "gpt-4o": {
    inputPerMillion: 2.5,
    cachedInputPerMillion: 1.25,
    outputPerMillion: 10,
  },
  "o3": {
    inputPerMillion: 2,
    cachedInputPerMillion: 0.5,
    outputPerMillion: 8,
  },
  "o4-mini": {
    inputPerMillion: 1.1,
    cachedInputPerMillion: 0.275,
    outputPerMillion: 4.4,
  },
};

/**
 * Estimate the cost of a single API request using a cache-aware pack.
 *
 * @param pack - Cache-aware pack result from packWithCacheTopology
 * @param model - Model name for pricing lookup
 * @param outputTokens - Estimated output tokens (default: 500)
 * @param pricing - Custom pricing (overrides MODEL_PRICING lookup)
 *
 * @example
 * ```ts
 * const pack = packWithCacheTopology(items, budget, {}, { provider: "anthropic" });
 * const cost = estimateCost(pack, "claude-sonnet-4-6");
 * console.log(`Saving $${cost.savings.toFixed(4)} per request (${cost.savingsPercent.toFixed(1)}%)`);
 * ```
 */
export function estimateCost(
  pack: CacheAwarePack,
  model: string,
  outputTokens: number = 500,
  pricing?: ModelPricing,
): CostEstimate {
  const price = pricing ?? MODEL_PRICING[model];
  if (!price) {
    const known = Object.keys(MODEL_PRICING).join(", ");
    throw new ValidationError(
      `Unknown model "${model}". Known models: ${known}. Pass custom pricing for unlisted models.`,
      [{ path: "model", message: `Expected one of: ${known}` }],
    );
  }

  const cachedTokens = pack.cacheableTokens;
  const uncachedTokens = pack.volatileTokens;
  const totalInput = pack.totalTokens;

  const costWithoutCache =
    (totalInput / 1_000_000) * price.inputPerMillion +
    (outputTokens / 1_000_000) * price.outputPerMillion;

  const costWithCache =
    (cachedTokens / 1_000_000) * price.cachedInputPerMillion +
    (uncachedTokens / 1_000_000) * price.inputPerMillion +
    (outputTokens / 1_000_000) * price.outputPerMillion;

  const savings = costWithoutCache - costWithCache;

  return {
    model,
    inputTokens: totalInput,
    cachedTokens,
    uncachedTokens,
    outputTokens,
    costWithoutCache: Math.round(costWithoutCache * 1_000_000) / 1_000_000,
    costWithCache: Math.round(costWithCache * 1_000_000) / 1_000_000,
    savings: Math.round(savings * 1_000_000) / 1_000_000,
    savingsPercent: costWithoutCache > 0
      ? Math.round((savings / costWithoutCache) * 1000) / 10
      : 0,
    cacheEfficiency: pack.cacheEfficiency,
  };
}

/**
 * Project costs over multiple requests.
 *
 * @param pack - Cache-aware pack result
 * @param model - Model name
 * @param requestCount - Number of requests to project
 * @param options - Additional options (outputTokens, requestsPerDay for monthly)
 *
 * @example
 * ```ts
 * const projection = projectCosts(pack, "claude-sonnet-4-6", 1000, {
 *   requestsPerDay: 500,
 * });
 * console.log(`Monthly savings: $${projection.monthlyEstimate?.monthlySavings.toFixed(2)}`);
 * ```
 */
export function projectCosts(
  pack: CacheAwarePack,
  model: string,
  requestCount: number,
  options?: {
    outputTokens?: number;
    pricing?: ModelPricing;
    requestsPerDay?: number;
  },
): CostProjection {
  const perRequest = estimateCost(
    pack,
    model,
    options?.outputTokens ?? 500,
    options?.pricing,
  );

  const totalWithoutCache = perRequest.costWithoutCache * requestCount;
  const totalWithCache = perRequest.costWithCache * requestCount;

  const result: CostProjection = {
    perRequest,
    requestCount,
    totalWithoutCache: Math.round(totalWithoutCache * 100) / 100,
    totalWithCache: Math.round(totalWithCache * 100) / 100,
    totalSavings: Math.round((totalWithoutCache - totalWithCache) * 100) / 100,
  };

  if (options?.requestsPerDay) {
    const monthlyRequests = options.requestsPerDay * 30;
    result.monthlyEstimate = {
      requestsPerDay: options.requestsPerDay,
      monthlyCostWithoutCache: Math.round(perRequest.costWithoutCache * monthlyRequests * 100) / 100,
      monthlyCostWithCache: Math.round(perRequest.costWithCache * monthlyRequests * 100) / 100,
      monthlySavings: Math.round(perRequest.savings * monthlyRequests * 100) / 100,
    };
  }

  return result;
}
