import type { ContextItem, ItemScorer, ScoringWeights } from "./types.js";
import type { BeadsIssue } from "./beads.js";

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
      typeof item.metadata?.salience === "number" ? item.metadata.salience : 0;

    return priority * w.priority + recency * w.recency + salience * w.salience;
  };
}

/** Default item scorer using standard weights (priority=1.0, recency=0.7, salience=0.5). */
export const defaultItemScorer: ItemScorer = createScorer();

/**
 * Create a causal graph-aware scorer based on BEADS issues.
 *
 * Uses task graph distance to prioritize items on the active path
 * and de-prioritize noise from closed or unrelated task branches.
 *
 * @param issues - The list of BEADS issues forming the task graph
 * @param activeTaskId - The ID of the currently active task
 * @param baseWeights - Standard scoring weights
 * @returns An ItemScorer function
 */
export function createCausalScorer(
  issues: BeadsIssue[],
  activeTaskId?: string,
  baseWeights: ScoringWeights = {}
): ItemScorer {
  const w = { ...DEFAULT_WEIGHTS, ...baseWeights };

  // Build a map for quick lookup
  const issueMap = new Map(issues.map(i => [i.id, i]));
  const activeIds = new Set(
    issues
      .filter(i => i.status === "open" || i.status === "in_progress")
      .map(i => i.id)
  );

  return (item: ContextItem) => {
    if (typeof item.score === "number") return item.score;

    const priority = item.priority ?? 0;
    const recency = item.recency ?? 0;
    const salience = (item.metadata?.salience as number) ?? 0;

    let multiplier = 1.0;

    // 1. Origin Protection: Pinned items or items explicitly marked as origin
    if (item.metadata?.isOrigin || item.metadata?.pinned) {
      multiplier = 2.0;
    }

    // 2. Graph-Aware Multiplier
    if (item.taskId) {
      const issue = issueMap.get(item.taskId);

      if (item.taskId === activeTaskId) {
        multiplier = 2.0; // Current active task
      } else if (item.isOutcome) {
        multiplier = 1.5; // Critical outcome of any task
      } else if (issue) {
        if (activeIds.has(item.taskId)) {
          multiplier = 1.2; // Other open tasks
        } else if (issue.status === "closed") {
          multiplier = 0.1; // Prune process noise from closed tasks
        }
      }
    }

    const baseScore =
      priority * w.priority + recency * w.recency + salience * w.salience;
    return baseScore * multiplier;
  };
}
