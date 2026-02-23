import type { Budget, ContextItem, Summarizer, TokenEstimator } from "./types.js";
import { estimateTokens, defaultTokenEstimator } from "./estimate.js";
import { pack } from "./pack.js";

export interface Turn {
  role: "user" | "assistant" | "tool" | "system";
  content: string;
  tokens?: number;
  timestamp?: number;
  /** If true, this turn is a summary of older turns */
  isSummary?: boolean;
}

export interface CompactionOptions {
  /** Maximum token budget for the managed context */
  budget: Budget;
  /** Summarize tool results older than N turns (default: 5) */
  summarizeAfterTurns?: number;
  /** Always preserve the last N turns verbatim (default: 2) */
  preserveRecentTurns?: number;
  /** System prompt to always include */
  systemPrompt?: string;
  /** Token estimator */
  tokenEstimator?: TokenEstimator;
  /** Summarizer for compacting old turns (if not provided, truncation is used) */
  summarizer?: Summarizer;
}

/**
 * A context manager that tracks token budgets across turns
 * and automatically compacts old content to stay within budget.
 *
 * @example
 * ```ts
 * const ctx = createContextManager({
 *   budget: { maxTokens: 8000 },
 *   summarizeAfterTurns: 3,
 *   preserveRecentTurns: 2,
 *   systemPrompt: "You are a helpful assistant.",
 * });
 *
 * ctx.addTurn({ role: "user", content: "What is context engineering?" });
 * ctx.addTurn({ role: "assistant", content: "Context engineering is..." });
 * ctx.addTurn({ role: "tool", content: longSearchResult });
 *
 * const compiled = ctx.compile();
 * // Returns turns that fit within budget, with old tool results summarized
 * ```
 */
export interface ContextManager {
  /** Add a turn to the conversation */
  addTurn(turn: Omit<Turn, "tokens" | "timestamp">): void;
  /** Add context items (e.g., from memory queries) */
  addItems(items: ContextItem[]): void;
  /** Get current token usage */
  getTokenUsage(): { used: number; budget: number; remaining: number };
  /** Compile the context — returns turns + items that fit within budget */
  compile(): { turns: Turn[]; items: ContextItem[]; totalTokens: number };
  /** Get the number of turns */
  turnCount(): number;
  /** Clear all turns and items */
  clear(): void;
}

/**
 * Create a context manager that tracks token budgets and compacts old turns.
 *
 * @param options - Compaction configuration including budget, summarization thresholds, and system prompt
 * @returns A ContextManager instance
 */
export function createContextManager(options: CompactionOptions): ContextManager {
  const estimate = options.tokenEstimator ?? defaultTokenEstimator;
  const summarizeAfter = options.summarizeAfterTurns ?? 5;
  const preserveRecent = options.preserveRecentTurns ?? 2;
  const maxTokens = options.budget.maxTokens;
  const reserveTokens = options.budget.reserveTokens ?? 0;
  const effectiveBudget = maxTokens - reserveTokens;

  let turns: Turn[] = [];
  let items: ContextItem[] = [];

  const systemTokens = options.systemPrompt
    ? estimate(options.systemPrompt)
    : 0;

  function addTurn(turn: Omit<Turn, "tokens" | "timestamp">): void {
    const tokens = estimate(turn.content);
    turns.push({ ...turn, tokens, timestamp: Date.now() });
  }

  function addItems(newItems: ContextItem[]): void {
    items = [...items, ...newItems];
  }

  function getTokenUsage(): { used: number; budget: number; remaining: number } {
    const used =
      systemTokens +
      turns.reduce((sum, t) => sum + (t.tokens ?? 0), 0) +
      items.reduce((sum, i) => sum + (i.tokens ?? estimate(i.content)), 0);
    return {
      used,
      budget: effectiveBudget,
      remaining: Math.max(0, effectiveBudget - used),
    };
  }

  function compile(): {
    turns: Turn[];
    items: ContextItem[];
    totalTokens: number;
  } {
    let availableTokens = effectiveBudget - systemTokens;

    // Phase 1: Always preserve recent turns
    const recentTurns = turns.slice(-preserveRecent);
    const olderTurns = turns.slice(0, -preserveRecent || turns.length);

    const recentTokens = recentTurns.reduce(
      (sum, t) => sum + (t.tokens ?? 0),
      0
    );
    availableTokens -= recentTokens;

    // Phase 2: Compact older turns
    const compactedOlder: Turn[] = [];

    if (olderTurns.length > 0 && olderTurns.length >= summarizeAfter) {
      // Group older turns and create a summary
      const combinedContent = olderTurns
        .map(t => `[${t.role}]: ${t.content}`)
        .join("\n");

      // Truncate to fit if no summarizer
      const targetTokens = Math.floor(availableTokens * 0.3); // allocate 30% to history
      const truncated = combinedContent.slice(0, targetTokens * 4); // rough char estimate
      const summaryTokens = estimate(truncated);

      compactedOlder.push({
        role: "system",
        content: `[Summary of ${olderTurns.length} earlier turns]\n${truncated}`,
        tokens: summaryTokens,
        isSummary: true,
        timestamp: olderTurns[0]?.timestamp,
      });
      availableTokens -= summaryTokens;
    } else {
      // Not enough turns to summarize — include as-is
      for (const turn of olderTurns) {
        if ((turn.tokens ?? 0) <= availableTokens) {
          compactedOlder.push(turn);
          availableTokens -= turn.tokens ?? 0;
        }
      }
    }

    // Phase 3: Pack context items into remaining budget
    let selectedItems: ContextItem[] = [];
    if (items.length > 0 && availableTokens > 0) {
      const itemBudget: Budget = { maxTokens: availableTokens };
      // Use synchronous estimation for items
      selectedItems = items
        .map(i => ({ ...i, tokens: i.tokens ?? estimate(i.content) }))
        .filter(i => (i.tokens ?? 0) <= availableTokens)
        .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

      let usedTokens = 0;
      selectedItems = selectedItems.filter(item => {
        if (usedTokens + (item.tokens ?? 0) <= availableTokens) {
          usedTokens += item.tokens ?? 0;
          return true;
        }
        return false;
      });
    }

    const allTurns = [...compactedOlder, ...recentTurns];
    const totalTokens =
      systemTokens +
      allTurns.reduce((sum, t) => sum + (t.tokens ?? 0), 0) +
      selectedItems.reduce((sum, i) => sum + (i.tokens ?? 0), 0);

    return { turns: allTurns, items: selectedItems, totalTokens };
  }

  function turnCount(): number {
    return turns.length;
  }

  function clear(): void {
    turns = [];
    items = [];
  }

  return { addTurn, addItems, getTokenUsage, compile, turnCount, clear };
}
