import type { ContextItem, ContextPack } from "./types.js";
import { estimateTokens } from "./estimate.js";

/**
 * Quality metrics for a context pack or item set.
 */
export interface ContextQuality {
  /** Items analyzed */
  itemCount: number;
  /** Total tokens */
  totalTokens: number;
  /** Information density: unique words per token (0-1, higher = more dense) */
  density: number;
  /** Topic diversity: ratio of unique bigrams to total bigrams (0-1) */
  diversity: number;
  /** Freshness: fraction of items with recency > 0.5 (0-1) */
  freshness: number;
  /** Redundancy: estimated content overlap between items (0-1, lower = better) */
  redundancy: number;
  /** Overall quality score (weighted combination, 0-1) */
  overall: number;
}

/**
 * Analyze the quality of a set of context items.
 *
 * Computes density, diversity, freshness, and redundancy metrics
 * without requiring an LLM call — uses heuristic analysis.
 *
 * @param items - Context items to analyze
 * @returns Quality metrics including density, diversity, freshness, and redundancy
 *
 * @example
 * ```ts
 * const packed = await pack(items, budget);
 * const quality = analyzeContext(packed.selected);
 * console.log(quality.overall); // 0.82
 * if (quality.redundancy > 0.3) {
 *   console.warn("High redundancy — consider deduplication");
 * }
 * ```
 */
export function analyzeContext(items: ContextItem[]): ContextQuality {
  if (items.length === 0) {
    return {
      itemCount: 0,
      totalTokens: 0,
      density: 0,
      diversity: 0,
      freshness: 0,
      redundancy: 0,
      overall: 0,
    };
  }

  const totalTokens = items.reduce(
    (sum, item) => sum + (item.tokens ?? estimateTokens(item.content)),
    0
  );

  // Density: unique words / total tokens
  const allWords = items.flatMap(item =>
    item.content
      .toLowerCase()
      .split(/\s+/)
      .filter(w => w.length > 0)
  );
  const uniqueWords = new Set(allWords);
  const density = Math.min(uniqueWords.size / Math.max(totalTokens, 1), 1);

  // Diversity: unique bigrams / total bigrams
  const bigrams = new Set<string>();
  const totalBigrams = { count: 0 };
  for (const item of items) {
    const words = item.content
      .toLowerCase()
      .split(/\s+/)
      .filter(w => w.length > 0);
    for (let i = 0; i < words.length - 1; i++) {
      bigrams.add(`${words[i]} ${words[i + 1]}`);
      totalBigrams.count++;
    }
  }
  const diversity =
    totalBigrams.count > 0 ? Math.min(bigrams.size / totalBigrams.count, 1) : 0;

  // Freshness: fraction of items with recency > 5 (on 0-10 scale)
  const freshCount = items.filter(item => (item.recency ?? 0) > 5).length;
  const freshness = freshCount / items.length;

  // Redundancy: pairwise word overlap using Jaccard similarity
  let totalOverlap = 0;
  let pairCount = 0;
  const itemWordSets = items.map(
    item =>
      new Set(
        item.content
          .toLowerCase()
          .split(/\s+/)
          .filter(w => w.length > 2)
      )
  );
  for (let i = 0; i < itemWordSets.length; i++) {
    for (let j = i + 1; j < itemWordSets.length; j++) {
      const a = itemWordSets[i];
      const b = itemWordSets[j];
      let intersection = 0;
      a.forEach(word => {
        if (b.has(word)) intersection++;
      });
      const union = a.size + b.size - intersection;
      if (union > 0) {
        totalOverlap += intersection / union;
        pairCount++;
      }
    }
  }
  const redundancy = pairCount > 0 ? totalOverlap / pairCount : 0;

  // Overall: weighted combination
  const overall =
    Math.round(
      (density * 0.25 +
        diversity * 0.25 +
        freshness * 0.2 +
        (1 - redundancy) * 0.3) *
        100
    ) / 100;

  return {
    itemCount: items.length,
    totalTokens,
    density: Math.round(density * 1000) / 1000,
    diversity: Math.round(diversity * 1000) / 1000,
    freshness: Math.round(freshness * 1000) / 1000,
    redundancy: Math.round(redundancy * 1000) / 1000,
    overall,
  };
}

/**
 * Analyze a ContextPack directly.
 *
 * @param pack - The context pack to analyze
 * @returns Quality metrics for the pack's selected items
 *
 * @example
 * ```ts
 * const packed = await pack(items, { maxTokens: 4000 });
 * const quality = analyzeContextPack(packed);
 * console.log(quality.overall);
 * ```
 */
export function analyzeContextPack(pack: ContextPack): ContextQuality {
  return analyzeContext(pack.selected);
}
