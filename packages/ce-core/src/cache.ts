import type { TokenEstimator } from "./types.js";

interface CacheOptions {
  maxSize?: number;
}

/**
 * Create a cached token estimator using an LRU cache.
 *
 * Wraps an existing estimator with content-keyed caching to avoid
 * redundant estimation of the same text.
 *
 * @param estimator - The base token estimator to wrap
 * @param options - Cache options (maxSize defaults to 1000)
 * @returns A cached TokenEstimator
 *
 * @example
 * ```ts
 * import { createCachedEstimator } from "@ce/core";
 * import { openaiTokenEstimator } from "@ce/providers";
 *
 * const cached = createCachedEstimator(openaiTokenEstimator, { maxSize: 500 });
 * pack(items, budget, { tokenEstimator: cached });
 * ```
 */
export function createCachedEstimator(
  estimator: TokenEstimator,
  options: CacheOptions = {}
): TokenEstimator {
  const maxSize = options.maxSize ?? 1000;
  const cache = new Map<string, number>();

  return (text: string, opts?: { model?: string; provider?: string }) => {
    const key =
      opts?.model || opts?.provider
        ? `${text}\0${opts.model ?? ""}\0${opts.provider ?? ""}`
        : text;
    if (cache.has(key)) {
      return cache.get(key)!;
    }

    const result = estimator(text, opts);

    if (cache.size >= maxSize) {
      const firstKey = cache.keys().next().value;
      if (firstKey !== undefined) {
        cache.delete(firstKey);
      }
    }

    cache.set(key, result);
    return result;
  };
}
