import type {
  Budget,
  ContextItem,
  PackOptions,
  ScoringWeights,
} from "@context-engineering/core";
import { pack } from "@context-engineering/core";
import { InMemoryFeedbackStore } from "./store.js";
import type {
  FeedbackRecord,
  FeedbackStore,
  ItemFeature,
  OptimizerConfig,
  OptimizerState,
  OptimizedPack,
  Outcome,
  WeightInsights,
} from "./types.js";
import { WeightOptimizer } from "./weight-optimizer.js";

const DEFAULT_MIN_SAMPLES = 20;
const DEFAULT_LEARNING_RATE = 0.1;
const DEFAULT_REGULARIZATION = 0.01;
const DEFAULT_BASE_WEIGHTS: ScoringWeights = {
  priority: 1.0,
  recency: 1.0,
  salience: 1.0,
  relevance: 1.0,
};
const SCORING_DIMENSIONS = [
  "priority",
  "recency",
  "salience",
  "relevance",
] as const;

let idCounter = 0;

function generateId(): string {
  return `opt_${Date.now()}_${++idCounter}_${Math.random().toString(36).slice(2, 8)}`;
}

/**
 * Create a ContextOptimizer with the given configuration.
 * This is the primary entry point for adaptive context learning.
 */
export function createContextOptimizer(
  config: OptimizerConfig
): ContextOptimizer {
  return new ContextOptimizer(config);
}

/**
 * Adaptive context optimizer that learns which scoring weights
 * produce the best model outputs over time.
 */
export class ContextOptimizer {
  private store: FeedbackStore;
  private segment: string;
  private weightOptimizer: WeightOptimizer;
  private config: OptimizerConfig;
  private learnedWeights: ScoringWeights | null = null;

  constructor(config: OptimizerConfig) {
    this.config = config;
    this.store = config.store ?? new InMemoryFeedbackStore();
    this.segment = config.segment ?? "default";

    const baseWeights = config.baseWeights ?? DEFAULT_BASE_WEIGHTS;
    this.weightOptimizer = new WeightOptimizer({
      learningRate: config.learningRate ?? DEFAULT_LEARNING_RATE,
      regularization: config.regularization ?? DEFAULT_REGULARIZATION,
      baseWeights,
      minSamples: config.minSamples ?? DEFAULT_MIN_SAMPLES,
    });
  }

  /**
   * Pack items with learned weights.
   * Records feedback for later correlation analysis.
   */
  async pack(
    items: ContextItem[],
    budget: Budget,
    options?: PackOptions
  ): Promise<OptimizedPack> {
    const optimizerId = generateId();

    // Get current learned weights
    const learned = await this.getCurrentWeights();

    // Merge: user-provided weights override learned weights
    const mergedWeights = mergeWeights(learned, options?.weights);

    // Call the real pack() from ce-core
    const result = pack(items, budget, {
      ...options,
      weights: mergedWeights,
    });

    // Build item features for correlation analysis
    const itemFeatures = buildItemFeatures(items, result.selected);

    // Record feedback entry
    const record: FeedbackRecord = {
      id: generateId(),
      timestamp: Date.now(),
      packId: optimizerId,
      segment: this.segment,
      selectedItemIds: result.selected.map(i => i.id),
      droppedItemIds: result.dropped.map(i => i.id),
      itemFeatures,
      weightsUsed: mergedWeights,
      budget: budget.maxTokens,
      utilization:
        budget.maxTokens > 0 ? result.totalTokens / budget.maxTokens : 0,
    };

    await this.store.save(record);

    return {
      ...result,
      optimizerId,
      weightsUsed: mergedWeights,
    };
  }

  /**
   * Report the outcome of a previous pack operation.
   * This is how the optimizer learns which weights work.
   */
  async reportOutcome(optimizerId: string, outcome: Outcome): Promise<void> {
    // Validate at the boundary: a non-finite quality (NaN/Infinity from a
    // divide-by-zero metric or implicit-analysis score) would propagate through
    // correlation analysis and poison the learned weights, corrupting every
    // subsequent pack(). Reject it here so it never enters a FeedbackRecord.
    if (!Number.isFinite(outcome.quality)) {
      throw new RangeError(
        `Outcome.quality must be a finite number (0-1), got ${outcome.quality}`
      );
    }
    await this.store.updateOutcome(optimizerId, outcome);
    // Invalidate cached learned weights so next pack() recomputes
    this.learnedWeights = null;
  }

  /**
   * Get current learning insights including correlations,
   * recommended weights, and per-kind analysis.
   */
  async getInsights(): Promise<WeightInsights> {
    const records = await this.store.getRecordsWithOutcomes({
      segment: this.segment,
    });

    const correlations = this.weightOptimizer.computeCorrelations(records);
    const recommendedWeights = this.weightOptimizer.optimize(records);
    const confidence = this.weightOptimizer.computeConfidence(records);
    const kindInsights = this.weightOptimizer.computeKindInsights(records);

    return {
      currentWeights: await this.getCurrentWeights(),
      sampleCount: records.length,
      correlations: {
        priority: correlations.priority ?? 0,
        recency: correlations.recency ?? 0,
        salience: correlations.salience ?? 0,
        relevance: correlations.relevance ?? 0,
      },
      recommendedWeights,
      confidence,
      kindInsights,
    };
  }

  /**
   * Reset learned weights back to base weights.
   * Clears all feedback data for this segment.
   */
  async reset(): Promise<void> {
    await this.store.clear(this.segment);
    this.learnedWeights = null;
  }

  /**
   * Export current optimizer state for persistence or sharing.
   */
  async exportState(): Promise<OptimizerState> {
    const records = await this.store.getRecordsWithOutcomes({
      segment: this.segment,
    });

    return {
      weights: this.weightOptimizer.optimize(records),
      segment: this.segment,
      sampleCount: records.length,
      exportedAt: Date.now(),
    };
  }

  /**
   * Import previously exported optimizer state.
   * Sets learned weights directly without needing to replay feedback.
   */
  async importState(state: OptimizerState): Promise<void> {
    // Exported state can carry poisoned (non-finite) weights from a previously
    // corrupted optimizer. Reject them here so importing cannot reintroduce a
    // NaN/Infinity weight that would corrupt every pack().
    for (const dim of SCORING_DIMENSIONS) {
      const value = state.weights[dim];
      if (value !== undefined && !Number.isFinite(value)) {
        throw new RangeError(
          `OptimizerState.weights.${dim} must be a finite number, got ${value}`
        );
      }
    }
    this.learnedWeights = { ...state.weights };
  }

  /**
   * Get the current learned weights, computing from feedback if not cached.
   */
  private async getCurrentWeights(): Promise<ScoringWeights> {
    if (this.learnedWeights) {
      return { ...this.learnedWeights };
    }

    const records = await this.store.getRecordsWithOutcomes({
      segment: this.segment,
    });

    const weights = this.weightOptimizer.optimize(records);
    this.learnedWeights = weights;
    return { ...weights };
  }
}

/**
 * Merge learned weights with user-provided overrides.
 * User-provided values take precedence for explicitly set dimensions.
 */
function mergeWeights(
  learned: ScoringWeights,
  userOverrides?: ScoringWeights
): ScoringWeights {
  if (!userOverrides) {
    return { ...learned };
  }

  return {
    priority: userOverrides.priority ?? learned.priority,
    recency: userOverrides.recency ?? learned.recency,
    salience: userOverrides.salience ?? learned.salience,
    relevance: userOverrides.relevance ?? learned.relevance,
  };
}

/**
 * Build item-level features for correlation analysis.
 * Extracts scoring dimensions from each item and marks selection status.
 */
function buildItemFeatures(
  allItems: ContextItem[],
  selectedItems: ContextItem[]
): ItemFeature[] {
  const selectedIds = new Set(selectedItems.map(i => i.id));

  return allItems.map(item => ({
    itemId: item.id,
    kind: item.kind ?? "unknown",
    priority: item.priority ?? 0,
    recency: item.recency ?? 0,
    salience: (item.metadata?.salience as number) ?? 0,
    relevance: (item.metadata?.relevance as number) ?? 0,
    tokens: item.tokens ?? 0,
    selected: selectedIds.has(item.id),
  }));
}
