import type {
  ContextItem,
  ContextPack,
  ScoringWeights,
} from "@context-engineering/core";

export interface OptimizerConfig {
  /** How to collect feedback: 'implicit' (auto from response), 'explicit' (user signals), 'metric' (custom function) */
  feedback: "implicit" | "explicit" | "metric";
  /** Custom quality metric function (required when feedback='metric') */
  qualityMetric?: (
    response: string,
    context: ContextItem[]
  ) => number | Promise<number>;
  /** Minimum observations before adjusting weights */
  minSamples?: number;
  /** How aggressively to shift weights (0-1) */
  learningRate?: number;
  /** Regularization strength — pulls weights toward defaults to prevent overfitting */
  regularization?: number;
  /** Base weights to start from and regularize toward */
  baseWeights?: ScoringWeights;
  /** Where to persist feedback data */
  store?: FeedbackStore;
  /** Optional: segment learning by application/scenario */
  segment?: string;
}

export interface Outcome {
  /** Quality score 0-1 */
  quality: number;
  /** Did user accept/use the output? */
  accepted?: boolean;
  /** Response latency ms */
  latency?: number;
  /** The model's response text (for implicit analysis) */
  response?: string;
  /** Arbitrary metadata */
  metadata?: Record<string, unknown>;
}

export interface FeedbackRecord {
  id: string;
  timestamp: number;
  packId: string;
  segment: string;
  /** Which items were selected */
  selectedItemIds: string[];
  /** Which items were dropped */
  droppedItemIds: string[];
  /** Item-level features for correlation */
  itemFeatures: ItemFeature[];
  /** Weights used for this pack */
  weightsUsed: ScoringWeights;
  /** Budget used */
  budget: number;
  /** Token utilization (0-1) */
  utilization: number;
  /** Outcome (filled in later via reportOutcome) */
  outcome?: Outcome;
}

export interface ItemFeature {
  itemId: string;
  kind: string;
  priority: number;
  recency: number;
  salience: number;
  relevance: number;
  tokens: number;
  selected: boolean;
}

export interface WeightInsights {
  /** Current learned weights */
  currentWeights: ScoringWeights;
  /** How many observations contributed */
  sampleCount: number;
  /** Per-dimension correlation with quality */
  correlations: {
    priority: number;
    recency: number;
    salience: number;
    relevance: number;
  };
  /** What the optimizer recommends */
  recommendedWeights: ScoringWeights;
  /** Confidence level (0-1, based on sample size and variance) */
  confidence: number;
  /** Per-kind insights: which item kinds correlate with quality */
  kindInsights: Array<{
    kind: string;
    avgQualityWhenIncluded: number;
    avgQualityWhenExcluded: number;
    inclusionLift: number;
    count: number;
  }>;
}

export interface OptimizedPack extends ContextPack {
  /** Unique ID for reporting outcomes */
  optimizerId: string;
  /** Weights that were used */
  weightsUsed: ScoringWeights;
}

export interface OptimizerState {
  weights: ScoringWeights;
  segment: string;
  sampleCount: number;
  exportedAt: number;
}

export interface FeedbackStore {
  save(record: FeedbackRecord): Promise<void>;
  updateOutcome(packId: string, outcome: Outcome): Promise<void>;
  getRecords(options?: {
    segment?: string;
    limit?: number;
    since?: number;
  }): Promise<FeedbackRecord[]>;
  getRecordsWithOutcomes(options?: {
    segment?: string;
    limit?: number;
  }): Promise<FeedbackRecord[]>;
  clear(segment?: string): Promise<void>;
}
