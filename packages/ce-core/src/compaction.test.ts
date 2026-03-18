import { describe, expect, it } from "vitest";
import { createContextManager } from "./compaction.js";
import type { ContextItem, TokenEstimator } from "./types.js";

/** Deterministic estimator: 1 token per word */
const wordEstimator: TokenEstimator = (text: string) => {
  const trimmed = text.trim();
  if (!trimmed) return 0;
  return trimmed.split(/\s+/).length;
};

describe("createContextManager", () => {
  it("tracks turns via addTurn and turnCount", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 1000 },
      tokenEstimator: wordEstimator,
    });

    expect(ctx.turnCount()).toBe(0);

    ctx.addTurn({ role: "user", content: "hello world" });
    expect(ctx.turnCount()).toBe(1);

    ctx.addTurn({ role: "assistant", content: "hi there" });
    expect(ctx.turnCount()).toBe(2);
  });

  it("tracks token usage via getTokenUsage", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 100 },
      tokenEstimator: wordEstimator,
    });

    ctx.addTurn({ role: "user", content: "one two three" }); // 3 tokens
    ctx.addTurn({ role: "assistant", content: "four five" }); // 2 tokens

    const usage = ctx.getTokenUsage();
    expect(usage.used).toBe(5);
    expect(usage.budget).toBe(100);
    expect(usage.remaining).toBe(95);
  });

  it("compile returns all turns when within budget", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 1000 },
      preserveRecentTurns: 10,
      tokenEstimator: wordEstimator,
    });

    ctx.addTurn({ role: "user", content: "hello" });
    ctx.addTurn({ role: "assistant", content: "world" });

    const result = ctx.compile();
    expect(result.turns).toHaveLength(2);
    expect(result.turns[0].role).toBe("user");
    expect(result.turns[0].content).toBe("hello");
    expect(result.turns[1].role).toBe("assistant");
    expect(result.turns[1].content).toBe("world");
    expect(result.totalTokens).toBe(2); // 1 + 1
  });

  it("compile compacts old turns when over summarizeAfterTurns threshold", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 500 },
      summarizeAfterTurns: 3,
      preserveRecentTurns: 2,
      tokenEstimator: wordEstimator,
    });

    // Add 5 turns — older 3 should be compacted, last 2 preserved
    ctx.addTurn({ role: "user", content: "first message" });
    ctx.addTurn({ role: "assistant", content: "first reply" });
    ctx.addTurn({ role: "user", content: "second message" });
    ctx.addTurn({ role: "assistant", content: "second reply" });
    ctx.addTurn({ role: "user", content: "third message" });

    const result = ctx.compile();

    // Last 2 turns should be preserved verbatim
    const lastTwo = result.turns.slice(-2);
    expect(lastTwo[0].content).toBe("second reply");
    expect(lastTwo[1].content).toBe("third message");

    // Older turns should be compacted into a summary
    const summaryTurn = result.turns[0];
    expect(summaryTurn.isSummary).toBe(true);
    expect(summaryTurn.content).toContain("Summary of 3 earlier turns");
  });

  it("preserveRecentTurns always keeps last N turns verbatim", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 500 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 3,
      tokenEstimator: wordEstimator,
    });

    ctx.addTurn({ role: "user", content: "alpha" });
    ctx.addTurn({ role: "assistant", content: "beta" });
    ctx.addTurn({ role: "user", content: "gamma" });
    ctx.addTurn({ role: "assistant", content: "delta" });
    ctx.addTurn({ role: "user", content: "epsilon" });

    const result = ctx.compile();
    const lastThree = result.turns.slice(-3);
    expect(lastThree[0].content).toBe("gamma");
    expect(lastThree[1].content).toBe("delta");
    expect(lastThree[2].content).toBe("epsilon");
  });

  it("addItems includes context items in compile output", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 1000 },
      preserveRecentTurns: 10,
      tokenEstimator: wordEstimator,
    });

    ctx.addTurn({ role: "user", content: "hello" });

    const contextItems: ContextItem[] = [
      { id: "doc1", content: "some context information", tokens: 3 },
      { id: "doc2", content: "more context", tokens: 2 },
    ];
    ctx.addItems(contextItems);

    const result = ctx.compile();
    expect(result.items).toHaveLength(2);
    expect(result.items.map(i => i.id)).toContain("doc1");
    expect(result.items.map(i => i.id)).toContain("doc2");
    expect(result.totalTokens).toBe(6); // 1 turn token + 3 + 2 item tokens
  });

  it("clear resets everything", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 1000 },
      tokenEstimator: wordEstimator,
    });

    ctx.addTurn({ role: "user", content: "hello" });
    ctx.addItems([{ id: "x", content: "data", tokens: 5 }]);
    expect(ctx.turnCount()).toBe(1);

    ctx.clear();

    expect(ctx.turnCount()).toBe(0);
    const usage = ctx.getTokenUsage();
    expect(usage.used).toBe(0);

    const result = ctx.compile();
    expect(result.turns).toHaveLength(0);
    expect(result.items).toHaveLength(0);
    expect(result.totalTokens).toBe(0);
  });

  it("system prompt tokens are accounted for in budget", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 10 },
      systemPrompt: "you are a helpful assistant", // 5 tokens
      preserveRecentTurns: 10,
      tokenEstimator: wordEstimator,
    });

    const usage = ctx.getTokenUsage();
    expect(usage.used).toBe(5);
    expect(usage.remaining).toBe(5);

    // Add a turn that uses 3 tokens
    ctx.addTurn({ role: "user", content: "one two three" });

    const usage2 = ctx.getTokenUsage();
    expect(usage2.used).toBe(8);
    expect(usage2.remaining).toBe(2);

    const result = ctx.compile();
    // totalTokens should include system prompt
    expect(result.totalTokens).toBe(8); // 5 system + 3 turn
  });

  it("respects reserveTokens in the budget", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 100, reserveTokens: 30 },
      tokenEstimator: wordEstimator,
    });

    const usage = ctx.getTokenUsage();
    expect(usage.budget).toBe(70); // 100 - 30
    expect(usage.remaining).toBe(70);
  });

  it("items are sorted by score and packed greedily", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 20 },
      preserveRecentTurns: 10,
      tokenEstimator: wordEstimator,
    });

    ctx.addTurn({ role: "user", content: "hi" }); // 1 token

    ctx.addItems([
      { id: "low", content: "low score item", tokens: 8, score: 1 },
      { id: "high", content: "high score item", tokens: 8, score: 10 },
      { id: "mid", content: "mid score item", tokens: 8, score: 5 },
    ]);

    const result = ctx.compile();
    // Budget is 20, turn uses 1, so 19 available for items
    // High (8) + mid (8) = 16 fit, low (8) would push to 24 — dropped
    expect(result.items.map(i => i.id)).toEqual(["high", "mid"]);
  });

  it("does not compact when fewer turns than summarizeAfterTurns", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 500 },
      summarizeAfterTurns: 10,
      preserveRecentTurns: 2,
      tokenEstimator: wordEstimator,
    });

    ctx.addTurn({ role: "user", content: "first" });
    ctx.addTurn({ role: "assistant", content: "second" });
    ctx.addTurn({ role: "user", content: "third" });
    ctx.addTurn({ role: "assistant", content: "fourth" });

    const result = ctx.compile();
    // 2 older + 2 recent = 4 turns, all included as-is (no summary)
    expect(result.turns).toHaveLength(4);
    expect(result.turns.every(t => !t.isSummary)).toBe(true);
  });
});

describe("compileAsync", () => {
  it("calls asyncSummarizer for older turns when provided", async () => {
    const calls: string[] = [];
    const ctx = createContextManager({
      budget: { maxTokens: 200 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 1,
      asyncSummarizer: async (item, _targetTokens) => {
        calls.push(item.content);
        return { ...item, content: "summary", tokens: 5 };
      },
    });
    for (let i = 0; i < 5; i++) {
      ctx.addTurn({
        role: "user",
        content: `turn content number ${i} with enough words to matter`,
      });
    }
    const result = await ctx.compileAsync();
    expect(calls.length).toBeGreaterThan(0);
    expect(result.totalTokens).toBeLessThanOrEqual(200);
  });

  it("batches older turns: batchSize controls grouping", async () => {
    let callCount = 0;
    const ctx = createContextManager({
      budget: { maxTokens: 2000 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 1,
      batchSize: 3,
      asyncSummarizer: async (item, _target) => {
        callCount++;
        return { ...item, content: `batch summary ${callCount}`, tokens: 10 };
      },
    });
    // Add 10 turns: 1 preserved (recent), 9 older = 3 batches of 3
    for (let i = 0; i < 10; i++) {
      ctx.addTurn({ role: "user", content: `turn ${i}` });
    }
    await ctx.compileAsync();
    expect(callCount).toBe(3);
  });

  it("falls back to truncation when asyncSummarizer returns null", async () => {
    const ctx = createContextManager({
      budget: { maxTokens: 200 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 1,
      asyncSummarizer: async () => null,
    });
    for (let i = 0; i < 5; i++) {
      ctx.addTurn({ role: "user", content: `turn ${i} content here` });
    }
    const result = await ctx.compileAsync();
    expect(result.turns.length).toBeGreaterThan(0);
  });

  it("falls back to truncation when asyncSummarizer result exceeds budget", async () => {
    const ctx = createContextManager({
      budget: { maxTokens: 100 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 1,
      asyncSummarizer: async (item, _target) => {
        return { ...item, content: "x".repeat(500), tokens: 999 };
      },
    });
    for (let i = 0; i < 5; i++) {
      ctx.addTurn({ role: "user", content: `turn ${i}` });
    }
    const result = await ctx.compileAsync();
    expect(result.totalTokens).toBeLessThanOrEqual(100);
  });

  it("sync compile does not call asyncSummarizer", () => {
    const ctx = createContextManager({
      budget: { maxTokens: 200 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 1,
      asyncSummarizer: async () => {
        throw new Error("should not be called in sync");
      },
    });
    for (let i = 0; i < 5; i++) {
      ctx.addTurn({ role: "user", content: `turn ${i}` });
    }
    expect(() => ctx.compile()).not.toThrow();
  });

  it("compileAsync without asyncSummarizer uses truncation (same as sync)", async () => {
    const ctx = createContextManager({
      budget: { maxTokens: 200 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 1,
    });
    for (let i = 0; i < 5; i++) {
      ctx.addTurn({ role: "user", content: `turn ${i}` });
    }
    const syncResult = ctx.compile();
    const asyncResult = await ctx.compileAsync();
    expect(asyncResult.totalTokens).toBe(syncResult.totalTokens);
  });

  it("falls back to truncation on asyncSummarizer error", async () => {
    const ctx = createContextManager({
      budget: { maxTokens: 200 },
      summarizeAfterTurns: 2,
      preserveRecentTurns: 1,
      asyncSummarizer: async () => {
        throw new Error("LLM API down");
      },
    });
    for (let i = 0; i < 5; i++) {
      ctx.addTurn({ role: "user", content: `turn ${i} with more words` });
    }
    const result = await ctx.compileAsync();
    expect(result.turns.length).toBeGreaterThan(0);
  });
});
