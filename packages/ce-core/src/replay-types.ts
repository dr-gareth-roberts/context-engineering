import type {
  ContextItem,
  Budget,
  ContextPack,
  PackOptions,
  ScoringWeights,
} from "./types.js";

/** A single recorded context packing event. */
export interface ContextRecording {
  /** Unique ID for this recording */
  id: string;
  /** Timestamp when the recording was captured */
  timestamp: string;
  /** Model string (e.g. "gpt-4o", "claude-sonnet-4-6") */
  model: string;
  /** The input items that were packed */
  items: ContextItem[];
  /** The budget used */
  budget: Budget;
  /** Pack options used (excluding non-serializable fields like scorer/summarizer) */
  options: SerializablePackOptions;
  /** The resulting pack */
  result: ContextPack;
  /** Optional: the model's response text, for quality comparison */
  response?: string;
  /** Optional: user-provided quality score (0-1) */
  qualityScore?: number;
  /** Optional metadata */
  metadata?: Record<string, unknown>;
}

/** Pack options that can be serialized to JSON (no functions). */
export interface SerializablePackOptions {
  allowCompression?: boolean;
  weights?: ScoringWeights;
  query?: string;
}

/** A strategy variant to test during replay. */
export interface ReplayVariant {
  /** Human-readable name for this variant */
  name: string;
  /** Override the budget */
  budget?: Budget;
  /** Override pack options */
  options?: Partial<PackOptions>;
}

/** Result of replaying a single recording with a single variant. */
export interface ReplayResult {
  /** The recording that was replayed */
  recordingId: string;
  /** The variant that was used */
  variantName: string;
  /** The new pack result */
  pack: ContextPack;
  /** Token difference from original (negative = saved tokens) */
  tokenDelta: number;
  /** Items that changed selection vs. original */
  selectionChanges: {
    newlySelected: string[];
    newlyDropped: string[];
  };
}

/** Aggregated results across all recordings for a single variant. */
export interface VariantSummary {
  /** Variant name */
  name: string;
  /** Individual replay results */
  results: ReplayResult[];
  /** Average token delta across all recordings */
  avgTokenDelta: number;
  /** Average utilization percentage */
  avgUtilization: number;
  /** How many recordings changed their selection */
  recordingsAffected: number;
}

/** Full replay report across all variants. */
export interface ReplayReport {
  /** When the replay was run */
  timestamp: string;
  /** Number of recordings replayed */
  recordingCount: number;
  /** Results per variant */
  variants: VariantSummary[];
}
