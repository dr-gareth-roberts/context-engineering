import { analyzeContext } from "@context-engineering/core";
import { estimateTokens } from "@context-engineering/core";
import type { ContextItem } from "@context-engineering/core";
import type { ComplexityBreakdown, ComplexityWeights } from "./types.js";

const DEFAULT_WEIGHTS: Required<ComplexityWeights> = {
  diversity: 0.25,
  density: 0.2,
  dependencyDepth: 0.2,
  toolCallCount: 0.15,
  multilinguality: 0.1,
  averageItemLength: 0.1,
};

/**
 * Unicode script detection patterns.
 * Each regex matches a range of characters belonging to a script family.
 */
const SCRIPT_PATTERNS: RegExp[] = [
  /[\u0041-\u024F]/, // Latin
  /[\u4E00-\u9FFF]/, // CJK (Chinese/Japanese/Korean unified ideographs)
  /[\u0600-\u06FF]/, // Arabic
  /[\u0400-\u04FF]/, // Cyrillic
  /[\u0900-\u097F]/, // Devanagari
  /[\u3040-\u309F]/, // Hiragana
  /[\u30A0-\u30FF]/, // Katakana
  /[\uAC00-\uD7AF]/, // Hangul
  /[\u0E00-\u0E7F]/, // Thai
  /[\u0590-\u05FF]/, // Hebrew
];

/**
 * Count the number of distinct Unicode script blocks present in text.
 */
function countScripts(text: string): number {
  let count = 0;
  for (const pattern of SCRIPT_PATTERNS) {
    if (pattern.test(text)) {
      count++;
    }
  }
  return count;
}

/**
 * Walk dependsOn chains to find the maximum dependency depth across all items.
 */
function computeMaxDependencyDepth(items: ContextItem[]): number {
  const itemMap = new Map<string, ContextItem>();
  for (const item of items) {
    itemMap.set(item.id, item);
  }

  const depthCache = new Map<string, number>();

  function getDepth(id: string, visited: Set<string>): number {
    if (depthCache.has(id)) {
      return depthCache.get(id) ?? 0;
    }
    if (visited.has(id)) {
      return 0; // cycle detection
    }

    const item = itemMap.get(id);
    if (!item?.dependsOn?.length) {
      depthCache.set(id, 0);
      return 0;
    }

    visited.add(id);
    let maxChildDepth = 0;
    for (const depId of item.dependsOn) {
      const childDepth = getDepth(depId, visited);
      maxChildDepth = Math.max(maxChildDepth, childDepth);
    }
    visited.delete(id);

    const depth = maxChildDepth + 1;
    depthCache.set(id, depth);
    return depth;
  }

  let maxDepth = 0;
  for (const item of items) {
    const depth = getDepth(item.id, new Set());
    maxDepth = Math.max(maxDepth, depth);
  }

  return maxDepth;
}

/**
 * Analyze the complexity of a set of context items.
 *
 * Computes six dimensions of complexity using heuristics (no ML required),
 * then combines them with configurable weights into an overall score in [0, 1].
 */
export function analyzeComplexity(
  items: ContextItem[],
  weights?: ComplexityWeights
): ComplexityBreakdown {
  if (items.length === 0) {
    return {
      overall: 0,
      dimensions: {
        diversity: 0,
        density: 0,
        dependencyDepth: 0,
        toolCallCount: 0,
        multilinguality: 0,
        averageItemLength: 0,
      },
    };
  }

  const w: Required<ComplexityWeights> = { ...DEFAULT_WEIGHTS, ...weights };

  // Get diversity and density from ce-core's analyzeContext
  const quality = analyzeContext(items);

  // dependencyDepth: max chain depth normalized by 10, clamped to [0,1]
  const maxDepth = computeMaxDependencyDepth(items);
  const dependencyDepth = Math.min(maxDepth / 10, 1);

  // toolCallCount: fraction of items with 'tool' in their kind
  const toolCount = items.filter(
    item => item.kind?.toLowerCase().includes("tool") ?? false
  ).length;
  const toolCallCount = Math.min(toolCount / items.length, 1);

  // multilinguality: count distinct Unicode script blocks across all content
  const allContent = items.map(item => item.content).join(" ");
  const scriptCount = countScripts(allContent);
  const multilinguality = Math.min((scriptCount - 1) / 4, 1);

  // averageItemLength: mean token count per item, normalized by 2000
  const totalTokens = items.reduce(
    (sum, item) => sum + estimateTokens(item.content),
    0
  );
  const meanTokens = totalTokens / items.length;
  const averageItemLength = Math.min(meanTokens / 2000, 1);

  const dimensions = {
    diversity: quality.diversity,
    density: quality.density,
    dependencyDepth,
    toolCallCount,
    multilinguality: Math.max(multilinguality, 0),
    averageItemLength,
  };

  // Weighted combination normalized to [0,1]
  const weightSum =
    w.diversity +
    w.density +
    w.dependencyDepth +
    w.toolCallCount +
    w.multilinguality +
    w.averageItemLength;

  const overall =
    weightSum > 0
      ? (dimensions.diversity * w.diversity +
          dimensions.density * w.density +
          dimensions.dependencyDepth * w.dependencyDepth +
          dimensions.toolCallCount * w.toolCallCount +
          dimensions.multilinguality * w.multilinguality +
          dimensions.averageItemLength * w.averageItemLength) /
        weightSum
      : 0;

  return {
    overall: Math.round(overall * 1000) / 1000,
    dimensions: {
      diversity: Math.round(dimensions.diversity * 1000) / 1000,
      density: Math.round(dimensions.density * 1000) / 1000,
      dependencyDepth: Math.round(dimensions.dependencyDepth * 1000) / 1000,
      toolCallCount: Math.round(dimensions.toolCallCount * 1000) / 1000,
      multilinguality: Math.round(dimensions.multilinguality * 1000) / 1000,
      averageItemLength: Math.round(dimensions.averageItemLength * 1000) / 1000,
    },
  };
}
