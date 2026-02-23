import type { ContextItem, ItemScorer, ScoringWeights } from "./types";

const DEFAULT_WEIGHTS: Required<ScoringWeights> = {
  priority: 1.0,
  recency: 0.7,
  salience: 0.5,
};

/**
 * Create an item scorer with custom weights.
 *
 * @param weights - Custom scoring weights (defaults: priority=1.0, recency=0.7, salience=0.5)
 * @returns An ItemScorer function
 *
 * @example
 * ```ts
 * const scorer = createScorer({ priority: 2.0, recency: 0.0 });
 * const score = scorer(item);
 * ```
 */
export function createScorer(weights: ScoringWeights = {}): ItemScorer {
  const w = { ...DEFAULT_WEIGHTS, ...weights };

  return (item: ContextItem) => {
    if (typeof item.score === "number") return item.score;

    const priority = item.priority ?? 0;
    const recency = item.recency ?? 0;
    const salience =
      typeof item.metadata?.salience === "number"
        ? (item.metadata.salience as number)
        : 0;

    return priority * w.priority + recency * w.recency + salience * w.salience;
  };
}

/** Default item scorer using standard weights (priority=1.0, recency=0.7, salience=0.5). */
export const defaultItemScorer: ItemScorer = createScorer();
