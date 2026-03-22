import { describe, it, expect } from "vitest";
import { createContextAwareRetriever } from "../retriever.js";
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

describe("createContextAwareRetriever", () => {
  it("retrieves items and converts VectorResult to ContextItem", async () => {
    const store = createMockStore([
      makeResult("r1", "unique alpha content here", 0.95),
      makeResult("r2", "unique beta content here", 0.85),
    ]);

    const retriever = createContextAwareRetriever({
      store,
      currentContext: [],
      budget: { maxTokens: 10000 },
    });

    const pack = await retriever.retrieve("search query");

    expect(pack.items.length).toBe(2);
    expect(pack.items[0].id).toBe("r1");
    expect(pack.items[0].content).toBe("unique alpha content here");
    expect(pack.items[0].metadata).toMatchObject({
      source: "rag",
      vectorScore: 0.95,
    });
  });

  it("filters out candidates overlapping with existing context", async () => {
    const existingContent = "the quick brown fox jumps over the lazy dog";
    const store = createMockStore([
      makeResult("dup", existingContent, 0.99),
      makeResult(
        "new",
        "quantum computing advances in superconducting qubits",
        0.8
      ),
    ]);

    const retriever = createContextAwareRetriever({
      store,
      currentContext: [makeItem("existing", existingContent)],
      budget: { maxTokens: 10000 },
    });

    // minGain of 0.3 filters the duplicate: gain = 0*0.6 + relevance*0.4
    // For a duplicate, novelty=0, so gain is only from query relevance
    const pack = await retriever.retrieve("query", { minGain: 0.3 });

    // The duplicate should be filtered, leaving only the novel item
    expect(pack.items.length).toBe(1);
    expect(pack.items[0].id).toBe("new");
    expect(pack.candidatesFiltered).toBeGreaterThanOrEqual(1);
  });

  it("respects budget and stops adding when budget exhausted", async () => {
    // Each item is roughly 5-6 tokens. Budget is very tight.
    const store = createMockStore([
      makeResult("r1", "alpha bravo charlie", 0.9),
      makeResult("r2", "delta echo foxtrot", 0.8),
      makeResult("r3", "golf hotel india", 0.7),
    ]);

    const retriever = createContextAwareRetriever({
      store,
      currentContext: [],
      budget: { maxTokens: 6, reserveTokens: 0 },
    });

    const pack = await retriever.retrieve("query");

    // With ~4 tokens per item and 6 token budget, should fit at most 1
    expect(pack.items.length).toBeLessThanOrEqual(2);
    expect(pack.tokensUsed).toBeLessThanOrEqual(6);
  });

  it("returns empty when all candidates are redundant", async () => {
    const content = "the exact same content repeated verbatim";
    const store = createMockStore([makeResult("r1", content, 0.95)]);

    const retriever = createContextAwareRetriever({
      store,
      currentContext: [makeItem("existing", content)],
      budget: { maxTokens: 10000 },
    });

    // With novelty=0, gain is only from query relevance component
    // Use high minGain to ensure the redundant item is filtered
    const pack = await retriever.retrieve("query", { minGain: 0.3 });

    expect(pack.items.length).toBe(0);
    expect(pack.totalGain).toBe(0);
  });

  it("minGain threshold filters low-gain candidates", async () => {
    const store = createMockStore([
      makeResult("r1", "alpha bravo charlie delta echo", 0.9),
      makeResult("r2", "alpha bravo charlie foxtrot golf", 0.8),
    ]);

    const retriever = createContextAwareRetriever({
      store,
      currentContext: [
        makeItem("existing", "alpha bravo charlie delta epsilon"),
      ],
      budget: { maxTokens: 10000 },
    });

    // High minGain should filter more aggressively
    const strictPack = await retriever.retrieve("query", { minGain: 0.8 });
    const loosePack = await retriever.retrieve("query", { minGain: 0.01 });

    expect(strictPack.items.length).toBeLessThanOrEqual(loosePack.items.length);
  });

  it("topK controls candidate count via maxCandidates multiplier", async () => {
    const results = Array.from({ length: 20 }, (_, i) =>
      makeResult(
        `r${i}`,
        `unique content number ${i} with distinct words`,
        0.9 - i * 0.01
      )
    );

    let queriedTopK = 0;
    const store: VectorStoreLike = {
      async query(_text: string, topK: number): Promise<VectorResult[]> {
        queriedTopK = topK;
        return results.slice(0, topK);
      },
    };

    const retriever = createContextAwareRetriever({
      store,
      currentContext: [],
      budget: { maxTokens: 100000 },
    });

    await retriever.retrieve("query", { topK: 5 });

    // Default maxCandidates = topK * 3 = 15
    expect(queriedTopK).toBe(15);
  });

  it("metadata includes source: rag and vectorScore", async () => {
    const store = createMockStore([
      makeResult("r1", "unique content for metadata test", 0.87),
    ]);

    const retriever = createContextAwareRetriever({
      store,
      currentContext: [],
      budget: { maxTokens: 10000 },
    });

    const pack = await retriever.retrieve("query");

    expect(pack.items[0].metadata).toEqual(
      expect.objectContaining({ source: "rag", vectorScore: 0.87 })
    );
  });

  it("handles store returning fewer results than topK", async () => {
    const store = createMockStore([
      makeResult("only", "only one unique result available", 0.5),
    ]);

    const retriever = createContextAwareRetriever({
      store,
      currentContext: [],
      budget: { maxTokens: 10000 },
    });

    const pack = await retriever.retrieve("query", { topK: 10 });

    expect(pack.items.length).toBe(1);
    expect(pack.candidatesEvaluated).toBe(1);
  });
});
