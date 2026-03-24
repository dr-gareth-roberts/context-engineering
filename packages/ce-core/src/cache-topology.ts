/**
 * Cache-Topology-Aware Packing
 *
 * Structures context output to maximize prefix cache hits across API calls.
 * Anthropic: 90% cost reduction, 85% latency reduction with prefix caching.
 * OpenAI: 50% cost reduction, automatic for prompts >1024 tokens.
 *
 * The key insight: if items are always sorted by score, every request produces
 * a different prefix, destroying cache reuse. Instead, we partition items into
 * a stable prefix (deterministically ordered) and a volatile suffix (score-ordered).
 *
 * Based on: https://ankitbko.github.io/blog/2025/08/prompt-engineering-kv-cache/
 */

import type { Budget, ContextItem, ContextPack, PackOptions } from "./types.js";
import { pack, packAsync } from "./pack.js";
import { estimateTokens } from "./estimate.js";
import { hash64 } from "./hash.js";
import { CacheConfigSchema, validateWithSchema } from "./schemas.js";
import type { MaybeAsync } from "./maybe-async.js";
import { chain } from "./maybe-async.js";

/** Volatility level for cache partitioning. */
export type Volatility = "static" | "session" | "request";

/**
 * Provider-specific cache configuration.
 * Different providers have different prefix caching behaviors.
 */
export interface CacheConfig {
  /** Provider name for cache-specific behavior */
  provider?: "anthropic" | "openai" | "auto";
  /** Minimum prefix length for cache eligibility (tokens) */
  minPrefixTokens?: number;
  /** Whether to insert cache breakpoint markers in metadata */
  markBreakpoints?: boolean;
}

/**
 * Result of cache-aware packing, extending ContextPack with cache metadata.
 */
export interface CacheAwarePack extends ContextPack {
  /** Hash of the stable prefix — same hash = cache hit */
  cacheKey: string;
  /** Tokens in the stable prefix (cacheable across requests) */
  cacheableTokens: number;
  /** Tokens in the volatile suffix (changes per request) */
  volatileTokens: number;
  /** Cache efficiency: cacheableTokens / totalTokens */
  cacheEfficiency: number;
  /** Partition boundaries: [staticEnd, sessionEnd] */
  partitionBoundaries: number[];
}

/**
 * Assign a volatility level to an item based on its kind and metadata.
 *
 * Items are classified into three tiers:
 * - static: system prompts, tool definitions, few-shot examples (rarely change)
 * - session: conversation history, memory retrievals (change per session)
 * - request: current query, fresh RAG results (change every request)
 *
 * @param item - The context item to classify
 * @returns The volatility level: "static", "session", or "request"
 *
 * @example
 * ```ts
 * const v = classifyVolatility({ id: "sys", content: "...", kind: "system" });
 * console.log(v); // "static"
 * ```
 */
export function classifyVolatility(item: ContextItem): Volatility {
  // Explicit volatility in metadata takes precedence
  if (item.metadata?.volatility) {
    return item.metadata.volatility as Volatility;
  }

  const kind = item.kind?.toLowerCase() ?? "";

  // Static: system prompts, tools, schemas, examples, instructions
  if (
    kind === "system" ||
    kind === "tool" ||
    kind === "schema" ||
    kind === "example" ||
    kind === "instruction" ||
    kind === "few-shot"
  ) {
    return "static";
  }

  // Request: queries, retrieval results, tool results
  if (
    kind === "query" ||
    kind === "retrieval" ||
    kind === "tool-result" ||
    kind === "request"
  ) {
    return "request";
  }

  // Session: memory, conversation, history
  if (
    kind === "memory" ||
    kind === "conversation" ||
    kind === "history" ||
    kind === "session"
  ) {
    return "session";
  }

  // Default: items without explicit kind are request-level (volatile)
  return "request";
}

/** Function that packs items into a budget, returning sync or async. */
type PackFn = (
  items: ContextItem[],
  budget: Budget,
  options: PackOptions
) => MaybeAsync<ContextPack>;

/**
 * Shared implementation for both sync and async packWithCacheTopology.
 *
 * Uses MaybeAsync + chain() so the sync path never creates Promises,
 * while the async path chains naturally through .then().
 */
function packWithCacheTopologyImpl(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions,
  cacheConfig: CacheConfig,
  packFn: PackFn
): MaybeAsync<CacheAwarePack> {
  validateWithSchema(CacheConfigSchema, cacheConfig, "cacheConfig");

  const estimator = options.tokenEstimator;

  // 1. Classify items by volatility
  const staticItems: ContextItem[] = [];
  const sessionItems: ContextItem[] = [];
  const requestItems: ContextItem[] = [];

  for (const item of items) {
    const volatility = classifyVolatility(item);
    switch (volatility) {
      case "static":
        staticItems.push(item);
        break;
      case "session":
        sessionItems.push(item);
        break;
      case "request":
        requestItems.push(item);
        break;
    }
  }

  // 2. Sort static items deterministically by id (not by score)
  // This ensures the same items always produce the same prefix
  staticItems.sort((a, b) => a.id.localeCompare(b.id));

  // 3. Sort session items by recency (most recent last, for conversation order)
  sessionItems.sort((a, b) => (a.recency ?? 0) - (b.recency ?? 0));

  // 4. Pack within each partition using score-based selection
  const maxTokens = budget.maxTokens - (budget.reserveTokens ?? 0);
  let remaining = maxTokens;

  // Static items: include all that fit (they're high-value and cacheable)
  const selectedStatic: ContextItem[] = [];
  for (const item of staticItems) {
    const tokens = item.tokens ?? estimateTokens(item.content, { estimator });
    if (tokens <= remaining) {
      selectedStatic.push({ ...item, tokens });
      remaining -= tokens;
    }
  }

  // Session items: include by score within remaining budget
  const sessionPackResult: MaybeAsync<ContextPack> =
    remaining > 0
      ? packFn(sessionItems, { maxTokens: remaining }, options)
      : {
          selected: [],
          dropped: sessionItems,
          totalTokens: 0,
          budget,
          stats: {},
        };

  return chain(sessionPackResult, sessionPack => {
    remaining -= sessionPack.totalTokens;

    // Request items: pack by score into whatever's left
    const requestPackResult: MaybeAsync<ContextPack> =
      remaining > 0
        ? packFn(requestItems, { maxTokens: remaining }, options)
        : {
            selected: [],
            dropped: requestItems,
            totalTokens: 0,
            budget,
            stats: {},
          };

    return chain(requestPackResult, requestPack => {
      // 5. Compose final ordered list: static -> session -> request
      const selected = [
        ...selectedStatic,
        ...sessionPack.selected,
        ...requestPack.selected,
      ];

      const selectedStaticIds = new Set(selectedStatic.map(i => i.id));
      const dropped = [
        ...staticItems.filter(i => !selectedStaticIds.has(i.id)),
        ...sessionPack.dropped,
        ...requestPack.dropped,
      ];

      // 6. Add breakpoint markers if configured
      if (cacheConfig.markBreakpoints) {
        const staticEnd = selectedStatic.length;
        const sessionEnd = staticEnd + sessionPack.selected.length;

        if (staticEnd > 0 && staticEnd < selected.length) {
          selected[staticEnd - 1] = {
            ...selected[staticEnd - 1],
            metadata: {
              ...selected[staticEnd - 1].metadata,
              _cacheBreakpoint: "static-end",
            },
          };
        }
        if (sessionEnd > staticEnd && sessionEnd < selected.length) {
          selected[sessionEnd - 1] = {
            ...selected[sessionEnd - 1],
            metadata: {
              ...selected[sessionEnd - 1].metadata,
              _cacheBreakpoint: "session-end",
            },
          };
        }
      }

      // 7. Compute cache key from stable prefix content
      const staticContent = selectedStatic
        .map(i => `${i.id}:${i.content}`)
        .join("|");
      const cacheKey = hash64(staticContent);

      const staticTokens = selectedStatic.reduce(
        (sum, i) => sum + (i.tokens ?? 0),
        0
      );
      const totalTokens = selected.reduce((sum, i) => sum + (i.tokens ?? 0), 0);

      return {
        budget,
        selected,
        dropped,
        totalTokens,
        stats: {
          staticCount: selectedStatic.length,
          sessionCount: sessionPack.selected.length,
          requestCount: requestPack.selected.length,
          remainingTokens: Math.max(0, maxTokens - totalTokens),
        },
        cacheKey,
        cacheableTokens: staticTokens,
        volatileTokens: totalTokens - staticTokens,
        cacheEfficiency:
          totalTokens > 0
            ? Math.round((staticTokens / totalTokens) * 1000) / 1000
            : 0,
        partitionBoundaries: [
          selectedStatic.length,
          selectedStatic.length + sessionPack.selected.length,
        ],
      };
    });
  });
}

/**
 * Pack items with cache-topology awareness.
 *
 * Partitions items into stable prefix and volatile suffix to maximize
 * prefix cache hits across API calls. The stable prefix uses deterministic
 * ordering (by id) so the same items always produce the same prefix.
 *
 * @param items - Context items to pack (should have `kind` set for best results)
 * @param budget - Token budget
 * @param options - Standard pack options
 * @param cacheConfig - Cache-specific configuration
 * @returns CacheAwarePack with cache metadata
 *
 * @example
 * ```ts
 * const result = packWithCacheTopology(
 *   [
 *     { id: "sys", content: "You are helpful.", kind: "system", priority: 10 },
 *     { id: "doc", content: "Retrieved doc...", kind: "retrieval", priority: 7 },
 *     { id: "q", content: "User question", kind: "query", priority: 9 },
 *   ],
 *   { maxTokens: 4096 },
 *   {},
 *   { provider: "anthropic" }
 * );
 * console.log(result.cacheKey);        // stable across requests with same static items
 * console.log(result.cacheEfficiency);  // 0.0 - 1.0
 * ```
 */
export function packWithCacheTopology(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions = {},
  cacheConfig: CacheConfig = {}
): CacheAwarePack {
  return packWithCacheTopologyImpl(
    items,
    budget,
    options,
    cacheConfig,
    pack
  ) as CacheAwarePack;
}

/**
 * Async variant of packWithCacheTopology.
 *
 * Same logic as packWithCacheTopology but delegates to packAsync() internally,
 * supporting async operations like embedding-based redundancy elimination.
 *
 * @param items - Context items to pack (should have `kind` set for best results)
 * @param budget - Token budget
 * @param options - Standard pack options (supports embeddingProvider, redundancyConfig)
 * @param cacheConfig - Cache-specific configuration
 * @returns Promise<CacheAwarePack> with cache metadata
 */
export async function packWithCacheTopologyAsync(
  items: ContextItem[],
  budget: Budget,
  options: PackOptions = {},
  cacheConfig: CacheConfig = {}
): Promise<CacheAwarePack> {
  return packWithCacheTopologyImpl(
    items,
    budget,
    options,
    cacheConfig,
    packAsync
  ) as Promise<CacheAwarePack>;
}
