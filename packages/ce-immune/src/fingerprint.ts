import type { ContextItem, Budget } from "@context-engineering/core";
import type { Fingerprint } from "./types.js";

/**
 * Compute basic statistics for a numeric array.
 * Returns zeroed stats for empty input.
 */
export function computeStats(values: number[]): {
  min: number;
  max: number;
  mean: number;
  std: number;
} {
  if (values.length === 0) {
    return { min: 0, max: 0, mean: 0, std: 0 };
  }

  let min = values[0];
  let max = values[0];
  let sum = 0;

  for (const v of values) {
    if (v < min) min = v;
    if (v > max) max = v;
    sum += v;
  }

  const mean = sum / values.length;

  let varianceSum = 0;
  for (const v of values) {
    const diff = v - mean;
    varianceSum += diff * diff;
  }
  const std = Math.sqrt(varianceSum / values.length);

  return { min, max, mean, std };
}

/**
 * Extract a set of words from content, lowercased and deduplicated.
 */
function wordSet(content: string): Set<string> {
  const words = content.toLowerCase().split(/\s+/).filter(Boolean);
  return new Set(words);
}

/**
 * Compute Jaccard similarity between two sets.
 */
function jaccardSimilarity(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 && b.size === 0) return 1;

  let intersectionSize = 0;
  const smaller = a.size <= b.size ? a : b;
  const larger = a.size <= b.size ? b : a;

  for (const word of smaller) {
    if (larger.has(word)) intersectionSize++;
  }

  const unionSize = a.size + b.size - intersectionSize;
  if (unionSize === 0) return 1;
  return intersectionSize / unionSize;
}

/**
 * Extract a feature vector (fingerprint) from a set of context items.
 * All values are normalized to 0-1 or small ranges for fair comparison.
 */
export function extractFingerprint(
  items: ContextItem[],
  budget?: Budget
): Fingerprint {
  if (items.length === 0) {
    return {
      kindsPresent: [],
      kindRatios: {},
      priorityStats: { min: 0, max: 0, mean: 0, std: 0 },
      recencyStats: { min: 0, max: 0, mean: 0, std: 0 },
      tokenUtilization: 0,
      itemCount: 0,
      stalenessRatio: 0,
      redundancyEstimate: 0,
    };
  }

  // Kinds
  const kindCounts: Record<string, number> = {};
  for (const item of items) {
    const kind = item.kind ?? "unknown";
    kindCounts[kind] = (kindCounts[kind] ?? 0) + 1;
  }
  const kindsPresent = Object.keys(kindCounts).sort();
  const kindRatios: Record<string, number> = {};
  for (const [kind, count] of Object.entries(kindCounts)) {
    kindRatios[kind] = count / items.length;
  }

  // Priority and recency distributions
  const priorities = items.map(item => item.priority ?? 0.5);
  const recencies = items.map(item => item.recency ?? 0.5);
  const priorityStats = computeStats(priorities);
  const recencyStats = computeStats(recencies);

  // Token utilization
  let totalTokens = 0;
  for (const item of items) {
    totalTokens += item.tokens ?? Math.ceil(item.content.length / 4);
  }
  const maxTokens = budget?.maxTokens ?? totalTokens;
  const tokenUtilization =
    maxTokens > 0 ? Math.min(totalTokens / maxTokens, 1) : 0;

  // Staleness ratio: fraction of items with recency < 0.2
  let staleCount = 0;
  for (const item of items) {
    if ((item.recency ?? 0.5) < 0.2) staleCount++;
  }
  const stalenessRatio = staleCount / items.length;

  // Redundancy estimate: fraction of items with >0.8 Jaccard overlap
  // Cap at first 50 items for performance
  const capped = items.slice(0, 50);
  const wordSets = capped.map(item => wordSet(item.content));
  const redundantItems = new Set<number>();

  for (let i = 0; i < wordSets.length; i++) {
    for (let j = i + 1; j < wordSets.length; j++) {
      if (jaccardSimilarity(wordSets[i], wordSets[j]) > 0.8) {
        redundantItems.add(i);
        redundantItems.add(j);
      }
    }
  }
  const redundancyEstimate =
    capped.length > 0 ? redundantItems.size / capped.length : 0;

  return {
    kindsPresent,
    kindRatios,
    priorityStats,
    recencyStats,
    tokenUtilization,
    itemCount: items.length,
    stalenessRatio,
    redundancyEstimate,
  };
}

/**
 * Compute cosine similarity between two kindRatio vectors.
 * Keys not present in one vector are treated as 0.
 */
function kindRatioCosineSimilarity(
  a: Record<string, number>,
  b: Record<string, number>
): number {
  const allKeys = new Set([...Object.keys(a), ...Object.keys(b)]);
  if (allKeys.size === 0) return 1;

  let dotProduct = 0;
  let normA = 0;
  let normB = 0;

  for (const key of allKeys) {
    const va = a[key] ?? 0;
    const vb = b[key] ?? 0;
    dotProduct += va * vb;
    normA += va * va;
    normB += vb * vb;
  }

  const denominator = Math.sqrt(normA) * Math.sqrt(normB);
  if (denominator === 0) return 1;
  return dotProduct / denominator;
}

/**
 * Compute normalized Euclidean distance similarity for stats objects.
 * Returns 1 - normalized distance, clamped to [0, 1].
 */
function statsSimilarity(
  a: { min: number; max: number; mean: number; std: number },
  b: { min: number; max: number; mean: number; std: number }
): number {
  const diffs = [a.min - b.min, a.max - b.max, a.mean - b.mean, a.std - b.std];
  let sumSq = 0;
  for (const d of diffs) {
    sumSq += d * d;
  }
  // Max possible distance per dimension is 1 (since values are 0-1 range),
  // so max total distance is sqrt(4) = 2
  const distance = Math.sqrt(sumSq);
  const normalized = distance / 2;
  return Math.max(0, 1 - normalized);
}

/**
 * Compare two fingerprints and return a 0-1 similarity score.
 * Uses a weighted average of dimension-level similarities.
 */
export function compareFingerprints(a: Fingerprint, b: Fingerprint): number {
  // Weights for each dimension
  const weights = {
    kindRatios: 0.2,
    priorityStats: 0.15,
    recencyStats: 0.15,
    tokenUtilization: 0.15,
    itemCount: 0.1,
    stalenessRatio: 0.1,
    redundancyEstimate: 0.15,
  };

  const kindSim = kindRatioCosineSimilarity(a.kindRatios, b.kindRatios);
  const prioritySim = statsSimilarity(a.priorityStats, b.priorityStats);
  const recencySim = statsSimilarity(a.recencyStats, b.recencyStats);
  const tokenSim = 1 - Math.abs(a.tokenUtilization - b.tokenUtilization);
  const itemCountSim =
    Math.max(a.itemCount, b.itemCount) > 0
      ? 1 -
        Math.abs(a.itemCount - b.itemCount) / Math.max(a.itemCount, b.itemCount)
      : 1;
  const stalenessSim = 1 - Math.abs(a.stalenessRatio - b.stalenessRatio);
  const redundancySim =
    1 - Math.abs(a.redundancyEstimate - b.redundancyEstimate);

  return (
    weights.kindRatios * kindSim +
    weights.priorityStats * prioritySim +
    weights.recencyStats * recencySim +
    weights.tokenUtilization * tokenSim +
    weights.itemCount * itemCountSim +
    weights.stalenessRatio * stalenessSim +
    weights.redundancyEstimate * redundancySim
  );
}
