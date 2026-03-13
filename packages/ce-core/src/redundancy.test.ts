import { describe, expect, it, vi } from "vitest";
import { eliminateRedundancy, type EmbeddingProvider } from "./redundancy";
import type { ContextItem } from "./types";

class MessyProvider implements EmbeddingProvider {
  async embed(texts: string[]): Promise<number[][]> {
    return texts.map((text) => {
      if (text === "zero") return [0, 0, 0];
      if (text === "identical-1") return [0.5, 0.5, 0.5];
      if (text === "identical-2") return [0.5, 0.5, 0.5];
      if (text === "opposite-1") return [1, -1, 1];
      if (text === "opposite-2") return [-1, 1, -1];
      // fallback unique vectors
      return [Math.random(), Math.random(), Math.random()];
    });
  }
}

describe("eliminateRedundancy - Edge Cases", () => {
  it("handles empty items array gracefully", async () => {
    const provider = new MessyProvider();
    const result = await eliminateRedundancy([], { provider });
    expect(result).toEqual([]);
  });

  it("handles zero-magnitude vectors without NaN/Infinity issues", async () => {
    const provider = new MessyProvider();
    const items: ContextItem[] = [
      { id: "1", content: "zero", recency: 1 },
      { id: "2", content: "zero", recency: 2 },
    ];
    // Cosine similarity with a zero vector should be 0.
    const result = await eliminateRedundancy(items, { provider, similarityThreshold: 0.5 });
    
    // Since similarity is 0 (below 0.5), they should NOT cluster, both survive
    expect(result.length).toBe(2);
  });

  it("handles perfectly identical vectors and resolves ties via priority", async () => {
    const provider = new MessyProvider();
    const items: ContextItem[] = [
      { id: "1", content: "identical-1", recency: 5, priority: 10 },
      { id: "2", content: "identical-2", recency: 5, priority: 20 }, // Same recency, higher priority
      { id: "3", content: "identical-1", recency: 5, priority: 5 },
    ];
    const result = await eliminateRedundancy(items, { provider, similarityThreshold: 0.99 });
    
    // Should cluster into 1 group, keep the one with highest priority (id "2")
    expect(result.length).toBe(1);
    expect(result[0].id).toBe("2");
  });

  it("handles opposite vectors (negative cosine similarity)", async () => {
    const provider = new MessyProvider();
    const items: ContextItem[] = [
      { id: "1", content: "opposite-1", recency: 1 },
      { id: "2", content: "opposite-2", recency: 2 },
    ];
    // similarity should be -1.0
    const result = await eliminateRedundancy(items, { provider, similarityThreshold: 0.0 });
    
    // -1.0 is less than 0.0 threshold, so they should not cluster
    expect(result.length).toBe(2);
  });

  it("does not mutate original items array", async () => {
    const provider = new MessyProvider();
    const items: ContextItem[] = [
      { id: "1", content: "identical-1", recency: 1 },
      { id: "2", content: "identical-2", recency: 2 },
    ];
    const originalLength = items.length;
    await eliminateRedundancy(items, { provider });
    expect(items.length).toBe(originalLength);
  });

  it("supports summarize strategy fallback to recency when LLM is unmocked", async () => {
    const provider = new MessyProvider();
    const items: ContextItem[] = [
      { id: "1", content: "identical-1", recency: 10 },
      { id: "2", content: "identical-2", recency: 50 },
    ];
    const result = await eliminateRedundancy(items, { provider, strategy: "summarize" });
    
    // In our rudimentary fallback for 'summarize', it uses best recency
    expect(result.length).toBe(1);
    expect(result[0].id).toBe("2");
  });
});
