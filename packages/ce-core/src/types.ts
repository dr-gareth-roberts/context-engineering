export interface Budget {
  maxTokens: number;
  reserveTokens?: number;
}

export interface Compression {
  content: string;
  tokens?: number;
  note?: string;
}

export interface ContextItem {
  id: string;
  content: string;
  kind?: string;
  priority?: number;
  recency?: number;
  tokens?: number;
  score?: number;
  metadata?: Record<string, unknown>;
  compressions?: Compression[];
  /** The BEADS task ID this item belongs to */
  taskId?: string;
  /** If true, this item represents a critical outcome/result of a task */
  isOutcome?: boolean;
  /** IDs of tasks this item depends on */
  dependsOn?: string[];
}

/**
 * Create a ContextItem with sensible defaults.
 *
 * Only `id` and `content` are required — all other fields are optional overrides.
 *
 * @example
 * ```ts
 * const item = createContextItem("readme", "# My Project\n...");
 * const withMeta = createContextItem("code", source, { kind: "code", priority: 10 });
 * ```
 */
export function createContextItem(
  id: string,
  content: string,
  overrides?: Partial<Omit<ContextItem, "id" | "content">>
): ContextItem {
  return { id, content, ...overrides };
}

export interface ContextPlan {
  budget: Budget;
  items: ContextItem[];
  strategy?: string;
  options?: Record<string, unknown>;
}

export interface ContextPack {
  budget: Budget;
  selected: ContextItem[];
  dropped: ContextItem[];
  totalTokens: number;
  stats?: Record<string, unknown>;
  notes?: string[];
}

export type TraceDecision = "include" | "exclude" | "compress";

export interface TraceStep {
  id: string;
  decision: TraceDecision;
  tokens?: number;
  score?: number;
  reason?: string;
  usedCompression?: boolean;
  compressedTokens?: number;
}

export interface ContextTrace {
  pack: ContextPack;
  steps: TraceStep[];
  createdAt: string;
}

export interface MemoryItem {
  id: string;
  content: string;
  createdAt: string;
  updatedAt?: string;
  salience?: number;
  ttlSeconds?: number;
  metadata?: Record<string, unknown>;
}

export interface TokenEstimator {
  (text: string, options?: { model?: string; provider?: string }): number;
}

export interface ItemScorer {
  (item: ContextItem): number;
}

export interface Summarizer {
  (item: ContextItem, targetTokens: number): ContextItem | null;
}

export interface ScoringWeights {
  priority?: number;
  recency?: number;
  salience?: number;
}

export interface PackOptions {
  tokenEstimator?: TokenEstimator;
  scorer?: ItemScorer;
  summarizer?: Summarizer;
  allowCompression?: boolean;
  weights?: ScoringWeights;
  logger?: import("./logger.js").Logger;
}

export interface PackDiff {
  added: ContextItem[];
  removed: ContextItem[];
  kept: ContextItem[];
  changed: Array<{ before: ContextItem; after: ContextItem }>;
}
