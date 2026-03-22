import type { ContextPack } from "@context-engineering/core";

/** A function that summarizes dropped messages into a single string. */
export type SummarizeFunction = (
  messages: DroppedMessage[]
) => Promise<string>;

/** Strategy for handling context overflow. */
export type ContextStrategy = "trim" | "summarize" | SummarizeFunction;

/** Represents a message that was dropped during context packing. */
export interface DroppedMessage {
  role: string;
  content: string;
  tokens: number;
  index: number;
}

/** Event emitted after each intercepted call. */
export interface ContextEvent {
  /** Timestamp of the event */
  timestamp: number;
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
  /** The full pack result, if requested */
  pack?: ContextPack;
}

/** Listener for context events. */
export type ContextEventListener = (event: ContextEvent) => void;

/** Options for the SDK interceptor. */
export interface InterceptorOptions {
  /**
   * Token budget override. If not set, uses the model's known context window
   * from MODEL_METADATA minus a reserve for the response.
   */
  budget?: number;

  /**
   * Tokens to reserve for the model's response.
   * @default 4096
   */
  reserveTokens?: number;

  /**
   * Strategy for handling context overflow.
   * - `'trim'` (default): Drop lowest-scored older messages, keep system + recent
   * - `'summarize'`: Replace dropped messages with a summary
   * - Custom function: Your own summarization logic
   * @default 'trim'
   */
  strategy?: ContextStrategy;

  /**
   * Whether to log a one-line summary to console after each call.
   * @default true
   */
  log?: boolean;

  /**
   * Priority assigned to the system message (highest by default).
   * @default 100
   */
  systemPriority?: number;

  /**
   * Number of recent user/assistant messages to always keep (protected from trimming).
   * @default 2
   */
  recentMessageCount?: number;

  /**
   * Include the full ContextPack in emitted events (for debugging).
   * @default false
   */
  includePack?: boolean;

  /**
   * Event listeners for structured observability.
   */
  on?: {
    pack?: ContextEventListener;
    trim?: ContextEventListener;
    error?: (error: unknown) => void;
  };
}

/** Internal resolved config with defaults applied. */
export interface ResolvedConfig {
  budget: number | undefined;
  reserveTokens: number;
  strategy: ContextStrategy;
  log: boolean;
  systemPriority: number;
  recentMessageCount: number;
  includePack: boolean;
  on: {
    pack?: ContextEventListener;
    trim?: ContextEventListener;
    error?: (error: unknown) => void;
  };
}

export function resolveConfig(options: InterceptorOptions = {}): ResolvedConfig {
  return {
    budget: options.budget,
    reserveTokens: options.reserveTokens ?? 4096,
    strategy: options.strategy ?? "trim",
    log: options.log ?? true,
    systemPriority: options.systemPriority ?? 100,
    recentMessageCount: options.recentMessageCount ?? 2,
    includePack: options.includePack ?? false,
    on: options.on ?? {},
  };
}
