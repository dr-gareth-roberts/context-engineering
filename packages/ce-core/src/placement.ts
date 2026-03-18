import type { ContextItem } from "./types.js";
import { PlacementOptionsSchema, validateWithSchema } from "./schemas.js";

/**
 * Attention profile for a model family.
 * Values represent relative attention strength at each position bucket (0-1).
 * Positions are normalized: 0.0 = start of context, 1.0 = end.
 */
export interface AttentionProfile {
  /** Model family name */
  name: string;
  /** Effective context limit as fraction of advertised (e.g., 0.65 = use only 65%) */
  effectiveCapacity: number;
  /** Attention weights at position buckets [start...end] */
  positionWeights: number[];
}

/**
 * Built-in attention profiles based on research.
 * From "Lost in the Middle" (Liu et al. 2023) and "Context Rot" (Hong et al. 2025).
 */
export const ATTENTION_PROFILES: Record<string, AttentionProfile> = {
  // Claude models: strong primacy, moderate recency, weaker middle
  claude: {
    name: "claude",
    effectiveCapacity: 0.7,
    positionWeights: [1.0, 0.85, 0.65, 0.55, 0.5, 0.5, 0.55, 0.65, 0.8, 0.95],
  },
  // GPT-4 family: strong recency bias
  gpt4: {
    name: "gpt4",
    effectiveCapacity: 0.65,
    positionWeights: [0.9, 0.75, 0.6, 0.5, 0.45, 0.45, 0.5, 0.6, 0.8, 1.0],
  },
  // Default: balanced U-shape
  default: {
    name: "default",
    effectiveCapacity: 0.7,
    positionWeights: [0.95, 0.8, 0.65, 0.55, 0.5, 0.5, 0.55, 0.65, 0.8, 0.95],
  },
};

export type PlacementStrategy = "score-order" | "attention-optimized";

export interface PlacementOptions {
  /** Placement strategy (default: "score-order") */
  strategy?: PlacementStrategy;
  /** Model family for attention profile (default: "default") */
  model?: string;
  /** Custom attention profile (overrides model) */
  profile?: AttentionProfile;
}

/**
 * Reorder selected items for optimal attention placement.
 *
 * With "attention-optimized": places highest-priority items at positions
 * where the model pays most attention (typically start and end),
 * and lower-priority items in the middle.
 *
 * @param items - Items already selected by pack(), in score order
 * @param options - Placement strategy and model profile
 * @returns Items reordered for optimal attention
 *
 * @example
 * ```ts
 * const packed = await pack(items, budget);
 * packed.selected = placeItems(packed.selected, {
 *   strategy: "attention-optimized",
 *   model: "claude"
 * });
 * ```
 */
export function placeItems(
  items: ContextItem[],
  options?: PlacementOptions
): ContextItem[] {
  if (options) {
    validateWithSchema(PlacementOptionsSchema, options, "placement options");
  }

  const strategy = options?.strategy ?? "score-order";
  if (strategy === "score-order" || items.length <= 2) return [...items];

  const profile =
    options?.profile ??
    ATTENTION_PROFILES[options?.model ?? "default"] ??
    ATTENTION_PROFILES.default;

  // Score each position bucket
  const n = items.length;
  const bucketCount = profile.positionWeights.length;

  // Assign positions: highest-scored items go to highest-attention positions
  const sortedByScore = items
    .map((item, originalIndex) => ({
      item,
      originalIndex,
      score: item.score ?? 0,
    }))
    .sort((a, b) => b.score - a.score);

  // Get attention weight for each output position
  const positionAttention = Array.from({ length: n }, (_, i) => {
    const bucketIndex = Math.min(
      Math.floor((i / n) * bucketCount),
      bucketCount - 1
    );
    return { position: i, attention: profile.positionWeights[bucketIndex] };
  });

  // Sort positions by attention (highest attention first)
  positionAttention.sort((a, b) => b.attention - a.attention);

  // Assign highest-scored items to highest-attention positions
  const result = new Array<ContextItem>(n);
  for (let i = 0; i < n; i++) {
    result[positionAttention[i].position] = sortedByScore[i].item;
  }

  return result;
}

/**
 * Get the effective token budget for a model, accounting for context degradation.
 *
 * @param advertisedTokens - The model's advertised context window
 * @param model - Model family name
 * @returns Recommended effective token limit
 *
 * @example
 * ```ts
 * const budget = effectiveBudget(128000, "claude");
 * console.log(budget); // 89600
 * ```
 */
export function effectiveBudget(
  advertisedTokens: number,
  model?: string
): number {
  const profile =
    ATTENTION_PROFILES[model ?? "default"] ?? ATTENTION_PROFILES.default;
  return Math.floor(advertisedTokens * profile.effectiveCapacity);
}
