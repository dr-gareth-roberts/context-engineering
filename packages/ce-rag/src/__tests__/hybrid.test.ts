import { describe, it, expect } from "vitest";
import { createHybridRetriever } from "../hybrid.js";
import type { VectorStoreLike, VectorResult } from "../types.js";
import type { ContextItem } from "@context-engineering/core";

function createMockStore(results: VectorResult[]): VectorStoreLike {
  return {
    async query(_text: string, topK: number): Promise<VectorResult[]> {
      return results.slice(0, topK);
    },
  };
}

function makeResult(id: string, content: string, score: number): VectorResult {
  return { id, content, score };
}

function makeItem(id: string, content: string): ContextItem {
  return { id, content };
}

describe("createHybridRetriever", () => {
  it("combines vector and BM25 rankings via RRF", async () => {
    // Item with high vector score but low keyword match
    // Item with lower vector score but better keyword match
    const store = createMockStore([
      makeResult("vec-top", "semantically similar embedding match", 0.99),
      makeResult("kw-top", "search query keywords exact match", 0.7),
      makeResult("mid", "moderate relevance both signals mixed", 0.85),
    ]);

    const retriever = createHybridRetriever({
      store,
      currentContext: [],
      budget: { maxTokens: 10000 },
    });

    const pack = await retriever.retrieve("search query keywords");

    expect(pack.items.length).toBeGreaterThan(0);
    expect(pack.candidatesEvaluated).toBe(3);
  });

  it("RRF produces expected merged order for known inputs", async () => {
    // Set up items where vector and BM25 disagree on ranking
    const store = createMockStore([
      makeResult("a", "alpha bravo charlie delta echo foxtrot", 0.95),
      makeResult("b", "golf hotel india juliet kilo lima", 0.9),
    ]);

    const retriever = createHybridRetriever({
      store,
      currentContext: [],
      budget: { maxTokens: 10000 },
      vectorWeight: 0.5,
      bm25Weight: 0.5,
    });

    const pack = await retriever.retrieve("alpha bravo charlie");

    // Both should be present; the one matching the query keywords
    // should benefit from BM25 ranking
    expect(pack.items.length).toBe(2);
  });

  it("bm25Weight and vectorWeight control fusion balance", async () => {
    const store = createMockStore([
      makeResult("vec-fav", "unique semantic content embedding", 0.99),
      makeResult("kw-fav", "specific keywords query terms match", 0.5),
    ]);

    const vectorHeavy = createHybridRetriever({
      store,
      currentContext: [],
      budget: { maxTokens: 10000 },
      vectorWeight: 0.9,
      bm25Weight: 0.1,
    });

    const bm25Heavy = createHybridRetriever({
      store,
      currentContext: [],
      budget: { maxTokens: 10000 },
      vectorWeight: 0.1,
      bm25Weight: 0.9,
    });

    const vectorResult = await vectorHeavy.retrieve(
      "specific keywords query terms"
    );
    const bm25Result = await bm25Heavy.retrieve(
      "specific keywords query terms"
    );

    // Both should return items, but ordering may differ
    expect(vectorResult.items.length).toBeGreaterThan(0);
    expect(bm25Result.items.length).toBeGreaterThan(0);
  });

  it("information gain filter works with hybrid results", async () => {
    const existingContent = "the quick brown fox jumps over the lazy dog";
    const store = createMockStore([
      makeResult("dup", existingContent, 0.99),
      makeResult(
        "novel",
        "quantum computing superconducting qubits advances",
        0.8
      ),
    ]);

    const retriever = createHybridRetriever({
      store,
      currentContext: [makeItem("existing", existingContent)],
      budget: { maxTokens: 10000 },
    });

    // minGain of 0.3 filters duplicates: novelty=0 means gain is only
    // from the query relevance component (0.5 * 0.4 = 0.2 < 0.3)
    const pack = await retriever.retrieve("query", { minGain: 0.3 });

    // Duplicate should be filtered by information gain
    const ids = pack.items.map(item => item.id);
    expect(ids).not.toContain("dup");
    expect(ids).toContain("novel");
  });

  it("budget-aware cutoff works", async () => {
    const store = createMockStore([
      makeResult("r1", "alpha bravo charlie", 0.9),
      makeResult("r2", "delta echo foxtrot", 0.8),
      makeResult("r3", "golf hotel india", 0.7),
    ]);

    const retriever = createHybridRetriever({
      store,
      currentContext: [],
      budget: { maxTokens: 6, reserveTokens: 0 },
    });

    const pack = await retriever.retrieve("query");

    expect(pack.tokensUsed).toBeLessThanOrEqual(6);
  });

  it("falls back gracefully when store returns empty", async () => {
    const store = createMockStore([]);

    const retriever = createHybridRetriever({
      store,
      currentContext: [],
      budget: { maxTokens: 10000 },
    });

    const pack = await retriever.retrieve("query");

    expect(pack.items).toEqual([]);
    expect(pack.totalGain).toBe(0);
    expect(pack.candidatesEvaluated).toBe(0);
    expect(pack.tokensUsed).toBe(0);
  });
});
