import type { Logger } from "./logger.js";
import type { RedundancyOptions } from "./redundancy.js";

export interface Budget {
  maxTokens: number;
  reserveTokens?: number;
}

export interface QueryContext {
  text: string;
  keywords?: string[];
  embedding?: number[];
}

export type QueryInput = string | QueryContext;

export interface EmbeddingProvider {
  embed(texts: string[]): Promise<number[][]>;
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
  embedding?: number[];
  /** The BEADS task ID this item belongs to */
  taskId?: string;
  /** If true, this item represents a critical outcome/result of a task */
  isOutcome?: boolean;
  /** IDs of tasks this item depends on */
  dependsOn?: string[];
  /** ID of the item this one supersedes (replaces) */
  supersedes?: string;
  /** ID of the parent item for hierarchical inclusion */
  parentId?: string;
  /** Cost in dollars to produce this item */
  cost?: number;
  /** Latency in milliseconds to produce this item */
  latency?: number;
  /** Related URLs or resource identifiers */
  links?: string[];
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
  lastAccessedAt?: string;
  isSummary?: boolean;
  embedding?: number[];
  links?: string[];
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

/** Async summarizer for LLM-based compaction. Used by compileAsync(). */
export interface AsyncSummarizer {
  (item: ContextItem, targetTokens: number): Promise<ContextItem | null>;
}

export interface ScoringWeights {
  priority?: number;
  recency?: number;
  salience?: number;
  relevance?: number;
}

export interface PackOptions {
  tokenEstimator?: TokenEstimator;
  scorer?: ItemScorer;
  summarizer?: Summarizer;
  allowCompression?: boolean;
  weights?: ScoringWeights;
  logger?: Logger;
  redundancyConfig?: RedundancyOptions;
  query?: QueryInput;
  embeddingProvider?: EmbeddingProvider;
}

export interface ContextPlan {
  budget: Budget;
  items: ContextItem[];
  strategy?: string;
  options?: Record<string, unknown>;
}

export interface PackDiff {
  added: ContextItem[];
  removed: ContextItem[];
  kept: ContextItem[];
  changed: Array<{ before: ContextItem; after: ContextItem }>;
}
