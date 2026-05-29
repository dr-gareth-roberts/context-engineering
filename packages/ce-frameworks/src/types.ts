import type {
  ScoringWeights,
  ContextRecorder,
} from "@context-engineering/core";

/** A function that summarizes dropped messages into a single string. */
export type SummarizeFunction = (messages: DroppedMessage[]) => Promise<string>;

/** Strategy for handling context overflow. */
export type ContextStrategy = "trim" | "summarize" | SummarizeFunction;

/** Options for framework middleware adapters. */
export interface FrameworkMiddlewareOptions {
  /** Token budget in tokens (default: 128000). Not auto-detected from the model. */
  budget?: number;
  /** Tokens reserved for model response (default: 4096) */
  reserveTokens?: number;
  /** Trimming strategy (default: 'trim') */
  strategy?: ContextStrategy;
  /** Console logging (default: true) */
  log?: boolean;
  /** Priority for system messages (default: 100) */
  systemPriority?: number;
  /** Recent messages to protect from trimming (default: 2) */
  recentMessageCount?: number;
  /** Scoring weight overrides */
  weights?: ScoringWeights;
  /** Event listeners */
  on?: {
    pack?: (event: ContextEvent) => void;
    trim?: (event: ContextEvent) => void;
    error?: (error: unknown) => void;
  };
  /** Attach recorder for replay */
  recorder?: ContextRecorder;
}

/** Duck-typed message that all frameworks roughly share. */
export interface GenericMessage {
  role: string;
  content: string;
  [key: string]: unknown;
}

/** A message that was dropped during context packing. */
export interface DroppedMessage {
  role: string;
  content: string;
  tokens: number;
  index: number;
}

/** Event emitted after each framework interception. */
export interface ContextEvent {
  /** Timestamp of the event */
  timestamp: number;
  /** Source framework */
  framework: string;
  /** Model used for the call */
  model: string;
  /** Total messages before packing */
  totalMessages: number;
  /** Messages kept after packing */
  keptMessages: number;
  /** Messages trimmed */
  trimmedMessages: number;
  /** Whether a summary was injected */
  summarized: boolean;
  /** Tokens used after packing */
  tokensUsed: number;
  /** Token budget for the model */
  tokenBudget: number;
  /** Utilization percentage (0-100) */
  utilization: number;
  /** Time taken to pack (ms) */
  packTimeMs: number;
}

/** Internal resolved config with defaults applied. */
export interface ResolvedConfig {
  budget: number;
  reserveTokens: number;
  strategy: ContextStrategy;
  log: boolean;
  systemPriority: number;
  recentMessageCount: number;
  weights?: ScoringWeights;
  on: {
    pack?: (event: ContextEvent) => void;
    trim?: (event: ContextEvent) => void;
    error?: (error: unknown) => void;
  };
  recorder?: ContextRecorder;
}

/** Default token budget when none is specified and model is unknown. */
const DEFAULT_BUDGET = 128_000;

/** Resolve user options into a fully-populated config. */
export function resolveConfig(
  options: FrameworkMiddlewareOptions = {}
): ResolvedConfig {
  return {
    budget: options.budget ?? DEFAULT_BUDGET,
    reserveTokens: options.reserveTokens ?? 4096,
    strategy: options.strategy ?? "trim",
    log: options.log ?? true,
    systemPriority: options.systemPriority ?? 100,
    recentMessageCount: options.recentMessageCount ?? 2,
    weights: options.weights,
    on: options.on ?? {},
    recorder: options.recorder,
  };
}
